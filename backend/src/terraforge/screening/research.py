from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any

from terraforge.persistence.local import atomic_write_text
from terraforge.settings import Settings

from .models import CandidateSite, SiteEvidence, SourceCitation, utc_now

CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
PERMIT_SCORES = {
    "explicit_by_right": 95,
    "administrative_or_special_review": 70,
    "discretionary_multi_agency": 40,
    "moratorium_or_prohibition": 0,
    "unknown": None,
}
INFRASTRUCTURE_SCORES = {
    "established": 90,
    "documented": 70,
    "limited": 35,
    "unknown": None,
}


class GroundedSiteResearch:
    """Two-stage research: grounded retrieval, then schema-constrained fact extraction."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._cache_dir = (settings.terraforge_data_dir / "cache" / "site-research").resolve()
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def ready(self) -> bool:
        return settings_key(self.settings) is not None

    async def enrich(self, site: CandidateSite) -> CandidateSite:
        if site.catalog:
            return site
        if not self.ready:
            site.warnings.append("Grounded site research requires GOOGLE_API_KEY.")
            return site
        path = self._cache_path(site)
        if path.exists() and time.time() - path.stat().st_mtime <= CACHE_TTL_SECONDS:
            self._apply_cached(site, json.loads(path.read_text(encoding="utf-8")))
            return site
        if path.exists():
            site.warnings.append("Cached site intelligence was stale and was not used.")
        try:
            evidence, citations = await asyncio.to_thread(self._research, site)
        except Exception as exc:  # noqa: BLE001 -- secondary provider failure is non-fatal
            site.warnings.append(f"Grounded site research was unavailable: {type(exc).__name__}")
            return site
        self._apply_evidence(site, evidence, citations)
        await atomic_write_text(
            path,
            json.dumps(
                {
                    "evidence": evidence.model_dump(mode="json"),
                    "citations": [item.model_dump(mode="json") for item in citations],
                    "retrieved_at": utc_now().isoformat(),
                },
                indent=2,
                default=str,
            ),
        )
        return site

    def _cache_path(self, site: CandidateSite):
        cache_key = hashlib.sha256(
            f"{site.name}|{site.metro}|{site.state}|{site.latitude:.5f}|{site.longitude:.5f}".encode()
        ).hexdigest()
        return self._cache_dir / f"{cache_key}.json"

    @staticmethod
    def _apply_cached(site: CandidateSite, cached: dict[str, Any]) -> None:
        evidence_payload = cached.get("evidence")
        if evidence_payload is None and cached.get("summary"):
            evidence_payload = {"summary": cached["summary"]}
        evidence = SiteEvidence.model_validate(evidence_payload)
        citations = [SourceCitation.model_validate(item) for item in cached.get("citations", [])]
        GroundedSiteResearch._apply_evidence(site, evidence, citations)

    @staticmethod
    def _apply_evidence(
        site: CandidateSite, evidence: SiteEvidence, citations: list[SourceCitation]
    ) -> None:
        site.evidence = evidence
        site.research_summary = evidence.summary
        site.citations.extend(sorted(citations, key=lambda item: item.official, reverse=True))
        site.permitting_status = evidence.permitting_readiness
        site.permitting_score = PERMIT_SCORES[evidence.permitting_readiness]
        site.logistics_score = INFRASTRUCTURE_SCORES[evidence.infrastructure_readiness]
        if evidence.industrial_energy_price_cents_kwh is not None:
            site.industrial_energy_price_cents_kwh = evidence.industrial_energy_price_cents_kwh
        site.warnings.extend(evidence.validation_warnings)

    def _research(self, site: CandidateSite) -> tuple[SiteEvidence, list[SourceCitation]]:
        from google import genai

        client = genai.Client(api_key=settings_key(self.settings))
        try:
            narrative, citations = self._grounded_search(client, site)
            evidence = self._extract_facts(client, site, narrative, citations)
            return evidence, citations
        finally:
            client.close()

    def _grounded_search(self, client, site: CandidateSite) -> tuple[str, list[SourceCitation]]:
        from google.genai import types

        prompt = (
            f"Research {site.name} near {site.metro}, {site.state} as a possible data-center site. "
            "Prioritize current official municipal, county, state, regulator, electric utility, water-provider, "
            "airport, and infrastructure-operator sources. Summarize only cited facts about the permitting path, "
            "electricity price or tariff context, water constraints, major transport access, workforce, and fiber "
            "or data-center ecosystem. Explicitly mark unknowns. Never claim capacity, permits, incentives, or water "
            "rights are guaranteed."
        )
        response = client.models.generate_content(
            model=self.settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())]
            ),
        )
        narrative = response.text or "Grounded research returned no narrative."
        return narrative, self._grounding_citations(response)

    def _extract_facts(
        self,
        client,
        site: CandidateSite,
        narrative: str,
        citations: list[SourceCitation],
    ) -> SiteEvidence:
        from google.genai import types

        sources = "\n".join(
            f"[{index}] {citation.title} | {citation.url} | {citation.fact}"
            for index, citation in enumerate(citations, start=1)
        )
        prompt = f"""Validate and extract typed site-screening facts for {site.name}.

Grounded narrative:
{narrative}

Retrieved citations:
{sources or "No citations were returned."}

Rules:
- Use only claims supported by the retrieved citations.
- Every fact source_url must exactly match one retrieved URL.
- Set permitting_readiness to explicit_by_right, administrative_or_special_review,
  discretionary_multi_agency, moratorium_or_prohibition, or unknown.
- Set infrastructure_readiness to established, documented, limited, or unknown.
- Return an electricity price only if a cited source gives an applicable numeric cents/kWh value.
- Add a validation warning for missing or ambiguous power, water, permitting, or infrastructure evidence.
- Do not invent parcel-level zoning, utility capacity, water rights, permit timing, or incentives.
"""
        response = client.models.generate_content(
            model=self.settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=SiteEvidence,
                temperature=0,
            ),
        )
        evidence = response.parsed or SiteEvidence.model_validate_json(response.text or "{}")
        if not isinstance(evidence, SiteEvidence):
            evidence = SiteEvidence.model_validate(evidence)
        allowed_urls = {str(item.url) for item in citations}
        unsupported = [fact for fact in evidence.facts if str(fact.source_url) not in allowed_urls]
        if unsupported:
            raise ValueError("Structured extraction returned facts without retrieved citation URLs")
        return evidence

    @staticmethod
    def _grounding_citations(response) -> list[SourceCitation]:
        candidate = response.candidates[0] if response.candidates else None
        metadata = getattr(candidate, "grounding_metadata", None) if candidate else None
        fact_by_chunk: dict[int, str] = {}
        for support in getattr(metadata, "grounding_supports", None) or []:
            segment = getattr(support, "segment", None)
            fact = (getattr(segment, "text", None) or "").strip()
            for index in getattr(support, "grounding_chunk_indices", None) or []:
                if fact:
                    fact_by_chunk[int(index)] = fact[:500]
        citations: list[SourceCitation] = []
        for index, chunk in enumerate(getattr(metadata, "grounding_chunks", None) or []):
            web = getattr(chunk, "web", None)
            url = getattr(web, "uri", None) if web else None
            title = getattr(web, "title", None) if web else None
            if not url:
                continue
            citations.append(
                SourceCitation(
                    title=title or "Grounded source",
                    url=url,
                    publisher=(title or "Grounded web source")[:120],
                    fact=fact_by_chunk.get(
                        index, "Supports the grounded site-intelligence summary."
                    ),
                    official=".gov" in url.lower() or ".us" in url.lower(),
                )
            )
        return sorted(citations[:12], key=lambda item: item.official, reverse=True)


def settings_key(settings: Settings) -> str | None:
    if settings.google_api_key and settings.google_api_key.get_secret_value():
        return settings.google_api_key.get_secret_value()
    return None

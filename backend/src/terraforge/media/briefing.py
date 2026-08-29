from __future__ import annotations

from terraforge.contracts.models import RunRecord


def _clean(value: object, limit: int = 700) -> str:
    return " ".join(str(value).split())[:limit]


def build_briefing_prompt(record: RunRecord) -> str:
    """Build a restrained communication prompt from validated run outputs only."""
    specification = record.research_spec
    region = (
        specification.region
        if specification
        else record.study_area.label
        if record.study_area and record.study_area.label
        else "the selected habitat study area"
    )
    habitat = specification.habitat_type.replace("_", " ") if specification else "habitat"
    metric_lines: list[str] = []
    for key, value in record.metrics.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        metric_lines.append(f"{_clean(key, 80)}: {value:.3g}")
        if len(metric_lines) == 7:
            break
    metrics = "; ".join(metric_lines) or "No quantitative signal should be visualized."
    summary = _clean(record.final_summary or "No validated summary is available.")
    return (
        "Create an 8-second, 16:9, photorealistic but scientifically restrained "
        f"environmental field-briefing visual for {region}, focused on {habitat}. "
        "Begin with a calm satellite-style aerial view, then transition smoothly to "
        "field-scale ecological details appropriate to that habitat. Show only subtle, "
        "plausible environmental conditions; do not dramatize change. "
        f"Validated research context: {summary} Quantitative context: {metrics}. "
        "This is an illustrative communication asset, not evidence. Do not invent or "
        "identify species, imply causation, or show people, property damage, disasters, "
        "written text, numbers, charts, labels, borders, maps, logos, or watermarks. "
        "Use natural ambient sound only, with no narration or dialogue."
    )

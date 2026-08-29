from __future__ import annotations

import asyncio

import httpx


async def get_with_retry(
    url: str, *, params: dict | None = None, timeout: float = 60, attempts: int = 3
) -> httpx.Response:
    last_error: Exception | None = None
    require_identity_encoding = False
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout),
        follow_redirects=True,
        headers={"User-Agent": "ThermaSite/0.1"},
    ) as client:
        for attempt in range(attempts):
            try:
                headers = {"Accept-Encoding": "identity"} if require_identity_encoding else None
                response = await client.get(url, params=params, headers=headers)
                if response.status_code == 429 or response.status_code >= 500:
                    response.raise_for_status()
                response.raise_for_status()
                if not response.content:
                    raise ValueError("Authoritative source returned an empty response")
                return response
            except httpx.DecodingError as exc:
                # Some public scientific APIs intermittently label an uncompressed body
                # as gzip/deflate. Ask for an identity response on bounded retries.
                require_identity_encoding = True
                last_error = exc
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.35 * (2**attempt))
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.35 * (2**attempt))
    raise RuntimeError(f"Source request failed after {attempts} attempts: {last_error}")

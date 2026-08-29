from __future__ import annotations

import asyncio
import ipaddress
from urllib.parse import urlparse

import httpx


def validate_webhook_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Notification webhooks must use a public HTTPS URL")
    if parsed.hostname.lower() in {"localhost", "localhost.localdomain"}:
        raise ValueError("Local webhook targets are not allowed")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return
    if not address.is_global:
        raise ValueError("Private, loopback, and link-local webhook targets are not allowed")


async def deliver_webhook(
    url: str,
    payload: dict,
    timeout: float = 15,
    attempts: int = 3,
    idempotency_key: str | None = None,
) -> dict:
    target_host = urlparse(url).hostname or "unknown"
    history: list[dict] = []
    try:
        validate_webhook_url(url)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            for attempt in range(1, max(1, attempts) + 1):
                try:
                    response = await client.post(
                        url,
                        json=payload,
                        headers={"Idempotency-Key": idempotency_key} if idempotency_key else None,
                    )
                    history.append({"attempt": attempt, "http_status": response.status_code})
                    if response.is_success:
                        return {
                            "status": "delivered",
                            "target_host": target_host,
                            "http_status": response.status_code,
                            "attempt_count": attempt,
                            "attempts": history,
                            "idempotency_key": idempotency_key,
                        }
                    if response.status_code < 500 and response.status_code != 429:
                        break
                except httpx.HTTPError as exc:
                    history.append({"attempt": attempt, "error": type(exc).__name__})
                if attempt < attempts:
                    await asyncio.sleep(0.25 * 2 ** (attempt - 1))
        return {
            "status": "failed",
            "target_host": target_host,
            "attempt_count": len(history),
            "attempts": history,
            "idempotency_key": idempotency_key,
        }
    except (httpx.HTTPError, ValueError) as exc:
        return {
            "status": "failed",
            "target_host": target_host,
            "error": type(exc).__name__,
            "attempt_count": len(history),
            "attempts": history,
            "idempotency_key": idempotency_key,
        }

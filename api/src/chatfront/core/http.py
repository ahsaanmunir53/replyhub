"""Outbound HTTP: one place for timeouts, retries with backoff and clear errors."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Mapping
from typing import Any

import httpx

from chatfront.core.errors import AppError

log = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


def _detail(response: httpx.Response) -> str:
    """The provider's own error code and words (Meta: code, subcode, message), so a failure
    says why; long digit runs (phone numbers, ids) are masked."""
    try:
        body = response.json()
    except ValueError:
        return ""
    if not isinstance(body, dict):
        return ""
    error = body.get("error")
    if not isinstance(error, dict):  # OpenAI-style hosts: a string, or "detail"/"message"
        text = error if isinstance(error, str) else body.get("detail") or body.get("message")
        words = re.sub(r"\d{6,}", "#", str(text or ""))[:160]
        return f" ({words})" if words else ""
    parts = [str(error.get(k)) for k in ("code", "error_subcode") if error.get(k) is not None]
    words = re.sub(r"\d{6,}", "#", str(error.get("message", "")))[:160]
    return f" ({'/'.join(parts)}: {words})" if parts or words else ""


class UpstreamError(AppError):
    """A call to another service failed; `retryable` says whether trying again could help."""

    status_code = 502

    def __init__(self, service: str, message: str, *, status: int | None, retryable: bool) -> None:
        super().__init__("upstream_error", f"{service}: {message}")
        self.service = service
        self.status = status
        self.retryable = retryable


async def request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    service: str,
    retries: int = 2,
    backoff_seconds: float = 0.5,
    json: Any = None,
    content: bytes | None = None,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, str] | None = None,
) -> httpx.Response:
    """Send a request, retrying timeouts and retryable statuses with exponential backoff.

    Only pass retries > 0 for requests that are safe to repeat.
    """
    attempt = 0
    while True:
        try:
            response = await client.request(
                method, url, json=json, content=content, headers=headers, params=params
            )
        except httpx.TransportError as exc:
            error = UpstreamError(service, type(exc).__name__, status=None, retryable=True)
        else:
            if response.is_success:
                return response
            retryable = response.status_code in RETRYABLE_STATUS
            error = UpstreamError(
                service,
                f"HTTP {response.status_code}{_detail(response)}",
                status=response.status_code,
                retryable=retryable,
            )
        if not error.retryable or attempt >= retries:
            raise error
        delay = backoff_seconds * (2**attempt)
        if error.status == 429:  # a rate limit says when to come back; wait that long, briefly
            delay = max(delay, MIN_RATE_WAIT, _retry_after(response, error.message))
        log.warning("%s failed (%s), retrying in %.1fs", service, error.message, delay)
        await asyncio.sleep(delay)
        attempt += 1


_TRY_AGAIN = re.compile(r"try again in (?:(\d+)m)?([\d.]+)s", re.I)
MIN_RATE_WAIT = 1.2  # free plans such as Mistral's allow one request a second
MAX_RATE_WAIT = 8.0  # longer than this, the next endpoint answers instead


def _retry_after(response: httpx.Response, message: str) -> float:
    """Seconds a rate-limited service asks to wait, from Retry-After or its message, capped."""
    header = response.headers.get("retry-after", "")
    try:
        wait = float(header)
    except ValueError:
        found = _TRY_AGAIN.search(message)
        wait = (int(found.group(1) or 0) * 60 + float(found.group(2))) if found else 0.0
    return min(wait, MAX_RATE_WAIT)

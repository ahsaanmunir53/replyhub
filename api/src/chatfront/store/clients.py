"""Reading orders from the business's store with its read-only key: Shopify's Admin API and
WooCommerce's REST API. Only what the report needs is kept: number, time, total, currency,
status, whether it is cash on delivery, and whether it went out. No customer details.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpcore
import httpx

from chatfront.core.errors import AppError
from chatfront.core.http import request
from chatfront.core.money import to_minor

SHOPIFY, WOOCOMMERCE = "shopify", "woocommerce"
PLATFORMS = (SHOPIFY, WOOCOMMERCE)
SHOPIFY_API = "2024-10"
PAGE = 100
MAX_PAGES = 5  # one sync reads at most 500 orders; the next picks up the rest
_SHOPIFY_HOST = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}\.myshopify\.com$")


class StoreError(AppError):
    """The store could not be read: a wrong address or key, or the store is down."""

    def __init__(self, message: str) -> None:
        super().__init__("store_error", message)


@dataclass(frozen=True, slots=True)
class StoreOrderData:
    external_id: str
    number: str
    placed_at: datetime
    total: int  # minor units
    currency: str
    status: str  # pending | paid | cancelled | refunded
    cod: bool
    fulfilled: bool


def normal_url(platform: str, url: str) -> str:
    """The store's base address, https only. Shopify must be its myshopify.com address."""
    raw = url.strip().rstrip("/")
    if "://" not in raw:
        raw = f"https://{raw}"
    parts = urlsplit(raw)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host or parts.username or parts.password or parts.port:
        raise StoreError("The store address must be a plain https address")
    if platform == SHOPIFY:
        if not _SHOPIFY_HOST.match(host):
            raise StoreError("Use the store's myshopify.com address, e.g. mystore.myshopify.com")
        return f"https://{host}"
    path = parts.path.rstrip("/")
    return f"https://{host}{path}"


async def check_public(url: str) -> None:
    """Refuse an address that points inside a private network (the server must never be used
    to reach its own neighbours)."""
    host = urlsplit(url).hostname or ""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise StoreError("The store address could not be found") from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            raise StoreError("The store address is not a public website")


class PublicOnlyBackend(httpcore.AsyncNetworkBackend):
    """Connects only to public addresses, checked at the moment of connecting, so a store
    address that resolves to a public IP when saved and a private one later (DNS rebinding)
    still cannot reach the server's own network. TLS still checks the store's own name."""

    def __init__(self) -> None:
        self._inner = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 - httpcore's interface
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        loop = asyncio.get_running_loop()
        try:
            infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise httpcore.ConnectError(f"cannot resolve {host}") from exc
        addresses = [str(info[4][0]) for info in infos]
        if not addresses or not all(ipaddress.ip_address(a).is_global for a in addresses):
            raise httpcore.ConnectError("the store address is not a public website")
        return await self._inner.connect_tcp(
            addresses[0], port, timeout, local_address, socket_options
        )

    async def connect_unix_socket(
        self,
        path: str,  # noqa: ARG002
        timeout: float | None = None,  # noqa: ARG002, ASYNC109
        socket_options: Iterable[Any] | None = None,  # noqa: ARG002
    ) -> httpcore.AsyncNetworkStream:
        raise httpcore.ConnectError("unix sockets are not stores")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def store_client() -> httpx.AsyncClient:
    """The client for reading stores: public addresses only, no proxy from the environment,
    short timeouts, and no redirects (a redirect could point anywhere)."""
    transport = httpx.AsyncHTTPTransport(trust_env=False, retries=0)
    transport._pool = httpcore.AsyncConnectionPool(
        ssl_context=httpx.create_ssl_context(),
        max_connections=10,
        network_backend=PublicOnlyBackend(),
    )
    return httpx.AsyncClient(
        transport=transport,
        timeout=httpx.Timeout(20.0, connect=10.0),
        follow_redirects=False,
        trust_env=False,
    )


def _when(value: str) -> datetime:
    placed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return placed if placed.tzinfo else placed.replace(tzinfo=UTC)


def _minor(amount: Any, digits: int) -> int:
    try:
        return int(to_minor(str(amount or "0"), digits))
    except AppError:
        return 0


def shopify_order(raw: dict[str, Any], digits: int) -> StoreOrderData:
    financial = str(raw.get("financial_status") or "pending")
    if raw.get("cancelled_at"):
        status = "cancelled"
    elif financial in ("refunded", "partially_refunded"):
        status = "refunded"
    elif financial in ("paid", "partially_paid"):
        status = "paid"
    else:
        status = "pending"
    gateways = " ".join(str(g) for g in raw.get("payment_gateway_names") or []).lower()
    return StoreOrderData(
        external_id=str(raw["id"]),
        number=str(raw.get("name") or raw.get("order_number") or raw["id"])[:40],
        placed_at=_when(str(raw["created_at"])),
        total=_minor(raw.get("total_price"), digits),
        currency=str(raw.get("currency") or "")[:3],
        status=status,
        cod="cash on delivery" in gateways or "cod" in gateways.split(),
        fulfilled=raw.get("fulfillment_status") == "fulfilled",
    )


_WOO_STATUS = {
    "completed": "paid",
    "processing": "paid",
    "cancelled": "cancelled",
    "failed": "cancelled",
    "refunded": "refunded",
}


def woo_order(raw: dict[str, Any], digits: int) -> StoreOrderData:
    cod = raw.get("payment_method") == "cod"
    status = _WOO_STATUS.get(str(raw.get("status")), "pending")
    if cod and status == "paid" and raw.get("status") == "processing":
        status = "pending"  # cash on delivery is not paid until it is delivered
    return StoreOrderData(
        external_id=str(raw["id"]),
        number=f"#{raw.get('number') or raw['id']}"[:40],
        placed_at=_when(str(raw.get("date_created_gmt") or raw["date_created"])),
        total=_minor(raw.get("total"), digits),
        currency=str(raw.get("currency") or "")[:3],
        status=status,
        cod=cod,
        fulfilled=raw.get("status") == "completed",
    )


async def fetch_orders(
    http: httpx.AsyncClient,
    platform: str,
    url: str,
    key: str,
    secret: str | None,
    since: datetime,
    digits: int,
) -> list[StoreOrderData]:
    """Orders changed since `since`, newest pages first, at most MAX_PAGES pages."""
    await check_public(url)
    found: list[StoreOrderData] = []
    try:
        if platform == SHOPIFY:
            params = {
                "status": "any",
                "limit": str(PAGE),
                "updated_at_min": since.isoformat(),
                "fields": "id,name,order_number,created_at,total_price,currency,"
                "financial_status,fulfillment_status,cancelled_at,payment_gateway_names",
            }
            next_url: str | None = f"{url}/admin/api/{SHOPIFY_API}/orders.json"
            for _ in range(MAX_PAGES):
                if next_url is None:
                    break
                response = await request(
                    http,
                    "GET",
                    next_url,
                    service="shopify",
                    headers={"X-Shopify-Access-Token": key},
                    params=params,
                )
                found += [shopify_order(o, digits) for o in response.json().get("orders", [])]
                next_url = response.links.get("next", {}).get("url")
                if next_url and urlsplit(next_url).hostname != urlsplit(url).hostname:
                    raise StoreError("The store sent a next page on another address")
                params = {}  # the next link carries them
            return found
        auth = httpx.BasicAuth(key, secret or "").auth_flow(httpx.Request("GET", url))
        header = next(auth).headers["Authorization"]
        for page in range(1, MAX_PAGES + 1):
            response = await request(
                http,
                "GET",
                f"{url}/wp-json/wc/v3/orders",
                service="woocommerce",
                headers={"Authorization": header},
                params={
                    "modified_after": since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
                    "dates_are_gmt": "true",
                    "per_page": str(PAGE),
                    "page": str(page),
                },
            )
            batch = response.json()
            if not isinstance(batch, list):
                raise StoreError("The store did not send a list of orders")
            found += [woo_order(o, digits) for o in batch]
            if len(batch) < PAGE:
                break
        return found
    except (KeyError, ValueError, TypeError) as exc:
        raise StoreError("The store's answer could not be read") from exc

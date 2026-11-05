"""Reading a website store's orders: addresses, Shopify and WooCommerce orders, owner words."""

from __future__ import annotations

import pytest

from chatfront.store import clients
from chatfront.store.service import asks


def test_store_addresses() -> None:
    shopify = clients.normal_url("shopify", "Gulmohar.myshopify.com/")
    assert shopify == "https://gulmohar.myshopify.com"
    assert (
        clients.normal_url("woocommerce", "shop.example.ae/store/")
        == "https://shop.example.ae/store"
    )
    for platform, url in (
        ("shopify", "gulmohar.example"),  # Shopify only by its myshopify.com address
        ("woocommerce", "http://shop.example.ae"),  # https only
        ("woocommerce", "https://user:pass@shop.example.ae"),
        ("woocommerce", "https://shop.example.ae:8443"),
    ):
        with pytest.raises(clients.StoreError):
            clients.normal_url(platform, url)


async def test_a_private_address_is_refused() -> None:
    with pytest.raises(clients.StoreError):
        await clients.check_public("https://127.0.0.1")


def test_shopify_orders() -> None:
    base = {"id": 7, "name": "#1007", "created_at": "2026-11-04T10:00:00+04:00", "currency": "AED"}
    paid = clients.shopify_order({**base, "total_price": "199.50", "financial_status": "paid"}, 2)
    assert (paid.total, paid.status, paid.cod, paid.fulfilled) == (19950, "paid", False, False)
    cod = clients.shopify_order(
        {**base, "total_price": "80", "payment_gateway_names": ["Cash on Delivery (COD)"]}, 2
    )
    assert (cod.status, cod.cod) == ("pending", True)
    gone = clients.shopify_order({**base, "cancelled_at": "2026-11-04T11:00:00Z"}, 2)
    assert gone.status == "cancelled"


def test_woocommerce_orders() -> None:
    raw = {"id": 9, "number": "9", "date_created_gmt": "2026-11-04T06:00:00", "total": "120.00"}
    cod = clients.woo_order({**raw, "status": "processing", "payment_method": "cod"}, 2)
    assert (cod.number, cod.status, cod.cod) == ("#9", "pending", True)  # not paid until delivered
    done = clients.woo_order({**raw, "status": "completed", "payment_method": "stripe"}, 2)
    assert (done.status, done.fulfilled, done.placed_at.tzinfo is not None) == ("paid", True, True)


@pytest.mark.parametrize(
    ("text", "asked"),
    [
        ("aaj ka scene?", "today"),
        ("Report", "today"),
        ("today's sales", "today"),
        ("pending COD", "cod"),
        ("kurta ki price 2900 karo", None),
    ],
)
def test_what_the_owner_asks(text: str, asked: str | None) -> None:
    assert asks(text) == asked

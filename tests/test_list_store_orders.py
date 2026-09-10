"""Contract tests for the HW1 additional tool, list_store_orders.

The gap it fills: SPEC.md AUTH-1 lets support view any store's orders, but no
starter tool exposed store-scoped listing. Conversation 8 of the Part B
session hit this wall.
"""

from __future__ import annotations

from agent import db
from agent.auth import AuthContext
from agent.tools import DEFAULT_ORDER_LIMIT, list_store_orders

SUPPORT = AuthContext(user_id=9501, role="support")
MERCHANT_2 = AuthContext(user_id=9002, role="merchant", store_id=2)
SHOPPER_1 = AuthContext(user_id=1, role="shopper")


def _store_name(store_id: int) -> str:
    with db.connection() as conn:
        return db.get_store(conn, store_id).name


def test_support_lists_any_store(world: dict) -> None:
    result = list_store_orders(SUPPORT, _store_name(1))
    assert result["ok"] is True
    assert result["store_id"] == 1
    assert 0 < result["count"] <= DEFAULT_ORDER_LIMIT
    assert result["count"] == len(result["orders"])
    ordered = [o["ordered_at"] for o in result["orders"]]
    assert ordered == sorted(ordered, reverse=True)  # newest first


def test_merchant_lists_own_store_only(world: dict) -> None:
    ok = list_store_orders(MERCHANT_2, _store_name(2))
    assert ok["ok"] is True and ok["store_id"] == 2

    denied = list_store_orders(MERCHANT_2, _store_name(1))
    assert denied == {
        "ok": False,
        "error": "permission_denied",
        "reason": denied["reason"],
    }
    assert "store 1" in denied["reason"]


def test_shopper_is_denied(world: dict) -> None:
    result = list_store_orders(SHOPPER_1, _store_name(1))
    assert result["error"] == "permission_denied"


def test_unknown_store_is_not_found(world: dict) -> None:
    result = list_store_orders(SUPPORT, "No Such Store 9999")
    assert result["error"] == "not_found"

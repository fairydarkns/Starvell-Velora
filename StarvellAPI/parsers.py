from __future__ import annotations

from domain.chat_models import ChatEntry, ChatThread
from domain.order_models import OrderContext, OrderProfile
from domain.user_models import UserProfile


def parse_account(page_payload: dict) -> tuple[UserProfile, str | None]:
    page = page_payload.get("pageProps") or {}
    return UserProfile.from_payload(page.get("user")), page.get("sid")


def parse_threads(rows: list[dict], current_user_id: int | None) -> list[ChatThread]:
    return [ChatThread.from_payload(item, current_user_id) for item in rows if isinstance(item, dict)]


def parse_thread_messages(rows: list[dict], thread_id: str) -> tuple[ChatEntry, ...]:
    return tuple(ChatEntry.from_payload(item, thread_id) for item in rows if isinstance(item, dict))


def parse_orders(rows: list[dict]) -> list[OrderProfile]:
    return [OrderProfile.from_payload(item) for item in rows if isinstance(item, dict)]


def parse_order_context(payload: dict) -> OrderContext:
    page = payload.get("pageProps") or {}
    order = OrderProfile.from_payload(page.get("order"))
    thread_id = (page.get("chat") or {}).get("id")
    messages = tuple(
        ChatEntry.from_payload(item, thread_id or "")
        for item in page.get("messages", [])
        if isinstance(item, dict)
    )
    current_user = UserProfile.from_payload(page.get("user")) if page.get("user") else None
    return OrderContext(order=order, thread_id=thread_id, messages=messages, current_user=current_user, raw_payload=dict(payload))

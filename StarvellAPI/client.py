from __future__ import annotations

from domain.chat_models import ChatEntry, ChatThread
from domain.order_models import OrderContext, OrderProfile
from domain.user_models import UserProfile

from .auth import fetch_identity
from .parsers import parse_order_context, parse_orders, parse_thread_messages, parse_threads
from .runtime_types import RuntimeSettings
from .transport import Transport


class StarvellClient:
    def __init__(self, settings: RuntimeSettings) -> None:
        self._settings = settings
        self._transport = Transport(settings)
        self._base_url = "https://starvell.com"
        self._api_url = f"{self._base_url}/api"

    async def open(self) -> None:
        await self._transport.open()

    async def close(self) -> None:
        await self._transport.close()

    async def whoami(self) -> tuple[UserProfile, str | None]:
        return await fetch_identity(self._transport)

    async def list_threads(self, *, offset: int = 0, limit: int = 50, current_user_id: int | None = None) -> list[ChatThread]:
        rows = await self._transport.request_json(
            "POST",
            f"{self._api_url}/chats/list",
            payload={"offset": offset, "limit": limit},
            referer=f"{self._base_url}/chat",
        )
        return parse_threads(rows if isinstance(rows, list) else [], current_user_id)

    async def read_thread(
        self,
        *,
        thread_id: str,
        counterpart_id: int,
        current_user_id: int | None,
        limit: int = 20,
    ) -> tuple[ChatThread, tuple[ChatEntry, ...]]:
        payload = await self._transport.request_json(
            "POST",
            f"{self._base_url}/api/bff/chat-page",
            payload={
                "interlocutorId": counterpart_id,
                "messagesListDto": {
                    "chatId": thread_id,
                    "limit": limit,
                },
            },
            referer=f"{self._base_url}/chat/{thread_id}",
        )
        thread_blob = (payload.get("chatResult") or payload.get("additionalData") or {}).get("chat") or {
            "id": thread_id,
            "participants": [],
        }
        thread = ChatThread.from_payload(thread_blob, current_user_id)
        items = (payload.get("messagesListResult") or {}).get("items", [])
        return thread, parse_thread_messages(items if isinstance(items, list) else [], thread.thread_id)

    async def send_message(self, *, thread_id: str, text: str) -> dict:
        return await self._transport.request_json(
            "POST",
            f"{self._api_url}/messages/send",
            payload={"chatId": thread_id, "content": text},
            referer=f"{self._base_url}/chat/{thread_id}",
        )

    async def mark_thread_seen(self, *, thread_id: str) -> None:
        await self._transport.request_json(
            "POST",
            f"{self._api_url}/chats/read",
            payload={"chatId": thread_id},
            referer=f"{self._base_url}/chat/{thread_id}",
            include_sid=True,
        )

    async def list_orders(self, *, status: str | None = None) -> list[OrderProfile]:
        payload: dict[str, dict[str, str]] = {"filter": {}}
        if status:
            payload["filter"]["status"] = status
        rows = await self._transport.request_json(
            "POST",
            f"{self._api_url}/orders/list",
            payload=payload,
            referer=f"{self._base_url}/account/sells",
        )
        return parse_orders(rows if isinstance(rows, list) else [])

    async def read_order(self, *, order_id: str) -> OrderContext:
        payload = await self._transport.next_data(
            f"order/{order_id}.json",
            query=f"?order_id={order_id}",
            include_sid=True,
        )
        return parse_order_context(payload)

    async def confirm_order(self, *, order_id: str) -> dict:
        return await self._transport.request_json(
            "POST",
            f"{self._api_url}/orders/confirm",
            payload={"orderId": order_id},
            referer=f"{self._base_url}/order/{order_id}",
            include_sid=True,
        )

    async def mark_seller_completed(self, *, order_id: str) -> dict:
        return await self._transport.request_json(
            "POST",
            f"{self._api_url}/orders/{order_id}/mark-seller-completed",
            payload={"id": order_id},
            referer=f"{self._base_url}/order/{order_id}",
            include_sid=True,
        )

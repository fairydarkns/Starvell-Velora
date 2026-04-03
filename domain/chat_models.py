from __future__ import annotations

from dataclasses import dataclass, field

from domain.common_models import to_dt, to_int, to_text
from domain.user_models import UserProfile


@dataclass(slots=True, frozen=True)
class ChatThread:
    thread_id: str = ""
    unread_count: int = 0
    counterpart_id: int | None = None
    counterpart: UserProfile | None = None
    last_message_id: str | None = None
    raw_payload: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: dict, current_user_id: int | None) -> "ChatThread":
        participants = [UserProfile.from_payload(item) for item in payload.get("participants", [])]
        counterpart = None
        for participant in participants:
            if participant.user_id is not None and participant.user_id != current_user_id:
                counterpart = participant
                break
        last_message = payload.get("lastMessage") or {}
        return cls(
            thread_id=str(payload.get("id") or ""),
            unread_count=int(payload.get("unreadMessageCount") or payload.get("unreadCount") or 0),
            counterpart_id=counterpart.user_id if counterpart else None,
            counterpart=counterpart,
            last_message_id=to_text(last_message.get("id")),
            raw_payload=dict(payload),
        )


@dataclass(slots=True, frozen=True)
class ChatEntry:
    message_id: str = ""
    thread_id: str = ""
    author_id: int | None = None
    author: UserProfile | None = None
    text: str | None = None
    event_type: str = "MESSAGE"
    notification_type: str | None = None
    linked_order_id: str | None = None
    created_at: object | None = None
    raw_payload: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: dict, thread_id: str) -> "ChatEntry":
        metadata = payload.get("metadata") or {}
        order = payload.get("order") or {}
        return cls(
            message_id=str(payload.get("id") or ""),
            thread_id=thread_id,
            author_id=to_int(payload.get("authorId")),
            author=UserProfile.from_payload(payload.get("author")) if payload.get("author") else None,
            text=to_text(payload.get("content") or payload.get("text")),
            event_type=to_text(payload.get("type")) or "MESSAGE",
            notification_type=to_text(metadata.get("notificationType")),
            linked_order_id=to_text(metadata.get("orderId") or order.get("id")),
            created_at=to_dt(payload.get("createdAt") or payload.get("updatedAt")),
            raw_payload=dict(payload),
        )

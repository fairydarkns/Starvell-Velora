from __future__ import annotations

from dataclasses import dataclass, field

from domain.common_models import to_dt, to_int, to_text


@dataclass(slots=True, frozen=True)
class UserProfile:
    user_id: int | None = None
    username: str | None = None
    display_name: str | None = None
    roles: tuple[str, ...] = ()
    is_online: bool | None = None
    last_seen_at: object | None = None
    raw_payload: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: dict | None) -> "UserProfile":
        payload = payload or {}
        return cls(
            user_id=to_int(payload.get("id")),
            username=to_text(payload.get("username")),
            display_name=to_text(payload.get("username"))
            or to_text(payload.get("nickname"))
            or to_text(payload.get("name")),
            roles=tuple(str(item) for item in payload.get("roles", []) if item is not None),
            is_online=payload.get("isOnline"),
            last_seen_at=to_dt(payload.get("lastOnlineAt")),
            raw_payload=dict(payload),
        )

    @property
    def label(self) -> str:
        return self.display_name or (f"ID {self.user_id}" if self.user_id is not None else "Unknown user")

from __future__ import annotations

from domain.user_models import UserProfile

from .parsers import parse_account
from .transport import Transport


async def fetch_identity(transport: Transport) -> tuple[UserProfile, str | None]:
    payload = await transport.next_data("index.json")
    profile, sid = parse_account(payload)
    transport.remember_sid(sid)
    return profile, sid

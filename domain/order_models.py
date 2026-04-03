from __future__ import annotations

from dataclasses import dataclass, field

from domain.chat_models import ChatEntry
from domain.common_models import to_dt, to_int, to_text
from domain.user_models import UserProfile


@dataclass(slots=True, frozen=True)
class OfferProfile:
    offer_id: int | None = None
    title: str | None = None
    description: str | None = None
    game_name: str | None = None
    category_name: str | None = None
    subcategory_name: str | None = None
    raw_payload: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: dict | None) -> "OfferProfile":
        payload = payload or {}
        localized = (payload.get("descriptions") or {}).get("rus") or {}
        return cls(
            offer_id=to_int(payload.get("id")),
            title=to_text(localized.get("briefDescription")) or to_text(payload.get("name")),
            description=to_text(localized.get("description")) or to_text(payload.get("description")),
            game_name=to_text((payload.get("game") or {}).get("name")),
            category_name=to_text((payload.get("category") or {}).get("name")),
            subcategory_name=to_text((payload.get("subCategory") or {}).get("name")),
            raw_payload=dict(payload),
        )


@dataclass(slots=True, frozen=True)
class OrderProfile:
    order_id: str = ""
    status: str = "UNKNOWN"
    buyer_id: int | None = None
    seller_id: int | None = None
    quantity: int | None = None
    total_price_minor: int | None = None
    buyer: UserProfile | None = None
    seller: UserProfile | None = None
    offer: OfferProfile | None = None
    created_at: object | None = None
    updated_at: object | None = None
    raw_payload: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: dict | None) -> "OrderProfile":
        payload = payload or {}
        return cls(
            order_id=str(payload.get("id") or ""),
            status=to_text(payload.get("status")) or "UNKNOWN",
            buyer_id=to_int(payload.get("buyerId")),
            seller_id=to_int(payload.get("sellerId")),
            quantity=to_int(payload.get("quantity")),
            total_price_minor=to_int(payload.get("totalPrice") or payload.get("basePrice")),
            buyer=UserProfile.from_payload(payload.get("buyer") or payload.get("user"))
            if payload.get("buyer") or payload.get("user")
            else None,
            seller=UserProfile.from_payload(payload.get("seller")) if payload.get("seller") else None,
            offer=OfferProfile.from_payload(
                payload.get("offerDetails") or payload.get("listing") or payload.get("offer")
            )
            if payload.get("offerDetails") or payload.get("listing") or payload.get("offer")
            else None,
            created_at=to_dt(payload.get("createdAt")),
            updated_at=to_dt(payload.get("updatedAt")),
            raw_payload=dict(payload),
        )

    @property
    def short_code(self) -> str:
        compact = self.order_id.replace("-", "")
        return compact[-8:].upper() if len(compact) >= 8 else compact.upper()

    @property
    def total_price(self) -> float | None:
        if self.total_price_minor is None:
            return None
        return self.total_price_minor / 100


@dataclass(slots=True, frozen=True)
class OrderContext:
    order: OrderProfile = field(default_factory=OrderProfile)
    thread_id: str | None = None
    messages: tuple[ChatEntry, ...] = ()
    current_user: UserProfile | None = None
    raw_payload: dict = field(default_factory=dict, repr=False)

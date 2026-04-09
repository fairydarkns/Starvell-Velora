"""Утилиты для экспорта и создания лотов Starvell."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _price_to_string(value: Any) -> str:
    if value is None:
        return "0"
    if isinstance(value, str):
        return value.strip() or "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        text = f"{value:.1f}".rstrip("0").rstrip(".")
        return text or "0"
    return str(value)


def _extract_descriptions(data: Mapping[str, Any]) -> dict[str, Any]:
    descriptions = deepcopy(dict(data.get("descriptions") or {}))
    rus = deepcopy(dict(descriptions.get("rus") or {}))
    brief = str(rus.get("briefDescription") or data.get("title") or data.get("name") or "").strip()
    description = str(rus.get("description") or brief).strip()
    descriptions["rus"] = {
        "briefDescription": brief,
        "description": description,
    }
    return descriptions


def _extract_basic_attributes(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_attributes = data.get("basicAttributes")
    if not isinstance(raw_attributes, list):
        raw_attributes = data.get("attributes") or []

    result: list[dict[str, Any]] = []
    for item in raw_attributes:
        if not isinstance(item, Mapping):
            continue
        attr_id = item.get("id")
        option_id = item.get("optionId")
        if not option_id and isinstance(item.get("value"), Mapping):
            option_id = item["value"].get("id")
        if attr_id and option_id:
            result.append({"id": attr_id, "optionId": option_id})
    return result


def _extract_numeric_attributes(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_numeric = data.get("numericAttributes") or []
    result: list[dict[str, Any]] = []
    for item in raw_numeric:
        if not isinstance(item, Mapping):
            continue
        attr_id = item.get("id")
        numeric_value = item.get("numericValue")
        if attr_id is None or numeric_value is None:
            continue
        result.append({"id": attr_id, "numericValue": numeric_value})
    return result


def normalize_create_offer_payload(raw_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Собрать create-пейлоад Starvell из edit/public структуры."""
    payload = deepcopy(dict(raw_payload or {}))

    delivery_time = deepcopy(dict(payload.get("deliveryTime") or {}))
    delivery_from = deepcopy(dict(delivery_time.get("from") or {}))
    delivery_to = deepcopy(dict(delivery_time.get("to") or {}))
    if not delivery_from:
        delivery_from = {"unit": "MINUTES", "value": 1}
    if not delivery_to:
        delivery_to = deepcopy(delivery_from)

    normalized = {
        "type": payload.get("type") or "LOT",
        "categoryId": payload.get("categoryId"),
        "price": _price_to_string(payload.get("price")),
        "isActive": bool(payload.get("isActive", True)),
        "availability": _safe_int(payload.get("availability"), 1),
        "goods": deepcopy(list(payload.get("goods") or [])),
        "numericAttributes": _extract_numeric_attributes(payload),
        "postPaymentMessage": str(payload.get("postPaymentMessage") or ""),
        "deliveryTime": {
            "from": {
                "unit": delivery_from.get("unit") or "MINUTES",
                "value": _safe_int(delivery_from.get("value"), 1),
            },
            "to": {
                "unit": delivery_to.get("unit") or "MINUTES",
                "value": _safe_int(delivery_to.get("value"), _safe_int(delivery_from.get("value"), 1)),
            },
        },
        "descriptions": _extract_descriptions(payload),
        "basicAttributes": _extract_basic_attributes(payload),
    }

    if payload.get("instantDelivery") is not None:
        normalized["instantDelivery"] = bool(payload.get("instantDelivery"))

    if payload.get("subCategoryId") is not None:
        normalized["subCategoryId"] = payload.get("subCategoryId")

    if payload.get("minOrderCurrencyAmount") is not None:
        normalized["minOrderCurrencyAmount"] = payload.get("minOrderCurrencyAmount")

    return normalized


def build_export_record_from_edit_payload(
    lot_id: int | str,
    payload: Mapping[str, Any],
    *,
    title: str | None = None,
    url: str | None = None,
) -> dict[str, Any]:
    return {
        "source": {
            "mode": "own_edit_payload",
            "lot_id": str(lot_id),
            "title": title or "",
            "url": url or "",
        },
        "payload": normalize_create_offer_payload(payload),
    }


def extract_public_offer_from_next_data(data: Mapping[str, Any]) -> dict[str, Any]:
    page_props = dict((data or {}).get("pageProps") or {})
    bff = dict(page_props.get("bff") or {})
    candidates = (
        page_props.get("offer"),
        bff.get("offer"),
        page_props.get("listing"),
        bff.get("listing"),
    )
    for candidate in candidates:
        if isinstance(candidate, Mapping) and candidate:
            return dict(candidate)
    return {}


def build_export_record_from_public_offer(
    user_id: int | str,
    category: Mapping[str, Any],
    offer: Mapping[str, Any],
    offer_page: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    public_offer = dict(offer_page or {}) or dict(offer or {})
    merged = deepcopy(dict(public_offer))

    for key, value in dict(offer).items():
        if key not in merged or merged.get(key) in (None, "", [], {}):
            merged[key] = deepcopy(value)

    merged.setdefault("categoryId", category.get("id"))
    if not merged.get("subCategoryId") and isinstance(merged.get("subCategory"), Mapping):
        merged["subCategoryId"] = merged["subCategory"].get("id")

    source_offer_id = offer.get("id") or merged.get("id")
    source_title = (
        ((merged.get("descriptions") or {}).get("rus") or {}).get("briefDescription")
        or offer.get("title")
        or offer.get("name")
        or category.get("name")
    )

    return {
        "source": {
            "mode": "public_offer",
            "user_id": str(user_id),
            "lot_id": str(source_offer_id or ""),
            "title": str(source_title or ""),
            "url": f"https://starvell.com/offers/{source_offer_id}" if source_offer_id else "",
            "category_id": category.get("id"),
            "category_name": category.get("name"),
            "sub_category_id": (merged.get("subCategory") or {}).get("id") or merged.get("subCategoryId"),
            "sub_category_name": (merged.get("subCategory") or {}).get("name"),
        },
        "payload": normalize_create_offer_payload(merged),
    }


def extract_category_schema(category: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "categoryId": category.get("id"),
        "categoryName": category.get("name"),
        "gameId": category.get("gameId"),
        "filters": deepcopy(list(category.get("filters") or [])),
        "numericFilters": deepcopy(list(category.get("numericFilters") or [])),
    }

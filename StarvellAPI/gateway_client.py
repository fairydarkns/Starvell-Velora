"""Основной клиент API"""

import logging
from typing import Optional, List, Dict, Any

from .api_config import Config
from .session_manager import SessionManager
from .api_utils import BuildIdCache, extract_build_id, extract_sid_from_cookies
from .api_exceptions import NotFoundError

logger = logging.getLogger("API")


def _normalize_wallet_amount(value: Any) -> float:
    """Преобразовать копейки Starvell в рубли."""
    try:
        return float(value) / 100.0
    except (TypeError, ValueError):
        return 0.0


def _normalize_order_money(order: Dict[str, Any]) -> Dict[str, Any]:
    """Добавить к заказу нормализованные денежные поля, не ломая raw-структуру."""
    if not isinstance(order, dict):
        return order

    normalized = dict(order)
    for field in ("basePrice", "totalPrice", "price"):
        if field in normalized:
            raw_field = f"{field}Raw"
            rub_field = f"{field}Rub"
            normalized.setdefault(raw_field, normalized.get(field))
            normalized[rub_field] = _normalize_wallet_amount(normalized.get(raw_field))

    if "shortId" not in normalized or not normalized.get("shortId"):
        order_id = str(normalized.get("id", ""))
        clean_id = order_id.replace("-", "")
        normalized["shortId"] = clean_id[-8:].upper() if len(clean_id) >= 8 else order_id[:8].upper()

    normalized["displayAmountRub"] = (
        normalized.get("totalPriceRub")
        or normalized.get("basePriceRub")
        or normalized.get("priceRub")
        or 0.0
    )
    return normalized


def _normalize_profile_user(user_data: Dict[str, Any]) -> Dict[str, Any]:
    """Нормализовать профиль пользователя из Next Data."""
    if not isinstance(user_data, dict):
        return {}

    normalized = dict(user_data)
    normalized["nickname"] = (
        normalized.get("nickname")
        or normalized.get("username")
        or normalized.get("name")
    )
    normalized["verified"] = normalized.get("kycStatus") == "VERIFIED"
    normalized["rating"] = float(normalized.get("rating", 0) or 0)
    normalized["reviewsCount"] = int(normalized.get("reviewsCount", 0) or 0)
    return normalized

class StarAPI:
    """
    Главный класс для работы с Starvell API
    
    Пример использования:
        async with StarAPI(session_cookie="your_cookie") as api:
            user = await api.get_user_info()
            chats = await api.get_chats()
    """
    
    def __init__(
        self,
        session_cookie: str,
        user_agent: Optional[str] = None,
        timeout: Optional[int] = None,
    ):
        """
        Инициализация клиента
        
        Args:
            session_cookie: Cookie сессии пользователя
            user_agent: Кастомный User-Agent (опционально)
            timeout: Таймаут запросов в секундах (опционально)
        """
        self.config = Config(user_agent=user_agent, timeout=timeout)
        self.session = SessionManager(session_cookie, self.config)
        self._build_id_cache = BuildIdCache(ttl=self.config.BUILD_ID_CACHE_TTL)
        
    async def __aenter__(self):
        await self.session.start()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.session.close()
        
    async def close(self):
        """Закрыть сессию"""
        await self.session.close()
        
    # ==================== Внутренние методы ====================
    
    async def _get_build_id(self) -> str:
        """Получить build_id (с кэшированием)"""
        async def fetch():
            html = await self.session.get_text(
                f"{self.config.BASE_URL}/",
                headers={"accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
            )
            return extract_build_id(html)
            
        return await self._build_id_cache.get(fetch)
        
    async def _get_next_data(
        self,
        path: str,
        params: Optional[str] = None,
        include_sid: bool = False,
    ) -> dict:
        """
        Получить данные из Next.js Data API
        
        Args:
            path: Путь (например, "index.json" или "chat.json")
            params: Query параметры (например, "?offer_id=123")
            include_sid: Включить SID cookie в запрос
        """
        for attempt in range(2):
            try:
                build_id = await self._get_build_id()
                url = f"{self.config.BASE_URL}/_next/data/{build_id}/{path}"
                
                if params:
                    url += params
                    
                data = await self.session.get_json(
                    url,
                    referer=f"{self.config.BASE_URL}/",
                    headers={"x-nextjs-data": "1"},
                    include_sid=include_sid,
                )
                
                return data
                
            except NotFoundError:
                if attempt == 0:
                    # Build ID устарел, сбрасываем кэш
                    self._build_id_cache.reset()
                    continue
                raise
                
        raise RuntimeError("Не удалось получить Next.js данные")
        
    # ==================== Аутентификация ====================

    async def _get_user_profile_page(self, user_id: int | str) -> Dict[str, Any]:
        return await self._get_next_data(
            f"users/{user_id}.json",
            params=f"?user_id={user_id}",
        )

    @staticmethod
    def _extract_user_profile_user(page_props: Dict[str, Any]) -> Dict[str, Any]:
        bff = page_props.get("bff") or {}
        for candidate in (
            bff.get("user"),
            page_props.get("user"),
            page_props.get("foreignProfileUser"),
        ):
            if isinstance(candidate, dict) and candidate:
                return _normalize_profile_user(candidate)
        return {}

    @staticmethod
    def _extract_user_profile_categories(page_props: Dict[str, Any]) -> tuple[list[Dict[str, Any]], str]:
        bff = page_props.get("bff") or {}
        for key, source in (
            ("pageProps.bff.userProfileOffers", bff.get("userProfileOffers")),
            ("pageProps.userProfileOffers", page_props.get("userProfileOffers")),
            ("pageProps.categoriesWithOffers", page_props.get("categoriesWithOffers")),
        ):
            if isinstance(source, list):
                return source, key
        return [], "unknown"
    
    async def get_user_info(self) -> Dict[str, Any]:
        """
        Получить информацию о текущем пользователе
        
        Returns:
            dict: Информация о пользователе и статус авторизации
        """
        index_data = await self._get_next_data("index.json")
        index_page_props = index_data.get("pageProps", {})
        index_user = index_page_props.get("user") or {}

        # Получаем SID для дальнейших запросов.
        sid = index_page_props.get("sid")
        if sid:
            self.session.set_sid(sid)

        user = dict(index_user)
        theme = index_page_props.get("currentTheme")

        try:
            wallet_data = await self._get_next_data("wallet.json", include_sid=True)
            wallet_page_props = wallet_data.get("pageProps", {})
            wallet_user = wallet_page_props.get("user") or {}
            if wallet_user:
                user = dict(wallet_user)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Не удалось получить wallet.json, использую index.json для профиля: %s", exc)

        # Структура wallet.json отдает суммы в копейках.
        balance_payload = user.get("balance")
        rub_balance_raw = None
        if isinstance(balance_payload, dict):
            rub_balance_raw = balance_payload.get("rubBalance")
        if rub_balance_raw is None:
            rub_balance_raw = user.get("rubBalance", 0)

        user["balance"] = {
            "rubBalance": _normalize_wallet_amount(rub_balance_raw),
        }
        user["holdedAmount"] = _normalize_wallet_amount(user.get("holdedAmount", 0))
        user["verified"] = user.get("kycStatus") == "VERIFIED"

        return {
            "authorized": bool(user),
            "user": user,
            "sid": sid or self.session.get_sid(),
            "theme": theme,
        }
    
    async def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Получить профиль пользователя по ID
        
        Args:
            user_id: ID пользователя в Starvell
            
        Returns:
            dict: Данные профиля (nickname, name, id и др.) или None если не найден
        """
        try:
            data = await self._get_user_profile_page(user_id)
            page_props = data.get("pageProps", {})
            user_data = self._extract_user_profile_user(page_props)
            if user_data:
                return user_data
            return None
        except Exception as e:
            logger.debug(f"Не удалось получить профиль пользователя {user_id}: {e}")
            return None
        
    # ==================== Чаты ====================
    
    async def get_chats(self, offset: int = 0, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Получить список всех чатов
        
        Returns:
            list: Список чатов
        """
        data = await self.session.post_json(
            f"{self.config.API_URL}/chats/list",
            data={"offset": offset, "limit": limit},
            referer=f"{self.config.BASE_URL}/chat",
        )
        return data if isinstance(data, list) else []

    async def get_unread_chats(self, offset: int = 0, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Получить список непрочитанных чатов
        
        Returns:
            list: Список непрочитанных чатов
        """
        data = await self.session.post_json(
            f"{self.config.API_URL}/chats/list-unread",
            data={"offset": offset, "limit": limit},
            referer=f"{self.config.BASE_URL}/chat",
        )
        return data if isinstance(data, list) else []

    async def get_chat_page(
        self,
        chat_id: str,
        interlocutor_id: str,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """
        Получить полные данные страницы чата через BFF.
        
        Returns:
            dict: Ответ chat-page со списком сообщений и additionalData
        """
        return await self.session.post_json(
            f"{self.config.BASE_URL}/api/bff/chat-page",
            data={
                "interlocutorId": int(interlocutor_id),
                "messagesListDto": {
                    "chatId": chat_id,
                    "limit": limit,
                },
            },
            referer=f"{self.config.BASE_URL}/chat/{chat_id}",
        )
        
    async def get_messages(
        self,
        chat_id: str,
        interlocutor_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Получить сообщения из чата
        
        Args:
            chat_id: ID чата
            interlocutor_id: ID собеседника
            limit: Максимальное количество сообщений
            
        Returns:
            list: Список сообщений
        """
        data = await self.get_chat_page(chat_id, interlocutor_id, limit=limit)
        items = data.get("messagesListResult", {}).get("items", [])
        return items if isinstance(items, list) else []
        
    async def send_message(self, chat_id: str, content: str) -> Dict[str, Any]:
        """
        Отправить сообщение в чат
        
        Args:
            chat_id: ID чата
            content: Текст сообщения
            
        Returns:
            dict: Информация об отправленном сообщении
        """
        return await self.session.post_json(
            f"{self.config.API_URL}/messages/send",
            data={"chatId": chat_id, "content": content},
            referer=f"{self.config.BASE_URL}/chat/{chat_id}",
        )
    
    async def mark_chat_as_read(self, chat_id: str) -> bool:
        """
        Пометить чат как прочитанный
        
        Args:
            chat_id: ID чата
            
        Returns:
            bool: True если успешно
        """
        try:
            await self.session.post_json(
                f"{self.config.API_URL}/chats/read",
                data={"chatId": chat_id},
                referer=f"{self.config.BASE_URL}/chat/{chat_id}",
                include_sid=True,
            )
            return True
        except Exception as e:
            logger.debug(f"Не удалось пометить чат {chat_id} как прочитанный: {e}")
            return False
    
    async def find_chat_by_user_id(self, user_id: str) -> Optional[str]:
        """
        Найти ID чата с конкретным пользователем
        
        Args:
            user_id: ID пользователя для поиска
            
        Returns:
            str | None: ID чата если найден, иначе None
        """
        try:
            chats = await self.get_chats()
            
            for chat in chats:
                participants = chat.get("participants", [])
                for member in participants:
                    if str(member.get("id")) == str(user_id):
                        return chat.get("id")
            
            return None
        except Exception as e:
            logger.error(f"Ошибка поиска чата для пользователя {user_id}: {e}")
            return None
        
    # ==================== Заказы ====================
    
    async def get_sells(self) -> Dict[str, Any]:
        """
        Получить список продаж (только первые 20 через Next.js Data API)
        
        ⚠️ DEPRECATED: Используйте get_all_orders() для получения ВСЕХ заказов
        
        Returns:
            dict: Данные о продажах (ограничено 20 заказами)
        """
        return await self._get_next_data("account/sells.json")
    
    async def get_all_orders(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Получить ВСЕ заказы с информацией о покупателях
        
        Использует гибридный подход
        
        Args:
            status: Фильтр по статусу ("CREATED", "COMPLETED", "REFUND", "PRE_CREATED")
                   Если None - возвращает все заказы
        
        Returns:
            list: Список всех заказов с информацией о покупателях
        """
        payload = {"filter": {}}
        if status:
            payload["filter"]["status"] = status
        
        all_orders = await self.session.post_json(
            f"{self.config.API_URL}/orders/list",
            data=payload,
            referer=f"{self.config.BASE_URL}/account/sells",
        )
        
        if not isinstance(all_orders, list):
            all_orders = []
        
        try:
            data = await self._get_next_data("account/sells.json")
            page_props = data.get("pageProps", {})
            recent_orders = page_props.get("orders", [])
            
            user_map = {}
            for order in recent_orders:
                order_id = order.get("id")
                user = order.get("user")
                if order_id and user:
                    user_map[order_id] = user
            
            for order in all_orders:
                order_id = order.get("id")
                if order_id in user_map:
                    order["user"] = user_map[order_id]
        
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.debug(f"Не удалось обогатить заказы данными пользователей: {e}")

        return [_normalize_order_money(order) for order in all_orders if isinstance(order, dict)]
        
    async def refund_order(self, order_id: str) -> Dict[str, Any]:
        """
        Вернуть деньги за заказ
        
        Args:
            order_id: ID заказа
            
        Returns:
            dict: Результат операции
        """
        return await self.session.post_json(
            f"{self.config.API_URL}/orders/refund",
            data={"orderId": order_id},
            referer=f"{self.config.BASE_URL}/order/{order_id}",
            include_sid=True,
        )
        
    async def confirm_order(self, order_id: str) -> Dict[str, Any]:
        """
        Подтвердить заказ
        
        Args:
            order_id: ID заказа
            
        Returns:
            dict: Результат операции
        """
        return await self.session.post_json(
            f"{self.config.API_URL}/orders/confirm",
            data={"orderId": order_id},
            referer=f"{self.config.BASE_URL}/order/{order_id}",
            include_sid=True,
        )

    async def mark_seller_completed(self, order_id: str) -> Dict[str, Any]:
        """
        Отметить заказ выполненным со стороны продавца.
        
        Args:
            order_id: ID заказа
            
        Returns:
            dict: Результат операции
        """
        return await self.session.post_json(
            f"{self.config.API_URL}/orders/{order_id}/mark-seller-completed",
            data={"id": order_id},
            referer=f"{self.config.BASE_URL}/order/{order_id}",
            include_sid=True,
        )

    async def create_review_response(self, review_id: str, content: str, order_id: str) -> Dict[str, Any]:
        """
        Ответить на отзыв.

        Args:
            review_id: ID отзыва
            content: Текст ответа
            order_id: ID заказа для referer

        Returns:
            dict: Результат операции
        """
        return await self.session.post_json(
            f"{self.config.API_URL}/review-responses/create",
            data={"content": content, "reviewId": review_id},
            referer=f"{self.config.BASE_URL}/order/{order_id}",
            include_sid=True,
        )

    async def delete_review_response(self, review_response_id: str, order_id: str) -> Dict[str, Any]:
        """
        Удалить ответ на отзыв.

        Args:
            review_response_id: ID ответа на отзыв
            order_id: ID заказа для referer

        Returns:
            dict: Результат операции
        """
        return await self.session.post_json(
            f"{self.config.API_URL}/review-responses/{review_response_id}/delete",
            data={},
            referer=f"{self.config.BASE_URL}/order/{order_id}",
            include_sid=True,
        )
    
    async def get_order_details(self, order_id: str) -> Dict[str, Any]:
        """
        Получить детальную информацию о заказе
        
        Args:
            order_id: ID заказа (например, 019b95a8-df7d-683c-17a9-3889985947d6)
            
        Returns:
            dict: Полные данные заказа включая chat_id, buyer, lot и т.д.
        """
        data = await self._get_next_data(
            f"order/{order_id}.json",
            params=f"?order_id={order_id}",
            include_sid=True,
        )
        page_props = data.get("pageProps", {})
        if isinstance(page_props.get("order"), dict):
            page_props["order"] = _normalize_order_money(page_props["order"])
        bff = page_props.get("bff")
        if isinstance(bff, dict) and isinstance(bff.get("order"), dict):
            bff["order"] = _normalize_order_money(bff["order"])
        return data
        
    # ==================== Офферы ====================
    
    async def get_offer(self, offer_id: int) -> Dict[str, Any]:
        """
        Получить детальную информацию об оффере
        
        Args:
            offer_id: ID оффера
            
        Returns:
            dict: Данные об оффере
        """
        return await self._get_next_data(
            f"offers/{offer_id}.json",
            params=f"?offer_id={offer_id}",
            include_sid=True,
        )

    async def get_offer_edit_data(self, offer_id: int) -> Dict[str, Any]:
        """
        Получить payload лота для редактирования.
        """
        data = await self._get_next_data(
            f"offers/edit/{offer_id}.json",
            params=f"?offer_id={offer_id}",
            include_sid=True,
        )
        page_props = data.get("pageProps", {})
        offer = page_props.get("offer") or {}

        # В edit-странице Starvell возвращает attributes, а update ждёт basicAttributes.
        if "attributes" in offer and "basicAttributes" not in offer:
            offer["basicAttributes"] = offer.pop("attributes")

        offer.setdefault("numericAttributes", [])
        return offer

    async def update_offer(self, offer_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Обновить лот по полному payload.
        """
        return await self.session.post_json(
            f"{self.config.API_URL}/offers/{offer_id}/update",
            data=payload,
            referer=f"{self.config.BASE_URL}/offers/edit/{offer_id}",
            include_sid=True,
        )

    async def create_offer(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """TODO: создание новых лотов будет реализовано позже."""
        raise NotImplementedError("TODO: create_offer пока не реализован")

    async def delete_offer(self, offer_id: int) -> Dict[str, Any]:
        """
        Удалить лот.
        """
        return await self.session.post_json(
            f"{self.config.API_URL}/offers/{offer_id}/delete",
            data={},
            referer=f"{self.config.BASE_URL}/offers/edit/{offer_id}",
            include_sid=True,
        )
        
    async def bump_offers(
        self,
        game_id: int,
        category_ids: List[int],
        referer: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Поднять офферы в топ (bump)
        
        Args:
            game_id: ID игры
            category_ids: Список ID категорий для поднятия
            referer: Referer для запроса (опционально)
            
        Returns:
            dict: Результат операции с деталями запроса
        """
        logger.debug(f"🚀 Отправка запроса на поднятие: game_id={game_id}, categories={category_ids}")
        
        # Убедимся, что у нас есть SID перед запросом поднятия
        if not self.session.get_sid():
            logger.debug("⚠️ SID отсутствует, получаем его через user_info...")
            await self.get_user_info()
        
        response = await self.session.post_json(
            f"{self.config.API_URL}/offers/bump",
            data={"gameId": game_id, "categoryIds": category_ids},
            referer=referer or self.config.BASE_URL,
            include_sid=True,
        )
        
        logger.debug(f"📨 Ответ API на поднятие: {response}")
        
        return {
            "request": {"gameId": game_id, "categoryIds": category_ids},
            "response": response,
        }
        
    # ==================== Пользователи ====================
    
    async def get_user_offers(self, user_id: int) -> List[Dict[str, Any]]:
        """
        Получить все офферы пользователя
        
        Args:
            user_id: ID пользователя
            
        Returns:
            list: Список офферов пользователя
        """
        logger.debug("🔍 Запрашиваю список лотов пользователя %s через Next Data...", user_id)

        data = await self._get_user_profile_page(user_id)
        page_props = data.get("pageProps", {})
        categories, source_key = self._extract_user_profile_categories(page_props)

        if not categories:
            logger.warning("⚠️ Не удалось найти userProfileOffers в Next Data для пользователя %s", user_id)
            logger.debug("📊 Ключи pageProps: %s", list(page_props.keys()))
            bff = page_props.get("bff") or {}
            if isinstance(bff, dict):
                logger.debug("📊 Ключи pageProps.bff: %s", list(bff.keys()))
            return []

        logger.debug("📊 Источник офферов: %s", source_key)
        logger.debug("📊 Найдено категорий: %s", len(categories))
        
        offers = []
        for category in categories:
            category_offers = category.get("offers", [])
            logger.debug(f"  - Категория: {len(category_offers)} лотов")
            
            for offer in category_offers:
                offer_id = offer.get("id")
                price = offer.get("price")
                availability = offer.get("availability")
                
                # Формируем название
                descriptions = offer.get("descriptions") or {}
                brief = (descriptions.get("rus") or {}).get("briefDescription")
                if not brief:
                    brief = offer.get("title") or offer.get("name")
                if not brief:
                    brief = category.get("name")
                attrs = offer.get("attributes", [])
                labels = [a.get("valueLabel") for a in attrs if a.get("valueLabel")]
                title_parts = [p for p in [brief, *labels] if p]
                title = ", ".join(title_parts) if title_parts else None
                
                offers.append({
                    "id": offer_id,
                    "title": title,
                    "availability": availability,
                    "price": price,
                    "url": f"{self.config.BASE_URL}/offers/{offer_id}" if offer_id else None,
                })
        
        logger.debug(f"✅ Всего собрано лотов: {len(offers)}")
        return offers
    
    async def get_user_categories(self, user_id: int) -> Dict[int, List[int]]:
        """
        Получить все категории с лотами пользователя, сгруппированные по играм
        
        Args:
            user_id: ID пользователя
            
        Returns:
            dict: Словарь {game_id: [category_ids]} - все категории пользователя по играм
        """
        logger.debug("🔍 Запрашиваю категории пользователя %s через Next Data...", user_id)

        data = await self._get_user_profile_page(user_id)
        page_props = data.get("pageProps", {})
        categories, source_key = self._extract_user_profile_categories(page_props)

        logger.debug("📊 Источник категорий: %s", source_key)
        logger.debug("📊 Всего категорий профиля: %s", len(categories))
        logger.debug("📊 Ключи pageProps: %s", list(page_props.keys()))
        
        # Группируем категории по играм
        game_categories = {}
        for idx, category in enumerate(categories):
            logger.debug(f"  - Категория #{idx}: ключи={list(category.keys())}")
            
            game_id = category.get("gameId")
            category_id = category.get("id")  # ID самой категории
            offers = category.get("offers", [])
            offer_count = len(offers)
            
            logger.debug(f"    gameId={game_id}, categoryId={category_id}, offers={offer_count}")
            
            if game_id and category_id and offer_count > 0:
                if game_id not in game_categories:
                    game_categories[game_id] = []
                if category_id not in game_categories[game_id]:
                    game_categories[game_id].append(category_id)
                    logger.debug(f"    ✅ Добавлено сопоставление: game {game_id} -> category {category_id}")
                    
        logger.debug(f"📦 Найдено игр: {len(game_categories)}")
        for game_id, cat_ids in game_categories.items():
            logger.debug(f"  🎮 Игра {game_id}: категории {cat_ids}")
            
        return game_categories
    
    # ==================== Поддержка онлайна ====================
    
    async def keep_alive(self) -> bool:
        """
        Поддержка онлайн статуса (heartbeat)
        Отправляет heartbeat запрос к API
        
        Returns:
            True если запрос успешен, False если ошибка
        """
        try:
            # Отправляем heartbeat запрос
            response = await self.session.post_json(
                f"{self.config.API_URL}/user/heartbeat",
                data={},
                referer=f"{self.config.BASE_URL}/",
                include_sid=True,
            )
            return True
        except Exception as e:
            # Пробуем альтернативный метод - просто запрос к чатам
            try:
                await self.get_chats()
                return True
            except Exception:
                return False

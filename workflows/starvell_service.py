"""
Сервис для работы со Starvell API
"""

import asyncio
from typing import Optional, List, Dict, Any
from StarvellAPI.gateway_client import StarAPI
from StarvellAPI.api_exceptions import StarAPIError
from support.runtime_config import BotConfig
from support.runtime_storage import Database


class StarvellService:
    """Сервис для работы с Starvell"""
    
    def __init__(self, db: Database):
        self.db = db
        self.api: Optional[StarAPI] = None
        self._lock = asyncio.Lock()
        self._session_error_notified = False  # Флаг для уведомления об ошибке сессии (1 раз)
        self.last_user_info: Dict[str, Any] = {}
        
    async def start(self):
        """Запустить сервис"""
        self.api = StarAPI(
            session_cookie=BotConfig.STARVELL_SESSION(),
            user_agent=BotConfig.USER_AGENT()
        )
        await self.api.session.start()
        # Сбрасываем флаг при старте/перезапуске
        self._session_error_notified = False
        
    async def stop(self):
        """Остановить сервис"""
        if self.api:
            await self.api.close()
    
    async def _notify_session_error(self):
        """Отправить уведомление об ошибке сессии (только один раз)"""
        if self._session_error_notified:
            return
        
        self._session_error_notified = True
        
        import logging
        logger = logging.getLogger(__name__)
        logger.error("⚠️ СЕССИЯ STARVELL УСТАРЕЛА! Токен невалиден или истёк. Обновите session_cookie в конфигурации.")
        
        # Пытаемся отправить уведомление админам
        try:
            from tg_bot.notifications import get_notification_manager
            notification_manager = get_notification_manager()
            if notification_manager:
                await notification_manager.notify_all_admins(
                    "error",
                    "⚠️ <b>Сессия Starvell устарела!</b>\n\n"
                    "Токен (session_cookie) невалиден или истёк.\n"
                    "Starvell сбросил сессию.\n\n"
                    "🔧 <b>Необходимо:</b>\n"
                    "1. Получить новый session_cookie из браузера\n"
                    "2. Обновить его в конфигурации (_main.cfg)\n"
                    "3. Перезапустить бота",
                    force=True
                )
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление об ошибке сессии: {e}")
            
    async def get_user_info(self) -> Dict[str, Any]:
        """Получить информацию о пользователе"""
        if not self.api:
            raise RuntimeError("API не инициализирован")
        
        try:
            info = await self.api.get_user_info()
            self.last_user_info = info
            return info
        except Exception as e:
            from StarvellAPI.api_exceptions import NotFoundError
            if isinstance(e, NotFoundError):
                await self._notify_session_error()
            raise
    
    async def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Получить профиль пользователя по ID
        
        Args:
            user_id: ID пользователя в Starvell
            
        Returns:
            dict: Данные профиля (nickname, name, id и др.) или None если не найден
        """
        if not self.api:
            raise RuntimeError("API не инициализирован")
        return await self.api.get_user_profile(user_id)
        
    async def get_chats(self) -> List[Dict[str, Any]]:
        """Получить список чатов"""
        if not self.api:
            raise RuntimeError("API не инициализирован")
        
        try:
            return await self.api.get_chats()
        except Exception as e:
            from StarvellAPI.api_exceptions import NotFoundError
            if isinstance(e, NotFoundError):
                await self._notify_session_error()
            raise
        
    async def get_unread_chats(self) -> List[Dict[str, Any]]:
        """Получить чаты с непрочитанными сообщениями"""
        if not self.api:
            raise RuntimeError("API не инициализирован")
        
        try:
            return await self.api.get_unread_chats()
        except Exception as e:
            from StarvellAPI.api_exceptions import NotFoundError
            if isinstance(e, NotFoundError):
                await self._notify_session_error()
            raise
        
    async def get_messages(
        self,
        chat_id: str,
        interlocutor_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Получить сообщения из чата"""
        if not self.api:
            raise RuntimeError("API не инициализирован")
        
        try:
            return await self.api.get_messages(chat_id, interlocutor_id, limit)
        except Exception as e:
            from StarvellAPI.api_exceptions import NotFoundError
            if isinstance(e, NotFoundError):
                await self._notify_session_error()
            raise
        
    async def send_message(self, chat_id: str, content: str) -> Dict[str, Any]:
        """Отправить сообщение в чат"""
        if not self.api:
            raise RuntimeError("API не инициализирован")
            
        async with self._lock:
            # Добавляем вотермарк в сообщение при отправке в Starvell, если включено
            try:
                from support.runtime_config import BotConfig
                if BotConfig.USE_WATERMARK():
                    wm = BotConfig.WATERMARK() or ''
                    if wm:
                        # Добавляем в начало, затем пустая строка и оригинальное сообщение
                        content = f"{wm}\n\n{content}"
            except Exception:
                # Не критично — продолжаем без вотермарки
                pass

            result = await self.api.send_message(chat_id, content)
            await self.db.add_sent_message(chat_id, content)
            return result
    
    async def mark_chat_as_read(self, chat_id: str) -> bool:
        """Пометить чат как прочитанный"""
        if not self.api:
            raise RuntimeError("API не инициализирован")
        return await self.api.mark_chat_as_read(chat_id)
    
    async def find_chat_by_user_id(self, user_id: str) -> Optional[str]:
        """Найти ID чата с конкретным пользователем"""
        if not self.api:
            raise RuntimeError("API не инициализирован")
        return await self.api.find_chat_by_user_id(user_id)
            
    async def get_orders(self) -> List[Dict[str, Any]]:
        """Получить список заказов"""
        if not self.api:
            raise RuntimeError("API не инициализирован")
        
        try:
            # Используем новый метод для получения ВСЕХ заказов
            orders = await self.api.get_all_orders()
            return orders if orders else []
        except Exception as e:
            # Проверяем, является ли это ошибкой NotFound (обычно устаревшая сессия)
            from StarvellAPI.api_exceptions import NotFoundError
            if isinstance(e, NotFoundError):
                await self._notify_session_error()
            raise
    
    async def get_all_orders(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Получить ВСЕ заказы с опциональным фильтром по статусу
        
        Args:
            status: Фильтр по статусу ("CREATED", "COMPLETED", "REFUND", "PRE_CREATED")
                   Если None - возвращает все заказы
        
        Returns:
            list: Список всех заказов
        """
        if not self.api:
            raise RuntimeError("API не инициализирован")
        
        try:
            orders = await self.api.get_all_orders(status=status)
            return orders if orders else []
        except Exception as e:
            from StarvellAPI.api_exceptions import NotFoundError
            if isinstance(e, NotFoundError):
                await self._notify_session_error()
            raise
        
    async def refund_order(self, order_id: str) -> Dict[str, Any]:
        """Вернуть деньги за заказ"""
        if not self.api:
            raise RuntimeError("API не инициализирован")
        return await self.api.refund_order(order_id)
        
    async def confirm_order(self, order_id: str) -> Dict[str, Any]:
        """Подтвердить заказ"""
        if not self.api:
            raise RuntimeError("API не инициализирован")
        return await self.api.confirm_order(order_id)

    async def mark_seller_completed(self, order_id: str) -> Dict[str, Any]:
        """Отметить заказ выполненным со стороны продавца"""
        if not self.api:
            raise RuntimeError("API не инициализирован")
        return await self.api.mark_seller_completed(order_id)
    
    async def get_order_details(self, order_id: str) -> Dict[str, Any]:
        """Получить детальную информацию о заказе"""
        if not self.api:
            raise RuntimeError("API не инициализирован")
        return await self.api.get_order_details(order_id)
        
    async def bump_offers(
        self,
        game_id: Optional[int] = None,
        category_ids: Optional[List[int]] = None
    ) -> Dict[str, Any]:
        """Поднять офферы в топ"""
        if not self.api:
            raise RuntimeError("API не инициализирован")
            
        # Используем значения из конфига, если не переданы
        game_id = game_id or BotConfig.AUTO_BUMP_GAME_ID()
        category_ids = category_ids or BotConfig.AUTO_BUMP_CATEGORIES()
        
        async with self._lock:
            try:
                # Сначала получаем user_info для SID
                await self.api.get_user_info()
                
                # Поднимаем
                result = await self.api.bump_offers(game_id, category_ids)
                
                # Сохраняем в БД
                await self.db.add_bump_history(game_id, category_ids, True)
                
                return result
            except Exception as e:
                from StarvellAPI.api_exceptions import NotFoundError
                if isinstance(e, NotFoundError):
                    await self._notify_session_error()
                await self.db.add_bump_history(game_id, category_ids, False)
                raise
                
    async def get_new_messages_count(self) -> int:
        """Получить количество новых сообщений"""
        chats = await self.get_unread_chats()
        return sum((chat.get("unreadMessageCount") or chat.get("unreadCount") or 0) for chat in chats)
        
    async def check_new_messages(self) -> List[Dict[str, Any]]:
        """Проверить новые сообщения по всем чатам через lastMessage.id."""
        import logging
        from support.runtime_config import BotConfig
        logger = logging.getLogger(__name__)

        new_messages = []
        chats = await self.get_chats()

        logger.debug(f"📬 Получено чатов для проверки сообщений: {len(chats)}")

        auto_read_enabled = BotConfig.AUTO_READ_ENABLED()
        my_user = self.last_user_info.get("user", {}) if self.last_user_info else {}
        my_user_id = str(my_user.get("id", ""))

        if not my_user_id:
            user_info = await self.get_user_info()
            my_user_id = str(user_info.get("user", {}).get("id", ""))

        for chat in chats:
            chat_id = chat.get("id")
            if not chat_id:
                continue

            last_message = chat.get("lastMessage") or {}
            latest_id = last_message.get("id")
            if not latest_id:
                continue

            participants = chat.get("participants", [])
            interlocutor_id = None
            for participant in participants:
                participant_id = str(participant.get("id", ""))
                if participant_id and participant_id != my_user_id:
                    interlocutor_id = participant_id
                    break

            if not interlocutor_id:
                continue

            last_known_id = await self.db.get_last_message(chat_id)
            if not last_known_id:
                await self.db.set_last_message(chat_id, latest_id)
                unread_count = chat.get("unreadMessageCount") or chat.get("unreadCount") or 0
                if auto_read_enabled and unread_count:
                    await self.mark_chat_as_read(chat_id)
                continue

            if latest_id == last_known_id:
                unread_count = chat.get("unreadMessageCount") or chat.get("unreadCount") or 0
                if auto_read_enabled and unread_count:
                    await self.mark_chat_as_read(chat_id)
                continue

            messages = await self.get_messages(chat_id, interlocutor_id, limit=20)
            if not messages:
                await self.db.set_last_message(chat_id, latest_id)
                continue

            chat_new_messages = []
            for msg in messages:
                msg_id = msg.get("id")
                if msg_id == last_known_id:
                    break
                chat_new_messages.append({
                    "chat_id": chat_id,
                    "message": msg,
                    "chat": chat,
                })

            if chat_new_messages:
                new_messages.extend(chat_new_messages)

            await self.db.set_last_message(chat_id, latest_id)

            unread_count = chat.get("unreadMessageCount") or chat.get("unreadCount") or 0
            if auto_read_enabled and unread_count:
                await self.mark_chat_as_read(chat_id)

        return new_messages
        
    async def check_new_orders(self) -> List[Dict[str, Any]]:
        """Проверить новые заказы по уведомлениям ORDER_PAYMENT во всех чатах."""
        new_orders = []

        chats = await self.get_chats()
        my_user = self.last_user_info.get("user", {}) if self.last_user_info else {}
        my_user_id = str(my_user.get("id", ""))
        my_username = str(my_user.get("username", ""))

        if not my_user_id:
            user_info = await self.get_user_info()
            my_user = user_info.get("user", {})
            my_user_id = str(my_user.get("id", ""))
            my_username = str(my_user.get("username", ""))

        for chat in chats:
            chat_id = chat.get("id")
            if not chat_id:
                continue

            last_message = chat.get("lastMessage") or {}
            latest_id = last_message.get("id")
            if not latest_id:
                continue

            last_known_order_msg = await self.db.get_last_order_message(chat_id)
            if not last_known_order_msg:
                await self.db.set_last_order_message(chat_id, latest_id)
                continue

            if latest_id == last_known_order_msg:
                continue

            participants = chat.get("participants", [])
            interlocutor_id = None
            for participant in participants:
                participant_id = str(participant.get("id", ""))
                if participant_id and participant_id != my_user_id:
                    interlocutor_id = participant_id
                    break

            if not interlocutor_id:
                await self.db.set_last_order_message(chat_id, latest_id)
                continue

            messages = await self.get_messages(chat_id, interlocutor_id, limit=20)
            if not messages:
                await self.db.set_last_order_message(chat_id, latest_id)
                continue

            for msg in messages:
                msg_id = msg.get("id")
                if msg_id == last_known_order_msg:
                    break

                if msg.get("type") != "NOTIFICATION":
                    continue

                metadata = msg.get("metadata") or {}
                if metadata.get("notificationType") != "ORDER_PAYMENT":
                    continue

                order = msg.get("order") or {}
                order_id = str(metadata.get("orderId") or order.get("id") or "")
                if not order_id:
                    continue

                buyer = msg.get("buyer") or order.get("buyer") or {}
                buyer_id = str(msg.get("buyerId") or buyer.get("id") or order.get("buyerId") or "")
                buyer_username = str(buyer.get("username") or buyer.get("nickname") or buyer.get("name") or "")

                if (buyer_id and buyer_id == my_user_id) or (buyer_username and my_username and buyer_username == my_username):
                    continue

                last_known = await self.db.get_last_order(order_id)
                order_status = str(order.get("status") or metadata.get("notificationType") or "CREATED")
                if last_known and last_known.get("status") == order_status:
                    continue

                enriched_order = dict(order)
                enriched_order["id"] = order_id
                enriched_order["buyerId"] = msg.get("buyerId") or buyer.get("id")
                enriched_order["buyer"] = buyer
                enriched_order["user"] = buyer
                enriched_order["chat_id"] = chat_id
                enriched_order["chatId"] = chat_id
                enriched_order["_notification_type"] = metadata.get("notificationType")
                enriched_order["_message_id"] = msg_id

                new_orders.append(enriched_order)
                await self.db.set_last_order(order_id, order_status)

            await self.db.set_last_order_message(chat_id, latest_id)

        return new_orders
    
    async def get_lots(self) -> List[Dict[str, Any]]:
        """Получить список лотов пользователя"""
        if not self.api:
            raise RuntimeError("API не инициализирован")
        
        try:
            # Получаем информацию о текущем пользователе
            user_info = await self.api.get_user_info()
            user = user_info.get("user")
            
            if not user or not user.get("id"):
                raise RuntimeError("Не удалось получить ID пользователя")
            
            user_id = user.get("id")
            
            # Получаем офферы этого пользователя
            offers = await self.api.get_user_offers(user_id)
            return offers
        except Exception as e:
            from StarvellAPI.api_exceptions import NotFoundError
            if isinstance(e, NotFoundError):
                await self._notify_session_error()
            raise RuntimeError(f"Ошибка получения лотов: {e}")
    
    async def get_lot_edit_data(self, lot_id: str) -> Dict[str, Any]:
        """Получить payload лота для редактирования"""
        if not self.api:
            raise RuntimeError("API не инициализирован")
        
        try:
            return await self.api.get_offer_edit_data(int(lot_id))
        except Exception as e:
            raise RuntimeError(f"Ошибка получения payload лота {lot_id}: {e}")

    async def update_lot(self, lot_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Обновить лот через edit payload"""
        if not self.api:
            raise RuntimeError("API не инициализирован")

        try:
            payload = await self.get_lot_edit_data(lot_id)
            payload.update(updates)

            if payload.get("instantDelivery") and isinstance(payload.get("goods"), list) and payload.get("goods"):
                goods_count = len(payload.get("goods"))
                current_availability = payload.get("availability")
                if not isinstance(current_availability, int) or current_availability > goods_count:
                    payload["availability"] = goods_count

            response = await self.api.update_offer(int(lot_id), payload)

            if isinstance(response, dict) and any(key in response for key in ("error", "errors", "message")):
                error_value = response.get("error") or response.get("errors") or response.get("message")
                if error_value:
                    raise RuntimeError(str(error_value))

            return response
        except Exception as e:
            raise RuntimeError(f"Ошибка обновления лота {lot_id}: {e}")

    async def delete_lot(self, lot_id: str) -> Dict[str, Any]:
        """Удалить лот"""
        if not self.api:
            raise RuntimeError("API не инициализирован")

        try:
            return await self.api.delete_offer(int(lot_id))
        except Exception as e:
            raise RuntimeError(f"Ошибка удаления лота {lot_id}: {e}")

    async def create_lot(self, *args, **kwargs) -> Dict[str, Any]:
        """TODO: создание новых лотов будет реализовано позже"""
        raise NotImplementedError("TODO: create_lot пока не реализован")

    async def activate_lot(self, lot_id: str, amount: Optional[int] = None) -> bool:
        """
        Активировать лот с указанным количеством
        
        Args:
            lot_id: ID лота
            amount: Количество товара (опционально)
        
        Returns:
            True если успешно, False otherwise
        """
        if not self.api:
            raise RuntimeError("API не инициализирован")
        
        try:
            updates = {"isActive": True}
            if amount is not None:
                updates["availability"] = amount
            await self.update_lot(lot_id, updates)
            return True
        except Exception as e:
            raise RuntimeError(f"Ошибка активации лота {lot_id}: {e}")

    async def deactivate_lot(self, lot_id: str) -> bool:
        """Деактивировать лот"""
        if not self.api:
            raise RuntimeError("API не инициализирован")

        try:
            await self.update_lot(lot_id, {"isActive": False})
            return True
        except Exception as e:
            raise RuntimeError(f"Ошибка деактивации лота {lot_id}: {e}")
    
    async def keep_alive(self) -> bool:
        """
        Поддержка онлайн статуса
        
        Returns:
            True если успешно
        """
        if not self.api:
            raise RuntimeError("API не инициализирован")
        
        return await self.api.keep_alive()
    
    async def raise_lots(self, game_id: int, category_ids: List[int]) -> bool:
        """
        Поднять лоты категорий
        
        Args:
            game_id: ID игры
            category_ids: Список ID категорий
        
        Returns:
            True если успешно, False otherwise
        """
        if not self.api:
            raise RuntimeError("API не инициализирован")
        
        try:
            async with self._lock:
                # Используем существующий метод bump_offers
                result = await self.bump_offers(game_id, category_ids)
                return result.get('success', False)
        except Exception as e:
            # Пробрасываем исключение дальше для обработки wait time
            raise RuntimeError(f"Ошибка поднятия лотов: {e}")

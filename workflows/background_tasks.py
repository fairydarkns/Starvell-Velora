"""
Фоновые задачи бота
"""

import asyncio
import logging
import time
from datetime import datetime
from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from support.runtime_config import BotConfig, get_config_manager
from workflows.starvell_service import StarvellService
from support.runtime_storage import Database
from workflows.autoticket import get_autoticket_service


logger = logging.getLogger(__name__)

logging.getLogger('apscheduler').setLevel(logging.ERROR)

REALTIME_IDLE_TIMEOUT = 90
REALTIME_HARD_RECONNECT_TIMEOUT = 3600


class BackgroundTasks:
    """Управление фоновыми задачами"""
    
    def __init__(self, bot: Bot, starvell: StarvellService, db: Database, notifier=None, auto_response=None):
        self.bot = bot
        self.starvell = starvell
        self.db = db
        self.notifier = notifier
        self.auto_response = auto_response
        self.scheduler = AsyncIOScheduler()
        self._seen_messages: dict[str, set[str]] = {}  # chat_id -> set of message_ids
        self._first_check_messages = True  # Флаг первой проверки после запуска
        self._first_check_orders = True  # Флаг первой проверки заказов после запуска
        self._auto_ticket_first_run_done = False  # Флаг первого запуска авто-тикетов
        self._realtime_task: asyncio.Task | None = None
        self._my_user_id: str = ""
        self._my_username: str = ""
        
    def start(self):
        """Запустить фоновые задачи"""
        if self.starvell.realtime_enabled:
            self._realtime_task = asyncio.create_task(self._realtime_loop())
            logger.info("Realtime-обработка сообщений и заказов включена через websocket")
        else:
            # Проверка новых сообщений
            chat_interval = 5
            self.scheduler.add_job(
                self._check_new_messages_loop,
                'interval',
                seconds=max(1, int(chat_interval)),
                id='check_messages',
            )
            
            # Проверка новых заказов
            orders_interval = get_config_manager().get('Monitor', 'ordersPollInterval', 5)
            self.scheduler.add_job(
                self._check_new_orders_loop,
                'interval',
                seconds=max(1, int(orders_interval)),
                id='check_orders',
            )
        
        # Авто-bump офферов
        if BotConfig.AUTO_BUMP_ENABLED():
            self.scheduler.add_job(
                self._auto_bump,
                'interval',
                seconds=BotConfig.AUTO_BUMP_INTERVAL(),
                id='auto_bump',
            )

        # Авто-тикеты
        if BotConfig.AUTO_TICKET_ENABLED():
            # Запускаем первую проверку через 10 секунд после старта
            # (даём время на инициализацию и авторизацию)
            import datetime as dt
            first_run_time = dt.datetime.now() + dt.timedelta(seconds=10)
            self.scheduler.add_job(
                self._check_auto_ticket_with_init,
                'date',
                run_date=first_run_time,
                id='auto_ticket_init',
            )
            # Затем запускаем по таймеру
            self.scheduler.add_job(
                self._check_auto_ticket_loop,
                'interval',
                seconds=BotConfig.AUTO_TICKET_INTERVAL(),
                id='auto_ticket',
            )
        
        # Проверка автоответов (каждые 30 секунд)
        if self.auto_response:
            self.scheduler.add_job(
                self._check_auto_responses,
                'interval',
                seconds=30,
                id='auto_responses',
            )
            
        # Очистка старых данных (раз в день)
        self.scheduler.add_job(
            self._cleanup_old_data,
            'cron',
            hour=3,
            minute=0,
            id='cleanup',
        )
        
        self.scheduler.start()
        logger.info("Фоновые задачи запущены")
        
    def stop(self):
        """Остановить фоновые задачи"""
        if self._realtime_task:
            self._realtime_task.cancel()
            self._realtime_task = None
        self.scheduler.shutdown()
        logger.info("Фоновые задачи остановлены")

    async def _ensure_current_user(self):
        if self._my_user_id and self._my_username:
            return
        user_info = self.starvell.last_user_info or await self.starvell.get_user_info()
        user = user_info.get("user", {})
        self._my_user_id = str(user.get("id", ""))
        self._my_username = str(user.get("username", ""))

    async def _realtime_loop(self):
        """Обработка realtime-событий из websocket."""
        while True:
            try:
                event = await asyncio.wait_for(
                    self.starvell.wait_realtime_event(),
                    timeout=REALTIME_IDLE_TIMEOUT,
                )
                await self._handle_realtime_event(event)
            except asyncio.TimeoutError:
                await self._check_realtime_health()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка в realtime-цикле: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def _check_realtime_health(self):
        socket = self.starvell.socket
        if not socket:
            return

        if not socket.connected:
            logger.warning("Realtime socket Starvell отключен, пытаюсь переподключиться")
            ok = await self.starvell.ensure_realtime_connected(force=True)
            logger.info("Результат переподключения realtime socket: %s", "успешно" if ok else "ошибка")
            return

        now = time.monotonic()
        idle_for = now - socket.last_activity_ts
        if idle_for >= REALTIME_HARD_RECONNECT_TIMEOUT:
            logger.warning(
                "Realtime socket Starvell без событий %.1f сек, выполняю профилактический hard reconnect",
                idle_for,
            )
            ok = await self.starvell.ensure_realtime_connected(force=True)
            logger.info("Результат переподключения realtime socket: %s", "успешно" if ok else "ошибка")

    async def _handle_realtime_event(self, event: dict):
        event_name = event.get("event")
        payload = event.get("data") or {}

        if event_name == "message_created":
            await self._handle_socket_message(payload)
            return
        if event_name == "sale_update":
            await self._handle_socket_sale_update(payload)
            return
        if event_name == "chat_read":
            logger.debug(
                "Socket: чат прочитан пользователем %s в чате %s",
                payload.get("readerUserId"),
                payload.get("chatId"),
            )
            return
        if event_name == "viewed_offer":
            logger.debug(
                "Socket: просмотрен лот %s пользователем %s",
                (payload.get("offer") or {}).get("id"),
                payload.get("buyerId"),
            )

    async def _handle_socket_message(self, message: dict):
        chat_id = str(message.get("chatId") or "")
        if not chat_id:
            return

        message_id = str(message.get("id") or "")

        if message.get("type") == "NOTIFICATION":
            if chat_id not in self._seen_messages:
                self._seen_messages[chat_id] = set()
            if message_id and message_id in self._seen_messages[chat_id]:
                return
            if message_id:
                self._seen_messages[chat_id].add(message_id)

            await self._handle_socket_notification(message)
            if BotConfig.AUTO_READ_ENABLED():
                await self.starvell.mark_chat_as_read(chat_id)
            return

        await self._process_message(
            {
                "chat_id": chat_id,
                "message": message,
                "chat": {},
            }
        )

    @staticmethod
    def _build_short_order_id(order_id: str, order: dict | None = None) -> str:
        if order and order.get("shortId"):
            return str(order["shortId"])
        clean_id = order_id.replace("-", "")
        return clean_id[-8:].upper() if len(clean_id) >= 8 else order_id[:8].upper()

    @staticmethod
    def _resolve_buyer_name(order: dict, message: dict) -> str:
        buyer = message.get("buyer") or order.get("buyer") or order.get("user") or {}
        buyer_id = message.get("buyerId") or order.get("buyerId") or buyer.get("id")
        if isinstance(buyer, dict):
            return (
                buyer.get("username")
                or buyer.get("nickname")
                or buyer.get("name")
                or buyer.get("displayName")
                or f"ID{buyer_id}"
                or "Неизвестно"
            )
        if buyer_id:
            return f"ID{buyer_id}"
        return "Неизвестно"

    async def _handle_socket_notification(self, message: dict):
        metadata = message.get("metadata") or {}
        notification_type = str(metadata.get("notificationType") or "").upper()
        order = dict(message.get("order") or {})
        order_id = str(metadata.get("orderId") or order.get("id") or "")
        chat_id = str(message.get("chatId") or "")

        if not order_id:
            return

        order["id"] = order_id
        order["buyerId"] = message.get("buyerId") or (message.get("buyer") or {}).get("id") or order.get("buyerId")
        order["buyer"] = message.get("buyer") or order.get("buyer") or {}
        order["user"] = order.get("buyer") or order.get("user") or {}
        order["chat_id"] = chat_id
        order["chatId"] = chat_id
        order["_notification_type"] = notification_type
        order["_message_id"] = message.get("id")

        if notification_type == "ORDER_PAYMENT":
            await self._process_order(order)
            return

        if not self.notifier:
            return

        await self._ensure_current_user()

        short_id = self._build_short_order_id(order_id, order)
        buyer_name = self._resolve_buyer_name(order, message)
        buyer_id = str(message.get("buyerId") or order.get("buyerId") or (message.get("buyer") or {}).get("id") or "")
        if (buyer_id and buyer_id == self._my_user_id) or (buyer_name and self._my_username and buyer_name == self._my_username):
            return
        seller_name = self._my_username or "Неизвестно"
        review = order.get("review") or {}

        refund_types = {"ORDER_REFUND", "ORDER_REFUNDED", "ORDER_CANCELLED", "ORDER_CANCELED"}
        buyer_confirm_types = {"ORDER_COMPLETED", "ORDER_CONFIRMED"}
        seller_confirm_types = {"ORDER_SELLER_COMPLETED", "ORDER_MARKED_COMPLETED"}
        review_created_types = {"REVIEW_CREATED"}
        review_deleted_types = {"REVIEW_DELETED"}

        if notification_type in review_created_types:
            logger.info("Получено socket-событие REVIEW_CREATED для заказа %s", order_id)
            if order_id:
                try:
                    order_details = await self.starvell.get_order_details(order_id)
                    review = self.starvell.extract_review_from_order_details(order_details) or review or {}
                except Exception as e:
                    logger.debug("Не удалось получить детали отзыва по заказу %s: %s", order_id, e)
            if review:
                await self.notifier.notify_order_review(
                    order_id=order_id,
                    short_id=short_id,
                    buyer=buyer_name,
                    rating=str(review.get("rating", "N/A")),
                    comment=str(review.get("content") or review.get("comment") or review.get("text") or ""),
                    review_id=str(review.get("id") or ""),
                    can_reply=not bool(review.get("reviewResponse")),
                    review_response_id=str((review.get("reviewResponse") or {}).get("id") or ""),
                )
            else:
                logger.debug("Не нашел review в деталях заказа %s для REVIEW_CREATED", order_id)
            return

        if notification_type in review_deleted_types:
            logger.info("Получено socket-событие REVIEW_DELETED для заказа %s", order_id)
            await self.notifier.notify_order_review_removed(
                order_id=order_id,
                short_id=short_id,
                buyer=buyer_name,
            )
            return

        if (
            notification_type in refund_types
            or "REFUND" in notification_type
            or "CANCEL" in notification_type
            or order.get("refundedAt")
            or self.starvell.is_cancelled_order(order)
        ):
            await self.notifier.notify_order_refunded(
                order_id=order_id,
                short_id=short_id,
                buyer=buyer_name,
                seller=seller_name,
                chat_id=chat_id,
            )
            return

        if (
            notification_type in seller_confirm_types
            or self.starvell.is_waiting_buyer_confirmation(order)
        ):
            await self.notifier.notify_order_marked_completed(
                order_id=order_id,
                short_id=short_id,
                buyer=buyer_name,
                seller=seller_name,
                chat_id=chat_id,
            )
            return

        if (
            notification_type in buyer_confirm_types
            or self.starvell.is_completed_order(order)
        ):
            await self.notifier.notify_order_buyer_confirmed(
                order_id=order_id,
                short_id=short_id,
                buyer=buyer_name,
                chat_id=chat_id,
            )
            return

    async def _handle_socket_sale_update(self, payload: dict):
        return
        
    async def _check_new_messages_loop(self):
        """Polling цикл для проверки новых сообщений"""
        try:
            # ВСЕГДА проверяем сообщения (для плагинов и кастомных команд)
            # Уведомления будут отправлены только если включены (проверка внутри notify_new_message)
            await self._check_new_messages()
                    
        except Exception as e:
            logger.error(f"Ошибка при проверке сообщений: {e}", exc_info=True)
            
    async def _check_new_orders_loop(self):
        """Polling цикл для проверки новых заказов """
        try:
            # ВСЕГДА проверяем заказы (для плагинов)
            # Уведомления будут отправлены только если включены (проверка внутри notify_new_order)
            await self._check_new_orders()
                    
        except Exception as e:
            logger.error(f"Ошибка при проверке заказов: {e}", exc_info=True)
            
    async def _check_new_messages(self):
        """Проверка новых сообщений"""
        try:
            new_messages = await self.starvell.check_new_messages()
            
            if not self.notifier:
                logger.warning("Менеджер уведомлений не инициализирован")
                return
            
            # Логируем количество найденных новых сообщений
            if new_messages:
                if BotConfig.DEBUG():
                    logger.debug(f"📬 Получено {len(new_messages)} новых сообщений из API Starvell")
            
            for msg_data in new_messages:
                await self._process_message(msg_data)
                    
        except Exception as e:
            logger.error(f"Ошибка при проверке новых сообщений: {e}", exc_info=True)
            
    async def _check_new_orders(self):
        """Проверка новых заказов"""
        try:
            new_orders = await self.starvell.check_new_orders()
            
            if not self.notifier:
                logger.warning("Менеджер уведомлений не инициализирован")
                return
            
            # Логируем количество найденных новых заказов
            if new_orders:
                logger.debug(f"📦 Получено {len(new_orders)} новых заказов из API Starvell")
            
            for order in new_orders:
                await self._process_order(order)
                    
        except Exception as e:
            logger.error(f"Ошибка при проверке новых заказов: {e}", exc_info=True)

    async def _process_message(self, msg_data: dict):
        chat_id = str(msg_data.get("chat_id", ""))
        message = msg_data.get("message", {})
        chat = msg_data.get("chat", {})

        author_id = str(message.get("authorId", "N/A"))
        content = message.get("content") or message.get("text", "")
        message_id = message.get("id")

        if not content:
            return

        config = get_config_manager()
        blacklist_section = f"Blacklist.{author_id}"
        if config._config.has_section(blacklist_section):
            if BotConfig.DEBUG():
                logger.debug(f"Сообщение от пользователя {author_id} игнорируется (в черном списке)")
            return

        author_username = None
        author_roles = []
        author_data = message.get("author", {})
        if author_data:
            author_username = author_data.get("username") or author_data.get("name")
            author_roles = author_data.get("roles", [])

        if not author_username and chat:
            participants = chat.get("participants", [])
            for participant in participants:
                if str(participant.get("id")) == str(author_id):
                    author_username = participant.get("username") or participant.get("name")
                    break

        await self._ensure_current_user()
        is_own_message = bool(self._my_user_id and str(author_id) == self._my_user_id)
        if is_own_message and not BotConfig.NOTIFY_OWN_MESSAGES():
            return

        if chat_id not in self._seen_messages:
            self._seen_messages[chat_id] = set()
        if message_id and message_id in self._seen_messages[chat_id]:
            return

        is_support = bool(author_roles and ("SUPPORT" in author_roles or "MODERATOR" in author_roles or "ADMIN" in author_roles))
        if is_support:
            await self.notifier.notify_support_message(
                chat_id=chat_id,
                author=str(author_id),
                content=content,
                message_id=str(message_id) if message_id else None,
                author_nickname=author_username,
                author_roles=author_roles,
                raw_message=message,
                raw_chat=chat,
            )
        else:
            await self.notifier.notify_new_message(
                chat_id=chat_id,
                author=str(author_id),
                content=content,
                message_id=str(message_id) if message_id else None,
                author_nickname=author_username,
                raw_message=message,
                raw_chat=chat,
            )

        if message_id:
            self._seen_messages[chat_id].add(message_id)

        if not is_own_message and BotConfig.AUTO_READ_ENABLED():
            await self.starvell.mark_chat_as_read(chat_id)

        await self._check_custom_command(chat_id, content, author_id)

        role_prefix = f"[{', '.join(author_roles)}] " if author_roles else ""
        display_name = author_username or author_id
        logger.info(f"📩 Новое сообщение от {role_prefix}{display_name}: {content[:50]}...")

    async def _process_order(self, order: dict):
        order_id = str(order.get("id", ""))
        if not order_id:
            return

        await self._ensure_current_user()
        status = order.get("status", "CREATED")
        normalized_status = str(status).upper()

        if normalized_status not in {"CREATED", "PRE_CREATED"}:
            logger.debug(
                "Пропускаю socket/order событие для заказа %s со статусом %s: это не новый заказ",
                order_id,
                normalized_status,
            )
            return

        buyer_obj = order.get("buyer") or order.get("user") or {}
        buyer_id = str(order.get("buyerId") or buyer_obj.get("id") or "")
        buyer_username = str(
            buyer_obj.get("username") or
            buyer_obj.get("nickname") or
            buyer_obj.get("name") or
            ""
        )

        if (buyer_id and buyer_id == self._my_user_id) or (
            buyer_username and self._my_username and buyer_username == self._my_username
        ):
            return

        last_known = await self.db.get_last_order(order_id)
        if last_known and last_known.get("status") == status:
            return

        short_id = order.get("shortId", "")
        if not short_id:
            clean_id = order_id.replace("-", "")
            short_id = clean_id[-8:].upper() if len(clean_id) >= 8 else order_id[:8].upper()

        amount = self.starvell.extract_order_income_rub(order)

        buyer = order.get("user") or order.get("buyer") or {}
        buyer_id = order.get("buyerId")
        buyer_name = "Неизвестно"

        if isinstance(buyer, dict):
            buyer_name = (
                buyer.get("username") or
                buyer.get("nickname") or
                buyer.get("name") or
                buyer.get("displayName") or
                f"ID{buyer.get('id', buyer_id)}"
            )
        elif buyer_id:
            buyer_name = f"ID{buyer_id}"
            order["user"] = {
                "id": buyer_id,
                "username": buyer_name,
            }

        lot = order.get("offerDetails") or order.get("listing") or order.get("lot") or order.get("offer") or {}
        lot_name = "Неизвестно"
        if isinstance(lot, dict):
            descriptions = lot.get("descriptions", {})
            if descriptions:
                rus_desc = descriptions.get("rus", {})
                lot_name = (
                    rus_desc.get("briefDescription") or
                    rus_desc.get("description") or
                    lot.get("name") or
                    lot.get("title") or
                    "Неизвестно"
                )
            else:
                lot_name = (
                    lot.get("name") or
                    lot.get("title") or
                    lot.get("description") or
                    "Неизвестно"
                )
        elif isinstance(lot, str):
            lot_name = lot

        await self.notifier.notify_new_order(
            order_id=order_id,
            short_id=short_id,
            buyer=buyer_name,
            amount=float(amount),
            lot_name=lot_name,
            status=status,
            order_data=order,
        )
        await self.db.set_last_order(order_id, normalized_status)

        logger.info(f"🛒 Новый заказ #{short_id} от {buyer_name}: {lot_name} - {amount}₽")
        logger.debug(f"Полные данные заказа: {order}")
            
    async def _auto_bump(self):
        """Автоматическое поднятие офферов"""
        try:
            # Проверяем, включено ли автоподнятие хотя бы у одного админа
            auto_bump_enabled = False
            
            for admin_id in BotConfig.ADMIN_IDS():
                settings = await self.db.get_user_settings(admin_id)
                if settings.get("auto_bump_enabled", False):
                    auto_bump_enabled = True
                    break
                    
            if not auto_bump_enabled:
                return
                
            # Выполняем поднятие
            logger.info("Выполняется автоподнятие офферов...")
            
            result = await self.starvell.bump_offers()
            
            from tg_bot.notifications import get_notification_manager, NotificationType
            notif_manager = get_notification_manager()
            
            if notif_manager:
                # Уведомляем админов через NotificationManager
                message = f"Время: {datetime.now().strftime('%H:%M:%S')}\n"
                message += f"Game ID: {BotConfig.AUTO_BUMP_GAME_ID()}\n"
                message += f"Категории: {', '.join(map(str, BotConfig.AUTO_BUMP_CATEGORIES()))}"
                
                await notif_manager.notify_all_admins(
                    NotificationType.AUTO_BUMP,
                    message
                )
                        
            logger.info("Автоподнятие офферов успешно выполнено")
            
        except Exception as e:
            logger.error(f"Ошибка при выполнении автоподнятия офферов: {e}", exc_info=True)

            from tg_bot.notifications import get_notification_manager
            notif_manager = get_notification_manager()

            # Собираем подробные детали для уведомления
            details = {
                "Время": datetime.now().strftime('%H:%M:%S'),
                "game_id": BotConfig.AUTO_BUMP_GAME_ID(),
                "categories": BotConfig.AUTO_BUMP_CATEGORIES(),
                "error_type": type(e).__name__,
            }

            # Попытка получить дополнительные аргументы/тело ответа из исключения
            try:
                if hasattr(e, 'args') and e.args:
                    details['args'] = e.args
                # Если исключение содержит вложенные детали (например, словарь), попытаться их добавить
                if hasattr(e, '__dict__'):
                    for k, v in e.__dict__.items():
                        if k not in details:
                            details[k] = str(v)
            except Exception:
                pass

            if notif_manager:
                await notif_manager.notify_error(
                    str(e),
                    context="Автоподнятие офферов",
                    details=details
                )
                    
    async def _cleanup_old_data(self):
        """Очистка старых данных"""
        try:
            logger.info("Очистка старых данных...")
            await self.db.cleanup(days=7)
            logger.info("Очистка завершена")
        except Exception as e:
            logger.error(f"Ошибка при очистке данных: {e}", exc_info=True)
    
    async def _check_custom_command(self, chat_id: str, message_text: str, author_id: str):
        """Проверить и обработать кастомную команду"""
        try:
            import json
            from pathlib import Path

            commands_file = Path("storage/telegram/custom_commands.json")
            legacy_commands_file = Path("storage/custom_commands.json")
            if not commands_file.exists() and legacy_commands_file.exists():
                try:
                    commands_file.parent.mkdir(parents=True, exist_ok=True)
                    legacy_commands_file.replace(commands_file)
                except Exception as e:
                    logger.error(f"Ошибка переноса файла кастомных команд: {e}")
                    return
            if not commands_file.exists():
                return

            with open(commands_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Проверяем, включены ли кастомные команды
            if not data.get("enabled", False):
                return
            
            prefix = data.get("prefix", "!")
            commands = data.get("commands", [])
            
            # Проверяем, начинается ли сообщение с префикса
            if not message_text.startswith(prefix):
                return
            
            # Извлекаем команду (без префикса)
            command_text = message_text[len(prefix):].strip().lower()
            
            # Ищем соответствующую команду
            for cmd in commands:
                if cmd["name"].lower() == command_text:
                    # Нашли команду - отправляем ответ
                    try:
                        await self.starvell.send_message(chat_id, cmd["text"])
                        logger.info(f"🤖 Отправлен автоответ на команду '{prefix}{cmd['name']}' пользователю {author_id}")
                    except Exception as e:
                        logger.error(f"Ошибка при отправке автоответа на команду: {e}")
                    break
                    
        except Exception as e:
            logger.error(f"Ошибка при обработке кастомной команды: {e}", exc_info=True)
    
    async def _check_auto_responses(self):
        """Проверка и отправка автоответов"""
        try:
            if self.auto_response:
                await self.auto_response.check_and_respond()
        except Exception as e:
            logger.error(f"Ошибка при проверке автоответов: {e}", exc_info=True)
            
    async def toggle_auto_bump(self, enabled: bool):
        """Включить/выключить автоподнятие"""
        if enabled and not self.scheduler.get_job('auto_bump'):
            self.scheduler.add_job(
                self._auto_bump,
                'interval',
                seconds=BotConfig.AUTO_BUMP_INTERVAL(),
                id='auto_bump',
            )
            logger.info("Автоподнятие включено")
        elif not enabled and self.scheduler.get_job('auto_bump'):
            self.scheduler.remove_job('auto_bump')
            logger.info("Автоподнятие выключено")

    async def _check_auto_ticket_with_init(self):
        """Первая проверка авто-тикетов при запуске бота"""
        if self._auto_ticket_first_run_done:
            return
        
        self._auto_ticket_first_run_done = True
        logger.info("🎫 Запускаю первую проверку авто-тикетов при старте бота...")
        
        await self._check_auto_ticket_loop()

    async def _check_auto_ticket_loop(self):
        """Проверка авто-тикетов"""
        if not BotConfig.AUTO_TICKET_ENABLED():
            return

        try:
            autoticket = get_autoticket_service()
            if not autoticket:
                logger.warning("Сервис авто-тикетов не инициализирован")
                return

            # Получаем неподтвержденные заказы
            hours = BotConfig.AUTO_TICKET_ORDER_AGE()
            unconfirmed = await autoticket.get_unconfirmed_orders(self.starvell, hours=hours)
            
            if not unconfirmed:
                logger.debug("Неподтверждённых заказов не найдено")
                return
                
            # Убрали лог: 📋 Найдено {len(unconfirmed)} заказов для авто-тикета
            
            # Берём заказы с учётом максимального количества
            max_orders = min(BotConfig.AUTO_TICKET_MAX_ORDERS(), len(unconfirmed))
            orders_to_process = unconfirmed[:max_orders]
            
            # Собираем список ID заказов
            order_ids = [order.get('id') for order in orders_to_process if order.get('id')]
            
            if not order_ids:
                logger.warning("Не удалось извлечь ID заказов")
                return
            
            # Проверяем, можно ли отправить тикет (прошёл ли интервал)
            if not autoticket.can_send_ticket():
                remaining = autoticket.get_time_until_next_ticket()
                logger.info(f"⏳ Тикет не отправлен - интервал не прошёл (осталось {remaining}с)")
                return
            
            # Отправляем ОДИН тикет со ВСЕМИ заказами
            # Первый заказ (самый старый) идёт в поле orderId, остальные в описание
            # Убрали лог: 📨 Создаю тикет с {len(order_ids)} заказами...
            success, msg = await autoticket.send_ticket(order_ids)
            
            # Уведомляем админов о результате (если включено)
            if BotConfig.NOTIFY_AUTO_TICKET() and self.notifier:
                if success:
                    # Формируем список заказов для уведомления (ID в строчку через пробел)
                    orders_list = " ".join([
                        f"#{order.get('id', 'N/A').replace('-', '')[-8:].upper()}"
                        for order in orders_to_process
                    ])
                    
                    text = (
                        f"🎫 <b>Покупатель забыл подтвердить заказ</b>\n\n"
                        f"Список заказов: {orders_list}\n"
                        f"Всего заказов: {len(order_ids)}"
                    )
                    await self.notifier.notify_all_admins(
                        "auto_ticket",
                        text,
                        force=False
                    )
                else:
                    text = (
                        f"❌ <b>Ошибка создания авто-тикета</b>\n\n"
                        f"� Заказов: {len(order_ids)}\n"
                        f"❗ {msg}"
                    )
                    await self.notifier.notify_all_admins(
                        "auto_ticket",
                        text,
                        force=True
                    )
            
        except Exception as e:
            logger.error(f"❌ Ошибка в цикле авто-тикетов: {e}", exc_info=True)

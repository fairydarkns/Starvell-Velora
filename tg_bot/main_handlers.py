"""
Обработчики команд бота
"""

import hashlib
import asyncio
import json
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from support.runtime_config import BotConfig, get_config_manager
from tg_bot.notifications import NotificationType
from tg_bot.full_keyboards import (
    get_main_menu,
    get_global_switches_menu,
    get_notifications_menu,
    get_auto_delivery_lots_menu,
    get_auto_ticket_settings_menu,
    get_blacklist_menu,
    get_modules_menu,
    get_select_template_menu,
    get_custom_commands_menu,
    CBT,
)
import tg_bot.auto_delivery_handlers as auto_delivery_handlers
import tg_bot.blacklist_handlers as blacklist_handlers
import tg_bot.plugins_handlers as plugins_handlers
import tg_bot.templates_handlers as templates_handlers
import tg_bot.extra_handlers as extra_handlers
import tg_bot.custom_commands_handlers as custom_commands_handlers


router = Router()
router.include_router(auto_delivery_handlers.router)
router.include_router(blacklist_handlers.router)
router.include_router(plugins_handlers.router)
router.include_router(templates_handlers.router)
router.include_router(extra_handlers.router)
router.include_router(custom_commands_handlers.router)

ORDER_ACTION_CONTEXT: dict[tuple[int, int], dict] = {}
REVIEW_REPLY_CONTEXT: dict[int, dict] = {}


# Утилита: безопасное приведение к float (чтобы избежать ошибок форматирования, если приходит dict)
def _safe_float(val, default=0.0):
    """Преобразовать в float безопасно; в случае ошибки вернуть default"""
    try:
        if isinstance(val, dict):
            for k in ("amount", "price", "totalPrice", "basePrice", "value"):
                if k in val:
                    try:
                        return float(val[k])
                    except Exception:
                        continue
            return default
        return float(val)
    except Exception:
        return default


def _format_starvell_datetime(raw_value: str) -> str:
    if not raw_value:
        return "Неизвестно"
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(raw_value)


def _extract_profile_metrics(user: dict) -> tuple[float, float, float]:
    balance_data = user.get("balance", {})
    balance = balance_data.get("rubBalance", 0) if isinstance(balance_data, dict) else 0
    hold_balance = user.get("holdedAmount", 0)
    total_balance = _safe_float(balance) + _safe_float(hold_balance)
    return _safe_float(balance), _safe_float(hold_balance), total_balance


def _order_money_rub(order: dict, *fields: str) -> float:
    if "displayAmountRub" in order:
        return _safe_float(order.get("displayAmountRub"))
    for field in fields:
        rub_field = f"{field}Rub"
        if rub_field in order:
            return _safe_float(order.get(rub_field))
        if field in order:
            return _safe_float(order.get(field)) / 100.0
    return 0.0


def _format_verification_status(user: dict) -> str:
    return "✅ Верифицирован" if user.get("kycStatus") == "VERIFIED" else "❌ Не верифицирован"


def _build_profile_text(user: dict) -> str:
    username = user.get("username", "Неизвестно")
    user_id = user.get("id", "?")
    created_at = _format_starvell_datetime(user.get("createdAt"))
    balance, hold_balance, total_balance = _extract_profile_metrics(user)
    rating = _safe_float(user.get("rating", 0))
    reviews_count = int(user.get("reviewsCount", 0) or 0)
    verified = _format_verification_status(user)

    text = "👤 <b>Профиль продавца</b>\n\n"
    text += f"<b>Имя:</b> {username}\n"
    text += f"<b>ID:</b> <code>{user_id}</code>\n"
    text += f"<b>Статус:</b> {verified}\n"
    text += f"<b>Регистрация:</b> {created_at}\n\n"
    text += "💰 <b>Баланс:</b>\n"
    text += f"├ Доступно: <code>{balance:.2f}</code> ₽\n"
    text += f"├ Заморожено: <code>{hold_balance:.2f}</code> ₽\n"
    text += f"└ Всего: <code>{total_balance:.2f}</code> ₽\n\n"
    text += f"⭐ <b>Рейтинг:</b> {rating:.1f} ({reviews_count} отзывов)"
    return text


def _normalize_for_json(value):
    """Подготовить произвольные данные заказа к JSON-выводу."""
    if isinstance(value, dict):
        return {str(key): _normalize_for_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_for_json(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_for_json(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _order_sort_key(order: dict) -> str:
    """Вернуть ключ сортировки для выбора самого свежего заказа."""
    for field in ("updatedAt", "paidAt", "createdAt", "date", "timestamp"):
        raw_value = order.get(field)
        if raw_value:
            return str(raw_value)
    return str(order.get("id", ""))


def _build_home_panel_text() -> str:
    return (
        "🧭 <b>StarvellVelora // Хаб управления</b>\n\n"
        "Здесь собраны основные контуры управления магазином:\n"
        "автосценарии, сигналы, выдача, ответы и модули.\n\n"
        "Выберите нужный раздел ниже."
    )


def _build_automation_panel_text() -> str:
    return (
        "⚙️ <b>Глобальные настройки</b>\n\n"
        "Этот раздел управляет фоновыми действиями магазина.\n"
        "Каждый переключатель применяется сразу."
    )


def _build_alerts_panel_text() -> str:
    return (
        "🔔 <b>Настройка уведомлений</b>\n\n"
        "Включите только те события, которые должны доходить до Telegram.\n"
        "Здесь же можно выбрать: брать только непрочитанные сообщения или весь поток,"
        " включая собственные ответы."
    )


def _get_notifications_menu_state() -> dict:
    return {
        "messages": BotConfig.NOTIFY_NEW_MESSAGES(),
        "orders": BotConfig.NOTIFY_NEW_ORDERS(),
        "restore": BotConfig.NOTIFY_LOT_RESTORE(),
        "start": BotConfig.NOTIFY_BOT_START(),
        "stop": BotConfig.NOTIFY_BOT_STOP(),
        "auto_ticket": BotConfig.NOTIFY_AUTO_TICKET(),
        "order_confirm": BotConfig.NOTIFY_ORDER_CONFIRMED(),
        "review": BotConfig.NOTIFY_REVIEW(),
        "review_deleted": BotConfig.NOTIFY_REVIEW_DELETED(),
        "auto_responses": BotConfig.NOTIFY_AUTO_RESPONSES(),
        "support_messages": BotConfig.NOTIFY_SUPPORT_MESSAGES(),
        "own_messages": BotConfig.NOTIFY_OWN_MESSAGES(),
        "all_messages": BotConfig.NOTIFY_ALL_MESSAGES(),
    }


async def _refresh_notifications_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        _build_alerts_panel_text(),
        reply_markup=get_notifications_menu(**_get_notifications_menu_state()),
    )


def _build_modules_panel_text(modules_data: list[dict]) -> str:
    enabled_count = sum(1 for item in modules_data if item["enabled"])
    disabled_count = len(modules_data) - enabled_count
    return (
        "🧩 <b>Реестр плагинов</b>\n\n"
        f"• Всего: <code>{len(modules_data)}</code>\n"
        f"• Активно: <code>{enabled_count}</code>\n"
        f"• На паузе: <code>{disabled_count}</code>\n\n"
        "После изменения состава модулей выполните <code>/restart</code>."
    )


def _build_about_panel_text() -> str:
    return (
        "🛰 <b>Паспорт проекта</b>\n\n"
        "StarvellVelora — отдельный операционный бот для работы со Starvell.\n\n"
        "Автор: @kortkk\n"
        "Новости: @starvell_velora\n"
        "Канал модулей: @velora_plugins"
    )


# === Состояния ===

class AuthState(StatesGroup):
    """Состояния для авторизации"""
    waiting_for_password = State()


class ReplyState(StatesGroup):
    """Состояния для быстрого ответа на сообщения"""
    waiting_for_reply = State()


class SessionState(StatesGroup):
    """Состояния для обновления session_cookie"""
    waiting_for_cookie = State()


class AutoTicketState(StatesGroup):
    """Состояния для настройки авто-тикетов"""
    waiting_for_interval = State()
    waiting_for_max_orders = State()


class LotTestState(StatesGroup):
    """Состояния тестового управления лотами"""
    waiting_for_lot_id = State()
    waiting_for_price = State()


class ReviewReplyState(StatesGroup):
    """Состояние ответа на отзыв"""
    waiting_for_text = State()


def _order_action_context_key(callback: CallbackQuery) -> tuple[int, int]:
    return callback.message.chat.id, callback.message.message_id


def _strip_order_action_buttons(
    reply_markup: InlineKeyboardMarkup | None,
    *,
    keep_refund: bool = False,
) -> InlineKeyboardMarkup | None:
    if not reply_markup:
        return None

    rows = []
    for row in reply_markup.inline_keyboard:
        filtered_row = []
        for button in row:
            callback_data = getattr(button, "callback_data", None)
            if callback_data:
                if callback_data.startswith("complete:"):
                    continue
                if callback_data.startswith("refund:") and not keep_refund:
                    continue
            filtered_row.append(button)
        if filtered_row:
            rows.append(filtered_row)

    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def _extract_order_card_field(message_text: str | None, prefix: str) -> str:
    if not message_text:
        return ""
    for line in message_text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return ""


def _build_short_order_id(order_id: str, message_text: str | None = None) -> str:
    if message_text:
        short_id = _extract_order_card_field(message_text, "🆔 ID заказа: ")
        if short_id.startswith("#"):
            return short_id[1:].strip()
    clean_id = order_id.replace("-", "")
    return clean_id[-8:].upper() if len(clean_id) >= 8 else order_id[:8].upper()


def _extract_order_id_from_markup(reply_markup: InlineKeyboardMarkup | None) -> str:
    if not reply_markup:
        return ""
    for row in reply_markup.inline_keyboard:
        for button in row:
            url = getattr(button, "url", None)
            if url and "/order/" in url:
                return url.rsplit("/order/", 1)[-1].strip()
    return ""


def _build_review_reply_markup(order_id: str, review_id: str | None = None, response_id: str | None = None) -> InlineKeyboardMarkup:
    row = []
    if response_id:
        row.append(
            InlineKeyboardButton(
                text="🗑️ Удалить ответ",
                callback_data=f"review_delete:{response_id}",
            )
        )
    elif review_id:
        row.append(
            InlineKeyboardButton(
                text="💬 Ответить на отзыв",
                callback_data=f"review_reply:{review_id}",
            )
        )
    row.append(
        InlineKeyboardButton(
            text="💰 Вернуть деньги",
            callback_data=f"refund:{order_id}",
        )
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            row,
            [
                InlineKeyboardButton(
                    text="🔗 Открыть заказ",
                    url=f"https://starvell.com/order/{order_id}",
                )
            ],
        ]
    )


# === Функции авторизации ===

def hash_password(password: str) -> str:
    """Хеширование пароля"""
    return hashlib.sha256(password.encode()).hexdigest()


def is_user_authorized(user_id: int) -> bool:
    """Проверка авторизации пользователя"""
    admin_ids = BotConfig.ADMIN_IDS()
    return user_id in admin_ids


async def authorize_user(user_id: int):
    """Добавить пользователя в список админов"""
    admin_ids = BotConfig.ADMIN_IDS()
    if user_id not in admin_ids:
        admin_ids.append(user_id)
        BotConfig.set_admin_ids(admin_ids)

# === Команды ===

@router.message(Command("start"))
@router.message(Command("menu"))
async def cmd_start(message: Message, state: FSMContext, **kwargs):
    """Команда /start"""
    # Загружаем текущий язык
    
    
    # Проверяем авторизацию
    if not is_user_authorized(message.from_user.id):
        # Показываем приглашение ввести пароль и кнопку с ссылкой на репозиторий
        try:
            repo_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="Хочу такого же бота",
                    url="https://t.me/kortkk"
                )]
            ])
            await message.answer("🔐 Введите пароль доступа, чтобы открыть хаб управления.", reply_markup=repo_kb)
        except Exception:
            # На случай редких проблем со сборкой клавиатуры просто отправим текст
            await message.answer("🔐 Введите пароль доступа, чтобы открыть хаб управления.")

        await state.set_state(AuthState.waiting_for_password)
        return
    
    await message.answer(
        _build_home_panel_text(),
        reply_markup=get_main_menu()
    )


@router.message(Command("update"))
async def cmd_update(message: Message, updater, **kwargs):
    """Команда /update - вручную обновить бота"""
    # Проверяем авторизацию
    if not is_user_authorized(message.from_user.id):
        return
    
    status_msg = await message.answer("🔍 Проверяю наличие новой версии...")
    try:
        update_available = await updater.check_for_updates()
    except Exception as error:  # noqa: BLE001
        await status_msg.edit_text(f"❌ {error}")
        return

    if not update_available:
        await status_msg.edit_text(
            f"✅ Установлена последняя версия: <code>{updater.current_version}</code>"
        )
        return

    await status_msg.edit_text(
        f"✨ Доступно обновление!\n\n"
        f"📌 Текущая: <code>{updater.current_version}</code>\n"
        f"✨ Новая: <code>{updater.latest_version}</code>\n\n"
        f"🔄 Создаю резервную копию и применяю обновление..."
    )
    result = await updater.perform_update()
    
    if result["success"]:
        await status_msg.edit_text(
            result["message"] + "\n\n"
            f"<tg-spoiler>Детали обновления:\n{result['output']}</tg-spoiler>\n\n"
            f"🔄 Перезапуск бота через 3 секунды..."
        )
        
        # Даём время прочитать сообщение и перезапускаем бот
        await asyncio.sleep(3)
        
        updater.restart()
    else:
        await status_msg.edit_text(
            result["message"] + "\n\n"
            f"<tg-spoiler>Ошибка:\n{result['output']}</tg-spoiler>"
        )




@router.message(Command("session_cookie"))
async def cmd_session_cookie(message: Message, starvell, **kwargs):
    """Команда /session_cookie <cookie> — обновить session_cookie и перезапустить подключение к Starvell"""
    # Проверяем авторизацию
    if not is_user_authorized(message.from_user.id):
        return

    # Разрешаем ввод в том же сообщении: /session_cookie <value>
    parts = message.text.split(None, 1)
    if len(parts) == 1:
        # Запускаем FSM — ждём, пока пользователь отправит новый ключ в следующем сообщении
        await message.answer(
            "✉️ Отправьте новый <b>session_cookie</b> сообщением в этом чате.\n\n"
            "Для отмены отправьте /cancel",
            parse_mode="HTML"
        )
        await message.answer(
            "ℹ️ Примечание: рекомендуется отправлять ключ в личном чате с ботом, чтобы он не оказался в групповой переписке."
        )
        await message.answer("⏳ Жду новый session_cookie...")
        await kwargs.get('state').set_state(SessionState.waiting_for_cookie)
        return

    new_cookie = parts[1].strip()
    if not new_cookie:
        await message.answer("❌ Пустое значение session_cookie. Попробуйте ещё раз.")
        return

    # Сохраняем в конфиг
    try:
        config = get_config_manager()
        config.set('Starvell', 'session_cookie', new_cookie)
        # Применяем изменения в рантайме
        BotConfig.reload()
    except Exception as e:
        await message.answer(f"❌ Не удалось сохранить конфигурацию: {e}")
        return

    await message.answer("✅ session_cookie обновлён в конфиге. Попытка перезапустить подключение к Starvell...")

    # Перезапускаем StarvellService (если он доступен через injected dependency)
    try:
        # starvell — это экземпляр StarvellService, прокинутый в workflow_data
        await starvell.stop()
        await starvell.start()
        # После старта флаг _session_error_notified уже сброшен в start()
        # Проверяем авторизацию
        user_info = await starvell.get_user_info()
        if user_info.get('authorized'):
            await message.answer("✅ Успешно авторизован в Starvell. Все службы могут продолжить работу.")
        else:
            await message.answer("⚠️ Перезапуск выполнен, но авторизация не удалась. Проверьте session_cookie и при необходимости перезапустите бота вручную.")
    except Exception as e:
        await message.answer(f"❌ Ошибка при перезапуске сервиса Starvell: {e}")
        import logging
        logging.getLogger(__name__).exception("Ошибка при перезапуске StarvellService")



@router.message(SessionState.waiting_for_cookie)
async def process_session_cookie_input(message: Message, state: FSMContext, starvell=None, **kwargs):
    """Обработка введённого session_cookie из FSM"""
    # Только авторизованный админ может вводить
    if not is_user_authorized(message.from_user.id):
        await message.answer("🔒 Только администратор может обновлять session_cookie")
        await state.clear()
        return

    new_cookie = (message.text or "").strip()
    if not new_cookie:
        await message.answer("❌ Пустой ключ. Отправьте /session_cookie и попробуйте снова.")
        await state.clear()
        return

    await message.answer("🔁 Сохраняю новый ключ и перезапускаю подключение...")

    try:
        config = get_config_manager()
        config.set('Starvell', 'session_cookie', new_cookie)
        BotConfig.reload()

        if starvell:
            await starvell.stop()
            await starvell.start()

            # Проверяем авторизацию
            user_info = await starvell.get_user_info()
            if user_info.get('authorized'):
                await message.answer("✅ Ключ успешно обновлён и авторизация выполнена.")
            else:
                await message.answer("⚠️ Ключ сохранён, но авторизация не удалась. Проверьте значение session_cookie.")
        else:
            await message.answer("✅ Ключ сохранён в конфиге. Перезапустите бота вручную для применения.")

    except Exception as e:
        await message.answer(f"❌ Ошибка при обновлении ключа: {e}")
        import logging
        logging.getLogger(__name__).exception("Ошибка при обновлении session_cookie")

    await state.clear()


@router.message(Command("profile"))
async def cmd_profile(message: Message, starvell, **kwargs):
    """Команда /profile - показать профиль продавца"""
    # Проверяем авторизацию
    if not is_user_authorized(message.from_user.id):
        return
    
    try:
        # Получаем информацию о пользователе
        user_info = await starvell.get_user_info()
        
        if not user_info.get("authorized"):
            await message.answer("❌ Не авторизован в Starvell")
            return
        
        user_data = user_info.get("user", {})
        text = _build_profile_text(user_data)

        # Кнопка для статистики
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="📊 Подробная статистика",
                callback_data="profile_stats"
            )],
            [InlineKeyboardButton(
                text="🔄 Обновить",
                callback_data="profile_refresh"
            )]
        ])

    # Балансы уже форматированы безопасно выше, замены не требуются

        await message.answer(text, reply_markup=keyboard)
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при получении профиля: {e}")


@router.callback_query(F.data == "profile_refresh")
async def callback_profile_refresh(callback: CallbackQuery, starvell, **kwargs):
    """Обновить информацию о профиле"""
    await callback.answer("🔄 Обновление...")
    
    try:
        # Получаем информацию о пользователе
        user_info = await starvell.get_user_info()
        
        if not user_info.get("authorized"):
            await callback.message.edit_text("❌ Не авторизован в Starvell")
            return
        
        user_data = user_info.get("user", {})
        text = _build_profile_text(user_data)
        
        # Кнопка для статистики
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="📊 Подробная статистика",
                callback_data="profile_stats"
            )],
            [InlineKeyboardButton(
                text="🔄 Обновить",
                callback_data="profile_refresh"
            )]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
        
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)


@router.callback_query(F.data == "profile_stats")
async def callback_profile_stats(callback: CallbackQuery, starvell, **kwargs):
    """Показать подробную статистику"""
    await callback.answer("📊 Загрузка статистики...")
    
    try:
        # Получаем заказы
        orders = await starvell.get_orders()
        
        # Анализируем статистику (проверка регистра статуса)
        total_orders = len(orders)
        completed_orders = sum(1 for order in orders if str(order.get("status")).upper() == "COMPLETED")
        cancelled_orders = sum(1 for order in orders if str(order.get("status")).upper() == "CANCELLED")
        active_orders = total_orders - completed_orders - cancelled_orders
        
        # Считаем доход: Starvell отдает суммы заказов в копейках.
        total_income = sum(
            _order_money_rub(order, "basePrice", "totalPrice", "price")
            for order in orders
            if str(order.get("status")).upper() == "COMPLETED"
        )
        
        # Считаем среднюю оценку
        reviews = [order.get("review", {}) for order in orders if order.get("review")]
        avg_rating = sum(r.get("rating", 0) for r in reviews) / len(reviews) if reviews else starvell.last_user_info.get("user", {}).get("rating", 0)
        
        # Статистика по датам
        from datetime import datetime, timedelta
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=7)
        month_start = today_start - timedelta(days=30)
        
        orders_today = 0
        orders_week = 0
        orders_month = 0
        income_today = 0
        income_week = 0
        income_month = 0
        
        for order in orders:
            if str(order.get("status")).upper() != "COMPLETED":
                continue
                
            created_at = order.get("createdAt")
            if not created_at:
                continue
                
            try:
                order_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                order_price = _order_money_rub(order, "basePrice", "totalPrice", "price")
                
                if order_date >= today_start:
                    orders_today += 1
                    income_today += order_price
                    
                if order_date >= week_start:
                    orders_week += 1
                    income_week += order_price
                    
                if order_date >= month_start:
                    orders_month += 1
                    income_month += order_price
            except:
                continue
        
        text = f"📊 <b>Подробная статистика</b>\n\n"
        text += f"📦 <b>Заказы:</b>\n"
        text += f"├ Всего: <code>{total_orders}</code>\n"
        text += f"├ Завершено: <code>{completed_orders}</code> ({completed_orders/total_orders*100 if total_orders else 0:.1f}%)\n"
        text += f"├ Активных: <code>{active_orders}</code>\n"
        text += f"└ Отменено: <code>{cancelled_orders}</code>\n\n"
        
        text += f"💰 <b>Доход (завершенные):</b>\n"
        text += f"├ За сегодня: <code>{_safe_float(income_today):.2f}</code> ₽ ({orders_today} зак.)\n"
        text += f"├ За неделю: <code>{_safe_float(income_week):.2f}</code> ₽ ({orders_week} зак.)\n"
        text += f"├ За месяц: <code>{_safe_float(income_month):.2f}</code> ₽ ({orders_month} зак.)\n"
        text += f"└ Всего: <code>{_safe_float(total_income):.2f}</code> ₽\n\n"
        
        text += f"⭐ <b>Отзывы:</b>\n"
        text += f"├ Средняя оценка: <code>{_safe_float(avg_rating):.2f}</code>\n"
        text += f"└ Всего отзывов: <code>{len(reviews)}</code>\n\n"
        
        if total_orders > 0:
            avg_order_value = _safe_float(total_income) / completed_orders if completed_orders else 0
            text += f"📈 <b>Средний чек:</b> <code>{_safe_float(avg_order_value):.2f}</code> ₽"
        
        # Кнопки управления
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="� Обновить статистику",
                callback_data="profile_stats"
            )],
            [InlineKeyboardButton(
                text="� Вернуться к профилю",
                callback_data="profile_back"
            )]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
        
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)


@router.callback_query(F.data == "profile_back")
async def callback_profile_back(callback: CallbackQuery, starvell, **kwargs):
    """Вернуться к профилю"""
    await callback.answer()
    
    # Получаем информацию о пользователе
    user_info = await starvell.get_user_info()
    
    if not user_info.get("authorized"):
        await callback.answer("❌ Не авторизован", show_alert=True)
        return
    
    user = user_info.get("user", {})
    username = user.get("username", "Неизвестно")
    user_id = user.get("id", "N/A")
    balance, hold_balance, total_balance = _extract_profile_metrics(user)
    verified = _format_verification_status(user)
    created_at = _format_starvell_datetime(user.get("createdAt"))
    
    # Получаем статистику
    orders = await starvell.get_orders()
    total_orders = len(orders)
    active_orders = sum(1 for o in orders if str(o.get("status")).upper() not in ["COMPLETED", "CANCELLED"])
    
    # Статистика по отзывам
    reviews = [o.get("review") for o in orders if o.get("review")]
    # Если нет отзывов по заказам, берем общий рейтинг из профиля
    if reviews:
        avg_rating = sum(r.get("rating", 0) for r in reviews) / len(reviews)
    else:
        avg_rating = _safe_float(user.get("rating", 0))
    
    text = f"👤 <b>Профиль</b>\n\n"
    text += f"<b>Имя:</b> {username}\n"
    text += f"<b>ID:</b> <code>{user_id}</code>\n"
    text += f"<b>Статус:</b> {verified}\n"
    text += f"<b>Регистрация:</b> {created_at}\n\n"
    text += f"💰 <b>Баланс:</b>\n"
    text += f"├ Доступно: <code>{balance:.2f}</code> ₽\n"
    text += f"├ Заморожено: <code>{hold_balance:.2f}</code> ₽\n"
    text += f"└ Всего: <code>{total_balance:.2f}</code> ₽\n\n"
    text += f"📦 <b>Заказы:</b>\n"
    text += f"├ Всего: <code>{total_orders}</code>\n"
    text += f"⭐ <b>Средняя оценка:</b> <code>{avg_rating:.2f}</code>"
    
    # Кнопки
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📊 Подробная статистика",
            callback_data="profile_stats"
        )],
        [InlineKeyboardButton(
            text="🔄 Обновить",
            callback_data="profile_refresh"
        )],
        [InlineKeyboardButton(
            text="🔙 Назад",
            callback_data=CBT.MAIN
        )]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.message(Command("logs"))
async def cmd_logs(message: Message, **kwargs):
    """Команда /logs - отправить логи"""
    # Проверяем авторизацию
    if not is_user_authorized(message.from_user.id):
        return
    
    from pathlib import Path
    from aiogram.types import FSInputFile, BufferedInputFile
    
    log_file = Path("logs/log.log")
    
    # Проверяем существование файла
    if not log_file.exists():
        await message.answer("❌ Файл логов не найден")
        return
    
    try:
        # Читаем последние ошибки из лога
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Ищем последнюю ошибку
        last_error = None
        error_lines = []
        
        error_markers = ("| ERROR |", "| FATAL |", " - ERROR - ", " [E] ")
        stop_markers = ("| INFO  |", "| WARN  |", "| DEBUG |", " - INFO - ", " [I] ", " - WARNING - ", " [W] ")

        for i in range(len(lines) - 1, -1, -1):
            line = lines[i]
            if any(marker in line for marker in error_markers):
                # Нашли ошибку, собираем её и следующие строки (traceback)
                error_lines = []
                for j in range(i, min(i + 20, len(lines))):
                    error_lines.append(lines[j])
                    if j > i and any(marker in lines[j] for marker in stop_markers):
                        break
                last_error = ''.join(error_lines)
                break
        
        # Формируем сообщение
        if last_error:
            error_msg = f"📋 <b>Последняя ошибка:</b>\n\n<code>{last_error[:3500]}</code>"
        else:
            error_msg = "✅ Ошибок не обнаружено"
        
        # Отправляем сообщение с краткой информацией об ошибке
        await message.answer(error_msg)
        # Отправим полный лог-файл как документ
        await message.answer_document(
            FSInputFile(str(log_file)),
            caption="📄 Полный лог-файл бота"
        )
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при чтении логов: {e}")


@router.message(Command("lot_test"))
async def cmd_lot_test(message: Message, state: FSMContext, **kwargs):
    """Тестовая команда ручного управления лотами"""
    if not is_user_authorized(message.from_user.id):
        return

    await state.clear()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Включить лот", callback_data="lot_test:activate")],
        [InlineKeyboardButton(text="🔴 Выключить лот", callback_data="lot_test:deactivate")],
        [InlineKeyboardButton(text="💰 Изменить цену", callback_data="lot_test:price")],
        [InlineKeyboardButton(text="🗑 Удалить лот", callback_data="lot_test:delete")],
    ])
    await message.answer(
        "🧪 <b>Тестовое управление лотом</b>\n\nВыберите действие.",
        reply_markup=keyboard,
    )


@router.message(Command("order_test"))
async def cmd_order_test(message: Message, starvell, **kwargs):
    """Диагностика: показать все поля последнего заказа."""
    if not is_user_authorized(message.from_user.id):
        return

    try:
        orders = await starvell.get_orders()
        if not orders:
            await message.answer("❌ Заказы не найдены.")
            return

        latest_order = max(orders, key=_order_sort_key)
        rendered = json.dumps(
            _normalize_for_json(latest_order),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )

        header = "🧾 <b>Последний заказ</b>\n\n"
        order_id = latest_order.get("id")
        if order_id:
            header += f"<b>ID:</b> <code>{order_id}</code>\n\n"

        max_payload_length = 3500
        if len(rendered) <= max_payload_length:
            await message.answer(f"{header}<pre>{rendered}</pre>")
            return

        preview = rendered[:max_payload_length]
        await message.answer(
            f"{header}<b>JSON слишком большой, показываю начало:</b>\n\n<pre>{preview}</pre>"
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка при получении последнего заказа: {e}")


@router.callback_query(F.data.startswith("lot_test:"))
async def callback_lot_test_action(callback: CallbackQuery, state: FSMContext, **kwargs):
    if not is_user_authorized(callback.from_user.id):
        await callback.answer()
        return

    action = callback.data.split(":", 1)[1]
    await state.update_data(lot_test_action=action)
    await state.set_state(LotTestState.waiting_for_lot_id)

    action_titles = {
        "activate": "включения",
        "deactivate": "выключения",
        "price": "изменения цены",
        "delete": "удаления",
    }
    await callback.message.edit_text(
        f"🧪 <b>Тест лота</b>\n\nОтправьте ID лота для {action_titles.get(action, action)}.",
    )
    await callback.answer()


@router.message(LotTestState.waiting_for_lot_id)
async def process_lot_test_lot_id(message: Message, state: FSMContext, starvell, **kwargs):
    if not is_user_authorized(message.from_user.id):
        await state.clear()
        return

    lot_id = (message.text or "").strip()
    if not lot_id.isdigit():
        await message.answer("❌ ID лота должен быть числом. Попробуйте ещё раз.")
        return

    data = await state.get_data()
    action = data.get("lot_test_action")
    await state.update_data(lot_id=lot_id)

    if action == "price":
        await state.set_state(LotTestState.waiting_for_price)
        await message.answer("💰 Отправьте новую цену для лота.")
        return

    try:
        if action == "activate":
            await starvell.activate_lot(lot_id)
            await message.answer(f"✅ Лот <code>{lot_id}</code> включен.")
        elif action == "deactivate":
            await starvell.deactivate_lot(lot_id)
            await message.answer(f"✅ Лот <code>{lot_id}</code> выключен.")
        elif action == "delete":
            await starvell.delete_lot(lot_id)
            await message.answer(f"✅ Лот <code>{lot_id}</code> удалён.")
        else:
            await message.answer("❌ Неизвестное действие.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
    finally:
        await state.clear()


@router.message(LotTestState.waiting_for_price)
async def process_lot_test_price(message: Message, state: FSMContext, starvell, **kwargs):
    if not is_user_authorized(message.from_user.id):
        await state.clear()
        return

    raw_price = (message.text or "").strip().replace(",", ".")
    try:
        price = float(raw_price)
    except ValueError:
        await message.answer("❌ Цена должна быть числом. Попробуйте ещё раз.")
        return

    data = await state.get_data()
    lot_id = data.get("lot_id")
    if not lot_id:
        await state.clear()
        await message.answer("❌ Не найден ID лота. Запустите /lot_test заново.")
        return

    try:
        await starvell.update_lot(lot_id, {"price": str(price)})
        await message.answer(f"✅ Цена лота <code>{lot_id}</code> обновлена на <code>{price}</code>.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
    finally:
        await state.clear()


@router.message(Command("restart"))
async def cmd_restart(message: Message, **kwargs):
    """Команда /restart - перезапустить бот"""
    # Проверяем авторизацию
    if not is_user_authorized(message.from_user.id):
        return
    
    import os
    import sys

    notifications = kwargs.get("notifications")
    starvell = kwargs.get("starvell")
    
    await message.answer(
        "🔄 <b>Перезапуск бота...</b>\n\n"
        "⏳ Бот будет перезапущен через несколько секунд"
    )

    if notifications and BotConfig.NOTIFY_BOT_STOP():
        try:
            user_info = await starvell.get_user_info() if starvell else {}
            user = user_info.get("user", {}) if isinstance(user_info, dict) else {}
            from datetime import datetime
            current_time = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
            stop_message = (
                f"<b>Аккаунт:</b> {user.get('username', 'Неизвестно')}\n"
                f"<b>ID:</b> <code>{user.get('id', 'N/A')}</code>\n\n"
                f"<b>Время остановки:</b> <code>{current_time}</code>\n"
                "<b>Причина:</b> ручной перезапуск\n"
            )
            await notifications.notify_all_admins(
                NotificationType.BOT_STOPPED,
                stop_message,
                force=False,
            )
        except Exception:
            pass
    
    # Даём время отправить сообщение
    await asyncio.sleep(1)
    
    # Перезапускаем процесс
    os.execv(sys.executable, [sys.executable] + sys.argv)


@router.message(AuthState.waiting_for_password)
async def process_password(message: Message, state: FSMContext):
    """Обработка ввода пароля"""
    password = message.text
    password_hash = hash_password(password)
    stored_hash = BotConfig.PASSWORD_HASH()
    
    # Удаляем сообщение с паролем
    try:
        await message.delete()
    except:
        pass
    
    if password_hash == stored_hash:
        # Пароль верный - авторизуем пользователя
        await authorize_user(message.from_user.id)
        await state.clear()
        
        await message.answer(
            "✅ Авторизация подтверждена.\n\n" + _build_home_panel_text(),
            reply_markup=get_main_menu()
        )
    else:
        # Пароль неверный
        await message.answer("❌ Неверный пароль. Попробуйте ещё раз:")


# === Callback обработчики ===

@router.callback_query(F.data == CBT.MAIN)
async def callback_main_menu(callback: CallbackQuery, **kwargs):
    """Главное меню"""
    await callback.answer()
    
    # Загружаем текущий язык
    
    await callback.message.edit_text(
        _build_home_panel_text(),
        reply_markup=get_main_menu()
    )


@router.callback_query(F.data == CBT.GLOBAL_SWITCHES)
async def callback_global_switches(callback: CallbackQuery):
    """Меню глобальных переключателей"""
    await callback.answer()
    
    # Загружаем текущий язык
    
    
    # Получаем текущие настройки
    auto_bump = BotConfig.AUTO_BUMP_ENABLED()
    auto_delivery = BotConfig.AUTO_DELIVERY_ENABLED()
    auto_restore = BotConfig.AUTO_RESTORE_ENABLED()
    auto_read = BotConfig.AUTO_READ_ENABLED()
    auto_ticket = BotConfig.AUTO_TICKET_ENABLED()
    order_confirm = BotConfig.ORDER_CONFIRM_RESPONSE_ENABLED()
    review_response = BotConfig.REVIEW_RESPONSE_ENABLED()
    
    # Формируем описание
    status_text = _build_automation_panel_text()
    
    await callback.message.edit_text(
        status_text,
        reply_markup=get_global_switches_menu(auto_bump, auto_delivery, auto_restore, auto_read, auto_ticket, order_confirm, review_response)
    )


@router.callback_query(F.data == CBT.SWITCH_AUTO_BUMP)
async def callback_switch_auto_bump(callback: CallbackQuery, auto_raise=None, **kwargs):
    """Переключить авто-поднятие"""
    # Переключаем
    current = BotConfig.AUTO_BUMP_ENABLED()
    BotConfig.update(**{"auto_bump.enabled": not current})
    
    # Если включили - триггерим немедленную проверку
    if not current and auto_raise:
        await auto_raise.trigger_immediate_check()
    
    # Загружаем текущий язык
    
    
    # Уведомление об изменении
    status = "включено" if not current else "выключено"
    await callback.answer(f"Авто-поднятие {status}", show_alert=False)
    
    # Обновляем меню
    auto_bump = not current
    auto_delivery = BotConfig.AUTO_DELIVERY_ENABLED()
    auto_restore = BotConfig.AUTO_RESTORE_ENABLED()
    auto_read = BotConfig.AUTO_READ_ENABLED()
    auto_ticket = BotConfig.AUTO_TICKET_ENABLED()
    order_confirm = BotConfig.ORDER_CONFIRM_RESPONSE_ENABLED()
    review_response = BotConfig.REVIEW_RESPONSE_ENABLED()
    
    status_text = _build_automation_panel_text()
    
    await callback.message.edit_text(
        status_text,
        reply_markup=get_global_switches_menu(auto_bump, auto_delivery, auto_restore, auto_read, auto_ticket, order_confirm, review_response)
    )


@router.callback_query(F.data == CBT.SWITCH_AUTO_DELIVERY)
async def callback_switch_auto_delivery(callback: CallbackQuery):
    """Переключить авто-выдачу"""
    # Переключаем
    current = BotConfig.AUTO_DELIVERY_ENABLED()
    BotConfig.update(**{"auto_delivery.enabled": not current})
    
    # Загружаем текущий язык
    
    
    # Уведомление об изменении
    status = "включена" if not current else "выключена"
    await callback.answer(f"Авто-выдача {status}", show_alert=False)
    
    # Обновляем меню
    auto_bump = BotConfig.AUTO_BUMP_ENABLED()
    auto_delivery = not current
    auto_restore = BotConfig.AUTO_RESTORE_ENABLED()
    auto_read = BotConfig.AUTO_READ_ENABLED()
    auto_ticket = BotConfig.AUTO_TICKET_ENABLED()
    order_confirm = BotConfig.ORDER_CONFIRM_RESPONSE_ENABLED()
    review_response = BotConfig.REVIEW_RESPONSE_ENABLED()
    
    status_text = _build_automation_panel_text()
    
    await callback.message.edit_text(
        status_text,
        reply_markup=get_global_switches_menu(auto_bump, auto_delivery, auto_restore, auto_read, auto_ticket, order_confirm, review_response)
    )


@router.callback_query(F.data == CBT.SWITCH_AUTO_RESTORE)
async def callback_switch_auto_restore(callback: CallbackQuery):
    """Переключить авто-восстановление"""
    # Переключаем
    current = BotConfig.AUTO_RESTORE_ENABLED()
    BotConfig.update(**{"auto_restore.enabled": not current})
    
    # Уведомление об изменении
    status = "включено" if not current else "выключено"
    await callback.answer(f"Авто-восстановление {status}", show_alert=False)
    
    # Обновляем меню
    auto_bump = BotConfig.AUTO_BUMP_ENABLED()
    auto_delivery = BotConfig.AUTO_DELIVERY_ENABLED()
    auto_restore = not current
    auto_read = BotConfig.AUTO_READ_ENABLED()
    auto_ticket = BotConfig.AUTO_TICKET_ENABLED()
    order_confirm = BotConfig.ORDER_CONFIRM_RESPONSE_ENABLED()
    review_response = BotConfig.REVIEW_RESPONSE_ENABLED()
    
    status_text = _build_automation_panel_text()
    
    await callback.message.edit_text(
        status_text,
        reply_markup=get_global_switches_menu(auto_bump, auto_delivery, auto_restore, auto_read, auto_ticket, order_confirm, review_response)
    )


@router.callback_query(F.data == CBT.SWITCH_AUTO_READ)
async def callback_switch_auto_read(callback: CallbackQuery):
    """Переключить авто-прочтение чатов"""
    # Переключаем
    current = BotConfig.AUTO_READ_ENABLED()
    BotConfig.update(**{"auto_read.enabled": not current})
    
    # Уведомление об изменении
    status = "включено" if not current else "выключено"
    await callback.answer(f"Авто-прочтение чатов {status}", show_alert=False)
    
    # Обновляем меню
    auto_bump = BotConfig.AUTO_BUMP_ENABLED()
    auto_delivery = BotConfig.AUTO_DELIVERY_ENABLED()
    auto_restore = BotConfig.AUTO_RESTORE_ENABLED()
    auto_read = not current
    auto_ticket = BotConfig.AUTO_TICKET_ENABLED()
    order_confirm = BotConfig.ORDER_CONFIRM_RESPONSE_ENABLED()
    review_response = BotConfig.REVIEW_RESPONSE_ENABLED()
    
    status_text = _build_automation_panel_text()
    
    await callback.message.edit_text(
        status_text,
        reply_markup=get_global_switches_menu(auto_bump, auto_delivery, auto_restore, auto_read, auto_ticket, order_confirm, review_response)
    )



@router.callback_query(F.data == CBT.SWITCH_USE_WATERMARK)
async def callback_switch_use_watermark(callback: CallbackQuery):
    """Переключить использование вотермарки в сообщениях"""
    current = BotConfig.USE_WATERMARK()
    BotConfig.update(**{"other.use_watermark": not current})

    status = "включено" if not current else "выключено"
    await callback.answer(f"Использование вотермарки {status}", show_alert=False)

    # Обновляем меню
    auto_bump = BotConfig.AUTO_BUMP_ENABLED()
    auto_delivery = BotConfig.AUTO_DELIVERY_ENABLED()
    auto_restore = BotConfig.AUTO_RESTORE_ENABLED()
    auto_read = BotConfig.AUTO_READ_ENABLED()
    auto_ticket = BotConfig.AUTO_TICKET_ENABLED()
    order_confirm = BotConfig.ORDER_CONFIRM_RESPONSE_ENABLED()
    review_response = BotConfig.REVIEW_RESPONSE_ENABLED()

    status_text = _build_automation_panel_text()

    await callback.message.edit_text(
        status_text,
        reply_markup=get_global_switches_menu(auto_bump, auto_delivery, auto_restore, auto_read, auto_ticket, order_confirm, review_response)
    )


@router.callback_query(F.data == CBT.AUTO_TICKET_SETTINGS)
async def callback_auto_ticket_settings(callback: CallbackQuery):
    """Меню настроек авто-тикета"""
    enabled = BotConfig.AUTO_TICKET_ENABLED()
    interval = BotConfig.AUTO_TICKET_INTERVAL()
    max_orders = BotConfig.AUTO_TICKET_MAX_ORDERS()
    notify = BotConfig.NOTIFY_AUTO_TICKET()
    
    text = (
        "🎫 <b>Настройки авто-тикета</b>\n\n"
        "Бот будет автоматически создавать тикеты для неподтверждённых заказов.\n"
        "Для работы требуется, чтобы бот был авторизован.\n\n"
        f"Статус: <b>{'Включено ✅' if enabled else 'Выключено ❌'}</b>"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=get_auto_ticket_settings_menu(enabled, interval, max_orders, notify)
    )

@router.callback_query(F.data == CBT.SWITCH_AUTO_TICKET_INTERNAL)
async def callback_switch_auto_ticket_internal(callback: CallbackQuery):
    """Переключить авто-тикет (внутри настроек)"""
    # Переключаем
    current = BotConfig.AUTO_TICKET_ENABLED()
    BotConfig.update(**{"auto_ticket.enabled": not current})
    
    # Уведомление об изменении
    status = "включен" if not current else "выключен"
    await callback.answer(f"Авто-тикет {status}", show_alert=False)
    
    # Обновляем меню настроек (остаемся в нем)
    enabled = not current
    interval = BotConfig.AUTO_TICKET_INTERVAL()
    max_orders = BotConfig.AUTO_TICKET_MAX_ORDERS()
    notify = BotConfig.NOTIFY_AUTO_TICKET()
    
    text = (
        "🎫 <b>Настройки авто-тикета</b>\n\n"
        "Бот будет автоматически создавать тикеты для неподтверждённых заказов.\n"
        "Для работы требуется, чтобы бот был авторизован.\n\n"
        f"Статус: <b>{'Включено ✅' if enabled else 'Выключено ❌'}</b>"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=get_auto_ticket_settings_menu(enabled, interval, max_orders, notify)
    )


@router.callback_query(F.data == CBT.SWITCH_AUTO_TICKET)
async def callback_switch_auto_ticket(callback: CallbackQuery):
    """Переключить авто-тикет (глобальное меню)"""
    # Переключаем
    current = BotConfig.AUTO_TICKET_ENABLED()
    BotConfig.update(**{"auto_ticket.enabled": not current})
    
    # Уведомление об изменении
    status = "включен" if not current else "выключен"
    await callback.answer(f"Авто-тикет {status}", show_alert=False)
    
    # Обновляем глобальное меню
    auto_bump = BotConfig.AUTO_BUMP_ENABLED()
    auto_delivery = BotConfig.AUTO_DELIVERY_ENABLED()
    auto_restore = BotConfig.AUTO_RESTORE_ENABLED()
    auto_read = BotConfig.AUTO_READ_ENABLED()
    auto_ticket = not current
    order_confirm = BotConfig.ORDER_CONFIRM_RESPONSE_ENABLED()
    review_response = BotConfig.REVIEW_RESPONSE_ENABLED()
    
    status_text = _build_automation_panel_text()
    
    await callback.message.edit_text(
        status_text,
        reply_markup=get_global_switches_menu(auto_bump, auto_delivery, auto_restore, auto_read, auto_ticket, order_confirm, review_response)
    )


@router.callback_query(F.data == CBT.SWITCH_AUTO_TICKET_NOTIFY)
async def callback_switch_auto_ticket_notify(callback: CallbackQuery):
    """Переключить уведомления авто-тикета"""
    current = BotConfig.NOTIFY_AUTO_TICKET()
    BotConfig.update(**{"notifications.auto_ticket": not current})
    
    await callback.answer(f"Уведомления {'включены' if not current else 'выключены'}", show_alert=False)
    
    # Обновляем меню
    enabled = BotConfig.AUTO_TICKET_ENABLED()
    interval = BotConfig.AUTO_TICKET_INTERVAL()
    max_orders = BotConfig.AUTO_TICKET_MAX_ORDERS()
    notify = not current
    
    text = (
        "🎫 <b>Настройки авто-тикета</b>\n\n"
        "Бот будет автоматически создавать тикеты для неподтверждённых заказов.\n"
        "Для работы требуется, чтобы бот был авторизован.\n\n"
        f"Статус: <b>{'Включено ✅' if enabled else 'Выключено ❌'}</b>"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=get_auto_ticket_settings_menu(enabled, interval, max_orders, notify)
    )


@router.callback_query(F.data == CBT.AUTO_TICKET_SET_INTERVAL)
async def callback_auto_ticket_set_interval(callback: CallbackQuery, state: FSMContext):
    """Запросить интервал проверки вручную"""
    await state.set_state(AutoTicketState.waiting_for_interval)
    await callback.message.answer(
        "⏱️ Введите интервал проверки в минутах (30-1440):\n\n"
        "Например: <code>60</code> (1 час)\n"
        "Отправьте /cancel для отмены",
    )
    await callback.answer()


@router.message(AutoTicketState.waiting_for_interval)
async def process_auto_ticket_interval(message: Message, state: FSMContext):
    """Обработать ввод интервала"""
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Отменено")
        return
    
    try:
        interval_minutes = int(message.text.strip())
        
        if interval_minutes < 30 or interval_minutes > 1440:
            await message.answer(
                "❌ Интервал должен быть от 30 до 1440 минут (24 часа)\n"
                "Попробуйте ещё раз или отправьте /cancel"
            )
            return
        
        interval_seconds = interval_minutes * 60
        BotConfig.update(**{"auto_ticket.interval": interval_seconds})
        await state.clear()
        
        await message.answer(
            f"✅ Интервал установлен: {interval_minutes} мин ({interval_seconds} сек)"
        )
        
    except ValueError:
        await message.answer(
            "❌ Неверный формат. Введите число от 30 до 1440\n"
            "Отправьте /cancel для отмены"
        )


@router.callback_query(F.data == CBT.AUTO_TICKET_SET_MAX)
async def callback_auto_ticket_set_max(callback: CallbackQuery, state: FSMContext):
    """Запросить макс. заказов вручную"""
    await state.set_state(AutoTicketState.waiting_for_max_orders)
    await callback.message.answer(
        "🔢 Введите максимальное количество заказов для обработки за раз (1-50):\n\n"
        "Например: <code>5</code>\n"
        "Отправьте /cancel для отмены",
    )
    await callback.answer()


@router.message(AutoTicketState.waiting_for_max_orders)
async def process_auto_ticket_max_orders(message: Message, state: FSMContext):
    """Обработать ввод макс. заказов"""
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Отменено")
        return
    
    try:
        max_orders = int(message.text.strip())
        
        if max_orders < 1 or max_orders > 50:
            await message.answer(
                "❌ Количество должно быть от 1 до 50\n"
                "Попробуйте ещё раз или отправьте /cancel"
            )
            return
        
        BotConfig.update(**{"auto_ticket.max_orders": max_orders})
        await state.clear()
        
        await message.answer(f"✅ Макс. заказов установлено: {max_orders}")
        
    except ValueError:
        await message.answer(
            "❌ Неверный формат. Введите число от 1 до 50\n"
            "Отправьте /cancel для отмены"
        )


@router.callback_query(F.data == CBT.SWITCH_ORDER_CONFIRM)
async def callback_switch_order_confirm(callback: CallbackQuery, auto_response, **kwargs):
    """Переключить авто-ответ на подтверждение заказа"""
    # Переключаем
    current = BotConfig.ORDER_CONFIRM_RESPONSE_ENABLED()
    new_state = not current
    BotConfig.update(**{"AutoResponse.orderConfirm": new_state})
    
    # Если включаем функцию - инициализируем существующие заказы
    if new_state:
        await auto_response._initialize_processed_orders()
    
    # Уведомление об изменении
    status = "включен" if new_state else "выключен"
    await callback.answer(f"Авто-ответ на подтверждение заказа {status}", show_alert=False)
    
    # Обновляем меню - возвращаемся в меню настройки ответа
    from tg_bot.full_keyboards import get_order_confirm_response_menu
    enabled = new_state
    text = BotConfig.ORDER_CONFIRM_RESPONSE_TEXT()
    
    message_text = (
        "✅ <b>Ответ на подтверждение заказа</b>\n\n"
        f"<b>Статус:</b> {'включено ✅' if enabled else 'выключено ❌'}\n\n"
        f"<b>Текущий текст ответа:</b>\n<i>{text}</i>\n\n"
        "При завершении заказа бот автоматически отправит это сообщение покупателю."
    )
    
    await callback.message.edit_text(
        message_text,
        reply_markup=get_order_confirm_response_menu(enabled, text)
    )


@router.callback_query(F.data == CBT.SWITCH_REVIEW_RESPONSE)
async def callback_switch_review_response(callback: CallbackQuery, auto_response, **kwargs):
    """Переключить авто-ответ на отзыв"""
    # Переключаем
    current = BotConfig.REVIEW_RESPONSE_ENABLED()
    new_state = not current
    BotConfig.update(**{"AutoResponse.reviewResponse": new_state})
    
    # Если включаем функцию - инициализируем существующие заказы
    if new_state:
        await auto_response._initialize_processed_orders()
    
    # Уведомление об изменении
    status = "включен" if new_state else "выключен"
    await callback.answer(f"Авто-ответ на отзыв {status}", show_alert=False)
    
    # Обновляем меню - возвращаемся в меню настройки ответа
    from tg_bot.full_keyboards import get_review_response_menu
    enabled = new_state
    text = BotConfig.REVIEW_RESPONSE_TEXT()
    
    message_text = (
        "⭐ <b>Ответ на отзыв</b>\n\n"
        f"<b>Статус:</b> {'включено ✅' if enabled else 'выключено ❌'}\n\n"
        f"<b>Текущий текст ответа:</b>\n<i>{text}</i>\n\n"
        "При получении отзыва бот автоматически отправит это сообщение."
    )
    
    await callback.message.edit_text(
        message_text,
        reply_markup=get_review_response_menu(enabled, text)
    )


@router.callback_query(F.data == "empty")
async def callback_empty(callback: CallbackQuery):
    """Пустой callback (для неактивных кнопок)"""
    await callback.answer()


@router.callback_query(F.data == CBT.AUTO_DELIVERY)
async def callback_auto_delivery_menu(callback: CallbackQuery, auto_delivery, **kwargs):
    """Меню автовыдачи"""
    await callback.answer()
    
    lots = await auto_delivery.get_lots()
    
    keyboard = get_auto_delivery_lots_menu(lots, offset=0)
    
    text = "📦 <b>Лоты с автовыдачей</b>\n\n"
    text += f"Всего лотов: <code>{len(lots)}</code>"
    
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data == CBT.BLACKLIST)
async def callback_blacklist_menu(callback: CallbackQuery, **kwargs):
    """Меню чёрного списка"""
    await callback.answer()
    
    # Получаем список из конфига
    blacklist = []
    config = get_config_manager()
    if config._config.has_section("Blacklist"):
        sections = [s for s in config._config.sections() if s.startswith("Blacklist.")]
        
        for section in sections:
            username = section.replace("Blacklist.", "", 1)
            block_delivery = BotConfig.get(f"{section}.block_delivery", True, bool)
            block_response = BotConfig.get(f"{section}.block_response", True, bool)
            
            blacklist.append({
                "username": username,
                "block_delivery": block_delivery,
                "block_response": block_response
            })
    
    keyboard = get_blacklist_menu(blacklist, offset=0)
    
    text = "🚫 <b>Чёрный список</b>\n\n"
    text += f"Заблокировано пользователей: <code>{len(blacklist)}</code>"
    
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data == CBT.PLUGINS)
async def callback_modules_registry(callback: CallbackQuery, extension_hub, **kwargs):
    """Меню модулей"""
    await callback.answer()
    
    modules_data = []
    for uuid, module_card in extension_hub.plugins.items():
        modules_data.append({
            "uuid": uuid,
            "name": module_card.name,
            "version": module_card.version,
            "description": module_card.description,
            "enabled": module_card.enabled
        })
    
    keyboard = get_modules_menu(modules_data, offset=0)
    text = _build_modules_panel_text(modules_data)
    
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data == CBT.ABOUT)
async def callback_about(callback: CallbackQuery):
    """Показать информацию о боте и ссылки автора"""
    await callback.answer()

    text = _build_about_panel_text()

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Связаться", url="https://t.me/kortkk")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data=CBT.MAIN)]
    ])

    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data == CBT.NOTIFICATIONS)
async def callback_notifications(callback: CallbackQuery):
    """Меню настроек уведомлений"""
    await callback.answer()

    await _refresh_notifications_menu(callback)


@router.callback_query(F.data == CBT.NOTIF_MESSAGES)
async def callback_notif_messages(callback: CallbackQuery):
    """Переключить уведомления о новых сообщениях"""
    current = BotConfig.NOTIFY_NEW_MESSAGES()
    BotConfig.update(**{"notifications.new_messages": not current})
    
    
    status = "включены" if not current else "выключены"
    await callback.answer(f"Уведомления о сообщениях {status}", show_alert=False)
    
    await _refresh_notifications_menu(callback)


@router.callback_query(F.data == CBT.NOTIF_ALL_MESSAGES)
async def callback_notif_all_messages(callback: CallbackQuery):
    """Переключить режим всех новых сообщений / только непрочитанных."""
    current = BotConfig.NOTIFY_ALL_MESSAGES()
    BotConfig.update(**{"notifications.all_messages": not current})

    mode = "все новые сообщения" if not current else "только непрочитанные"
    await callback.answer(f"Теперь будут приходить: {mode}", show_alert=False)
    await _refresh_notifications_menu(callback)


@router.callback_query(F.data == CBT.NOTIF_OWN_MESSAGES)
async def callback_notif_own_messages(callback: CallbackQuery):
    """Переключить уведомления о собственных сообщениях."""
    current = BotConfig.NOTIFY_OWN_MESSAGES()
    BotConfig.update(**{"notifications.own_messages": not current})

    status = "включены" if not current else "выключены"
    await callback.answer(f"Уведомления о своих сообщениях {status}", show_alert=False)
    await _refresh_notifications_menu(callback)


@router.callback_query(F.data == CBT.NOTIF_ORDERS)
async def callback_notif_orders(callback: CallbackQuery):
    """Переключить уведомления о новых заказах"""
    current = BotConfig.NOTIFY_NEW_ORDERS()
    BotConfig.update(**{"notifications.new_orders": not current})
    
    
    status = "включены" if not current else "выключены"
    await callback.answer(f"Уведомления о заказах {status}", show_alert=False)
    
    await _refresh_notifications_menu(callback)


@router.callback_query(F.data == CBT.NOTIF_SUPPORT_MESSAGES)
async def callback_notif_support_messages(callback: CallbackQuery):
    """Переключить уведомления о сообщениях от поддержки"""
    current = BotConfig.NOTIFY_SUPPORT_MESSAGES()
    BotConfig.update(**{"notifications.support_messages": not current})
    
    
    status = "включены" if not current else "выключены"
    await callback.answer(f"Уведомления от поддержки {status}", show_alert=False)
    
    await _refresh_notifications_menu(callback)


@router.callback_query(F.data == CBT.NOTIF_RESTORE)
async def callback_notif_restore(callback: CallbackQuery):
    """Переключить уведомления о восстановлении лота"""
    current = BotConfig.NOTIFY_LOT_RESTORE()
    BotConfig.update(**{"notifications.lot_restore": not current})
    
    
    status = "включены" if not current else "выключены"
    await callback.answer(f"Уведомления о восстановлении {status}", show_alert=False)
    
    await _refresh_notifications_menu(callback)


@router.callback_query(F.data == CBT.NOTIF_START)
async def callback_notif_start(callback: CallbackQuery):
    """Переключить уведомления о запуске бота"""
    current = BotConfig.NOTIFY_BOT_START()
    BotConfig.update(**{"notifications.bot_start": not current})
    
    
    status = "включены" if not current else "выключены"
    await callback.answer(f"Уведомления о запуске {status}", show_alert=False)
    
    await _refresh_notifications_menu(callback)



@router.callback_query(F.data == CBT.NOTIF_AUTO_RESPONSES)
async def callback_notif_auto_responses(callback: CallbackQuery):
    """Переключить уведомления при выполнении автоответов/команд"""
    current = BotConfig.NOTIFY_AUTO_RESPONSES()
    BotConfig.update(**{"notifications.auto_responses": not current})

    status = "включены" if not current else "выключены"
    await callback.answer(f"Уведомления автоответов {status}", show_alert=False)

    await _refresh_notifications_menu(callback)


@router.callback_query(F.data == CBT.NOTIF_ORDER_CONFIRMED)
async def callback_notif_order_confirmed(callback: CallbackQuery):
    """Переключить уведомления о подтверждении заказа"""
    current = BotConfig.NOTIFY_ORDER_CONFIRMED()
    BotConfig.update(**{"notifications.order_confirmed": not current})

    status = "включены" if not current else "выключены"
    await callback.answer(f"Уведомления о подтверждении заказа {status}", show_alert=False)

    await _refresh_notifications_menu(callback)


@router.callback_query(F.data == CBT.NOTIF_AUTO_TICKET)
async def callback_notif_auto_ticket(callback: CallbackQuery):
    """Переключить уведомления об отправке авто-тикета"""
    current = BotConfig.NOTIFY_AUTO_TICKET()
    BotConfig.update(**{"notifications.auto_ticket": not current})

    status = "включены" if not current else "выключены"
    await callback.answer(f"Уведомления авто-тикета {status}", show_alert=False)

    await _refresh_notifications_menu(callback)


@router.callback_query(F.data == CBT.NOTIF_STOP)
async def callback_notif_stop(callback: CallbackQuery):
    """Переключить уведомления об остановке бота"""
    current = BotConfig.NOTIFY_BOT_STOP()
    BotConfig.update(**{"notifications.bot_stop": not current})

    status = "включены" if not current else "выключены"
    await callback.answer(f"Уведомления об остановке бота {status}", show_alert=False)

    await _refresh_notifications_menu(callback)


@router.callback_query(F.data == CBT.NOTIF_REVIEW)
async def callback_notif_review(callback: CallbackQuery):
    """Переключить уведомления о получении отзывов"""
    current = BotConfig.NOTIFY_REVIEW()
    BotConfig.update(**{"notifications.review": not current})

    status = "включены" if not current else "выключены"
    await callback.answer(f"Уведомления о получении отзыва {status}", show_alert=False)

    await _refresh_notifications_menu(callback)


@router.callback_query(F.data == CBT.NOTIF_REVIEW_DELETED)
async def callback_notif_review_deleted(callback: CallbackQuery):
    """Переключить уведомления об удалении отзывов"""
    current = BotConfig.NOTIFY_REVIEW_DELETED()
    BotConfig.update(**{"notifications.review_deleted": not current})

    status = "включены" if not current else "выключены"
    await callback.answer(f"Уведомления об удалении отзыва {status}", show_alert=False)

    await _refresh_notifications_menu(callback)





# === Обработчик кнопки "Ответить" из уведомлений ===

@router.callback_query(F.data.startswith("r:"))
async def handle_reply_button(callback: CallbackQuery, state: FSMContext, **kwargs):
    """Обработка нажатия кнопки 'Ответить' в уведомлении"""
    # Извлекаем chat_id из callback data (формат: r:chat_id)
    chat_id = callback.data.split(":", 1)[1]
    
    # Сохраняем chat_id в состояние
    await state.update_data(reply_chat_id=chat_id)
    await state.set_state(ReplyState.waiting_for_reply)
    
    await callback.answer()
    await callback.message.answer(
        "✍️ <b>Быстрый ответ</b>\n\n"
        "Отправьте сообщение, которое хотите отправить пользователю.\n\n"
        "Для отмены используйте /cancel",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="reply_cancel")]
        ])
    )


@router.callback_query(F.data == "reply_cancel")
async def handle_reply_cancel(callback: CallbackQuery, state: FSMContext):
    """Отмена быстрого ответа"""
    await state.clear()
    await callback.answer("Отменено")
    await callback.message.delete()


@router.message(ReplyState.waiting_for_reply)
async def process_quick_reply(message: Message, state: FSMContext, **kwargs):
    """Обработка отправки быстрого ответа"""
    # Получаем starvell из kwargs
    starvell = kwargs.get('starvell')
    
    if not starvell:
        await message.answer("❌ Ошибка: сервис Starvell недоступен")
        await state.clear()
        return
    
    # Получаем сохраненный chat_id
    data = await state.get_data()
    chat_id = data.get("reply_chat_id")
    
    if not chat_id:
        await message.answer("❌ Ошибка: не удалось определить чат")
        await state.clear()
        return
    
    # Отправляем сообщение
    try:
        status_msg = await message.answer("📤 Отправка сообщения...")
        
        result = await starvell.send_message(chat_id, message.text)
        
        await status_msg.edit_text(
            "✅ <b>Сообщение отправлено!</b>\n\n"
            f"💬 Текст: <code>{message.text[:100]}</code>"
        )
        
        # Очищаем состояние
        await state.clear()
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при отправке: {e}")
        await state.clear()


# === Обработчик кнопки "Вернуть деньги" ===

@router.callback_query(F.data.startswith("refund:"))
async def handle_refund_button(callback: CallbackQuery):
    """Обработка нажатия кнопки 'Вернуть деньги' - запрос подтверждения"""
    order_id = callback.data.split(":", 1)[1]
    ORDER_ACTION_CONTEXT[_order_action_context_key(callback)] = {
        "order_id": order_id,
        "original_markup": callback.message.reply_markup,
    }

    confirm_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Да, вернуть",
                callback_data=f"refund_confirm:{order_id}"
            ),
            InlineKeyboardButton(
                text="❌ Нет",
                callback_data="refund_cancel"
            )
        ]
    ])
    
    await callback.message.edit_reply_markup(reply_markup=confirm_keyboard)
    await callback.answer("⚠️ Подтвердите возврат денег", show_alert=True)


@router.callback_query(F.data.startswith("review_reply:"))
async def handle_review_reply_button(callback: CallbackQuery, state: FSMContext):
    """Запрос текста ответа на отзыв."""
    review_id = callback.data.split(":", 1)[1]
    order_id = _extract_order_id_from_markup(callback.message.reply_markup)
    if not order_id:
        await callback.answer("❌ Не удалось определить заказ для ответа на отзыв", show_alert=True)
        return

    REVIEW_REPLY_CONTEXT[callback.from_user.id] = {
        "review_id": review_id,
        "order_id": order_id,
        "message_id": callback.message.message_id,
        "chat_id": callback.message.chat.id,
    }
    await state.set_state(ReviewReplyState.waiting_for_text)
    await callback.message.answer("💬 Отправьте текст ответа на отзыв или <code>-</code> для отмены.", parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("review_delete:"))
async def handle_review_delete_button(callback: CallbackQuery):
    """Запрос подтверждения удаления ответа на отзыв."""
    response_id = callback.data.split(":", 1)[1]
    order_id = _extract_order_id_from_markup(callback.message.reply_markup)
    if not order_id:
        await callback.answer("❌ Не удалось определить заказ для удаления ответа", show_alert=True)
        return

    ORDER_ACTION_CONTEXT[_order_action_context_key(callback)] = {
        "order_id": order_id,
        "review_id": "",
        "review_response_id": response_id,
        "original_markup": callback.message.reply_markup,
    }
    confirm_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Да, удалить",
                callback_data=f"review_delete_confirm:{response_id}"
            ),
            InlineKeyboardButton(
                text="❌ Нет",
                callback_data="refund_cancel"
            )
        ]
    ])
    await callback.message.edit_reply_markup(reply_markup=confirm_keyboard)
    await callback.answer("⚠️ Подтвердите удаление ответа на отзыв", show_alert=True)


@router.callback_query(F.data.startswith("confirm:"))
async def handle_confirm_order(callback: CallbackQuery, **kwargs):
    """Обработка подтверждения заказа"""
    short_order_id = callback.data.split(":", 1)[1]
    
    # Получаем starvell из kwargs
    starvell = kwargs.get('starvell')
    
    if not starvell:
        await callback.answer("❌ Ошибка: сервис Starvell недоступен", show_alert=True)
        return
    
    try:
        # Подтверждаем заказ
        await callback.answer("⏳ Подтверждение заказа...", show_alert=False)
        
        result = await starvell.confirm_order(short_order_id)
        
        # Обновляем сообщение
        await callback.message.edit_text(
            callback.message.text + "\n\n✅ <b>Заказ подтверждён!</b>",
            reply_markup=None
        )
        
    except Exception as e:
        await callback.answer(f"❌ Ошибка при подтверждении: {str(e)}", show_alert=True)


@router.callback_query(F.data.startswith("complete:"))
async def handle_complete_button(callback: CallbackQuery):
    """Запрос подтверждения ручной отметки заказа выполненным."""
    order_id = callback.data.split(":", 1)[1]
    ORDER_ACTION_CONTEXT[_order_action_context_key(callback)] = {
        "order_id": order_id,
        "original_markup": callback.message.reply_markup,
    }

    confirm_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Да, подтвердить",
                callback_data=f"complete_confirm:{order_id}"
            ),
            InlineKeyboardButton(
                text="❌ Нет",
                callback_data="refund_cancel"
            )
        ]
    ])

    await callback.message.edit_reply_markup(reply_markup=confirm_keyboard)
    await callback.answer("⚠️ Подтвердите выполнение заказа", show_alert=True)


@router.callback_query(F.data.startswith("complete_confirm:"))
async def handle_mark_seller_completed(callback: CallbackQuery, **kwargs):
    """Обработка ручной отметки заказа выполненным."""
    order_id = callback.data.split(":", 1)[1]
    starvell = kwargs.get('starvell')

    if not starvell:
        await callback.answer("❌ Ошибка: сервис Starvell недоступен", show_alert=True)
        return

    try:
        await callback.answer("⏳ Отмечаю заказ выполненным...", show_alert=False)
        await starvell.mark_seller_completed(order_id)
        context = ORDER_ACTION_CONTEXT.pop(_order_action_context_key(callback), {})
        original_markup = context.get("original_markup")
        reduced_markup = _strip_order_action_buttons(original_markup, keep_refund=True)
        await callback.message.edit_text(
            callback.message.text + "\n\n✅ <b>Заказ отмечен выполненным.</b>",
            reply_markup=reduced_markup
        )
    except Exception as e:
        await callback.answer(f"❌ Ошибка при подтверждении выполнения: {str(e)}", show_alert=True)


@router.callback_query(F.data.startswith("refund_confirm:"))
async def handle_refund_confirm(callback: CallbackQuery, **kwargs):
    """Подтверждение возврата денег"""
    order_id = callback.data.split(":", 1)[1]
    
    # Получаем starvell из kwargs
    starvell = kwargs.get('starvell')
    
    if not starvell:
        await callback.answer("❌ Ошибка: сервис Starvell недоступен", show_alert=True)
        return
    
    try:
        # Выполняем возврат
        await callback.answer("⏳ Выполняется возврат...", show_alert=False)
        
        await starvell.refund_order(order_id)
        context = ORDER_ACTION_CONTEXT.pop(_order_action_context_key(callback), {})
        original_markup = context.get("original_markup")
        reduced_markup = _strip_order_action_buttons(original_markup)
        
        # Обновляем сообщение
        await callback.message.edit_text(
            callback.message.text + "\n\n💰 <b>Деньги возвращены!</b>",
            reply_markup=reduced_markup
        )
        
    except Exception as e:
        await callback.answer(f"❌ Ошибка при возврате: {str(e)}", show_alert=True)


@router.callback_query(F.data == "refund_cancel")
async def handle_refund_cancel(callback: CallbackQuery):
    """Отмена возврата денег"""
    context = ORDER_ACTION_CONTEXT.pop(_order_action_context_key(callback), {})
    original_markup = context.get("original_markup")
    if original_markup:
        await callback.message.edit_reply_markup(reply_markup=original_markup)
    await callback.answer("Отменено")


@router.message(ReviewReplyState.waiting_for_text)
async def process_review_reply_text(message: Message, state: FSMContext, **kwargs):
    """Обработка текста ответа на отзыв."""
    starvell = kwargs.get("starvell")
    if not starvell:
        await message.answer("❌ Ошибка: сервис Starvell недоступен")
        REVIEW_REPLY_CONTEXT.pop(message.from_user.id, None)
        await state.clear()
        return

    context = REVIEW_REPLY_CONTEXT.get(message.from_user.id)
    if not context:
        await message.answer("❌ Контекст ответа на отзыв потерян")
        await state.clear()
        return

    text = (message.text or "").strip()
    if text == "-":
        REVIEW_REPLY_CONTEXT.pop(message.from_user.id, None)
        await state.clear()
        await message.answer("Отменено.")
        return

    try:
        response_result = await starvell.create_review_response(
            review_id=context["review_id"],
            content=text,
            order_id=context["order_id"],
        )

        await message.answer("✅ Ответ на отзыв отправлен.")

        try:
            response_id = str(
                (response_result.get("reviewResponse") or {}).get("id")
                or response_result.get("id")
                or ""
            )

            await message.bot.edit_message_reply_markup(
                chat_id=context["chat_id"],
                message_id=context["message_id"],
                reply_markup=_build_review_reply_markup(
                    order_id=context["order_id"],
                    review_id=context["review_id"],
                    response_id=response_id or None,
                ),
            )
        except Exception:
            pass
    except Exception as e:
        await message.answer(f"❌ Ошибка при отправке ответа на отзыв: {e}")
    finally:
        REVIEW_REPLY_CONTEXT.pop(message.from_user.id, None)
        await state.clear()


@router.callback_query(F.data.startswith("review_delete_confirm:"))
async def handle_review_delete_confirm(callback: CallbackQuery, **kwargs):
    """Подтверждение удаления ответа на отзыв."""
    response_id = callback.data.split(":", 1)[1]
    starvell = kwargs.get("starvell")
    if not starvell:
        await callback.answer("❌ Ошибка: сервис Starvell недоступен", show_alert=True)
        return

    context = ORDER_ACTION_CONTEXT.pop(_order_action_context_key(callback), {})
    order_id = context.get("order_id") or _extract_order_id_from_markup(callback.message.reply_markup)
    original_markup = context.get("original_markup")
    if not order_id:
        await callback.answer("❌ Не удалось определить заказ", show_alert=True)
        return

    try:
        await callback.answer("⏳ Удаляю ответ на отзыв...", show_alert=False)
        await starvell.delete_review_response(response_id, order_id)
        review_id = context.get("review_id")
        if not review_id:
            try:
                order_details = await starvell.get_order_details(order_id)
                page_props = order_details.get("pageProps", {})
                bff = page_props.get("bff") or {}
                review = (
                    page_props.get("review")
                    or (page_props.get("order") or {}).get("review")
                    or bff.get("review")
                    or (bff.get("order") or {}).get("review")
                    or {}
                )
                review_id = str(review.get("id") or "")
            except Exception:
                review_id = ""
        await callback.message.edit_reply_markup(
            reply_markup=_build_review_reply_markup(order_id=order_id, review_id=review_id or None),
        )
        await callback.answer("Ответ на отзыв удалён", show_alert=False)
    except Exception as e:
        if original_markup:
            await callback.message.edit_reply_markup(reply_markup=original_markup)
        await callback.answer(f"❌ Ошибка при удалении ответа: {e}", show_alert=True)

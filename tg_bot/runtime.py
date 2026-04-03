"""
Главный файл бота
"""

import asyncio
import logging
import sys
from pathlib import Path
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from support.runtime_config import BotConfig, get_config_manager
from tg_bot.notifications import init_notifications, NotificationType
from support.usage_stats import log_event
from support.runtime_storage import Database
from workflows.starvell_service import StarvellService
from tg_bot.main_handlers import router
from tg_bot.middlewares import AuthMiddleware
from workflows.background_tasks import BackgroundTasks
from workflows.auto_delivery import AutoDeliveryService
from workflows.auto_restore import AutoRestoreService
from workflows.auto_raise import AutoRaiseService
from workflows.manual_update import ManualUpdateService
from workflows.keep_alive import KeepAliveService
from workflows.auto_response import AutoResponseService
from support.extension_hub import ExtensionHub
from tg_bot.plugin_cp import init_modules_cp


logger = logging.getLogger(__name__)


def _log_plain_block(text: str, color: str = "cyan") -> None:
    logger.info(text, extra={"plain_block": True, "block_color": color})


def _log_startup_banner() -> None:
    from version import VERSION

    _log_plain_block(
        "\n"
        " ___      ___ _______   ___       ________  ________  ________     \n"
        "|\\  \\    /  /|\\  ___ \\ |\\  \\     |\\   __  \\|\\   __  \\|\\   __  \\    \n"
        "\\ \\  \\  /  / | \\   __/|\\ \\  \\    \\ \\  \\|\\  \\ \\  \\|\\  \\ \\  \\|\\  \\   \n"
        " \\ \\  \\/  / / \\ \\  \\_|/_\\ \\  \\    \\ \\  \\\\\\  \\ \\   _  _\\ \\   __  \\  \n"
        "  \\ \\    / /   \\ \\  \\_|\\ \\ \\  \\____\\ \\  \\\\\\  \\ \\  \\\\  \\\\ \\  \\ \\  \\ \n"
        "   \\ \\__/ /     \\ \\_______\\ \\_______\\ \\_______\\ \\__\\\\ _\\\\ \\__\\ \\__\\\n"
        "    \\|__|/       \\|_______|\\|_______|\\|_______|\\|__|\\|__|\\|__|\\|__|\n"
        "\n"
        "                     StarvellVelora\n"
        f"                      версия {VERSION}\n"
        "                      tg: @kortkk",
        color="cyan",
    )


def _log_profile_summary(user: dict) -> None:
    username = user.get("username") or "неизвестно"
    nickname = user.get("nickname") or username
    user_id = user.get("id", "N/A")
    email = user.get("email") or "не указана"

    _log_plain_block(
        "\n"
        "┌─ Профиль Starvell\n"
        f"│ Логин : {username}\n"
        f"│ Ник   : {nickname}\n"
        f"│ ID    : {user_id}\n"
        f"│ Почта : {email}\n"
        "└─ Авторизация подтверждена",
        color="blue",
    )


async def main():
    """Главная функция бота (вызывается из главного main.py)"""
    _log_startup_banner()

    # Валидация конфигурации
    try:
        BotConfig.validate()
        BotConfig.ensure_dirs()
    except ValueError as e:
        logger.error(f"Ошибка конфигурации: {e}")
        logger.error("Проверьте configs/_main.cfg")
        return
    
    # Инициализация компонентов
    session = AiohttpSession(proxy=BotConfig.TELEGRAM_PROXY()) if BotConfig.TELEGRAM_PROXY() else AiohttpSession()
    bot = Bot(
        token=BotConfig.BOT_TOKEN(),
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()
    
    # Устанавливаем меню команд
    commands = [
        BotCommand(command="menu", description="🧭 Хаб управления"),
        BotCommand(command="profile", description="🪪 Паспорт продавца"),
        BotCommand(command="order_test", description="🧾 Последний заказ"),
        BotCommand(command="update", description="📦 Ручное обновление"),
        BotCommand(command="logs", description="🗒 Журнал узла"),
        BotCommand(command="restart", description="♻️ Перезапуск узла"),
        BotCommand(command="session_cookie", description="🪪 Обновить сессию"),
        BotCommand(command="lot_test", description="🧪 Проверка лота"),
    ]
    await bot.set_my_commands(commands)
    logger.info("Меню команд установлено")
    
    try:
        await bot.set_my_short_description(
            "🧭 StarvellVelora — хаб управления для автоматизации Starvell\n\n📢 Новости: @starvell_velora\n🧩 Плагины: @velora_plugins"
        )
        
        description = (
            "🧭 StarvellVelora — хаб управления для автоматизации Starvell.com\n\n"
            "Контакты:\n"
            "💬 Автор: @kortkk\n"
            "📢 Канал с новостями: @starvell_velora\n"
            "🧩 Канал с плагинами: @velora_plugins\n"
        )
        await bot.set_my_description(description)
        logger.info("Описание бота установлено")
    except Exception as e:
        logger.warning(f"Не удалось установить описание бота: {e}")
    
    # База данных (JSON хранилище)
    db = Database(storage_dir=BotConfig.STORAGE_DIR())
    await db.connect()
    
    # Сервис Starvell
    starvell = StarvellService(db)
    
    # Инициализация системы уведомлений
    from tg_bot.notifications import init_notifications
    notifications = init_notifications(bot, starvell)
    logger.info("Система уведомлений инициализирована")
    
    # Сервис авто-выдачи (без зависимостей)
    auto_delivery = AutoDeliveryService()
    
    # Сервис авто-восстановления (требует auto_delivery для проверки товаров)
    auto_restore = AutoRestoreService(starvell, auto_delivery)
    
    # Сервис авто-поднятия
    auto_raise = AutoRaiseService(starvell)
    
    # Сервис ручного обновления
    updater = ManualUpdateService(Path(__file__).resolve().parent.parent)
    
    # Сервис вечного онлайна
    keep_alive = KeepAliveService(starvell)
    
    # Сервис автоответов
    auto_response = AutoResponseService(starvell, db)
    
    # Сервис авто-тикетов
    from workflows.autoticket import init_autoticket_service
    # Получаем сессию напрямую из конфига
    session_cookie = get_config_manager().get('Starvell', 'session_cookie', '')
    autoticket_service = init_autoticket_service(session_cookie)
    
    # Центр расширений
    extension_hub = ExtensionHub()
    extension_hub.discover_extensions()
    
    notifications.extension_hub = extension_hub
    
    # Инициализируем панель управления модулями
    init_modules_cp(bot, extension_hub, router)
    logger.info("Реестр модулей инициализирован")
    
    # Регистрируем обработчики расширений
    extension_hub.attach_router(router)
    logger.info("Обработчики расширений зарегистрированы")
    
    try:
        await starvell.start()
        await auto_delivery.start()
        await auto_restore.start()
        await auto_raise.start()
        await keep_alive.start()
        await auto_response.start()
        
        # Запускаем init-хуки расширений
        await extension_hub.execute_handlers(extension_hub.init_handlers, bot, starvell, db, extension_hub)
        
        # Проверяем авторизацию
        user_info = await starvell.get_user_info()
        if not user_info.get("authorized"):
            # Не отправляем нотификацию здесь, чтобы не дублировать логику
            # уведомления, уже реализованную в StarvellService._notify_session_error().
            logger.error("Не удалось авторизоваться в Starvell! Продолжаю работу без авторизации.")
            logger.error("Проверьте session_cookie в configs/_main.cfg")
            
        user = user_info.get("user", {})
        
        # Обновляем имя бота только если оно реально изменилось,
        # чтобы не ловить flood control на каждом старте.
        nickname = user.get("nickname") or user.get("username") or "Trader"
        desired_bot_name = f"{nickname} | StarvellVelora"
        try:
            current_name = await bot.get_my_name()
            if getattr(current_name, "name", "") != desired_bot_name:
                await bot.set_my_name(desired_bot_name)
        except Exception as e:
            logger.warning(f"Не удалось изменить имя бота: {e}")
            
        _log_profile_summary(user)
        
    except Exception as e:
        logger.error(f"Ошибка при подключении к Starvell: {e}")
        logger.exception("Детальная информация об ошибке:")
        await auto_response.stop()
        await keep_alive.stop()
        await auto_raise.stop()
        await auto_restore.stop()
        await auto_delivery.stop()
        await starvell.stop()
        await db.close()
        return
        
    # Middleware для проверки доступа
    dp.message.middleware(AuthMiddleware())
    dp.callback_query.middleware(AuthMiddleware())
    
    # Регистрируем роутер
    dp.include_router(router)
    
    # Добавляем зависимости в контекст
    dp.workflow_data.update({
        "starvell": starvell,
        "db": db,
        "auto_delivery": auto_delivery,
        "auto_restore": auto_restore,
        "auto_raise": auto_raise,
        "updater": updater,
        "auto_response": auto_response,
        "autoticket_service": autoticket_service,
        "extension_hub": extension_hub,
    })
    
    # Фоновые задачи
    tasks = BackgroundTasks(bot, starvell, db, notifications, auto_response)
    tasks.start()
    
    # Уведомляем админов о запуске
    if BotConfig.NOTIFY_BOT_START():
        try:
            from datetime import datetime
            from version import VERSION
            
            # Формируем детальное уведомление
            current_time = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
            
            message = (
                f"<b>Аккаунт:</b> {user.get('username', 'Неизвестно')}\n"
                f"<b>ID:</b> <code>{user.get('id', 'N/A')}</code>\n\n"
                f"<b>Версия бота:</b> <code>{VERSION}</code>\n"
                f"<b>Время запуска:</b> <code>{current_time}</code>\n\n"
            )
            
            await notifications.notify_all_admins(
                NotificationType.BOT_STARTED,
                message,
                force=False
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить уведомление о запуске: {e}")
            
        logger.info("✅ Бот успешно запущен!")
        # Записываем событие в usage_stats
        try:
            from version import VERSION
            log_event("bot_started", f"version={VERSION} user={user.get('username')} id={user.get('id')} time={current_time}")
        except Exception:
            log_event("bot_started", f"user={user.get('username')} id={user.get('id')} time={current_time}")
    
    # Запускаем стартовые хуки расширений
    await extension_hub.execute_handlers(extension_hub.start_handlers, bot, starvell, db, extension_hub)
    
    try:
        # Запускаем polling
        await dp.start_polling(bot)
    finally:
        # Очистка
        logger.info("Остановка бота...")
        
        # Запускаем stop-хуки расширений
        await extension_hub.execute_handlers(extension_hub.stop_handlers, bot, starvell, db, extension_hub)
        
        tasks.stop()
        await keep_alive.stop()
        await auto_raise.stop()
        await auto_restore.stop()
        await auto_delivery.stop()
        await starvell.stop()
        await db.close()
        
        
        # Логируем остановку
        try:
            log_event("bot_stopped", "clean shutdown")
        except Exception:
            pass
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)

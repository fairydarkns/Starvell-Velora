"""Telegram-хаб управления подключаемыми модулями."""

from __future__ import annotations
from typing import TYPE_CHECKING
import logging
from pathlib import Path

if TYPE_CHECKING:
    from support.extension_hub import ExtensionHub

from aiogram import F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from tg_bot.full_keyboards import CBT
from tg_bot.plugin_keyboards import modules_list, edit_module, module_commands


logger = logging.getLogger("ModulesCP")


def _build_module_card_text(module_card) -> str:
    text = (
        f"<b><i>{module_card.name} v{module_card.version}</i></b>\n\n"
        f"{module_card.description}\n\n"
        f"<b><i>UUID:</i></b> <code>{module_card.uuid}</code>\n"
        f"<b><i>Автор:</i></b> {module_card.author}\n"
        f"<b><i>Статус:</i></b> {'🔹 Активен' if module_card.enabled else '▫️ На паузе'}\n"
    )

    if module_card.commands:
        text += "\n<b><i>Команды модуля:</i></b>\n"
        for cmd, desc in module_card.commands.items():
            text += f"• <code>/{cmd}</code> — {desc or 'Без описания'}\n"

    return text


class ModuleUploadState(StatesGroup):
    """Состояния для загрузки модулей"""
    waiting_for_file = State()


def init_modules_cp(bot, extension_hub: "ExtensionHub", router, *args):
    """
    Инициализация панели управления модулями.
    Регистрирует обработчики для работы с расширениями через Telegram.
    
    :param bot: Экземпляр бота
    :param extension_hub: Центр модулей
    :param router: Router для регистрации обработчиков
    """
    
    async def check_module_exists(uuid: str, message: Message) -> bool:
        """
        Проверяет существование модуля по UUID.
        Если модуль не существует - отправляет сообщение с кнопкой обновления.
        
        :param uuid: UUID модуля
        :param message: Telegram сообщение
        :return: True если модуль существует, False если нет
        """
        if uuid not in extension_hub.plugins:
            keyboard = modules_list(extension_hub, CBT, 0)
            text = f"❌ Модуль с UUID `{uuid}` не найден.\n\nВозможно он уже был удалён."
            await bot.edit_message_text(
                text=text,
                chat_id=message.chat.id,
                message_id=message.message_id,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            return False
        return True
    
    @router.callback_query(F.data.startswith(f"{CBT.PLUGINS_LIST}:"))
    async def open_modules_list(callback: CallbackQuery):
        """Открывает список модулей"""
        await callback.answer()
        
        offset = int(callback.data.split(":")[1])
        
        keyboard = modules_list(extension_hub, CBT, offset)
        
        total = len(extension_hub.plugins)
        enabled = sum(1 for p in extension_hub.plugins.values() if p.enabled)
        
        text = (
            "🧩 *Реестр плагинов*\n\n"
            f"• Всего модулей: {total}\n"
            f"• Активно: {enabled}\n"
            f"• На паузе: {total - enabled}\n\n"
            "⚠️ *После изменения состава модулей выполните* /restart"
        )
        
        await callback.message.edit_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    
    @router.callback_query(F.data.startswith(f"{CBT.EDIT_PLUGIN}:"))
    async def open_module_card(callback: CallbackQuery):
        """Открывает панель управления модулем"""
        await callback.answer()
        
        parts = callback.data.split(":")
        uuid, offset = parts[1], int(parts[2])
        
        if not await check_module_exists(uuid, callback.message):
            return
        
        module_card = extension_hub.plugins[uuid]
        
        keyboard = edit_module(module_card, CBT, uuid, int(offset), ask_delete=False)
        
        await callback.message.edit_text(
            text=_build_module_card_text(module_card),
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    
    @router.callback_query(F.data.startswith(f"{CBT.PLUGIN_COMMANDS}:"))
    async def open_module_commands(callback: CallbackQuery):
        """Открывает список команд модуля"""
        await callback.answer()
        
        parts = callback.data.split(":")
        uuid, offset = parts[1], int(parts[2])
        
        if not await check_module_exists(uuid, callback.message):
            return
        
        module_card = extension_hub.plugins[uuid]
        
        if not module_card.commands:
            await callback.answer("У этого модуля нет команд", show_alert=True)
            return
        
        commands_text = []
        for cmd, desc in module_card.commands.items():
            commands_text.append(f"/{cmd} - {desc}")
        
        text = (
            f"⌨️ *Команды модуля {module_card.name}*\n\n"
            + "\n\n".join(commands_text)
        )
        
        keyboard = module_commands(module_card, CBT, uuid, int(offset))
        
        await callback.message.edit_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    
    @router.callback_query(F.data.startswith(f"{CBT.TOGGLE_PLUGIN}:"))
    async def toggle_module(callback: CallbackQuery):
        """Включает/выключает модуль"""
        await callback.answer()
        
        parts = callback.data.split(":")
        uuid, offset = parts[1], int(parts[2])
        
        if not await check_module_exists(uuid, callback.message):
            return
        
        extension_hub.switch_module(uuid)
        module_card = extension_hub.plugins[uuid]
        
        status = "активирован" if module_card.enabled else "поставлен на паузу"
        logger.info(
            f"Пользователь {callback.from_user.username} ({callback.from_user.id}) "
            f"{status} модуль {module_card.name}"
        )
        
        # Обновляем меню
        callback.data = f"{CBT.EDIT_PLUGIN}:{uuid}:{offset}"
        await open_module_card(callback)
    
    @router.callback_query(F.data.startswith(f"{CBT.DELETE_PLUGIN}:"))
    async def ask_delete_module(callback: CallbackQuery):
        """Запрашивает подтверждение удаления модуля"""
        await callback.answer()
        
        parts = callback.data.split(":")
        uuid, offset = parts[1], int(parts[2])
        
        if not await check_module_exists(uuid, callback.message):
            return
        
        module_card = extension_hub.plugins[uuid]
        keyboard = edit_module(module_card, CBT, uuid, int(offset), ask_delete=True)
        
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    
    @router.callback_query(F.data.startswith(f"{CBT.CANCEL_DELETE_PLUGIN}:"))
    async def cancel_delete_module(callback: CallbackQuery):
        """Отменяет удаление модуля"""
        await callback.answer()
        
        parts = callback.data.split(":")
        uuid, offset = parts[1], int(parts[2])
        
        if not await check_module_exists(uuid, callback.message):
            return
        
        module_card = extension_hub.plugins[uuid]
        keyboard = edit_module(module_card, CBT, uuid, int(offset), ask_delete=False)
        
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    
    @router.callback_query(F.data.startswith(f"{CBT.CONFIRM_DELETE_PLUGIN}:"))
    async def delete_module(callback: CallbackQuery):
        """Удаляет модуль"""
        await callback.answer()
        
        parts = callback.data.split(":")
        uuid, offset = parts[1], int(parts[2])
        
        if not await check_module_exists(uuid, callback.message):
            return
        
        module_card = extension_hub.plugins[uuid]
        module_name = module_card.name
        
        # Удаляем модуль
        if extension_hub.remove_module(uuid):
            logger.info(
                f"Пользователь {callback.from_user.username} ({callback.from_user.id}) "
                f"удалил модуль {module_name}"
            )
            
            await callback.answer(f"✅ Модуль {module_name} удалён", show_alert=True)
            
            # Возвращаемся к списку
            callback.data = f"{CBT.PLUGINS_LIST}:{offset}"
            await open_modules_list(callback)
        else:
            await callback.answer("❌ Ошибка при удалении модуля", show_alert=True)
    
    @router.callback_query(F.data.startswith(CBT.UPLOAD_PLUGIN))
    async def act_upload_module(callback: CallbackQuery, state: FSMContext):
        """Активирует режим загрузки модуля"""
        await callback.answer()
        
        # Получаем offset из callback data или используем 0 по умолчанию
        parts = callback.data.split(":")
        offset = int(parts[1]) if len(parts) > 1 else 0
        
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="❌ Отмена",
                callback_data=f"{CBT.PLUGINS_LIST}:{offset}"
            )]
        ])
        
        await callback.message.edit_text(
            text=(
                "📥 *Импорт модуля*\n\n"
                "Отправьте файл модуля (`.py`) в этот чат.\n\n"
                "⚠️ *Внимание!* Подключайте только проверенные модули."
            ),
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
        await state.set_state(ModuleUploadState.waiting_for_file)
        await state.update_data(offset=offset)
    
    @router.message(ModuleUploadState.waiting_for_file, F.document)
    async def upload_module(message: Message, state: FSMContext):
        """Обрабатывает загрузку файла модуля"""
        data = await state.get_data()
        offset = data.get("offset", 0)
        await state.clear()
        
        # Проверяем расширение файла
        if not message.document.file_name.endswith('.py'):
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="🔙 Назад",
                    callback_data=f"{CBT.PLUGINS_LIST}:{offset}"
                )]
            ])
            
            await message.answer(
                "❌ Неверный формат файла. Ожидается `.py` файл.",
                reply_markup=keyboard
            )
            return
        
        # Скачиваем файл
        file = await bot.get_file(message.document.file_id)
        file_path = Path("plugins") / message.document.file_name
        
        await bot.download_file(file.file_path, file_path)
        
        logger.info(
            f"[ВАЖНО] Пользователь @{message.from_user.username} ({message.from_user.id}) "
            f"загрузил модуль {file_path}"
        )
        
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="🔙 Назад",
                callback_data=f"{CBT.PLUGINS_LIST}:{offset}"
            )]
        ])
        
        await message.answer(
            f"✅ Модуль `{message.document.file_name}` загружен!\n\n"
            "⚠️ После изменения состава модулей выполните /restart.",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )


# Экспорт функции инициализации для системы расширений
BIND_TO_PRE_INIT = [init_modules_cp]

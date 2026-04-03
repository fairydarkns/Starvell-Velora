"""
Хэндлеры панели управления чёрным списком
"""

import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from tg_bot.full_keyboards import (
    get_blacklist_menu,
    get_blacklist_user_edit_menu,
    get_back_button
)
from support.runtime_config import BotConfig, get_config_manager

logger = logging.getLogger(__name__)

router = Router()


class BlacklistStates(StatesGroup):
    """Состояния для чёрного списка"""
    waiting_username = State()


# ==================== Список заблокированных ====================

@router.callback_query(F.data.startswith("bl_list:"))
async def show_blacklist(callback: CallbackQuery, db, **kwargs):
    """Показать чёрный список"""
    try:
        offset = int(callback.data.split(":")[1])
        
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
        
        keyboard = get_blacklist_menu(blacklist, offset)
        
        text = "🚫 <b>Чёрный список</b>\n\n"
        text += f"Заблокировано пользователей: <code>{len(blacklist)}</code>"
        
        await callback.message.edit_text(
            text,
            reply_markup=keyboard
        )
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка показа чёрного списка: {e}", exc_info=True)
        await callback.answer("❌ Ошибка при загрузке", show_alert=True)


@router.callback_query(F.data == "bl_add")
async def add_to_blacklist(callback: CallbackQuery, state: FSMContext):
    """Начать добавление пользователя в ЧС"""
    await state.set_state(BlacklistStates.waiting_username)
    
    await callback.message.answer(
        "✏️ <b>Добавление в чёрный список</b>\n\n"
        "Введите ID пользователя:\n\n"
        "Отправьте /cancel для отмены",
        reply_markup=get_back_button("bl_list:0")
    )
    await callback.answer()


@router.message(BlacklistStates.waiting_username)
async def process_blacklist_username(message: Message, state: FSMContext):
    """Обработать добавление в ЧС"""
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Отменено")
        return
    
    user_id = message.text.strip()
    
    # Проверяем, не в ЧС ли уже
    section = f"Blacklist.{user_id}"
    
    config = get_config_manager()
    if config._config.has_section(section):
        await message.answer(
            f"❌ Пользователь <b>@{user_id}</b> уже в чёрном списке!",
            reply_markup=get_back_button("bl_list:0")
        )
        return
    
    try:
        # Добавляем в ЧС с дефолтными настройками
        if not config._config.has_section("Blacklist"):
            config._config.add_section("Blacklist")
        
        BotConfig.update(f"{section}.block_delivery", True)
        BotConfig.update(f"{section}.block_response", True)
        
        await state.clear()
        
        await message.answer(
            f"✅ Пользователь <b>@{user_id}</b> добавлен в чёрный список!\n\n"
            "По умолчанию блокируется автовыдача и автоответы.",
            reply_markup=get_back_button("bl_list:0")
        )
        
        logger.info(f"Пользователь @{user_id} добавлен в ЧС юзером {message.from_user.id}")
        
    except Exception as e:
        logger.error(f"Ошибка добавления в ЧС: {e}", exc_info=True)
        await message.answer("❌ Ошибка при добавлении")


# ==================== Редактирование пользователя ====================

@router.callback_query(F.data.startswith("bl_edit:"))
async def edit_blacklist_user(callback: CallbackQuery, **kwargs):
    """Редактировать пользователя в ЧС"""
    try:
        user_index = int(callback.data.split(":")[1])
        offset = int(callback.data.split(":")[2])
        
        # Получаем пользователя
        config = get_config_manager()
        sections = [s for s in config._config.sections() if s.startswith("Blacklist.")]
        
        if user_index >= len(sections):
            await callback.answer("❌ Пользователь не найден", show_alert=True)
            return
        
        section = sections[user_index]
        username = section.replace("Blacklist.", "", 1)
        
        block_delivery = BotConfig.get(f"{section}.block_delivery", True, bool)
        block_response = BotConfig.get(f"{section}.block_response", True, bool)
        
        user_data = {
            "username": username,
            "block_delivery": block_delivery,
            "block_response": block_response
        }
        
        text = f"🚫 <b>@{username}</b>\n\n"
        text += f"{'✅' if block_delivery else '❌'} Блокировать автовыдачу\n"
        text += f"{'✅' if block_response else '❌'} Блокировать автоответы\n"
        
        keyboard = get_blacklist_user_edit_menu(user_index, offset, user_data)
        
        await callback.message.edit_text(
            text,
            reply_markup=keyboard
        )
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка редактирования пользователя ЧС: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("bl_toggle:"))
async def toggle_blacklist_setting(callback: CallbackQuery, **kwargs):
    """Переключить настройку блокировки"""
    try:
        # bl_toggle:setting:user_index:offset
        parts = callback.data.split(":")
        setting = parts[1]
        user_index = int(parts[2])
        offset = int(parts[3])
        
        config = get_config_manager()
        sections = [s for s in config._config.sections() if s.startswith("Blacklist.")]
        
        if user_index >= len(sections):
            await callback.answer("❌ Пользователь не найден", show_alert=True)
            return
        
        section = sections[user_index]
        username = section.replace("Blacklist.", "", 1)
        
        # Переключаем настройку
        current_value = BotConfig.get(f"{section}.{setting}", True, bool)
        BotConfig.update(f"{section}.{setting}", not current_value)
        
        logger.info(f"Настройка {setting} для @{username} изменена на {not current_value}")
        
        # Обновляем меню
        callback.data = f"bl_edit:{user_index}:{offset}"
        await edit_blacklist_user(callback)
        
    except Exception as e:
        logger.error(f"Ошибка переключения настройки ЧС: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("bl_delete:"))
async def delete_from_blacklist(callback: CallbackQuery, **kwargs):
    """Удалить пользователя из ЧС"""
    try:
        user_index = int(callback.data.split(":")[1])
        
        config = get_config_manager()
        sections = [s for s in config._config.sections() if s.startswith("Blacklist.")]
        
        if user_index >= len(sections):
            await callback.answer("❌ Пользователь не найден", show_alert=True)
            return
        
        section = sections[user_index]
        username = section.replace("Blacklist.", "", 1)
        
        config._config.remove_section(section)
        config.save()
        
        logger.info(f"Пользователь @{username} удалён из ЧС юзером {callback.from_user.id}")
        
        await callback.message.edit_text(
            f"✅ Пользователь <b>@{username}</b> удалён из чёрного списка",
            reply_markup=get_back_button("bl_list:0")
        )
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка удаления из ЧС: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


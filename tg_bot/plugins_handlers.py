"""Хэндлеры реестра модулей."""

import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from tg_bot.full_keyboards import get_modules_menu, get_module_info_menu

logger = logging.getLogger(__name__)

router = Router()


def _build_modules_overview(plugins_data: list[dict]) -> str:
    enabled_count = sum(1 for item in plugins_data if item["enabled"])
    disabled_count = len(plugins_data) - enabled_count
    return (
        "🧩 <b>Реестр плагинов</b>\n\n"
        f"• Всего: <code>{len(plugins_data)}</code>\n"
        f"• Активно: <code>{enabled_count}</code>\n"
        f"• На паузе: <code>{disabled_count}</code>\n\n"
        "После изменения состава модулей выполните <code>/restart</code>."
    )


# ==================== Список модулей ====================

@router.callback_query(F.data.startswith("plugins_list:"))
async def show_modules_list(callback: CallbackQuery, extension_hub, **kwargs):
    """Показать список модулей"""
    try:
        offset = int(callback.data.split(":")[1])
        
        modules_data = []
        for uuid, module_card in extension_hub.plugins.items():
            modules_data.append({
                "uuid": uuid,
                "name": module_card.name,
                "version": module_card.version,
                "description": module_card.description,
                "enabled": module_card.enabled
            })
        
        keyboard = get_modules_menu(modules_data, offset)
        
        text = _build_modules_overview(modules_data)
        
        await callback.message.edit_text(
            text,
            reply_markup=keyboard
        )
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка показа списка модулей: {e}", exc_info=True)
        await callback.answer("❌ Ошибка при загрузке", show_alert=True)


# ==================== Просмотр модуля ====================

@router.callback_query(F.data.startswith("plugin_info:"))
async def show_module_info(callback: CallbackQuery, extension_hub, **kwargs):
    """Показать информацию о модуле"""
    try:
        uuid = callback.data.split(":")[1]
        offset = int(callback.data.split(":")[2])
        
        if uuid not in extension_hub.plugins:
            await callback.answer("❌ Модуль не найден", show_alert=True)
            return
        
        module_card = extension_hub.plugins[uuid]
        
        text = f"🧩 <b>{module_card.name}</b>\n\n"
        text += f"<b>Версия:</b> {module_card.version}\n"
        text += f"<b>Автор:</b> {module_card.author}\n"
        text += f"<b>UUID:</b> <code>{uuid}</code>\n\n"
        text += f"<b>Описание:</b>\n{module_card.description}\n\n"
        text += f"<b>Статус:</b> {'🔹 Активен' if module_card.enabled else '▫️ На паузе'}"
        
        keyboard = get_module_info_menu(uuid, offset, module_card.enabled)
        
        await callback.message.edit_text(
            text,
            reply_markup=keyboard
        )
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка показа информации о модуле: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


# ==================== Переключение модуля ====================

@router.callback_query(F.data.startswith("plugin_toggle:"))
async def toggle_module(callback: CallbackQuery, extension_hub, **kwargs):
    """Переключить модуль"""
    try:
        uuid = callback.data.split(":")[1]
        offset = int(callback.data.split(":")[2])
        
        if uuid not in extension_hub.plugins:
            await callback.answer("❌ Модуль не найден", show_alert=True)
            return
        
        # Переключаем
        extension_hub.switch_module(uuid)
        
        # Получаем обновлённый статус
        module_card = extension_hub.plugins[uuid]
        status_text = "активирован" if module_card.enabled else "поставлен на паузу"
        
        logger.info(f"Модуль {module_card.name} {status_text} пользователем {callback.from_user.id}")
        
        # Обновляем текст и клавиатуру
        text = f"🧩 <b>{module_card.name}</b>\n\n"
        text += f"<b>Версия:</b> {module_card.version}\n"
        text += f"<b>Автор:</b> {module_card.author}\n"
        text += f"<b>UUID:</b> <code>{uuid}</code>\n\n"
        text += f"<b>Описание:</b>\n{module_card.description}\n\n"
        text += f"<b>Статус:</b> {'🔹 Активен' if module_card.enabled else '▫️ На паузе'}\n\n"
        text += "После изменения состава модулей выполните <code>/restart</code>."
        
        keyboard = get_module_info_menu(uuid, offset, module_card.enabled)
        
        await callback.message.edit_text(
            text,
            reply_markup=keyboard
        )
        
        # Уведомление
        await callback.answer(f"Модуль {status_text}", show_alert=False)
        
    except Exception as e:
        logger.error(f"Ошибка переключения модуля: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


# ==================== Удаление модуля ====================

@router.callback_query(F.data.startswith("plugin_delete_ask:"))
async def module_delete_ask(callback: CallbackQuery, extension_hub, **kwargs):
    """Подтверждение удаления модуля"""
    try:
        uuid = callback.data.split(":")[1]
        offset = int(callback.data.split(":")[2])
        
        if uuid not in extension_hub.plugins:
            await callback.answer("❌ Модуль не найден", show_alert=True)
            return
        
        module_card = extension_hub.plugins[uuid]
        
        text = f"⚠️ <b>Удаление модуля</b>\n\n"
        text += f"Вы уверены, что хотите удалить модуль:\n"
        text += f"<b>{module_card.name}</b> v{module_card.version}?\n\n"
        text += f"<i>Файл модуля будет удалён безвозвратно.</i>"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Да, удалить",
                    callback_data=f"plugin_delete_confirm:{uuid}:{offset}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data=f"plugin_info:{uuid}:{offset}"
                )
            ]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка при запросе удаления модуля: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("plugin_delete_confirm:"))
async def module_delete_confirm(callback: CallbackQuery, extension_hub, **kwargs):
    """Подтверждённое удаление модуля"""
    try:
        uuid = callback.data.split(":")[1]
        offset = int(callback.data.split(":")[2])
        
        if uuid not in extension_hub.plugins:
            await callback.answer("❌ Модуль не найден", show_alert=True)
            return
        
        module_card = extension_hub.plugins[uuid]
        module_name = module_card.name
        
        success = extension_hub.remove_module(uuid)
        
        if success:
            logger.info(f"Модуль {module_name} удалён пользователем {callback.from_user.id}")
            await callback.answer(f"✅ Модуль {module_name} удалён", show_alert=True)
            
            modules_data = []
            for p_uuid, module_card in extension_hub.plugins.items():
                modules_data.append({
                    "uuid": p_uuid,
                    "name": module_card.name,
                    "version": module_card.version,
                    "description": module_card.description,
                    "enabled": module_card.enabled
                })
            
            keyboard = get_modules_menu(modules_data, offset)
            
            text = _build_modules_overview(modules_data)
            
            await callback.message.edit_text(text, reply_markup=keyboard)
        else:
            await callback.answer("❌ Ошибка при удалении", show_alert=True)
        
    except Exception as e:
        logger.error(f"Ошибка удаления модуля: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)

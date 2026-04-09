"""
Хэндлеры панели управления автовыдачей 
"""

import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from tg_bot.full_keyboards import (
    get_auto_delivery_lots_menu,
    get_lot_edit_menu,
    get_back_button
)
from support.runtime_config import BotConfig

logger = logging.getLogger(__name__)

router = Router()


def _is_cancel_text(text: str | None) -> bool:
    return (text or "").strip() in {"-", "/cancel"}


class AutoDeliveryStates(StatesGroup):
    """Состояния для автовыдачи"""
    waiting_lot_name = State()
    waiting_delivery_text = State()
    waiting_products_file = State()
    waiting_products = State()


# ==================== Список лотов ====================

@router.callback_query(F.data.startswith("ad_lots_list:"))
async def show_lots_list(callback: CallbackQuery, auto_delivery, **kwargs):
    """Показать список лотов с автовыдачей"""
    try:
        offset = int(callback.data.split(":")[1])
        
        lots = await auto_delivery.get_lots()
        
        keyboard = get_auto_delivery_lots_menu(lots, offset)
        
        text = "📦 <b>Лоты с автовыдачей</b>\n\n"
        text += f"Всего лотов: <code>{len(lots)}</code>"
        
        await callback.message.edit_text(
            text,
            reply_markup=keyboard
        )
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка показа списка лотов: {e}", exc_info=True)
        await callback.answer("❌ Ошибка при загрузке списка", show_alert=True)


@router.callback_query(F.data == "ad_add_lot")
async def add_lot_manual(callback: CallbackQuery, state: FSMContext):
    """Активировать режим добавления лота вручную"""
    await state.set_state(AutoDeliveryStates.waiting_lot_name)
    
    await callback.message.answer(
        "📝 Введите название лота для привязки автовыдачи:\n\n"
        "Отправьте /cancel для отмены",
        reply_markup=get_back_button("ad_lots_list:0")
    )
    await callback.answer()


@router.message(AutoDeliveryStates.waiting_lot_name)
async def process_lot_name(message: Message, state: FSMContext, auto_delivery, **kwargs):
    """Обработать название лота"""
    if _is_cancel_text(message.text):
        await state.clear()
        await message.answer("❌ Отменено")
        return
    
    lot_name = message.text.strip()
    
    # Проверяем, не существует ли уже
    lots = await auto_delivery.get_lots()
    if any(lot.get("name") == lot_name for lot in lots):
        await message.answer(
            f"❌ Лот <b>{lot_name}</b> уже существует!",
            reply_markup=get_back_button("ad_lots_list:0")
        )
        return
    
    # Создаём лот с автовыдачей
    try:
        await auto_delivery.add_lot(
            name=lot_name,
            response_text="Спасибо за покупку, $username!\n\nВот твой товар:\n\n$product"
        )
        
        await state.clear()
        
        await message.answer(
            f"✅ Лот <b>{lot_name}</b> добавлен!\n\n"
            "Теперь вы можете настроить автовыдачу для него.",
            reply_markup=get_back_button("ad_lots_list:0")
        )
        
        logger.info(f"Лот {lot_name} добавлен пользователем {message.from_user.id}")
        
    except Exception as e:
        logger.error(f"Ошибка добавления лота: {e}", exc_info=True)
        await message.answer("❌ Ошибка при добавлении лота")


# ==================== Редактирование лота ====================

@router.callback_query(F.data.startswith("ad_edit_lot:"))
async def edit_lot(callback: CallbackQuery, auto_delivery, **kwargs):
    """Показать меню редактирования лота"""
    try:
        lot_index = int(callback.data.split(":")[1])
        offset = int(callback.data.split(":")[2])
        
        lots = await auto_delivery.get_lots()
        
        if lot_index >= len(lots):
            await callback.answer("❌ Лот не найден", show_alert=True)
            return
        
        lot = lots[lot_index]
        
        # Формируем текст информации о лоте
        text = f"📦 <b>{lot.get('name')}</b>\n\n"
        text += f"<b>Текст выдачи:</b>\n<code>{lot.get('response_text', 'Не установлен')}</code>\n\n"
        
        products_file = lot.get('products_file')
        if products_file:
            products_count = await auto_delivery.count_products(products_file)
            text += f"<b>Файл товаров:</b> <code>{products_file}</code>\n"
            text += f"<b>Товаров в файле:</b> <code>{products_count}</code>\n\n"
        else:
            text += "<i>Файл товаров не привязан</i>\n\n"
        
        # Настройки
        text += "<b>Настройки:</b>\n"
        text += f"{'✅' if lot.get('enabled', True) else '❌'} Автовыдача включена\n"
        text += f"{'✅' if lot.get('disable_on_empty', False) else '❌'} Деактивация при опустошении\n"
        text += f"{'✅' if lot.get('disable_auto_restore', False) else '❌'} Отключить авто-восстановление\n"
        
        keyboard = get_lot_edit_menu(lot_index, offset, lot)
        
        await callback.message.edit_text(
            text,
            reply_markup=keyboard
        )
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка редактирования лота: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("ad_toggle:"))
async def toggle_lot_setting(callback: CallbackQuery, auto_delivery, **kwargs):
    """Переключить настройку лота"""
    try:
        # ad_toggle:setting:lot_index:offset
        parts = callback.data.split(":")
        setting = parts[1]
        lot_index = int(parts[2])
        offset = int(parts[3])
        
        lots = await auto_delivery.get_lots()
        if lot_index >= len(lots):
            await callback.answer("❌ Лот не найден", show_alert=True)
            return
        
        lot = lots[lot_index]
        
        # Переключаем настройку
        current_value = lot.get(setting, False)
        await auto_delivery.update_lot_setting(
            lot.get('name'),
            setting,
            not current_value
        )
        
        logger.info(f"Настройка {setting} лота {lot.get('name')} изменена на {not current_value}")
        
        # Обновляем меню
        callback.data = f"ad_edit_lot:{lot_index}:{offset}"
        await edit_lot(callback, auto_delivery=auto_delivery)
        
    except Exception as e:
        logger.error(f"Ошибка переключения настройки: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("ad_delete_lot:"))
async def delete_lot(callback: CallbackQuery, auto_delivery, **kwargs):
    """Удалить лот"""
    try:
        lot_index = int(callback.data.split(":")[1])
        
        lots = await auto_delivery.get_lots()
        if lot_index >= len(lots):
            await callback.answer("❌ Лот не найден", show_alert=True)
            return
        
        lot = lots[lot_index]
        lot_name = lot.get('name')
        
        await auto_delivery.delete_lot(lot_name)
        
        logger.info(f"Лот {lot_name} удалён пользователем {callback.from_user.id}")
        
        await callback.message.edit_text(
            f"✅ Лот <b>{lot_name}</b> удалён",
            reply_markup=get_back_button("ad_lots_list:0")
        )
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка удаления лота: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("ad_edit_text:"))
async def start_edit_text(callback: CallbackQuery, state: FSMContext):
    """Начать редактирование текста выдачи"""
    lot_index = int(callback.data.split(":")[1])
    offset = int(callback.data.split(":")[2])
    
    await state.set_state(AutoDeliveryStates.waiting_delivery_text)
    await state.update_data(lot_index=lot_index, offset=offset)
    
    await callback.message.answer(
        "✏️ <b>Редактирование текста выдачи</b>\n\n"
        "Доступные переменные:\n"
        "<code>$username</code> - имя покупателя\n"
        "<code>$product</code> - товар из файла\n"
        "<code>$order_id</code> - ID заказа\n\n"
        "Отправьте новый текст или /cancel для отмены:",
        reply_markup=get_back_button(f"ad_edit_lot:{lot_index}:{offset}")
    )
    await callback.answer()


@router.message(AutoDeliveryStates.waiting_delivery_text)
async def process_delivery_text(message: Message, state: FSMContext, auto_delivery, **kwargs):
    """Обработать новый текст выдачи"""
    if _is_cancel_text(message.text):
        await state.clear()
        await message.answer("❌ Отменено")
        return
    
    data = await state.get_data()
    lot_index = data.get('lot_index')
    offset = data.get('offset', 0)
    
    new_text = message.text.strip()
    
    lots = await auto_delivery.get_lots()
    if lot_index >= len(lots):
        await message.answer("❌ Лот не найден")
        await state.clear()
        return
    
    lot = lots[lot_index]
    
    # Проверяем наличие $product если есть файл
    if lot.get('products_file') and '$product' not in new_text:
        await message.answer(
            "⚠️ <b>Предупреждение!</b>\n\n"
            "К лоту привязан файл товаров, но в тексте нет переменной <code>$product</code>!\n"
            "Товары не будут выдаваться.",
            reply_markup=get_back_button(f"ad_edit_lot:{lot_index}:{offset}")
        )
        return
    
    try:
        await auto_delivery.update_lot_setting(
            lot.get('name'),
            'response_text',
            new_text
        )
        
        await state.clear()
        
        await message.answer(
            "✅ Текст выдачи обновлён!",
            reply_markup=get_back_button(f"ad_edit_lot:{lot_index}:{offset}")
        )
        
        logger.info(f"Текст выдачи лота {lot.get('name')} обновлён")
        
    except Exception as e:
        logger.error(f"Ошибка обновления текста: {e}", exc_info=True)
        await message.answer("❌ Ошибка при сохранении")


# ==================== Файлы товаров ====================

@router.callback_query(F.data.startswith("ad_link_file:"))
async def start_link_file(callback: CallbackQuery, state: FSMContext):
    """Начать привязку файла товаров"""
    lot_index = int(callback.data.split(":")[1])
    offset = int(callback.data.split(":")[2])
    
    await state.set_state(AutoDeliveryStates.waiting_products_file)
    await state.update_data(lot_index=lot_index, offset=offset)
    
    await callback.message.answer(
        "📁 <b>Привязка файла товаров</b>\n\n"
        "Введите название файла (без расширения .txt)\n"
        "Или отправьте <code>-</code> для отвязки файла\n\n"
        "Отправьте /cancel для отмены",
        reply_markup=get_back_button(f"ad_edit_lot:{lot_index}:{offset}")
    )
    await callback.answer()


@router.message(AutoDeliveryStates.waiting_products_file)
async def process_products_file(message: Message, state: FSMContext, auto_delivery, **kwargs):
    """Обработать привязку файла"""
    if _is_cancel_text(message.text):
        await state.clear()
        await message.answer("❌ Отменено")
        return
    
    data = await state.get_data()
    lot_index = data.get('lot_index')
    offset = data.get('offset', 0)
    
    file_name = message.text.strip()
    
    lots = await auto_delivery.get_lots()
    if lot_index >= len(lots):
        await message.answer("❌ Лот не найден")
        await state.clear()
        return
    
    lot = lots[lot_index]
    
    try:
        if file_name == "-":
            # Отвязываем файл
            await auto_delivery.update_lot_setting(
                lot.get('name'),
                'products_file',
                None
            )
            await message.answer(
                "✅ Файл товаров отвязан",
                reply_markup=get_back_button(f"ad_edit_lot:{lot_index}:{offset}")
            )
        else:
            # Привязываем файл
            file_path = f"{file_name}.txt"
            
            # Проверяем наличие $product в тексте
            if '$product' not in lot.get('response_text', ''):
                await message.answer(
                    "⚠️ <b>Ошибка!</b>\n\n"
                    "В тексте выдачи нет переменной <code>$product</code>!\n"
                    "Сначала добавьте её в текст выдачи.",
                    reply_markup=get_back_button(f"ad_edit_lot:{lot_index}:{offset}")
                )
                return
            
            await auto_delivery.update_lot_setting(
                lot.get('name'),
                'products_file',
                file_path
            )
            
            # Создаём файл если не существует
            await auto_delivery.ensure_products_file(file_path)
            
            await message.answer(
                f"✅ Файл <code>{file_path}</code> привязан!",
                reply_markup=get_back_button(f"ad_edit_lot:{lot_index}:{offset}")
            )
        
        await state.clear()
        logger.info(f"Файл товаров лота {lot.get('name')} обновлён: {file_name}")
        
    except Exception as e:
        logger.error(f"Ошибка привязки файла: {e}", exc_info=True)
        await message.answer("❌ Ошибка")


@router.callback_query(F.data.startswith("ad_test:"))
async def test_delivery(callback: CallbackQuery, auto_delivery, **kwargs):
    """Создать тестовый ключ автовыдачи"""
    try:
        lot_index = int(callback.data.split(":")[1])
        
        lots = await auto_delivery.get_lots()
        if lot_index >= len(lots):
            await callback.answer("❌ Лот не найден", show_alert=True)
            return
        
        lot = lots[lot_index]
        test_key = await auto_delivery.create_test_key(lot.get('name'))
        
        await callback.message.answer(
            f"✅ <b>Тестовый ключ создан!</b>\n\n"
            f"Отправьте эту команду в чат с покупателем:\n"
            f"<code>!автовыдача {test_key}</code>\n\n"
            f"Ключ действителен для одной выдачи."
        )
        await callback.answer()
        
        logger.info(f"Создан тестовый ключ для лота {lot.get('name')}")
        
    except Exception as e:
        logger.error(f"Ошибка создания тестового ключа: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)

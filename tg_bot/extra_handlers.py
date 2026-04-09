"""
Обработчики для дополнительных функций
(автоответы, конфиги, авторизованные пользователи)
"""

import os
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from tg_bot.full_keyboards import (
    get_main_menu_page_2,
    get_order_confirm_response_menu,
    get_review_response_menu,
    get_configs_menu,
    get_authorized_users_menu,
    CBT,
)
from support.runtime_config import BotConfig, get_config_manager


router = Router()


def _is_cancel_text(text: str | None) -> bool:
    return (text or "").strip() in {"-", "/cancel"}


class EditTextStates(StatesGroup):
    """Состояния для редактирования текстов"""
    waiting_for_order_confirm_text = State()
    waiting_for_review_text = State()
    waiting_for_config = State()


# === Вторая страница главного меню ===

@router.callback_query(F.data == CBT.MAIN_PAGE_2)
async def callback_main_page_2(callback: CallbackQuery):
    """Вторая страница главного меню"""
    await callback.answer()

    await callback.message.edit_text(
        "🛠️ <b>Дополнительные настройки</b>\n\n"
        "Здесь собраны доступ, конфиг и вспомогательные сценарии.",
        reply_markup=get_main_menu_page_2()
    )


# === Ответ на подтверждение заказа ===

@router.callback_query(F.data == CBT.ORDER_CONFIRM_RESPONSE)
async def callback_order_confirm_response(callback: CallbackQuery):
    """Меню настройки ответа на подтверждение заказа"""
    await callback.answer()
    
    enabled = BotConfig.ORDER_CONFIRM_RESPONSE_ENABLED()
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


@router.callback_query(F.data == "edit_order_confirm_text")
async def callback_edit_order_confirm_text(callback: CallbackQuery, state: FSMContext):
    """Начать редактирование текста ответа на подтверждение"""
    await callback.answer()
    
    await state.set_state(EditTextStates.waiting_for_order_confirm_text)
    
    await callback.message.edit_text(
        "✏️ <b>Изменение текста ответа на подтверждение заказа</b>\n\n"
        "Отправьте новый текст сообщения, которое будет отправляться покупателю "
        "после завершения заказа.\n\n"
        "Для отмены используйте <code>/cancel</code> или <code>-</code>."
    )


@router.message(EditTextStates.waiting_for_order_confirm_text)
async def process_order_confirm_text(message: Message, state: FSMContext):
    """Обработка нового текста ответа на подтверждение"""
    if _is_cancel_text(message.text):
        await state.clear()
        await message.answer("❌ Отменено")
        return

    text = message.text.strip()
    
    if not text or len(text) > 4096:
        await message.answer(
            "❌ Текст должен быть от 1 до 4096 символов. Попробуйте ещё раз:"
        )
        return
    
    # Сохраняем
    BotConfig.update(**{"AutoResponse.orderConfirmText": text})
    
    await state.clear()
    
    enabled = BotConfig.ORDER_CONFIRM_RESPONSE_ENABLED()
    
    message_text = (
        "✅ <b>Текст успешно изменён!</b>\n\n"
        f"<b>Статус:</b> {'включено ✅' if enabled else 'выключено ❌'}\n\n"
        f"<b>Новый текст ответа:</b>\n<i>{text}</i>"
    )
    
    await message.answer(
        message_text,
        reply_markup=get_order_confirm_response_menu(enabled, text)
    )


# === Ответ на отзыв ===

@router.callback_query(F.data == CBT.REVIEW_RESPONSE)
async def callback_review_response(callback: CallbackQuery):
    """Меню настройки ответа на отзыв"""
    await callback.answer()
    
    enabled = BotConfig.REVIEW_RESPONSE_ENABLED()
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


@router.callback_query(F.data == "edit_review_text")
async def callback_edit_review_text(callback: CallbackQuery, state: FSMContext):
    """Начать редактирование текста ответа на отзыв"""
    await callback.answer()
    
    await state.set_state(EditTextStates.waiting_for_review_text)
    
    await callback.message.edit_text(
        "✏️ <b>Изменение текста ответа на отзыв</b>\n\n"
        "Отправьте новый текст сообщения, которое будет отправляться "
        "в ответ на отзыв.\n\n"
        "Для отмены используйте <code>/cancel</code> или <code>-</code>."
    )


@router.message(EditTextStates.waiting_for_review_text)
async def process_review_text(message: Message, state: FSMContext):
    """Обработка нового текста ответа на отзыв"""
    if _is_cancel_text(message.text):
        await state.clear()
        await message.answer("❌ Отменено")
        return

    text = message.text.strip()
    
    if not text or len(text) > 4096:
        await message.answer(
            "❌ Текст должен быть от 1 до 4096 символов. Попробуйте ещё раз:"
        )
        return
    
    # Сохраняем
    BotConfig.update(**{"AutoResponse.reviewResponseText": text})
    
    await state.clear()
    
    enabled = BotConfig.REVIEW_RESPONSE_ENABLED()
    
    message_text = (
        "✅ <b>Текст успешно изменён!</b>\n\n"
        f"<b>Статус:</b> {'включено ✅' if enabled else 'выключено ❌'}\n\n"
        f"<b>Новый текст ответа:</b>\n<i>{text}</i>"
    )
    
    await message.answer(
        message_text,
        reply_markup=get_review_response_menu(enabled, text)
    )


# === Конфиги ===

@router.callback_query(F.data == CBT.CONFIGS_MENU)
async def callback_configs_menu(callback: CallbackQuery):
    """Меню управления конфигами"""
    await callback.answer()
    
    await callback.message.edit_text(
        "🗂 <b>Центр конфига</b>\n\n"
        "• Скачать текущий <code>_main.cfg</code>\n"
        "• Заменить конфиг новым файлом\n\n"
        "После загрузки бот будет перезапущен.",
        reply_markup=get_configs_menu()
    )


@router.callback_query(F.data == CBT.CONFIG_DOWNLOAD)
async def callback_config_download(callback: CallbackQuery):
    """Скачать конфиг"""
    config_manager = get_config_manager()
    config_path = config_manager.config_path
    
    if not config_path.exists():
        await callback.answer("❌ Файл конфига не найден!", show_alert=True)
        return
    
    await callback.answer()
    
    # Отправляем файл
    await callback.message.answer_document(
        FSInputFile(config_path),
        caption="📁 <b>Конфиг _main.cfg</b>\n\n"
                "Сохраните этот файл в надёжном месте."
    )


@router.callback_query(F.data == CBT.CONFIG_UPLOAD)
async def callback_config_upload(callback: CallbackQuery, state: FSMContext):
    """Начать загрузку конфига"""
    await callback.answer()
    
    await state.set_state(EditTextStates.waiting_for_config)
    
    await callback.message.edit_text(
        "📤 <b>Загрузка конфига</b>\n\n"
        "Отправьте файл <code>_main.cfg</code> в чат.\n\n"
        "⚠️ <b>Внимание!</b> Текущий конфиг будет удалён и заменён новым. "
        "Бот будет перезапущен.\n\n"
        "Для отмены используйте <code>/cancel</code> или <code>-</code>."
    )


@router.message(EditTextStates.waiting_for_config)
async def process_config_upload(message: Message, state: FSMContext, bot):
    """Обработка загрузки конфига"""
    if _is_cancel_text(message.text):
        await state.clear()
        await message.answer("❌ Отменено")
        return

    if not message.document:
        await message.answer(
            "❌ Пожалуйста, отправьте файл конфигурации."
        )
        return
    
    # Проверяем расширение
    if not message.document.file_name.endswith('.cfg'):
        await message.answer(
            "❌ Файл должен иметь расширение .cfg"
        )
        return
    
    await state.clear()
    
    # Скачиваем файл
    file = await bot.get_file(message.document.file_id)
    
    config_manager = get_config_manager()
    config_path = config_manager.config_path
    
    # Удаляем старый конфиг
    if config_path.exists():
        config_path.unlink()
    
    # Сохраняем новый
    await bot.download_file(file.file_path, config_path)
    
    await message.answer(
        "✅ <b>Конфиг успешно загружен!</b>\n\n"
        "Бот будет перезапущен через 3 секунды..."
    )
    
    # Перезапуск бота
    import asyncio
    import sys
    import os
    await asyncio.sleep(3)
    os.execv(sys.executable, [sys.executable] + sys.argv)


# === Авторизованные пользователи ===

@router.callback_query(F.data == CBT.AUTHORIZED_USERS)
async def callback_authorized_users(callback: CallbackQuery):
    """Меню авторизованных пользователей"""
    await callback.answer()
    
    admin_ids = BotConfig.ADMIN_IDS()
    
    if admin_ids:
        message_text = (
            "🔐 <b>Настройки доступа</b>\n\n"
            f"Всего авторизовано: <b>{len(admin_ids)}</b>\n\n"
            "Нажмите 🗑, чтобы убрать пользователя из контура доступа."
        )
    else:
        message_text = (
            "🔐 <b>Настройки доступа</b>\n\n"
            "Список авторизованных пользователей пуст."
        )
    
    await callback.message.edit_text(
        message_text,
        reply_markup=get_authorized_users_menu(admin_ids)
    )


@router.callback_query(F.data.startswith(f"{CBT.REMOVE_AUTH_USER}:"))
async def callback_remove_auth_user(callback: CallbackQuery):
    """Удалить авторизованного пользователя"""
    user_id = int(callback.data.split(":")[1])
    
    admin_ids = BotConfig.ADMIN_IDS()
    
    if user_id not in admin_ids:
        await callback.answer("❌ Пользователь не найден", show_alert=True)
        return
    
    # Удаляем
    admin_ids.remove(user_id)
    BotConfig.set_admin_ids(admin_ids)
    
    await callback.answer(f"✅ Пользователь {user_id} удалён", show_alert=False)
    
    # Обновляем меню
    if admin_ids:
        message_text = (
            "🔐 <b>Настройки доступа</b>\n\n"
            f"Всего авторизовано: <b>{len(admin_ids)}</b>\n\n"
            "Нажмите 🗑, чтобы убрать пользователя из контура доступа."
        )
    else:
        message_text = (
            "🔐 <b>Настройки доступа</b>\n\n"
            "Список авторизованных пользователей пуст."
        )
    
    await callback.message.edit_text(
        message_text,
        reply_markup=get_authorized_users_menu(admin_ids)
    )

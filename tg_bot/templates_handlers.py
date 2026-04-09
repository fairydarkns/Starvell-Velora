"""
Обработчики для работы с быстрыми ответами
"""

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from tg_bot.full_keyboards import (
    get_templates_menu,
    get_template_detail_menu,
    get_template_edit_menu,
    get_main_menu,
    get_select_template_menu
)
from support.templates_manager import get_template_manager
from tg_bot.full_keyboards import CBT


router = Router()
TEMPLATE_CHAT_CONTEXT: dict[int, str] = {}
TEMPLATE_VIEW_CONTEXT: dict[int, dict] = {}


class TemplateStates(StatesGroup):
    """Состояния для работы с быстрыми ответами"""
    waiting_for_name = State()
    waiting_for_text = State()
    waiting_for_edit_name = State()
    waiting_for_edit_text = State()


def _is_cancel_text(text: str | None) -> bool:
    return (text or "").strip() in {"-", "/cancel"}


@router.callback_query(F.data.startswith("show_templates:"))
async def callback_show_templates_for_reply(callback: CallbackQuery):
    """Показать быстрые ответы для выбора и отправки"""
    await callback.answer()

    # Извлекаем chat_id (может содержать двоеточия, берём всё после первого ":")
    chat_id = callback.data.split(":", 1)[1]
    TEMPLATE_CHAT_CONTEXT[callback.from_user.id] = chat_id
    TEMPLATE_VIEW_CONTEXT[callback.from_user.id] = {
        "text": callback.message.html_text or callback.message.text or callback.message.caption or "",
        "reply_markup": callback.message.reply_markup,
    }

    template_manager = get_template_manager()
    templates = template_manager.get_all()

    if templates:
        text = "📝 <b>Выберите быстрый ответ для отправки:</b>"
    else:
        text = (
            "📝 <b>Быстрых ответов пока нет</b>\n\n"
            "У вас пока нет быстрых ответов. Вы можете добавить первый быстрый ответ ниже."
        )

    await callback.message.edit_text(
        text,
        reply_markup=get_select_template_menu(chat_id, templates, back_callback="templates_back")
    )


@router.callback_query(F.data == "templates_back")
async def callback_templates_back(callback: CallbackQuery):
    """Вернуться из меню быстрых ответов к исходному уведомлению."""
    await callback.answer()

    context = TEMPLATE_VIEW_CONTEXT.get(callback.from_user.id)
    if not context:
        await callback.answer("❌ Контекст уведомления не найден", show_alert=True)
        return

    await callback.message.edit_text(
        context.get("text") or "Сообщение недоступно",
        reply_markup=context.get("reply_markup"),
    )


@router.callback_query(F.data == CBT.TEMPLATES)
async def callback_templates_menu(callback: CallbackQuery):
    """Меню быстрых ответов"""
    await callback.answer()

    template_manager = get_template_manager()
    templates = template_manager.get_all()

    text = "📝 <b>Быстрые ответы</b>\n\n"

    if templates:
        text += f"Всего быстрых ответов: <b>{len(templates)}</b>\n\n"
        text += "Выберите быстрый ответ для просмотра или редактирования:"
    else:
        text += "У вас пока нет быстрых ответов.\n"
        text += "Нажмите кнопку ниже, чтобы добавить первый быстрый ответ."

    await callback.message.edit_text(
        text,
        reply_markup=get_templates_menu(templates)
    )


@router.callback_query(F.data == CBT.ADD_TEMPLATE)
async def callback_add_template(callback: CallbackQuery, state: FSMContext):
    """Начать добавление нового быстрого ответа"""
    await callback.answer()

    await state.set_state(TemplateStates.waiting_for_name)

    await callback.message.edit_text(
        "📝 <b>Добавление нового быстрого ответа</b>\n\n"
        "Отправьте название для быстрого ответа.\n\n"
        "Например: <code>Приветствие</code>, <code>Благодарность</code>, <code>Отказ</code>\n\n"
        "Для отмены используйте <code>/cancel</code> или <code>-</code>."
    )


@router.message(TemplateStates.waiting_for_name)
async def process_template_name(message: Message, state: FSMContext):
    """Обработка названия быстрого ответа"""
    if _is_cancel_text(message.text):
        await state.clear()
        await message.answer("❌ Отменено")
        return

    name = message.text.strip()
    
    if not name or len(name) > 100:
        await message.answer(
            "❌ Название должно быть от 1 до 100 символов. Попробуйте ещё раз:"
        )
        return
    
    # Сохраняем название
    await state.update_data(name=name)
    await state.set_state(TemplateStates.waiting_for_text)
    
    await message.answer(
        f"✅ Название: <b>{name}</b>\n\n"
        "Теперь отправьте текст быстрого ответа.\n\n"
        "Это сообщение будет отправляться пользователям.\n\n"
        "Для отмены используйте <code>/cancel</code> или <code>-</code>."
    )


@router.message(TemplateStates.waiting_for_text)
async def process_template_text(message: Message, state: FSMContext):
    """Обработка текста быстрого ответа"""
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
    
    # Получаем название из состояния
    data = await state.get_data()
    name = data.get("name")
    
    # Добавляем заготовку
    template_manager = get_template_manager()
    template_id = template_manager.add(name, text)
    
    await state.clear()
    
    # Показываем меню заготовок
    templates = template_manager.get_all()
    
    await message.answer(
        f"✅ Быстрый ответ <b>{name}</b> успешно добавлен!\n\n"
        f"Всего быстрых ответов: <b>{len(templates)}</b>",
        reply_markup=get_templates_menu(templates)
    )


@router.callback_query(F.data.startswith(f"{CBT.TEMPLATE_DETAIL}:"))
async def callback_template_detail(callback: CallbackQuery):
    """Просмотр деталей быстрого ответа"""
    await callback.answer()
    
    template_id = callback.data.split(":")[1]
    
    template_manager = get_template_manager()
    template = template_manager.get_by_id(template_id)
    
    if not template:
        await callback.message.edit_text(
            "❌ Быстрый ответ не найден",
            reply_markup=get_templates_menu(template_manager.get_all())
        )
        return
    
    text = (
        f"📝 <b>{template['name']}</b>\n\n"
        f"<b>Текст быстрого ответа:</b>\n{template['text']}\n\n"
        f"<b>ID:</b> <code>{template['id']}</code>"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=get_template_detail_menu(template_id)
    )


@router.callback_query(F.data.startswith(f"{CBT.DELETE_TEMPLATE}:"))
async def callback_delete_template(callback: CallbackQuery):
    """Удалить быстрый ответ"""
    template_id = callback.data.split(":")[1]
    
    template_manager = get_template_manager()
    template = template_manager.get_by_id(template_id)
    
    if not template:
        await callback.answer("❌ Быстрый ответ не найден", show_alert=True)
        return
    
    name = template['name']
    success = template_manager.delete(template_id)
    
    if success:
        await callback.answer(f"✅ Быстрый ответ '{name}' удалён", show_alert=False)
        
        # Возвращаем к списку заготовок
        templates = template_manager.get_all()
        
        text = "📝 <b>Быстрые ответы</b>\n\n"

        if templates:
            text += f"Всего быстрых ответов: <b>{len(templates)}</b>\n\n"
            text += "Выберите быстрый ответ для просмотра или редактирования:"
        else:
            text += "У вас пока нет быстрых ответов.\n"
            text += "Нажмите кнопку ниже, чтобы добавить первый быстрый ответ."
        
        await callback.message.edit_text(
            text,
            reply_markup=get_templates_menu(templates)
        )
    else:
        await callback.answer("❌ Ошибка при удалении", show_alert=True)


@router.callback_query(F.data.startswith(f"{CBT.SELECT_TEMPLATE}:"))
async def callback_select_template(callback: CallbackQuery, starvell=None, **kwargs):
    """Выбрать и отправить быстрый ответ пользователю"""
    await callback.answer()
    
    # Формат: SELECT_TEMPLATE:template_id:chat_id или SELECT_TEMPLATE:template_id
    parts = callback.data.split(":", 2)  # Разбиваем максимум на 3 части
    template_id = parts[1]
    # chat_id может быть в callback_data или нужно извлечь из текста сообщения
    chat_id = parts[2] if len(parts) > 2 else None
    
    # Если chat_id нет в callback_data, пытаемся извлечь из текста сообщения
    if not chat_id:
        chat_id = TEMPLATE_CHAT_CONTEXT.get(callback.from_user.id)
    
    if not chat_id:
        await callback.answer("❌ Не указан чат", show_alert=True)
        return
    
    template_manager = get_template_manager()
    template = template_manager.get_by_id(template_id)
    
    if not template:
        await callback.answer("❌ Быстрый ответ не найден", show_alert=True)
        return
    
    # Отправляем сообщение через Starvell API
    if starvell:
        try:
            await starvell.send_message(chat_id, template['text'])
            await callback.answer(f"✅ Отправлено: {template['name']}", show_alert=False)
        except Exception as e:
            await callback.answer(f"❌ Ошибка отправки: {e}", show_alert=True)
    else:
        await callback.answer("❌ Сервис недоступен", show_alert=True)


@router.callback_query(F.data.startswith(f"{CBT.EDIT_TEMPLATE}:"))
async def callback_edit_template(callback: CallbackQuery):
    """Показать меню редактирования заготовки"""
    await callback.answer()
    
    template_id = callback.data.split(":")[1]
    
    template_manager = get_template_manager()
    template = template_manager.get_by_id(template_id)
    
    if not template:
        await callback.message.edit_text(
            "❌ Заготовка не найдена",
            reply_markup=get_templates_menu(template_manager.get_all())
        )
        return
    
    text = (
        f"✏️ <b>Редактирование заготовки</b>\n\n"
        f"<b>Название:</b> {template['name']}\n"
        f"<b>Текст:</b> {template['text']}\n\n"
        f"Выберите, что хотите изменить:"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=get_template_edit_menu(template_id)
    )


@router.callback_query(F.data.startswith(f"{CBT.EDIT_TEMPLATE_NAME}:"))
async def callback_edit_template_name(callback: CallbackQuery, state: FSMContext):
    """Начать редактирование названия заготовки"""
    await callback.answer()
    
    template_id = callback.data.split(":")[1]
    
    template_manager = get_template_manager()
    template = template_manager.get_by_id(template_id)
    
    if not template:
        await callback.message.edit_text(
            "❌ Заготовка не найдена",
            reply_markup=get_templates_menu(template_manager.get_all())
        )
        return
    
    # Сохраняем ID заготовки в состояние
    await state.update_data(template_id=template_id)
    await state.set_state(TemplateStates.waiting_for_edit_name)
    
    await callback.message.edit_text(
        f"✏️ <b>Редактирование названия</b>\n\n"
        f"<b>Текущее название:</b> {template['name']}\n\n"
        f"Отправьте новое название для заготовки:\n\n"
        "Для отмены используйте <code>/cancel</code> или <code>-</code>."
    )


@router.message(TemplateStates.waiting_for_edit_name)
async def process_edit_template_name(message: Message, state: FSMContext):
    """Обработка нового названия заготовки"""
    if _is_cancel_text(message.text):
        await state.clear()
        await message.answer("❌ Отменено")
        return

    name = message.text.strip()
    
    if not name or len(name) > 100:
        await message.answer(
            "❌ Название должно быть от 1 до 100 символов. Попробуйте ещё раз:"
        )
        return
    
    # Получаем ID заготовки из состояния
    data = await state.get_data()
    template_id = data.get("template_id")
    
    if not template_id:
        await state.clear()
        await message.answer("❌ Ошибка: ID заготовки не найден")
        return
    
    # Обновляем название
    template_manager = get_template_manager()
    template = template_manager.get_by_id(template_id)
    
    if not template:
        await state.clear()
        await message.answer(
            "❌ Заготовка не найдена",
            reply_markup=get_templates_menu(template_manager.get_all())
        )
        return
    
    # Обновляем заготовку
    success = template_manager.update(template_id, name=name)
    
    await state.clear()
    
    if success:
        updated_template = template_manager.get_by_id(template_id)
        text = (
            f"✅ Название успешно изменено!\n\n"
            f"📝 <b>{updated_template['name']}</b>\n\n"
            f"<b>Текст заготовки:</b>\n{updated_template['text']}\n\n"
            f"<b>ID:</b> <code>{updated_template['id']}</code>"
        )
        
        await message.answer(
            text,
            reply_markup=get_template_detail_menu(template_id)
        )
    else:
        await message.answer(
            "❌ Ошибка при обновлении заготовки",
            reply_markup=get_templates_menu(template_manager.get_all())
        )


@router.callback_query(F.data.startswith(f"{CBT.EDIT_TEMPLATE_TEXT}:"))
async def callback_edit_template_text(callback: CallbackQuery, state: FSMContext):
    """Начать редактирование текста заготовки"""
    await callback.answer()
    
    template_id = callback.data.split(":")[1]
    
    template_manager = get_template_manager()
    template = template_manager.get_by_id(template_id)
    
    if not template:
        await callback.message.edit_text(
            "❌ Заготовка не найдена",
            reply_markup=get_templates_menu(template_manager.get_all())
        )
        return
    
    # Сохраняем ID заготовки в состояние
    await state.update_data(template_id=template_id)
    await state.set_state(TemplateStates.waiting_for_edit_text)
    
    await callback.message.edit_text(
        f"📝 <b>Редактирование текста</b>\n\n"
        f"<b>Текущий текст:</b>\n{template['text']}\n\n"
        f"Отправьте новый текст для заготовки:\n\n"
        "Для отмены используйте <code>/cancel</code> или <code>-</code>."
    )


@router.message(TemplateStates.waiting_for_edit_text)
async def process_edit_template_text(message: Message, state: FSMContext):
    """Обработка нового текста заготовки"""
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
    
    # Получаем ID заготовки из состояния
    data = await state.get_data()
    template_id = data.get("template_id")
    
    if not template_id:
        await state.clear()
        await message.answer("❌ Ошибка: ID заготовки не найден")
        return
    
    # Обновляем текст
    template_manager = get_template_manager()
    template = template_manager.get_by_id(template_id)
    
    if not template:
        await state.clear()
        await message.answer(
            "❌ Заготовка не найдена",
            reply_markup=get_templates_menu(template_manager.get_all())
        )
        return
    
    # Обновляем заготовку
    success = template_manager.update(template_id, text=text)
    
    await state.clear()
    
    if success:
        updated_template = template_manager.get_by_id(template_id)
        display_text = (
            f"✅ Текст успешно изменён!\n\n"
            f"📝 <b>{updated_template['name']}</b>\n\n"
            f"<b>Текст заготовки:</b>\n{updated_template['text']}\n\n"
            f"<b>ID:</b> <code>{updated_template['id']}</code>"
        )
        
        await message.answer(
            display_text,
            reply_markup=get_template_detail_menu(template_id)
        )
    else:
        await message.answer(
            "❌ Ошибка при обновлении заготовки",
            reply_markup=get_templates_menu(template_manager.get_all())
        )

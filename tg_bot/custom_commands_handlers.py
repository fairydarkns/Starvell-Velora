"""
Обработчики для кастомных команд
"""

import json
import logging
from pathlib import Path
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from tg_bot.full_keyboards import get_custom_commands_menu, CBT

logger = logging.getLogger(__name__)
router = Router()

COMMANDS_FILE = Path("storage/telegram/custom_commands.json")
LEGACY_COMMANDS_FILE = Path("storage/custom_commands.json")


class CustomCommandState(StatesGroup):
    """Состояния для работы с кастомными командами"""
    waiting_for_command_name = State()
    waiting_for_command_text = State()
    waiting_for_prefix = State()
    editing_command_name = State()
    editing_command_text = State()


def load_commands():
    """Загрузить кастомные команды из JSON"""
    if not COMMANDS_FILE.exists() and LEGACY_COMMANDS_FILE.exists():
        try:
            COMMANDS_FILE.parent.mkdir(parents=True, exist_ok=True)
            LEGACY_COMMANDS_FILE.replace(COMMANDS_FILE)
            logger.info("Файл кастомных команд перенесён в storage/telegram/")
        except Exception as e:
            logger.error(f"Ошибка переноса кастомных команд: {e}")

    if not COMMANDS_FILE.exists():
        # Создать файл по умолчанию
        COMMANDS_FILE.parent.mkdir(parents=True, exist_ok=True)
        default_data = {
            "prefix": "!",
            "enabled": False,
            "commands": []
        }
        save_commands(default_data)
        return default_data
    
    try:
        with open(COMMANDS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка загрузки команд: {e}")
        return {"prefix": "!", "enabled": False, "commands": []}


def save_commands(data):
    """Сохранить кастомные команды в JSON"""
    try:
        COMMANDS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(COMMANDS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения команд: {e}")


@router.callback_query(F.data == CBT.CUSTOM_COMMANDS)
async def callback_custom_commands_menu(callback: CallbackQuery, **kwargs):
    """Меню кастомных команд"""
    await callback.answer()
    
    data = load_commands()
    commands = data.get("commands", [])
    prefix = data.get("prefix", "!")
    enabled = data.get("enabled", False)
    
    text = f"🤖 <b>Настройка автоответов</b>\n\n"
    text += f"<b>Префикс:</b> <code>{prefix}</code>\n"
    text += f"<b>Статус:</b> {'✅ Включено' if enabled else '❌ Выключено'}\n"
    text += f"<b>Команд:</b> {len(commands)}\n\n"
    
    if commands:
        text += "<b>Доступные команды:</b>\n"
        for cmd in commands[:5]:  # Показываем только первые 5
            text += f"• <code>{prefix}{cmd['name']}</code>\n"
        if len(commands) > 5:
            text += f"... и ещё {len(commands) - 5}\n"
    else:
        text += "Нет добавленных команд. Нажмите 'Добавить команду' чтобы создать новую."
    
    keyboard = get_custom_commands_menu(commands, page=0, enabled=enabled, prefix=prefix)
    
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data == CBT.TOGGLE_CUSTOM_COMMANDS)
async def callback_toggle_custom_commands(callback: CallbackQuery, **kwargs):
    """Переключить кастомные команды"""
    data = load_commands()
    data["enabled"] = not data.get("enabled", False)
    save_commands(data)
    
    status = "включены" if data["enabled"] else "выключены"
    await callback.answer(f"Кастомные команды {status}", show_alert=False)
    
    # Обновляем меню
    commands = data.get("commands", [])
    prefix = data.get("prefix", "!")
    enabled = data["enabled"]
    
    text = f"🤖 <b>Настройка автоответов</b>\n\n"
    text += f"<b>Префикс:</b> <code>{prefix}</code>\n"
    text += f"<b>Статус:</b> {'✅ Включено' if enabled else '❌ Выключено'}\n"
    text += f"<b>Команд:</b> {len(commands)}\n\n"
    
    if commands:
        text += "<b>Доступные команды:</b>\n"
        for cmd in commands[:5]:
            text += f"• <code>{prefix}{cmd['name']}</code>\n"
        if len(commands) > 5:
            text += f"... и ещё {len(commands) - 5}\n"
    else:
        text += "Нет добавленных команд."
    
    keyboard = get_custom_commands_menu(commands, page=0, enabled=enabled, prefix=prefix)
    
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data == CBT.ADD_CUSTOM_COMMAND)
async def callback_add_custom_command(callback: CallbackQuery, state: FSMContext, **kwargs):
    """Начать добавление команды"""
    await callback.answer()
    
    await callback.message.edit_text(
        "📝 <b>Добавление новой команды</b>\n\n"
        "Введите название команды (без префикса):\n"
        "Например: <code>help</code>, <code>price</code>, <code>info</code>\n\n"
        "Отправьте /cancel для отмены."
    )
    
    await state.set_state(CustomCommandState.waiting_for_command_name)


@router.message(CustomCommandState.waiting_for_command_name)
async def process_command_name(message: Message, state: FSMContext, **kwargs):
    """Обработать название команды"""
    if message.text == "/cancel":
        await message.answer("❌ Отменено")
        await state.clear()
        return
    
    command_name = message.text.strip().lower()
    
    # Валидация
    if not command_name or len(command_name) > 50:
        await message.answer("❌ Название команды должно быть от 1 до 50 символов. Попробуйте снова:")
        return
    
    # Проверяем, не существует ли уже
    data = load_commands()
    if any(cmd["name"] == command_name for cmd in data.get("commands", [])):
        await message.answer(f"❌ Команда <code>{command_name}</code> уже существует. Введите другое название:")
        return
    
    await state.update_data(command_name=command_name)
    
    await message.answer(
        f"✅ Название: <code>{command_name}</code>\n\n"
        "Теперь введите текст ответа на эту команду:\n\n"
        "Отправьте /cancel для отмены."
    )
    
    await state.set_state(CustomCommandState.waiting_for_command_text)


@router.message(CustomCommandState.waiting_for_command_text)
async def process_command_text(message: Message, state: FSMContext, **kwargs):
    """Обработать текст команды"""
    if message.text == "/cancel":
        await message.answer("❌ Отменено")
        await state.clear()
        return
    
    command_text = message.text.strip()
    
    if not command_text or len(command_text) > 4000:
        await message.answer("❌ Текст ответа должен быть от 1 до 4000 символов. Попробуйте снова:")
        return
    
    # Получаем название из состояния
    user_data = await state.get_data()
    command_name = user_data.get("command_name")
    
    # Сохраняем команду
    data = load_commands()
    if "commands" not in data:
        data["commands"] = []
    
    data["commands"].append({
        "name": command_name,
        "text": command_text
    })
    
    save_commands(data)
    
    await message.answer(
        f"✅ <b>Команда добавлена!</b>\n\n"
        f"<b>Название:</b> <code>{command_name}</code>\n"
        f"<b>Префикс:</b> <code>{data.get('prefix', '!')}</code>\n\n"
        f"Теперь покупатели могут использовать команду:\n"
        f"<code>{data.get('prefix', '!')}{command_name}</code>\n\n"
        f"Не забудьте включить кастомные команды в меню настроек!"
    )
    
    await state.clear()


@router.callback_query(F.data.startswith("custom_cmd_page:"))
async def callback_custom_commands_page(callback: CallbackQuery, **kwargs):
    """Переключить страницу команд"""
    page = int(callback.data.split(":")[1])
    
    data = load_commands()
    commands = data.get("commands", [])
    prefix = data.get("prefix", "!")
    enabled = data.get("enabled", False)
    
    text = f"🤖 <b>Настройка автоответов</b>\n\n"
    text += f"<b>Префикс:</b> <code>{prefix}</code>\n"
    text += f"<b>Статус:</b> {'✅ Включено' if enabled else '❌ Выключено'}\n"
    text += f"<b>Команд:</b> {len(commands)}\n\n"
    
    if commands:
        text += "<b>Доступные команды:</b>\n"
        for cmd in commands[:5]:
            text += f"• <code>{prefix}{cmd['name']}</code>\n"
        if len(commands) > 5:
            text += f"... и ещё {len(commands) - 5}\n"
    else:
        text += "Нет добавленных команд."
    
    keyboard = get_custom_commands_menu(commands, page=page, enabled=enabled, prefix=prefix)
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("custom_cmd_view:"))
async def callback_view_command(callback: CallbackQuery, **kwargs):
    """Просмотр команды"""
    command_name = callback.data.split(":", 1)[1]
    
    data = load_commands()
    commands = data.get("commands", [])
    
    command = next((cmd for cmd in commands if cmd["name"] == command_name), None)
    
    if not command:
        await callback.answer("❌ Команда не найдена", show_alert=True)
        return
    
    text = f"📝 <b>Команда: {command_name}</b>\n\n"
    text += f"<b>Полная команда:</b> <code>{data.get('prefix', '!')}{command_name}</code>\n\n"
    text += f"<b>Ответ:</b>\n{command['text']}"
    
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✏️ Изменить текст",
                callback_data=f"custom_cmd_edit:{command_name}"
            )
        ],
        [
            InlineKeyboardButton(
                text="🗑 Удалить",
                callback_data=f"custom_cmd_del:{command_name}"
            )
        ],
        [
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=CBT.CUSTOM_COMMANDS
            )
        ]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("custom_cmd_del:"))
async def callback_delete_command(callback: CallbackQuery, **kwargs):
    """Удалить команду"""
    command_name = callback.data.split(":", 1)[1]
    
    data = load_commands()
    commands = data.get("commands", [])
    
    # Удаляем команду
    data["commands"] = [cmd for cmd in commands if cmd["name"] != command_name]
    save_commands(data)
    
    await callback.answer(f"✅ Команда '{command_name}' удалена", show_alert=False)
    
    # Возвращаемся в меню
    commands = data.get("commands", [])
    prefix = data.get("prefix", "!")
    enabled = data.get("enabled", False)
    
    text = f"🤖 <b>Настройка автоответов</b>\n\n"
    text += f"<b>Префикс:</b> <code>{prefix}</code>\n"
    text += f"<b>Статус:</b> {'✅ Включено' if enabled else '❌ Выключено'}\n"
    text += f"<b>Команд:</b> {len(commands)}\n\n"
    
    if commands:
        text += "<b>Доступные команды:</b>\n"
        for cmd in commands[:5]:
            text += f"• <code>{prefix}{cmd['name']}</code>\n"
        if len(commands) > 5:
            text += f"... и ещё {len(commands) - 5}\n"
    else:
        text += "Нет добавленных команд."
    
    keyboard = get_custom_commands_menu(commands, page=0, enabled=enabled, prefix=prefix)
    
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data == CBT.CHANGE_PREFIX)
async def callback_change_prefix(callback: CallbackQuery, state: FSMContext, **kwargs):
    """Изменить префикс"""
    await callback.answer()
    
    data = load_commands()
    current_prefix = data.get("prefix", "!")
    
    await callback.message.edit_text(
        f"🔧 <b>Изменение префикса</b>\n\n"
        f"Текущий префикс: <code>{current_prefix}</code>\n\n"
        f"Введите новый префикс (1-5 символов):\n"
        f"Например: <code>!</code>, <code>/</code>, <code>.</code>, <code>!!</code>\n\n"
        f"Отправьте /cancel для отмены."
    )
    
    await state.set_state(CustomCommandState.waiting_for_prefix)


@router.message(CustomCommandState.waiting_for_prefix)
async def process_prefix(message: Message, state: FSMContext, **kwargs):
    """Обработать новый префикс"""
    if message.text == "/cancel":
        await message.answer("❌ Отменено")
        await state.clear()
        return
    
    prefix = message.text.strip()
    
    if not prefix or len(prefix) > 5:
        await message.answer("❌ Префикс должен быть от 1 до 5 символов. Попробуйте снова:")
        return
    
    # Сохраняем префикс
    data = load_commands()
    data["prefix"] = prefix
    save_commands(data)
    
    await message.answer(
        f"✅ <b>Префикс изменён!</b>\n\n"
        f"Новый префикс: <code>{prefix}</code>\n\n"
        f"Теперь команды вызываются так:\n"
        f"<code>{prefix}команда</code>"
    )
    
    await state.clear()


@router.callback_query(F.data.startswith("custom_cmd_edit:"))
async def callback_edit_command(callback: CallbackQuery, state: FSMContext, **kwargs):
    """Начать редактирование команды"""
    command_name = callback.data.split(":", 1)[1]
    
    await callback.answer()
    
    await state.update_data(editing_command=command_name)
    
    await callback.message.edit_text(
        f"✏️ <b>Редактирование команды: {command_name}</b>\n\n"
        f"Введите новый текст ответа:\n\n"
        f"Отправьте /cancel для отмены."
    )
    
    await state.set_state(CustomCommandState.editing_command_text)


@router.message(CustomCommandState.editing_command_text)
async def process_edit_command_text(message: Message, state: FSMContext, **kwargs):
    """Обработать новый текст команды"""
    if message.text == "/cancel":
        await message.answer("❌ Отменено")
        await state.clear()
        return
    
    command_text = message.text.strip()
    
    if not command_text or len(command_text) > 4000:
        await message.answer("❌ Текст ответа должен быть от 1 до 4000 символов. Попробуйте снова:")
        return
    
    # Получаем название из состояния
    user_data = await state.get_data()
    command_name = user_data.get("editing_command")
    
    # Обновляем команду
    data = load_commands()
    commands = data.get("commands", [])
    
    for cmd in commands:
        if cmd["name"] == command_name:
            cmd["text"] = command_text
            break
    
    save_commands(data)
    
    await message.answer(
        f"✅ <b>Команда обновлена!</b>\n\n"
        f"<b>Название:</b> <code>{command_name}</code>\n"
        f"<b>Новый текст:</b>\n{command_text}"
    )
    
    await state.clear()

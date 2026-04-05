"""Клавиатуры для управления подключаемыми модулями."""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton



def modules_list(extension_hub, CBT, offset: int = 0) -> InlineKeyboardMarkup:
    """Список модулей с пагинацией"""
    keyboard = []
    
    modules = list(extension_hub.plugins.values())
    per_page = 5
    start = offset
    end = min(offset + per_page, len(modules))
    
    for i in range(start, end):
        module = modules[i]
        status = "◆" if module.enabled else "◇"
        keyboard.append([
            InlineKeyboardButton(
                text=f"{status} {module.name} v{module.version}",
                callback_data=f"{CBT.EDIT_PLUGIN}:{module.uuid}:{offset}"
            )
        ])
    
    # Навигация
    nav_buttons = []
    if offset > 0:
        nav_buttons.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=f"{CBT.PLUGINS_LIST}:{offset - per_page}"
            )
        )
    if end < len(modules):
        nav_buttons.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=f"{CBT.PLUGINS_LIST}:{offset + per_page}"
            )
        )
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    # Импортировать модуль
    keyboard.append([
        InlineKeyboardButton(
            text="⤴️ Импортировать модуль",
            callback_data=f"{CBT.UPLOAD_PLUGIN}:{offset}"
        )
    ])
    
    keyboard.append([
        InlineKeyboardButton(
            text="🔙 Назад",
            callback_data=CBT.MAIN
        )
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def edit_module(module_card, CBT, uuid: str, offset: int, ask_delete: bool = False) -> InlineKeyboardMarkup:
    """Меню редактирования модуля"""
    keyboard = []
    
    if ask_delete:
        # Подтверждение удаления
        keyboard.append([
            InlineKeyboardButton(
                text="✅ Да, удалить",
                callback_data=f"{CBT.CONFIRM_DELETE_PLUGIN}:{uuid}:{offset}"
            )
        ])
        keyboard.append([
            InlineKeyboardButton(
                text="❌ Отмена",
                callback_data=f"{CBT.EDIT_PLUGIN}:{uuid}:{offset}"
            )
        ])
    else:
        # Обычное меню
        status_text = "▶️ Активировать" if not module_card.enabled else "⏸ Пауза"
        keyboard.append([
            InlineKeyboardButton(
                text=status_text,
                callback_data=f"{CBT.TOGGLE_PLUGIN}:{uuid}:{offset}"
            )
        ])

        if module_card.commands:
            keyboard.append([
                InlineKeyboardButton(
                    text="⌨️ Команды модуля",
                    callback_data=f"{CBT.PLUGIN_COMMANDS}:{uuid}:{offset}"
                )
            ])
        
        keyboard.append([
            InlineKeyboardButton(
                text="🗑 Удалить модуль",
                callback_data=f"{CBT.DELETE_PLUGIN}:{uuid}:{offset}"
            )
        ])
    
    keyboard.append([
        InlineKeyboardButton(
            text="🔙 Назад",
            callback_data=f"{CBT.PLUGINS_LIST}:{offset}"
        )
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def module_commands(module_card, CBT, uuid: str, offset: int) -> InlineKeyboardMarkup:
    """Список команд модуля"""
    keyboard = []
    
    for cmd_name, cmd_desc in module_card.commands.items():
        keyboard.append([
            InlineKeyboardButton(
                text=f"/{cmd_name} - {cmd_desc}",
                callback_data="empty"
            )
        ])
    
    keyboard.append([
        InlineKeyboardButton(
            text="🔙 Назад",
            callback_data=f"{CBT.EDIT_PLUGIN}:{uuid}:{offset}"
        )
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

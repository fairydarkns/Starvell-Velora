"""Реестр подключаемых модулей StarvellVelora."""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Callable, Dict, Optional
from uuid import UUID

from aiogram.filters.state import StateFilter

logger = logging.getLogger("ExtensionHub")


class ExtensionCard:
    """Описание подключенного расширения."""

    def __init__(
        self,
        name: str,
        version: str,
        description: str,
        author: str,
        uuid: str,
        path: str,
        module: ModuleType,
        has_settings: bool,
        delete_handler: Optional[Callable],
        enabled: bool,
    ) -> None:
        self.name = name
        self.version = version
        self.description = description
        self.author = author
        self.uuid = uuid
        self.path = path
        self.module = module
        self.has_settings = has_settings
        self.delete_handler = delete_handler
        self.enabled = enabled
        self.commands: Dict[str, str] = {}


class ExtensionHub:
    """Реестр и исполнитель расширений."""

    def __init__(self) -> None:
        self.extensions: Dict[str, ExtensionCard] = {}
        self.extensions_dir = Path("plugins")
        self.disabled_cache = Path("storage/cache/disabled_extensions.txt")
        self.disabled_extensions: list[str] = []

        self.init_handlers: list[Callable] = []
        self.start_handlers: list[Callable] = []
        self.stop_handlers: list[Callable] = []
        self.new_order_handlers: list[Callable] = []
        self.new_message_handlers: list[Callable] = []
        self.settings_handlers: Dict[str, list[Callable]] = {}

    @property
    def plugins(self) -> Dict[str, ExtensionCard]:
        return self.extensions

    @staticmethod
    def is_uuid_valid(uuid_str: str) -> bool:
        try:
            uuid_obj = UUID(uuid_str, version=4)
            return str(uuid_obj) == uuid_str
        except ValueError:
            return False

    @staticmethod
    def is_extension_enabled(file_path: Path) -> bool:
        try:
            with open(file_path, "r", encoding="utf-8") as file_obj:
                first_line = file_obj.readline().strip()
                if first_line.startswith("#") and "noplug" in first_line:
                    return False
        except Exception as error:
            logger.error(f"Ошибка чтения файла {file_path}: {error}")
            return False
        return True

    def load_disabled_extensions(self) -> None:
        if not self.disabled_cache.exists():
            return
        try:
            with open(self.disabled_cache, "r", encoding="utf-8") as file_obj:
                self.disabled_extensions = [line.strip() for line in file_obj if line.strip()]
        except Exception as error:
            logger.error(f"Ошибка загрузки списка отключённых расширений: {error}")

    def save_disabled_extensions(self) -> None:
        self.disabled_cache.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.disabled_cache, "w", encoding="utf-8") as file_obj:
                file_obj.write("\n".join(self.disabled_extensions))
        except Exception as error:
            logger.error(f"Ошибка сохранения списка отключённых расширений: {error}")

    def _iter_extension_files(self) -> list[Path]:
        if not self.extensions_dir.exists():
            return []

        discovered: list[Path] = []
        discovered.extend(
            path
            for path in sorted(self.extensions_dir.glob("*.py"))
            if path.name != "__init__.py"
        )

        for directory in sorted(self.extensions_dir.iterdir()):
            if not directory.is_dir():
                continue
            for candidate_name in ("module.py", "plugin.py", "__init__.py"):
                candidate = directory / candidate_name
                if candidate.exists() and self._is_entrypoint_candidate(candidate):
                    discovered.append(candidate)
                    break
        return discovered

    @staticmethod
    def _is_entrypoint_candidate(file_path: Path) -> bool:
        """Отсекает служебные пакеты без плагинных метаданных."""
        if file_path.name != "__init__.py":
            return True
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception:
            return False
        required_markers = ("NAME", "VERSION", "DESCRIPTION", "AUTHOR", "UUID")
        return all(f"{marker} =" in content for marker in required_markers)

    def load_extension_module(self, file_path: Path) -> tuple[ModuleType, dict]:
        relative_parts = file_path.relative_to(self.extensions_dir).with_suffix("").parts
        module_name = "extensions." + ".".join(relative_parts)
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Не удалось создать спецификацию для {file_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        required_fields = {
            "NAME": str,
            "VERSION": str,
            "DESCRIPTION": str,
            "AUTHOR": str,
            "UUID": str,
        }
        payload: dict[str, object] = {}
        for field in required_fields:
            if not hasattr(module, field):
                raise AttributeError(f"Модуль {file_path.name} не содержит поле {field}")
            payload[field] = getattr(module, field)

        payload["SETTINGS_PAGE"] = getattr(module, "SETTINGS_PAGE", False)
        payload["BIND_TO_DELETE"] = getattr(module, "BIND_TO_DELETE", None)
        return module, payload

    def discover_extensions(self) -> None:
        if not self.extensions_dir.exists():
            logger.warning("Папка модулей не найдена")
            self.extensions_dir.mkdir(parents=True, exist_ok=True)
            return

        self.load_disabled_extensions()
        extension_files = self._iter_extension_files()

        if not extension_files:
            logger.info("Модули не обнаружены")
            return

        sys.path.insert(0, str(self.extensions_dir))
        loaded_count = 0
        for file_path in extension_files:
            try:
                if not self.is_extension_enabled(file_path):
                    logger.debug(f"Модуль {file_path.name} отключён через метку # noplug")
                    continue

                module, payload = self.load_extension_module(file_path)
                uuid = str(payload["UUID"])
                if not self.is_uuid_valid(uuid):
                    logger.error(f"Модуль {file_path.name} имеет невалидный UUID: {uuid}")
                    continue
                if uuid in self.extensions:
                    logger.error(f"UUID {uuid} ({payload['NAME']}) уже зарегистрирован")
                    continue

                enabled = uuid not in self.disabled_extensions
                card = ExtensionCard(
                    name=str(payload["NAME"]),
                    version=str(payload["VERSION"]),
                    description=str(payload["DESCRIPTION"]),
                    author=str(payload["AUTHOR"]),
                    uuid=uuid,
                    path=str(file_path),
                    module=module,
                    has_settings=bool(payload["SETTINGS_PAGE"]),
                    delete_handler=payload["BIND_TO_DELETE"],
                    enabled=enabled,
                )
                self.extensions[uuid] = card
                loaded_count += 1
                logger.info(f"{'🟢' if enabled else '⚪'} Модуль {card.name} v{card.version} подключён")
            except Exception as error:
                logger.error(f"Ошибка загрузки модуля {file_path.name}: {error}")
                logger.debug("Подробности исключения", exc_info=True)

        logger.info(f"Подключено модулей: {loaded_count}/{len(extension_files)}")

    def attach_router(self, router=None) -> None:
        active_extensions: list[ExtensionCard] = []

        for uuid, extension in self.extensions.items():
            if not extension.enabled:
                continue
            active_extensions.append(extension)

            module = extension.module
            if hasattr(module, "BIND_TO_INIT"):
                for handler in module.BIND_TO_INIT:
                    handler.plugin_uuid = uuid
                    self.init_handlers.append(handler)
            if hasattr(module, "BIND_TO_START"):
                for handler in module.BIND_TO_START:
                    handler.plugin_uuid = uuid
                    self.start_handlers.append(handler)
            if hasattr(module, "BIND_TO_STOP"):
                for handler in module.BIND_TO_STOP:
                    handler.plugin_uuid = uuid
                    self.stop_handlers.append(handler)
            if hasattr(module, "BIND_TO_NEW_ORDER"):
                for handler in module.BIND_TO_NEW_ORDER:
                    handler.plugin_uuid = uuid
                    self.new_order_handlers.append(handler)
            if hasattr(module, "BIND_TO_NEW_MESSAGE"):
                for handler in module.BIND_TO_NEW_MESSAGE:
                    handler.plugin_uuid = uuid
                    self.new_message_handlers.append(handler)
            if hasattr(module, "BIND_TO_SETTINGS_PAGE"):
                self.settings_handlers[uuid] = module.BIND_TO_SETTINGS_PAGE

        if not router:
            return

        # Сначала регистрируем все команды модулей, чтобы их не перехватывали
        # более общие текстовые обработчики F.text из других модулей.
        for extension in active_extensions:
            module = extension.module
            if hasattr(module, "COMMANDS"):
                for command_name, command_data in module.COMMANDS.items():
                    handler = command_data.get("handler")
                    filters_list = command_data.get("filters", [])
                    if handler:
                        router.message.register(handler, *filters_list)
                        extension.commands[command_name] = command_data.get("description", "")
                        logger.info(
                            "Зарегистрирована команда модуля %s: /%s",
                            extension.name,
                            command_name,
                        )

        for extension in active_extensions:
            module = extension.module
            if hasattr(module, "CALLBACKS"):
                for _, callback_data in module.CALLBACKS.items():
                    handler = callback_data.get("handler")
                    callback_filter = callback_data.get("filter")
                    if handler and callback_filter:
                        router.callback_query.register(handler, callback_filter)
                logger.info(
                    "Зарегистрированы callback-обработчики модуля %s: %s",
                    extension.name,
                    len(getattr(module, "CALLBACKS", {})),
                )

        for extension in active_extensions:
            module = extension.module
            if hasattr(module, "TEXT_HANDLERS"):
                for _, handler_data in module.TEXT_HANDLERS.items():
                    handler = handler_data.get("handler")
                    text_filter = handler_data.get("filter")
                    if handler and text_filter:
                        router.message.register(handler, StateFilter(None), text_filter)
                logger.info(
                    "Зарегистрированы текстовые обработчики модуля %s: %s",
                    extension.name,
                    len(getattr(module, "TEXT_HANDLERS", {})),
                )

    async def execute_handlers(self, handlers: list[Callable], *args) -> None:
        for handler in handlers:
            try:
                plugin_uuid = getattr(handler, "plugin_uuid", None)
                if plugin_uuid and plugin_uuid in self.extensions and not self.extensions[plugin_uuid].enabled:
                    continue
                if asyncio.iscoroutinefunction(handler):
                    await handler(*args)
                else:
                    handler(*args)
            except Exception as error:
                logger.error(f"Ошибка выполнения модуля {handler.__name__}: {error}")
                logger.debug("Подробности исключения", exc_info=True)

    def switch_extension(self, uuid: str) -> bool:
        if uuid not in self.extensions:
            return False
        card = self.extensions[uuid]
        card.enabled = not card.enabled
        if card.enabled and uuid in self.disabled_extensions:
            self.disabled_extensions.remove(uuid)
        elif not card.enabled and uuid not in self.disabled_extensions:
            self.disabled_extensions.append(uuid)
        self.save_disabled_extensions()
        return True

    def remove_extension(self, uuid: str) -> bool:
        if uuid not in self.extensions:
            return False

        card = self.extensions[uuid]
        if card.delete_handler:
            try:
                card.delete_handler()
            except Exception as error:
                logger.error(f"Ошибка выполнения delete-хука для {card.name}: {error}")

        try:
            os.remove(card.path)
        except Exception as error:
            logger.error(f"Ошибка удаления файла модуля {card.path}: {error}")
            return False

        del self.extensions[uuid]
        if uuid in self.disabled_extensions:
            self.disabled_extensions.remove(uuid)
            self.save_disabled_extensions()
        logger.info(f"Модуль {card.name} удалён")
        return True

    discover_modules = discover_extensions
    bind_routes = attach_router
    run_hooks = execute_handlers
    switch_module = switch_extension
    remove_module = remove_extension

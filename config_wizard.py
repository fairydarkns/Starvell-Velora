from __future__ import annotations

import configparser
import hashlib
import json
from collections import OrderedDict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent
CONFIGS_DIR = PROJECT_ROOT / "configs"
STORAGE_DIR = PROJECT_ROOT / "storage"
MAIN_CONFIG_PATH = CONFIGS_DIR / "_main.cfg"
TEMPLATES_PATH = STORAGE_DIR / "telegram" / "templates.json"
CUSTOM_COMMANDS_PATH = STORAGE_DIR / "telegram" / "custom_commands.json"
ADMINS_PATH = STORAGE_DIR / "telegram" / "admins.json"
TELEGRAM_STATE_PATH = STORAGE_DIR / "telegram" / "state.json"
MARKETPLACE_STATE_PATH = STORAGE_DIR / "marketplace" / "state.json"
SYSTEM_STATE_PATH = STORAGE_DIR / "system" / "update_state.json"
STATISTICS_PATH = STORAGE_DIR / "stats" / "statistics.json"
LOGS_DIR = PROJECT_ROOT / "logs"
BACKUPS_DIR = PROJECT_ROOT / "backups"


CONFIG_LAYOUT: OrderedDict[str, OrderedDict[str, str]] = OrderedDict(
    [
        (
            "Telegram",
            OrderedDict(
                [
                    ("token", ""),
                    ("secretkeyhash", ""),
                    ("adminids", "[]"),
                    ("enabled", "true"),
                ]
            ),
        ),
        (
            "Starvell",
            OrderedDict(
                [
                    ("session_cookie", ""),
                    (
                        "user_agent",
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
                    ),
                    ("locale", "ru"),
                ]
            ),
        ),
        (
            "Monitor",
            OrderedDict(
                [
                    ("chat_poll_interval", "5"),
                    ("order_poll_interval", "10"),
                    ("request_timeout", "20"),
                    ("retry_count", "3"),
                    ("auto_read", "true"),
                ]
            ),
        ),
        (
            "StarvellProxy",
            OrderedDict(
                [
                    ("enabled", "false"),
                    ("host", ""),
                    ("port", ""),
                    ("username", ""),
                    ("password", ""),
                ]
            ),
        ),
        (
            "TelegramProxy",
            OrderedDict(
                [
                    ("enabled", "false"),
                    ("scheme", "http"),
                    ("host", ""),
                    ("port", ""),
                    ("username", ""),
                    ("password", ""),
                ]
            ),
        ),
        (
            "Other",
            OrderedDict(
                [
                    ("debug", "false"),
                    ("log_level", "INFO"),
                    ("timezone", "Europe/Moscow"),
                    ("use_watermark", "false"),
                    ("watermark", ""),
                ]
            ),
        ),
    ]
)


def _ensure_directories() -> None:
    for path in (
        CONFIGS_DIR,
        STORAGE_DIR / "telegram",
        STORAGE_DIR / "marketplace",
        STORAGE_DIR / "system",
        STORAGE_DIR / "stats",
        LOGS_DIR,
        BACKUPS_DIR,
        PROJECT_ROOT / "plugins",
    ):
        path.mkdir(parents=True, exist_ok=True)


def _ensure_json_file(path: Path, default_payload: Any) -> None:
    if path.exists():
        return
    path.write_text(
        json.dumps(default_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _ensure_support_files() -> None:
    _ensure_json_file(TEMPLATES_PATH, [])
    _ensure_json_file(
        CUSTOM_COMMANDS_PATH,
        {"prefix": "!", "enabled": False, "commands": []},
    )
    _ensure_json_file(TELEGRAM_STATE_PATH, {"last_bot_message_id": None})
    _ensure_json_file(
        MARKETPLACE_STATE_PATH,
        {
            "account": {},
            "threads": {},
            "orders": {},
        },
    )
    _ensure_json_file(
        SYSTEM_STATE_PATH,
        {"last_backup": None, "last_update": None, "kept_backups": []},
    )
    _ensure_json_file(STATISTICS_PATH, {})


def _new_parser() -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.optionxform = str.lower
    return parser


def _parse_bool(raw_value: str) -> bool:
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _print_step(title: str, description: str | None = None) -> None:
    line = "─" * 54
    print(f"\n{line}")
    print(f" {title}")
    if description:
        print(f" {description}")
    print(line)


def _prompt_text(
    label: str,
    *,
    current_value: str = "",
    hint: str | None = None,
    example: str | None = None,
    required: bool = True,
) -> str:
    while True:
        print(f"\n• {label}")
        if hint:
            print(f"  Подсказка: {hint}")
        if example:
            print(f"  Пример: {example}")

        suffix = f" [{current_value}]" if current_value else ""
        entered = input(f"  Ввод{suffix}: ").strip()
        if entered:
            return entered
        if current_value:
            return current_value
        if not required:
            return ""
        print("  Значение не может быть пустым. Попробуйте еще раз.")


def _prompt_choice(
    label: str,
    *,
    hint: str | None = None,
    options_hint: str | None = None,
    default: str = "",
) -> str:
    while True:
        print(f"\n• {label}")
        if hint:
            print(f"  Подсказка: {hint}")
        if options_hint:
            print(f"  Варианты: {options_hint}")
        suffix = f" [{default}]" if default else ""
        entered = input(f"  Выбор{suffix}: ").strip()
        if entered:
            return entered
        if default:
            return default


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _prompt_password_hash(current_hash: str = "") -> str:
    if current_hash:
        keep_current = _prompt_choice(
            "Пароль Telegram-бота уже задан",
            hint="Можно оставить текущий пароль или задать новый.",
            options_hint="1 = оставить текущий, 2 = задать новый",
            default="1",
        )
        if keep_current != "2":
            return current_hash

    while True:
        print("\n• Пароль для доступа к Telegram-боту")
        print("  Подсказка: этот пароль будут вводить администраторы при первом входе в бота.")
        print("  Совет: используйте не короткую строку, которую трудно подобрать.")
        password = input("  Пароль: ").strip()
        if not password:
            print("  Пароль не может быть пустым.")
            continue

        confirmation = input("  Повторите пароль: ").strip()
        if password != confirmation:
            print("  Пароли не совпадают. Попробуйте еще раз.")
            continue
        return _hash_password(password)


def _read_admin_registry() -> dict[str, Any]:
    if not ADMINS_PATH.exists():
        return {}
    try:
        return json.loads(ADMINS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _parse_admin_ids(raw_value: str) -> tuple[int, ...]:
    cleaned = raw_value.strip().strip("[]")
    if not cleaned:
        return ()
    result: list[int] = []
    for chunk in cleaned.split(","):
        item = chunk.strip()
        if not item:
            continue
        result.append(int(item))
    return tuple(result)


def _default_admin_prefs() -> dict[str, Any]:
    return {
        "enabled": True,
        "bot_start": True,
        "bot_stop": False,
        "new_messages": True,
        "new_orders": True,
        "support_messages": True,
        "order_completed": True,
        "order_confirmed": True,
        "backup_created": True,
        "backup_failed": True,
        "update_started": True,
        "update_finished": True,
        "update_failed": True,
        "errors": True,
    }


def _write_admin_registry(payload: dict[str, Any]) -> None:
    ADMINS_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _collect_admin_registry(
    interactive: bool,
    seed_admin_ids: tuple[int, ...] = (),
) -> dict[str, Any]:
    registry = _read_admin_registry()
    normalized: dict[str, Any] = {}
    for admin_id, prefs in registry.items():
        normalized[str(admin_id)] = _default_admin_prefs() | (prefs or {})

    if not normalized and seed_admin_ids:
        for admin_id in seed_admin_ids:
            normalized[str(admin_id)] = _default_admin_prefs()

    return normalized


def _prompt_proxy(raw_prompt: str, *, allow_scheme_choice: bool) -> dict[str, str]:
    while True:
        raw_value = _prompt_text(
            raw_prompt,
            hint="Можно без авторизации или с логином и паролем.",
            example="127.0.0.1:8080 или user:password@127.0.0.1:8080",
            required=False,
        )
        if not raw_value:
            defaults = {"enabled": "false", "host": "", "port": "", "username": "", "password": ""}
            if allow_scheme_choice:
                defaults["scheme"] = "http"
            return defaults

        try:
            username = ""
            password = ""
            host_port = raw_value
            if "@" in raw_value:
                auth_part, host_port = raw_value.rsplit("@", 1)
                if ":" not in auth_part:
                    raise ValueError("Прокси с авторизацией должен быть в формате user:password@ip:port")
                username, password = auth_part.split(":", 1)

            if ":" not in host_port:
                raise ValueError("Прокси должен быть в формате ip:port")
            host, port = host_port.rsplit(":", 1)
            if not host.strip() or not port.isdigit():
                raise ValueError("Неверный формат proxy host/port")

            result = {
                "enabled": "true",
                "host": host.strip(),
                "port": port.strip(),
                "username": username.strip(),
                "password": password.strip(),
            }

            if allow_scheme_choice:
                scheme_choice = _prompt_choice(
                    "Тип прокси для Telegram",
                    hint="HTTP обычно достаточно. SOCKS5 полезен, если так требует ваш сервер.",
                    options_hint="1 = http, 2 = socks5",
                    default="1",
                )
                result["scheme"] = "socks5" if scheme_choice == "2" else "http"

            return result
        except ValueError as exc:
            print(f"  Ошибка: {exc}")
            print("  Повторите ввод в одном из корректных форматов.")


def _apply_config_layout(parser: configparser.ConfigParser) -> bool:
    changed = False
    for section, fields in CONFIG_LAYOUT.items():
        if not parser.has_section(section):
            parser.add_section(section)
            changed = True
        for key, default_value in fields.items():
            if not parser.has_option(section, key):
                parser.set(section, key, default_value)
                changed = True
    return changed


def _commit_setup(
    parser: configparser.ConfigParser,
    admin_registry: dict[str, Any],
) -> None:
    _ensure_directories()
    _ensure_support_files()

    with MAIN_CONFIG_PATH.open("w", encoding="utf-8") as stream:
        parser.write(stream)

    _write_admin_registry(admin_registry)


def ensure_main_config(interactive: bool = True) -> configparser.ConfigParser:
    first_run = not MAIN_CONFIG_PATH.exists()

    parser = _new_parser()
    if MAIN_CONFIG_PATH.exists():
        parser.read(MAIN_CONFIG_PATH, encoding="utf-8")

    changed = _apply_config_layout(parser)

    if interactive:
        if first_run:
            _print_step(
                "Первичная настройка",
                "Сейчас будут запрошены базовые параметры запуска бота.",
            )

        if not parser.get("Telegram", "token", fallback="").strip():
            parser.set(
                "Telegram",
                "token",
                _prompt_text(
                    "Telegram bot token",
                    hint="Токен выдает BotFather после создания бота.",
                    example="1234567890:AAExampleToken",
                ),
            )
            changed = True
        if not parser.get("Telegram", "secretkeyhash", fallback="").strip():
            parser.set(
                "Telegram",
                "secretkeyhash",
                _prompt_password_hash(parser.get("Telegram", "secretkeyhash", fallback="")),
            )
            changed = True
        if not parser.get("Starvell", "session_cookie", fallback="").strip():
            parser.set(
                "Starvell",
                "session_cookie",
                _prompt_text(
                    "Starvell session_cookie",
                    hint="Возьмите значение cookie авторизованной сессии Starvell из браузера.",
                    example="eyJhbGciOi... или длинная строка cookie",
                ),
            )
            changed = True
        if not parser.get("Starvell", "user_agent", fallback="").strip():
            parser.set(
                "Starvell",
                "user_agent",
                _prompt_text(
                    "User-Agent для Starvell",
                    current_value=parser.get("Starvell", "user_agent", fallback=""),
                    hint="Обычно лучше оставить стандартный User-Agent текущего браузера.",
                    example="Mozilla/5.0 ... Chrome/135.0.0.0 Safari/537.36",
                ),
            )
            changed = True

        if first_run:
            _print_step(
                "Прокси для Starvell",
                "Этот прокси будет использоваться только для запросов к Starvell.",
            )
            use_starvell_proxy = _prompt_choice(
                "Нужен HTTP-прокси для Starvell?",
                hint="Если прокси не нужен, оставьте значение по умолчанию.",
                options_hint="y = да, n = нет",
                default="n",
            ).lower()
            if use_starvell_proxy == "y":
                proxy_values = _prompt_proxy(
                    "HTTP-прокси для Starvell",
                    allow_scheme_choice=False,
                )
                for key, value in proxy_values.items():
                    parser.set("StarvellProxy", key, value)
                changed = True

            _print_step(
                "Прокси для Telegram",
                "Этот прокси будет использоваться только для запросов Telegram Bot API.",
            )
            telegram_proxy_mode = _prompt_choice(
                "Прокси для Telegram",
                hint="Можно не использовать прокси, либо выбрать http или socks5.",
                options_hint="0 = нет, 1 = http, 2 = socks5",
                default="0",
            )
            if telegram_proxy_mode in {"1", "2"}:
                proxy_values = _prompt_proxy(
                    "Прокси для Telegram",
                    allow_scheme_choice=False,
                )
                proxy_values["enabled"] = "true"
                proxy_values["scheme"] = "socks5" if telegram_proxy_mode == "2" else "http"
                for key, value in proxy_values.items():
                    parser.set("TelegramProxy", key, value)
                changed = True

        starvell_proxy = parser.getboolean("StarvellProxy", "enabled", fallback=False)
        if starvell_proxy and (
            not parser.get("StarvellProxy", "host", fallback="").strip()
            or not parser.get("StarvellProxy", "port", fallback="").strip()
        ):
            proxy_values = _prompt_proxy(
                "HTTP-прокси для Starvell",
                allow_scheme_choice=False,
            )
            for key, value in proxy_values.items():
                parser.set("StarvellProxy", key, value)
            changed = True

        telegram_proxy = parser.getboolean("TelegramProxy", "enabled", fallback=False)
        if telegram_proxy and (
            not parser.get("TelegramProxy", "host", fallback="").strip()
            or not parser.get("TelegramProxy", "port", fallback="").strip()
        ):
            proxy_values = _prompt_proxy(
                "Прокси для Telegram",
                allow_scheme_choice=True,
            )
            for key, value in proxy_values.items():
                parser.set("TelegramProxy", key, value)
            changed = True

    required_blanks = [
        ("Telegram", "token"),
        ("Telegram", "secretkeyhash"),
        ("Starvell", "session_cookie"),
    ]
    missing_required = [
        f"{section}.{key}"
        for section, key in required_blanks
        if not parser.get(section, key, fallback="").strip()
    ]
    if missing_required and not interactive:
        joined = ", ".join(missing_required)
        raise RuntimeError(f"Config is incomplete: {joined}")

    seed_admin_ids = _parse_admin_ids(parser.get("Telegram", "adminids", fallback=""))
    admin_registry = _collect_admin_registry(interactive=interactive, seed_admin_ids=seed_admin_ids)
    final_admin_ids = tuple(int(item) for item in admin_registry.keys())
    parser.set("Telegram", "adminids", str(list(final_admin_ids)))

    registry_changed = admin_registry != _read_admin_registry()
    if changed or first_run or registry_changed or not ADMINS_PATH.exists():
        _commit_setup(parser, admin_registry)
    return parser


def run_first_time_setup() -> None:
    _print_step(
        "First Run",
        "Заполните основные параметры. Все значения сохранятся только после успешного завершения.",
    )
    try:
        ensure_main_config(interactive=True)
    except KeyboardInterrupt:
        print("\nПервичная настройка прервана. Файлы не были созданы.")
        return
    print(f"Конфигурация сохранена в {MAIN_CONFIG_PATH}")

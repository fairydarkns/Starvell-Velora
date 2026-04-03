from __future__ import annotations

import asyncio
from pathlib import Path

from config_wizard import MAIN_CONFIG_PATH, ensure_main_config
from support import configure_logging
from support.runtime_config import get_config_manager


PROJECT_ROOT = Path(__file__).resolve().parent


def _print_bootstrap_banner() -> None:
    from version import VERSION

    print(
        "\n"
        " ___      ___ _______   ___       ________  ________  ________     \n"
        "|\\  \\    /  /|\\  ___ \\ |\\  \\     |\\   __  \\|\\   __  \\|\\   __  \\    \n"
        "\\ \\  \\  /  / | \\   __/|\\ \\  \\    \\ \\  \\|\\  \\ \\  \\|\\  \\ \\  \\|\\  \\   \n"
        " \\ \\  \\/  / / \\ \\  \\_|/_\\ \\  \\    \\ \\  \\\\\\  \\ \\   _  _\\ \\   __  \\  \n"
        "  \\ \\    / /   \\ \\  \\_|\\ \\ \\  \\____\\ \\  \\\\\\  \\ \\  \\\\  \\\\ \\  \\ \\  \\ \n"
        "   \\ \\__/ /     \\ \\_______\\ \\_______\\ \\_______\\ \\__\\\\ _\\\\ \\__\\ \\__\\\n"
        "    \\|__|/       \\|_______|\\|_______|\\|_______|\\|__|\\|__|\\|__|\\|__|\n"
        "\n"
        "                     StarvellVelora\n"
        f"                      версия {VERSION}\n"
        "                      tg: @kortkk\n"
    )


async def run() -> None:
    if not MAIN_CONFIG_PATH.exists():
        _print_bootstrap_banner()

    try:
        ensure_main_config(interactive=True)
    except KeyboardInterrupt:
        print("\nПервичная настройка прервана. Файлы не были созданы.")
        return

    config_manager = get_config_manager(reload=True)
    configure_logging(config_manager.get('Other', 'log_level', 'INFO'), PROJECT_ROOT)

    from tg_bot.runtime import main as telegram_runtime_main

    await telegram_runtime_main()


asyncio.run(run())

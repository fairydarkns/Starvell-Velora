from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

try:
    from colorama import Fore, Style, init as colorama_init
except ImportError:  # pragma: no cover
    Fore = Style = None

    def colorama_init(*_args, **_kwargs) -> None:
        return None


class MaxLevelFilter(logging.Filter):
    def __init__(self, max_level: int) -> None:
        super().__init__()
        self._max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= self._max_level


class ConsoleFormatter(logging.Formatter):
    LEVEL_COLORS = {
        logging.DEBUG: Fore.CYAN if Fore else "",
        logging.INFO: getattr(Fore, "LIGHTBLUE_EX", Fore.CYAN) if Fore else "",
        logging.WARNING: Fore.YELLOW if Fore else "",
        logging.ERROR: Fore.RED if Fore else "",
        logging.CRITICAL: Fore.MAGENTA if Fore else "",
    }

    BLOCK_COLORS = {
        "cyan": getattr(Fore, "LIGHTCYAN_EX", Fore.CYAN) if Fore else "",
        "blue": getattr(Fore, "LIGHTBLUE_EX", Fore.CYAN) if Fore else "",
        "soft_blue": getattr(Fore, "BLUE", Fore.CYAN) if Fore else "",
    }

    LEVEL_LABELS = {
        logging.DEBUG: "DEBUG",
        logging.INFO: "INFO ",
        logging.WARNING: "WARN ",
        logging.ERROR: "ERROR",
        logging.CRITICAL: "FATAL",
    }

    def format(self, record: logging.LogRecord) -> str:
        if getattr(record, "plain_block", False):
            message = record.getMessage()
            color_name = getattr(record, "block_color", "cyan")
            color = self.BLOCK_COLORS.get(color_name, "")
            reset = Style.RESET_ALL if Style else ""
            return f"{color}{message}{reset}" if color else message

        original_levelname = record.levelname
        color = self.LEVEL_COLORS.get(record.levelno, "")
        reset = Style.RESET_ALL if Style else ""
        record.levelname = f"{color}{self.LEVEL_LABELS.get(record.levelno, original_levelname):<5}{reset}"
        try:
            return super().format(record)
        finally:
            record.levelname = original_levelname


class FileFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        if getattr(record, "plain_block", False):
            return record.getMessage()
        return super().format(record)


def _reset_named_logger(logger_name: str) -> logging.Logger:
    logger = logging.getLogger(logger_name)
    logger.handlers.clear()
    return logger


def _configure_websocket_logging(
    *,
    project_root: Path,
    debug_enabled: bool,
    file_formatter: logging.Formatter,
) -> None:
    websocket_loggers = (
        "StarSocket",
        "socketio",
        "socketio.client",
        "engineio",
        "engineio.client",
    )

    if not debug_enabled:
        for logger_name in websocket_loggers:
            ws_logger = _reset_named_logger(logger_name)
            if logger_name == "StarSocket":
                ws_logger.setLevel(logging.INFO)
                ws_logger.propagate = True
            else:
                ws_logger.setLevel(logging.WARNING)
                ws_logger.propagate = True
        return

    websocket_log_path = project_root / "logs" / "websocket.log"
    websocket_log_path.parent.mkdir(parents=True, exist_ok=True)

    websocket_file_handler = RotatingFileHandler(
        websocket_log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    websocket_file_handler.setLevel(logging.DEBUG)
    websocket_file_handler.setFormatter(file_formatter)

    for logger_name in websocket_loggers:
        ws_logger = _reset_named_logger(logger_name)
        ws_logger.setLevel(logging.DEBUG)
        ws_logger.addHandler(websocket_file_handler)
        if logger_name == "StarSocket":
            ws_logger.propagate = True
        else:
            ws_logger.propagate = False


def configure_logging(level_name: str, project_root: Path, debug_enabled: bool = False) -> None:
    log_path = project_root / "logs" / "log.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    colorama_init(autoreset=False)

    file_formatter = FileFormatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )
    console_formatter = ConsoleFormatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        "%H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(getattr(logging, level_name.upper(), logging.INFO))

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.DEBUG)
    stdout_handler.addFilter(MaxLevelFilter(logging.INFO))
    stdout_handler.setFormatter(console_formatter)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.WARNING)
    stderr_handler.setFormatter(console_formatter)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(file_formatter)

    root_logger.addHandler(stdout_handler)
    root_logger.addHandler(stderr_handler)
    root_logger.addHandler(file_handler)
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("tzlocal").setLevel(logging.ERROR)
    _configure_websocket_logging(
        project_root=project_root,
        debug_enabled=debug_enabled,
        file_formatter=file_formatter,
    )

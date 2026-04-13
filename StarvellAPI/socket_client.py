"""Realtime клиент Starvell на базе Socket.IO."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from typing import Any, Awaitable, Callable, Optional

import socketio

from .api_config import Config
from .session_manager import SessionManager

logger = logging.getLogger("StarSocket")

SocketEventHandler = Callable[[dict[str, Any]], Awaitable[None] | None]


class StarSocketClient:
    """Клиент для получения realtime-событий Starvell."""

    NAMESPACES = (
        "/online",
        "/chats",
        "/user-notifications",
    )

    def __init__(
        self,
        session: SessionManager,
        config: Config,
        on_event: Optional[SocketEventHandler] = None,
    ) -> None:
        self.session = session
        self.config = config
        self.on_event = on_event
        self._last_activity_ts = time.monotonic()
        self._connected_namespaces: set[str] = set()
        self._create_client()

    @property
    def connected(self) -> bool:
        return self.client.connected

    @property
    def healthy(self) -> bool:
        return self.connected and not self.missing_namespaces

    @property
    def last_activity_ts(self) -> float:
        return self._last_activity_ts

    @property
    def missing_namespaces(self) -> tuple[str, ...]:
        expected = set(self.NAMESPACES)
        missing = expected.difference(self._connected_namespaces)
        return tuple(sorted(missing))

    def mark_activity(self) -> None:
        self._last_activity_ts = time.monotonic()

    def _create_client(self) -> None:
        socketio_logger: Any = False
        engineio_logger: Any = False
        if logger.isEnabledFor(logging.DEBUG):
            socketio_logger = logging.getLogger("socketio.client")
            engineio_logger = logging.getLogger("engineio.client")

        self.client = socketio.AsyncClient(
            reconnection=True,
            reconnection_attempts=0,
            reconnection_delay=2,
            reconnection_delay_max=15,
            randomization_factor=0.2,
            logger=socketio_logger,
            engineio_logger=engineio_logger,
        )
        self._register_handlers()

    def _register_handlers(self) -> None:
        for namespace in self.NAMESPACES:
            self.client.on("connect", self._make_connect_handler(namespace), namespace=namespace)
            self.client.on("disconnect", self._make_disconnect_handler(namespace), namespace=namespace)
            self.client.on("connect_error", self._make_connect_error_handler(namespace), namespace=namespace)

        self.client.on("message_created", self._make_event_handler("/chats", "message_created"), namespace="/chats")
        self.client.on("chat_read", self._make_event_handler("/chats", "chat_read"), namespace="/chats")
        self.client.on("sale_update", self._make_event_handler("/user-notifications", "sale_update"), namespace="/user-notifications")

    def _make_connect_handler(self, namespace: str):
        async def handler():
            self._connected_namespaces.add(namespace)
            self.mark_activity()
            logger.info("Socket namespace подключен: %s", namespace)

        return handler

    def _make_disconnect_handler(self, namespace: str):
        async def handler():
            self._connected_namespaces.discard(namespace)
            self.mark_activity()
            logger.warning("Socket namespace отключен: %s", namespace)

        return handler

    def _make_connect_error_handler(self, namespace: str):
        async def handler(data: Any):
            self._connected_namespaces.discard(namespace)
            self.mark_activity()
            logger.warning("Socket namespace не смог подключиться: %s | data=%s", namespace, data)

        return handler

    def _make_event_handler(self, namespace: str, event_name: str):
        async def handler(data: Any):
            self.mark_activity()
            logger.debug("Socket событие %s [%s]", event_name, namespace)
            await self._dispatch_event(
                {
                    "namespace": namespace,
                    "event": event_name,
                    "data": data,
                }
            )

        return handler

    async def _dispatch_event(self, event: dict[str, Any]) -> None:
        if self.on_event is None:
            return
        result = self.on_event(event)
        if inspect.isawaitable(result):
            await result

    async def _wait_for_namespaces(self, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.healthy:
                return True
            await asyncio.sleep(0.1)
        return self.healthy

    async def start(self) -> None:
        if self.connected:
            logger.warning("Socket клиент уже подключен")
            return

        self._connected_namespaces.clear()

        headers = {
            "Cookie": self.session.build_cookie_header(include_sid=True),
            "Origin": self.config.BASE_URL,
            "User-Agent": self.config.user_agent,
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        }

        logger.info("Подключаю Socket.IO клиент Starvell")
        await self.client.connect(
            self.config.BASE_URL,
            headers=headers,
            transports=["websocket"],
            namespaces=list(self.NAMESPACES),
            wait_timeout=self.config.timeout,
        )
        namespaces_ok = await self._wait_for_namespaces(timeout=min(float(self.config.timeout), 10.0))
        self.mark_activity()
        if not namespaces_ok:
            missing = ", ".join(self.missing_namespaces) or "unknown"
            logger.warning("Socket.IO подключился не полностью. Отсутствуют namespace: %s", missing)
            try:
                await self.client.disconnect()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Ошибка при отключении неполного Socket.IO соединения: %s", exc)
            raise RuntimeError(f"Socket.IO подключился не полностью, отсутствуют namespace: {missing}")
        logger.info("Socket.IO клиент Starvell подключен")

    async def stop(self) -> None:
        if not self.connected:
            return
        await self.client.disconnect()
        self._connected_namespaces.clear()
        self.mark_activity()
        logger.info("Socket.IO клиент Starvell остановлен")

    async def reconnect(self, force: bool = False) -> None:
        logger.warning("Переподключаю Socket.IO клиент Starvell")
        old_client = self.client
        try:
            if old_client.connected:
                await old_client.disconnect()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Ошибка при отключении Socket.IO перед reconnect: %s", exc)
        if force:
            self._create_client()
        else:
            self._connected_namespaces.clear()
        await self.start()

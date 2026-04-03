"""
Сервис вечного онлайна
"""

import asyncio
import logging
from typing import Optional

from support.runtime_config import BotConfig


logger = logging.getLogger("KeepAlive")


class KeepAliveService:
    """
    Сервис для поддержания онлайн статуса на Starvell
    
    Периодически отправляет heartbeat запросы к API,
    чтобы сервер видел что пользователь активен.
    """
    
    def __init__(self, starvell):
        """
        Args:
            starvell: StarvellService instance
        """
        self.starvell = starvell
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._interval = 60  # Интервал в секундах
        self._last_success = None
        
    async def start(self):
        """Запустить сервис"""
        if self._running:
            logger.warning("Сервис вечного онлайна уже запущен")
            return

        # Проверяем включено ли в конфиге
        if not BotConfig.KEEP_ALIVE_ENABLED():
            logger.info("⏸️ Вечный онлайн отключен в настройках")
            self._running = False
            return

        # Устанавливаем флаг и запускаем фоновую задачу
        self._running = True
        try:
            self._task = asyncio.create_task(self._keep_alive_loop())
            logger.info(f"Сервис вечного онлайна запущен (интервал: {self._interval}s)")
        except Exception as e:
            self._running = False
            logger.error(f"Не удалось запустить задачу вечного онлайна: {e}")
        
    async def stop(self):
        """Остановить сервис"""
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        logger.info("⏹️ Сервис вечного онлайна остановлен")
        
    async def _keep_alive_loop(self):
        """Основной цикл поддержания онлайна"""
        logger.debug("Цикл вечного онлайна запущен")
        # Первый запрос сразу
        await self._send_heartbeat()

        while self._running:
            try:
                await asyncio.sleep(self._interval)

                if not BotConfig.KEEP_ALIVE_ENABLED():
                    logger.debug("Вечный онлайн отключен, пропускаем heartbeat")
                    continue

                await self._send_heartbeat()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка в цикле вечного онлайна: {e}", exc_info=True)
                await asyncio.sleep(5)  # Короткая пауза перед повтором
                
    async def _send_heartbeat(self):
        """Отправить heartbeat запрос"""
        try:
            success = await self.starvell.keep_alive()
            
            if success:
                self._last_success = asyncio.get_event_loop().time()
                logger.debug("💚 Импульс присутствия отправлен успешно")
            else:
                logger.warning("⚠️ Не удалось отправить импульс присутствия")
                
        except Exception as e:
            logger.error(f"❌ Ошибка отправки импульса присутствия: {e}")
            
    def get_status(self) -> dict:
        """
        Получить статус сервиса
        
        Returns:
            dict с информацией о статусе
        """
        return {
            "running": self._running,
            "enabled": BotConfig.KEEP_ALIVE_ENABLED(),
            "interval": self._interval,
            "last_success": self._last_success,
        }

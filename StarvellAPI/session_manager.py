"""Управление HTTP сессиями"""

import asyncio
import time
import json
from typing import Optional, Dict, Any
import aiohttp
from aiohttp import BasicAuth, ClientTimeout, ClientResponseError

from .api_config import Config
from .api_utils import extract_sid_from_cookies
from .api_exceptions import (
    StarAPIError,
    AuthenticationError,
    RateLimitError,
    NotFoundError,
    ServerError,
)
from support.runtime_config import BotConfig


class SessionManager:
    """Менеджер HTTP сессий с retry логикой"""
    
    def __init__(self, session_cookie: str, config: Config):
        self.session_cookie = session_cookie
        self.config = config
        self._session: Optional[aiohttp.ClientSession] = None
        self._sid_cookie: Optional[str] = None
        self._guard_ready = False
        self._guard_warming = False
        
    async def __aenter__(self):
        await self.start()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        
    async def start(self):
        """Создать сессию"""
        if self._session is None or self._session.closed:
            timeout = ClientTimeout(total=self.config.timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)
        await self._ensure_guard_cookies()
            
    async def close(self):
        """Закрыть сессию"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
            
    def _get_headers(
        self,
        referer: str = None,
        extra: Dict[str, str] = None,
        *,
        json_body: bool = False,
    ) -> Dict[str, str]:
        """Получить заголовки для запроса"""
        headers = {
            "accept": "*/*",
            "accept-language": "ru,en;q=0.9",
            "user-agent": self.config.user_agent,
        }
        
        if referer:
            headers["referer"] = referer
            if json_body and "origin" not in (extra or {}):
                headers["origin"] = self.config.BASE_URL
            
        if extra:
            headers.update(extra)
            
        return headers

    @staticmethod
    def _is_session_rejected(status: int, body: str) -> bool:
        """Определить, отклонил ли Starvell именно session cookie."""
        if status == 401:
            return True
        if status != 403:
            return False

        text = (body or "").strip()
        if "SESSION_NOT_FOUND" in text:
            return True

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return False

        if not isinstance(data, dict):
            return False

        nested = data.get("data")
        if isinstance(nested, dict) and nested.get("code") == "SESSION_NOT_FOUND":
            return True
        return False

    @staticmethod
    def _auth_error_message(body: str) -> str:
        if "SESSION_NOT_FOUND" in body:
            return (
                "Сессия Starvell не найдена (SESSION_NOT_FOUND). "
                "Обновите session_cookie из браузера."
            )
        return "Неверный session cookie"

    async def _ensure_guard_cookies(self) -> None:
        """Прогреть anti-bot cookies DDoS-Guard перед рабочими запросами."""
        if self._guard_ready or self._guard_warming:
            return

        if self._session is None:
            await self.start()

        self._guard_warming = True
        proxy, proxy_auth = self._get_proxy()
        try:
            async with self._session.request(
                "GET",
                f"{self.config.BASE_URL}/",
                headers=self._get_headers(
                    None,
                    {
                        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    },
                ),
                cookies=self._get_cookies(False),
                proxy=proxy,
                proxy_auth=proxy_auth,
            ) as resp:
                if resp.status < 500:
                    await resp.text()
                    self._guard_ready = True
        except Exception:
            # Не блокируем запуск: рабочие запросы попробуют прогреть cookie снова.
            pass
        finally:
            self._guard_warming = False
        
    def _get_cookies(self, include_sid: bool = False) -> Dict[str, str]:
        """Получить cookies для запроса"""
        cookies = {
            "session": self.session_cookie,
            **Config.DEFAULT_COOKIES,
        }
        
        if include_sid and self._sid_cookie:
            cookies["sid"] = self._sid_cookie
            
        return cookies
        
    def set_sid(self, sid: Optional[str]):
        """Установить SID cookie"""
        self._sid_cookie = sid
        
    def get_sid(self) -> Optional[str]:
        """Получить SID cookie"""
        return self._sid_cookie

    def sync_sid_from_jar(self) -> Optional[str]:
        """Подхватить sid из cookie jar после ответов Starvell."""
        if self._session is None:
            return self._sid_cookie
        sid = extract_sid_from_cookies(self._session)
        if sid:
            self._sid_cookie = sid
        return self._sid_cookie

    def build_cookie_header(self, include_sid: bool = False) -> str:
        """Собрать Cookie header для внешних клиентов, например Socket.IO."""
        cookies = self._get_cookies(include_sid)
        return "; ".join(f"{key}={value}" for key, value in cookies.items() if value)

    def _get_proxy(self) -> tuple[Optional[str], Optional[BasicAuth]]:
        proxy = BotConfig.PROXY()
        if not proxy:
            return None, None
        login = BotConfig.PROXY_LOGIN()
        password = BotConfig.PROXY_PASSWORD()
        proxy_auth = BasicAuth(login, password) if login else None
        return proxy, proxy_auth
        
    async def get_json(
        self,
        url: str,
        referer: str = None,
        headers: Dict[str, str] = None,
        include_sid: bool = False,
    ) -> Any:
        """GET запрос с получением JSON"""
        if self._session is None:
            await self.start()
        if not self._guard_ready:
            await self._ensure_guard_cookies()
            
        retry_count = self.config.max_retries
        request_headers = self._get_headers(referer, headers)
        cookies = self._get_cookies(include_sid)
        proxy, proxy_auth = self._get_proxy()
        
        last_error = None
        
        for attempt in range(retry_count):
            try:
                async with self._session.request(
                    "GET",
                    url,
                    headers=request_headers,
                    cookies=cookies,
                    proxy=proxy,
                    proxy_auth=proxy_auth,
                ) as resp:
                    if resp.status in (401, 403):
                        body = await resp.text()
                        if self._is_session_rejected(resp.status, body):
                            raise AuthenticationError(self._auth_error_message(body))
                        if resp.status == 403:
                            try:
                                return json.loads(body)
                            except json.JSONDecodeError:
                                raise StarAPIError(
                                    "Starvell вернул 403 без JSON. "
                                    "Возможна блокировка IP/DDoS-Guard или закрытый endpoint."
                                )
                    elif resp.status == 404:
                        raise NotFoundError(f"Ресурс не найден: {url}")
                    elif resp.status == 429:
                        raise RateLimitError("Превышен лимит запросов")
                    elif resp.status >= 500:
                        raise ServerError(f"Ошибка сервера: {resp.status}")
                    
                    resp.raise_for_status()
                    return await resp.json()
                    
            except (ClientResponseError, aiohttp.ClientError) as e:
                last_error = e
                
                # Не повторяем запросы для определенных ошибок
                if isinstance(e, (AuthenticationError, NotFoundError, RateLimitError)):
                    raise
                    
                # Последняя попытка
                if attempt == retry_count - 1:
                    break
                    
                # Ждем перед следующей попыткой
                await asyncio.sleep(self.config.RETRY_DELAY * (attempt + 1))
                
        # Если все попытки провалились
        if last_error:
            raise StarAPIError(f"Не удалось выполнить запрос после {retry_count} попыток: {last_error}")
        raise StarAPIError("Неизвестная ошибка при выполнении запроса")
            
    async def post_json(
        self,
        url: str,
        data: Any,
        referer: str = None,
        headers: Dict[str, str] = None,
        include_sid: bool = False,
    ) -> Any:
        """POST запрос с отправкой и получением JSON"""
        if self._session is None:
            await self.start()
        if not self._guard_ready:
            await self._ensure_guard_cookies()
            
        retry_count = self.config.max_retries
        headers = headers or {}
        headers["content-type"] = "application/json"
        request_headers = self._get_headers(referer, headers, json_body=True)
        cookies = self._get_cookies(include_sid)
        proxy, proxy_auth = self._get_proxy()
        
        last_error = None
        
        for attempt in range(retry_count):
            try:
                async with self._session.request(
                    "POST",
                    url,
                    headers=request_headers,
                    cookies=cookies,
                    json=data,
                    proxy=proxy,
                    proxy_auth=proxy_auth,
                ) as resp:
                    # Для ошибок читаем тело ответа для отладки
                    if resp.status >= 400:
                        try:
                            error_body = await resp.text()
                            # Пытаемся распарсить как JSON
                            try:
                                error_data = json.loads(error_body)
                                error_message = error_data.get("message") or error_data.get("error") or error_body
                            except:
                                error_message = error_body
                        except:
                            error_message = f"HTTP {resp.status}"
                    
                    # Обработка статус кодов
                    if resp.status == 400:
                        raise StarAPIError(f"Bad Request (400): {error_message}")
                    elif resp.status in (401, 403):
                        if self._is_session_rejected(resp.status, error_message):
                            raise AuthenticationError(self._auth_error_message(error_message))
                        raise StarAPIError(f"Доступ запрещён ({resp.status}): {error_message}")
                    elif resp.status == 404:
                        raise NotFoundError(f"Ресурс не найден: {url}")
                    elif resp.status == 429:
                        raise RateLimitError("Превышен лимит запросов")
                    elif resp.status >= 500:
                        raise ServerError(f"Ошибка сервера: {resp.status}")
                    
                    resp.raise_for_status()
                    
                    content_type = resp.headers.get("Content-Type", "")
                    
                    if "application/json" in content_type.lower():
                        return await resp.json()
                    else:
                        text = await resp.text()
                        return {"status": resp.status, "text": text}
                    
            except (ClientResponseError, aiohttp.ClientError) as e:
                last_error = e
                
                # Не повторяем запросы для определенных ошибок
                if isinstance(e, (AuthenticationError, NotFoundError, RateLimitError)):
                    raise
                    
                # Последняя попытка
                if attempt == retry_count - 1:
                    break
                    
                # Ждем перед следующей попыткой
                await asyncio.sleep(self.config.RETRY_DELAY * (attempt + 1))
                
        # Если все попытки провалились
        if last_error:
            raise StarAPIError(f"Не удалось выполнить запрос после {retry_count} попыток: {last_error}")
        raise StarAPIError("Неизвестная ошибка при выполнении запроса")
                
    async def get_text(
        self,
        url: str,
        referer: str = None,
        headers: Dict[str, str] = None,
    ) -> str:
        """GET запрос с получением текста"""
        if self._session is None:
            await self.start()
        if not self._guard_ready:
            await self._ensure_guard_cookies()
            
        retry_count = self.config.max_retries
        request_headers = self._get_headers(referer, headers)
        cookies = self._get_cookies(False)
        proxy, proxy_auth = self._get_proxy()
        
        last_error = None
        
        for attempt in range(retry_count):
            try:
                async with self._session.request(
                    "GET",
                    url,
                    headers=request_headers,
                    cookies=cookies,
                    proxy=proxy,
                    proxy_auth=proxy_auth,
                ) as resp:
                    if resp.status in (401, 403):
                        body = await resp.text()
                        if self._is_session_rejected(resp.status, body):
                            raise AuthenticationError(self._auth_error_message(body))
                        raise StarAPIError(
                            "Starvell вернул 403 при загрузке HTML. "
                            "Проверьте IP/прокси или повторите запрос позже."
                        )
                    elif resp.status == 404:
                        raise NotFoundError(f"Ресурс не найден: {url}")
                    elif resp.status == 429:
                        raise RateLimitError("Превышен лимит запросов")
                    elif resp.status >= 500:
                        raise ServerError(f"Ошибка сервера: {resp.status}")
                    
                    resp.raise_for_status()
                    return await resp.text()
                    
            except (ClientResponseError, aiohttp.ClientError) as e:
                last_error = e
                
                # Не повторяем запросы для определенных ошибок
                if isinstance(e, (AuthenticationError, NotFoundError, RateLimitError)):
                    raise
                    
                # Последняя попытка
                if attempt == retry_count - 1:
                    break
                    
                # Ждем перед следующей попыткой
                await asyncio.sleep(self.config.RETRY_DELAY * (attempt + 1))
                
        # Если все попытки провалились
        if last_error:
            raise StarAPIError(f"Не удалось выполнить запрос после {retry_count} попыток: {last_error}")
        raise StarAPIError("Неизвестная ошибка при выполнении запроса")

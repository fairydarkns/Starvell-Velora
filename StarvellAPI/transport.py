from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

import aiohttp
from aiohttp import ClientTimeout

from .api_exceptions import (
    MarketplaceError,
    RemoteNotFoundError,
    RemoteServerError,
    SessionExpiredError,
    ThrottledError,
)
from .proxy import build_proxy_auth, build_proxy_url
from .runtime_types import RuntimeSettings

BUILD_PATTERN = re.compile(r'"buildId":"([^"]+)"')


class Transport:
    def __init__(self, settings: RuntimeSettings) -> None:
        self._settings = settings
        self._session: aiohttp.ClientSession | None = None
        self._sid_cookie: str | None = None
        self._build_id: str | None = None
        self._build_id_until: float = 0.0
        self._base_url = "https://starvell.com"
        self._api_url = f"{self._base_url}/api"

    async def open(self) -> None:
        if self._session and not self._session.closed:
            return
        timeout = ClientTimeout(total=self._settings.request_timeout)
        self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    def remember_sid(self, sid: str | None) -> None:
        self._sid_cookie = sid

    def _headers(self, referer: str | None, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "accept": "*/*",
            "accept-language": "ru,en;q=0.9",
            "user-agent": self._settings.starvell_user_agent,
        }
        if referer:
            headers["referer"] = referer
        if extra:
            headers.update(extra)
        return headers

    def _cookies(self, include_sid: bool) -> dict[str, str]:
        cookies = {
            "session": self._settings.starvell_session_cookie,
            "starvell.theme": "dark",
            "starvell.time_zone": self._settings.timezone,
            "starvell.my_games": "1,10,11",
        }
        if include_sid and self._sid_cookie:
            cookies["sid"] = self._sid_cookie
        return cookies

    async def request_json(
        self,
        method: str,
        url: str,
        *,
        payload: Any | None = None,
        referer: str | None = None,
        include_sid: bool = False,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        if self._session is None:
            await self.open()
        assert self._session is not None

        headers = self._headers(referer, extra_headers)
        if payload is not None:
            headers["content-type"] = "application/json"

        proxy_url = build_proxy_url(self._settings.starvell_proxy)
        proxy_auth = build_proxy_auth(self._settings.starvell_proxy)

        for attempt in range(max(1, self._settings.retry_count)):
            try:
                async with self._session.request(
                    method=method.upper(),
                    url=url,
                    headers=headers,
                    cookies=self._cookies(include_sid),
                    json=payload,
                    proxy=proxy_url,
                    proxy_auth=proxy_auth,
                ) as response:
                    if response.status == 401:
                        raise SessionExpiredError("Starvell rejected the session cookie")
                    if response.status == 404:
                        raise RemoteNotFoundError(f"Missing resource: {url}")
                    if response.status == 429:
                        raise ThrottledError("Starvell rate limited this request")
                    if response.status >= 500:
                        raise RemoteServerError(f"Starvell returned HTTP {response.status}")
                    if response.status >= 400:
                        body = await response.text()
                        try:
                            parsed = json.loads(body)
                        except json.JSONDecodeError:
                            parsed = body
                        raise MarketplaceError(f"HTTP {response.status}: {parsed}")

                    if "application/json" in response.headers.get("Content-Type", "").lower():
                        return await response.json()
                    return {"status": response.status, "body": await response.text()}
            except (SessionExpiredError, RemoteNotFoundError, ThrottledError):
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError, MarketplaceError) as error:
                if attempt == self._settings.retry_count - 1:
                    raise MarketplaceError(str(error)) from error
                await asyncio.sleep(1 + attempt)

        raise MarketplaceError("Unreachable transport failure")

    async def request_text(
        self,
        url: str,
        *,
        referer: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> str:
        if self._session is None:
            await self.open()
        assert self._session is not None

        proxy_url = build_proxy_url(self._settings.starvell_proxy)
        proxy_auth = build_proxy_auth(self._settings.starvell_proxy)
        async with self._session.get(
            url,
            headers=self._headers(referer, extra_headers),
            cookies=self._cookies(False),
            proxy=proxy_url,
            proxy_auth=proxy_auth,
        ) as response:
            if response.status == 401:
                raise SessionExpiredError("Starvell rejected the session cookie")
            if response.status == 404:
                raise RemoteNotFoundError(f"Missing resource: {url}")
            if response.status >= 500:
                raise RemoteServerError(f"Starvell returned HTTP {response.status}")
            if response.status >= 400:
                raise MarketplaceError(f"HTTP {response.status}: {await response.text()}")
            return await response.text()

    async def next_data(
        self,
        path: str,
        *,
        query: str = "",
        include_sid: bool = False,
    ) -> dict[str, Any]:
        for attempt in range(2):
            build_id = await self._get_build_id()
            url = f"{self._base_url}/_next/data/{build_id}/{path}"
            if query:
                url = f"{url}{query}"
            try:
                payload = await self.request_json(
                    "GET",
                    url,
                    referer=self._base_url,
                    include_sid=include_sid,
                    extra_headers={"x-nextjs-data": "1"},
                )
                return payload if isinstance(payload, dict) else {}
            except RemoteNotFoundError:
                if attempt == 0:
                    self._build_id = None
                    self._build_id_until = 0
                    continue
                raise
        raise MarketplaceError("Could not fetch Next.js data")

    async def _get_build_id(self) -> str:
        if self._build_id and time.monotonic() < self._build_id_until:
            return self._build_id
        html = await self.request_text(
            f"{self._base_url}/",
            extra_headers={
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            },
        )
        match = BUILD_PATTERN.search(html)
        if not match:
            raise MarketplaceError("Unable to extract build id from Starvell")
        self._build_id = match.group(1)
        self._build_id_until = time.monotonic() + 1800
        return self._build_id

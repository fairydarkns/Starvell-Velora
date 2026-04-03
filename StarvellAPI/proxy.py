from __future__ import annotations

from aiohttp import BasicAuth

from .runtime_types import ProxySettings


def build_proxy_url(proxy: ProxySettings) -> str | None:
    return proxy.url


def build_proxy_auth(proxy: ProxySettings) -> BasicAuth | None:
    if not proxy.configured or not proxy.username:
        return None
    return BasicAuth(proxy.username, proxy.password)

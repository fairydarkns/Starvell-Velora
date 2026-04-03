from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class ProxySettings:
    enabled: bool
    host: str
    port: int | None
    username: str
    password: str
    scheme: str = "http"

    @property
    def configured(self) -> bool:
        return self.enabled and bool(self.host) and self.port is not None

    @property
    def url(self) -> str | None:
        if not self.configured:
            return None
        credentials = ""
        if self.username:
            credentials = self.username
            if self.password:
                credentials = f"{credentials}:{self.password}"
            credentials = f"{credentials}@"
        return f"{self.scheme}://{credentials}{self.host}:{self.port}"


@dataclass(slots=True, frozen=True)
class RuntimeSettings:
    telegram_token: str
    telegram_enabled: bool
    admin_ids: tuple[int, ...]
    starvell_session_cookie: str
    starvell_user_agent: str
    starvell_locale: str
    chat_poll_interval: int
    order_poll_interval: int
    request_timeout: int
    retry_count: int
    auto_read: bool
    starvell_proxy: ProxySettings
    telegram_proxy: ProxySettings
    debug: bool
    log_level: str
    timezone: str
    use_watermark: bool
    watermark: str

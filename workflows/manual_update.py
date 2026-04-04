from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional
from urllib.error import HTTPError
from urllib.request import urlopen

from support.backup import create_user_backup
from support.process_control import restart_current_process
from support.updater import apply_update_from_archive
from version import GITHUB_REPO, UPDATE_ARCHIVE_URL, UPDATE_BRANCH, VERSION, VERSION_URL


logger = logging.getLogger("ManualUpdate")


class ManualUpdateService:
    """Только ручное обновление по команде /update."""

    def __init__(self, project_root):
        self.project_root = project_root
        self.current_version = VERSION
        self.latest_version: Optional[str] = None
        self.update_available = False
        self._resolved_branch: Optional[str] = None
        self._resolved_version_url: Optional[str] = None
        self._resolved_archive_url: Optional[str] = None

    async def check_for_updates(self) -> bool:
        try:
            content = await asyncio.to_thread(self._download_version_file)
            version_match = re.search(r'VERSION\s*=\s*["\']([^"\']+)["\']', content)
            if not version_match:
                raise RuntimeError("Не удалось распарсить VERSION из version.py")
            self.latest_version = version_match.group(1)
            self.update_available = self._compare_versions(self.current_version, self.latest_version)
            return self.update_available
        except Exception as error:  # noqa: BLE001
            logger.exception("Не удалось проверить доступную версию")
            raise RuntimeError(f"Не удалось проверить обновления: {error}") from error

    def _download_version_file(self) -> str:
        try:
            with urlopen(VERSION_URL, timeout=10) as response:  # noqa: S310
                self._resolved_branch = UPDATE_BRANCH
                self._resolved_version_url = VERSION_URL
                self._resolved_archive_url = UPDATE_ARCHIVE_URL
                return response.read().decode("utf-8")
        except HTTPError as error:
            raise RuntimeError(
                "Не удалось получить version.py из GitHub. "
                f"Проверьте репозиторий {GITHUB_REPO} и ветку {UPDATE_BRANCH}"
            ) from error

    @staticmethod
    def _compare_versions(current: str, latest: str) -> bool:
        def parse_version(raw: str) -> tuple[int, int, int]:
            parts = raw.split(".")
            major = int(parts[0]) if len(parts) > 0 else 0
            minor = int(parts[1]) if len(parts) > 1 else 0
            patch = int(parts[2]) if len(parts) > 2 else 0
            return major, minor, patch

        return parse_version(latest) > parse_version(current)

    async def perform_update(self) -> dict:
        try:
            if not self._resolved_archive_url:
                await self.check_for_updates()
            backup_path = await asyncio.to_thread(create_user_backup, self.project_root)
            await asyncio.to_thread(apply_update_from_archive, self.project_root, self._resolved_archive_url)
            return {
                "success": True,
                "message": "✅ Обновление установлено.",
                "output": (
                    f"Backup: {backup_path.name}\n"
                    f"Branch: {self._resolved_branch}\n"
                    f"Archive: {self._resolved_archive_url}"
                ),
                "backup_path": str(backup_path),
            }
        except Exception as error:  # noqa: BLE001
            logger.exception("Ручное обновление завершилось ошибкой")
            return {
                "success": False,
                "message": "❌ Ошибка при обновлении.",
                "output": str(error),
                "backup_path": None,
            }

    def restart(self) -> None:
        restart_current_process()

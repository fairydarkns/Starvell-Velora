from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from support.archive import build_zip_archive
from support.json_storage import load_json, save_json


def create_user_backup(project_root: Path) -> Path:
    backups_dir = project_root / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    archive_path = backups_dir / f"user_backup_{timestamp}.zip"
    build_zip_archive(
        archive_path,
        [
            project_root / "configs",
            project_root / "storage",
            project_root / "plugins",
        ],
        project_root,
    )
    prune_backups(project_root, keep_last=3)
    state_path = project_root / "storage" / "system" / "update_state.json"
    state = load_json(state_path, {"last_backup": None, "last_update": None, "kept_backups": []})
    kept = [str(path.name) for path in sorted(backups_dir.glob("user_backup_*.zip"))]
    state["last_backup"] = archive_path.name
    state["kept_backups"] = kept
    save_json(state_path, state)
    return archive_path


def prune_backups(project_root: Path, keep_last: int) -> None:
    backups_dir = project_root / "backups"
    existing = sorted(backups_dir.glob("user_backup_*.zip"))
    while len(existing) > keep_last:
        oldest = existing.pop(0)
        oldest.unlink(missing_ok=True)

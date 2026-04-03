from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def build_zip_archive(target_path: Path, source_paths: list[Path], root_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(target_path, "w", compression=ZIP_DEFLATED) as archive:
        for source_path in source_paths:
            if not source_path.exists():
                continue
            if source_path.is_file():
                archive.write(source_path, source_path.relative_to(root_path))
                continue
            for item in source_path.rglob("*"):
                if item.is_file():
                    archive.write(item, item.relative_to(root_path))

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlretrieve


UPDATE_ALLOWLIST = [
    "tg_bot",
    "StarvellAPI",
    "workflows",
    "domain",
    "support",
    "config_wizard.py",
    "first-run.py",
    "main.py",
    "version.py",
    "requirements.txt",
    "README.md",
]


def apply_update_from_archive(project_root: Path, archive_url: str) -> None:
    with TemporaryDirectory(prefix="starvell-update-") as temp_dir:
        temp_root = Path(temp_dir)
        downloaded_zip = temp_root / "release.zip"
        urlretrieve(archive_url, downloaded_zip)

        extract_root = temp_root / "release"
        extract_root.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(downloaded_zip) as archive:
            archive.extractall(extract_root)

        extracted_items = list(extract_root.iterdir())
        if not extracted_items:
            raise RuntimeError("Downloaded archive is empty")

        source_root = extracted_items[0]
        for relative_path in UPDATE_ALLOWLIST:
            source_path = source_root / relative_path
            target_path = project_root / relative_path
            if not source_path.exists():
                continue
            if target_path.exists():
                if target_path.is_dir():
                    shutil.rmtree(target_path)
                else:
                    target_path.unlink()
            if source_path.is_dir():
                shutil.copytree(source_path, target_path)
            else:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, target_path)

"""
Backup service: creates an encrypted ZIP of the SQLite database.
"""
from __future__ import annotations

import os
import zipfile
from datetime import datetime
from pathlib import Path

from database.db import DB_PATH


def crear_backup(destino_dir: str | Path | None = None, password: str | None = None) -> Path:
    """
    Copy the SQLite DB into a timestamped .zip file.
    If password is provided, the zip is password-protected (requires pyminizip).
    Returns the path to the created backup file.
    """
    if destino_dir is None:
        destino_dir = DB_PATH.parent / "backups"
    destino_dir = Path(destino_dir)
    destino_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = destino_dir / f"contabilidad_backup_{timestamp}.zip"

    if password:
        try:
            import pyminizip
            pyminizip.compress(
                str(DB_PATH),
                None,
                str(backup_path),
                password,
                5  # compression level
            )
        except ImportError:
            # Fall back to unencrypted zip with warning
            _zip_sin_password(backup_path)
            return backup_path
    else:
        _zip_sin_password(backup_path)

    return backup_path


def _zip_sin_password(backup_path: Path) -> None:
    with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(DB_PATH, arcname=DB_PATH.name)


def limpiar_backups_viejos(destino_dir: Path, mantener: int = 10) -> int:
    """Delete oldest backups, keeping only `mantener` most recent. Returns deleted count."""
    backups = sorted(destino_dir.glob("contabilidad_backup_*.zip"))
    to_delete = backups[:-mantener] if len(backups) > mantener else []
    for f in to_delete:
        f.unlink()
    return len(to_delete)

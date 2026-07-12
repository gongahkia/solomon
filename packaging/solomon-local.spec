# SPDX-License-Identifier: Apache-2.0

# PyInstaller spec for the offline-default Solomon local SKU.

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

project_root = Path(SPECPATH).parent
src_root = project_root / "src"

a = Analysis(
    [str(src_root / "solomon" / "cli" / "main.py")],
    pathex=[str(src_root)],
    binaries=[],
    datas=collect_data_files("rfc3987_syntax"),
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="solomon-local",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)

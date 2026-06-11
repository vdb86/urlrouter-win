# URLRouter.spec
# -*- mode: python ; coding: utf-8 -*-
#
# Build a single portable .exe:
#   pyinstaller URLRouter.spec --clean
#
# Output: dist/URLRouter.exe

import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# pywin32 support files that PyInstaller may miss
hidden = [
    "win32api",
    "win32con",
    "win32gui",
    "win32ui",
    "win32pipe",
    "win32file",
    "win32security",
    "pywintypes",
    "win32timezone",
    "pkg_resources.py2_warn",
    "PyQt6.QtSvg",
    "PyQt6.QtXml",
]

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "scipy", "PIL"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ── onedir build ──────────────────────────────────────────────────────
# The exe contains only the bootloader + Python; all DLLs and data sit
# beside it in the dist\URLRouter\ folder.  There is NO per-launch archive
# extraction, so each click-to-popup launch is near-instant (~50-150 ms)
# instead of the 2-3 s that onefile pays decompressing on every run.
#
# Still fully portable: zip the dist\URLRouter\ folder, copy it anywhere,
# run URLRouter.exe inside it.  No installer.  config.json is written next
# to URLRouter.exe inside that folder.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,     # ← onedir: binaries go to COLLECT, not the exe
    name="URLRouter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[
        "vcruntime140.dll",
        "python3*.dll",
        "Qt6Core.dll",
        "Qt6Gui.dll",
        "Qt6Widgets.dll",
    ],
    console=False,             # no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="icon.ico",
    version_file=None,
    uac_admin=False,           # explicitly no elevation required
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[
        "vcruntime140.dll",
        "python3*.dll",
        "Qt6Core.dll",
        "Qt6Gui.dll",
        "Qt6Widgets.dll",
    ],
    name="URLRouter",          # → dist\URLRouter\URLRouter.exe
)

# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


ROOT = Path(SPECPATH)


a = Analysis(
    ["app/desktop.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "sources.json"), "."),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GeoNewsBot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="GeoNewsBot",
)
app = BUNDLE(
    coll,
    name="GeoNewsBot.app",
    icon=None,
    bundle_identifier="kz.qazaqtimes.geonewsbot",
    info_plist={
        "CFBundleName": "GeoNewsBot",
        "CFBundleDisplayName": "GeoNewsBot",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1",
        "NSHighResolutionCapable": True,
    },
)

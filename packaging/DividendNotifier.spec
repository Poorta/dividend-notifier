# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


block_cipher = None

hiddenimports = (
    collect_submodules("app")
    + collect_submodules("scripts")
    + collect_submodules("akshare")
    + collect_submodules("apscheduler")
)

a = Analysis(
    ["mac_launcher.py"],
    pathex=[".", ".."],
    binaries=[],
    datas=[
        ("../app/templates", "app/templates"),
        ("../app/static", "app/static"),
        ("../.env.example", "."),
    ] + collect_data_files("akshare"),
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Dividend Notifier",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Dividend Notifier",
)

app = BUNDLE(
    coll,
    name="Dividend Notifier.app",
    icon=None,
    bundle_identifier="com.opensource.dividendnotifier",
    info_plist={
        "NSHighResolutionCapable": "True",
        "CFBundleShortVersionString": "0.1.1",
        "CFBundleVersion": "0.1.1",
    },
)

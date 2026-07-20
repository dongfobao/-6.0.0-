# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

project_dir = Path.cwd()
app_dir = project_dir / "app"
web_dir = app_dir / "web"

datas = [(str(web_dir), "web")]

a = Analysis(
    [str(app_dir / "customer_delivery_entry.py")],
    pathex=[str(app_dir), str(project_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=["serial", "serial.tools.list_ports_windows", "serial.tools.list_ports"],
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
    name="YLDQ数据分析",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    version=str(project_dir / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="YLDQ数据分析系统",
)

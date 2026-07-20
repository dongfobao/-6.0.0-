# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

project_dir = Path.cwd()
app_dir = project_dir / "app"
web_dir = app_dir / "web"

datas = [(str(web_dir), "web")]

a = Analysis(
    [str(app_dir / "dashboard_workbench_entry.py")],
    pathex=[str(app_dir), str(project_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "serial",
        "serial.serialwin32",
        "serial.tools",
        "serial.tools.list_ports",
        "serial.tools.list_ports_windows",
    ],
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
    name="YLDQ分析系统",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="YLDQ分析系统工作台",
)

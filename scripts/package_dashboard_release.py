from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
SPEC_PATH = PROJECT_DIR / "packaging" / "dashboard_workbench.spec"
DIST_DIR = PROJECT_DIR / "dist" / "YLDQ6.0远程监控系统"
RELEASE_DIR = PROJECT_DIR / "release" / "YLDQ6.0远程监控系统"
LIVE_DEVICES_PATH = PROJECT_DIR / "live_devices.json"


def run_packaging() -> None:
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", str(SPEC_PATH)]
    subprocess.run(cmd, cwd=PROJECT_DIR, check=True)


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def resolve_release_dir() -> Path:
    try:
        reset_dir(RELEASE_DIR)
        return RELEASE_DIR
    except PermissionError:
        fallback = PROJECT_DIR / "release" / f"YLDQ6.0远程监控系统_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        reset_dir(fallback)
        return fallback


def copy_release_tree() -> Path:
    if not DIST_DIR.exists():
        raise FileNotFoundError(f"Missing dist output: {DIST_DIR}")

    release_dir = resolve_release_dir()
    shutil.copytree(DIST_DIR, release_dir, dirs_exist_ok=True)

    (release_dir / "实时采集会话").mkdir(parents=True, exist_ok=True)

    if LIVE_DEVICES_PATH.exists():
        shutil.copy2(LIVE_DEVICES_PATH, release_dir / "live_devices.json")

    return release_dir


def main() -> int:
    run_packaging()
    release_dir = copy_release_tree()
    archive_path = Path(shutil.make_archive(
        str(release_dir), "zip", root_dir=release_dir.parent, base_dir=release_dir.name
    ))
    print()
    print("Package completed:")
    print(release_dir)
    print(archive_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

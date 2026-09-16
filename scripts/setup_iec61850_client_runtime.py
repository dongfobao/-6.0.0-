"""准备 IEC61850 测试总站使用的 32 位隔离运行时。"""

from __future__ import annotations

import shutil
import struct
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
FIRMWARE_ROOT = PROJECT_DIR.parents[1]
RUNTIME_DIR = PROJECT_DIR / "runtime" / "python32"
PYTHON_ZIP_URL = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-win32.zip"
VCREDIST_URL = "https://download.microsoft.com/download/1/6/5/165255E7-1014-4D0A-B094-B6A430A6BFFC/vcredist_x86.exe"


def download(url: str, target: Path) -> None:
    if not target.exists():
        print(f"下载 {url}")
        urllib.request.urlretrieve(url, target)


def prepare_runtime() -> None:
    source_dll = FIRMWARE_ROOT / "tools" / "iec61850" / "iec61850.dll"
    if not source_dll.exists():
        raise FileNotFoundError(f"未找到协议库: {source_dll}")

    with tempfile.TemporaryDirectory(prefix="yldq_iec61850_") as temporary:
        temp_dir = Path(temporary)
        python_zip = temp_dir / "python32.zip"
        redistributable = temp_dir / "vcredist_x86.exe"
        extract_dir = temp_dir / "vcredist"
        cab_dir = temp_dir / "cab"
        download(PYTHON_ZIP_URL, python_zip)
        download(VCREDIST_URL, redistributable)

        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(python_zip) as archive:
            archive.extractall(RUNTIME_DIR)

        extract_dir.mkdir()
        subprocess.run([str(redistributable), f"/x:{extract_dir}", "/q"], check=True)
        cab_dir.mkdir()
        subprocess.run([str(Path.home().anchor) + r"Windows\System32\expand.exe", "-F:*", str(extract_dir / "vc_red.cab"), str(cab_dir)], check=True)
        shutil.copy2(cab_dir / "F_CENTRAL_msvcr100_x86", RUNTIME_DIR / "msvcr100.dll")
        shutil.copy2(cab_dir / "F_CENTRAL_msvcp100_x86", RUNTIME_DIR / "msvcp100.dll")
        shutil.copy2(source_dll, RUNTIME_DIR / "iec61850.dll")

    dll_bytes = (RUNTIME_DIR / "iec61850.dll").read_bytes()
    pe_offset = struct.unpack_from("<I", dll_bytes, 0x3C)[0]
    machine = struct.unpack_from("<H", dll_bytes, pe_offset + 4)[0]
    if machine != 0x14C:
        raise RuntimeError(f"IEC61850 DLL不是32位x86，machine=0x{machine:04X}")
    result = subprocess.run(
        [str(RUNTIME_DIR / "python.exe"), "-c", "import ctypes; ctypes.CDLL('iec61850.dll'); print('IEC61850 runtime OK')"],
        cwd=RUNTIME_DIR, check=True, capture_output=True, text=True,
    )
    print(result.stdout.strip())
    print(RUNTIME_DIR)


if __name__ == "__main__":
    prepare_runtime()

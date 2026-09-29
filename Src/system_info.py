import math
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from time import time

APP_VERSION = "3.2.0"


def _build_timestamp():
    if getattr(sys, "frozen", False):
        try:
            return Path(sys.executable).stat().st_mtime
        except OSError:
            return time()
    return time()


def _git_commit():
    if getattr(sys, "frozen", False):
        commit_file = Path(getattr(sys, "_MEIPASS", ".")) / "build_commit.txt"
        try:
            return commit_file.read_text(encoding="utf-8").strip() or "release"
        except OSError:
            return "release"
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
            cwd=Path(__file__).resolve().parent.parent,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return result.stdout.strip() or "dev"
    except (OSError, subprocess.SubprocessError):
        return "dev"


def readable_size(size_bytes):
    if size_bytes == 0:
        return "0 bytes"
    units = ["bytes", "KB", "MB", "GB"]
    power = int(math.log(size_bytes, 1024))
    power = min(power, len(units) - 1)
    size = size_bytes / (1024**power)
    return f"{size:.2f} {units[power]}"


def normalize_architecture(arch: str) -> str:
    mapping = {
        "x86_64": "64-Bit",
        "amd64": "AMD64",
        "arm64": "ARM64",
        "aarch64": "ARM64",
    }
    return mapping.get(arch.lower(), arch)


def join_parts(*parts: str | None) -> str:
    return " ".join(part for part in parts if part)


def get_windows_feature_update() -> str | None:
    if platform.system() != "Windows":
        return None

    try:
        import winreg

        key_path = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
            display_version, _ = winreg.QueryValueEx(key, "DisplayVersion")
            return display_version
    except OSError:
        return None


def get_system_info() -> str:
    system = platform.system()
    arch = normalize_architecture(platform.machine())

    if system == "Windows":
        build = platform.version().split(".")[-1]
        return join_parts(
            system,
            platform.release(),
            get_windows_feature_update(),
            platform.win32_edition(),
            f"(Build {build})",
            arch,
        )

    if system == "Linux":
        try:
            os_release = platform.freedesktop_os_release()
            if "PRETTY_NAME" in os_release:
                return join_parts(os_release["PRETTY_NAME"], arch)
            name = os_release.get("NAME", "Linux")
            version = os_release.get("VERSION") or os_release.get("VERSION_ID") or ""
            return join_parts(name, version, arch)
        except (AttributeError, OSError):
            return join_parts(system, platform.release(), arch)

    if system == "Darwin":
        mac_version, *_ = platform.mac_ver()
        if mac_version:
            return join_parts("macOS", mac_version, arch)
        return join_parts("macOS", f"(Darwin {platform.release()})", arch)

    return join_parts(system, platform.release(), arch)


msfr_version = f"{APP_VERSION} ({_git_commit()})"
build_date = (
    datetime.fromtimestamp(_build_timestamp())
    .astimezone()
    .strftime("%Y-%m-%d (%A, %B %d)")
)

"""Provider cho Firefox.

Firefox khong nhan flag '--proxy-server' nhu Chromium, no doc proxy tu
prefs.js/user.js trong profile - can 1 co che rieng (vd tao user.js
trong profile cach ly) chua duoc cai dat. Vi vay launch() hien tra ve
loi ro rang thay vi im lang khong hoat dong; list_profiles() (do
profiles.ini) da dung duoc ngay.
"""

import configparser
import os
import shutil
import sys
from typing import List, Optional, Tuple

from .base import BrowserProvider

WINDOWS_PATHS = [
    r"%ProgramFiles%\Mozilla Firefox\firefox.exe",
    r"%ProgramFiles(x86)%\Mozilla Firefox\firefox.exe",
]
MACOS_PATHS = ["/Applications/Firefox.app/Contents/MacOS/firefox"]
LINUX_BINS = ["firefox", "firefox-esr"]


class FirefoxBrowser(BrowserProvider):
    name = "firefox"
    supports_launch = False

    def find_executable(self) -> Optional[str]:
        if sys.platform.startswith("win"):
            for template in WINDOWS_PATHS:
                path = os.path.expandvars(template)
                if os.path.exists(path):
                    return path
        elif sys.platform == "darwin":
            for path in MACOS_PATHS:
                if os.path.exists(path):
                    return path
        else:
            for bin_name in LINUX_BINS:
                path = shutil.which(bin_name)
                if path:
                    return path
        return None

    def user_data_dir(self) -> str:
        if sys.platform.startswith("win"):
            base = os.path.expandvars(r"%LOCALAPPDATA%")
        elif sys.platform == "darwin":
            base = os.path.expanduser("~/Library/Application Support")
        else:
            base = os.path.expanduser("~/.config")
        return os.path.join(base, "cepp_firefox")

    @staticmethod
    def _profiles_ini() -> str:
        if sys.platform.startswith("win"):
            return os.path.expandvars(r"%APPDATA%\Mozilla\Firefox\profiles.ini")
        elif sys.platform == "darwin":
            return os.path.expanduser("~/Library/Application Support/Firefox/profiles.ini")
        else:
            return os.path.expanduser("~/.mozilla/firefox/profiles.ini")

    def list_profiles(self) -> List[dict]:
        """Đọc profiles.ini để liệt kê các profile Firefox đã có."""
        ini_path = self._profiles_ini()
        if not os.path.exists(ini_path):
            return []
        config = configparser.ConfigParser()
        try:
            config.read(ini_path, encoding="utf-8")
        except Exception:
            return []
        base_dir = os.path.dirname(ini_path)
        profiles = []
        for section in config.sections():
            if not section.startswith("Profile") or not config.has_option(section, "Path"):
                continue
            path = config.get(section, "Path")
            is_relative = config.getboolean(section, "IsRelative", fallback=True)
            full_path = os.path.join(base_dir, path) if is_relative else path
            name = config.get(section, "Name", fallback=path)
            profiles.append({"id": section, "name": name, "path": full_path})
        return profiles

    def launch(
        self, proxy_url: str, sites: List[str], profile_id: Optional[str] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        return None, (
            "Chưa hỗ trợ mở Firefox qua proxy tự động (Firefox cần cấu hình "
            "proxy trong profile, không nhận --proxy-server như Chromium). "
            "Hiện chỉ hỗ trợ dò profile."
        )

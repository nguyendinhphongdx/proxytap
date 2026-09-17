"""Provider dung chung cho moi browser nen Chromium (Chrome, Edge, Brave, ...).

Chrome/Edge/Brave chi khac nhau ve duong dan cai dat va ten thu muc
User Data - toan bo logic con lai (launch flags, doc Local State de
liet ke profile that) giong het nhau, nen dung 1 class duy nhat, cau
hinh bang du lieu (data-driven) thay vi 1 class rieng cho tung hang.
"""

import json
import os
import shutil
import subprocess
import sys
from typing import List, Optional, Tuple

from .base import BrowserProvider


class ChromiumBrowser(BrowserProvider):
    supports_launch = True

    def __init__(
        self,
        name: str,
        windows_paths: List[str],
        macos_paths: List[str],
        linux_bins: List[str],
        windows_user_data_sub: str,
        macos_user_data_sub: str,
        linux_user_data_sub: str,
    ):
        self.name = name
        self._windows_paths = windows_paths
        self._macos_paths = macos_paths
        self._linux_bins = linux_bins
        self._windows_user_data_sub = windows_user_data_sub
        self._macos_user_data_sub = macos_user_data_sub
        self._linux_user_data_sub = linux_user_data_sub

    def find_executable(self) -> Optional[str]:
        if sys.platform.startswith("win"):
            for template in self._windows_paths:
                path = os.path.expandvars(template)
                if os.path.exists(path):
                    return path
        elif sys.platform == "darwin":
            for path in self._macos_paths:
                if os.path.exists(path):
                    return path
        else:  # Linux / các Unix khác
            for bin_name in self._linux_bins:
                path = shutil.which(bin_name)
                if path:
                    return path
        return None

    def user_data_dir(self) -> str:
        """Thư mục profile riêng cho tool này, tách biệt profile chính."""
        if sys.platform.startswith("win"):
            base = os.path.expandvars(r"%LOCALAPPDATA%")
        elif sys.platform == "darwin":
            base = os.path.expanduser("~/Library/Application Support")
        else:
            base = os.path.expanduser("~/.config")
        return os.path.join(base, f"cepp_{self.name}")

    def _real_user_data_root(self) -> Optional[str]:
        """Thư mục 'User Data' thật của browser (khác user_data_dir() ở trên)."""
        if sys.platform.startswith("win"):
            base, sub = os.path.expandvars(r"%LOCALAPPDATA%"), self._windows_user_data_sub
        elif sys.platform == "darwin":
            base, sub = os.path.expanduser("~/Library/Application Support"), self._macos_user_data_sub
        else:
            base, sub = os.path.expanduser("~/.config"), self._linux_user_data_sub
        if not sub:
            return None
        return os.path.join(base, sub)

    def list_profiles(self) -> List[dict]:
        """Đọc 'Local State' (JSON) để liệt kê các profile thật đã có."""
        root = self._real_user_data_root()
        if not root:
            return []
        local_state_path = os.path.join(root, "Local State")
        if not os.path.exists(local_state_path):
            return []
        try:
            with open(local_state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            info_cache = data.get("profile", {}).get("info_cache", {})
            return [
                {"id": folder, "name": meta.get("name", folder), "path": os.path.join(root, folder)}
                for folder, meta in info_cache.items()
            ]
        except Exception:
            return []

    def launch(self, proxy_url: str, sites: List[str]) -> Tuple[Optional[str], Optional[str]]:
        exe = self.find_executable()
        if not exe:
            return None, f"Không tìm thấy {self.name} đã cài đặt."
        args = [
            exe,
            f"--user-data-dir={self.user_data_dir()}",
            "--no-first-run",
            "--no-default-browser-check",
            f"--proxy-server={proxy_url}",
            "--new-window",
            *sites,
        ]
        try:
            subprocess.Popen(args)
            return exe, None
        except Exception as e:
            return None, str(e)

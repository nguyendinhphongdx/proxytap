"""Hang so dung chung, khong thuoc rieng module nao."""

import os
import sys

DEFAULT_PORT = 8899

SITES = ["https://www.facebook.com", "https://www.youtube.com", "https://www.tiktok.com"]


def log_dir() -> str:
    """Thu muc luu file log, tao san neu chua co. Cross-platform."""
    if sys.platform.startswith("win"):
        base = os.path.expandvars(r"%LOCALAPPDATA%")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.path.expanduser("~/.local/share")
    d = os.path.join(base, "cepp_proxy_gui")
    os.makedirs(d, exist_ok=True)
    return d


LOG_FILE = os.path.join(log_dir(), "cepp_proxy_gui.log")

"""Cac 'browser provider' - moi loai browser (Chrome, Edge, Brave, Firefox)
cai dat interface chung o base.py. Danh sach browser duoc dang ky trong
registry.py.
"""

from .base import BrowserProvider
from .registry import (
    BRAVE,
    BROWSERS,
    CHROME,
    EDGE,
    FIREFOX,
    all_browser_names,
    get_browser,
    launchable_browser_names,
)

__all__ = [
    "BrowserProvider",
    "BROWSERS",
    "CHROME",
    "EDGE",
    "BRAVE",
    "FIREFOX",
    "get_browser",
    "all_browser_names",
    "launchable_browser_names",
]

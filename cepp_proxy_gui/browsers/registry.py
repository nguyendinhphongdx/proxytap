"""Noi duy nhat khai bao 'co nhung browser nao' trong tool.

Them 1 browser moi (vd Vivaldi, chi la Chromium khac) chi can them 1
dong ChromiumBrowser(...) o day - khong phai sua UI hay logic launch.
"""

from typing import Dict, List

from .base import BrowserProvider
from .chromium import ChromiumBrowser
from .firefox import FirefoxBrowser

CHROME = ChromiumBrowser(
    name="chrome",
    windows_paths=[
        r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    ],
    macos_paths=["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"],
    linux_bins=["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"],
    windows_user_data_sub=r"Google\Chrome\User Data",
    macos_user_data_sub="Google/Chrome",
    linux_user_data_sub="google-chrome",
)

EDGE = ChromiumBrowser(
    name="edge",
    windows_paths=[
        r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    ],
    macos_paths=["/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"],
    linux_bins=["microsoft-edge", "microsoft-edge-stable", "microsoft-edge-dev"],
    windows_user_data_sub=r"Microsoft\Edge\User Data",
    macos_user_data_sub="Microsoft Edge",
    linux_user_data_sub="microsoft-edge",
)

BRAVE = ChromiumBrowser(
    name="brave",
    windows_paths=[
        r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe",
    ],
    macos_paths=["/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"],
    linux_bins=["brave-browser", "brave-browser-stable", "brave"],
    windows_user_data_sub=r"BraveSoftware\Brave-Browser\User Data",
    macos_user_data_sub="BraveSoftware/Brave-Browser",
    linux_user_data_sub="BraveSoftware/Brave-Browser",
)

FIREFOX = FirefoxBrowser()

BROWSERS: Dict[str, BrowserProvider] = {b.name: b for b in (CHROME, EDGE, BRAVE, FIREFOX)}


def get_browser(name: str) -> BrowserProvider:
    return BROWSERS[name]


def all_browser_names() -> List[str]:
    return list(BROWSERS.keys())


def launchable_browser_names() -> List[str]:
    """Cac browser thuc su ho tro launch() (Firefox chua ho tro)."""
    return [name for name, b in BROWSERS.items() if b.supports_launch]

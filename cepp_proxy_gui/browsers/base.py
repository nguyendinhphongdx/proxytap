"""Interface chung cho moi 'browser provider' (Chrome, Edge, Brave, Firefox, ...).

Them 1 browser moi = viet/cau hinh 1 class ke thua BrowserProvider,
dang ky vao registry.py - khong phai dung tay sua if/elif theo ten
browser rai rac trong UI hay logic launch.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Tuple


class BrowserProvider(ABC):
    name: str = ""
    #: True neu launch() thuc su ho tro mo qua proxy (Chromium-based).
    #: False neu provider nay chi ho tro do profile (vd Firefox hien tai).
    supports_launch: bool = True

    @abstractmethod
    def find_executable(self) -> Optional[str]:
        """Tra ve duong dan file thuc thi neu tim thay tren may, None neu khong."""

    @abstractmethod
    def user_data_dir(self) -> str:
        """Thu muc profile rieng (cach ly) ma tool nay dung khi launch."""

    @abstractmethod
    def list_profiles(self) -> List[dict]:
        """Liet ke cac profile THAT da co san tren may (chi doc, khong sua)."""

    @abstractmethod
    def launch(self, proxy_url: str, sites: List[str]) -> Tuple[Optional[str], Optional[str]]:
        """Mo browser voi proxy_url va danh sach site cho san.

        Tra ve (duong_dan_exe, thong_bao_loi) - thong_bao_loi la None
        neu thanh cong.
        """

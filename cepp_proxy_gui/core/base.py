"""Interface chung cho moi 'proxy provider' (local CONNECT proxy, SSH tunnel, ...).

UI chi lam viec qua interface nay: goi start()/stop() va doc event tu
1 queue.Queue dung chung, khong can biet ben trong tung provider lam
gi khac nhau (asyncio server vs paramiko channel...). Muon them 1
kieu forward traffic moi (vd WireGuard, Shadowsocks) chi can viet 1
class ke thua ProxyProvider, khong phai sua UI.
"""

from abc import ABC, abstractmethod
import queue


class ProxyProvider(ABC):
    """Hop dong toi thieu ma moi provider phai dam bao."""

    def __init__(self, event_queue: "queue.Queue"):
        self.events = event_queue

    @abstractmethod
    def start(self, *args, **kwargs) -> None:
        """Khoi dong provider tren thread/background rieng (khong duoc block)."""

    @abstractmethod
    def stop(self) -> None:
        """Dung provider, giai phong tai nguyen (socket, ket noi SSH, ...)."""

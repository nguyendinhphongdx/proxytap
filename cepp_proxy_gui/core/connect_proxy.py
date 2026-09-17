"""Local HTTP CONNECT proxy - provider don gian nhat.

Nhan CONNECT host:port tu browser, mo ket noi TCP tho toi dich, roi
relay byte 2 chieu. Khong giai ma/can thiep TLS. Chay tren asyncio
event loop rieng (1 thread), bao cao su kien qua queue de UI cap nhat.
"""

import asyncio
import threading
import queue

from .base import ProxyProvider


class ConnectProxy(ProxyProvider):
    """Asyncio CONNECT-proxy chạy trên thread riêng, báo cáo sự kiện qua queue."""

    def __init__(self, event_queue: "queue.Queue"):
        super().__init__(event_queue)
        self.loop = None
        self.server = None
        self.thread = None
        self.allowed_hosts = None  # None = cho phép tất cả; set() = whitelist
        self._active = 0

    def start(self, host: str, port: int):
        self.thread = threading.Thread(target=self._run_loop, args=(host, port), daemon=True)
        self.thread.start()

    def stop(self):
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self._shutdown)

    def set_allowed_hosts(self, hosts):
        self.allowed_hosts = hosts  # set of lowercase suffixes, or None

    def _host_allowed(self, host: str) -> bool:
        if self.allowed_hosts is None:
            return True
        host = host.lower()
        return any(host == d or host.endswith("." + d) for d in self.allowed_hosts)

    def _run_loop(self, host, port):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._main(host, port))
        except Exception as e:
            self.events.put(("error", str(e)))
        finally:
            self.loop.close()
            self.events.put(("stopped", None))

    def _shutdown(self):
        if self.server:
            self.server.close()
        for task in asyncio.all_tasks(self.loop):
            task.cancel()

    async def _pipe(self, reader, writer):
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                writer.write(data)
                await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    async def _handle(self, cr, cw):
        peer = cw.get_extra_info("peername")
        self._active += 1
        self.events.put(("active", self._active))
        try:
            line = await cr.readline()
            if not line:
                return
            parts = line.decode("latin1").split()
            if len(parts) < 2:
                return
            method, target = parts[0], parts[1]

            while True:
                h = await cr.readline()
                if h in (b"\r\n", b"\n", b""):
                    break

            if method.upper() != "CONNECT":
                cw.write(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
                await cw.drain()
                return

            host, _, port_s = target.partition(":")
            port = int(port_s) if port_s else 443

            if not self._host_allowed(host):
                self.events.put(("blocked", f"{host}:{port}"))
                cw.write(b"HTTP/1.1 403 Forbidden\r\n\r\n")
                await cw.drain()
                return

            try:
                sr, sw = await asyncio.open_connection(host, port)
            except Exception as e:
                self.events.put(("log", f"502 {host}:{port} ({e})"))
                cw.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                await cw.drain()
                return

            self.events.put(("log", f"OK  {host}:{port}  <- {peer}"))
            cw.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await cw.drain()
            await asyncio.gather(self._pipe(cr, sw), self._pipe(sr, cw))
        except Exception:
            pass
        finally:
            cw.close()
            self._active -= 1
            self.events.put(("active", self._active))

    async def _main(self, host, port):
        self.server = await asyncio.start_server(self._handle, host, port)
        self.events.put(("started", f"{host}:{port}"))
        async with self.server:
            await self.server.serve_forever()

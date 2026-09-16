"""
cepp_gui.py - Simple local CONNECT proxy.

Chuc nang: mo mot HTTP CONNECT proxy tren 127.0.0.1:<port>, tunnel TCP
tho toi dich duoc yeu cau (vd tu trinh duyet cau hinh proxy toi day).

Chay:  python cepp_gui.py [port]
"""

import asyncio
import sys

DEFAULT_PORT = 8899


class ProxyCore:
    """Asyncio CONNECT-proxy: nhan CONNECT host:port, relay TCP tho 2 chieu."""

    def __init__(self):
        self.server = None

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

            try:
                sr, sw = await asyncio.open_connection(host, port)
            except Exception:
                cw.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                await cw.drain()
                return

            cw.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await cw.drain()
            await asyncio.gather(self._pipe(cr, sw), self._pipe(sr, cw))
        except Exception:
            pass
        finally:
            cw.close()

    async def main(self, host, port):
        self.server = await asyncio.start_server(self._handle, host, port)
        print(f"CONNECT proxy listening on {host}:{port}", flush=True)
        async with self.server:
            await self.server.serve_forever()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    try:
        asyncio.run(ProxyCore().main("127.0.0.1", port))
    except KeyboardInterrupt:
        pass

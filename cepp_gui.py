"""
cepp_gui.py - Simple local CONNECT proxy with a Tkinter control UI.

Chuc nang: mo mot HTTP CONNECT proxy tren 127.0.0.1:<port>, tunnel TCP
tho toi dich duoc trinh duyet yeu cau. Co UI de Start/Stop, doi cong,
xem log ket noi.

Chay:  python cepp_gui.py
"""

import asyncio
import threading
import queue
import time
import tkinter as tk
from tkinter import ttk, messagebox

DEFAULT_PORT = 8899


class ProxyCore:
    """Asyncio CONNECT-proxy chay tren thread rieng, bao cao su kien qua queue."""

    def __init__(self, event_queue: queue.Queue):
        self.events = event_queue
        self.loop = None
        self.server = None
        self.thread = None
        self.allowed_hosts = None  # None = cho phep tat ca; set() = whitelist
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


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("cepp proxy - control panel")
        self.geometry("560x420")
        self.resizable(True, True)

        self.events = queue.Queue()
        self.core = None
        self.running = False

        self._build_ui()
        self.after(100, self._poll_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="Port:").pack(side="left")
        self.port_var = tk.StringVar(value=str(DEFAULT_PORT))
        ttk.Entry(top, textvariable=self.port_var, width=8).pack(side="left", padx=(4, 16))

        self.start_btn = ttk.Button(top, text="Start", command=self._on_start)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(top, text="Stop", command=self._on_stop, state="disabled")
        self.stop_btn.pack(side="left", padx=(6, 16))

        self.status_var = tk.StringVar(value="Stopped")
        ttk.Label(top, textvariable=self.status_var, foreground="gray").pack(side="left")
        self.active_var = tk.StringVar(value="active: 0")
        ttk.Label(top, textvariable=self.active_var).pack(side="right")

        wl = ttk.LabelFrame(self, text="Gioi han domain (de trong = cho phep tat ca)", padding=8)
        wl.pack(fill="x", padx=10, pady=(0, 6))
        self.wl_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(wl, text="Chi cho phep domain trong danh sach",
                         variable=self.wl_enabled, command=self._apply_whitelist).pack(anchor="w")
        self.wl_text = tk.Text(wl, height=3)
        self.wl_text.insert("1.0", "facebook.com\nfbcdn.net\nyoutube.com\nytimg.com\ntiktok.com\ntiktokcdn.com")
        self.wl_text.pack(fill="x", pady=(4, 4))
        ttk.Button(wl, text="Ap dung", command=self._apply_whitelist).pack(anchor="e")

        logf = ttk.LabelFrame(self, text="Log ket noi", padding=6)
        logf.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.log = tk.Text(logf, state="disabled", wrap="none")
        self.log.pack(fill="both", expand=True, side="left")
        sb = ttk.Scrollbar(logf, command=self.log.yview)
        sb.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=sb.set)

    def _apply_whitelist(self):
        if not self.core:
            return
        if self.wl_enabled.get():
            hosts = {h.strip().lower() for h in self.wl_text.get("1.0", "end").splitlines() if h.strip()}
            self.core.set_allowed_hosts(hosts)
            self._append_log(f"[whitelist bat: {len(hosts)} domain]")
        else:
            self.core.set_allowed_hosts(None)
            self._append_log("[whitelist tat: cho phep tat ca]")

    def _on_start(self):
        try:
            port = int(self.port_var.get())
        except ValueError:
            messagebox.showerror("Loi", "Port khong hop le")
            return
        self.core = ProxyCore(self.events)
        if self.wl_enabled.get():
            hosts = {h.strip().lower() for h in self.wl_text.get("1.0", "end").splitlines() if h.strip()}
            self.core.set_allowed_hosts(hosts)
        self.core.start("127.0.0.1", port)
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")

    def _on_stop(self):
        if self.core:
            self.core.stop()
        self.stop_btn.config(state="disabled")

    def _on_close(self):
        if self.core:
            self.core.stop()
        self.destroy()

    def _append_log(self, text):
        self.log.configure(state="normal")
        ts = time.strftime("%H:%M:%S")
        self.log.insert("end", f"[{ts}] {text}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _poll_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "started":
                    self.status_var.set(f"Running on {payload}")
                    self.running = True
                elif kind == "stopped":
                    self.status_var.set("Stopped")
                    self.running = False
                    self.start_btn.config(state="normal")
                    self.stop_btn.config(state="disabled")
                elif kind == "error":
                    self._append_log(f"[loi] {payload}")
                    messagebox.showerror("Loi proxy", payload)
                elif kind == "log":
                    self._append_log(payload)
                elif kind == "blocked":
                    self._append_log(f"BLOCKED {payload}")
                elif kind == "active":
                    self.active_var.set(f"active: {payload}")
        except queue.Empty:
            pass
        self.after(100, self._poll_events)


if __name__ == "__main__":
    App().mainloop()

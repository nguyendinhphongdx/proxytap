"""
cepp_gui.py - Simple local CONNECT proxy with a Tkinter control UI.

Chức năng: mở một HTTP CONNECT proxy trên 127.0.0.1:<port>, tunnel TCP
thô tới đích browser yêu cầu. Có UI để Start/Stop, đổi cổng, xem log
kết nối, và (tùy chọn) giới hạn theo danh sách domain cho phép.

Chạy:  python cepp_gui.py
"""

import asyncio
import os
import shutil
import socket
import subprocess
import sys
import threading
import queue
import time
import tkinter as tk
from tkinter import ttk, messagebox

try:
    import paramiko
    HAVE_PARAMIKO = True
except ImportError:
    HAVE_PARAMIKO = False

DEFAULT_PORT = 8899

SITES = ["https://www.facebook.com", "https://www.youtube.com", "https://www.tiktok.com"]

# Đường dẫn cài đặt mặc định trên Windows / macOS.
WINDOWS_BROWSER_PATHS = {
    "chrome": [
        r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    ],
    "edge": [
        r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    ],
    "brave": [
        r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe",
    ],
}

MACOS_BROWSER_PATHS = {
    "chrome": ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"],
    "edge": ["/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"],
    "brave": ["/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"],
}

# Trên Linux, trình duyệt nằm trong PATH nên dò bằng shutil.which theo tên lệnh.
LINUX_BROWSER_BINS = {
    "chrome": ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"],
    "edge": ["microsoft-edge", "microsoft-edge-stable", "microsoft-edge-dev"],
    "brave": ["brave-browser", "brave-browser-stable", "brave"],
}


def find_browser_exe(name: str):
    if sys.platform.startswith("win"):
        for template in WINDOWS_BROWSER_PATHS.get(name, []):
            path = os.path.expandvars(template)
            if os.path.exists(path):
                return path
    elif sys.platform == "darwin":
        for path in MACOS_BROWSER_PATHS.get(name, []):
            if os.path.exists(path):
                return path
    else:  # Linux / các Unix khác
        for bin_name in LINUX_BROWSER_BINS.get(name, []):
            path = shutil.which(bin_name)
            if path:
                return path
    return None


def user_data_dir(name: str) -> str:
    """Thư mục profile riêng cho browser, tách biệt profile chính. Cross-platform."""
    if sys.platform.startswith("win"):
        base = os.path.expandvars(r"%LOCALAPPDATA%")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.path.expanduser("~/.config")
    return os.path.join(base, f"cepp_{name}")


def launch_browser(name: str, port: int):
    exe = find_browser_exe(name)
    if not exe:
        return None, f"Không tìm thấy {name} đã cài đặt."
    udd = user_data_dir(name)
    args = [
        exe,
        f"--user-data-dir={udd}",
        "--no-first-run",
        "--no-default-browser-check",
        f"--proxy-server=http://127.0.0.1:{port}",
        "--new-window",
        *SITES,
    ]
    try:
        subprocess.Popen(args)
        return exe, None
    except Exception as e:
        return None, str(e)


class ProxyCore:
    """Asyncio CONNECT-proxy chạy trên thread riêng, báo cáo sự kiện qua queue."""

    def __init__(self, event_queue: queue.Queue):
        self.events = event_queue
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


class SSHSocksTunnel:
    """SOCKS5 proxy local, forward moi ket noi qua kenh SSH (paramiko) toi VPS.

    Khac voi ProxyCore: doan tu may minh toi VPS duoc SSH ma hoa toan bo,
    nen ISP/router noi dia khong doc duoc domain (SNI) hay can thiep DNS -
    dung cho truong hop chan o tang mang thay vi chan theo tien trinh.
    """

    def __init__(self, event_queue: queue.Queue):
        self.events = event_queue
        self.client = None
        self.transport = None
        self.server_sock = None
        self.running = False
        self.accept_thread = None
        self._active = 0

    def connect_and_serve(self, ssh_host, ssh_port, username, password, key_path,
                           key_passphrase, local_host, local_port):
        threading.Thread(
            target=self._run,
            args=(ssh_host, ssh_port, username, password, key_path,
                  key_passphrase, local_host, local_port),
            daemon=True,
        ).start()

    def _run(self, ssh_host, ssh_port, username, password, key_path,
              key_passphrase, local_host, local_port):
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            connect_kwargs = dict(hostname=ssh_host, port=ssh_port, username=username, timeout=15)
            if key_path:
                connect_kwargs["key_filename"] = key_path
                if key_passphrase:
                    connect_kwargs["passphrase"] = key_passphrase
            else:
                connect_kwargs["password"] = password
            self.client.connect(**connect_kwargs)
            self.transport = self.client.get_transport()

            self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_sock.bind((local_host, local_port))
            self.server_sock.listen(128)
            self.running = True
            self.events.put(("ssh_connected", f"{local_host}:{local_port}"))

            while self.running:
                try:
                    client_sock, _ = self.server_sock.accept()
                except OSError:
                    break
                threading.Thread(target=self._handle_socks, args=(client_sock,), daemon=True).start()
        except Exception as e:
            self.events.put(("ssh_error", str(e)))
        finally:
            self.running = False
            self.events.put(("ssh_stopped", None))

    def stop(self):
        self.running = False
        try:
            if self.server_sock:
                self.server_sock.close()
        except Exception:
            pass
        try:
            if self.client:
                self.client.close()
        except Exception:
            pass

    def _handle_socks(self, client_sock):
        self._active += 1
        self.events.put(("ssh_active", self._active))
        dest = None
        try:
            greeting = client_sock.recv(262)
            if len(greeting) < 2 or greeting[0] != 0x05:
                return
            client_sock.sendall(b"\x05\x00")  # khong yeu cau auth

            req = client_sock.recv(4)
            if len(req) < 4:
                return
            _, cmd, _, atyp = req
            if cmd != 1:  # chi ho tro CONNECT
                client_sock.sendall(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00")
                return

            if atyp == 1:
                dest_host = socket.inet_ntoa(client_sock.recv(4))
            elif atyp == 3:
                length = client_sock.recv(1)[0]
                dest_host = client_sock.recv(length).decode("idna", errors="replace")
            elif atyp == 4:
                dest_host = socket.inet_ntop(socket.AF_INET6, client_sock.recv(16))
            else:
                client_sock.sendall(b"\x05\x08\x00\x01\x00\x00\x00\x00\x00\x00")
                return
            dest_port = int.from_bytes(client_sock.recv(2), "big")
            dest = f"{dest_host}:{dest_port}"

            channel = self.transport.open_channel(
                "direct-tcpip", (dest_host, dest_port), ("127.0.0.1", 0), timeout=15
            )
            client_sock.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
            self.events.put(("log", f"SSH OK  {dest}"))
            self._relay(client_sock, channel)
        except Exception as e:
            self.events.put(("log", f"SSH loi {dest or '?'} ({e})"))
            try:
                client_sock.sendall(b"\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00")
            except Exception:
                pass
        finally:
            try:
                client_sock.close()
            except Exception:
                pass
            self._active -= 1
            self.events.put(("ssh_active", self._active))

    def _relay(self, sock, channel):
        def sock_to_channel():
            try:
                while True:
                    data = sock.recv(65536)
                    if not data:
                        break
                    channel.sendall(data)
            except Exception:
                pass
            finally:
                try:
                    channel.close()
                except Exception:
                    pass

        def channel_to_sock():
            try:
                while True:
                    data = channel.recv(65536)
                    if not data:
                        break
                    sock.sendall(data)
            except Exception:
                pass
            finally:
                try:
                    sock.close()
                except Exception:
                    pass

        t1 = threading.Thread(target=sock_to_channel, daemon=True)
        t2 = threading.Thread(target=channel_to_sock, daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()


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

        ttk.Label(top, text="Browser:").pack(side="left")
        self.browser_var = tk.StringVar(value="chrome")
        ttk.Combobox(top, textvariable=self.browser_var, values=["chrome", "edge", "brave"],
                     width=8, state="readonly").pack(side="left", padx=(4, 6))
        self.open_btn = ttk.Button(top, text="Mở trình duyệt", command=self._on_open_browser, state="disabled")
        self.open_btn.pack(side="left")

        row2 = ttk.Frame(self, padding=(10, 0))
        row2.pack(fill="x")
        self.status_var = tk.StringVar(value="Stopped")
        ttk.Label(row2, textvariable=self.status_var, foreground="gray").pack(side="left")
        self.active_var = tk.StringVar(value="active: 0")
        ttk.Label(row2, textvariable=self.active_var).pack(side="right")

        wl = ttk.LabelFrame(self, text="Giới hạn domain (để trống = cho phép tất cả)", padding=8)
        wl.pack(fill="x", padx=10, pady=(0, 6))
        self.wl_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(wl, text="Chỉ cho phép domain trong danh sách",
                         variable=self.wl_enabled, command=self._apply_whitelist).pack(anchor="w")
        self.wl_text = tk.Text(wl, height=3)
        self.wl_text.insert("1.0", "facebook.com\nfbcdn.net\nyoutube.com\nytimg.com\ntiktok.com\ntiktokcdn.com")
        self.wl_text.pack(fill="x", pady=(4, 4))
        ttk.Button(wl, text="Áp dụng", command=self._apply_whitelist).pack(anchor="e")

        logf = ttk.LabelFrame(self, text="Log kết nối", padding=6)
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
            self._append_log(f"[whitelist bật: {len(hosts)} domain]")
        else:
            self.core.set_allowed_hosts(None)
            self._append_log("[whitelist tắt: cho phép tất cả]")

    def _on_start(self):
        try:
            port = int(self.port_var.get())
        except ValueError:
            messagebox.showerror("Lỗi", "Port không hợp lệ")
            return
        self.core = ProxyCore(self.events)
        if self.wl_enabled.get():
            hosts = {h.strip().lower() for h in self.wl_text.get("1.0", "end").splitlines() if h.strip()}
            self.core.set_allowed_hosts(hosts)
        self.core.start("127.0.0.1", port)
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.open_btn.config(state="normal")

    def _on_stop(self):
        if self.core:
            self.core.stop()
        self.stop_btn.config(state="disabled")
        self.open_btn.config(state="disabled")

    def _on_open_browser(self):
        try:
            port = int(self.port_var.get())
        except ValueError:
            messagebox.showerror("Lỗi", "Port không hợp lệ")
            return
        name = self.browser_var.get()
        exe, err = launch_browser(name, port)
        if err:
            self._append_log(f"[lỗi mở browser] {err}")
            messagebox.showerror("Lỗi", err)
        else:
            self._append_log(f"[mở {name}] {exe}")

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
                    self._append_log(f"[lỗi] {payload}")
                    messagebox.showerror("Lỗi proxy", payload)
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

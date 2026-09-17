"""Tkinter control panel.

App chi lam viec qua 2 interface (ProxyProvider, BrowserProvider) va
registry cua tung loai - khong biet ConnectProxy/SSHSocksTunnel hay
ChromiumBrowser/FirefoxBrowser lam viec ben trong the nao. Muon them
1 browser hay 1 kieu tunnel moi, sua o browsers/registry.py hoac
core/__init__.py, KHONG can dung toi file nay.
"""

import os
import queue
import subprocess
import sys
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from ..browsers import get_browser, launchable_browser_names
from ..constants import DEFAULT_PORT, LOG_FILE, SITES
from ..core import HAVE_PARAMIKO, ConnectProxy, SSHSocksTunnel


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("cepp proxy - control panel")
        self.geometry("640x680")
        self.resizable(True, True)

        self.events = queue.Queue()
        self.core = None
        self.running = False
        self.ssh_tunnel = None
        self.ssh_running = False
        self._ssh_dialog = None

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
        browser_cb = ttk.Combobox(top, textvariable=self.browser_var, values=launchable_browser_names(),
                                   width=8, state="readonly")
        browser_cb.pack(side="left", padx=(4, 6))
        browser_cb.bind("<<ComboboxSelected>>", lambda e: self._reset_profile_choice())

        row2 = ttk.Frame(self, padding=(10, 0))
        row2.pack(fill="x")
        self.status_var = tk.StringVar(value="Stopped")
        ttk.Label(row2, textvariable=self.status_var, foreground="gray").pack(side="left")
        self.active_var = tk.StringVar(value="active: 0")
        ttk.Label(row2, textvariable=self.active_var).pack(side="right")

        # Chọn browser sẽ đi qua ngả nào rồi mở
        openf = ttk.Frame(self, padding=(10, 6))
        openf.pack(fill="x")
        ttk.Label(openf, text="Mở trình duyệt qua:").pack(side="left")
        self.route_var = tk.StringVar(value="local")
        ttk.Radiobutton(openf, text="Local Proxy", variable=self.route_var, value="local").pack(side="left", padx=(6, 0))
        ttk.Radiobutton(openf, text="VPS qua SSH (SOCKS5)", variable=self.route_var, value="ssh").pack(side="left", padx=(6, 0))
        self.open_btn = ttk.Button(openf, text="Mở trình duyệt", command=self._on_open_browser, state="disabled")
        self.open_btn.pack(side="right")

        # Profile browser: do (chi doc) + click thang vao dong trong danh sach
        # de chon profile do lam profile mo qua proxy. Chi ap dung cho browser
        # ho tro launch (Chromium-based) - Firefox chua ho tro nen khong xuat
        # hien o day. Dong dau tien luon la "profile rieng cua tool" (mac dinh).
        pf = ttk.LabelFrame(
            self, text="Profile browser (theo Browser đã chọn ở trên) — click 1 dòng để chọn dùng",
            padding=8,
        )
        pf.pack(fill="x", padx=10, pady=(0, 6))
        ttk.Button(pf, text="Dò profile", command=self._on_scan_profiles).pack(anchor="w")

        self.ISOLATED_LABEL = "— Profile riêng của tool (mặc định, cách ly) —"
        self._profile_ids = [None]
        self.profile_list = tk.Listbox(pf, height=4, exportselection=False)
        self.profile_list.pack(fill="x", pady=(6, 0))
        self.profile_list.insert("end", self.ISOLATED_LABEL)
        self.profile_list.selection_set(0)
        self.profile_list.bind("<<ListboxSelect>>", self._on_pick_profile)

        self.profile_choice_var = tk.StringVar(value=f"Đang dùng: {self.ISOLATED_LABEL}")
        ttk.Label(pf, textvariable=self.profile_choice_var, foreground="gray").pack(anchor="w", pady=(4, 0))

        ttk.Label(
            pf,
            text=("⚠ Nếu chọn profile thật: phải ĐÓNG hết cửa sổ browser đang dùng "
                  "profile đó trước khi Mở trình duyệt — nếu không, Chrome/Edge/Brave "
                  "dùng chung tiến trình theo profile và cờ proxy sẽ bị BỎ QUA."),
            foreground="#b45309", wraplength=580, justify="left",
        ).pack(anchor="w", pady=(4, 0))

        wl = ttk.LabelFrame(self, text="Giới hạn domain (để trống = cho phép tất cả)", padding=8)
        wl.pack(fill="x", padx=10, pady=(0, 6))
        self.wl_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(wl, text="Chỉ cho phép domain trong danh sách",
                         variable=self.wl_enabled, command=self._apply_whitelist).pack(anchor="w")
        self.wl_text = tk.Text(wl, height=3)
        self.wl_text.insert("1.0", "facebook.com\nfbcdn.net\nyoutube.com\nytimg.com\ntiktok.com\ntiktokcdn.com")
        self.wl_text.pack(fill="x", pady=(4, 4))
        ttk.Button(wl, text="Áp dụng", command=self._apply_whitelist).pack(anchor="e")

        # SSH Tunnel (VPS) - dùng khi chặn ở tầng mạng (DNS/SNI), không phải
        # theo tiến trình. Ít khi cần đến nên chỉ hiện 1 dòng gọn ở đây, cấu
        # hình đầy đủ nằm trong dialog riêng mở khi bấm "Cấu hình...".
        self.ssh_host_var = tk.StringVar()
        self.ssh_port_var = tk.StringVar(value="22")
        self.ssh_user_var = tk.StringVar()
        self.ssh_pass_var = tk.StringVar()
        self.ssh_key_var = tk.StringVar()
        self.socks_port_var = tk.StringVar(value="1080")
        self.ssh_status_var = tk.StringVar(value="Chưa kết nối")

        sshf = ttk.Frame(self, padding=(10, 6))
        sshf.pack(fill="x")
        ttk.Label(sshf, text="SSH Tunnel (VPS):").pack(side="left")
        ttk.Label(sshf, textvariable=self.ssh_status_var, foreground="gray").pack(side="left", padx=(6, 0))
        ttk.Button(sshf, text="Cấu hình...", command=self._open_ssh_dialog).pack(side="right")

        logf = ttk.LabelFrame(self, text="Log kết nối", padding=6)
        logf.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        logf_top = ttk.Frame(logf)
        logf_top.pack(fill="x", pady=(0, 4))
        ttk.Label(logf_top, text=f"Lưu tại: {LOG_FILE}", foreground="gray").pack(side="left")
        ttk.Button(logf_top, text="Mở thư mục log", command=self._open_log_folder).pack(side="right")
        self.log = tk.Text(logf, state="disabled", wrap="none", height=14)
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
        self.core = ConnectProxy(self.events)
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
        route = self.route_var.get()
        name = self.browser_var.get()
        if route == "local":
            try:
                port = int(self.port_var.get())
            except ValueError:
                messagebox.showerror("Lỗi", "Port không hợp lệ")
                return
            proxy_url = f"http://127.0.0.1:{port}"
        else:
            if not self.ssh_running:
                messagebox.showerror("Lỗi", "Chưa Connect SSH Tunnel.")
                return
            try:
                socks_port = int(self.socks_port_var.get())
            except ValueError:
                messagebox.showerror("Lỗi", "SOCKS port không hợp lệ")
                return
            proxy_url = f"socks5://127.0.0.1:{socks_port}"

        profile_id = self._selected_profile_id()

        browser = get_browser(name)
        exe, err = browser.launch(proxy_url, SITES, profile_id=profile_id)
        if err:
            self._append_log(f"[lỗi mở browser] {err}")
            messagebox.showerror("Lỗi", err)
        elif profile_id:
            self._append_log(f"[mở {name} qua {proxy_url}, profile thật '{profile_id}'] {exe}")
        else:
            self._append_log(f"[mở {name} qua {proxy_url}, profile riêng của tool] {exe}")

    def _selected_profile_id(self):
        sel = self.profile_list.curselection()
        if not sel or sel[0] >= len(self._profile_ids):
            return None
        return self._profile_ids[sel[0]]

    def _on_pick_profile(self, _event=None):
        sel = self.profile_list.curselection()
        if not sel:
            return
        label = self.profile_list.get(sel[0])
        self.profile_choice_var.set(f"Đang dùng: {label}")

    def _reset_profile_choice(self):
        """Khi đổi Browser, xóa danh sách profile cũ (khác browser -> khác id)."""
        self.profile_list.delete(0, "end")
        self._profile_ids = [None]
        self.profile_list.insert("end", self.ISOLATED_LABEL)
        self.profile_list.selection_set(0)
        self.profile_choice_var.set(f"Đang dùng: {self.ISOLATED_LABEL}")

    def _on_scan_profiles(self):
        name = self.browser_var.get()
        profiles = get_browser(name).list_profiles()
        self.profile_list.delete(0, "end")
        self._profile_ids = [None]
        self.profile_list.insert("end", self.ISOLATED_LABEL)
        for p in profiles:
            self.profile_list.insert("end", f"{p['name']}   —   {p['path']}")
            self._profile_ids.append(p["id"])
        self.profile_list.selection_set(0)
        self.profile_choice_var.set(f"Đang dùng: {self.ISOLATED_LABEL}")
        if profiles:
            self._append_log(f"[dò profile] {name}: tìm thấy {len(profiles)} profile")
        else:
            self._append_log(f"[dò profile] {name}: không tìm thấy profile nào")

    def _open_ssh_dialog(self):
        """Mo dialog cau hinh SSH Tunnel. Chi build widget 1 lan (singleton),
        lan sau chi deiconify+lift - tranh loi 'widget destroyed' vi
        _poll_events con giu tham chieu ssh_connect_btn/ssh_disconnect_btn.
        """
        if self._ssh_dialog is not None and self._ssh_dialog.winfo_exists():
            self._ssh_dialog.deiconify()
            self._ssh_dialog.lift()
            self._ssh_dialog.focus_force()
            return

        dlg = tk.Toplevel(self)
        dlg.title("Cấu hình SSH Tunnel (VPS)")
        dlg.resizable(False, False)
        dlg.protocol("WM_DELETE_WINDOW", dlg.withdraw)  # dong = an, khong huy
        self._ssh_dialog = dlg

        frm = ttk.Frame(dlg, padding=10)
        frm.pack(fill="both", expand=True)

        if not HAVE_PARAMIKO:
            ttk.Label(
                frm, foreground="red",
                text="Chưa cài paramiko. Chạy:  pip install paramiko",
            ).pack(anchor="w", pady=(0, 6))

        r1 = ttk.Frame(frm)
        r1.pack(fill="x", pady=2)
        ttk.Label(r1, text="VPS host:", width=12).pack(side="left")
        ttk.Entry(r1, textvariable=self.ssh_host_var, width=28).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Label(r1, text="Port:").pack(side="left")
        ttk.Entry(r1, textvariable=self.ssh_port_var, width=6).pack(side="left", padx=(4, 0))

        r2 = ttk.Frame(frm)
        r2.pack(fill="x", pady=2)
        ttk.Label(r2, text="Username:", width=12).pack(side="left")
        ttk.Entry(r2, textvariable=self.ssh_user_var).pack(side="left", fill="x", expand=True)

        r3 = ttk.Frame(frm)
        r3.pack(fill="x", pady=2)
        ttk.Label(r3, text="Password:", width=12).pack(side="left")
        ttk.Entry(r3, textvariable=self.ssh_pass_var, show="*").pack(side="left", fill="x", expand=True)

        r4 = ttk.Frame(frm)
        r4.pack(fill="x", pady=2)
        ttk.Label(r4, text="Hoặc key file:", width=12).pack(side="left")
        ttk.Entry(r4, textvariable=self.ssh_key_var).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(r4, text="Chọn...", command=self._on_browse_key).pack(side="left")

        r5 = ttk.Frame(frm)
        r5.pack(fill="x", pady=(8, 2))
        ttk.Label(r5, text="SOCKS port local:", width=16).pack(side="left")
        ttk.Entry(r5, textvariable=self.socks_port_var, width=8).pack(side="left", padx=(0, 16))
        self.ssh_connect_btn = ttk.Button(r5, text="Connect", command=self._on_ssh_connect,
                                           state=("normal" if HAVE_PARAMIKO else "disabled"))
        self.ssh_connect_btn.pack(side="left")
        self.ssh_disconnect_btn = ttk.Button(r5, text="Disconnect", command=self._on_ssh_disconnect, state="disabled")
        self.ssh_disconnect_btn.pack(side="left", padx=(6, 0))

        r6 = ttk.Frame(frm)
        r6.pack(fill="x", pady=(4, 0))
        ttk.Label(r6, textvariable=self.ssh_status_var, foreground="gray").pack(side="left")

        ttk.Button(frm, text="Đóng", command=dlg.withdraw).pack(anchor="e", pady=(10, 0))

    def _on_browse_key(self):
        path = filedialog.askopenfilename(title="Chọn SSH private key")
        if path:
            self.ssh_key_var.set(path)

    def _on_ssh_connect(self):
        if not HAVE_PARAMIKO:
            messagebox.showerror("Lỗi", "Chưa cài paramiko. Chạy: pip install paramiko")
            return
        host = self.ssh_host_var.get().strip()
        if not host:
            messagebox.showerror("Lỗi", "Nhập VPS host")
            return
        try:
            ssh_port = int(self.ssh_port_var.get())
            socks_port = int(self.socks_port_var.get())
        except ValueError:
            messagebox.showerror("Lỗi", "Port không hợp lệ")
            return
        username = self.ssh_user_var.get().strip()
        password = self.ssh_pass_var.get() or None
        key_path = self.ssh_key_var.get().strip() or None
        if not username or (not password and not key_path):
            messagebox.showerror("Lỗi", "Cần username và (password hoặc key file)")
            return

        self.ssh_tunnel = SSHSocksTunnel(self.events)
        self.ssh_connect_btn.config(state="disabled")
        self.ssh_status_var.set("Đang kết nối...")
        self.ssh_tunnel.start(
            host, ssh_port, username, password, key_path, None, "127.0.0.1", socks_port,
        )

    def _on_ssh_disconnect(self):
        if self.ssh_tunnel:
            self.ssh_tunnel.stop()
        self.ssh_disconnect_btn.config(state="disabled")

    def _on_close(self):
        if self.core:
            self.core.stop()
        if self.ssh_tunnel:
            self.ssh_tunnel.stop()
        self.destroy()

    def _append_log(self, text):
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {text}"

        self.log.configure(state="normal")
        self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def _open_log_folder(self):
        folder = os.path.dirname(LOG_FILE)
        try:
            if sys.platform.startswith("win"):
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không mở được thư mục log: {e}")

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
                elif kind == "ssh_connected":
                    self.ssh_running = True
                    self.ssh_status_var.set(f"Đang chạy SOCKS5 tại {payload}")
                    self.ssh_disconnect_btn.config(state="normal")
                    self.open_btn.config(state="normal")
                    self._append_log(f"[SSH tunnel] đã kết nối, SOCKS5 tại {payload}")
                elif kind == "ssh_error":
                    self.ssh_status_var.set("Lỗi kết nối")
                    self.ssh_connect_btn.config(state="normal")
                    self._append_log(f"[SSH tunnel lỗi] {payload}")
                    messagebox.showerror("Lỗi SSH Tunnel", payload)
                elif kind == "ssh_stopped":
                    self.ssh_running = False
                    self.ssh_status_var.set("Chưa kết nối")
                    self.ssh_connect_btn.config(state="normal" if HAVE_PARAMIKO else "disabled")
                    self.ssh_disconnect_btn.config(state="disabled")
                    if not self.running:
                        self.open_btn.config(state="disabled")
                elif kind == "ssh_active":
                    self.active_var.set(f"SSH active: {payload}")
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

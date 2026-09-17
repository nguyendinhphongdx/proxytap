# proxytap

A small, self-contained local proxy with a Tkinter control panel. It exists
to solve one specific problem: **on some machines, a browser's outbound
network connections are blocked by process identity** (a filtering tool or
device policy that keys off `chrome.exe`/`msedge.exe` specifically), while a
different, unmonitored process making the exact same connection is not.

This tool runs that "different process" as a small, auditable Python
package instead of an opaque pre-built binary, and adds a GUI so you can
see and control exactly what it's doing.

## What it does

1. **Local CONNECT proxy** (`core.ConnectProxy`) — a tiny `asyncio` HTTP
   CONNECT tunnel on `127.0.0.1:<port>`. It accepts `CONNECT host:port` from
   the browser, opens a raw TCP connection to the real destination, and
   relays bytes both ways. It does not decrypt, inspect, or modify TLS
   traffic — it's a dumb pipe.
2. **Browser launcher** — detects an installed Chrome/Edge/Brave on
   Windows, macOS, or Linux, and launches it with `--proxy-server` pointing
   at the local proxy, using a separate `--user-data-dir` so it doesn't
   touch your main browser profile.
3. **Optional domain whitelist** — restrict the proxy to a list of allowed
   domains (with subdomain matching) instead of tunneling to anything the
   browser asks for.
4. **SSH SOCKS5 tunnel** (`core.SSHSocksTunnel`) — an alternative transport
   for a harder problem (see [Limitations](#limitations) below): connects to
   a VPS you control over SSH (via `paramiko`) and runs a local SOCKS5
   server that forwards each connection through the encrypted SSH channel.
   Point the browser at this instead of the local proxy when the block is
   at the network layer rather than the process layer. Configured from its
   own dialog to keep it out of the way when you're not using it.
5. **Profile detection + reuse** — lists real, existing Chrome/Edge/Brave
   profiles (via `Local State`) by name and path, and can launch directly
   into one of them (`--profile-directory`) instead of the tool's isolated
   profile, so an already-logged-in session (Facebook/YouTube/etc.) works
   immediately with no re-login. Firefox profile detection (via
   `profiles.ini`) is implemented but not yet wired into launching.
6. **Persistent log** — every connection/event line is written to a log
   file in addition to the on-screen log, so history survives closing the
   app.

## Project structure

```
run.py                          thin entry point (python run.py)
proxytap/
├── constants.py                shared constants (port, sites, log path)
├── core/                       "proxy provider" implementations
│   ├── base.py                 ProxyProvider interface (start/stop contract)
│   ├── connect_proxy.py        ConnectProxy — local HTTP CONNECT tunnel
│   └── ssh_tunnel.py           SSHSocksTunnel — SOCKS5 over SSH (paramiko)
├── browsers/                   "browser provider" implementations
│   ├── base.py                 BrowserProvider interface
│   ├── chromium.py             ChromiumBrowser (data-driven: Chrome/Edge/Brave)
│   ├── firefox.py              FirefoxBrowser (profile detection only so far)
│   └── registry.py             the one place that lists supported browsers
└── ui/
    └── app.py                  Tkinter App — talks only to the interfaces above
```

Both "provider" concepts follow the same shape (a small ABC in `base.py`
per package): the UI calls `start()`/`stop()` on whichever `ProxyProvider`
is active, and `find_executable()`/`user_data_dir()`/`list_profiles()`/
`launch()` on whichever `BrowserProvider` is selected, without knowing or
caring which concrete class it's talking to. Adding a new transport (e.g.
WireGuard) or a new Chromium-based browser (e.g. Vivaldi) means adding one
class or one registry entry — the UI code doesn't change.

## Requirements

- Python 3.9+
- `tkinter` (included with most Python installs; on some Linux distros:
  `sudo apt install python3-tk`)
- `paramiko` — only needed for the SSH Tunnel feature:
  ```bash
  pip install paramiko
  ```

## Usage

```bash
python run.py
# equivalent: python -m proxytap
```

1. Set a port (default `8899`) and click **Start**.
2. Pick a browser. Optionally click **Dò profile** and select a real,
   already-logged-in profile from the list instead of the isolated default
   — if you do, close any window already using that profile first (see the
   warning in the UI: Chromium reuses one process per profile, so an
   already-running window would silently ignore the proxy flag).
3. Click **Mở trình duyệt** — it launches with the proxy configured and a
   few sites pre-opened.
4. Optionally enable the domain whitelist to restrict what the proxy will
   tunnel to.

Connection events are logged both in the UI and to a file (path shown
above the log view, with a shortcut button to open its folder).

### SSH Tunnel mode

Click **Cấu hình...** next to "SSH Tunnel (VPS)" to open its dialog, fill
in your VPS's host, port, username, and password or private key, then
click **Connect**. Once connected, switch the "Mở trình duyệt qua" radio
button to **VPS qua SSH (SOCKS5)** before opening the browser.

## Building a standalone executable

```bash
pip install pyinstaller
pyinstaller --onefile --noconsole --name proxytap run.py
```

This produces a single executable in `dist/` — no Python installation
required to run it. Pre-built Windows binaries are attached to
[Releases](../../releases) for convenience.

## How it works

```
Browser  --[TCP to 127.0.0.1]-->  proxytap  --[TCP to the real destination]-->  Internet
```

The browser only ever opens a connection to `127.0.0.1`. The connection
that actually reaches the internet is opened by this tool's own process,
not the browser's. If a filter on your machine blocks outbound connections
*by process identity* (rather than by inspecting the traffic itself), it
sees the browser only talking to localhost and this tool talking to the
outside world — and if it has no rule for this process, the connection
goes through.

## Limitations

This tool changes **which process** opens the connection. It does **not**
change what's inside the connection. That distinction matters a lot:

- **Process-based filtering** (a local agent or firewall rule that blocks
  `chrome.exe` specifically): the local CONNECT proxy mode generally works,
  because the real outbound connection is made by a different executable.
- **Network-level blocking** (DNS sinkholing or SNI/DPI inspection at your
  router or ISP): the local CONNECT proxy **does not help**, because the
  destination hostname/SNI still leaves your machine unencrypted and
  identical either way. Use the **SSH Tunnel** mode instead — the leg
  between your machine and your VPS is fully encrypted, so the local
  network only sees "an SSH connection to some IP," not which sites you're
  visiting.
- **Enterprise/browser policy** (`chrome://policy` shows the browser is
  "managed by your organization," e.g. via a domain-joined machine's Group
  Policy): neither mode helps. Chrome enforces policies like
  `URLBlocklist` inside the browser itself, before any network connection
  is even attempted, regardless of what process or proxy is involved. If
  you see this, check `chrome://policy` to confirm, and consider a browser
  that isn't subject to the same machine-wide policy.

## Disclaimer

This is a personal, single-user tool for your own device and your own
network. It doesn't attack, scan, or interfere with anyone else's systems.
Circumventing filtering or policy on a device or network you don't own or
administer, or that's owned by an employer/school/organization, may
violate its acceptable-use policy — that's a decision for you to make, not
something this README endorses either way. Use it only where you're
authorized to.

## License

No license file is included. All rights reserved by the author unless a
license is added later.

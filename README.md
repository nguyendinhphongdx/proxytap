# cepp-proxy-gui

A small, self-contained local proxy with a Tkinter control panel. It exists
to solve one specific problem: **on some machines, a browser's outbound
network connections are blocked by process identity** (a filtering tool or
device policy that keys off `chrome.exe`/`msedge.exe` specifically), while a
different, unmonitored process making the exact same connection is not.

This tool runs that "different process" as a small, auditable, single-file
Python script instead of an opaque pre-built binary, and adds a GUI so you
can see and control exactly what it's doing.

## What it does

1. **Local CONNECT proxy** (`ProxyCore`) — a tiny `asyncio` HTTP CONNECT
   tunnel on `127.0.0.1:<port>`. It accepts `CONNECT host:port` from the
   browser, opens a raw TCP connection to the real destination, and relays
   bytes both ways. It does not decrypt, inspect, or modify TLS traffic —
   it's a dumb pipe.
2. **Browser launcher** — detects an installed Chrome/Edge/Brave on
   Windows, macOS, or Linux, and launches it with `--proxy-server` pointing
   at the local proxy, using a separate `--user-data-dir` so it doesn't
   touch your main browser profile.
3. **Optional domain whitelist** — restrict the proxy to a list of allowed
   domains (with subdomain matching) instead of tunneling to anything the
   browser asks for.
4. **SSH SOCKS5 tunnel** (`SSHSocksTunnel`) — an alternative transport for
   a harder problem (see [Limitations](#limitations) below): connects to a
   VPS you control over SSH (via `paramiko`) and runs a local SOCKS5 server
   that forwards each connection through the encrypted SSH channel. Point
   the browser at this instead of the local proxy when the block is at the
   network layer rather than the process layer.

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
python cepp_gui.py
```

1. Set a port (default `8899`) and click **Start**.
2. Pick a browser and click **Mở trình duyệt** (Open browser) — it launches
   with the proxy configured and a few sites pre-opened.
3. Optionally enable the domain whitelist to restrict what the proxy will
   tunnel to.

### SSH Tunnel mode

If the local proxy doesn't help (see below), fill in your VPS's host,
port, username, and password or private key, then click **Connect**. Once
connected, switch the "Mở trình duyệt qua" radio button to **VPS qua SSH
(SOCKS5)** before opening the browser.

## Building a standalone executable

```bash
pip install pyinstaller
pyinstaller --onefile --noconsole --name cepp_proxy_gui cepp_gui.py
```

This produces a single executable in `dist/` — no Python installation
required to run it. Pre-built Windows binaries are attached to
[Releases](../../releases) for convenience.

## How it works

```
Browser  --[TCP to 127.0.0.1]-->  cepp_gui.py  --[TCP to the real destination]-->  Internet
```

The browser only ever opens a connection to `127.0.0.1`. The connection
that actually reaches the internet is opened by this script's own process,
not the browser's. If a filter on your machine blocks outbound connections
*by process identity* (rather than by inspecting the traffic itself), it
sees the browser only talking to localhost and this script talking to the
outside world — and if it has no rule for this script, the connection goes
through.

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

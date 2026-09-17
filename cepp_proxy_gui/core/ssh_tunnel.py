"""SOCKS5 proxy local, forward moi ket noi qua kenh SSH (paramiko) toi VPS.

Khac voi ConnectProxy: doan tu may minh toi VPS duoc SSH ma hoa toan
bo, nen ISP/router noi dia khong doc duoc domain (SNI) hay can thiep
DNS - dung cho truong hop chan o tang mang thay vi chan theo tien trinh.
"""

import socket
import threading
import queue

from .base import ProxyProvider

try:
    import paramiko
    HAVE_PARAMIKO = True
except ImportError:
    HAVE_PARAMIKO = False


class SSHSocksTunnel(ProxyProvider):
    def __init__(self, event_queue: "queue.Queue"):
        super().__init__(event_queue)
        self.client = None
        self.transport = None
        self.server_sock = None
        self.running = False
        self.accept_thread = None
        self._active = 0

    def start(self, ssh_host, ssh_port, username, password, key_path,
              key_passphrase, local_host, local_port):
        threading.Thread(
            target=self._run,
            args=(ssh_host, ssh_port, username, password, key_path,
                  key_passphrase, local_host, local_port),
            daemon=True,
        ).start()

    # Giu ten cu de tuong thich cac cho da goi connect_and_serve().
    connect_and_serve = start

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

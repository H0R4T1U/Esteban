"""Single-instance IPC over a Unix socket.

On Wayland a normal client cannot grab a global hotkey, so the running instance listens on
a Unix socket and the compositor keybinding is configured to run `esteban toggle`,
which sends one command here. This is the Linux stand-in for Alfred's Carbon hotkey
handler (AlfredHotkeyCombo::registerCombo 0x6c68): the hotkey arrives from outside the
process and the instance decides whether to show or hide the results box.

Protocol: one JSON object per connection, one JSON object back.
Commands: ping, show, hide, toggle, query, quit.
"""
from __future__ import annotations

import json
import os
import socket
from pathlib import Path

from .config import DATA_DIR


def socket_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    path = Path(runtime) if runtime and Path(runtime).exists() else DATA_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path / "esteban.sock"


def _responds(path: Path, timeout: float = 0.5) -> bool:
    """A socket file that accepts a connection belongs to a live instance; a stale file cannot."""
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(str(path))
        try:
            sock.sendall(b'{"command":"ping","payload":{}}\n')
            sock.recv(4096)
        except OSError:
            pass
        sock.close()
        return True
    except OSError:
        return False


def send(command: str, payload: dict | None = None, timeout: float = 1.5) -> dict | None:
    """Send one command to the running instance; None when no instance is listening."""
    path = socket_path()
    if not path.exists():
        return None
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(str(path))
        sock.sendall(json.dumps({"command": command, "payload": payload or {}}).encode() + b"\n")
        raw = sock.recv(4096)
        sock.close()
    except OSError:
        return None
    if not raw:
        return {}
    try:
        return json.loads(raw.decode())
    except ValueError:
        return {"reply": raw.decode().strip()}


class Server:
    """Non-blocking accept loop so the same handler can run inside a GUI main loop."""

    def __init__(self, handler, path: Path | None = None):
        self.handler = handler
        self.path = path or socket_path()
        self.sock = None

    def start(self) -> None:
        if self.path.exists():
            if _responds(self.path):
                raise RuntimeError(f"another instance is already listening on {self.path}")
            self.path.unlink()               # stale file from an instance that exited
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(str(self.path))
        self.sock.listen(8)
        self.sock.setblocking(False)

    def poll(self) -> bool:
        """Accept at most one pending connection (call from a main loop).

        Returns True so it can be handed straight to `GLib.timeout_add`: a callback that returns
        nothing is dropped by GLib after the first call, and the instance then stops answering
        `toggle` while its socket file is still there.
        """
        if not self.sock:
            return True
        try:
            conn, _ = self.sock.accept()
        except (BlockingIOError, OSError):
            return True
        try:
            raw = conn.recv(4096)
            request = json.loads(raw.decode()) if raw else {}
            reply = self.handler(request.get("command", "ping"), request.get("payload") or {})
            conn.sendall(json.dumps(reply if reply is not None else {"ok": True}).encode())
        except (OSError, ValueError) as exc:
            try:
                conn.sendall(json.dumps({"error": str(exc)}).encode())
            except OSError:
                pass
        finally:
            try:
                conn.close()
            except OSError:
                pass
        return True

    def serve(self) -> None:
        self.start()
        try:
            while True:
                conn, _ = self.sock.accept()
                try:
                    raw = conn.recv(4096)
                    request = json.loads(raw.decode()) if raw else {}
                    reply = self.handler(request.get("command", "ping"), request.get("payload") or {})
                    conn.sendall(json.dumps(reply if reply is not None else {"ok": True}).encode())
                except (OSError, ValueError) as exc:
                    try:
                        conn.sendall(json.dumps({"error": str(exc)}).encode())
                    except OSError:
                        pass
                finally:
                    conn.close()
        except KeyboardInterrupt:
            pass
        finally:
            self.close()

    def close(self) -> None:
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            try:
                self.path.unlink()
            except OSError:
                pass
            self.sock = None

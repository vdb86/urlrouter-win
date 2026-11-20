"""
ipc_server.py - Qt-based named-pipe server for the first (tray) instance.

This module is imported ONLY by the already-running instance (via app.py).
It is never imported during the short-lived URL-forwarding path, so the
second instance never pays the cost of loading Qt DLLs.

See ipc.py for the protocol: URL + b"\\n" + source JSON + b"\\n" in, one ACK
byte out. A v2 message (URL line only) is accepted too.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import time
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from ipc import (
    ACK, BUFSIZE, MESSAGE_END, PIPE_NAME, PIPE_TIMEOUT_MS,
    PIPE_ACCESS_DUPLEX, PIPE_TYPE_BYTE, PIPE_READMODE_BYTE, PIPE_WAIT,
    PIPE_UNLIMITED_INSTANCES, ERROR_PIPE_CONNECTED, ERROR_NO_DATA,
    _k32, last_error, send_to_existing, valid_handle,
)

MAX_MESSAGE   = 1_048_576   # 1 MB: far beyond any real URL
V2_WAIT_S     = 0.3         # how long to wait for a source line that may never come


def parse_source(raw: bytes) -> Optional[dict]:
    """The source JSON line -> {"exe", "path", "via"} or None."""
    try:
        obj = json.loads(raw.decode("utf-8", errors="replace") or "{}")
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    exe = str(obj.get("exe") or "").strip().lower()
    if not exe:
        return None
    return {"exe": exe,
            "path": str(obj.get("path") or ""),
            "via": str(obj.get("via") or "")}


class IPCServer(QThread):
    """Listens on the named pipe; emits url_received(url, source) for each
    inbound URL. source is a dict (see source_app.py) or None."""

    url_received = pyqtSignal(str, object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._running = True

    def run(self) -> None:
        while self._running:
            pipe = None
            try:
                pipe = _k32.CreateNamedPipeW(
                    PIPE_NAME,
                    PIPE_ACCESS_DUPLEX,
                    PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
                    PIPE_UNLIMITED_INSTANCES,
                    BUFSIZE, BUFSIZE, PIPE_TIMEOUT_MS, None,
                )
                if not valid_handle(pipe):
                    pipe = None
                    time.sleep(0.1)
                    continue

                connected = _k32.ConnectNamedPipe(pipe, None)
                err       = last_error()
                # ERROR_PIPE_CONNECTED: the client connected before we called
                # ConnectNamedPipe. ERROR_NO_DATA: it also closed already; try
                # to read whatever it left (the client will fall back anyway
                # because it got no acknowledgement).
                if not connected and err not in (0, ERROR_PIPE_CONNECTED, ERROR_NO_DATA):
                    continue

                msg = self._read_message(pipe)
                if msg is not None:
                    # Acknowledge first so the client can exit immediately.
                    written = wt.DWORD(0)
                    _k32.WriteFile(pipe, ACK, 1, ctypes.byref(written), None)
                    _k32.FlushFileBuffers(pipe)
                    raw_url, raw_src = msg
                    url = raw_url.decode("utf-8", errors="replace").strip()
                    if url and self._running:
                        self.url_received.emit(url, parse_source(raw_src))

            except Exception as exc:
                print(f"[IPC] server error: {exc}")
                if self._running:
                    time.sleep(0.1)
            finally:
                if pipe is not None:
                    _k32.DisconnectNamedPipe(pipe)
                    _k32.CloseHandle(pipe)

    @staticmethod
    def _read_message(pipe):
        """Read the URL line and the source line. Returns (url, source) bytes,
        source b"" for a v2 client, or None if the client went away before
        finishing the URL line."""
        data = b""
        buf  = ctypes.create_string_buffer(BUFSIZE)
        read = wt.DWORD(0)
        deadline = None
        while len(data) < MAX_MESSAGE:
            if data.count(MESSAGE_END) >= 2:
                url, src, _ = data.split(MESSAGE_END, 2)
                return url, src
            if MESSAGE_END in data:
                # URL line complete. A v2 client sends nothing more and waits
                # for the ACK, so never block in ReadFile here: peek instead.
                if deadline is None:
                    deadline = time.monotonic() + V2_WAIT_S
                avail = wt.DWORD(0)
                if not _k32.PeekNamedPipe(pipe, None, 0, None, ctypes.byref(avail), None):
                    break
                if avail.value == 0:
                    if time.monotonic() >= deadline:
                        break
                    time.sleep(0.005)
                    continue
            read.value = 0
            ok = _k32.ReadFile(pipe, buf, BUFSIZE, ctypes.byref(read), None)
            if read.value:
                data += buf.raw[: read.value]
            if not ok or read.value == 0:
                break
        if MESSAGE_END in data:
            url, _, rest = data.partition(MESSAGE_END)
            src = rest.split(MESSAGE_END, 1)[0] if MESSAGE_END in rest else b""
            return url, src
        return None

    def stop(self) -> None:
        self._running = False
        try:
            send_to_existing("", retry_ms=300)   # unblock ConnectNamedPipe
        except Exception:
            pass

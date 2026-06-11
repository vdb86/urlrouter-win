"""
ipc_server.py — Qt-based named-pipe server for the first (tray) instance.

This module is imported ONLY by the already-running instance (via app.py).
It is never imported during the short-lived URL-forwarding path, so the
second instance never pays the cost of loading Qt DLLs.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import time

from PyQt6.QtCore import QThread, pyqtSignal

from ipc import (
    PIPE_NAME, BUFSIZE, PIPE_TIMEOUT_MS,
    PIPE_ACCESS_INBOUND, PIPE_TYPE_BYTE, PIPE_READMODE_BYTE, PIPE_WAIT,
    PIPE_UNLIMITED_INSTANCES, ERROR_PIPE_CONNECTED,
    INVALID_HANDLE_VALUE, send_to_existing, _k32,
)


class IPCServer(QThread):
    """Listens on the named pipe; emits url_received for each inbound URL."""

    url_received = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._running = True

    def run(self) -> None:
        while self._running:
            try:
                pipe = _k32.CreateNamedPipeW(
                    PIPE_NAME,
                    PIPE_ACCESS_INBOUND,
                    PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
                    PIPE_UNLIMITED_INSTANCES,
                    BUFSIZE, BUFSIZE, PIPE_TIMEOUT_MS, None,
                )
                if pipe == INVALID_HANDLE_VALUE:
                    time.sleep(0.1)
                    continue

                connected = _k32.ConnectNamedPipe(pipe, None)
                err       = _k32.GetLastError()
                if connected == 0 and err not in (0, ERROR_PIPE_CONNECTED):
                    _k32.CloseHandle(pipe)
                    continue

                buf  = ctypes.create_string_buffer(BUFSIZE)
                read = ctypes.wintypes.DWORD(0)
                ok   = _k32.ReadFile(pipe, buf, BUFSIZE, ctypes.byref(read), None)
                _k32.CloseHandle(pipe)

                if ok and read.value > 0:
                    url = buf.raw[: read.value].decode("utf-8", errors="replace").strip()
                    if url:
                        self.url_received.emit(url)

            except Exception as exc:
                print(f"[IPC] server error: {exc}")
                if self._running:
                    time.sleep(0.1)

    def stop(self) -> None:
        self._running = False
        try:
            send_to_existing("")   # unblock ConnectNamedPipe
        except Exception:
            pass

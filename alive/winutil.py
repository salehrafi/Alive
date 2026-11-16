"""Small Win32 helpers (ctypes only): single instance, taskbar identity, messages."""
from __future__ import annotations

import ctypes
from ctypes import wintypes

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_u32 = ctypes.WinDLL("user32", use_last_error=True)

_k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
_k32.CreateMutexW.restype = wintypes.HANDLE
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_u32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
_u32.RegisterWindowMessageW.restype = wintypes.UINT
_u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

ERROR_ALREADY_EXISTS = 183
HWND_BROADCAST = 0xFFFF
WM_POWERBROADCAST = 0x0218
PBT_APMSUSPEND = 0x0004
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMRESUMEAUTOMATIC = 0x0012

SHOW_MESSAGE = _u32.RegisterWindowMessageW("ALIVE.KeepAlive.ShowWindow")


class SingleInstance:
    """Named mutex held for the process lifetime."""

    def __init__(self, name: str) -> None:
        self._handle = _k32.CreateMutexW(None, False, name)
        self.already_running = ctypes.get_last_error() == ERROR_ALREADY_EXISTS

    def release(self) -> None:
        if self._handle:
            _k32.CloseHandle(self._handle)
            self._handle = None


def signal_existing_instance() -> None:
    """Ask the running ALIVE to show its window."""
    _u32.PostMessageW(HWND_BROADCAST, SHOW_MESSAGE, 0, 0)


def allow_set_foreground() -> None:
    try:
        _u32.AllowSetForegroundWindow(wintypes.DWORD(-1 & 0xFFFFFFFF))  # ASFW_ANY
    except Exception:
        pass


def set_app_user_model_id(app_id: str) -> None:
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass


def trim_working_set() -> None:
    """Return start-up pages to the OS (cheap, one-off after launch)."""
    try:
        h = _k32.GetCurrentProcess()
        ctypes.WinDLL("psapi").EmptyWorkingSet(h)
    except Exception:
        pass

"""Bluetooth control: speaker connect/disconnect and radio (adapter) on/off state.

Kept apart from bluetooth.py (read-only status) because these calls change things.
"""
from __future__ import annotations

import base64
import ctypes
import os
import subprocess
from ctypes import wintypes

from .bluetooth import CM_GETIDLIST_FILTER_PRESENT, CR_SUCCESS, GUID, _cfg

# -- Speaker connect / disconnect (kernel-streaming property on the BT audio driver) --
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                             wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
_k32.CreateFileW.restype = wintypes.HANDLE
_k32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                 ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                 ctypes.c_void_p]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_INVALID_HANDLE = wintypes.HANDLE(-1).value

KSCATEGORY_AUDIO = GUID.from_str("6994ad04-93ef-11d0-a3cc-00a0c9223196")
KSPROPSETID_BtAudio = GUID.from_str("7fa06c40-b8f6-4c7e-8556-e8c33a12e54d")
KSPROPERTY_ONESHOT_RECONNECT = 0
KSPROPERTY_ONESHOT_DISCONNECT = 1
KSPROPERTY_TYPE_GET = 0x1
IOCTL_KS_PROPERTY = 0x002F0003  # CTL_CODE(FILE_DEVICE_KS, 0, METHOD_NEITHER, FILE_ANY_ACCESS)

_cfg.CM_Get_Device_Interface_List_SizeW.argtypes = [
    ctypes.POINTER(wintypes.ULONG), ctypes.POINTER(GUID), wintypes.LPCWSTR, wintypes.ULONG]
_cfg.CM_Get_Device_Interface_ListW.argtypes = [
    ctypes.POINTER(GUID), wintypes.LPCWSTR, ctypes.c_void_p, wintypes.ULONG, wintypes.ULONG]


class KSPROPERTY(ctypes.Structure):
    _fields_ = [("Set", GUID), ("Id", wintypes.ULONG), ("Flags", wintypes.ULONG)]


def audio_interfaces(instance_id: str) -> list[str]:
    """Kernel-streaming audio interfaces exposed by a Bluetooth audio device node."""
    n = wintypes.ULONG()
    if _cfg.CM_Get_Device_Interface_List_SizeW(ctypes.byref(n), ctypes.byref(KSCATEGORY_AUDIO),
                                               instance_id, 0) != CR_SUCCESS or n.value <= 1:
        return []
    buf = ctypes.create_unicode_buffer(n.value)
    if _cfg.CM_Get_Device_Interface_ListW(ctypes.byref(KSCATEGORY_AUDIO), instance_id, buf,
                                          n.value, 0) != CR_SUCCESS:
        return []
    return [x for x in buf[: n.value].split("\0") if x]


def ks_oneshot(path: str, connect: bool) -> bool:
    """Send the same Connect/Disconnect request as the Sound control panel.
    Returns once the driver accepts it; the link changes asynchronously."""
    h = _k32.CreateFileW(path, 0xC0000000, 0x3, None, 3, 0, None)  # R/W, share R/W, OPEN_EXISTING
    if not h or h == _INVALID_HANDLE:
        return False
    try:
        prop = KSPROPERTY(KSPROPSETID_BtAudio,
                          KSPROPERTY_ONESHOT_RECONNECT if connect else KSPROPERTY_ONESHOT_DISCONNECT,
                          KSPROPERTY_TYPE_GET)
        ret = wintypes.DWORD()
        return bool(_k32.DeviceIoControl(h, IOCTL_KS_PROPERTY, ctypes.byref(prop), ctypes.sizeof(prop),
                                         None, 0, ctypes.byref(ret), None))
    finally:
        _k32.CloseHandle(h)


# -- Radio state -----------------------------------------------------------------
class _RadioParams(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD)]


try:
    _bt = ctypes.WinDLL("BluetoothApis")
    _bt.BluetoothFindFirstRadio.argtypes = [ctypes.POINTER(_RadioParams), ctypes.POINTER(wintypes.HANDLE)]
    _bt.BluetoothFindFirstRadio.restype = wintypes.HANDLE
    _bt.BluetoothFindRadioClose.argtypes = [wintypes.HANDLE]
except OSError:  # no Bluetooth stack installed
    _bt = None

_BLUETOOTH_CLASS = "{e0cbf06c-cd8b-4647-bb8a-263b43f0f974}"
CM_GETIDLIST_FILTER_CLASS = 0x200
_ADAPTER_BUSES = ("USB\\", "PCI\\", "ACPI\\", "SDIO\\", "UART\\", "BTHUSB\\")


def radio_state() -> str:
    """'on', 'off' (adapter present, radio switched off) or 'none' (no adapter).

    An enabled radio exposes the Bluetooth port interface that
    BluetoothFindFirstRadio enumerates. Switching the radio off in Settings or
    Quick Settings removes that interface, while the adapter device stays present."""
    if _bt is not None:
        params, radio = _RadioParams(ctypes.sizeof(_RadioParams)), wintypes.HANDLE()
        find = _bt.BluetoothFindFirstRadio(ctypes.byref(params), ctypes.byref(radio))
        if find:
            _bt.BluetoothFindRadioClose(find)
            _k32.CloseHandle(radio)
            return "on"
    flags = CM_GETIDLIST_FILTER_CLASS | CM_GETIDLIST_FILTER_PRESENT
    size = wintypes.ULONG()
    if _cfg.CM_Get_Device_ID_List_SizeW(ctypes.byref(size), _BLUETOOTH_CLASS, flags) == CR_SUCCESS and size.value:
        buf = ctypes.create_unicode_buffer(size.value)
        if _cfg.CM_Get_Device_ID_ListW(_BLUETOOTH_CLASS, buf, size.value, flags) == CR_SUCCESS:
            if any(i.upper().startswith(_ADAPTER_BUSES) for i in buf[: size.value].split("\0")):
                return "off"
    return "none"


# -- Radio on/off ------------------------------------------------------------------
# Win32 has no API to switch the radio. The supported user-level API is WinRT
# Windows.Devices.Radios, called here through Windows PowerShell 5.1. It runs on
# demand only (button press), never polled, and needs no admin rights.
_RADIO_PS = r"""
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$m=([System.WindowsRuntimeSystemExtensions].GetMethods()|?{$_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'})[0]
function Await($op,[Type]$t){$x=$m.MakeGenericMethod($t).Invoke($null,@($op));$x.Wait(-1)|Out-Null;$x.Result}
[Windows.Devices.Radios.Radio,Windows.System.Devices,ContentType=WindowsRuntime]|Out-Null
Await ([Windows.Devices.Radios.Radio]::RequestAccessAsync()) ([Windows.Devices.Radios.RadioAccessStatus])|Out-Null
$r=(Await ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) ([System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]]))|?{$_.Kind -eq 'Bluetooth'}|Select-Object -First 1
if(-not $r){'NoRadio';exit}
$s=Await ($r.SetStateAsync('__STATE__')) ([Windows.Devices.Radios.RadioAccessStatus])
"$s"
"""


def set_radio(on: bool) -> tuple[bool, str]:
    """Blocking (about 1-3 s): call from a worker thread. Returns (ok, detail)."""
    script = _RADIO_PS.replace("__STATE__", "On" if on else "Off")
    enc = base64.b64encode(script.encode("utf-16-le")).decode()
    exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                       r"System32\WindowsPowerShell\v1.0\powershell.exe")
    try:
        r = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-EncodedCommand", enc],
                           capture_output=True, text=True, timeout=30,
                           creationflags=0x08000000)  # CREATE_NO_WINDOW
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    lines = (r.stdout or "").strip().splitlines()
    result = lines[-1].strip() if lines else ""
    if result == "Allowed":
        return True, ""
    if result == "NoRadio":
        return False, "No Bluetooth radio found"
    if result:
        return False, f"Windows refused: {result}"
    return False, (r.stderr or "PowerShell failed").strip().splitlines()[0][:120]

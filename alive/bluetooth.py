"""Bluetooth connection + battery lookup via the Windows Configuration Manager.

Windows stores the battery level it shows in Settings > Bluetooth & devices in the
device property DEVPKEY_Bluetooth_Battery ({104EA319-...} 2). The Bluetooth stack
fills it from the Hands-Free profile (HFP AT+IPHONEACCEV / +XEVENT) for classic
devices and from the GATT Battery Service for BLE devices. Reading it here gives
exactly the value Windows trusts — nothing is estimated or invented.

All calls are plain cfgmgr32 property reads (microseconds, no radio traffic), so
reading them never touches the audio path.
"""
from __future__ import annotations

import ctypes
import os
import uuid
from ctypes import wintypes
from dataclasses import dataclass

_cfg = ctypes.WinDLL("cfgmgr32")

CR_SUCCESS = 0
CR_BUFFER_SMALL = 0x1A
CM_LOCATE_DEVNODE_PHANTOM = 0x1
CM_GETIDLIST_FILTER_ENUMERATOR = 0x1
CM_GETIDLIST_FILTER_PRESENT = 0x100

DEVPROP_TYPE_BYTE = 0x03
DEVPROP_TYPE_GUID = 0x0D
DEVPROP_TYPE_BOOLEAN = 0x11
DEVPROP_TYPE_STRING = 0x12


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def from_str(cls, s: str) -> "GUID":
        g = cls()
        ctypes.memmove(ctypes.byref(g), uuid.UUID(s).bytes_le, 16)
        return g


class DEVPROPKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", wintypes.ULONG)]


def _key(fmtid: str, pid: int) -> DEVPROPKEY:
    return DEVPROPKEY(GUID.from_str(fmtid), pid)


KEY_CONTAINER_ID = _key("8c7ed206-3f8a-4827-b3ab-ae9e1faefc6c", 2)
KEY_BATTERY = _key("104ea319-6ee2-4701-bd47-8ddbf425bbe5", 2)
KEY_BT_CONNECTED = _key("83da6326-97a6-4088-9453-a1923f573b29", 15)

_cfg.CM_Locate_DevNodeW.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.LPCWSTR, wintypes.ULONG]
_cfg.CM_Get_DevNode_PropertyW.argtypes = [
    wintypes.DWORD, ctypes.POINTER(DEVPROPKEY), ctypes.POINTER(wintypes.ULONG),
    ctypes.c_void_p, ctypes.POINTER(wintypes.ULONG), wintypes.ULONG]
_cfg.CM_Get_Device_ID_List_SizeW.argtypes = [ctypes.POINTER(wintypes.ULONG), wintypes.LPCWSTR, wintypes.ULONG]
_cfg.CM_Get_Device_ID_ListW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, wintypes.ULONG, wintypes.ULONG]

_BT_ENUMERATORS = ("BTHENUM", "BTHLE", "BTHLEDEVICE", "BTHHFENUM")


def _locate(instance_id: str) -> int | None:
    dev = wintypes.DWORD()
    if _cfg.CM_Locate_DevNodeW(ctypes.byref(dev), instance_id, CM_LOCATE_DEVNODE_PHANTOM) != CR_SUCCESS:
        return None
    return dev.value


def _get_prop(devinst: int, key: DEVPROPKEY) -> tuple[int, bytes] | None:
    ptype = wintypes.ULONG()
    size = wintypes.ULONG(64)
    buf = ctypes.create_string_buffer(64)
    cr = _cfg.CM_Get_DevNode_PropertyW(devinst, ctypes.byref(key), ctypes.byref(ptype), buf, ctypes.byref(size), 0)
    if cr == CR_BUFFER_SMALL:
        buf = ctypes.create_string_buffer(size.value)
        cr = _cfg.CM_Get_DevNode_PropertyW(devinst, ctypes.byref(key), ctypes.byref(ptype), buf, ctypes.byref(size), 0)
    if cr != CR_SUCCESS:
        return None
    return ptype.value, buf.raw[: size.value]


def _container_of(devinst: int) -> str | None:
    p = _get_prop(devinst, KEY_CONTAINER_ID)
    if not p or p[0] != DEVPROP_TYPE_GUID or len(p[1]) < 16:
        return None
    return str(uuid.UUID(bytes_le=p[1][:16]))


def _list_ids(enumerator: str) -> list[str]:
    flags = CM_GETIDLIST_FILTER_ENUMERATOR
    size = wintypes.ULONG()
    if _cfg.CM_Get_Device_ID_List_SizeW(ctypes.byref(size), enumerator, flags) != CR_SUCCESS or not size.value:
        return []
    buf = ctypes.create_unicode_buffer(size.value)
    if _cfg.CM_Get_Device_ID_ListW(enumerator, buf, size.value, flags) != CR_SUCCESS:
        return []
    return [s for s in buf[: size.value].split("\0") if s]


@dataclass
class BluetoothStatus:
    connected: bool | None  # None = Windows does not report connection state
    battery: int | None     # None = not reported / not reliable


class BluetoothDeviceProbe:
    """Resolves an audio endpoint to its Bluetooth device nodes and reads them.

    resolve() walks the Bluetooth device tree once (a few ms) and caches the
    handful of device nodes that belong to the speaker. read() then only does
    two or three property reads.
    """

    def __init__(self) -> None:
        self._device_node: int | None = None     # BTHENUM\DEV_xxx / BTHLE\DEV_xxx
        self._battery_nodes: list[int] = []
        self._ks_paths: list[str] = []           # audio driver interfaces (A2DP, HFP)

    @property
    def can_control(self) -> bool:
        return bool(self._ks_paths)

    def resolve(self, container: str | None) -> None:
        """container: the audio endpoint's PnP container ID. It comes from the
        endpoint's property store, which (unlike the endpoint's device node)
        still exists while a Bluetooth device is disconnected."""
        self._device_node = None
        self._battery_nodes = []
        self._ks_paths = []
        container = (container or "").lower()
        if not container:
            return
        for enum in _BT_ENUMERATORS:
            for iid in _list_ids(enum):
                node = _locate(iid)
                if node is None or _container_of(node) != container:
                    continue
                upper = iid.upper()
                if upper.startswith(("BTHENUM\\DEV_", "BTHLE\\DEV_")):
                    self._device_node = node
                if _get_prop(node, KEY_BATTERY) is not None:
                    self._battery_nodes.append(node)
                if enum in ("BTHENUM", "BTHHFENUM"):
                    from .bt_control import audio_interfaces
                    self._ks_paths += audio_interfaces(iid)

    def set_connected(self, connect: bool) -> bool:
        """Connect or disconnect the speaker's Bluetooth audio profiles (A2DP and
        Hands-Free). Blocking for a moment: call from a worker thread."""
        from .bt_control import ks_oneshot
        ok = False
        for path in list(self._ks_paths):
            ok |= ks_oneshot(path, connect)
        return ok

    def read(self) -> BluetoothStatus:
        connected: bool | None = None
        if self._device_node is not None:
            p = _get_prop(self._device_node, KEY_BT_CONNECTED)
            if p and p[0] == DEVPROP_TYPE_BOOLEAN and p[1]:
                connected = p[1][0] != 0
        battery: int | None = None
        # A battery value cached from a previous connection is stale: only report
        # it while the device is connected.
        if connected is not False:
            for node in self._battery_nodes:
                p = _get_prop(node, KEY_BATTERY)
                if p and p[0] == DEVPROP_TYPE_BYTE and p[1] and 0 <= p[1][0] <= 100:
                    battery = p[1][0]
                    break
        return BluetoothStatus(connected, battery)

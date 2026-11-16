"""Windows Core Audio (MMDevice API) access: endpoints, default output, sessions.

Only the raw COM interface definitions from pycaw are used (pycaw.api.*), which
keeps the dependency to comtypes and avoids pycaw.utils' psutil import.
"""
from __future__ import annotations

import ctypes
import os
import uuid
from dataclasses import dataclass

import comtypes
from comtypes import COMObject, GUID
from pycaw.api.audiopolicy import IAudioSessionControl2, IAudioSessionManager2
from pycaw.api.mmdeviceapi import IMMDeviceEnumerator, IMMNotificationClient
from pycaw.api.mmdeviceapi.depend.structures import PROPERTYKEY

CLSID_MMDeviceEnumerator = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")

E_RENDER = 0
E_CONSOLE = 0
E_MULTIMEDIA = 1

STATE_ACTIVE = 0x1
STATE_UNPLUGGED = 0x8

SESSION_ACTIVE = 1


def _pkey(fmtid: str, pid: int) -> PROPERTYKEY:
    k = PROPERTYKEY()
    k.fmtid = GUID(fmtid)
    k.pid = pid
    return k


PKEY_FRIENDLY_NAME = _pkey("{a45c254e-df1c-4efd-8020-67d146a850e0}", 14)
PKEY_ENUMERATOR_NAME = _pkey("{a45c254e-df1c-4efd-8020-67d146a850e0}", 24)
PKEY_CONTAINER_ID = _pkey("{8c7ed206-3f8a-4827-b3ab-ae9e1faefc6c}", 2)
VT_CLSID = 72


_CoTaskMemFree = ctypes.windll.ole32.CoTaskMemFree
_CoTaskMemFree.argtypes = [ctypes.c_void_p]


def _device_id(dev) -> str:
    """IMMDevice::GetId without the leak: comtypes' generated wrapper copies the
    CoTaskMemAlloc'd string but never frees it (~110 bytes per call)."""
    ptr = ctypes.c_wchar_p()
    dev._IMMDevice__com_GetId(ctypes.byref(ptr))
    try:
        return ptr.value or ""
    finally:
        _CoTaskMemFree(ctypes.cast(ptr, ctypes.c_void_p))


@dataclass(frozen=True)
class Endpoint:
    id: str
    name: str
    state: int
    bluetooth: bool
    container: str = ""  # PnP container ID: links the endpoint to its Bluetooth device

    @property
    def active(self) -> bool:
        return self.state == STATE_ACTIVE


class _NotificationClient(COMObject):
    """IMMNotificationClient. Called on a Windows audio-service thread: it must
    return immediately, so it only forwards a flag to the owner's callback."""

    _com_interfaces_ = (IMMNotificationClient,)

    def __init__(self, on_change) -> None:
        super().__init__()
        self._on_change = on_change

    def OnDeviceStateChanged(self, device_id, new_state):
        self._on_change(False)
        return 0

    def OnDeviceAdded(self, device_id):
        self._on_change(False)
        return 0

    def OnDeviceRemoved(self, device_id):
        self._on_change(False)
        return 0

    def OnDefaultDeviceChanged(self, flow, role, device_id):
        if flow == E_RENDER:
            self._on_change(True)
        return 0

    def OnPropertyValueChanged(self, device_id, key):
        return 0  # very chatty (volume etc.) and irrelevant


class AudioDevices:
    """Thin wrapper around IMMDeviceEnumerator. Use from the GUI (STA) thread."""

    def __init__(self) -> None:
        self._enum = comtypes.CoCreateInstance(
            CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, comtypes.CLSCTX_INPROC_SERVER)
        self._client: _NotificationClient | None = None

    # -- notifications --------------------------------------------------------
    def register(self, on_change) -> None:
        """on_change(default_changed: bool) — invoked from a foreign thread."""
        if self._client is None:
            self._client = _NotificationClient(on_change)
            self._enum.RegisterEndpointNotificationCallback(self._client)

    def unregister(self) -> None:
        if self._client is not None:
            try:
                self._enum.UnregisterEndpointNotificationCallback(self._client)
            except Exception:
                pass
            self._client = None

    # -- queries ----------------------------------------------------------------
    @staticmethod
    def _read_str(store, key) -> str | None:
        try:
            v = store.GetValue(key)
        except Exception:
            return None
        try:
            s = v.GetValue()
            return s if isinstance(s, str) else None
        finally:
            v.clear()

    @staticmethod
    def _read_guid(store, key) -> str:
        """VT_CLSID property. pycaw's PROPVARIANT declares the CLSID* member as an
        inline GUID, so read the pointer from the union's first bytes directly."""
        try:
            v = store.GetValue(key)
        except Exception:
            return ""
        try:
            if v.vt != VT_CLSID:
                return ""
            ptr = ctypes.c_void_p.from_address(ctypes.addressof(v.union)).value
            return str(uuid.UUID(bytes_le=ctypes.string_at(ptr, 16))) if ptr else ""
        finally:
            v.clear()

    def _endpoint(self, dev) -> Endpoint:
        store = dev.OpenPropertyStore(0)  # STGM_READ
        name = self._read_str(store, PKEY_FRIENDLY_NAME) or "Unknown device"
        enum = (self._read_str(store, PKEY_ENUMERATOR_NAME) or "").upper()
        bt = enum.startswith("BTH")
        container = self._read_guid(store, PKEY_CONTAINER_ID) if bt else ""
        return Endpoint(_device_id(dev), name, dev.GetState(), bt, container)

    def default_output(self) -> Endpoint | None:
        try:
            dev = self._enum.GetDefaultAudioEndpoint(E_RENDER, E_MULTIMEDIA)
        except Exception:  # E_NOTFOUND when no output device exists
            return None
        try:
            return self._endpoint(dev)
        except Exception:
            return None

    def bluetooth_outputs(self) -> list[Endpoint]:
        """Bluetooth render endpoints that are connected or paired-but-unplugged."""
        out: list[Endpoint] = []
        try:
            col = self._enum.EnumAudioEndpoints(E_RENDER, STATE_ACTIVE | STATE_UNPLUGGED)
            for i in range(col.GetCount()):
                try:
                    ep = self._endpoint(col.Item(i))
                except Exception:
                    continue
                if ep.bluetooth:
                    out.append(ep)
        except Exception:
            pass
        out.sort(key=lambda e: (not e.active, "hands-free" in e.name.lower(), e.name.lower()))
        return out

    def endpoint_state(self, endpoint_id: str) -> int | None:
        try:
            return self._enum.GetDevice(endpoint_id).GetState()
        except Exception:
            return None

    def own_active_session(self) -> Endpoint | None:
        """The output endpoint on which THIS process currently has an *active*
        audio stream, or None. This is the ground truth for "is it playing"."""
        pid = os.getpid()
        try:
            col = self._enum.EnumAudioEndpoints(E_RENDER, STATE_ACTIVE)
            count = col.GetCount()
        except Exception:
            return None
        for i in range(count):
            try:
                dev = col.Item(i)
                mgr = dev.Activate(IAudioSessionManager2._iid_, comtypes.CLSCTX_ALL, None)
                mgr = mgr.QueryInterface(IAudioSessionManager2)
                sessions = mgr.GetSessionEnumerator()
                for j in range(sessions.GetCount()):
                    ctl = sessions.GetSession(j).QueryInterface(IAudioSessionControl2)
                    if ctl.GetProcessId() == pid and ctl.GetState() == SESSION_ACTIVE:
                        return self._endpoint(dev)
            except Exception:
                continue
        return None


# -- Endpoint (device) volume ---------------------------------------------------------
from pycaw.api.endpointvolume import IAudioEndpointVolume, IAudioEndpointVolumeCallback  # noqa: E402


class _VolumeCallback(COMObject):
    """Called on an audio-service thread whenever the device volume/mute changes
    (from ALIVE, the keyboard, Windows' flyout or the speaker's own buttons)."""

    _com_interfaces_ = (IAudioEndpointVolumeCallback,)

    def __init__(self, on_change) -> None:
        super().__init__()
        self._on_change = on_change

    def OnNotify(self, notify):
        self._on_change()
        return 0


class EndpointVolume:
    """Master volume + mute of one output device. Use from the GUI thread."""

    def __init__(self, devices: AudioDevices, endpoint_id: str, on_change) -> None:
        dev = devices._enum.GetDevice(endpoint_id)
        self.endpoint_id = endpoint_id
        self._vol = dev.Activate(IAudioEndpointVolume._iid_, comtypes.CLSCTX_ALL, None) \
            .QueryInterface(IAudioEndpointVolume)
        self._cb = _VolumeCallback(on_change)
        self._vol.RegisterControlChangeNotify(self._cb)

    def get(self) -> tuple[int, bool]:
        return round(self._vol.GetMasterVolumeLevelScalar() * 100), bool(self._vol.GetMute())

    def set_level(self, percent: int) -> None:
        self._vol.SetMasterVolumeLevelScalar(max(0, min(100, percent)) / 100.0, None)

    def set_mute(self, mute: bool) -> None:
        self._vol.SetMute(bool(mute), None)

    def close(self) -> None:
        if self._cb is not None:
            try:
                self._vol.UnregisterControlChangeNotify(self._cb)
            except Exception:
                pass
            self._cb = None

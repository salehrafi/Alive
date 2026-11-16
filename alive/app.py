"""Application lifecycle: wires engine, device monitoring, window and tray."""
from __future__ import annotations

import ctypes
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import APP_ID, APP_NAME, APP_VERSION, winutil
from . import bt_control
from .audio_devices import AudioDevices, Endpoint, EndpointVolume
from .audio_engine import AudioEngine, State
from .bluetooth import BluetoothDeviceProbe, BluetoothStatus
from .theme import font, palette, stylesheet
from .ui import MainWindow, View

BT_POLL_MS = 30_000        # battery/connection re-read (cheap property reads)
DEVICE_DEBOUNCE_MS = 800   # coalesce bursts of endpoint notifications
LOW_BATTERY = 20
MID_BATTERY = 50


def resource_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "assets" / name


def format_elapsed(seconds: float) -> str:
    s = int(seconds)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    core = f"{h:02d}:{m:02d}:{s:02d}"
    return f"{d}d {core}" if d else core


class _NativeFilter(QAbstractNativeEventFilter):
    """Catches power resume and the 'show yourself' message from a 2nd instance."""

    def __init__(self, on_resume, on_show) -> None:
        super().__init__()
        self._on_resume = on_resume
        self._on_show = on_show

    def nativeEventFilter(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == winutil.SHOW_MESSAGE:
                self._on_show()
                return True, 0
            if msg.message == winutil.WM_POWERBROADCAST and msg.wParam in (
                    winutil.PBT_APMRESUMEAUTOMATIC, winutil.PBT_APMRESUMESUSPEND):
                self._on_resume()
        return False, 0


class Controller(QObject):
    _deviceEvent = Signal(bool)   # emitted from the audio-service thread
    _volumeEvent = Signal()       # emitted from the audio-service thread
    _taskDone = Signal(str, bool, str)  # (task, ok, detail) from a worker thread

    def __init__(self, app: QApplication, start_hidden: bool, autostart: bool) -> None:
        super().__init__()
        self.app = app
        self.settings = QSettings(APP_NAME, APP_NAME)
        self.theme = self.settings.value("theme", "light")
        self.icon = QIcon(str(resource_path("alive.ico")))
        app.setWindowIcon(self.icon)

        self.devices = AudioDevices()
        self.engine = AudioEngine(self.devices, self)
        self.probe = BluetoothDeviceProbe()
        self.default_out: Endpoint | None = None
        self.speakers: list[Endpoint] = []
        self.target: Endpoint | None = None
        self.bt = BluetoothStatus(None, None)
        self.radio = "none"
        self.volume: EndpointVolume | None = None
        self._busy: str = ""            # "connect" / "disconnect" / "radio" while a request runs
        self._task_msg: tuple[str, str] | None = None  # (text, color) result of the last request
        self._shut = False

        self.window = MainWindow(self.icon)
        self.window.startRequested.connect(self.start)
        self.window.stopRequested.connect(self.stop)
        self.window.themeToggleRequested.connect(self.toggle_theme)
        self.window.speakerSelected.connect(self.select_speaker)
        self.window.hideRequested.connect(self.hide_window)
        self.window.visibilityChanged.connect(self._sync_tick)
        self.window.connectToggleRequested.connect(self.toggle_connection)
        self.window.radioToggleRequested.connect(self.toggle_radio)
        self.window.volumeChanged.connect(self.set_volume)
        self.window.muteToggleRequested.connect(self.toggle_mute)

        self._build_tray()
        self.apply_theme()

        # Timers: all single-purpose, and the 1 s tick only runs while visible.
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._update_elapsed)
        self._bt_timer = QTimer(self)
        self._bt_timer.setInterval(BT_POLL_MS)
        self._bt_timer.timeout.connect(self.poll_bluetooth)
        self._bt_timer.start()
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEVICE_DEBOUNCE_MS)
        self._debounce.timeout.connect(self.refresh_devices)
        self._default_changed = False

        self.engine.stateChanged.connect(self.render)
        self._deviceEvent.connect(self._on_device_event, Qt.QueuedConnection)
        self._volumeEvent.connect(self._update_volume, Qt.QueuedConnection)
        self._taskDone.connect(self._on_task_done, Qt.QueuedConnection)
        self.devices.register(self._deviceEvent.emit)

        self._filter = _NativeFilter(self._on_resume, self.show_window)
        app.installNativeEventFilter(self._filter)
        app.aboutToQuit.connect(self.shutdown)

        self.refresh_devices()
        self.window.winId()  # ensure a native HWND exists even when starting hidden
        if not start_hidden:
            self.show_window()
        if autostart:
            self.start()

    # -- tray ---------------------------------------------------------------------
    def _build_tray(self) -> None:
        base = self.icon.pixmap(32, 32)
        self._tray_icons: dict[str, QIcon] = {}
        for key, color in (("idle", None), ("green", "#2BC867"), ("orange", "#FFA928"), ("red", "#F0473A")):
            pm = QPixmap(base)
            if color:
                p = QPainter(pm)
                p.fillRect(18, 18, 14, 14, QColor("#000000"))
                p.fillRect(20, 20, 12, 12, QColor(color))
                p.end()
            self._tray_icons[key] = QIcon(pm)

        self.tray = QSystemTrayIcon(self._tray_icons["idle"], self)
        menu = QMenu()
        self._act_open = QAction(f"Open {APP_NAME}", menu, triggered=self.show_window)
        self._act_start = QAction("Start keep-alive", menu, triggered=self.start)
        self._act_stop = QAction("Stop keep-alive", menu, triggered=self.stop)
        self._act_exit = QAction("Exit", menu, triggered=self.exit)
        menu.addAction(self._act_open)
        menu.addSeparator()
        menu.addAction(self._act_start)
        menu.addAction(self._act_stop)
        menu.addSeparator()
        menu.addAction(self._act_exit)
        menu.setWindowFlags(menu.windowFlags() | Qt.NoDropShadowWindowHint)
        self._menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray)
        self.tray.setToolTip(APP_NAME)
        self.tray.show()

    def _on_tray(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self.window.isVisible() and not self.window.isMinimized():
                self.hide_window()
            else:
                self.show_window()

    # -- actions ------------------------------------------------------------------
    def start(self) -> None:
        self.engine.start()

    def stop(self) -> None:
        self.engine.stop()

    def show_window(self) -> None:
        w = self.window
        w.showNormal()
        w.raise_()
        w.activateWindow()

    def hide_window(self) -> None:
        self.window.hide()
        if not self.settings.value("tray_hint_shown", False, type=bool):
            self.settings.setValue("tray_hint_shown", True)
            self.tray.showMessage(APP_NAME, "ALIVE keeps running in the notification area.",
                                  self._tray_icons["idle"], 4000)
        winutil.trim_working_set()

    def toggle_theme(self) -> None:
        self.theme = "dark" if self.theme == "light" else "light"
        self.settings.setValue("theme", self.theme)
        self.apply_theme()

    def apply_theme(self) -> None:
        p = palette(self.theme)
        self.app.setStyleSheet(stylesheet(p, str(resource_path(''))))
        self.window.apply_palette(p)

    def select_speaker(self, endpoint_id: str) -> None:
        self.settings.setValue("speaker_id", endpoint_id)
        self.refresh_devices()

    def exit(self) -> None:
        self.shutdown()
        self.app.quit()

    def shutdown(self) -> None:
        if self._shut:
            return
        self._shut = True
        for t in (self._tick, self._bt_timer, self._debounce):
            t.stop()
        self.engine.shutdown()          # stops PlaySound, releases the stream
        self._close_volume()
        self.devices.unregister()       # stop COM notifications before teardown
        self.app.removeNativeEventFilter(self._filter)
        self.tray.hide()

    # -- Bluetooth / volume control -------------------------------------------------
    def _run_task(self, name: str, fn) -> None:
        """Run one blocking control request on a short-lived worker thread."""
        if self._busy:
            return
        self._busy = name
        self._task_msg = None
        self.render()

        def work():
            try:
                ok, detail = fn()
            except Exception as e:  # never let a worker die silently
                ok, detail = False, str(e)
            self._taskDone.emit(name, ok, detail)

        threading.Thread(target=work, name=f"alive-{name}", daemon=True).start()

    def toggle_connection(self) -> None:
        if self.target is None or not self.probe.can_control:
            return
        connect = not self.bt.connected
        probe = self.probe
        self._run_task("connect" if connect else "disconnect",
                       lambda: (probe.set_connected(connect), ""))

    def toggle_radio(self) -> None:
        if self.radio == "none":
            return
        turn_on = self.radio == "off"
        if not turn_on:
            box = QMessageBox(QMessageBox.Question, APP_NAME,
                              "Turn off Bluetooth?\n\nEvery Bluetooth device will disconnect, "
                              "including keyboards and mice.",
                              QMessageBox.Yes | QMessageBox.Cancel, self.window)
            box.setDefaultButton(QMessageBox.Cancel)
            if box.exec() != QMessageBox.Yes:
                return
        self._run_task("radio", lambda: bt_control.set_radio(turn_on))

    def _on_task_done(self, name: str, ok: bool, detail: str) -> None:
        self._busy = ""
        if not ok:
            what = {"connect": "Could not connect the speaker",
                    "disconnect": "Could not disconnect the speaker",
                    "radio": "Could not switch Bluetooth"}[name]
            self._task_msg = (what + (": " + detail if detail else "."), "red")
            QTimer.singleShot(10_000, self._clear_task_msg)
        # The link/radio change completes asynchronously; device events refresh the
        # view, and these re-checks catch anything without an event.
        for delay in (1500, 5000):
            QTimer.singleShot(delay, self.refresh_devices)
        self.refresh_devices()

    def _clear_task_msg(self) -> None:
        if self._task_msg is not None and not self._busy:
            self._task_msg = None
            self.render()

    def _close_volume(self) -> None:
        if self.volume is not None:
            self.volume.close()
            self.volume = None

    def _sync_volume(self) -> None:
        """Attach volume control to the target speaker while it is connected."""
        want = self.target.id if self.target and self.target.active else None
        if self.volume is not None and self.volume.endpoint_id == want:
            return
        self._close_volume()
        if want:
            try:
                self.volume = EndpointVolume(self.devices, want, self._volumeEvent.emit)
            except Exception:
                self.volume = None
        self._update_volume()

    def _update_volume(self) -> None:
        level, muted = None, False
        if self.volume is not None:
            try:
                level, muted = self.volume.get()
            except Exception:
                self._close_volume()
        self.window.set_volume(level, muted)

    def set_volume(self, percent: int) -> None:
        if self.volume is not None:
            try:
                self.volume.set_level(percent)
            except Exception:
                pass

    def toggle_mute(self) -> None:
        if self.volume is not None:
            try:
                _, muted = self.volume.get()
                self.volume.set_mute(not muted)
            except Exception:
                pass

    # -- device monitoring ----------------------------------------------------------
    def _on_device_event(self, default_changed: bool) -> None:
        self._default_changed |= default_changed
        self._debounce.start()

    def _on_resume(self) -> None:
        QTimer.singleShot(4000, self.refresh_devices)
        self.engine.check_soon(3000)

    def refresh_devices(self) -> None:
        self.default_out = self.devices.default_output()
        self.speakers = self.devices.bluetooth_outputs()
        saved = self.settings.value("speaker_id", "")
        by_id = {e.id: e for e in self.speakers}
        target = by_id.get(saved)
        if target is None and self.default_out and self.default_out.bluetooth:
            target = by_id.get(self.default_out.id)
        if target is None and self.speakers:
            target = self.speakers[0]
        self.target = target
        try:
            self.probe.resolve(target.container if target else None)
        except Exception:
            pass
        if self._default_changed:
            self._default_changed = False
            self.engine.check_soon(1200)
        self._sync_volume()
        self.poll_bluetooth()

    def poll_bluetooth(self) -> None:
        try:
            self.radio = bt_control.radio_state()
        except Exception:
            self.radio = "none"
        if self.target is None:
            self.bt = BluetoothStatus(None, None)
        else:
            try:
                st = self.probe.read()
            except Exception:
                st = BluetoothStatus(None, None)
            # Cross-check with the audio endpoint state, which Windows updates the
            # moment the A2DP link drops or returns.
            ep_state = self.devices.endpoint_state(self.target.id)
            endpoint_up = ep_state == 1
            # "Connected" means usable for audio: the Bluetooth link is up AND the
            # speaker's audio output exists. (After a disconnect the audio output goes
            # within ~1 s, while the link property lags by a few seconds.)
            connected = endpoint_up and st.connected is not False
            self.bt = BluetoothStatus(connected, st.battery if connected else None)
        self.render()

    # -- rendering --------------------------------------------------------------------
    def _sync_tick(self, *_):
        if self.window.isVisible() and self.engine.running:
            if not self._tick.isActive():
                self._tick.start()
        else:
            self._tick.stop()
        self._update_elapsed()

    def _elapsed_text(self) -> str:
        if self.engine.started_at is None:
            return "--:--:--"
        return format_elapsed(time.monotonic() - self.engine.started_at)

    def _update_elapsed(self) -> None:
        if self.window.isVisible() and not self.window.isMinimized():
            self.window.set_elapsed(self._elapsed_text())

    def render(self) -> None:
        e = self.engine
        state = e.state
        state_color = {State.ACTIVE: "green", State.STOPPED: "red", State.ERROR: "red"}.get(state, "orange")

        v = View(state=state.value.upper(), state_color=state_color, elapsed=self._elapsed_text(),
                 can_start=not e.running, can_stop=e.running)
        v.speakers = [(s.id, s.name if s.active else f"{s.name} — disconnected") for s in self.speakers]
        v.speaker_id = self.target.id if self.target else None

        connected = self.bt.connected
        if self.target is None:
            v.connection, v.connection_color = "No speaker", "muted"
        elif connected:
            v.connection, v.connection_color = "Connected", "green"
        else:
            v.connection, v.connection_color = "Disconnected", "red"
        busy = self._busy
        if busy in ("connect", "disconnect"):
            v.connection = "Connecting…" if busy == "connect" else "Disconnecting…"
            v.connection_color = "orange"
        if self.target is not None and self.probe.can_control and self.radio != "off":
            v.conn_action = "DISCONNECT" if connected else "CONNECT"
            v.conn_action_enabled = not busy

        radio = self.radio
        v.radio, v.radio_color = {"on": ("On", "green"), "off": ("Off", "red")}.get(radio, ("No adapter", "muted"))
        if busy == "radio":
            v.radio, v.radio_color = "Switching…", "orange"
        if radio != "none":
            v.radio_action = "TURN OFF" if radio == "on" else "TURN ON"
            v.radio_action_enabled = not busy

        b = self.bt.battery
        if b is None:
            v.battery, v.battery_color = "N/A", "muted"
        else:
            v.battery = f"{b}%"
            v.battery_color = "green" if b >= MID_BATTERY else ("orange" if b >= LOW_BATTERY else "red")

        v.default_output = self.default_out.name if self.default_out else "None"
        v.playing_on = e.output.name if e.output else "—"

        # One message, highest priority first. Facts only.
        msg, color = "", "muted"
        if state == State.ERROR:
            msg, color = e.error or "Playback error. Retrying automatically.", "red"
        elif self._task_msg is not None and not busy:
            msg, color = self._task_msg
        elif radio == "off":
            msg, color = "Bluetooth is off. Turn it on to reach the speaker.", "orange"
        elif self.target is None:
            msg, color = "No paired Bluetooth speaker found. Pair it in Windows Settings.", "orange"
        elif not connected:
            msg, color = ("Speaker disconnected. Keep-alive continues and will reach the speaker "
                          "when it reconnects." if e.running else "Speaker is disconnected."), "orange"
        elif e.running and e.output and e.output.id != self.target.id:
            msg, color = (f"Silence is playing on “{e.output.name}”, not on the speaker. "
                          "Set the speaker as the Windows default output."), "orange"
        elif self.default_out is None or self.default_out.id != self.target.id:
            msg, color = "The speaker is not the Windows default output.", "orange"
        elif b is not None and b < LOW_BATTERY:
            msg, color = "Speaker battery is low.", "orange"
        v.message, v.message_color = msg, color
        self.window.render(v)

        # Tray reflects the same verified state.
        self._act_start.setEnabled(not e.running)
        self._act_stop.setEnabled(e.running)
        tray_key = {State.ACTIVE: "green", State.ERROR: "red", State.STOPPED: "idle"}.get(state, "orange")
        if state == State.ACTIVE and (not connected or (e.output and self.target and e.output.id != self.target.id)):
            tray_key = "orange"
        self.tray.setIcon(self._tray_icons[tray_key])
        tip = f"{APP_NAME} — {state.value}"
        if self.target is not None:
            tip += f"\n{self.target.name}: {'connected' if connected else 'disconnected'}"
            if b is not None:
                tip += f", battery {b}%"
        self.tray.setToolTip(tip[:127])
        self._sync_tick()


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    winutil.set_app_user_model_id(APP_ID)
    instance = winutil.SingleInstance("Local\\ALIVE.KeepAlive.SingleInstance")
    if instance.already_running:
        winutil.allow_set_foreground()
        winutil.signal_existing_instance()
        return 0

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)  # closing the window hides it; tray Exit quits
    app.setStyle("Fusion")                # flat, fully stylable, no native rounding
    app.setFont(font())                   # Segoe UI 10pt for everything else

    if not QSystemTrayIcon.isSystemTrayAvailable():
        # Without a tray, closing the window must still be possible: quit instead.
        app.setQuitOnLastWindowClosed(True)

    ctl = Controller(app, start_hidden="--tray" in argv, autostart="--start" in argv)
    code = app.exec()
    ctl.shutdown()
    instance.release()
    return code

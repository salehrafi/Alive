"""Main window. Purely presentational: it renders a View and emits user intents."""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QSizePolicy, QSlider, QVBoxLayout, QWidget)

from . import APP_NAME
from .theme import Palette, font


@dataclass
class View:
    state: str = "STOPPED"
    state_color: str = "red"          # palette attribute name
    elapsed: str = "--:--:--"
    can_start: bool = True
    can_stop: bool = False
    speakers: list[tuple[str, str]] = field(default_factory=list)  # (id, label)
    speaker_id: str | None = None
    connection: str = "N/A"
    connection_color: str = "muted"
    conn_action: str = ""             # "CONNECT" / "DISCONNECT" / "" (hidden)
    conn_action_enabled: bool = True
    radio: str = "N/A"
    radio_color: str = "muted"
    radio_action: str = ""            # "TURN ON" / "TURN OFF" / ""
    radio_action_enabled: bool = True
    battery: str = "N/A"
    battery_color: str = "muted"
    default_output: str = "N/A"
    playing_on: str = "—"
    message: str = ""
    message_color: str = "muted"


def _rule() -> QFrame:
    f = QFrame()
    f.setObjectName("rule")
    return f


class _Dot(QFrame):
    """Square status indicator (sharp corners, flat fill)."""

    def __init__(self, size: int) -> None:
        super().__init__()
        self.setFixedSize(size, size)
        self._color = ""

    def set_color(self, color: str) -> None:
        if color != self._color:
            self._color = color
            self.setStyleSheet(f"background:{color}; border:none;")


class MainWindow(QWidget):
    startRequested = Signal()
    stopRequested = Signal()
    themeToggleRequested = Signal()
    speakerSelected = Signal(str)
    connectToggleRequested = Signal()
    radioToggleRequested = Signal()
    volumeChanged = Signal(int)
    muteToggleRequested = Signal()
    hideRequested = Signal()
    visibilityChanged = Signal(bool)

    def __init__(self, icon) -> None:
        super().__init__()
        self.setObjectName("root")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(icon)
        self.setWindowFlags(Qt.Window | Qt.WindowTitleHint | Qt.WindowSystemMenuHint
                            | Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint)
        self.setFixedWidth(420)
        self._palette: Palette | None = None
        self._view = View()
        self._updating = False

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 24)
        root.setSpacing(0)

        # Header
        head = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        wordmark = QLabel(APP_NAME)
        wordmark.setObjectName("wordmark")
        wordmark.setFont(font("Times New Roman", 22, 700, 3))
        tagline = QLabel("BLUETOOTH SPEAKER KEEP-ALIVE")
        tagline.setObjectName("tagline")
        tagline.setFont(font(pt=8, spacing=1))
        title_col.addWidget(wordmark)
        title_col.addWidget(tagline)
        head.addLayout(title_col)
        head.addStretch(1)
        self.theme_btn = QPushButton("DARK")
        self.theme_btn.setObjectName("themeToggle")
        self.theme_btn.setFont(font(pt=8, weight=600, spacing=1))
        self.theme_btn.setCursor(Qt.PointingHandCursor)
        self.theme_btn.setToolTip("Switch theme")
        self.theme_btn.clicked.connect(self.themeToggleRequested)
        head.addWidget(self.theme_btn, 0, Qt.AlignTop)
        root.addLayout(head)
        root.addSpacing(18)
        root.addWidget(_rule())
        root.addSpacing(22)

        # Status block
        status_row = QHBoxLayout()
        status_row.setSpacing(14)
        self.state_dot = _Dot(16)
        self.state_label = QLabel()
        self.state_label.setObjectName("state")
        self.state_label.setFont(font(pt=24, weight=600, spacing=1))
        status_row.addWidget(self.state_dot, 0, Qt.AlignVCenter)
        status_row.addWidget(self.state_label, 0, Qt.AlignVCenter)
        status_row.addStretch(1)
        self.elapsed_label = QLabel()
        self.elapsed_label.setObjectName("elapsed")
        self.elapsed_label.setFont(font("Consolas", 13))
        self.elapsed_label.setToolTip("Keep-alive runtime")
        status_row.addWidget(self.elapsed_label, 0, Qt.AlignVCenter)
        root.addLayout(status_row)
        root.addSpacing(20)

        # Controls
        btns = QHBoxLayout()
        btns.setSpacing(10)
        self.start_btn = QPushButton("START")
        self.start_btn.setObjectName("primary")
        self.stop_btn = QPushButton("STOP")
        for b in (self.start_btn, self.stop_btn):
            b.setCursor(Qt.PointingHandCursor)
            b.setFont(font(pt=10, weight=600, spacing=2))
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btns.addWidget(b)
        self.start_btn.clicked.connect(self.startRequested)
        self.stop_btn.clicked.connect(self.stopRequested)
        root.addLayout(btns)
        root.addSpacing(24)
        root.addWidget(_rule())
        root.addSpacing(18)

        # Details
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(14)
        grid.setColumnStretch(1, 1)

        def key(text: str) -> QLabel:
            k = QLabel(text)
            k.setObjectName("key")
            k.setFont(font(pt=8, weight=600, spacing=1))
            return k

        def value() -> QLabel:
            v = QLabel()
            v.setObjectName("value")
            v.setWordWrap(True)
            v.setTextInteractionFlags(Qt.TextSelectableByMouse)
            return v

        self.speaker_combo = QComboBox()
        self.speaker_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.speaker_combo.setMinimumContentsLength(10)
        self.speaker_combo.setCursor(Qt.PointingHandCursor)
        self.speaker_combo.setToolTip("Bluetooth speaker to monitor")
        self.speaker_combo.currentIndexChanged.connect(self._on_combo)
        popup = self.speaker_combo.view().window()
        popup.setWindowFlags(popup.windowFlags() | Qt.NoDropShadowWindowHint)
        self.speaker_none = value()
        self.speaker_none.setText("No paired Bluetooth speaker")

        self.conn_dot, self.conn_label = _Dot(9), value()
        self.radio_dot, self.radio_label = _Dot(9), value()

        def small(text: str, signal) -> QPushButton:
            b = QPushButton(text)
            b.setObjectName("small")
            b.setFont(font(pt=8, weight=600, spacing=1))
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(signal)
            return b

        self.conn_btn = small("DISCONNECT", self.connectToggleRequested)
        self.radio_btn = small("TURN OFF", self.radioToggleRequested)
        self.mute_btn = small("MUTE", self.muteToggleRequested)
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setPageStep(10)
        self.volume_slider.setCursor(Qt.PointingHandCursor)
        self.volume_slider.setToolTip("Speaker volume")
        self.volume_slider.valueChanged.connect(self._on_volume)
        self.volume_label = value()
        self.volume_label.setFixedWidth(40)
        self.volume_label.setWordWrap(False)
        self._vol_updating = False
        self.batt_dot, self.batt_label = _Dot(9), value()
        self.default_label = value()
        self.playing_label = value()

        def with_dot(dot: _Dot, label: QLabel, button: QPushButton | None = None) -> QWidget:
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(8)
            h.addWidget(dot, 0, Qt.AlignVCenter)
            h.addWidget(label, 1)
            if button is not None:
                h.addWidget(button, 0, Qt.AlignVCenter)
            return w

        volume_cell = QWidget()
        vh = QHBoxLayout(volume_cell)
        vh.setContentsMargins(0, 0, 0, 0)
        vh.setSpacing(10)
        vh.addWidget(self.volume_slider, 1)
        vh.addWidget(self.volume_label)
        vh.addWidget(self.mute_btn)

        speaker_cell = QWidget()
        sc = QVBoxLayout(speaker_cell)
        sc.setContentsMargins(0, 0, 0, 0)
        sc.addWidget(self.speaker_combo)
        sc.addWidget(self.speaker_none)

        rows = [("BLUETOOTH", with_dot(self.radio_dot, self.radio_label, self.radio_btn)),
                ("SPEAKER", speaker_cell),
                ("CONNECTION", with_dot(self.conn_dot, self.conn_label, self.conn_btn)),
                ("BATTERY", with_dot(self.batt_dot, self.batt_label)),
                ("VOLUME", volume_cell),
                ("DEFAULT OUTPUT", self.default_label),
                ("PLAYING ON", self.playing_label)]
        for r, (k, w) in enumerate(rows):
            grid.addWidget(key(k), r, 0, Qt.AlignLeft | Qt.AlignVCenter)
            grid.addWidget(w, r, 1)
        root.addLayout(grid)
        root.addSpacing(18)

        self.message_label = QLabel()
        self.message_label.setObjectName("message")
        self.message_label.setFont(font(pt=9))
        self.message_label.setWordWrap(True)
        root.addWidget(self.message_label)
        root.addStretch(1)

    # -- rendering --------------------------------------------------------------
    def apply_palette(self, p: Palette) -> None:
        self._palette = p
        self.theme_btn.setText("LIGHT" if p.name == "dark" else "DARK")
        self.render(self._view)

    def set_elapsed(self, text: str) -> None:
        if self.elapsed_label.text() != text:
            self.elapsed_label.setText(text)

    def render(self, v: View) -> None:
        self._view = v
        p = self._palette
        if p is None:
            return
        c = lambda name: getattr(p, name)  # noqa: E731
        self.state_label.setText(v.state)
        self.state_label.setStyleSheet(f"color:{c(v.state_color)};")
        self.state_dot.set_color(c(v.state_color))
        self.set_elapsed(v.elapsed)
        self.start_btn.setEnabled(v.can_start)
        self.stop_btn.setEnabled(v.can_stop)

        self._updating = True
        try:
            ids = [self.speaker_combo.itemData(i) for i in range(self.speaker_combo.count())]
            labels = [self.speaker_combo.itemText(i) for i in range(self.speaker_combo.count())]
            if ids != [s[0] for s in v.speakers] or labels != [s[1] for s in v.speakers]:
                self.speaker_combo.clear()
                for sid, label in v.speakers:
                    self.speaker_combo.addItem(label, sid)
            idx = self.speaker_combo.findData(v.speaker_id) if v.speaker_id else -1
            if idx >= 0 and idx != self.speaker_combo.currentIndex():
                self.speaker_combo.setCurrentIndex(idx)
        finally:
            self._updating = False
        has = bool(v.speakers)
        self.speaker_combo.setVisible(has)
        self.speaker_none.setVisible(not has)

        self.conn_label.setText(v.connection)
        self.conn_dot.set_color(c(v.connection_color))
        self.conn_btn.setText(v.conn_action)
        self.conn_btn.setVisible(bool(v.conn_action))
        self.conn_btn.setEnabled(v.conn_action_enabled)
        self.radio_label.setText(v.radio)
        self.radio_dot.set_color(c(v.radio_color))
        self.radio_btn.setText(v.radio_action)
        self.radio_btn.setVisible(bool(v.radio_action))
        self.radio_btn.setEnabled(v.radio_action_enabled)
        self.batt_label.setText(v.battery)
        self.batt_label.setStyleSheet(f"color:{c(v.battery_color)};" if v.battery_color != "muted" else "")
        self.batt_dot.set_color(c(v.battery_color))
        self.default_label.setText(v.default_output)
        self.playing_label.setText(v.playing_on)
        self.message_label.setText(v.message)
        self.message_label.setStyleSheet(f"color:{c(v.message_color)};")
        self.message_label.setVisible(bool(v.message))
        self.adjustSize()

    def set_volume(self, level: int | None, muted: bool = False) -> None:
        """level None = no controllable volume (speaker disconnected)."""
        enabled = level is not None
        self.volume_slider.setEnabled(enabled)
        self.mute_btn.setEnabled(enabled)
        self.mute_btn.setText("UNMUTE" if muted else "MUTE")
        if not enabled:
            self.volume_label.setText("N/A")
            return
        self.volume_label.setText("Muted" if muted else f"{level}%")
        if not self.volume_slider.isSliderDown() and self.volume_slider.value() != level:
            self._vol_updating = True
            self.volume_slider.setValue(level)
            self._vol_updating = False

    # -- events -------------------------------------------------------------------
    def _on_volume(self, value: int) -> None:
        if not self._vol_updating:
            self.volumeChanged.emit(value)

    def _on_combo(self, index: int) -> None:
        if not self._updating and index >= 0:
            self.speakerSelected.emit(self.speaker_combo.itemData(index))

    def closeEvent(self, e: QCloseEvent) -> None:
        # Closing the window never stops keep-alive; it just hides to the tray.
        e.ignore()
        self.hideRequested.emit()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self.visibilityChanged.emit(True)

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        self.visibilityChanged.emit(False)

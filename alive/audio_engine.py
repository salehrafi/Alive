"""Keep-alive audio engine.

Playback is identical to the original alive.py: a 1 s, 16-bit, 44.1 kHz stereo
all-zero PCM WAV looped by winsound.PlaySound(SND_FILENAME|SND_ASYNC|SND_LOOP).
Windows' own winmm thread streams it, so the GUI thread never blocks.

PlaySound is fire-and-forget and reports nothing back, so the engine verifies
the real state by asking Windows whether this process owns an *active* audio
session (see AudioDevices.own_active_session). The state shown in the GUI is
always the verified one.
"""
from __future__ import annotations

import os
import time
import wave
import winsound
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from .audio_devices import AudioDevices, Endpoint

SAMPLE_RATE = 44100
CHANNELS = 2
SAMPLE_WIDTH = 2
DURATION_S = 1
_FRAMES = SAMPLE_RATE * DURATION_S

_PLAY_FLAGS = winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP | winsound.SND_NODEFAULT

WATCHDOG_MS = 5_000       # verify cadence while running (one ~3 ms COM query)
FIRST_CHECK_MS = 700      # first verification after (re)starting playback
RECHECK_MS = 1_000        # re-check after a single missed verification
BASE_BACKOFF_MS = 2_000   # first retry delay after a failure (doubles)
MAX_BACKOFF_MS = 60_000


class State(Enum):
    STOPPED = "Stopped"
    STARTING = "Starting"
    ACTIVE = "Active"
    RECOVERING = "Recovering"
    ERROR = "Error"


def wav_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "ALIVE"


def ensure_silent_wav(path: Path) -> Path:
    """Return a valid silent WAV at `path`, (re)creating it if missing/corrupt."""
    expected_size = 44 + _FRAMES * CHANNELS * SAMPLE_WIDTH
    try:
        if path.stat().st_size == expected_size:
            with wave.open(str(path), "rb") as w:
                if (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (
                        CHANNELS, SAMPLE_WIDTH, SAMPLE_RATE, _FRAMES):
                    return path
    except (OSError, wave.Error, EOFError):
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(SAMPLE_WIDTH)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(bytes(_FRAMES * CHANNELS * SAMPLE_WIDTH))
    os.replace(tmp, path)
    return path


class AudioEngine(QObject):
    stateChanged = Signal()

    def __init__(self, devices: AudioDevices, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._devices = devices
        self._wav = wav_dir() / "silent.wav"
        self._want_running = False
        self._playing = False                 # PlaySound loop currently requested
        self.state = State.STOPPED
        self.error: str = ""
        self.output: Endpoint | None = None    # verified endpoint carrying the stream
        self.started_at: float | None = None   # monotonic time of user Start
        self._failures = 0
        self._backoff_ms = BASE_BACKOFF_MS

        self._follow_tried: str | None = None  # default id we already moved to

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._verify)
        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(self._retry)

    # -- public API -----------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._want_running

    def start(self) -> None:
        if self._want_running:
            return  # never start a duplicate loop
        self._want_running = True
        self.started_at = time.monotonic()
        self._failures = 0
        self._backoff_ms = BASE_BACKOFF_MS
        self._follow_tried = None
        self._play(State.STARTING)

    def stop(self) -> None:
        self._want_running = False
        self._timer.stop()
        self._retry_timer.stop()
        self._halt()
        self.started_at = None
        self.output = None
        self.error = ""
        self._set(State.STOPPED)

    def shutdown(self) -> None:
        self._want_running = False
        self._timer.stop()
        self._retry_timer.stop()
        self._halt()

    def check_soon(self, delay_ms: int = 1_500) -> None:
        """Re-verify shortly (device change, resume from sleep...)."""
        if self._want_running:
            self._timer.start(delay_ms)


    # -- internals --------------------------------------------------------------
    def _halt(self) -> None:
        if self._playing:
            try:
                winsound.PlaySound(None, 0)
            except RuntimeError:
                pass
            self._playing = False

    def _play(self, state: State) -> None:
        self._retry_timer.stop()
        self._halt()
        try:
            ensure_silent_wav(self._wav)
        except OSError as e:
            self._fail(f"Cannot create silent WAV: {e.strerror or e}")
            return
        if self._devices.default_output() is None:
            self._fail("No audio output device available")
            return
        try:
            winsound.PlaySound(str(self._wav), _PLAY_FLAGS)
            self._playing = True
        except RuntimeError as e:
            self._fail(f"Playback failed: {e}")
            return
        self._set(state)
        self._timer.start(FIRST_CHECK_MS)

    def _verify(self) -> None:
        if not self._want_running:
            return
        out = self._devices.own_active_session() if self._playing else None
        default = self._devices.default_output()
        if out is not None:
            # Stream is alive. If Windows switched the default output (e.g. the
            # speaker reconnected) and the stream did not follow, move it once.
            if (default is not None and default.id != out.id and default.active
                    and self._follow_tried != default.id):
                self._follow_tried = default.id
                self.output = out
                self._play(State.RECOVERING)
                return
            self._failures = 0
            self._backoff_ms = BASE_BACKOFF_MS
            self.error = ""
            changed = self.output != out or self.state != State.ACTIVE
            self.output = out
            if changed:
                self._set(State.ACTIVE)
            self._timer.start(WATCHDOG_MS)
            return
        # No active stream from this process.
        self._failures += 1
        self.output = None
        if self._failures == 1 and self.state == State.ACTIVE:
            self._timer.start(RECHECK_MS)  # tolerate one transient miss
            return
        if self._failures > 4:
            self.error = "Playback is not reaching any output device"
            self._set(State.ERROR)
        self._play_after_backoff()

    def _play_after_backoff(self) -> None:
        delay = self._backoff_ms
        self._backoff_ms = min(self._backoff_ms * 2, MAX_BACKOFF_MS)
        if self.state not in (State.ERROR,):
            self._set(State.RECOVERING)
        self._retry_timer.start(delay)

    def _retry(self) -> None:
        if self._want_running and self.output is None:
            self._play(self.state if self.state == State.ERROR else State.RECOVERING)

    def _fail(self, msg: str) -> None:
        self._playing = False
        self.output = None
        self.error = msg
        self._failures += 1
        self._set(State.ERROR)
        if self._want_running:
            delay = self._backoff_ms
            self._backoff_ms = min(self._backoff_ms * 2, MAX_BACKOFF_MS)
            self._retry_timer.start(delay)

    def _set(self, state: State) -> None:
        self.state = state
        self.stateChanged.emit()

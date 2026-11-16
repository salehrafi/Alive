# ALIVE

ALIVE keeps a Bluetooth speaker awake. Many speakers switch themselves off after a few
minutes without sound. ALIVE plays a silent audio loop through the speaker so it stays
connected and ready. It was built for the Xiaomi Compact Mini Bluetooth Speaker 2
(Windows name "MI BT 18I"), but it works with any Bluetooth speaker that Windows
treats as an audio output.

ALIVE started as a small Python script. This version adds a window, a system tray icon,
live status for the speaker, its battery, and its volume, and an installer.

## Installing

1. Run `ALIVE-Setup-1.0.0.exe` and follow the wizard.
2. The setup installs ALIVE for your user account only. You do not need administrator
   rights, and you do not need Python.
3. When setup finishes, ALIVE starts and a Start menu entry is created.

Make sure the speaker is paired and connected, and that it is the Windows default
audio output. ALIVE tells you if it is not.

### Install options

The wizard has two optional checkboxes. Both are off by default.

- **Create a desktop shortcut.**
- **Start ALIVE in the notification area when I sign in to Windows.** This adds a
  startup shortcut that opens ALIVE hidden in the tray. It does not start playback.

If you also want playback to start at sign-in, open the startup shortcut (press
Win + R, type `shell:startup`), and add `--start` to the end of its Target field:

```
"C:\Users\<you>\AppData\Local\Programs\ALIVE\ALIVE.exe" --tray --start
```

| Argument | Effect |
|---|---|
| `--tray` | Start hidden in the notification area. |
| `--start` | Start keep-alive as soon as ALIVE opens. |

Only one copy of ALIVE can run at a time. If you open it again, the window of the
running copy comes to the front.

### Uninstalling

Open Windows Settings, go to Apps, select ALIVE, and choose Uninstall. This stops
playback, removes the program, and deletes the silent sound file ALIVE keeps in
`%LOCALAPPDATA%\ALIVE`.

## Using ALIVE

1. Press **START**. The status changes to **ACTIVE** (green) only after Windows confirms
   that the silent sound is really playing.
2. Close the window. ALIVE keeps running in the notification area. Click the tray icon
   to open the window again. The tray menu also has Start, Stop and Exit.
3. Exiting ALIVE stops playback.

### What each field means

| Field | Meaning |
|---|---|
| Status | The state of the playback engine. ACTIVE is green. STARTING and RECOVERING are orange. STOPPED and ERROR are red. |
| Runtime | Time since you pressed START. It keeps counting through automatic recoveries. |
| Bluetooth | Whether the Bluetooth adapter is On, Off, or missing. TURN ON and TURN OFF switch it. Turning it off asks you first, because every Bluetooth device disconnects, including keyboards and mice. |
| Speaker | The Bluetooth audio device ALIVE watches. Use the dropdown if you have more than one. |
| Connection | Shows Connected only when the Bluetooth link is up and the speaker's audio output is available. CONNECT and DISCONNECT connect or disconnect the speaker. The speaker stays paired either way. |
| Battery | The battery level Windows reports for the speaker. Shows N/A if Windows has no value. Green is 50% or higher, orange is 20% to 49%, red is below 20%. |
| Volume | The speaker's volume and mute state. It stays in sync when you change the volume from Windows, the keyboard, or the speaker's own buttons. |
| Default output | The Windows default playback device. |
| Playing on | The device that ALIVE has confirmed is carrying the silent sound. |

The tray icon shows the same state at a glance. A green square means active. An orange
square means ALIVE is recovering or there is a warning, for example when the speaker is
disconnected. A red square means an error. No square means stopped. Hover over the icon
to see the status and battery level.

The DARK and LIGHT button at the top right switches the theme. ALIVE remembers your choice.

## How it works

**Playback.** ALIVE loops a one-second, 16-bit, 44.1 kHz stereo WAV file that contains
only silence. It plays the file with `winsound.PlaySound`, the same call the original
script used. Windows plays it on its own audio thread, so the window never freezes.
ALIVE stores the file in `%LOCALAPPDATA%\ALIVE\silent.wav`. Before each start it checks
the file and recreates it if it is missing or damaged.

**Checking the real state.** `PlaySound` does not report whether playback worked. So
ALIVE asks Windows whether its own process has an active audio stream, and on which
device. It checks 0.7 seconds after starting, then every 5 seconds. Each check takes
about 3 milliseconds. The status you see is always the result of that check.

**Recovery.**

- If the stream stops (the speaker disconnects, the driver resets, or the PC wakes from
  sleep), ALIVE starts playback again. It waits 2 seconds before the first retry, then
  4, 8, and so on, up to 60 seconds. After repeated failures the status shows ERROR, and
  ALIVE keeps retrying.
- If Windows changes the default output, for example when the speaker reconnects and
  Windows switches back to it, ALIVE moves the silent sound to the new default.
- ALIVE learns about device changes from Windows notifications. It does not poll for them.
  After the PC wakes from sleep, it checks again right away.

**Connection and battery.** ALIVE finds the speaker's Bluetooth device through its PnP
container ID. It then reads the same properties that Settings > Bluetooth & devices
uses. Battery comes from `DEVPKEY_Bluetooth_Battery`. Windows fills this in from the
Hands-Free profile for classic Bluetooth speakers, and from the GATT Battery Service for
Bluetooth LE devices. These reads are local and cheap. They happen every 30 seconds and
whenever Windows reports a device change. They never touch the audio playback.

If Windows has no battery value, or the speaker is disconnected, ALIVE shows N/A.
ALIVE does not estimate the battery level.

**Connect and disconnect.** The CONNECT and DISCONNECT buttons send the same request as
the Connect and Disconnect buttons in the classic Sound control panel. The request goes
to the speaker's Bluetooth audio drivers (A2DP and Hands-Free) through the kernel
streaming property `KSPROPSETID_BtAudio`. No administrator rights are needed, and the
speaker stays paired. With the MI BT 18I, disconnect took effect within about 1 second,
and reconnect completed within about 2 seconds.

**Bluetooth on and off.** ALIVE reads the radio state locally. An adapter that is on
is found through `BluetoothFindFirstRadio`. An adapter that is present but switched off
is detected through its device node. Switching the radio uses Windows' Radios API
(the same one Quick Settings uses). ALIVE calls it through Windows PowerShell, only when
you press the button. The call takes about half a second to 3 seconds.

**Volume.** ALIVE uses the Windows endpoint volume interface on the speaker's output.
Windows notifies ALIVE when the volume changes, so ALIVE does not poll.

## Resource use

These numbers come from the release build, measured on Windows 11 (build 26200) with
the speaker connected.

| State | Private memory | Working set | CPU (average) |
|---|---|---|---|
| Idle in tray | 31.0 MB | 66 MB | 0.000% (0 ms of CPU in 60 s) |
| Keep-alive running, hidden in tray | 31.1 MB | 69 MB | 0.018% |
| Keep-alive running, window open | 32.2 MB | 73 MB | 0.016% |

I also ran keep-alive for 20 minutes with samples every 30 seconds. Private memory
started at 31.6 MB and settled at 33.0 MB by minute 15, then stayed flat. Total CPU time
for the whole run was 2.95 seconds. The handle count stayed at about 490. During the run
I disconnected and reconnected the speaker on purpose. The sound moved to the PC
speakers and then came back to the Bluetooth speaker by itself. Only 1 of 40 samples,
taken during the disconnect, showed no active stream.

A leak test ran each periodic operation 5,000 times, twice. Memory did not grow after
the first warm-up round.

The later build with the Bluetooth and volume controls measured 32.2 MB private memory
and 0.007% CPU with keep-alive running in the tray.

Some changes came directly from these measurements:

- Fonts are set in code, not in the Qt stylesheet. One `font-family` rule in the
  stylesheet made Qt load the whole system font list. That cost about 18 MB and about
  650 handles.
- comtypes leaks about 110 bytes each time it reads a device ID. ALIVE calls the
  underlying function itself and frees the memory.
- The one-second elapsed-time display updates only while the window is visible.
- ALIVE has no network code, no log files, and no disk writes after startup.

## Project layout

```
alive/
  app.py             startup, tray, single instance, power events, main controller
  audio_engine.py    silent WAV playback, verification and recovery
  audio_devices.py   Windows audio endpoints, default output, volume, notifications
  bluetooth.py       connection and battery reads
  bt_control.py      speaker connect/disconnect, radio state and on/off
  ui.py              main window (display only)
  theme.py           light and dark colours, stylesheet, fonts
  winutil.py         Win32 helpers (single instance, app ID, messages)
  __main__.py        lets you run the package with `python -m alive`
assets/
  alive.ico          application icon (16 to 256 px)
  arrow_light.png    dropdown arrow, light theme
  arrow_dark.png     dropdown arrow, dark theme
run_alive.pyw        entry point for PyInstaller and for running from source
ALIVE.spec           PyInstaller settings
version_info.txt     program metadata (product name, version)
installer.iss        Inno Setup script for the installer
build_installer.ps1  builds dist\ALIVE-Setup-<version>.exe
requirements.txt     dependencies
```

## Running from source

```
pip install -r requirements.txt
python -m alive
```

To run without a console window, use `pythonw run_alive.pyw`.

## Building the installer

You need Windows 10 (version 1809 or later) or Windows 11, 64-bit. You also need
Python 3.10 or later, and Inno Setup 6. You can install Inno Setup with:

```
winget install JRSoftware.InnoSetup
```

Then run:

```
powershell -ExecutionPolicy Bypass -File build_installer.ps1
```

The script builds `dist\ALIVE\ALIVE.exe` with PyInstaller if that folder is missing.
Then it compiles `installer.iss`. The result is `dist\ALIVE-Setup-1.0.0.exe`, which is
the only file you need to share. You can delete the `dist\ALIVE` folder afterwards. The
script creates it again when you need it.

To regenerate the icon after changing it, run `python tools\make_icon.py`. This needs Pillow.

## Tests

The engine tests are in `tests\test_engine.py`. That folder is not in the project at the
moment. If you restore it, run:

```
python -m unittest discover -s tests -v
```

The tests cover:

- verifying that playback started
- refusing a second start while playing
- repeated start and stop
- no restarts while playback is healthy
- recovery after the stream stops
- following a change of default output
- one move attempt when the stream cannot follow the default
- playback failure followed by recovery
- no output device available
- cancelling a pending retry on stop
- creating and repairing the WAV file

## Troubleshooting

**Silence is playing on another device.** The speaker is not the Windows default output.
Open Settings, go to System, then Sound, and choose the speaker under Output. ALIVE
follows the default automatically.

**Battery shows N/A.** Windows has no battery value for the device. Check Settings >
Bluetooth & devices. Some speakers only report the battery after they reconnect.

**The speaker still sleeps while the status is ACTIVE.** Check that "Playing on" shows
the speaker. If it shows another device, change the default output as described above.

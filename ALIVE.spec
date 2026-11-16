# PyInstaller spec for ALIVE.
#   pyinstaller --noconfirm --clean ALIVE.spec              -> dist\ALIVE\ALIVE.exe (folder, recommended)
#   set ALIVE_ONEFILE=1 && pyinstaller --noconfirm ALIVE.spec -> dist\ALIVE.exe (single file)
import os
import re

ONEFILE = os.environ.get("ALIVE_ONEFILE") == "1"

# Only QtCore/QtGui/QtWidgets are used. Everything else PySide6 can drag in is excluded.
EXCLUDES = [
    "tkinter", "unittest", "pydoc", "doctest", "email", "http", "xmlrpc", "sqlite3",
    "numpy", "PIL", "psutil", "pycaw.utils", "pycaw.pycaw", "pycaw.magic",
    "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtSvg",
    "PySide6.QtPdf", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtMultimedia", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtDBus", "PySide6.QtXml", "PySide6.QtSql", "PySide6.QtTest",
    "PySide6.QtPrintSupport", "PySide6.QtConcurrent",
]

# Drop large binaries/data the app never loads.
DROP = re.compile(
    r"(opengl32sw|d3dcompiler|Qt6(Network|Qml|Quick|Pdf|Svg|OpenGL|VirtualKeyboard|DBus|WebEngine|Multimedia)"
    r"|qtvirtualkeyboard|qsvg|qpdf|qtuiotouch|qwebp|qtiff|qgif|qjpeg|qicns|qtga|qwbmp"
    r"|qdirect2d|qminimal|qoffscreen|qwindowsvistastyle|qmodernwindowsstyle|qnetworklistmanager|qtls"
    r"|translations[\\/]|libcrypto|libssl|_ssl|_hashlib|_bz2|_lzma|_decimal|_sqlite3|_elementtree|pyexpat)",
    re.IGNORECASE,
)

a = Analysis(
    ["run_alive.pyw"],
    pathex=[],
    binaries=[],
    datas=[("assets/alive.ico", "assets"), ("assets/arrow_light.png", "assets"),
           ("assets/arrow_dark.png", "assets")],
    hiddenimports=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=2,
)
a.binaries = [b for b in a.binaries if not DROP.search(b[0])]
a.datas = [d for d in a.datas if not DROP.search(d[0])]

pyz = PYZ(a.pure)

common = dict(
    name="ALIVE",
    icon="assets/alive.ico",
    version="version_info.txt",
    console=False,
    debug=False,
    strip=False,
    upx=False,  # UPX-packed Qt DLLs load slower, use more RAM and trip antivirus
    uac_admin=False,
)

if ONEFILE:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], runtime_tmpdir=None, **common)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **common)
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="ALIVE")

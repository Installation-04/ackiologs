# PyInstaller spec for ackiologs-service.exe — the Windows-only background
# service build (see service_run.py). Built only in the build-windows CI job
# and placed alongside ackiologs.exe so the MSI can register it as a service.
# Build from the repo root (Windows only, needs pywin32 installed):
#   pyinstaller packaging/pyinstaller/ackiologs_service.spec
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None
repo_root = os.path.abspath(os.path.join(os.path.dirname(SPEC), "..", ".."))

datas = [(os.path.join(repo_root, "app", "web", "static"), os.path.join("app", "web", "static"))]
datas += collect_data_files("asyncua")

hiddenimports = (
    collect_submodules("asyncua")
    + collect_submodules("pymodbus")
    + collect_submodules("pycomm3")
    + collect_submodules("snap7")
    + collect_submodules("bacpypes3")
    + collect_submodules("pysnmp")
    + collect_submodules("pyasn1")
    + [
        "paho.mqtt.client",
        "paho.mqtt.publish",
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
        "aiosqlite",
        "asyncpg",
        "httpx",
        "win32timezone",
        "win32serviceutil",
        "servicemanager",
    ]
)

a = Analysis(
    [os.path.join(repo_root, "packaging", "pyinstaller", "service_run.py")],
    pathex=[repo_root],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ackiologs-service",
    console=False,
    onefile=True,
)

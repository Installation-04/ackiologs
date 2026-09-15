# PyInstaller spec for the Ackiologs standalone executable, built for both Linux
# (onefile, tarball release) and Windows (onedir, zipped and wrapped into an MSI).
# Build from the repo root:
#   pyinstaller packaging/pyinstaller/ackiologs.spec
#
# `ONEFILE=1` selects a single-file binary (used for the Linux release);
# omitted/0 builds a onedir folder (used for the Windows release, since the MSI
# installer needs a folder of files to stage under Program Files).
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None
repo_root = os.path.abspath(os.path.join(os.path.dirname(SPEC), "..", ".."))
onefile = os.environ.get("ONEFILE", "0") == "1"

datas = [(os.path.join(repo_root, "app", "web", "static"), os.path.join("app", "web", "static"))]
datas += collect_data_files("asyncua")

hiddenimports = (
    collect_submodules("asyncua")
    + collect_submodules("pymodbus")
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
    ]
)

a = Analysis(
    [os.path.join(repo_root, "packaging", "pyinstaller", "run.py")],
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

if onefile:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name="ackiologs",
        console=True,
        onefile=True,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="ackiologs",
        console=True,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        name="ackiologs",
    )

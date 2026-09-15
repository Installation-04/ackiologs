"""Entry point for the packaged (PyInstaller) Ackiologs executable. Not used when
running from source — there, `uvicorn app.main:app` (see scripts/quickstart.sh and
the Dockerfile) is the entry point instead."""

import multiprocessing
import sys

import uvicorn


def main() -> None:
    host = "0.0.0.0"
    port = 8000
    for i, arg in enumerate(sys.argv[1:]):
        if arg in ("--host",) and i + 2 <= len(sys.argv) - 1:
            host = sys.argv[i + 2]
        if arg in ("--port",) and i + 2 <= len(sys.argv) - 1:
            port = int(sys.argv[i + 2])

    # Import the app object directly rather than uvicorn's "module:attr" string form —
    # inside a frozen executable there's no source file for uvicorn to re-import by path.
    from app.main import app as asgi_app

    print(f"Ackiologs starting at http://{host if host != '0.0.0.0' else 'localhost'}:{port}")
    uvicorn.run(asgi_app, host=host, port=port, workers=1, log_level="info")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()

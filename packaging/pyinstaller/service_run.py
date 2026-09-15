"""Windows Service entry point for the MSI-installed build. Wraps the same
ASGI app as packaging/pyinstaller/run.py, but hosts it through pywin32's
ServiceFramework so it runs permanently in the background — registered with
the Service Control Manager, started automatically at boot, no console window,
manageable via services.msc / `sc` — instead of needing a console window kept
open (that's what the portable zip's ackiologs.exe is for).
"""

import sys
import threading

import servicemanager
import win32event
import win32service
import win32serviceutil


class AckiologsService(win32serviceutil.ServiceFramework):
    _svc_name_ = "Ackiologs"
    _svc_display_name_ = "Ackiologs Historian"
    _svc_description_ = "Industrial data historian: collects, stores, and serves plant data."

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self._server = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        if self._server is not None:
            self._server.should_exit = True
        win32event.SetEvent(self.stop_event)

    def SvcDoRun(self):
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        threading.Thread(target=self._run_server, daemon=True).start()
        win32event.WaitForSingleObject(self.stop_event, win32event.INFINITE)

    def _run_server(self):
        import multiprocessing

        multiprocessing.freeze_support()
        import uvicorn

        from app.main import app as asgi_app

        config = uvicorn.Config(asgi_app, host="0.0.0.0", port=8000, workers=1, log_level="info")
        self._server = uvicorn.Server(config)
        self._server.run()


if __name__ == "__main__":
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(AckiologsService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(AckiologsService)

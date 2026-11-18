"""Startpunkt 3D-Vergleich-MK1."""
from __future__ import annotations

import os
import sys


def resource(rel: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, rel)


def selftest() -> int:
    """Prueft Kernlogik und dass alle GUI-Module importierbar sind (fuer den CI-Build)."""
    from .core.selftest import run
    ok = run()
    try:
        from .ui import main_window, viewer, widgets  # noqa: F401
        print("GUI-Module: OK", flush=True)
    except Exception as e:  # noqa: BLE001
        print("GUI-Module: FEHLER", e, flush=True)
        ok = False
    return 0 if ok else 1


def _quiet_vtk():
    """VTK-Warnungen nicht als eigenes Fenster (vtkOutputWindow) anzeigen."""
    try:
        from vtkmodules.vtkCommonCore import vtkObject
        vtkObject.GlobalWarningDisplayOff()
    except Exception:  # noqa: BLE001
        pass


def main():
    _quiet_vtk()
    if "--selftest" in sys.argv:
        code = selftest()
        log = os.environ.get("SELFTEST_LOG")
        if log:
            with open(log, "w") as f:
                f.write("OK" if code == 0 else "FEHLER")
        sys.exit(code)

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("3DVergleich.MK1")
        except Exception:  # noqa: BLE001
            pass

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QSurfaceFormat
    from PySide6.QtWidgets import QApplication

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    fmt = QSurfaceFormat.defaultFormat()
    QSurfaceFormat.setDefaultFormat(fmt)

    from .ui.main_window import MainWindow
    from .ui.theme import STYLESHEET
    from .version import APP_NAME

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    w = MainWindow(resource(os.path.join("assets", "icon.png")))
    w.show()
    w.viewer.start()
    # Dateien als Startparameter (z. B. per "Öffnen mit" oder Drag auf die exe)
    files = [a for a in sys.argv[1:] if os.path.isfile(a)]
    if files:
        w._load("A", files[0])
    if len(files) > 1:
        w._load("B", files[1])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

# -*- mode: python ; coding: utf-8 -*-
# PyInstaller-Spezifikation fuer 3D-Vergleich-MK1 (eine einzelne exe)

hiddenimports = [
    "vtkmodules.vtkCommonCore",
    "vtkmodules.vtkCommonDataModel",
    "vtkmodules.vtkCommonExecutionModel",
    "vtkmodules.vtkCommonMath",
    "vtkmodules.vtkCommonTransforms",
    "vtkmodules.vtkFiltersCore",
    "vtkmodules.vtkFiltersGeneral",
    "vtkmodules.vtkFiltersModeling",
    "vtkmodules.vtkFiltersSources",
    "vtkmodules.vtkIOGeometry",
    "vtkmodules.vtkIOImage",
    "vtkmodules.vtkIOLegacy",
    "vtkmodules.vtkIOPLY",
    "vtkmodules.vtkIOXML",
    "vtkmodules.vtkInteractionStyle",
    "vtkmodules.vtkInteractionWidgets",
    "vtkmodules.vtkRenderingAnnotation",
    "vtkmodules.vtkRenderingCore",
    "vtkmodules.vtkRenderingFreeType",
    "vtkmodules.vtkRenderingOpenGL2",
    "vtkmodules.vtkRenderingUI",
    "vtkmodules.util.numpy_support",
    "vtkmodules.qt",
    "vtkmodules.qt.QVTKRenderWindowInteractor",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "scipy.spatial",
    "scipy.spatial._ckdtree",
]

excludes = [
    "tkinter", "matplotlib", "pandas", "IPython", "pytest",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtQuickWidgets", "PySide6.Qt3DCore",
    "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtPdf",
    "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtSql", "PySide6.QtTest",
    "vtkmodules.web", "wslink",
]

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    datas=[("assets", "assets")],
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="3D-Vergleich-MK1",
    debug=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    icon="assets/icon.ico",
)

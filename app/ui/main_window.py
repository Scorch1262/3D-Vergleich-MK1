"""Hauptfenster: Dateien, Ausrichtung, Darstellung, Messen, Export."""
from __future__ import annotations

import csv
import datetime as _dt
import os

import numpy as np
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QIcon, QKeySequence, QShortcut, QAction
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QSlider, QSplitter, QStatusBar, QToolButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget, QMenu,
)

from ..core.deviation import CompareResult, run_compare, signed_distance, closest_points
from ..core.geometry import Geometry
from ..core.io_loader import FILE_FILTER, ALL_EXT, LoadError, load_file, save_geometry
from ..version import APP_NAME, APP_TITLE, APP_VERSION
from . import theme
from .viewer import Viewer
from .widgets import ColorBar, Histogram, Section, caption

MODES = [
    ("map", "Farbkarte (Abweichung)"),
    ("traffic", "Toleranz-Ampel"),
    ("outside", "Nur außerhalb Toleranz"),
    ("overlay", "Überlagerung (Transparenz)"),
    ("vectors", "Abweichungsvektoren"),
]


# --------------------------------------------------------------------- Threads
class LoadWorker(QThread):
    done = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, slot, path):
        super().__init__()
        self.slot, self.path = slot, path

    def run(self):
        try:
            geo = load_file(self.path)
            geo.prepare_display()
            self.done.emit(self.slot, geo)
        except LoadError as e:
            self.failed.emit(self.slot, str(e))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(self.slot, f"{type(e).__name__}: {e}")


class CompareWorker(QThread):
    progress = Signal(int, str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, a, b, mode, scale, quality):
        super().__init__()
        self.args = (a, b, mode, scale, quality)

    def run(self):
        try:
            a, b, mode, scale, quality = self.args
            res = run_compare(a, b, mode, scale, quality, progress=lambda v, t: self.progress.emit(v, t))
            self.done.emit(res)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"{type(e).__name__}: {e}")


# ------------------------------------------------------------------ Slot-Feld
class SlotBox(QFrame):
    file_dropped = Signal(str, str)
    open_clicked = Signal(str)

    def __init__(self, slot: str, title: str):
        super().__init__()
        self.slot = slot
        self.setObjectName("Panel")
        self.setAcceptDrops(True)
        g = QGridLayout(self)
        g.setContentsMargins(9, 8, 9, 8)
        g.setHorizontalSpacing(6)
        g.setVerticalSpacing(3)
        head = QLabel(f"{slot} · {title}")
        head.setObjectName("SlotA" if slot == "A" else "SlotB")
        self.btn = QPushButton("Öffnen …")
        self.btn.setFixedWidth(84)
        self.btn.clicked.connect(lambda: self.open_clicked.emit(self.slot))
        self.name = QLabel("– keine Datei –")
        self.name.setObjectName("Mono")
        self.name.setWordWrap(True)
        self.info = QLabel("")
        self.info.setObjectName("MonoDim")
        self.info.setWordWrap(True)
        g.addWidget(head, 0, 0)
        g.addWidget(self.btn, 0, 1, Qt.AlignRight)
        g.addWidget(self.name, 1, 0, 1, 2)
        g.addWidget(self.info, 2, 0, 1, 2)

    def set_geo(self, geo: Geometry | None, loading: bool = False):
        if loading:
            self.name.setText("lädt …")
            self.info.setText("")
            return
        if geo is None:
            self.name.setText("– keine Datei –")
            self.info.setText("")
        else:
            self.name.setText(geo.name)
            self.info.setText(geo.info_text())

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        urls = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if urls:
            self.file_dropped.emit(self.slot, urls[0])
            e.acceptProposedAction()


# --------------------------------------------------------------- Hauptfenster
class MainWindow(QMainWindow):
    def __init__(self, icon_path: str | None = None):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME}  v{APP_VERSION}")
        if icon_path and os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.resize(1560, 940)
        self.setAcceptDrops(True)
        self.geo: dict[str, Geometry | None] = {"A": None, "B": None}
        self.result: CompareResult | None = None
        self.loaders: dict[str, LoadWorker] = {}
        self.worker: CompareWorker | None = None
        self.measurements: list[dict] = []
        self._first_view = True
        self._build()
        self._update_enabled()

    # ================================================================= UI
    def _build(self):
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self._header())

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(self._sidebar())
        split.addWidget(self._center())
        split.addWidget(self._rightbar())
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        split.setSizes([345, 860, 385])
        v.addWidget(split, 1)

        sb = QStatusBar()
        self.setStatusBar(sb)
        self.status = QLabel("Bereit.")
        self.prog = QProgressBar()
        self.prog.setRange(0, 100)
        self.prog.setFixedWidth(240)
        self.prog.setVisible(False)
        sb.addWidget(self.status, 1)
        sb.addPermanentWidget(self.prog)
        ver = QLabel(f"v{APP_VERSION}")
        sb.addPermanentWidget(ver)

        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self._escape)
        QShortcut(QKeySequence(Qt.Key_Delete), self, activated=self._delete_selected_measure)
        QShortcut(QKeySequence("F"), self, activated=lambda: self.viewer.reset_camera())
        QShortcut(QKeySequence("Ctrl+O"), self, activated=lambda: self._open_dialog("A" if self.geo["A"] is None else "B"))

    def _header(self):
        h = QFrame()
        h.setObjectName("Header")
        h.setFixedHeight(48)
        lay = QHBoxLayout(h)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(10)
        t = QLabel("3D-VERGLEICH")
        t.setObjectName("Title")
        s = QLabel("// MK1  ·  ABWEICHUNGSANALYSE STL / PUNKTWOLKE")
        s.setObjectName("TitleSub")
        lay.addWidget(t)
        lay.addWidget(s)
        lay.addStretch(1)
        self.chip_a = QLabel("A: –")
        self.chip_a.setObjectName("Chip")
        self.chip_b = QLabel("B: –")
        self.chip_b.setObjectName("Chip")
        self.chip_state = QLabel("BEREIT")
        self.chip_state.setObjectName("ChipLive")
        for w in (self.chip_a, self.chip_b, self.chip_state):
            lay.addWidget(w)
        ver = QLabel(f"v{APP_VERSION}")
        ver.setObjectName("Chip")
        lay.addWidget(ver)
        return h

    def _set_state(self, txt: str, busy: bool = False):
        self.chip_state.setText(txt)
        self.chip_state.setObjectName("ChipBusy" if busy else "ChipLive")
        self.chip_state.style().unpolish(self.chip_state)
        self.chip_state.style().polish(self.chip_state)

    def _sidebar(self):
        frame = QFrame()
        frame.setObjectName("SideBar")
        frame.setMaximumWidth(440)
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        inner = QWidget()
        scroll.setWidget(inner)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(10, 10, 14, 10)
        lay.setSpacing(8)

        # ---- Dateien
        sec = Section("Dateien", True)
        self.slot_box = {"A": SlotBox("A", "REFERENZ"), "B": SlotBox("B", "PRÜFOBJEKT")}
        for sb in self.slot_box.values():
            sb.open_clicked.connect(self._open_dialog)
            sb.file_dropped.connect(self._load)
            sec.add(sb)
        row = QHBoxLayout()
        self.btn_swap = QPushButton("⇄  Tauschen")
        self.btn_swap.clicked.connect(self._swap)
        self.btn_clear = QPushButton("✕  Leeren")
        self.btn_clear.clicked.connect(self._clear_all)
        row.addWidget(self.btn_swap)
        row.addWidget(self.btn_clear)
        sec.add(row)
        self.chk_auto = QCheckBox("Nach dem Laden automatisch vergleichen")
        self.chk_auto.setChecked(True)
        sec.add(self.chk_auto)
        hint = QLabel("Dateien auch per Drag & Drop ins Fenster ziehen (zwei auf einmal = A und B).")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        sec.add(hint)
        lay.addWidget(sec)

        self.btn_compare = QPushButton("AUSRICHTEN && VERGLEICHEN")
        self.btn_compare.setObjectName("Primary")
        self.btn_compare.clicked.connect(self._compare)
        lay.addWidget(self.btn_compare)

        # ---- Ausrichtung
        sec = Section("Ausrichtung", False)
        sec.add(caption("Verfahren"))
        self.cmb_align = QComboBox()
        self.cmb_align.addItem("Automatisch (grob + fein)", "auto")
        self.cmb_align.addItem("Nur Feinausrichtung (ICP)", "fine")
        self.cmb_align.addItem("Keine (aktuelle Lage)", "none")
        sec.add(self.cmb_align)
        sec.add(caption("Genauigkeit / Stichproben"))
        self.cmb_quality = QComboBox()
        self.cmb_quality.addItem("Schnell (50 000)", "Schnell")
        self.cmb_quality.addItem("Normal (200 000)", "Normal")
        self.cmb_quality.addItem("Genau (800 000)", "Genau")
        self.cmb_quality.setCurrentIndex(1)
        sec.add(self.cmb_quality)
        self.chk_scale = QCheckBox("Skalierung zulassen (z. B. mm ↔ inch)")
        self.chk_scale.setToolTip("Nur bei vollständigen Objekten sinnvoll – bei Teil-Scans ist die "
                                  "Größe nicht eindeutig bestimmbar.")
        sec.add(self.chk_scale)
        self.btn_reset_align = QPushButton("Ausrichtung zurücksetzen")
        self.btn_reset_align.clicked.connect(self._reset_alignment)
        sec.add(self.btn_reset_align)
        sec.add(caption("Ergebnis Transformation (B → A)"))
        self.lbl_transform = QLabel("–")
        self.lbl_transform.setObjectName("Mono")
        self.lbl_transform.setWordWrap(True)
        self.lbl_transform.setTextInteractionFlags(Qt.TextSelectableByMouse)
        sec.add(self.lbl_transform)
        lay.addWidget(sec)

        # ---- Toleranz & Darstellung
        sec = Section("Toleranz & Darstellung", True)
        g = QGridLayout()
        g.setHorizontalSpacing(6)
        g.addWidget(caption("Toleranz ±"), 0, 0)
        g.addWidget(caption("Einheit"), 0, 1)
        self.spin_tol = QDoubleSpinBox()
        self.spin_tol.setDecimals(4)
        self.spin_tol.setRange(0.0001, 100000)
        self.spin_tol.setSingleStep(0.01)
        self.spin_tol.setValue(0.1)
        self.spin_tol.valueChanged.connect(self._tol_changed)
        self.cmb_unit = QComboBox()
        for u in ("mm", "µm", "cm", "m", "inch", "–"):
            self.cmb_unit.addItem(u)
        self.cmb_unit.currentIndexChanged.connect(self._refresh_panels)
        g.addWidget(self.spin_tol, 1, 0)
        g.addWidget(self.cmb_unit, 1, 1)
        sec.add(g)
        sec.add(caption("Darstellung"))
        self.cmb_mode = QComboBox()
        for key, name in MODES:
            self.cmb_mode.addItem(name, key)
        self.cmb_mode.currentIndexChanged.connect(self.update_view)
        sec.add(self.cmb_mode)
        sec.add(caption("Farbkarte auf"))
        self.cmb_target = QComboBox()
        self.cmb_target.addItem("B · Prüfobjekt (B gegenüber A)", "B")
        self.cmb_target.addItem("A · Referenz (B gegenüber A)", "A")
        self.cmb_target.currentIndexChanged.connect(self._target_changed)
        sec.add(self.cmb_target)
        self.chk_abs = QCheckBox("Betrag (ohne Vorzeichen)")
        self.chk_abs.toggled.connect(self.update_view)
        sec.add(self.chk_abs)
        g = QGridLayout()
        self.chk_autorange = QCheckBox("Farbbereich automatisch")
        self.chk_autorange.setChecked(True)
        self.chk_autorange.toggled.connect(self.update_view)
        self.spin_range = QDoubleSpinBox()
        self.spin_range.setDecimals(4)
        self.spin_range.setRange(0.0001, 100000)
        self.spin_range.setValue(0.5)
        self.spin_range.setPrefix("± ")
        self.spin_range.valueChanged.connect(self.update_view)
        g.addWidget(self.chk_autorange, 0, 0)
        g.addWidget(self.spin_range, 0, 1)
        sec.add(g)

        sec.add(caption("Sichtbarkeit / Deckkraft"))
        g = QGridLayout()
        self.chk_vis = {}
        self.sld_op = {}
        for i, (slot, val) in enumerate((("A", 35), ("B", 100))):
            c = QCheckBox(f"{slot} anzeigen")
            c.setChecked(True)
            c.toggled.connect(self.update_view)
            s = QSlider(Qt.Horizontal)
            s.setRange(5, 100)
            s.setValue(val)
            s.valueChanged.connect(self.update_view)
            self.chk_vis[slot] = c
            self.sld_op[slot] = s
            g.addWidget(c, i, 0)
            g.addWidget(s, i, 1)
        g.addWidget(QLabel("Punktgröße"), 2, 0)
        self.sld_psize = QSlider(Qt.Horizontal)
        self.sld_psize.setRange(1, 10)
        self.sld_psize.setValue(3)
        self.sld_psize.valueChanged.connect(self.update_view)
        g.addWidget(self.sld_psize, 2, 1)
        g.addWidget(QLabel("Vektor-Überhöhung"), 3, 0)
        self.spin_vec = QDoubleSpinBox()
        self.spin_vec.setRange(1, 1000)
        self.spin_vec.setDecimals(0)
        self.spin_vec.setValue(10)
        self.spin_vec.setSuffix(" ×")
        self.spin_vec.valueChanged.connect(self.update_view)
        g.addWidget(self.spin_vec, 3, 1)
        sec.add(g)
        lay.addWidget(sec)

        # ---- Messen
        sec = Section("Messen", False)
        t = QLabel("Werkzeug oben über der Ansicht wählen, dann Punkte anklicken. Messungen "
                   "funktionieren innerhalb von A oder B und zwischen A und B. Ziehen dreht weiter "
                   "die Ansicht, Esc bricht ab.")
        t.setObjectName("Hint")
        t.setWordWrap(True)
        sec.add(t)
        self.chk_snap = QCheckBox("Fang auf nächsten Datenpunkt")
        self.chk_snap.setChecked(False)
        self.chk_snap.toggled.connect(lambda on: setattr(self.viewer, "snap", on))
        sec.add(self.chk_snap)
        row = QHBoxLayout()
        b1 = QPushButton("Letzte löschen")
        b1.clicked.connect(self._delete_last_measure)
        b2 = QPushButton("Alle löschen")
        b2.clicked.connect(self._clear_measures)
        row.addWidget(b1)
        row.addWidget(b2)
        sec.add(row)
        lay.addWidget(sec)

        # ---- Export
        sec = Section("Export", False)
        self.btn_shot = QPushButton("Screenshot speichern (PNG)")
        self.btn_shot.clicked.connect(self._export_screenshot)
        self.btn_report = QPushButton("Bericht speichern (CSV)")
        self.btn_report.clicked.connect(self._export_report)
        self.btn_points = QPushButton("Abweichung je Punkt (CSV)")
        self.btn_points.clicked.connect(self._export_points)
        self.btn_save_b = QPushButton("Ausgerichtetes B speichern …")
        self.btn_save_b.clicked.connect(self._export_aligned)
        for b in (self.btn_shot, self.btn_report, self.btn_points, self.btn_save_b):
            sec.add(b)
        lay.addWidget(sec)

        lay.addStretch(1)
        for cmb in inner.findChildren(QComboBox):
            cmb.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            cmb.setMinimumContentsLength(8)
        frame.setMinimumWidth(inner.minimumSizeHint().width() + 12)
        return frame

    def _center(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        bar = QFrame()
        bar.setObjectName("Header")
        bar.setFixedHeight(40)
        h = QHBoxLayout(bar)
        h.setContentsMargins(8, 4, 8, 4)
        h.setSpacing(5)
        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(True)
        self.tools = {}
        for key, txt, tip in (
            ("none", "⟲  DREHEN", "Ansicht drehen / verschieben / zoomen"),
            ("dist", "↔  DISTANZ", "Abstand zwischen zwei Punkten (in A, in B oder A↔B)"),
            ("angle", "∠  WINKEL", "Winkel über drei Punkte (Scheitel = 2. Punkt)"),
            ("dev", "Δ  ABWEICHUNG", "Abweichung an einem Punkt zum jeweils anderen Objekt"),
            ("coord", "⌖  KOORDINATE", "Koordinate eines Punktes anzeigen"),
        ):
            b = QToolButton()
            b.setObjectName("Tool")
            b.setText(txt)
            b.setToolTip(tip)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self._set_tool(k))
            self.tool_group.addButton(b)
            self.tools[key] = b
            h.addWidget(b)
        self.tools["none"].setChecked(True)
        h.addStretch(1)
        vb = QToolButton()
        vb.setObjectName("Tool")
        vb.setText("ANSICHT ▾")
        vb.setPopupMode(QToolButton.InstantPopup)
        vmenu = QMenu(vb)
        for key, txt in (("iso", "Isometrisch"), ("front", "Vorne"), ("back", "Hinten"), ("top", "Oben"),
                         ("bottom", "Unten"), ("right", "Rechts"), ("left", "Links")):
            act = vmenu.addAction(txt)
            act.triggered.connect(lambda _=False, k=key: self.viewer.view(k))
        vmenu.addSeparator()
        act_fit = vmenu.addAction("Einpassen  (F)")
        act_fit.triggered.connect(lambda: self.viewer.reset_camera())
        self.act_par = vmenu.addAction("Parallelprojektion")
        self.act_par.setCheckable(True)
        self.act_par.toggled.connect(lambda on: self.viewer.set_parallel(on))
        vb.setMenu(vmenu)
        h.addWidget(vb)
        b = QToolButton()
        b.setObjectName("Tool")
        b.setText("⤢")
        b.setToolTip("Ansicht einpassen (Taste F)")
        b.clicked.connect(lambda: self.viewer.reset_camera())
        h.addWidget(b)
        v.addWidget(bar)
        self.viewer = Viewer()
        self.viewer.dev_lookup = self._dev_lookup
        self.viewer.snap = False
        self.viewer.signals.measure_done.connect(self._on_measure)
        self.viewer.signals.measure_progress.connect(lambda t: self.status.setText(t))
        v.addWidget(self.viewer, 1)
        return w

    def _rightbar(self):
        frame = QFrame()
        frame.setObjectName("RightBar")
        frame.setMaximumWidth(460)
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        inner = QWidget()
        scroll.setWidget(inner)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        sec = Section("Übereinstimmung", True)
        self.lbl_match = QLabel("--.- %")
        self.lbl_match.setObjectName("KpiValue")
        self.lbl_match.setAlignment(Qt.AlignCenter)
        sec.add(self.lbl_match)
        self.lbl_match_sub = QLabel("Noch kein Vergleich")
        self.lbl_match_sub.setObjectName("MonoDim")
        self.lbl_match_sub.setAlignment(Qt.AlignCenter)
        sec.add(self.lbl_match_sub)
        g = QGridLayout()
        g.setVerticalSpacing(1)
        g.addWidget(caption("B in Toleranz zu A"), 0, 0)
        g.addWidget(caption("A abgedeckt durch B"), 0, 1)
        self.lbl_ba = QLabel("–")
        self.lbl_ba.setObjectName("KpiSmall")
        self.lbl_ab = QLabel("–")
        self.lbl_ab.setObjectName("KpiSmall")
        g.addWidget(self.lbl_ba, 1, 0)
        g.addWidget(self.lbl_ab, 1, 1)
        sec.add(g)
        lay.addWidget(sec)

        sec = Section("Verteilung", True)
        self.colorbar = ColorBar()
        sec.add(self.colorbar)
        self.hist = Histogram()
        sec.add(self.hist)
        lay.addWidget(sec)

        sec = Section("Statistik", True)
        self.tree_stats = QTreeWidget()
        self.tree_stats.setHeaderLabels(["KENNWERT", "B → A", "A ← B"])
        self.tree_stats.setRootIsDecorated(False)
        self.tree_stats.setAlternatingRowColors(True)
        self.tree_stats.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree_stats.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree_stats.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tree_stats.header().setStretchLastSection(False)
        self.tree_stats.setMinimumHeight(292)
        sec.add(self.tree_stats)
        self.lbl_sign = QLabel("")
        self.lbl_sign.setObjectName("Hint")
        self.lbl_sign.setWordWrap(True)
        sec.add(self.lbl_sign)
        lay.addWidget(sec)

        sec = Section("Messungen", True)
        self.tree_meas = QTreeWidget()
        self.tree_meas.setHeaderLabels(["#", "ART", "OBJEKT", "WERT"])
        self.tree_meas.setRootIsDecorated(False)
        self.tree_meas.setAlternatingRowColors(True)
        self.tree_meas.header().setSectionResizeMode(3, QHeaderView.Stretch)
        self.tree_meas.setColumnWidth(0, 30)
        self.tree_meas.setColumnWidth(1, 82)
        self.tree_meas.setColumnWidth(2, 62)
        self.tree_meas.setMinimumHeight(170)
        self.tree_meas.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree_meas.customContextMenuRequested.connect(self._meas_menu)
        sec.add(self.tree_meas)
        lay.addWidget(sec)
        lay.addStretch(1)
        frame.setMinimumWidth(inner.minimumSizeHint().width() + 12)
        return frame

    # ============================================================ Dateien
    def _open_dialog(self, slot: str):
        path, _ = QFileDialog.getOpenFileName(self, f"Datei für {slot} öffnen", "", FILE_FILTER)
        if path:
            self._load(slot, path)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        paths = [p for p in paths if os.path.splitext(p)[1].lower() in ALL_EXT] or paths
        if not paths:
            return
        if len(paths) >= 2:
            self._load("A", paths[0])
            self._load("B", paths[1])
        elif self.geo["A"] is None and "A" not in self.loaders:
            self._load("A", paths[0])
        else:
            self._load("B", paths[0])
        e.acceptProposedAction()

    def _load(self, slot: str, path: str):
        if self.worker is not None:
            self.status.setText("Bitte warten, Vergleich läuft …")
            return
        w = LoadWorker(slot, path)
        w.done.connect(self._loaded)
        w.failed.connect(self._load_failed)
        w.finished.connect(lambda s=slot: self._loader_finished(s))
        self.loaders[slot] = w
        self.slot_box[slot].set_geo(None, loading=True)
        self.status.setText(f"Lade {os.path.basename(path)} …")
        self._set_state("LÄDT", True)
        self.prog.setVisible(True)
        self.prog.setRange(0, 0)
        self._update_enabled()
        w.start()

    def _loader_finished(self, slot):
        self.loaders.pop(slot, None)
        if not self.loaders:
            self.prog.setVisible(False)
            self.prog.setRange(0, 100)
            self._set_state("ERGEBNIS" if self.result else "BEREIT")
            self._update_enabled()
            if self.chk_auto.isChecked() and self.geo["A"] and self.geo["B"] and self.result is None:
                self._compare()

    def _loaded(self, slot, geo: Geometry):
        self.geo[slot] = geo
        self.result = None
        other = "B" if slot == "A" else "A"
        if self.geo["B"] is not None:
            self.geo["B"].set_transform(np.eye(4))
            if other == "B":
                self.viewer.refresh_points("B")
        self.viewer.set_geometry(slot, geo)
        self.slot_box[slot].set_geo(geo)
        chip = self.chip_a if slot == "A" else self.chip_b
        chip.setText(f"{slot}: {geo.name[:28]}")
        self._clear_measures()
        self.status.setText(f"{geo.name} geladen.")
        self.cmb_mode.setCurrentIndex(3)
        self.update_view()
        self._refresh_panels()
        self.viewer.reset_camera()

    def _load_failed(self, slot, msg):
        self.slot_box[slot].set_geo(self.geo[slot])
        QMessageBox.warning(self, "Datei konnte nicht geladen werden", msg)
        self.status.setText("Laden fehlgeschlagen.")

    def _swap(self):
        if self.worker or self.loaders:
            return
        self.geo["A"], self.geo["B"] = self.geo["B"], self.geo["A"]
        for g in self.geo.values():
            if g is not None:
                g.set_transform(np.eye(4))
        self.result = None
        for s in ("A", "B"):
            self.viewer.set_geometry(s, None)
        for s in ("A", "B"):
            self.viewer.set_geometry(s, self.geo[s])
            self.slot_box[s].set_geo(self.geo[s])
            chip = self.chip_a if s == "A" else self.chip_b
            chip.setText(f"{s}: {self.geo[s].name[:28]}" if self.geo[s] else f"{s}: –")
        self._clear_measures()
        self.cmb_mode.setCurrentIndex(3)
        self.update_view()
        self._refresh_panels()
        if self.chk_auto.isChecked() and self.geo["A"] and self.geo["B"]:
            self._compare()

    def _clear_all(self):
        if self.worker or self.loaders:
            return
        for s in ("A", "B"):
            self.geo[s] = None
            self.viewer.set_geometry(s, None)
            self.slot_box[s].set_geo(None)
        self.chip_a.setText("A: –")
        self.chip_b.setText("B: –")
        self.result = None
        self._clear_measures()
        self.viewer.set_vectors(None)
        self._refresh_panels()
        self._update_enabled()
        self.viewer.render()

    # ========================================================== Vergleich
    def _compare(self):
        a, b = self.geo["A"], self.geo["B"]
        if a is None or b is None or self.worker is not None or self.loaders:
            return
        self._set_tool("none")
        self.viewer.cancel_pending()
        self.worker = CompareWorker(a, b, self.cmb_align.currentData(), self.chk_scale.isChecked(),
                                    self.cmb_quality.currentData())
        self.worker.progress.connect(self._cmp_progress)
        self.worker.done.connect(self._cmp_done)
        self.worker.failed.connect(self._cmp_failed)
        self.worker.finished.connect(self._cmp_finished)
        self.prog.setRange(0, 100)
        self.prog.setValue(0)
        self.prog.setVisible(True)
        self._set_state("RECHNET", True)
        self._update_enabled()
        self.worker.start()

    def _cmp_progress(self, v, t):
        self.prog.setValue(v)
        self.status.setText(t + " …")

    def _cmp_done(self, res: CompareResult):
        self.result = res
        self.viewer.refresh_points("B")
        self._clear_measures()
        if self.cmb_mode.currentData() == "overlay":
            self.cmb_mode.setCurrentIndex(0)
        self.lbl_transform.setText(res.transform_text())
        self.update_view()
        self._refresh_panels()
        if self._first_view:
            self.viewer.view("iso")
            self._first_view = False
        tot, _, _ = res.match(self.spin_tol.value())
        self.status.setText(f"Vergleich fertig – Übereinstimmung {tot:.2f} % bei ±{self.spin_tol.value():g} "
                            f"{self.cmb_unit.currentText()}.")

    def _cmp_failed(self, msg):
        QMessageBox.critical(self, "Vergleich fehlgeschlagen", msg)
        self.status.setText("Vergleich fehlgeschlagen.")

    def _cmp_finished(self):
        self.worker = None
        self.prog.setVisible(False)
        self._set_state("ERGEBNIS" if self.result else "BEREIT")
        self._update_enabled()

    def _reset_alignment(self):
        if self.worker or self.geo["B"] is None:
            return
        self.geo["B"].set_transform(np.eye(4))
        self.result = None
        self.viewer.refresh_points("B")
        self._clear_measures()
        self.lbl_transform.setText("–")
        self.cmb_mode.setCurrentIndex(3)
        self.update_view()
        self._refresh_panels()
        self._set_state("BEREIT")

    def _update_enabled(self):
        busy = self.worker is not None or bool(self.loaders)
        both = self.geo["A"] is not None and self.geo["B"] is not None
        self.btn_compare.setEnabled(both and not busy)
        self.btn_swap.setEnabled(not busy and (self.geo["A"] or self.geo["B"]) is not None)
        self.btn_clear.setEnabled(not busy)
        for b in self.slot_box.values():
            b.btn.setEnabled(not busy)
        has = self.result is not None
        self.btn_report.setEnabled(has)
        self.btn_points.setEnabled(has)
        self.btn_save_b.setEnabled(self.geo["B"] is not None and not busy)
        for k, b in self.tools.items():
            b.setEnabled(not busy and (k != "dev" or has))

    # ========================================================= Darstellung
    def _unit(self):
        u = self.cmb_unit.currentText()
        return "" if u == "–" else u

    def _range(self, d_samples):
        tol = self.spin_tol.value()
        if not self.chk_autorange.isChecked():
            lim = self.spin_range.value()
        else:
            lim = float(np.percentile(np.abs(d_samples), 98)) if len(d_samples) else tol
            lim = max(lim, tol * 1.5)
            self.spin_range.blockSignals(True)
            self.spin_range.setValue(lim)
            self.spin_range.blockSignals(False)
        if self.chk_abs.isChecked():
            return 0.0, lim
        return -lim, lim

    def update_view(self, *_):
        if not hasattr(self, "viewer"):
            return
        mode = self.cmb_mode.currentData()
        res = self.result
        tol = self.spin_tol.value()
        target = self.cmb_target.currentData()
        op = {s: self.sld_op[s].value() / 100 for s in ("A", "B")}
        vis = {s: self.chk_vis[s].isChecked() for s in ("A", "B")}
        psize = float(self.sld_psize.value())
        self.viewer.set_vectors(None)
        base = {"A": theme.COLOR_A, "B": theme.COLOR_B}
        if res is None or mode == "overlay":
            for s in ("A", "B"):
                self.viewer.set_appearance(s, None, base[s], op[s], vis[s], psize)
            self.colorbar.setVisible(False)
            self.viewer.render()
            return
        self.colorbar.setVisible(True)
        absmode = self.chk_abs.isChecked()
        dsamp = res.dev_samples_b if target == "B" else res.dev_samples_a
        vmin, vmax = self._range(dsamp)
        dev = res.dev_b_vertices if target == "B" else res.dev_a_vertices
        other = "A" if target == "B" else "B"
        if absmode:
            dev = np.abs(dev)
        if mode == "vectors":
            self.viewer.set_appearance("A", None, theme.GHOST, op["A"], vis["A"], psize)
            self.viewer.set_appearance("B", None, base["B"], min(op["B"], 0.3), vis["B"], psize)
            sel = np.abs(res.vec_dev) > tol * 0.5
            if not sel.any():
                sel[:] = True
            vd = np.abs(res.vec_dev[sel]) if absmode else res.vec_dev[sel]
            cols = theme.colormap(vd, vmin, vmax)
            self.viewer.set_vectors(res.vec_from[sel], res.vec_to[sel], cols, self.spin_vec.value())
            self.colorbar.set_range(vmin, vmax, "map", tol)
        else:
            if mode == "map":
                cols = theme.colormap(dev, vmin, vmax)
                self.colorbar.set_range(vmin, vmax, "map", tol)
            elif mode == "traffic":
                cols = np.empty((len(dev), 3), np.uint8)
                cols[:] = theme.hex_rgb(theme.GREEN)
                cols[dev > tol] = theme.hex_rgb(theme.RED)
                cols[dev < -tol] = theme.hex_rgb(theme.BLUE)
                self.colorbar.set_range(vmin, vmax, "traffic", tol)
            else:  # outside
                cols = theme.colormap(dev, vmin, vmax)
                cols[np.abs(dev) <= tol] = theme.hex_rgb("#4a5562")
                self.colorbar.set_range(vmin, vmax, "map", tol)
            self.viewer.set_appearance(target, cols, None, op[target], vis[target], psize)
            self.viewer.set_appearance(other, None, theme.GHOST, op[other], vis[other], psize)
        self.hist.set_data(np.abs(dsamp) if absmode else dsamp, tol, vmin, vmax, self._unit())
        self.viewer.render()

    def _target_changed(self, *_):
        target = self.cmb_target.currentData()
        other = "A" if target == "B" else "B"
        for s, v in ((target, 100), (other, 35)):
            self.sld_op[s].blockSignals(True)
            self.sld_op[s].setValue(v)
            self.sld_op[s].blockSignals(False)
        self.update_view()

    def _tol_changed(self, *_):
        self.update_view()
        self._refresh_panels()

    def _refresh_panels(self, *_):
        res = self.result
        unit = self._unit()
        tol = self.spin_tol.value()
        self.tree_stats.clear()
        if res is None:
            self.lbl_match.setText("--.- %")
            self.lbl_match_sub.setText("Noch kein Vergleich")
            self.lbl_ba.setText("–")
            self.lbl_ab.setText("–")
            self.hist.set_data(None, tol, -1, 1)
            self.lbl_sign.setText("")
            self.colorbar.setVisible(False)
            return
        tot, ba, ab = res.match(tol)
        self.lbl_match.setText(f"{tot:.1f} %")
        col = theme.TEAL if tot >= 95 else (theme.AMBER if tot >= 80 else theme.RED)
        self.lbl_match.setStyleSheet(f"color: {col};")
        self.lbl_match_sub.setText(f"bei Toleranz ±{tol:g} {unit}")
        self.lbl_ba.setText(f"{ba:.2f} %")
        self.lbl_ab.setText(f"{ab:.2f} %")
        sb, sa = res.stats_b, res.stats_a
        db, da = res.dev_samples_b, res.dev_samples_a

        def frac(d, cond):
            return f"{np.mean(cond(d)) * 100:.2f} %" if len(d) else "–"

        rows = [
            ("Mittelwert", f"{sb.mean:+.4f}", f"{sa.mean:+.4f}"),
            ("Mittel |Δ|", f"{sb.mean_abs:.4f}", f"{sa.mean_abs:.4f}"),
            ("Std.-Abw.", f"{sb.std:.4f}", f"{sa.std:.4f}"),
            ("RMS", f"{sb.rms:.4f}", f"{sa.rms:.4f}"),
            ("Minimum", f"{sb.min:+.4f}", f"{sa.min:+.4f}"),
            ("Maximum", f"{sb.max:+.4f}", f"{sa.max:+.4f}"),
            ("Max |Δ|", f"{sb.max_abs:.4f}", f"{sa.max_abs:.4f}"),
            ("5 % Quantil", f"{sb.p05:+.4f}", f"{sa.p05:+.4f}"),
            ("95 % Quantil", f"{sb.p95:+.4f}", f"{sa.p95:+.4f}"),
            ("In Toleranz", frac(db, lambda d: np.abs(d) <= tol), frac(da, lambda d: np.abs(d) <= tol)),
            ("Über +Tol.", frac(db, lambda d: d > tol), frac(da, lambda d: d > tol)),
            ("Unter −Tol.", frac(db, lambda d: d < -tol), frac(da, lambda d: d < -tol)),
            ("Stichproben", f"{sb.n:,}".replace(",", "."), f"{sa.n:,}".replace(",", ".")),
        ]
        for r in rows:
            it = QTreeWidgetItem(list(r))
            it.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
            it.setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)
            self.tree_stats.addTopLevelItem(it)
        note = (f"Werte in {unit or 'Datei-Einheiten'}. Positiv = B liegt außerhalb von A "
                f"(Materialüberschuss), negativ = innerhalb.")
        if res.sign_estimated:
            note += " Bei Punktwolken wird das Vorzeichen über geschätzte Normalen bestimmt."
        self.lbl_sign.setText(note)
        self.colorbar.setVisible(self.cmb_mode.currentData() != "overlay")

    # ============================================================== Messen
    def _set_tool(self, key):
        if key in self.tools:
            self.tools[key].setChecked(True)
        self.viewer.set_measure_mode(key)
        names = {"none": "Ansicht drehen.", "dist": "Distanz: zwei Punkte anklicken.",
                 "angle": "Winkel: drei Punkte anklicken (2. Punkt = Scheitel).",
                 "dev": "Abweichung: Punkt auf A oder B anklicken.",
                 "coord": "Koordinate: Punkt anklicken."}
        self.status.setText(names.get(key, ""))

    def _escape(self):
        if self.viewer.pending:
            self.viewer.cancel_pending()
        else:
            self._set_tool("none")

    def _dev_lookup(self, slot, p):
        if self.result is None:
            return None
        p = np.asarray(p, float)[None, :]
        if slot == "B":
            other = self.geo["A"]
            val = float(signed_distance(other, p)[0])
        else:
            other = self.geo["B"]
            val = -float(signed_distance(other, p)[0])
        q = closest_points(other, p)[0]
        return val, q

    def _on_measure(self, m: dict):
        unit = self._unit()
        self.measurements.append(m)
        if m["type"] == "Winkel":
            val = f"{m['value']:.3f}°"
        elif m["type"] == "Koordinate":
            p = m["points"][0]
            val = f"{p[0]:.3f}; {p[1]:.3f}; {p[2]:.3f}"
        elif m["type"] == "Abweichung":
            val = f"{m['value']:+.4f} {unit}"
        else:
            dx, dy, dz = m["delta"]
            val = f"{m['value']:.4f} {unit}"
            m["extra"] = f"dX {dx:+.3f}  dY {dy:+.3f}  dZ {dz:+.3f}"
        it = QTreeWidgetItem([str(m["id"]), m["type"], m["slots"], val])
        it.setData(0, Qt.UserRole, m["id"])
        tip = "\n".join(f"P{i + 1}: {p[0]:.4f}; {p[1]:.4f}; {p[2]:.4f}" for i, p in enumerate(m["points"]))
        if "extra" in m:
            tip += "\n" + m["extra"]
        for c in range(4):
            it.setToolTip(c, tip)
        self.tree_meas.addTopLevelItem(it)
        self.tree_meas.scrollToItem(it)
        self.status.setText(f"{m['type']} {m['slots']}: {val}" + (f"   ({m['extra']})" if "extra" in m else ""))

    def _meas_menu(self, pos):
        it = self.tree_meas.itemAt(pos)
        menu = QMenu(self)
        if it:
            act = QAction("Messung löschen", self)
            act.triggered.connect(self._delete_selected_measure)
            menu.addAction(act)
        act2 = QAction("Alle löschen", self)
        act2.triggered.connect(self._clear_measures)
        menu.addAction(act2)
        menu.exec(self.tree_meas.viewport().mapToGlobal(pos))

    def _remove_measure(self, mid):
        self.viewer.remove_measure(mid)
        self.measurements = [m for m in self.measurements if m["id"] != mid]
        for i in range(self.tree_meas.topLevelItemCount()):
            it = self.tree_meas.topLevelItem(i)
            if it.data(0, Qt.UserRole) == mid:
                self.tree_meas.takeTopLevelItem(i)
                break

    def _delete_selected_measure(self):
        for it in self.tree_meas.selectedItems():
            self._remove_measure(it.data(0, Qt.UserRole))

    def _delete_last_measure(self):
        if self.measurements:
            self._remove_measure(self.measurements[-1]["id"])

    def _clear_measures(self):
        if hasattr(self, "viewer"):
            self.viewer.clear_measures()
        self.measurements = []
        if hasattr(self, "tree_meas"):
            self.tree_meas.clear()

    # ============================================================== Export
    @staticmethod
    def _de(v, nd=6):
        return f"{v:.{nd}f}".replace(".", ",")

    def _export_screenshot(self):
        path, _ = QFileDialog.getSaveFileName(self, "Screenshot speichern", "vergleich.png", "PNG (*.png)")
        if path:
            self.viewer.screenshot(path)
            self.status.setText(f"Screenshot gespeichert: {path}")

    def _export_report(self):
        res = self.result
        if res is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Bericht speichern", "vergleich_bericht.csv", "CSV (*.csv)")
        if not path:
            return
        tol = self.spin_tol.value()
        tot, ba, ab = res.match(tol)
        unit = self._unit()
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow([f"{APP_NAME} v{APP_VERSION}", _dt.datetime.now().strftime("%d.%m.%Y %H:%M")])
            w.writerow(["Referenz (A)", self.geo["A"].path or self.geo["A"].name])
            w.writerow(["Prüfobjekt (B)", self.geo["B"].path or self.geo["B"].name])
            w.writerow(["Einheit", unit])
            w.writerow(["Toleranz ±", self._de(tol, 4)])
            w.writerow([])
            w.writerow(["Übereinstimmung gesamt %", self._de(tot, 3)])
            w.writerow(["B in Toleranz zu A %", self._de(ba, 3)])
            w.writerow(["A abgedeckt durch B %", self._de(ab, 3)])
            w.writerow([])
            w.writerow(["Kennwert", "B → A", "A ← B"])
            for name, attr in (("Mittelwert", "mean"), ("Mittel |Δ|", "mean_abs"), ("Std.-Abw.", "std"),
                               ("RMS", "rms"), ("Minimum", "min"), ("Maximum", "max"),
                               ("Max |Δ|", "max_abs"), ("5 % Quantil", "p05"), ("95 % Quantil", "p95")):
                w.writerow([name, self._de(getattr(res.stats_b, attr)), self._de(getattr(res.stats_a, attr))])
            w.writerow(["Stichproben", res.stats_b.n, res.stats_a.n])
            w.writerow([])
            w.writerow(["Transformation B → A (4×4)"])
            for row in res.matrix:
                w.writerow([self._de(v, 9) for v in row])
            if self.measurements:
                w.writerow([])
                w.writerow(["Messungen", "Art", "Objekte", "Wert", "P1", "P2", "P3"])
                for m in self.measurements:
                    pts = [" / ".join(self._de(c, 4) for c in p) for p in m["points"]]
                    val = "" if m["value"] is None else self._de(m["value"], 5)
                    w.writerow([m["id"], m["type"], m["slots"], val] + pts)
        self.status.setText(f"Bericht gespeichert: {path}")

    def _export_points(self):
        res = self.result
        if res is None:
            return
        target = self.cmb_target.currentData()
        path, _ = QFileDialog.getSaveFileName(self, "Abweichungen je Punkt speichern",
                                              f"abweichungen_{target}.csv", "CSV (*.csv)")
        if not path:
            return
        geo = self.geo[target]
        pts = geo.disp_points
        dev = res.dev_b_vertices if target == "B" else res.dev_a_vertices
        tol = self.spin_tol.value()
        data = np.column_stack([pts, dev, (np.abs(dev) <= tol).astype(int)])
        with open(path, "w", encoding="utf-8-sig") as f:
            f.write("X;Y;Z;Abweichung;In_Toleranz\n")
            lines = [";".join(f"{v:.6f}".replace(".", ",") for v in row[:4]) + f";{int(row[4])}" for row in data]
            f.write("\n".join(lines))
        self.status.setText(f"{len(pts):,} Punkte gespeichert: {path}".replace(",", "."))

    def _export_aligned(self):
        geo = self.geo["B"]
        if geo is None:
            return
        base = os.path.splitext(geo.name)[0] + "_ausgerichtet"
        filt = "STL (*.stl);;PLY (*.ply);;XYZ (*.xyz)" if geo.is_mesh else "PLY (*.ply);;XYZ (*.xyz)"
        path, _ = QFileDialog.getSaveFileName(self, "Ausgerichtetes Prüfobjekt speichern", base, filt)
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".stl" if geo.is_mesh else ".ply"
        try:
            save_geometry(geo, path)
            self.status.setText(f"Gespeichert: {path}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Speichern fehlgeschlagen", str(e))

    # ============================================================== Ende
    def closeEvent(self, e):
        for w in list(self.loaders.values()):
            w.wait(2000)
        if self.worker:
            self.worker.wait(5000)
        self.viewer.vtk.Finalize()
        super().closeEvent(e)


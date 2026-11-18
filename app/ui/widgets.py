"""Eigene Bedienelemente: einklappbare Abschnitte, Histogramm."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QFont
from PySide6.QtWidgets import QFrame, QPushButton, QVBoxLayout, QWidget, QLabel, QSizePolicy

from . import theme


class Section(QWidget):
    """Einklappbarer Abschnitt mit Dashboard-Kopfzeile."""

    def __init__(self, title: str, expanded: bool = True, parent=None):
        super().__init__(parent)
        self._title = title.upper().replace("&", "&&")
        self.header = QPushButton()
        self.header.setObjectName("SectionHeader")
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.header.clicked.connect(self._toggle)
        self.body = QFrame()
        self.body.setObjectName("SectionBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(10, 10, 10, 10)
        self.body_layout.setSpacing(7)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.header)
        lay.addWidget(self.body)
        self._toggle()

    def _toggle(self):
        on = self.header.isChecked()
        self.header.setText(("▾  " if on else "▸  ") + self._title)
        self.body.setVisible(on)

    def add(self, w):
        if isinstance(w, QWidget):
            self.body_layout.addWidget(w)
        else:
            self.body_layout.addLayout(w)
        return w


def caption(text: str) -> QLabel:
    lb = QLabel(text.upper())
    lb.setObjectName("Caption")
    return lb


class Histogram(QWidget):
    """Histogramm der Abweichungen mit Toleranzband."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(150)
        self.counts = None
        self.edges = None
        self.tol = 0.1
        self.vmin, self.vmax = -1.0, 1.0
        self.mean = None
        self.unit = "mm"

    def set_data(self, d: np.ndarray, tol: float, vmin: float, vmax: float, unit: str = "mm"):
        if d is None or len(d) == 0:
            self.counts = None
            self.update()
            return
        lim = max(abs(vmin), abs(vmax), tol * 1.5, 1e-9)
        self.edges = np.linspace(-lim, lim, 49)
        self.counts, _ = np.histogram(np.clip(d, -lim, lim), bins=self.edges)
        self.tol = tol
        self.vmin, self.vmax = vmin, vmax
        self.mean = float(np.mean(d))
        self.unit = unit
        self.update()

    def set_tol(self, tol: float):
        self.tol = tol
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(6, 6, -6, -22)
        p.fillRect(self.rect(), QColor(theme.BG))
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        if self.counts is None:
            p.setPen(QColor(theme.TEXT_DIM))
            p.drawText(self.rect(), Qt.AlignCenter, "Noch kein Vergleich")
            return
        lim = self.edges[-1]

        def x_of(v):
            return r.left() + (v + lim) / (2 * lim) * r.width()

        # Toleranzband
        x0, x1 = x_of(-self.tol), x_of(self.tol)
        band = QColor(theme.GREEN)
        band.setAlpha(28)
        p.fillRect(QRectF(x0, r.top(), x1 - x0, r.height()), band)
        cmax = max(1, int(self.counts.max()))
        n = len(self.counts)
        w = r.width() / n
        centers = 0.5 * (self.edges[:-1] + self.edges[1:])
        cols = theme.colormap(centers, self.vmin, self.vmax)
        for i, c in enumerate(self.counts):
            if c == 0:
                continue
            h = (np.sqrt(c) / np.sqrt(cmax)) * r.height()
            col = QColor(*[int(v) for v in cols[i]])
            p.fillRect(QRectF(r.left() + i * w + 0.5, r.bottom() - h, max(1.0, w - 1), h), col)
        # Achsen / Marker
        p.setPen(QPen(QColor(theme.BORDER_HI), 1))
        p.drawLine(QPointF(r.left(), r.bottom()), QPointF(r.right(), r.bottom()))
        pen = QPen(QColor(theme.GREEN), 1, Qt.DashLine)
        p.setPen(pen)
        p.drawLine(QPointF(x0, r.top()), QPointF(x0, r.bottom()))
        p.drawLine(QPointF(x1, r.top()), QPointF(x1, r.bottom()))
        if self.mean is not None:
            p.setPen(QPen(QColor(theme.TEXT), 1))
            xm = x_of(np.clip(self.mean, -lim, lim))
            p.drawLine(QPointF(xm, r.top()), QPointF(xm, r.bottom()))
        f = QFont(theme.MONO.split(",")[0])
        f.setPointSizeF(7.5)
        p.setFont(f)
        p.setPen(QColor(theme.TEXT_DIM))
        y = self.rect().bottom() - 6
        p.drawText(QPointF(r.left(), y), f"{-lim:+.3g}")
        txt = f"{lim:+.3g}"
        p.drawText(QPointF(r.right() - p.fontMetrics().horizontalAdvance(txt), y), txt)
        mid = f"0 {self.unit}"
        p.drawText(QPointF(x_of(0) - p.fontMetrics().horizontalAdvance(mid) / 2, y), mid)
        p.setPen(QColor(theme.GREEN))
        p.drawText(QPointF(r.left() + 2, r.top() + 10), f"±{self.tol:g}")


class ColorBar(QWidget):
    """Kleine Legende fuer die Farbskala (im Seitenpanel)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(34)
        self.vmin, self.vmax = -1, 1
        self.mode = "map"
        self.tol = 0.1

    def set_range(self, vmin, vmax, mode="map", tol=0.1):
        self.vmin, self.vmax, self.mode, self.tol = vmin, vmax, mode, tol
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        r = self.rect().adjusted(1, 1, -1, -16)
        if self.mode == "traffic":
            third = r.width() / 3
            for i, c in enumerate([theme.BLUE, theme.GREEN, theme.RED]):
                p.fillRect(QRectF(r.left() + i * third, r.top(), third, r.height()), QColor(c))
            labels = [f"< -{self.tol:g}", f"±{self.tol:g}", f"> +{self.tol:g}"]
            p.setPen(QColor(theme.TEXT_DIM))
            for i, t in enumerate(labels):
                p.drawText(QRectF(r.left() + i * third, r.bottom() + 1, third, 14), Qt.AlignCenter, t)
            return
        vals = np.linspace(self.vmin, self.vmax, max(2, r.width()))
        cols = theme.colormap(vals, self.vmin, self.vmax)
        for i, c in enumerate(cols):
            p.setPen(QColor(int(c[0]), int(c[1]), int(c[2])))
            p.drawLine(r.left() + i, r.top(), r.left() + i, r.bottom())
        p.setPen(QColor(theme.TEXT_DIM))
        f = QFont(theme.MONO.split(",")[0])
        f.setPointSizeF(7.5)
        p.setFont(f)
        p.drawText(QRectF(r.left(), r.bottom() + 1, 80, 14), Qt.AlignLeft, f"{self.vmin:+.3g}")
        p.drawText(QRectF(r.right() - 80, r.bottom() + 1, 80, 14), Qt.AlignRight, f"{self.vmax:+.3g}")
        p.drawText(QRectF(r.left(), r.bottom() + 1, r.width(), 14), Qt.AlignCenter, "0")

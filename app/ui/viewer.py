"""3D-Ansicht (VTK in Qt) mit Farbdarstellung, Vektoren und Messwerkzeugen."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Signal, QObject
from PySide6.QtWidgets import QVBoxLayout, QWidget

import vtkmodules.qt
vtkmodules.qt.PyQtImpl = "PySide6"
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor  # noqa: E402

import vtkmodules.vtkRenderingOpenGL2  # noqa: F401,E402
import vtkmodules.vtkRenderingFreeType  # noqa: F401,E402
import vtkmodules.vtkInteractionStyle  # noqa: F401,E402
from vtkmodules.vtkCommonCore import vtkPoints, vtkUnsignedCharArray  # noqa: E402
from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData  # noqa: E402
from vtkmodules.vtkFiltersSources import vtkSphereSource, vtkLineSource  # noqa: E402
from vtkmodules.vtkInteractionStyle import vtkInteractorStyleTrackballCamera  # noqa: E402
from vtkmodules.vtkInteractionWidgets import vtkOrientationMarkerWidget  # noqa: E402
from vtkmodules.vtkRenderingAnnotation import vtkAxesActor  # noqa: E402
from vtkmodules.vtkRenderingCore import (  # noqa: E402
    vtkActor, vtkBillboardTextActor3D, vtkCellPicker, vtkPointPicker, vtkPolyDataMapper,
    vtkRenderer, vtkTextActor, vtkWindowToImageFilter,
)
from vtkmodules.vtkIOImage import vtkPNGWriter  # noqa: E402
from vtkmodules.util import numpy_support as nps  # noqa: E402

from ..core.geometry import Geometry  # noqa: E402
from . import theme  # noqa: E402


class _Signals(QObject):
    picked = Signal(str, object)          # slot, punkt
    measure_done = Signal(dict)
    measure_progress = Signal(str)


class Viewer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.signals = _Signals()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.vtk = QVTKRenderWindowInteractor(self)
        lay.addWidget(self.vtk)
        self.ren = vtkRenderer()
        self.ren.SetBackground(*theme.hex_rgbf("#0b1016"))
        self.ren.SetBackground2(*theme.hex_rgbf("#18222d"))
        self.ren.GradientBackgroundOn()
        self.rw = self.vtk.GetRenderWindow()
        self.rw.SetNumberOfLayers(2)
        self.ren.SetLayer(0)
        self.rw.AddRenderer(self.ren)
        # Messungen in eigener Ebene: immer sichtbar, nie vom Modell verdeckt
        self.ren_top = vtkRenderer()
        self.ren_top.SetLayer(1)
        self.ren_top.InteractiveOff()
        self.ren_top.SetActiveCamera(self.ren.GetActiveCamera())
        self.rw.AddRenderer(self.ren_top)
        self.rw.SetMultiSamples(0)
        self.rw.SetAlphaBitPlanes(1)
        self.ren.SetUseDepthPeeling(True)
        self.ren.SetMaximumNumberOfPeels(6)
        self.ren.SetOcclusionRatio(0.1)
        self.ren.SetUseFXAA(True)
        self.iren = self.rw.GetInteractor()
        self.style = vtkInteractorStyleTrackballCamera()
        self.iren.SetInteractorStyle(self.style)

        axes = vtkAxesActor()
        axes.SetShaftTypeToCylinder()
        axes.SetTotalLength(1, 1, 1)
        for cap, col in ((axes.GetXAxisCaptionActor2D(), theme.RED),
                         (axes.GetYAxisCaptionActor2D(), theme.GREEN),
                         (axes.GetZAxisCaptionActor2D(), theme.BLUE)):
            tp = cap.GetCaptionTextProperty()
            tp.SetColor(*theme.hex_rgbf(col))
            tp.ShadowOff()
            tp.ItalicOff()
            tp.BoldOn()
        axes.GetXAxisShaftProperty().SetColor(*theme.hex_rgbf(theme.RED))
        axes.GetXAxisTipProperty().SetColor(*theme.hex_rgbf(theme.RED))
        axes.GetYAxisShaftProperty().SetColor(*theme.hex_rgbf(theme.GREEN))
        axes.GetYAxisTipProperty().SetColor(*theme.hex_rgbf(theme.GREEN))
        axes.GetZAxisShaftProperty().SetColor(*theme.hex_rgbf(theme.BLUE))
        axes.GetZAxisTipProperty().SetColor(*theme.hex_rgbf(theme.BLUE))
        self.axes_widget = vtkOrientationMarkerWidget()
        self.axes_widget.SetOrientationMarker(axes)
        self.axes_widget.SetInteractor(self.iren)
        self.axes_widget.SetViewport(0.0, 0.0, 0.14, 0.2)
        self.axes_widget.EnabledOn()
        self.axes_widget.InteractiveOff()

        self.hint = vtkTextActor()
        self.hint.SetInput("Zwei Dateien hierher ziehen  ·  oder links öffnen\n"
                           "STL · PLY · OBJ · XYZ · TXT · CSV · PTS · PCD")
        htp = self.hint.GetTextProperty()
        htp.SetFontSize(17)
        htp.SetColor(*theme.hex_rgbf(theme.TEXT_DIM))
        htp.SetJustificationToCentered()
        htp.SetVerticalJustificationToCentered()
        htp.SetLineSpacing(1.6)
        self.hint.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
        self.hint.SetPosition(0.5, 0.5)
        self.ren.AddViewProp(self.hint)

        self.geos: dict[str, Geometry] = {}
        self.actors: dict[str, vtkActor] = {}
        self.polys: dict[str, vtkPolyData] = {}
        self.vec_actor = None

        # Messen
        self.measure_mode = "none"     # none | dist | angle | dev | coord
        self.snap = True
        self.pending = []              # [(slot, punkt)]
        self.pending_actors = []
        self.measure_actors: dict[int, list] = {}
        self._mid = 0
        self.dev_lookup = None         # callback(slot, punkt) -> (wert, naechster punkt) | None
        self._press = None
        self.cell_picker = vtkCellPicker()
        self.cell_picker.SetTolerance(0.0005)
        self.point_picker = vtkPointPicker()
        self.point_picker.SetTolerance(0.006)
        self.iren.AddObserver("LeftButtonPressEvent", self._on_press, 10.0)
        self.iren.AddObserver("LeftButtonReleaseEvent", self._on_release, 10.0)
        self.iren.AddObserver("MouseMoveEvent", self._on_move, 10.0)

    def start(self):
        self.vtk.Initialize()
        self.vtk.Start()

    def render(self):
        self.rw.Render()

    # ---------------------------------------------------------- Geometrie
    def set_geometry(self, slot: str, geo: Geometry | None):
        if slot in self.actors:
            self.ren.RemoveActor(self.actors.pop(slot))
            self.polys.pop(slot, None)
            self.geos.pop(slot, None)
        self.hint.SetVisibility(len(self.actors) == 0 and geo is None)
        if geo is None:
            self.render()
            return
        self.hint.SetVisibility(False)
        self.geos[slot] = geo
        pd = geo.polydata(display=True)
        self.polys[slot] = pd
        mapper = vtkPolyDataMapper()
        mapper.SetInputData(pd)
        mapper.SetColorModeToDirectScalars()
        mapper.ScalarVisibilityOff()
        actor = vtkActor()
        actor.SetMapper(mapper)
        prop = actor.GetProperty()
        col = theme.COLOR_A if slot == "A" else theme.COLOR_B
        prop.SetColor(*theme.hex_rgbf(col))
        if geo.is_mesh:
            prop.SetInterpolationToPhong()
            prop.SetSpecular(0.25)
            prop.SetSpecularPower(25)
            prop.SetAmbient(0.12)
            prop.SetDiffuse(0.85)
        else:
            prop.SetPointSize(2.5)
            prop.SetRenderPointsAsSpheres(True)
            prop.SetAmbient(0.25)
        self.actors[slot] = actor
        self.ren.AddActor(actor)
        self.render()

    def refresh_points(self, slot: str):
        """Nach einer Transformation die Punkte neu setzen."""
        geo = self.geos.get(slot)
        pd = self.polys.get(slot)
        if geo is None or pd is None:
            return
        vp = vtkPoints()
        vp.SetData(nps.numpy_to_vtk(np.ascontiguousarray(geo.disp_points), deep=True))
        pd.SetPoints(vp)
        n = geo.disp_normals()
        if n is not None:
            arr = nps.numpy_to_vtk(np.ascontiguousarray(n, dtype=np.float32), deep=True)
            arr.SetName("Normals")
            pd.GetPointData().SetNormals(arr)
        pd.Modified()

    def set_appearance(self, slot: str, colors: np.ndarray | None = None, solid: str | None = None,
                       opacity: float = 1.0, visible: bool = True, point_size: float = 2.5):
        actor = self.actors.get(slot)
        pd = self.polys.get(slot)
        if actor is None:
            return
        actor.SetVisibility(visible)
        prop = actor.GetProperty()
        prop.SetOpacity(opacity)
        if not self.geos[slot].is_mesh:
            prop.SetPointSize(point_size)
        mapper = actor.GetMapper()
        # eingefaerbtes Objekt leicht nach vorn ziehen, damit es nicht mit dem anderen flimmert
        off = -3.0 if colors is not None else 0.0
        mapper.SetResolveCoincidentTopologyToPolygonOffset()
        mapper.SetRelativeCoincidentTopologyPolygonOffsetParameters(off, off)
        mapper.SetRelativeCoincidentTopologyPointOffsetParameter(off)
        if colors is not None:
            arr = nps.numpy_to_vtk(np.ascontiguousarray(colors, dtype=np.uint8), deep=True,
                                   array_type=nps.get_vtk_array_type(np.uint8))
            arr.SetName("DevColors")
            pd.GetPointData().SetScalars(arr)
            mapper.ScalarVisibilityOn()
            mapper.SetScalarModeToUsePointData()
        else:
            mapper.ScalarVisibilityOff()
            if solid:
                prop.SetColor(*theme.hex_rgbf(solid))
        pd.Modified()

    def set_vectors(self, p_from: np.ndarray | None, p_to: np.ndarray | None = None,
                    colors: np.ndarray | None = None, scale: float = 1.0):
        if self.vec_actor is not None:
            self.ren.RemoveActor(self.vec_actor)
            self.vec_actor = None
        if p_from is None or len(p_from) == 0:
            return
        end = p_from + (p_to - p_from) * scale
        n = len(p_from)
        pts = np.empty((2 * n, 3))
        pts[0::2] = p_from
        pts[1::2] = end
        pd = vtkPolyData()
        vp = vtkPoints()
        vp.SetData(nps.numpy_to_vtk(pts, deep=True))
        pd.SetPoints(vp)
        lines = vtkCellArray()
        offs = np.arange(0, 2 * n + 1, 2, dtype=np.int64)
        conn = np.arange(2 * n, dtype=np.int64)
        lines.SetData(nps.numpy_to_vtkIdTypeArray(offs, deep=True), nps.numpy_to_vtkIdTypeArray(conn, deep=True))
        pd.SetLines(lines)
        c2 = np.repeat(colors, 2, axis=0).astype(np.uint8)
        arr = nps.numpy_to_vtk(c2, deep=True, array_type=nps.get_vtk_array_type(np.uint8))
        pd.GetPointData().SetScalars(arr)
        m = vtkPolyDataMapper()
        m.SetInputData(pd)
        m.SetColorModeToDirectScalars()
        a = vtkActor()
        a.SetMapper(m)
        a.GetProperty().SetLineWidth(2.0)
        a.GetProperty().SetRenderLinesAsTubes(True)
        a.PickableOff()
        self.vec_actor = a
        self.ren.AddActor(a)

    # ------------------------------------------------------------- Kamera
    def reset_camera(self):
        self.ren.ResetCamera()
        self.ren.ResetCameraClippingRange()
        self.render()

    def view(self, name: str):
        cam = self.ren.GetActiveCamera()
        b = self.ren.ComputeVisiblePropBounds()
        c = np.array([(b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2])
        dirs = {
            "iso": ((1, -1, 0.8), (0, 0, 1)), "front": ((0, -1, 0), (0, 0, 1)),
            "back": ((0, 1, 0), (0, 0, 1)), "top": ((0, 0, 1), (0, 1, 0)),
            "bottom": ((0, 0, -1), (0, 1, 0)), "right": ((1, 0, 0), (0, 0, 1)),
            "left": ((-1, 0, 0), (0, 0, 1)),
        }
        d, up = dirs.get(name, dirs["iso"])
        d = np.array(d, float)
        d /= np.linalg.norm(d)
        cam.SetFocalPoint(*c)
        cam.SetPosition(*(c + d * 100))
        cam.SetViewUp(*up)
        self.ren.ResetCamera()
        self.ren.ResetCameraClippingRange()
        self.render()

    def set_parallel(self, on: bool):
        self.ren.GetActiveCamera().SetParallelProjection(on)
        self.render()

    def screenshot(self, path: str, scale: int = 2):
        f = vtkWindowToImageFilter()
        f.SetInput(self.rw)
        f.SetScale(scale)
        f.SetInputBufferTypeToRGB()
        f.ReadFrontBufferOff()
        f.Update()
        w = vtkPNGWriter()
        w.SetFileName(path)
        w.SetInputConnection(f.GetOutputPort())
        w.Write()
        self.render()

    # ------------------------------------------------------------- Messen
    def set_measure_mode(self, mode: str):
        self.measure_mode = mode
        self.cancel_pending()

    def cancel_pending(self):
        for a in self.pending_actors:
            self.ren_top.RemoveActor(a)
        self.pending = []
        self.pending_actors = []
        self.render()

    def _scene_scale(self):
        b = [0] * 6
        bb = [g.bounds() for g in self.geos.values()]
        if bb:
            lo = np.min([x[0] for x in bb], axis=0)
            hi = np.max([x[1] for x in bb], axis=0)
            return float(np.linalg.norm(hi - lo)) or 1.0
        b = self.ren.ComputeVisiblePropBounds()
        if b[0] > b[1]:
            return 1.0
        return float(np.linalg.norm([b[1] - b[0], b[3] - b[2], b[5] - b[4]])) or 1.0

    def _on_press(self, obj, ev):
        self._press = self.iren.GetEventPosition()

    def _on_move(self, obj, ev):
        pass

    def _on_release(self, obj, ev):
        if self._press is None or self.measure_mode == "none":
            self._press = None
            return
        pos = self.iren.GetEventPosition()
        moved = abs(pos[0] - self._press[0]) + abs(pos[1] - self._press[1])
        self._press = None
        if moved > 4:
            return
        hit = self.pick(pos[0], pos[1])
        if hit is None:
            self.signals.measure_progress.emit("Kein Objekt getroffen.")
            return
        self._add_pick(*hit)

    def pick(self, x, y):
        """Liefert (slot, punkt) oder None. Netze per Flaechenschnitt, Wolken per Punkt."""
        cands = []
        mesh_actors = [(s, a) for s, a in self.actors.items() if a.GetVisibility() and self.geos[s].is_mesh]
        cloud_actors = [(s, a) for s, a in self.actors.items() if a.GetVisibility() and not self.geos[s].is_mesh]
        cam_pos = np.array(self.ren.GetActiveCamera().GetPosition())
        # jedes Objekt einzeln picken, damit auch ein (fast) verdecktes Objekt waehlbar bleibt
        for s, a in mesh_actors:
            cp = self.cell_picker
            cp.InitializePickList()
            cp.AddPickList(a)
            cp.PickFromListOn()
            if cp.Pick(x, y, 0, self.ren) and cp.GetActor() is a:
                cands.append((s, np.array(cp.GetPickPosition())))
        for s, a in cloud_actors:
            pp = self.point_picker
            pp.InitializePickList()
            pp.AddPickList(a)
            pp.PickFromListOn()
            if pp.Pick(x, y, 0, self.ren) and pp.GetPointId() >= 0 and pp.GetActor() is a:
                cands.append((s, np.array(pp.GetPickPosition())))
        if not cands:
            return None
        cands.sort(key=lambda c: np.linalg.norm(c[1] - cam_pos))
        # liegen beide Objekte (fast) uebereinander, das deckendere bevorzugen
        d0 = np.linalg.norm(cands[0][1] - cam_pos)
        near = [c for c in cands if np.linalg.norm(c[1] - cam_pos) - d0 < 0.01 * self._scene_scale()]
        near.sort(key=lambda c: -self.actors[c[0]].GetProperty().GetOpacity())
        slot, p = near[0]
        if self.snap:
            geo = self.geos[slot]
            _, idx = geo.vertex_tree().query(p)
            p = geo.points[idx]
        return slot, p

    def _marker(self, p, color, r=None):
        s = vtkSphereSource()
        s.SetCenter(*p)
        s.SetRadius(r or self._scene_scale() * 0.004)
        s.SetThetaResolution(16)
        s.SetPhiResolution(12)
        m = vtkPolyDataMapper()
        m.SetInputConnection(s.GetOutputPort())
        a = vtkActor()
        a.SetMapper(m)
        a.GetProperty().SetColor(*theme.hex_rgbf(color))
        a.GetProperty().LightingOff()
        a.PickableOff()
        self.ren_top.AddActor(a)
        return a

    def _line(self, p, q, color, width=2.5, dashed=False):
        ls = vtkLineSource()
        ls.SetPoint1(*p)
        ls.SetPoint2(*q)
        m = vtkPolyDataMapper()
        m.SetInputConnection(ls.GetOutputPort())
        a = vtkActor()
        a.SetMapper(m)
        pr = a.GetProperty()
        pr.SetColor(*theme.hex_rgbf(color))
        pr.SetLineWidth(width)
        pr.LightingOff()
        if dashed:
            pr.SetLineStipplePattern(0xF0F0)
        a.PickableOff()
        self.ren_top.AddActor(a)
        return a

    def _label(self, p, text, color=theme.AMBER):
        t = vtkBillboardTextActor3D()
        t.SetInput(text)
        t.SetPosition(*p)
        tp = t.GetTextProperty()
        tp.SetFontSize(15)
        tp.SetColor(*theme.hex_rgbf(color))
        tp.SetBackgroundColor(*theme.hex_rgbf("#0a0e13"))
        tp.SetBackgroundOpacity(0.82)
        tp.SetFrame(True)
        tp.SetFrameColor(*theme.hex_rgbf(color))
        tp.SetFrameWidth(1)
        tp.BoldOn()
        tp.SetJustificationToCentered()
        tp.SetVerticalJustificationToBottom()
        t.SetDisplayOffset(0, 10)
        t.PickableOff()
        self.ren_top.AddActor(t)
        return t

    def _add_pick(self, slot, p):
        mode = self.measure_mode
        col = theme.TEAL if slot == "A" else theme.AMBER
        if mode == "coord":
            mid = self._next_id()
            acts = [self._marker(p, col),
                    self._label(p, f"{slot}  X {p[0]:.3f}  Y {p[1]:.3f}  Z {p[2]:.3f}", col)]
            self.measure_actors[mid] = acts
            self.signals.measure_done.emit({"id": mid, "type": "Koordinate", "slots": slot,
                                            "value": None, "points": [p.tolist()]})
            self.render()
            return
        if mode == "dev":
            if self.dev_lookup is None:
                self.signals.measure_progress.emit("Erst vergleichen, dann Abweichung messen.")
                return
            res = self.dev_lookup(slot, p)
            if res is None:
                return
            val, q = res
            mid = self._next_id()
            other = "B" if slot == "A" else "A"
            acts = [self._marker(p, col), self._marker(q, theme.TEAL if other == "A" else theme.AMBER),
                    self._line(p, q, theme.TEXT, 2.0),
                    self._label(p, f"Δ {val:+.4f}", theme.RED if val > 0 else theme.BLUE)]
            self.measure_actors[mid] = acts
            self.signals.measure_done.emit({"id": mid, "type": "Abweichung", "slots": f"{slot}→{other}",
                                            "value": float(val), "points": [p.tolist(), q.tolist()]})
            self.render()
            return
        self.pending.append((slot, p))
        self.pending_actors.append(self._marker(p, col))
        need = 2 if mode == "dist" else 3
        if len(self.pending) < need:
            self.signals.measure_progress.emit(
                f"Punkt {len(self.pending)} gesetzt ({slot}) – weiteren Punkt anklicken.")
            self.render()
            return
        acts = list(self.pending_actors)
        pts = [q for _, q in self.pending]
        slots = "".join(s for s, _ in self.pending)
        mid = self._next_id()
        if mode == "dist":
            p1, p2 = pts
            d = float(np.linalg.norm(p2 - p1))
            dx, dy, dz = (p2 - p1)
            acts.append(self._line(p1, p2, theme.AMBER))
            acts.append(self._label((p1 + p2) / 2, f"{d:.4f}"))
            self.signals.measure_done.emit({"id": mid, "type": "Distanz", "slots": "↔".join(slots),
                                            "value": d, "delta": [float(dx), float(dy), float(dz)],
                                            "points": [p1.tolist(), p2.tolist()]})
        else:
            p1, p2, p3 = pts
            v1, v2 = p1 - p2, p3 - p2
            den = np.linalg.norm(v1) * np.linalg.norm(v2)
            ang = float(np.degrees(np.arccos(np.clip(np.dot(v1, v2) / den, -1, 1)))) if den > 0 else 0.0
            acts.append(self._line(p1, p2, theme.AMBER))
            acts.append(self._line(p2, p3, theme.AMBER))
            acts.append(self._label(p2, f"{ang:.3f}°"))
            self.signals.measure_done.emit({"id": mid, "type": "Winkel", "slots": "-".join(slots),
                                            "value": ang, "points": [p1.tolist(), p2.tolist(), p3.tolist()]})
        self.measure_actors[mid] = acts
        self.pending = []
        self.pending_actors = []
        self.render()

    def _next_id(self):
        self._mid += 1
        return self._mid

    def remove_measure(self, mid: int):
        for a in self.measure_actors.pop(mid, []):
            self.ren_top.RemoveActor(a)
        self.render()

    def clear_measures(self):
        for mid in list(self.measure_actors):
            self.remove_measure(mid)
        self.cancel_pending()

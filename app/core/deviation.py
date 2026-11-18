"""Abweichungsberechnung, Statistik und prozentuale Uebereinstimmung."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from vtkmodules.vtkFiltersCore import vtkImplicitPolyDataDistance
from vtkmodules.vtkFiltersGeneral import vtkDistancePolyDataFilter
from vtkmodules.util import numpy_support as nps

from .geometry import Geometry, polydata_from_numpy
from .registration import register, decompose

QUALITY = {
    "Schnell": 50_000,
    "Normal": 200_000,
    "Genau": 800_000,
}


def signed_distance(target: Geometry, query: np.ndarray) -> np.ndarray:
    """Vorzeichenbehafteter Abstand der Punkte `query` zur Oberflaeche von `target`.
    Positiv = Punkt liegt ausserhalb (Materialueberschuss), negativ = innerhalb."""
    if len(query) == 0:
        return np.zeros(0)
    if target.is_mesh:
        f = vtkDistancePolyDataFilter()
        f.SetInputData(0, polydata_from_numpy(query, None))
        f.SetInputData(1, target.polydata(display=False))
        f.SignedDistanceOn()
        f.NegateDistanceOff()
        f.ComputeSecondDistanceOff()
        if hasattr(f, "ComputeCellCenterDistanceOff"):
            f.ComputeCellCenterDistanceOff()
        f.Update()
        arr = f.GetOutput().GetPointData().GetArray("Distance")
        return nps.vtk_to_numpy(arr).astype(np.float64)
    tree = target.kdtree()
    tpts = target.disp_points
    d, idx = tree.query(query, workers=-1)
    n = target.cloud_normals()
    dplane = np.einsum("ij,ij->i", query - tpts[idx], n[idx])
    # Punkt-zu-Ebene-Abstand, damit der Punktabstand der Wolke nicht als Abweichung zaehlt;
    # liegt der Punkt seitlich ausserhalb der Wolke, waechst der Abstand wieder an.
    spacing = target.point_spacing()
    lateral = np.sqrt(np.maximum(d * d - dplane * dplane, 0.0))
    dist = np.sqrt(dplane * dplane + np.maximum(lateral - 1.5 * spacing, 0.0) ** 2)
    sgn = np.where(dplane < 0, -1.0, 1.0)
    return dist * sgn


def closest_points(target: Geometry, query: np.ndarray) -> np.ndarray:
    if target.is_mesh:
        imp = vtkImplicitPolyDataDistance()
        imp.SetInput(target.polydata(display=False))
        out = np.zeros_like(query)
        cp = [0.0, 0.0, 0.0]
        for i, q in enumerate(query):
            imp.EvaluateFunctionAndGetClosestPoint(q.tolist(), cp)
            out[i] = cp
        return out
    _, idx = target.kdtree().query(query, workers=-1)
    return target.disp_points[idx]


@dataclass
class Stats:
    n: int = 0
    min: float = 0.0
    max: float = 0.0
    mean: float = 0.0
    mean_abs: float = 0.0
    std: float = 0.0
    rms: float = 0.0
    p05: float = 0.0
    p95: float = 0.0
    max_abs: float = 0.0

    @staticmethod
    def of(d: np.ndarray) -> "Stats":
        if len(d) == 0:
            return Stats()
        return Stats(
            n=len(d), min=float(d.min()), max=float(d.max()), mean=float(d.mean()),
            mean_abs=float(np.abs(d).mean()), std=float(d.std()),
            rms=float(np.sqrt(np.mean(d ** 2))), p05=float(np.percentile(d, 5)),
            p95=float(np.percentile(d, 95)), max_abs=float(np.abs(d).max()),
        )


@dataclass
class CompareResult:
    matrix: np.ndarray
    reg_info: dict
    dev_b_vertices: np.ndarray        # Abweichung B->A an Anzeige-Punkten von B
    dev_a_vertices: np.ndarray        # Abweichung (B relativ zu A) an Anzeige-Punkten von A
    samples_b: np.ndarray             # Stichprobe B (flaechengewichtet)
    dev_samples_b: np.ndarray         # signierte Abweichung Stichprobe B -> A
    samples_a: np.ndarray
    dev_samples_a: np.ndarray         # signierte Abweichung (B rel. A) an Stichprobe A
    vec_from: np.ndarray              # Abweichungsvektoren (Teilmenge)
    vec_to: np.ndarray
    vec_dev: np.ndarray
    sign_estimated: bool = False
    stats_b: Stats = field(default_factory=Stats)
    stats_a: Stats = field(default_factory=Stats)

    def match(self, tol: float):
        """Prozentuale Uebereinstimmung bei Toleranz +-tol.
        Rueckgabe: (gesamt, B->A, A->B) in Prozent."""
        b = float(np.mean(np.abs(self.dev_samples_b) <= tol)) * 100 if len(self.dev_samples_b) else 0.0
        a = float(np.mean(np.abs(self.dev_samples_a) <= tol)) * 100 if len(self.dev_samples_a) else 0.0
        return 0.5 * (a + b), b, a

    def transform_text(self) -> str:
        (rx, ry, rz), t, s = decompose(self.matrix)
        txt = (f"Rotation X/Y/Z: {rx:.3f}° / {ry:.3f}° / {rz:.3f}°\n"
               f"Verschiebung: {t[0]:.4f} / {t[1]:.4f} / {t[2]:.4f}")
        if abs(s - 1) > 1e-9:
            txt += f"\nSkalierung: {s:.6f}"
        rms = self.reg_info.get("rms")
        if rms is not None:
            txt += f"\nICP-RMS: {rms:.4f}  ·  Start: {self.reg_info.get('candidate', '-')}"
        return txt


def run_compare(a: Geometry, b: Geometry, align_mode="auto", with_scale=False,
                quality="Normal", progress=None) -> CompareResult:
    def prog(v, t):
        if progress:
            progress(v, t)

    rng = np.random.default_rng(42)
    n = QUALITY.get(quality, 200_000)
    prog(1, "Stichproben erzeugen")
    if align_mode == "auto":
        b.set_transform(np.eye(4))
    if align_mode != "none":
        prog(2, "Normalen vorbereiten")
    sa, na = a.sample_with_normals(min(n, 400_000), rng, align_mode != "none")
    sb0 = b.sample(min(n, 400_000), rng)
    m_rel, info = register(sa, sb0, align_mode, with_scale, progress=prog, rng=rng, ref_normals=na)
    b.set_transform(m_rel @ b.transform)

    # Stichprobe und Anzeige-Punkte in einem Aufruf: der Suchbaum des Ziels wird nur einmal gebaut
    prog(70, "Abweichungen B → A")
    sb = b.sample(n, rng)
    d = signed_distance(a, np.vstack([sb, b.disp_points]))
    dsb, dvb = d[:len(sb)], d[len(sb):]
    prog(82, "Abweichungen A → B")
    sa = a.sample(n, rng)
    d = -signed_distance(b, np.vstack([sa, a.disp_points]))
    dsa, dva = d[:len(sa)], d[len(sa):]

    prog(92, "Abweichungsvektoren")
    nv = min(6000, len(b.disp_points))
    vi = rng.choice(len(b.disp_points), nv, replace=False)
    vfrom = b.disp_points[vi]
    vto = closest_points(a, vfrom)
    prog(99, "Statistik")
    res = CompareResult(
        matrix=b.transform.copy(), reg_info=info,
        dev_b_vertices=dvb, dev_a_vertices=dva,
        samples_b=sb, dev_samples_b=dsb, samples_a=sa, dev_samples_a=dsa,
        vec_from=vfrom, vec_to=vto, vec_dev=dvb[vi],
        sign_estimated=(not a.is_mesh) or (not b.is_mesh),
        stats_b=Stats.of(dsb), stats_a=Stats.of(dsa),
    )
    prog(100, "Fertig")
    return res

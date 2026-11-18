"""Geometrie-Container fuer Netze (STL/PLY/OBJ) und Punktwolken."""
from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree

from vtkmodules.vtkCommonCore import vtkPoints
from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData
from vtkmodules.vtkFiltersCore import vtkPolyDataNormals
from vtkmodules.vtkFiltersModeling import vtkAdaptiveSubdivisionFilter
from vtkmodules.util import numpy_support as nps


def polydata_from_numpy(points: np.ndarray, faces: np.ndarray | None) -> vtkPolyData:
    pd = vtkPolyData()
    vp = vtkPoints()
    vp.SetData(nps.numpy_to_vtk(np.ascontiguousarray(points, dtype=np.float64), deep=True))
    pd.SetPoints(vp)
    ca = vtkCellArray()
    if faces is not None and len(faces):
        n = len(faces)
        offsets = np.arange(0, 3 * n + 1, 3, dtype=np.int64)
        conn = np.ascontiguousarray(faces, dtype=np.int64).ravel()
        ca.SetData(nps.numpy_to_vtkIdTypeArray(offsets, deep=True),
                   nps.numpy_to_vtkIdTypeArray(conn, deep=True))
        pd.SetPolys(ca)
    else:
        n = len(points)
        offsets = np.arange(0, n + 1, dtype=np.int64)
        conn = np.arange(n, dtype=np.int64)
        ca.SetData(nps.numpy_to_vtkIdTypeArray(offsets, deep=True),
                   nps.numpy_to_vtkIdTypeArray(conn, deep=True))
        pd.SetVerts(ca)
    return pd


def faces_from_polydata(pd: vtkPolyData) -> np.ndarray | None:
    polys = pd.GetPolys()
    if polys is None or polys.GetNumberOfCells() == 0:
        return None
    offsets = nps.vtk_to_numpy(polys.GetOffsetsArray()).astype(np.int64)
    conn = nps.vtk_to_numpy(polys.GetConnectivityArray()).astype(np.int64)
    sizes = np.diff(offsets)
    if np.all(sizes == 3):
        return conn.reshape(-1, 3)
    # Polygone mit mehr als 3 Ecken als Faecher triangulieren
    tris = []
    for i in range(len(sizes)):
        s, e = offsets[i], offsets[i + 1]
        ids = conn[s:e]
        for k in range(1, len(ids) - 1):
            tris.append((ids[0], ids[k], ids[k + 1]))
    return np.asarray(tris, dtype=np.int64) if tris else None


class Geometry:
    """Haelt Original- und aktuell transformierte Daten einer Datei."""

    def __init__(self, name: str, path: str, points: np.ndarray, faces: np.ndarray | None):
        self.name = name
        self.path = path
        self.orig_points = np.ascontiguousarray(points, dtype=np.float64)
        self.faces = None if faces is None or len(faces) == 0 else np.ascontiguousarray(faces, dtype=np.int64)
        self.kind = "mesh" if self.faces is not None else "cloud"
        self.transform = np.eye(4)
        # Anzeige-Geometrie (bei groben CAD-Netzen verfeinert, damit die Farbkarte sauber ist)
        self.disp_orig_points = self.orig_points
        self.disp_faces = self.faces
        self.disp_normals_orig = None
        self._normals_cloud = None
        self._tree = None
        self._areas = None

    # ------------------------------------------------------------------ Basis
    @property
    def is_mesh(self) -> bool:
        return self.kind == "mesh"

    @property
    def points(self) -> np.ndarray:
        return self._apply(self.orig_points)

    @property
    def disp_points(self) -> np.ndarray:
        return self._apply(self.disp_orig_points)

    def _apply(self, p: np.ndarray) -> np.ndarray:
        if np.allclose(self.transform, np.eye(4)):
            return p
        return p @ self.transform[:3, :3].T + self.transform[:3, 3]

    def set_transform(self, m: np.ndarray):
        self.transform = np.array(m, dtype=np.float64)
        self._tree = None
        self._vtree = None
        self._spacing = None

    def disp_normals(self):
        if self.disp_normals_orig is None:
            return None
        n = self.disp_normals_orig @ self.transform[:3, :3].T
        ln = np.linalg.norm(n, axis=1, keepdims=True)
        ln[ln == 0] = 1
        return n / ln

    def bounds(self):
        p = self.points
        return p.min(axis=0), p.max(axis=0)

    def diag(self) -> float:
        lo, hi = self.bounds()
        d = float(np.linalg.norm(hi - lo))
        return d if d > 0 else 1.0

    def info_text(self) -> str:
        lo, hi = self.bounds()
        size = hi - lo
        if self.is_mesh:
            head = f"Netz · {len(self.orig_points):,} Punkte · {len(self.faces):,} Dreiecke"
        else:
            head = f"Punktwolke · {len(self.orig_points):,} Punkte"
        return (head + f"\nGröße: {size[0]:.3f} × {size[1]:.3f} × {size[2]:.3f}").replace(",", ".")

    # -------------------------------------------------------------- Abfragen
    def kdtree(self) -> cKDTree:
        if self._tree is None:
            self._tree = cKDTree(self.disp_points)
        return self._tree

    def vertex_tree(self) -> cKDTree:
        """KD-Baum ueber die echten (nicht verfeinerten) Punkte – fuer den Messfang."""
        if getattr(self, "_vtree", None) is None:
            self._vtree = cKDTree(self.points)
        return self._vtree

    def face_areas(self) -> np.ndarray:
        if self._areas is None:
            p = self.orig_points
            f = self.faces
            a = np.cross(p[f[:, 1]] - p[f[:, 0]], p[f[:, 2]] - p[f[:, 0]])
            self._areas = 0.5 * np.linalg.norm(a, axis=1)
        return self._areas

    def sample(self, n: int, rng: np.random.Generator) -> np.ndarray:
        return self.sample_with_normals(n, rng, False)[0]

    def sample_with_normals(self, n: int, rng: np.random.Generator, normals: bool = True):
        """Gleichmaessige Stichprobe (Netz: flaechengewichtet auf der Oberflaeche),
        optional mit Normalen (Netz: Dreiecksnormale, Wolke: geschaetzt)."""
        pts = self._sample(n, rng)
        if not normals:
            return pts, None
        if self.is_mesh:
            p = self.orig_points
            f = self.faces[self._last_tri]
            nr = np.cross(p[f[:, 1]] - p[f[:, 0]], p[f[:, 2]] - p[f[:, 0]])
            nr = nr @ self.transform[:3, :3].T
        else:
            nr = self.cloud_normals()[self._last_idx]
        ln = np.linalg.norm(nr, axis=1, keepdims=True)
        ln[ln == 0] = 1
        return pts, nr / ln

    def _sample(self, n: int, rng: np.random.Generator) -> np.ndarray:
        if self.is_mesh:
            areas = self.face_areas()
            total = areas.sum()
            if total <= 0:
                self._last_tri = np.zeros(n, np.int64)
                idx = rng.integers(0, len(self.orig_points), n)
                return self._apply(self.orig_points[idx])
            tri = rng.choice(len(self.faces), size=n, p=areas / total)
            self._last_tri = tri
            r1 = np.sqrt(rng.random(n))
            r2 = rng.random(n)
            p = self.orig_points
            f = self.faces[tri]
            a, b, c = p[f[:, 0]], p[f[:, 1]], p[f[:, 2]]
            pts = (1 - r1)[:, None] * a + (r1 * (1 - r2))[:, None] * b + (r1 * r2)[:, None] * c
            return self._apply(pts)
        p = self.orig_points
        if len(p) <= n:
            self._last_idx = np.arange(len(p))
            return self._apply(p)
        idx = rng.choice(len(p), size=n, replace=False)
        self._last_idx = idx
        return self._apply(p[idx])

    def polydata(self, display: bool = True) -> vtkPolyData:
        if display:
            pd = polydata_from_numpy(self.disp_points, self.disp_faces)
            n = self.disp_normals()
            if n is not None:
                arr = nps.numpy_to_vtk(np.ascontiguousarray(n, dtype=np.float32), deep=True)
                arr.SetName("Normals")
                pd.GetPointData().SetNormals(arr)
            return pd
        return polydata_from_numpy(self.points, self.faces)

    def point_spacing(self) -> float:
        """Mittlerer Punktabstand (Wolken), fuer Punkt-zu-Ebene-Abstaende."""
        if getattr(self, "_spacing", None) is None:
            pts = self.orig_points
            rng = np.random.default_rng(3)
            sub = pts if len(pts) <= 20000 else pts[rng.choice(len(pts), 20000, replace=False)]
            d, _ = cKDTree(pts).query(sub, k=2, workers=-1)
            self._spacing = float(np.median(d[:, 1])) * float(np.cbrt(np.linalg.det(self.transform[:3, :3])) or 1)
        return self._spacing

    # ---------------------------------------------------- Normalen (Wolken)
    def cloud_normals(self) -> np.ndarray:
        """Geschaetzte Normalen einer Punktwolke (PCA ueber Nachbarn)."""
        if self._normals_cloud is None:
            pts = self.orig_points
            tree = cKDTree(pts)
            k = min(12, len(pts))
            normals = np.zeros_like(pts)
            centroid = pts.mean(axis=0)
            chunk = 200_000
            for s in range(0, len(pts), chunk):
                q = pts[s:s + chunk]
                _, idx = tree.query(q, k=k, workers=-1)
                nb = pts[idx]
                nb = nb - nb.mean(axis=1, keepdims=True)
                cov = np.einsum("nki,nkj->nij", nb, nb)
                _, vec = np.linalg.eigh(cov)
                n = vec[:, :, 0]
                flip = np.einsum("ij,ij->i", n, q - centroid) < 0
                n[flip] *= -1
                normals[s:s + chunk] = n
            self._normals_cloud = normals
        n = self._normals_cloud @ self.transform[:3, :3].T
        ln = np.linalg.norm(n, axis=1, keepdims=True)
        ln[ln == 0] = 1
        return n / ln

    # ------------------------------------------------- Anzeige vorbereiten
    def prepare_display(self, max_triangles: int = 1_500_000):
        """Grobe Netze (z. B. CAD-STL) fuer die Farbdarstellung verfeinern + Normalen."""
        if not self.is_mesh:
            return
        n_tri = len(self.faces)
        pts, faces = self.orig_points, self.faces
        lo, hi = pts.min(axis=0), pts.max(axis=0)
        diag = float(np.linalg.norm(hi - lo)) or 1.0
        target_edge = diag / 180.0
        e = np.linalg.norm(pts[faces[:, 1]] - pts[faces[:, 0]], axis=1)
        if n_tri < max_triangles // 3 and np.percentile(e, 90) > target_edge * 1.5:
            sub = vtkAdaptiveSubdivisionFilter()
            sub.SetInputData(polydata_from_numpy(pts, faces))
            sub.SetMaximumEdgeLength(target_edge)
            sub.SetMaximumTriangleArea(target_edge * target_edge)
            sub.SetMaximumNumberOfTriangles(max_triangles)
            sub.SetMaximumNumberOfPasses(12)
            sub.Update()
            out = sub.GetOutput()
            f2 = faces_from_polydata(out)
            if f2 is not None and len(f2) > n_tri:
                pts = nps.vtk_to_numpy(out.GetPoints().GetData()).astype(np.float64)
                faces = f2
        self.disp_orig_points = np.ascontiguousarray(pts)
        self.disp_faces = np.ascontiguousarray(faces)
        nf = vtkPolyDataNormals()
        nf.SetInputData(polydata_from_numpy(self.disp_orig_points, self.disp_faces))
        nf.SetSplitting(False)
        nf.SetConsistency(False)
        nf.SetAutoOrientNormals(False)
        nf.ComputePointNormalsOn()
        nf.ComputeCellNormalsOff()
        nf.Update()
        normals = nf.GetOutput().GetPointData().GetNormals()
        if normals is not None and normals.GetNumberOfTuples() == len(self.disp_orig_points):
            self.disp_normals_orig = nps.vtk_to_numpy(normals).astype(np.float32)

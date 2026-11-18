"""Laden und Speichern von STL-Dateien und Punktwolken."""
from __future__ import annotations

import os
import re
import struct

import numpy as np

from vtkmodules.vtkIOGeometry import vtkOBJReader
from vtkmodules.vtkIOPLY import vtkPLYReader, vtkPLYWriter
from vtkmodules.vtkIOLegacy import vtkPolyDataReader
from vtkmodules.vtkIOXML import vtkXMLPolyDataReader
from vtkmodules.util import numpy_support as nps

from .geometry import Geometry, faces_from_polydata, polydata_from_numpy

MESH_EXT = [".stl", ".ply", ".obj", ".vtp", ".vtk"]
CLOUD_EXT = [".xyz", ".txt", ".csv", ".pts", ".asc", ".pcd", ".xyzn", ".xyzrgb"]
ALL_EXT = MESH_EXT + CLOUD_EXT

FILE_FILTER = (
    "3D-Dateien (" + " ".join("*" + e for e in ALL_EXT) + ");;"
    "STL (*.stl);;PLY (*.ply);;OBJ (*.obj);;"
    "Punktwolken (*.xyz *.txt *.csv *.pts *.asc *.pcd *.xyzn *.xyzrgb);;Alle Dateien (*)"
)


class LoadError(Exception):
    pass


def _dedupe(vertices: np.ndarray):
    """Doppelte Eckpunkte zusammenfassen (STL speichert jedes Dreieck einzeln)."""
    v = np.ascontiguousarray(vertices, dtype=np.float32)
    view = v.view(np.dtype((np.void, v.dtype.itemsize * 3))).ravel()
    _, first, inv = np.unique(view, return_index=True, return_inverse=True)
    uniq = v[first].astype(np.float64)
    faces = inv.reshape(-1, 3).astype(np.int64)
    good = (faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) & (faces[:, 0] != faces[:, 2])
    return uniq, faces[good]


def load_stl(path: str):
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        header = f.read(84)
    if len(header) < 84:
        raise LoadError("Datei ist zu klein für eine STL.")
    n = struct.unpack("<I", header[80:84])[0]
    is_binary = (84 + n * 50 == size)
    if not is_binary and not header[:5].lower().startswith(b"solid"):
        is_binary = True
    if is_binary:
        dt = np.dtype([("n", "<f4", (3,)), ("v", "<f4", (3, 3)), ("a", "<u2")])
        n = min(n, (size - 84) // 50)
        data = np.fromfile(path, dtype=dt, count=n, offset=84)
        verts = data["v"].reshape(-1, 3)
    else:
        with open(path, "r", errors="ignore") as f:
            txt = f.read()
        nums = re.findall(r"vertex\s+(\S+)\s+(\S+)\s+(\S+)", txt)
        if not nums:
            raise LoadError("Keine Dreiecke in der ASCII-STL gefunden.")
        verts = np.asarray(nums, dtype=np.float64)
        verts = verts[: (len(verts) // 3) * 3]
    if len(verts) == 0:
        raise LoadError("STL enthält keine Dreiecke.")
    return _dedupe(verts)


def _vtk_read(reader, path):
    reader.SetFileName(path)
    reader.Update()
    pd = reader.GetOutput()
    if pd is None or pd.GetNumberOfPoints() == 0:
        raise LoadError("Datei enthält keine Punkte.")
    pts = nps.vtk_to_numpy(pd.GetPoints().GetData()).astype(np.float64)
    faces = faces_from_polydata(pd)
    return pts, faces


def load_pcd(path: str):
    with open(path, "rb") as f:
        header = {}
        while True:
            line = f.readline()
            if not line:
                raise LoadError("PCD-Kopf unvollständig.")
            s = line.decode("ascii", errors="ignore").strip()
            if not s or s.startswith("#"):
                continue
            key, _, val = s.partition(" ")
            header[key.upper()] = val.split()
            if key.upper() == "DATA":
                break
        data_start = f.tell()
    fields = header.get("FIELDS", [])
    sizes = [int(x) for x in header.get("SIZE", [])]
    types = header.get("TYPE", [])
    counts = [int(x) for x in header.get("COUNT", ["1"] * len(fields))]
    npts = int(header.get("POINTS", header.get("WIDTH", ["0"]))[0])
    mode = header["DATA"][0].lower()
    if not all(k in fields for k in ("x", "y", "z")):
        raise LoadError("PCD enthält keine x/y/z-Felder.")
    if mode == "ascii":
        with open(path, "rb") as f:
            f.seek(data_start)
            arr = np.loadtxt(f, dtype=np.float64, ndmin=2)
        col = []
        c = 0
        for name, cnt in zip(fields, counts):
            col.append(c)
            c += cnt
        ix = [col[fields.index(k)] for k in ("x", "y", "z")]
        pts = arr[:, ix]
    elif mode == "binary":
        tmap = {"F": "f", "I": "i", "U": "u"}
        dt = []
        for i, (name, sz, tp, cnt) in enumerate(zip(fields, sizes, types, counts)):
            base = "<" + tmap[tp] + str(sz)
            nm = name if name not in [d[0] for d in dt] else f"{name}_{i}"
            dt.append((nm, base, (cnt,)) if cnt > 1 else (nm, base))
        data = np.fromfile(path, dtype=np.dtype(dt), count=npts, offset=data_start)
        pts = np.stack([data["x"], data["y"], data["z"]], axis=1).astype(np.float64)
    else:
        raise LoadError("Komprimierte PCD-Dateien (binary_compressed) werden nicht unterstützt – "
                        "bitte als ASCII oder binary speichern.")
    pts = pts[np.all(np.isfinite(pts), axis=1)]
    return pts, None


def load_text_cloud(path: str):
    with open(path, "r", errors="ignore") as f:
        head = [f.readline() for _ in range(50)]
    skip = 0
    first = None
    for i, line in enumerate(head):
        toks = [t for t in re.split(r"[,;\s]+", line.strip()) if t]
        if len(toks) >= 3:
            try:
                [float(t) for t in toks[:3]]
                first = line
                skip = i
                break
            except ValueError:
                pass
    if first is None:
        raise LoadError("Keine Koordinatenzeilen (x y z) gefunden.")
    delim = None
    if ";" in first:
        delim = ";"
    elif "," in first:
        delim = ","
    try:
        pts = np.loadtxt(path, dtype=np.float64, delimiter=delim, skiprows=skip,
                         usecols=(0, 1, 2), ndmin=2, comments="#")
    except Exception:
        rows = []
        with open(path, "r", errors="ignore") as f:
            for line in f:
                toks = [t for t in re.split(r"[,;\s]+", line.strip()) if t]
                if len(toks) >= 3:
                    try:
                        rows.append([float(t) for t in toks[:3]])
                    except ValueError:
                        continue
        pts = np.asarray(rows, dtype=np.float64).reshape(-1, 3)
    pts = pts[np.all(np.isfinite(pts), axis=1)]
    return pts, None


def load_file(path: str) -> Geometry:
    if not os.path.isfile(path):
        raise LoadError(f"Datei nicht gefunden: {path}")
    ext = os.path.splitext(path)[1].lower()
    if ext == ".stl":
        pts, faces = load_stl(path)
    elif ext == ".ply":
        pts, faces = _vtk_read(vtkPLYReader(), path)
    elif ext == ".obj":
        pts, faces = _vtk_read(vtkOBJReader(), path)
    elif ext == ".vtp":
        pts, faces = _vtk_read(vtkXMLPolyDataReader(), path)
    elif ext == ".vtk":
        pts, faces = _vtk_read(vtkPolyDataReader(), path)
    elif ext == ".pcd":
        pts, faces = load_pcd(path)
    else:
        pts, faces = load_text_cloud(path)
    if len(pts) < 3:
        raise LoadError("Zu wenige Punkte in der Datei.")
    if faces is not None:
        # unbenutzte Punkte entfernen
        used = np.zeros(len(pts), bool)
        used[faces.ravel()] = True
        if not used.all():
            remap = -np.ones(len(pts), np.int64)
            remap[used] = np.arange(used.sum())
            pts = pts[used]
            faces = remap[faces]
    return Geometry(os.path.basename(path), path, pts, faces)


def save_geometry(geo: Geometry, path: str):
    """Aktuelle (ausgerichtete) Lage speichern – STL, PLY oder XYZ."""
    ext = os.path.splitext(path)[1].lower()
    pts = geo.points
    if ext == ".stl":
        if not geo.is_mesh:
            raise LoadError("Punktwolken können nicht als STL gespeichert werden – bitte PLY oder XYZ wählen.")
        f = geo.faces
        tri = pts[f].astype(np.float32)
        nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        ln = np.linalg.norm(nrm, axis=1, keepdims=True)
        ln[ln == 0] = 1
        nrm = (nrm / ln).astype(np.float32)
        dt = np.dtype([("n", "<f4", (3,)), ("v", "<f4", (3, 3)), ("a", "<u2")])
        data = np.zeros(len(f), dtype=dt)
        data["n"] = nrm
        data["v"] = tri
        with open(path, "wb") as fh:
            fh.write(b"3D-Vergleich-MK1 ausgerichtet".ljust(80, b" "))
            fh.write(struct.pack("<I", len(f)))
            data.tofile(fh)
    elif ext == ".ply":
        w = vtkPLYWriter()
        w.SetFileName(path)
        w.SetInputData(polydata_from_numpy(pts, geo.faces))
        w.SetFileTypeToBinary()
        w.Write()
    else:
        np.savetxt(path, pts, fmt="%.6f")

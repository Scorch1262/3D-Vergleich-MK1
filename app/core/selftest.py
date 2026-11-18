"""Selbsttest der Kernlogik: bekannte Transformation muss wiedergefunden werden."""
import os
import tempfile

import numpy as np

from vtkmodules.vtkFiltersSources import vtkCubeSource, vtkCylinderSource, vtkSphereSource
from vtkmodules.vtkFiltersCore import vtkAppendPolyData, vtkTriangleFilter, vtkCleanPolyData
from vtkmodules.util import numpy_support as nps

from .geometry import Geometry, faces_from_polydata
from .io_loader import load_file, save_geometry
from .deviation import run_compare
from .registration import to_matrix


def make_part():
    """Asymmetrisches Testteil: Quader + Zylinder + Kugel."""
    cube = vtkCubeSource()
    cube.SetXLength(60); cube.SetYLength(30); cube.SetZLength(12)
    cyl = vtkCylinderSource()
    cyl.SetRadius(6); cyl.SetHeight(25); cyl.SetCenter(18, 20, 0); cyl.SetResolution(48)
    sph = vtkSphereSource()
    sph.SetRadius(7); sph.SetCenter(-22, -5, 8); sph.SetThetaResolution(40); sph.SetPhiResolution(30)
    app = vtkAppendPolyData()
    for s in (cube, cyl, sph):
        s.Update()
        t = vtkTriangleFilter(); t.SetInputData(s.GetOutput()); t.Update()
        app.AddInputData(t.GetOutput())
    app.Update()
    cl = vtkCleanPolyData(); cl.SetInputData(app.GetOutput()); cl.Update()
    pd = cl.GetOutput()
    pts = nps.vtk_to_numpy(pd.GetPoints().GetData()).astype(np.float64)
    return pts, faces_from_polydata(pd)


def rot(ax, ay, az):
    ax, ay, az = np.radians([ax, ay, az])
    rx = np.array([[1, 0, 0], [0, np.cos(ax), -np.sin(ax)], [0, np.sin(ax), np.cos(ax)]])
    ry = np.array([[np.cos(ay), 0, np.sin(ay)], [0, 1, 0], [-np.sin(ay), 0, np.cos(ay)]])
    rz = np.array([[np.cos(az), -np.sin(az), 0], [np.sin(az), np.cos(az), 0], [0, 0, 1]])
    return rz @ ry @ rx


def run(verbose=True):
    ok = True
    pts, faces = make_part()
    tmp = tempfile.mkdtemp()
    a = Geometry("ref.stl", "", pts, faces)
    pa = os.path.join(tmp, "ref.stl")
    save_geometry(a, pa)
    a = load_file(pa)
    a.prepare_display()

    m = to_matrix(rot(35, -20, 110), np.array([40.0, -15.0, 7.0]))
    pts_b = pts @ m[:3, :3].T + m[:3, 3]
    b = Geometry("test.stl", "", pts_b, faces)
    pb = os.path.join(tmp, "test.stl")
    save_geometry(b, pb)
    b = load_file(pb)
    b.prepare_display()
    res = run_compare(a, b, "auto", False, "Schnell")
    tot, ab, ba = res.match(0.05)
    rec = res.stats_b.max_abs
    if verbose:
        print("Netz/Netz  match@0.05:", round(tot, 2), " max|dev|:", round(rec, 5), res.reg_info)
    ok &= tot > 99.0 and rec < 0.05

    # Punktwolke mit Rauschen + lokaler Beule
    rng = np.random.default_rng(1)
    cloud = a.sample(60000, rng)
    bump = np.linalg.norm(cloud - np.array([0, 0, 6]), axis=1) < 8
    cloud[bump, 2] += 0.8
    cloud += rng.normal(0, 0.01, cloud.shape)
    cloud = cloud @ m[:3, :3].T + m[:3, 3]
    pc = os.path.join(tmp, "scan.xyz")
    np.savetxt(pc, cloud, fmt="%.5f")
    c = load_file(pc)
    res2 = run_compare(a, c, "auto", False, "Schnell")
    tot2, _, _ = res2.match(0.1)
    if verbose:
        print("Netz/Wolke match@0.1:", round(tot2, 2), " max dev:", round(res2.stats_b.max, 3),
              " mean:", round(res2.stats_b.mean, 4))
    ok &= tot2 > 90.0 and 0.6 < res2.stats_b.max < 1.0

    # Teil-Scan (nur ein Teil des Objekts erfasst)
    cen = cloud.mean(0)
    u = np.linalg.svd(cloud - cen, full_matrices=False)[2][0]
    part = cloud[(cloud - cen) @ u > -5]
    pp = os.path.join(tmp, "teil.xyz")
    np.savetxt(pp, part, fmt="%.5f")
    d = load_file(pp)
    res3 = run_compare(a, d, "auto", False, "Schnell")
    _, ba3, _ = res3.match(0.1)
    if verbose:
        print("Teil-Scan  B in Tol.@0.1:", round(ba3, 2))
    ok &= ba3 > 90.0
    print("SELBSTTEST", "OK" if ok else "FEHLER", flush=True)
    return ok


"""Automatische Ausrichtung: Grobausrichtung (Schwerpunkt + Hauptachsen, 24 Lagen)
und Feinausrichtung (getrimmtes ICP, optional mit Skalierung)."""
from __future__ import annotations

from itertools import permutations, product

import numpy as np
from scipy.spatial import cKDTree


def _signed_perms():
    mats = []
    for p in permutations(range(3)):
        for s in product([1, -1], repeat=3):
            m = np.zeros((3, 3))
            for i in range(3):
                m[i, p[i]] = s[i]
            if np.linalg.det(m) > 0:
                mats.append(m)
    return mats


PERMS = _signed_perms()  # 24 eigentliche Drehungen des Wuerfels


def umeyama(src, dst, with_scale=False):
    mu_s, mu_d = src.mean(0), dst.mean(0)
    xs, xd = src - mu_s, dst - mu_d
    cov = xd.T @ xs / len(src)
    u, s, vt = np.linalg.svd(cov)
    d = np.eye(3)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        d[2, 2] = -1
    r = u @ d @ vt
    if with_scale:
        var_s = (xs ** 2).sum() / len(src)
        sc = float(np.trace(np.diag(s) @ d) / var_s) if var_s > 0 else 1.0
    else:
        sc = 1.0
    t = mu_d - sc * r @ mu_s
    return r, t, sc


def to_matrix(r, t, s=1.0):
    m = np.eye(4)
    m[:3, :3] = s * r
    m[:3, 3] = t
    return m


def apply(m, p):
    return p @ m[:3, :3].T + m[:3, 3]


def _pca(p):
    c = p.mean(0)
    cov = np.cov((p - c).T)
    w, v = np.linalg.eigh(cov)
    order = np.argsort(w)[::-1]
    w, v = w[order], v[:, order]
    if np.linalg.det(v) < 0:
        v[:, 2] *= -1
    return c, v, w


def _rodrigues(w):
    th = np.linalg.norm(w)
    if th < 1e-12:
        return np.eye(3)
    k = w / th
    kx = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(th) * kx + (1 - np.cos(th)) * kx @ kx


def icp(src, dst, tree, m0, iters=40, trim=0.9, with_scale=False, eps=1e-6, diag=1.0, dst_normals=None):
    """Getrimmtes ICP. Mit Normalen der Referenz: Punkt-zu-Ebene (konvergiert deutlich besser,
    v. a. bei Teil-Scans und duenn abgetasteten CAD-Flaechen), sonst Punkt-zu-Punkt."""
    m = m0.copy()
    prev = None
    rms = np.inf
    plane = dst_normals is not None and not with_scale
    for _ in range(iters):
        cur = apply(m, src)
        d, idx = tree.query(cur, workers=-1)
        thr = np.quantile(d, trim)
        keep = d <= thr
        if keep.sum() < 10:
            keep = np.ones(len(d), bool)
        p = cur[keep]
        q = dst[idx[keep]]
        if plane:
            n = dst_normals[idx[keep]]
            c = p.mean(0)
            pc = p - c
            a = np.hstack([np.cross(pc, n), n])
            b = np.einsum("ij,ij->i", q - p, n)
            try:
                x, *_ = np.linalg.lstsq(a, b, rcond=None)
            except np.linalg.LinAlgError:
                x = np.zeros(6)
            r = _rodrigues(x[:3])
            t = c + x[3:] - r @ c
            step = to_matrix(r, t)
            res = np.abs(b)
        else:
            r, t, sc = umeyama(p, q, with_scale)
            step = to_matrix(r, t, sc)
            res = d[keep]
        m = step @ m
        rms = float(np.sqrt(np.mean(res ** 2)))
        if prev is not None and abs(prev - rms) < eps * diag:
            break
        prev = rms
    return m, rms


def icp_scale_sym(src, dst, tree_dst, m0, iters=30, eps=1e-8, diag=1.0):
    """Skalierung + Lage mit beidseitigen Zuordnungen (B->A und A->B), damit B nicht
    'zusammenschrumpft' – das passiert bei einseitigem ICP mit Skalierung."""
    m = m0.copy()
    prev = None
    rms = np.inf
    for _ in range(iters):
        cur = apply(m, src)
        d1, i1 = tree_dst.query(cur, workers=-1)
        t_src = cKDTree(cur)
        d2, i2 = t_src.query(dst, workers=-1)
        k1 = d1 <= np.quantile(d1, 0.9)
        k2 = d2 <= np.quantile(d2, 0.9)
        p = np.vstack([cur[k1], cur[i2[k2]]])
        q = np.vstack([dst[i1[k1]], dst[k2]])
        r, t, sc = umeyama(p, q, True)
        m = to_matrix(r, t, sc) @ m
        rms = float(np.sqrt(0.5 * (np.mean(d1[k1] ** 2) + np.mean(d2[k2] ** 2))))
        if prev is not None and abs(prev - rms) < eps * diag:
            break
        prev = rms
    return m, rms


def _score(src_t, dst, tree_dst, thr, sym=False):
    """Bewertung einer Lage: vor allem, wie viel von B auf A liegt (B darf ein Teil-Scan sein),
    zusaetzlich etwas Gewicht auf die Abdeckung von A."""
    d1, _ = tree_dst.query(src_t, workers=-1)
    tree_s = cKDTree(src_t)
    d2, _ = tree_s.query(dst, workers=-1)
    f1 = np.mean(d1 <= thr)
    f2 = np.mean(d2 <= thr)
    if sym:
        return 0.5 * (f1 + f2), float(np.sqrt(np.mean(d1 ** 2)))
    return 0.8 * f1 + 0.2 * f2, float(np.sqrt(np.mean(d1 ** 2)))


def register(ref_samples: np.ndarray, mov_samples: np.ndarray, mode: str = "auto",
             with_scale: bool = False, progress=None, rng=None, ref_normals: np.ndarray | None = None):
    """Liefert 4x4-Matrix, die das bewegliche Objekt (B) auf die Referenz (A) legt.

    mode: "auto" (grob + fein), "fine" (nur ICP aus aktueller Lage), "none".
    """
    rng = rng or np.random.default_rng(0)
    info = {"mode": mode, "candidate": "-", "rms": None, "score": None}
    if mode == "none":
        return np.eye(4), info

    def prog(v, txt):
        if progress:
            progress(v, txt)

    lo, hi = ref_samples.min(0), ref_samples.max(0)
    diag = float(np.linalg.norm(hi - lo)) or 1.0

    def sub(p, n, nrm=None):
        if len(p) <= n:
            return (p, nrm) if nrm is not None else p
        i = rng.choice(len(p), n, replace=False)
        return (p[i], nrm[i]) if nrm is not None else p[i]

    def sub_n(n):
        if ref_normals is None:
            return sub(ref_samples, n), None
        return sub(ref_samples, n, ref_normals)

    m_best = np.eye(4)
    if mode == "auto":
        dst_c, nrm_c = sub_n(8000)
        src_c = sub(mov_samples, 2000)
        tree_c = cKDTree(dst_c)
        cs, vs, ws = _pca(mov_samples)
        cd, vd, wd = _pca(ref_samples)
        s0 = 1.0
        scales = [1.0]
        if with_scale and ws.sum() > 0:
            s0 = float(np.sqrt(wd.sum() / ws.sum()))
            units = [1.0, 25.4, 1 / 25.4, 10.0, 0.1, 1000.0, 0.001, 2.54, 1 / 2.54]
            snap = min(units, key=lambda u: abs(np.log(u / s0)))
            scales = sorted({round(x, 9) for x in (s0, snap, 1.0)})
        cands = [("Originallage", np.eye(4))]
        for sc_ in scales:
            cands.append((f"Schwerpunkt ×{sc_:g}", to_matrix(np.eye(3), cd - sc_ * cs, sc_)))
        # Ist B nur ein Teil von A (Teil-Scan), liegt sein Schwerpunkt nicht im Schwerpunkt von A:
        # deshalb zusaetzlich versetzte Startpunkte entlang der Hauptachsen von A testen.
        ext = np.sqrt(np.maximum(wd, 0)) * 1.2
        size_ratio = np.sqrt(ws.sum() / wd.sum()) * s0 if wd.sum() > 0 else 1.0
        offsets = [("", np.zeros(3))]
        if size_ratio < 0.9:
            for ax in range(2):
                for sg in (-1, 1):
                    offsets.append((f" Versatz {'+' if sg > 0 else '-'}{'XY'[ax]}", vd[:, ax] * ext[ax] * sg))
        for sc_ in scales:
            stxt = f" ×{sc_:g}" if len(scales) > 1 else ""
            for i, p in enumerate(PERMS):
                r = vd @ p @ vs.T
                for oname, off in offsets:
                    cands.append((f"Hauptachsen #{i + 1}{oname}{stxt}",
                                  to_matrix(r, cd + off - sc_ * r @ cs, sc_)))
        thr = 0.015 * diag
        best = (-1, np.inf)
        scored = []
        for k, (name, m0) in enumerate(cands):
            if k % 4 == 0:
                prog(5 + int(40 * k / len(cands)), f"Grobausrichtung {k + 1}/{len(cands)}")
            m, rms = icp(src_c, dst_c, tree_c, m0, iters=12, trim=0.8,
                         with_scale=False, diag=diag, dst_normals=nrm_c)
            sc, _ = _score(apply(m, src_c), dst_c, tree_c, thr, sym=with_scale)
            scored.append((sc, rms, name, m))
        # die besten Kandidaten nochmals laenger verfeinern
        scored.sort(key=lambda x: (-x[0], x[1]))
        for k, (_, _, name, m0) in enumerate(scored[:6]):
            prog(46 + k, "Grobausrichtung verfeinern")
            m, rms = icp(src_c, dst_c, tree_c, m0, iters=40, trim=0.8,
                         with_scale=False, diag=diag, dst_normals=nrm_c)
            if with_scale:
                m, rms = icp_scale_sym(src_c, dst_c, tree_c, m, iters=25, diag=diag)
            sc, _ = _score(apply(m, src_c), dst_c, tree_c, thr * 0.4, sym=with_scale)
            if sc > best[0] + 1e-9 or (abs(sc - best[0]) < 1e-9 and rms < best[1]):
                best = (sc, rms)
                m_best = m
                info["candidate"] = name
    prog(55, "Feinausrichtung (ICP)")
    dst_f, nrm_f = sub_n(80000)
    src_f = sub(mov_samples, 25000)
    tree_f = cKDTree(dst_f)
    if with_scale:
        m, rms = icp_scale_sym(src_f, dst_f, tree_f, m_best, iters=60, eps=1e-8, diag=diag)
        prog(65, "Feinausrichtung (Verfeinerung)")
    m, rms = icp(src_f, dst_f, tree_f, m if with_scale else m_best, iters=60, trim=0.85,
                 with_scale=False, eps=1e-7, diag=diag, dst_normals=nrm_f)
    prog(67, "Feinausrichtung (Verfeinerung)")
    m, rms = icp(src_f, dst_f, tree_f, m, iters=40, trim=0.95,
                 with_scale=False, eps=1e-8, diag=diag, dst_normals=nrm_f)
    sc, _ = _score(apply(m, src_f), dst_f, tree_f, 0.01 * diag)
    info["rms"] = rms
    info["score"] = sc
    return m, info


def decompose(m: np.ndarray):
    """Rotation (Euler XYZ in Grad), Verschiebung, Skalierung."""
    a = m[:3, :3]
    s = float(np.cbrt(np.linalg.det(a))) if np.linalg.det(a) > 0 else 1.0
    r = a / s
    sy = np.hypot(r[0, 0], r[1, 0])
    if sy > 1e-6:
        rx = np.degrees(np.arctan2(r[2, 1], r[2, 2]))
        ry = np.degrees(np.arctan2(-r[2, 0], sy))
        rz = np.degrees(np.arctan2(r[1, 0], r[0, 0]))
    else:
        rx = np.degrees(np.arctan2(-r[1, 2], r[1, 1]))
        ry = np.degrees(np.arctan2(-r[2, 0], sy))
        rz = 0.0
    return (rx, ry, rz), m[:3, 3].copy(), s

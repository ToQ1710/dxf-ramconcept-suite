#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
DXF -> RAM Concept 2023 | Point / Line Load Importer
====================================================
Doc tai tu DXF tren layer RUNLENGTH:
  - POINT LOAD  = LEADER (1 mui ten)    -> vi tri = dau mui ten
  - LINE  LOAD  = DIMENSION (2 mui ten) -> doan tai = 2 diem do (defpoint2/3)
Gia tri SDL/LL = cap so xep doc tren layer TEXT_35 (so tren = SDL, so duoi = LL).

Hien so do san (SLAB EDGE) + cot/vach over (C-W OVER) lam context de canh.
Snap:
  - point load -> tam COT tren "column-over layer" ma mui ten chi vao
  - line  load -> doan VACH tren "wall-over layer" gan nhat
Gan vao 2 lop force loading: SDL -> "SI Dead Loading", LL -> "Live (Reducible) Loading".
Fz duong (giu nguyen do lon nhu ghi tren ban ve).
"""

import os
import sys
import math
import re
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

DEFAULT_GEOM_LAYER = "RUNLENGTH"
DEFAULT_TEXT_LAYER = "TEXT_35"
DEFAULT_COL_LAYER  = "CO OVER"
DEFAULT_WALL_LAYER = "WALL OVER"
DEFAULT_EDGE_LAYER = "SLAB EDGE"
DEFAULT_SDL_LAYER  = "SI Dead Loading"
DEFAULT_LL_LAYER   = "Live (Reducible) Loading"

SNAP_COL_R  = 2000.0   # ban kinh tim tam cot quanh dau mui ten (DXF units)
SNAP_WALL_R = 1500.0   # ban kinh snap dau line load vao dinh vach

RAM_API_PATH = r"C:\Program Files\Bentley\Engineering\RAM Concept\RAM Concept 2023\python"
if RAM_API_PATH not in sys.path:
    sys.path.insert(0, RAM_API_PATH)


# =============================================================================
# GEOMETRY HELPERS
# =============================================================================
def _centroid(pts):
    n = len(pts)
    return (sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n)


def _point_in_poly(x, y, poly):
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]; xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and \
           (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def _bbox(pts):
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _pca_axis(pts):
    """Truc chinh (huong dai nhat) cua tap diem -> (centroid, unit_vector)."""
    n = len(pts)
    cx = sum(p[0] for p in pts) / n
    cy = sum(p[1] for p in pts) / n
    sxx = sum((p[0] - cx) ** 2 for p in pts)
    syy = sum((p[1] - cy) ** 2 for p in pts)
    sxy = sum((p[0] - cx) * (p[1] - cy) for p in pts)
    theta = 0.5 * math.atan2(2 * sxy, sxx - syy)
    return (cx, cy), (math.cos(theta), math.sin(theta))


def _wall_model(pts):
    """Duong tam (centerline) cua 1 polyline vach (hcn dai).
    Tra ve {c,u,tmin,tmax} hoac None neu khong phai vach (qua vuong/ngan = cot)."""
    if len(pts) < 3:
        return None
    (cx, cy), (ux, uy) = _pca_axis(pts)
    ts = [(p[0] - cx) * ux + (p[1] - cy) * uy for p in pts]
    ss = [-(p[0] - cx) * uy + (p[1] - cy) * ux for p in pts]
    length = max(ts) - min(ts)
    width = max(ss) - min(ss)
    if length < 200 or width < 1e-6 or length / width < 2.0:
        return None
    return {"c": (cx, cy), "u": (ux, uy), "tmin": min(ts), "tmax": max(ts)}


try:
    from ezdxf.math import bulge_to_arc as _bulge_to_arc
except Exception:
    _bulge_to_arc = None


def _flatten_xyb(verts, closed, max_chord=150.0):
    """verts=[(x,y,bulge)] -> (FP diem da lam phang cung, vidx[k]=index cua dinh k trong FP)."""
    n = len(verts)
    FP = []; vidx = []
    cnt = n if closed else n - 1
    for i in range(n):
        vidx.append(len(FP))
        x1, y1, b = verts[i]
        FP.append((x1, y1))
        if i >= cnt:
            continue
        j = (i + 1) % n
        x2, y2 = verts[j][0], verts[j][1]
        if abs(b) > 1e-6 and _bulge_to_arc:
            try:
                center, _a0, _a1, R = _bulge_to_arc((x1, y1), (x2, y2), b)
                theta = 4.0 * math.atan(b)
                if R > 1e-9:
                    cx, cy = center.x, center.y
                    a0 = math.atan2(y1 - cy, x1 - cx)
                    npn = max(1, int(abs(R * theta) / max_chord))
                    for k in range(1, npn):
                        a = a0 + theta * k / npn
                        FP.append((cx + R * math.cos(a), cy + R * math.sin(a)))
            except Exception:
                pass
    return FP, vidx


def _fp_slice(FP, s, e):
    M = len(FP); out = [FP[s]]; i = s
    while i != e:
        i = (i + 1) % M
        out.append(FP[i])
    return out


def _polyline_len(pts):
    return sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
               for i in range(len(pts) - 1))


def _sample_polyline(pts, t):
    if len(pts) == 1:
        return pts[0]
    total = _polyline_len(pts)
    if total < 1e-9:
        return pts[0]
    target = t * total; acc = 0.0
    for i in range(len(pts) - 1):
        seg = math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
        if acc + seg >= target:
            f = (target - acc) / (seg or 1e-9)
            return (pts[i][0] + f * (pts[i + 1][0] - pts[i][0]),
                    pts[i][1] + f * (pts[i + 1][1] - pts[i][1]))
        acc += seg
    return pts[-1]


def _outline_centerline(verts, closed):
    """verts=[(x,y,bulge)] outline vach -> duong tam (polyline).
    Vach thang -> [mid1, mid2]; vach cong (co bulge) -> nhieu diem om theo cung."""
    n = len(verts)
    if n < 3:
        return None

    def elen(i):
        j = (i + 1) % n
        return math.hypot(verts[j][0] - verts[i][0], verts[j][1] - verts[i][1])

    cnt = n if closed else n - 1
    straight = sorted((elen(i), i) for i in range(cnt) if abs(verts[i][2]) <= 1e-6)
    if len(straight) < 2:
        return None
    e1, e2 = sorted([straight[0][1], straight[1][1]])
    if e1 == e2:
        return None

    def emid(i):
        j = (i + 1) % n
        return ((verts[i][0] + verts[j][0]) / 2, (verts[i][1] + verts[j][1]) / 2)

    mid1, mid2 = emid(e1), emid(e2)
    if not any(abs(verts[i][2]) > 1e-6 for i in range(cnt)):
        return [mid1, mid2]                       # vach thang -> 1 doan

    FP, vidx = _flatten_xyb(verts, closed)
    faceA = _fp_slice(FP, vidx[(e1 + 1) % n], vidx[e2])
    faceB = list(reversed(_fp_slice(FP, vidx[(e2 + 1) % n], vidx[e1])))
    if not faceA or not faceB:
        return [mid1, mid2]
    N = max(2, int(min(_polyline_len(faceA), _polyline_len(faceB)) / 200.0))
    center = [mid1]
    for k in range(1, N):
        t = k / N
        pa = _sample_polyline(faceA, t); pb = _sample_polyline(faceB, t)
        center.append(((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2))
    center.append(mid2)
    return center


# =============================================================================
# PARSE
# =============================================================================
def _numeric_texts(msp, text_layer):
    out = []
    for e in msp:
        if e.dxf.layer != text_layer:
            continue
        if e.dxftype() == "TEXT":
            s = e.dxf.text.strip()
            if re.fullmatch(r"\d+(\.\d+)?", s):
                out.append((e.dxf.insert.x, e.dxf.insert.y, float(s)))
    return out


_OVER_RE = re.compile(r"^\s*(DL|LL)\s*=\s*(\d+(?:\.\d+)?)", re.I)


def _ceil5(v):
    """Lam tron LEN boi so cua 5 (vd 9->10, 11/12->15). Giu 0 = 0."""
    if v <= 0:
        return 0.0
    return math.ceil(v / 5.0) * 5.0


def _hungarian(cost):
    """Gan TOI UU (min tong chi phi) bipartite. cost = ma tran n hang (DL text) x
    m cot (leader). Tra ve assign[i] = cot gan cho hang i (-1 neu khong gan).
    Dung de giu DUNG THU TU khi nhieu text/leader xep chong (greedy bi sai)."""
    n = len(cost)
    m = len(cost[0]) if n else 0
    if n == 0 or m == 0:
        return [-1] * n
    INF = float("inf")
    sz = max(n, m)
    C = [[cost[i][j] if i < n and j < m else 0.0 for j in range(sz)] for i in range(sz)]
    u = [0.0] * (sz + 1); v = [0.0] * (sz + 1)
    p = [0] * (sz + 1); way = [0] * (sz + 1)
    for i in range(1, sz + 1):
        p[0] = i; j0 = 0
        minv = [INF] * (sz + 1); used = [False] * (sz + 1)
        while True:
            used[j0] = True; i0 = p[j0]; delta = INF; j1 = -1
            for j in range(1, sz + 1):
                if not used[j]:
                    cur = C[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j] = cur; way[j] = j0
                    if minv[j] < delta:
                        delta = minv[j]; j1 = j
            for j in range(sz + 1):
                if used[j]:
                    u[p[j]] += delta; v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]; p[j0] = p[j1]; j0 = j1
    assign = [-1] * n
    for j in range(1, sz + 1):
        if p[j] != 0 and p[j] - 1 < n and j - 1 < m:
            assign[p[j] - 1] = j - 1
    return assign


def _over_value_texts(msp, text_layer):
    """TEXT dang 'DL=950(kN)' / 'LL=160(kN)' tren text_layer (tai truyen tu cot/vach
    tang tren) -> [(x, y, 'DL'|'LL', value)]. Bo qua MyEQX/MyEQY (moment)."""
    out = []
    for e in msp:
        if e.dxf.layer != text_layer or e.dxftype() != "TEXT":
            continue
        m = _OVER_RE.match(e.dxf.text.strip())
        if m:
            out.append((e.dxf.insert.x, e.dxf.insert.y, m.group(1).upper(), float(m.group(2))))
    return out


def _find_pair(texts, x, y, radius=1800.0, gap_x=400.0, gap_min=200.0, gap_max=900.0):
    """Cap so xep doc gan (x,y). Tra ve (sdl, ll) (tren=SDL, duoi=LL) hoac None."""
    cand = sorted((math.hypot(tx - x, ty - y), tx, ty, v) for tx, ty, v in texts)
    cand = [c for c in cand if c[0] < radius]
    for i in range(len(cand)):
        _, x1, y1, v1 = cand[i]
        for j in range(i + 1, len(cand)):
            _, x2, y2, v2 = cand[j]
            if abs(x1 - x2) < gap_x and gap_min < abs(y1 - y2) < gap_max:
                return (v1, v2) if y1 > y2 else (v2, v1)
    return None


def _all_pairs(texts, gap_x=400.0, gap_min=200.0, gap_max=900.0):
    """Tat ca cap so XEP DOC (SDL tren, LL duoi) tren text layer ->
    [(sdl, ll, x_mid, y_mid)]. Cung tieu chi voi _find_pair. Dung de gan cap gia
    tri cho leader bang Hungarian (moi cap 1 leader) -> tranh 2 leader gan nhau
    cung an 1 cap (vd 250/50 va 550/80)."""
    pairs = []
    n = len(texts)
    for i in range(n):
        xi, yi, vi = texts[i]
        best = None; bestd = 1e18
        for j in range(n):
            if i == j:
                continue
            xj, yj, vj = texts[j]
            if abs(xi - xj) < gap_x and gap_min < (yi - yj) < gap_max:
                if (yi - yj) < bestd:          # LL gan nhat NGAY DUOI SDL
                    bestd = yi - yj
                    best = (vi, vj, (xi + xj) / 2.0, (yi + yj) / 2.0)
        if best is not None:
            pairs.append(best)
    uniq = []
    for p in pairs:                            # dedup theo vi tri
        if not any(abs(p[2] - q[2]) < 1.0 and abs(p[3] - q[3]) < 1.0 for q in uniq):
            uniq.append(p)
    return uniq


def _poly_pts(e, unit=1.0):
    return [(p[0] * unit, p[1] * unit) for p in e.get_points("xy")]


def list_layers(dxf_path):
    import ezdxf
    doc = ezdxf.readfile(dxf_path)
    return sorted(l.dxf.name for l in doc.layers)


def _iter_entities(container, depth=0):
    """Duyet entity, explode INSERT (block/xref) -> tra ve hinh hoc o toa do WORLD.
    Plan (cot/vach/mep san) cua ban ve thuong nam trong block (vd 'L4')."""
    for e in container:
        yield e
        if e.dxftype() == "INSERT" and depth < 4:
            try:
                ves = list(e.virtual_entities())
            except Exception:
                ves = []
            for ve in _iter_entities(ves, depth + 1):
                yield ve


def read_dxf(dxf_path, geom_layer, text_layer, col_layer, wall_layer, edge_layer,
             wall_seg=800.0, unit_scale=0.001):
    """Doc tat ca: tai, cot/vach de snap, va context de ve.
    Tra ve dict {points, lines, columns, walls, context, layers}.
    unit_scale: doi mm DXF -> m (de quy tai truyen DL/LL tong -> kN/m theo chieu dai)."""
    import ezdxf
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    texts = _numeric_texts(msp, text_layer)

    columns = []      # [{'pts','c'}] tren col_layer
    wall_polys = []   # polyline tho tren wall_layer
    context = {"polys": [], "circles": []}   # de ve mo nhat

    ctx_layers = {col_layer, wall_layer, edge_layer}
    for e in _iter_entities(msp):
        ly = e.dxf.layer
        t = e.dxftype()
        if ly in ctx_layers:
            if t == "LWPOLYLINE":
                pts = _poly_pts(e)
                if len(pts) >= 2:
                    context["polys"].append((pts, bool(e.closed)))
            elif t == "LINE":
                context["polys"].append(([(e.dxf.start.x, e.dxf.start.y),
                                          (e.dxf.end.x, e.dxf.end.y)], False))
            elif t == "CIRCLE":
                context["circles"].append((e.dxf.center.x, e.dxf.center.y, e.dxf.radius))
        if ly == col_layer and t == "LWPOLYLINE":
            pts = _poly_pts(e)
            if len(pts) >= 3:
                columns.append({"pts": pts, "c": _centroid(pts)})
        if ly == wall_layer and t == "LWPOLYLINE":
            try:
                vp = list((q[0], q[1], q[2]) for q in e.get_points("xyb"))
            except Exception:
                vp = [(q[0], q[1], 0.0) for q in e.get_points("xy")]
            if len(vp) >= 3:
                wall_polys.append((vp, bool(getattr(e, "closed", False))))

    # duong tam cho moi mieng vach (loc bo cot vuong; vach cong -> nhieu doan)
    wall_segs = []
    wall_cl = []          # (outline_flat, centerline_pts, length) -> cho transfer line load
    for vp, closed in wall_polys:
        flat = [(x, y) for x, y, _b in vp]
        if not _wall_model(flat):          # khong thuon dai -> cot, bo qua
            continue
        cl = _outline_centerline(vp, closed)
        if cl and len(cl) >= 2:
            wall_cl.append((flat, cl, _polyline_len(cl)))
            for i in range(len(cl) - 1):
                a, b = cl[i], cl[i + 1]
                if math.hypot(b[0] - a[0], b[1] - a[1]) > 1e-6:
                    wall_segs.append((a, b))

    # ----- point loads (LEADER): gan cap gia tri TOI UU (Hungarian) -----
    # Moi leader (dau mui ten v[0]) -> 1 cap so RIENG. Tranh 2 leader gan nhau cung
    # an 1 cap (vd cot tren=250/50, cot duoi=550/80 -> truoc day ca 2 deu 250).
    pairs_all = _all_pairs(texts)
    pt_v0 = []
    for e in msp:
        if e.dxf.layer != geom_layer or e.dxftype() != "LEADER":
            continue
        try:
            v = list(e.vertices)
        except Exception:
            continue
        if v:
            pt_v0.append((v[0][0], v[0][1]))
    points = []
    if pt_v0 and pairs_all:
        PR = 1800.0; BIGP = 1e9
        costp = []
        for (lx, ly) in pt_v0:
            row = []
            for (sdl, ll, px, py) in pairs_all:
                dd = math.hypot(lx - px, ly - py)
                row.append(dd if dd <= PR else BIGP)
            costp.append(row)
        ap = _hungarian(costp)
        for li, (lx, ly) in enumerate(pt_v0):
            pj = ap[li]
            if pj < 0 or costp[li][pj] >= BIGP:
                continue
            sdl, ll, px, py = pairs_all[pj]
            sx, sy = _snap_to_column(lx, ly, columns)
            points.append({"x": lx, "y": ly, "sx": sx, "sy": sy,
                           "sdl": sdl, "ll": ll, "snapped": (sx, sy) != (lx, ly)})

    # ----- line loads (DIMENSION) -----
    lines = []
    for e in msp:
        if e.dxf.layer != geom_layer or e.dxftype() != "DIMENSION":
            continue
        d = e.dxf
        try:
            tm = d.text_midpoint
            a = d.defpoint2
            b = d.defpoint3
        except Exception:
            continue
        pr = _find_pair(texts, tm.x, tm.y)
        if not pr:
            continue
        segs, snapped = _snap_line_to_wall(a.x, a.y, b.x, b.y, wall_segs, wall_seg)
        lines.append({"x1": a.x, "y1": a.y, "x2": b.x, "y2": b.y,
                      "segs": segs, "sdl": pr[0], "ll": pr[1], "snapped": snapped})

    # ----- line loads CONG: LWPOLYLINE co bulge tren RUNLENGTH (run-length cung) -----
    for e in _iter_entities(msp):
        if e.dxf.layer != geom_layer or e.dxftype() != "LWPOLYLINE":
            continue
        if getattr(e, "closed", False):
            continue
        try:
            vp = list((q[0], q[1], q[2]) for q in e.get_points("xyb"))
        except Exception:
            continue
        if len(vp) < 2 or not any(abs(p[2]) > 1e-6 for p in vp):
            continue                      # chi nhan path CONG (co cung)
        mx = sum(p[0] for p in vp) / len(vp)
        my = sum(p[1] for p in vp) / len(vp)
        pr = _find_pair(texts, mx, my)
        if not pr:
            continue
        fp, _vi = _flatten_xyb(vp, False)
        a0, b0 = fp[0], fp[-1]
        segs, snapped = _snap_line_to_wall(a0[0], a0[1], b0[0], b0[1], wall_segs, wall_seg)
        if not snapped:                   # khong khop vach -> dung chinh path cung (da flatten)
            segs = _decimate_segments(fp, wall_seg)
        lines.append({"x1": a0[0], "y1": a0[1], "x2": b0[0], "y2": b0[1],
                      "segs": segs, "sdl": pr[0], "ll": pr[1], "snapped": snapped})

    # ----- TRANSFER loads: 'DL=/LL=' + LEADER -> WALL OVER (line) / CO OVER (point) -----
    # Vach over -> line load doc CENTERLINE, gia tri = DL/chieu-dai (kN/m).
    # Cot  over -> point load tai TAM cot, gia tri = DL (kN).
    over = _over_value_texts(msp, text_layer)
    dls = [(x, y, v) for x, y, k, v in over if k == "DL"]
    lls = [(x, y, v) for x, y, k, v in over if k == "LL"]
    leads = []
    for e in msp:
        if e.dxf.layer != geom_layer or e.dxftype() != "LEADER":
            continue
        try:
            vv = [(p[0], p[1]) for p in e.vertices]
        except Exception:
            vv = []
        if len(vv) >= 2:
            leads.append(vv)

    def _wall_hit(p):
        """(dist, (cl,L)) toi WALL OVER gan nhat (dung khoang cach toi CANH)."""
        best = (1e18, None)
        for flat, cl, L in wall_cl:
            if _point_in_poly(p[0], p[1], flat):
                return (0.0, (cl, L))
            dd = min(math.hypot(p[0] - q[0], p[1] - q[1])
                     for i in range(len(flat))
                     for q in (_nearest_point_on_seg(p[0], p[1],
                               flat[i][0], flat[i][1],
                               flat[(i + 1) % len(flat)][0], flat[(i + 1) % len(flat)][1]),))
            if dd < best[0]:
                best = (dd, (cl, L))
        return best

    def _col_hit(p):
        best = (1e18, None)
        for col in columns:
            dd = 0.0 if _point_in_poly(p[0], p[1], col["pts"]) \
                else math.hypot(p[0] - col["c"][0], p[1] - col["c"][1])
            if dd < best[0]:
                best = (dd, col)
        return best

    # LEADER-CENTRIC: voi MOI leader, MUI TEN = dau NAM TREN cau kien (WALL/CO OVER),
    # TAIL = dau con lai (canh khoi text DL=/LL=). Leader cua RUN-LENGTH point load
    # (mui ten co CAP SO ben canh) bi PHAT (uu tien leader sach) nhung VAN dung lam
    # fallback -> giu duoc DL ma vach no chi vao bi crowd boi run-length (vd DL=500).
    TOL = 800.0; R = 3500.0; PAIR_PEN = 1e5; BIG = 1e9
    tlead = []                                    # (tail, kind, ref, has_pair)
    for vv in leads:
        e0, e1 = vv[0], vv[-1]
        w0, wr0 = _wall_hit(e0); c0, cr0 = _col_hit(e0)
        w1, wr1 = _wall_hit(e1); c1, cr1 = _col_hit(e1)
        el0 = min(w0, c0); el1 = min(w1, c1)
        if min(el0, el1) > TOL:                   # khong dau nao cham cau kien
            continue
        if el0 <= el1:
            arrow, tail, wd, wr, cd, cr = e0, e1, w0, wr0, c0, cr0
        else:
            arrow, tail, wd, wr, cd, cr = e1, e0, w1, wr1, c1, cr1
        has_pair = _find_pair(texts, arrow[0], arrow[1]) is not None
        if wr is not None and wd <= cd:
            tlead.append((tail, "wall", wr, has_pair, arrow))
        elif cr is not None:
            tlead.append((tail, "col", cr, has_pair, arrow))

    # Gan TOI UU (Hungarian) -> giu dung thu tu khi text/leader xep chong (vd DL=146
    # vach tren, DL=9 vach giua, DL=746 vach duoi). Chi phi = tail_dist + phat cap so.
    n_tw = n_tc = n_tn = 0
    if dls and tlead:
        cost = []
        for (dx, dy, _dv) in dls:
            row = []
            for (tail, kind, ref, hp, arrow) in tlead:
                td = math.hypot(tail[0] - dx, tail[1] - dy)
                row.append(BIG if td > R else td + (PAIR_PEN if hp else 0.0))
            cost.append(row)
        assign = _hungarian(cost)
    else:
        assign = [-1] * len(dls)

    used_arrows = []                              # mui ten leader da dung cho transfer
    for di, lj in enumerate(assign):
        if lj < 0 or cost[di][lj] >= BIG:         # khong co leader hop le trong R
            n_tn += 1
            continue
        tail, kind, ref, hp, arrow = tlead[lj]
        used_arrows.append(arrow)
        dx, dy, dl_val = dls[di]
        ll_val = 0.0
        if lls:
            lx, ly, lv = min(lls, key=lambda L: math.hypot(L[0] - dx, L[1] - dy))
            if math.hypot(lx - dx, ly - dy) < 1200:
                ll_val = lv
        if kind == "wall":
            cl, L = ref
            Lm = max(L * unit_scale, 1e-6)        # chieu dai tuong (m)
            segs = [(cl[i], cl[i + 1]) for i in range(len(cl) - 1)
                    if math.hypot(cl[i + 1][0] - cl[i][0], cl[i + 1][1] - cl[i][1]) > 1e-6]
            # gia tri kN/m sau khi chia chieu dai -> lam tron LEN boi so cua 5
            lines.append({"x1": cl[0][0], "y1": cl[0][1], "x2": cl[-1][0], "y2": cl[-1][1],
                          "segs": segs, "sdl": _ceil5(dl_val / Lm), "ll": _ceil5(ll_val / Lm),
                          "snapped": True, "transfer": True})
            n_tw += 1
        else:
            sx, sy = ref["c"]
            points.append({"x": sx, "y": sy, "sx": sx, "sy": sy,
                           "sdl": dl_val, "ll": ll_val, "snapped": True, "transfer": True})
            n_tc += 1

    # Leader da dung cho TRANSFER thi KHONG de point load run-length trung tai mui
    # ten do (vd DL=500 da la line load -> bo point Fz=200 sinh ra tu cung leader).
    if used_arrows:
        kept = []
        for p in points:
            if not p.get("transfer") and any(
                    math.hypot(p["x"] - ax, p["y"] - ay) < 60 for ax, ay in used_arrows):
                continue
            kept.append(p)
        points = kept

    return {"points": points, "lines": lines, "columns": columns,
            "walls": wall_segs, "context": context,
            "transfer": {"wall": n_tw, "col": n_tc, "unmatched": n_tn},
            "layers": sorted(l.dxf.name for l in doc.layers)}


def _snap_to_column(tx, ty, columns):
    """Tra ve tam cot chua/gan dau mui ten; neu khong co -> giu nguyen (tx,ty)."""
    # uu tien cot chua diem
    for col in columns:
        if _point_in_poly(tx, ty, col["pts"]):
            return col["c"]
    # khong thi lay tam cot gan nhat trong ban kinh
    best = None; bd = SNAP_COL_R ** 2
    for col in columns:
        cx, cy = col["c"]
        d = (cx - tx) ** 2 + (cy - ty) ** 2
        if d < bd:
            bd = d; best = col["c"]
    return best if best else (tx, ty)


def _nearest_point_on_seg(px, py, ax, ay, bx, by, clamp=True):
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 < 1e-9:
        return ax, ay
    t = ((px - ax) * dx + (py - ay) * dy) / L2
    if clamp:
        t = max(0.0, min(1.0, t))
    return ax + t * dx, ay + t * dy


def _unit(p, q):
    L = math.hypot(q[0] - p[0], q[1] - p[1])
    return (0.0, 0.0) if L < 1e-9 else ((q[0] - p[0]) / L, (q[1] - p[1]) / L)


def _chain_walls(start, wall_segs, tol=300.0, max_turn_deg=40.0):
    """Noi cac doan tam vach lien nhau (dau gan nhau + huong lien tuc, goc re < max_turn)
    thanh 1 duong tam (polyline) -> om theo vach cong. Dung o goc gap (L/T)."""
    cosmin = math.cos(math.radians(max_turn_deg))
    used = {start}
    a, b = wall_segs[start]
    chain = [a, b]

    def extend(cur, d, prepend):
        while True:
            found = None
            for i, (p, q) in enumerate(wall_segs):
                if i in used:
                    continue
                for e0, e1 in ((p, q), (q, p)):
                    if math.hypot(e0[0] - cur[0], e0[1] - cur[1]) <= tol:
                        nd = _unit(cur, e1)
                        if nd != (0.0, 0.0) and d[0] * nd[0] + d[1] * nd[1] >= cosmin:
                            found = (i, e1, nd); break
                if found:
                    break
            if not found:
                break
            i, e1, nd = found
            used.add(i)
            if prepend:
                chain.insert(0, e1)
            else:
                chain.append(e1)
            cur = e1; d = nd

    extend(b, _unit(a, b), prepend=False)
    extend(a, _unit(b, a), prepend=True)
    return chain


def _decimate_segments(poly, min_len):
    """Chia polyline thanh cac doan THANG, moi doan (day cung) >= min_len."""
    if len(poly) < 2:
        return []
    keep = [poly[0]]
    for p in poly[1:]:
        if math.hypot(p[0] - keep[-1][0], p[1] - keep[-1][1]) >= min_len:
            keep.append(p)
    if keep[-1] != poly[-1]:
        if len(keep) >= 2 and math.hypot(poly[-1][0] - keep[-1][0],
                                         poly[-1][1] - keep[-1][1]) < min_len:
            keep[-1] = poly[-1]          # gop doan duoi ngan vao doan truoc
        else:
            keep.append(poly[-1])
    return [(keep[i], keep[i + 1]) for i in range(len(keep) - 1)]


def _snap_line_to_wall(ax, ay, bx, by, wall_segs, wall_seg):
    """Tra ve (list_doan_thang, snapped).
    - Tim doan vach gan & song song nhat voi tai -> noi chuoi vach (om vach cong)
      -> chia thanh cac doan >= wall_seg, nam tren duong tam vach.
    - Khong tim duoc -> giu nguyen doan tai goc."""
    orig_len = math.hypot(bx - ax, by - ay)
    if orig_len < 1e-9 or not wall_segs:
        return [((ax, ay), (bx, by))], False
    dxn, dyn = (bx - ax) / orig_len, (by - ay) / orig_len
    mx, my = (ax + bx) / 2, (ay + by) / 2
    best = -1; bd = SNAP_WALL_R ** 2
    for i, (p, q) in enumerate(wall_segs):
        ux, uy = _unit(p, q)
        if abs(dxn * ux + dyn * uy) < 0.7:        # khong song song -> bo (tranh vach vuong goc)
            continue
        qx, qy = _nearest_point_on_seg(mx, my, p[0], p[1], q[0], q[1])
        d = (qx - mx) ** 2 + (qy - my) ** 2
        if d < bd:
            bd = d; best = i
    if best < 0:
        return [((ax, ay), (bx, by))], False
    poly = _chain_walls(best, wall_segs)
    segs = _decimate_segments(poly, wall_seg)
    if not segs:
        return [((ax, ay), (bx, by))], False
    return segs, True


# =============================================================================
# IMPORT INTO RAM CONCEPT
# =============================================================================
def import_loads(cpt_path, points, lines, sdl_layer_name, ll_layer_name,
                 scale, ox, oy, log_fn, done_fn):
    try:
        from ram_concept.concept import Concept
        from ram_concept.point_2D import Point2D
        from ram_concept.line_segment_2D import LineSegment2D
    except ImportError as exc:
        log_fn(f"[ERROR] Could not load RAM Concept API: {exc}")
        done_fn(False)
        return

    def M(x, y):
        return (x * scale + ox, y * scale + oy)

    log_fn("Starting RAM Concept (headless)...")
    try:
        concept = Concept.start_concept(headless=True)
    except Exception as exc:
        log_fn(f"[ERROR] Could not start RAM Concept: {exc}")
        done_fn(False)
        return
    try:
        log_fn(f"Open file: {cpt_path}")
        model = concept.open_file(cpt_path)
        cad = model.cad_manager
        existing = {ll.name: ll for ll in cad.force_loading_layers}
        log_fn(f"Existing load layers: {list(existing.keys())}")

        def get_layer(name):
            if name in existing:
                return existing[name]
            log_fn(f"  [!] Not found '{name}' -> creating new.")
            ll = cad.add_force_loading_layer(name)
            existing[name] = ll
            return ll

        sdl_layer = get_layer(sdl_layer_name)
        ll_layer = get_layer(ll_layer_name)

        n_p = n_l = n_skip = 0
        for i, p in enumerate(points):
            mx, my = M(p["sx"], p["sy"])
            try:
                if p["sdl"]:
                    pl = sdl_layer.add_point_load(Point2D(mx, my))
                    pl.zero_load_values(); pl.Fz = p["sdl"]; n_p += 1
                if p["ll"]:
                    pl = ll_layer.add_point_load(Point2D(mx, my))
                    pl.zero_load_values(); pl.Fz = p["ll"]; n_p += 1
            except Exception as e:
                n_skip += 1
                msg = (str(e).strip().splitlines() or [repr(e)])[-1]
                log_fn(f"  [skip] point load #{i}: {msg}")

        for i, ln in enumerate(lines):
            for (p1, p2) in ln["segs"]:
                ax, ay = M(p1[0], p1[1]); bx, by = M(p2[0], p2[1])
                if math.hypot(bx - ax, by - ay) < 1e-3:    # doan suy bien -> bo qua
                    n_skip += 1
                    continue
                seg = LineSegment2D(Point2D(ax, ay), Point2D(bx, by))
                try:
                    if ln["sdl"]:
                        load = sdl_layer.add_line_load(seg)
                        load.set_load_values(0.0, 0.0, ln["sdl"], 0.0, 0.0); n_l += 1
                    if ln["ll"]:
                        load = ll_layer.add_line_load(seg)
                        load.set_load_values(0.0, 0.0, ln["ll"], 0.0, 0.0); n_l += 1
                except Exception as e:
                    n_skip += 1
                    msg = (str(e).strip().splitlines() or [repr(e)])[-1]
                    log_fn(f"  [skip] line load #{i} seg: {msg}")

        log_fn(f"\nPoint loads created: {n_p}  |  Line loads created: {n_l}")
        if n_skip:
            log_fn(f"  [!] Skipped {n_skip} load(s) with invalid geometry.")
        log_fn(f"\nSave file: {cpt_path}")
        model.save_file(cpt_path)
        model.close_model()
        log_fn("\n=== DONE ===")
        done_fn(True)
    except Exception as exc:
        import traceback
        log_fn(f"\n[ERROR] {exc}\n{traceback.format_exc()}")
        done_fn(False)
    finally:
        try:
            concept.shut_down()
        except Exception:
            pass


# =============================================================================
# GUI
# =============================================================================
C_POINT   = "#34D399"
C_LINE    = "#FB923C"
C_SLAB    = "#e53935"   # CPT slab outline (target)
C_CTX     = "#3a5a7a"   # DXF context (plan)
C_RAW     = "#64748b"   # raw tip before snap


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("DXF -> RAM Concept 2023 | Point / Line Load Importer")
        self.geometry("1240x820")

        self.points = []
        self.lines = []
        self.context = {"polys": [], "circles": []}
        self.slab_polys = None
        self.slab_bbox = None

        self.vscale = 1.0
        self.tx = 0.0
        self.ty = 0.0
        self._pan = None

        self.align_stage = 0
        self.align_p1 = self.align_q1 = self.align_p2 = None

        self.dxf_path = tk.StringVar()
        self.cpt_path = tk.StringVar()
        self.geom_layer = tk.StringVar(value=DEFAULT_GEOM_LAYER)
        self.text_layer = tk.StringVar(value=DEFAULT_TEXT_LAYER)
        self.col_layer = tk.StringVar(value=DEFAULT_COL_LAYER)
        self.wall_layer = tk.StringVar(value=DEFAULT_WALL_LAYER)
        self.edge_layer = tk.StringVar(value=DEFAULT_EDGE_LAYER)
        self.sdl_layer = tk.StringVar(value=DEFAULT_SDL_LAYER)
        self.ll_layer = tk.StringVar(value=DEFAULT_LL_LAYER)
        self.unit_var = tk.StringVar(value="0.001")
        self.off_x = tk.StringVar(value="0.0")
        self.off_y = tk.StringVar(value="0.0")
        self.wall_seg = tk.StringVar(value="800")   # chia vach cong (mm DXF)

        try:
            import shared_paths
            sp = shared_paths.load_paths()
            if sp.get("dxf"):
                self.dxf_path.set(sp["dxf"])
            if sp.get("cpt"):
                self.cpt_path.set(sp["cpt"])
            if sp.get("scale"):
                self.unit_var.set(str(sp["scale"]))
            if sp.get("ox") is not None:
                self.off_x.set(str(sp["ox"]))
            if sp.get("oy") is not None:
                self.off_y.set(str(sp["oy"]))
        except Exception:
            pass

        for var in (self.unit_var, self.off_x, self.off_y):
            var.trace_add("write", lambda *a: self._save_transform())

        self._build_ui()

    def _save_transform(self):
        try:
            import shared_paths
            shared_paths.save_transform(
                scale=float(self.unit_var.get()),
                ox=float(self.off_x.get()),
                oy=float(self.off_y.get()))
        except Exception:
            pass

    # ---------------- UI ----------------
    def _build_ui(self):
        top = ttk.Frame(self, padding=6)
        top.pack(side=tk.TOP, fill=tk.X)
        f = ttk.LabelFrame(top, text="  Files & Layers  ", padding=6)
        f.pack(fill=tk.X)
        f.columnconfigure(1, weight=1)
        f.columnconfigure(3, weight=1)

        ttk.Label(f, text="DXF file:").grid(row=0, column=0, sticky=tk.W, padx=(0, 6))
        ttk.Entry(f, textvariable=self.dxf_path).grid(row=0, column=1, columnspan=3, sticky=tk.EW)
        ttk.Button(f, text="Browse...", command=self._pick_dxf).grid(row=0, column=4, padx=4)
        ttk.Button(f, text="Detect loads", command=self._detect).grid(row=0, column=5)

        ttk.Label(f, text="CPT file:").grid(row=1, column=0, sticky=tk.W, padx=(0, 6), pady=(6, 0))
        ttk.Entry(f, textvariable=self.cpt_path).grid(row=1, column=1, columnspan=3, sticky=tk.EW, pady=(6, 0))
        ttk.Button(f, text="Browse...", command=self._pick_cpt).grid(row=1, column=4, padx=4, pady=(6, 0))
        ttk.Button(f, text="Read slab", command=self._read_slab).grid(row=1, column=5, pady=(6, 0))

        # layer comboboxes
        self.cb_geom = self._layer_row(f, "Load geometry layer:", self.geom_layer, 2, 0)
        self.cb_text = self._layer_row(f, "Value text layer:", self.text_layer, 2, 2)
        self.cb_col  = self._layer_row(f, "Column-over layer:", self.col_layer, 3, 0)
        self.cb_wall = self._layer_row(f, "Wall-over layer:", self.wall_layer, 3, 2)
        self.cb_edge = self._layer_row(f, "Slab-edge layer:", self.edge_layer, 4, 0)
        # Doi layer cot/vach -> tu Detect lai de SNAP tai vao vi tri moi
        self.cb_col.bind("<<ComboboxSelected>>", lambda e: self._relayer())
        self.cb_wall.bind("<<ComboboxSelected>>", lambda e: self._relayer())
        for cb in (self.cb_col, self.cb_wall):
            cb.bind("<Return>", lambda e: self._relayer())

        ttk.Label(f, text="Unit scale:").grid(row=4, column=2, sticky=tk.E, padx=(10, 4), pady=(6, 0))
        ttk.Entry(f, textvariable=self.unit_var, width=12).grid(row=4, column=3, sticky=tk.W, pady=(6, 0))

        of = ttk.Frame(f)
        of.grid(row=5, column=0, columnspan=6, sticky=tk.W, pady=(6, 0))
        ttk.Label(of, text="Offset X (m):").pack(side=tk.LEFT)
        ttk.Entry(of, textvariable=self.off_x, width=11).pack(side=tk.LEFT, padx=(2, 8))
        ttk.Label(of, text="Y (m):").pack(side=tk.LEFT)
        ttk.Entry(of, textvariable=self.off_y, width=11).pack(side=tk.LEFT, padx=2)
        ttk.Label(of, text="    Curved wall seg (mm):").pack(side=tk.LEFT)
        ttk.Entry(of, textvariable=self.wall_seg, width=8).pack(side=tk.LEFT, padx=2)

        bar = ttk.Frame(top, padding=(0, 6, 0, 0))
        bar.pack(fill=tk.X)
        ttk.Button(bar, text="Fit view", command=self._fit_view).pack(side=tk.LEFT, padx=2)
        self.btn_align = ttk.Button(bar, text="Align 2 points (DXF -> slab)", command=self._start_align)
        self.btn_align.pack(side=tk.LEFT, padx=2)
        self.lbl_count = ttk.Label(bar, text="No data")
        self.lbl_count.pack(side=tk.LEFT, padx=12)
        self.btn_import = ttk.Button(bar, text="  IMPORT POINT/LINE LOADS INTO RAM CONCEPT  ",
                                     command=self._import)
        self.btn_import.pack(side=tk.RIGHT, padx=2)

        mid = ttk.Frame(self)
        mid.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)
        self.canvas = tk.Canvas(mid, bg="#0d1626", highlightthickness=1,
                                highlightbackground="#26395e")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<MouseWheel>", self._on_zoom)
        self.canvas.bind("<ButtonPress-3>", self._pan_start)
        self.canvas.bind("<B3-Motion>", self._pan_move)
        self.canvas.bind("<Button-1>", self._on_click)

        logf = ttk.LabelFrame(self, text="  Log  ", padding=4)
        logf.pack(fill=tk.X, padx=6, pady=(0, 6))
        self.log = scrolledtext.ScrolledText(logf, height=7, font=("Consolas", 9))
        self.log.pack(fill=tk.BOTH, expand=True)

    def _layer_row(self, parent, label, var, row, col):
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky=tk.W,
                                           padx=(0, 4) if col == 0 else (10, 4), pady=(6, 0))
        cb = ttk.Combobox(parent, textvariable=var, width=18)
        cb.grid(row=row, column=col + 1, sticky=tk.W, pady=(6, 0))
        return cb

    def _set_layer_values(self, layers):
        for cb in (self.cb_geom, self.cb_text, self.cb_col, self.cb_wall, self.cb_edge):
            cb["values"] = layers

    # ---------------- file pick ----------------
    def _pick_dxf(self):
        p = filedialog.askopenfilename(title="Select DXF",
                                       filetypes=[("DXF", "*.dxf"), ("All", "*.*")])
        if p:
            self.dxf_path.set(p)

    def _pick_cpt(self):
        p = filedialog.askopenfilename(title="Select CPT",
                                       filetypes=[("RAM Concept", "*.cpt"), ("All", "*.*")])
        if p:
            self.cpt_path.set(p)

    # ---------------- log ----------------
    def _log(self, msg):
        self.log.insert(tk.END, msg + "\n")
        self.log.see(tk.END)

    def _log_safe(self, msg):
        self.after(0, lambda m=msg: self._log(m))

    def _log_clear(self):
        self.log.delete("1.0", tk.END)

    # ---------------- detect ----------------
    def _relayer(self):
        """Doi layer cot/vach-over -> Detect lai de snap tai vao tam vach/cot moi."""
        path = self.dxf_path.get().strip()
        if path and os.path.isfile(path) and (self.points or self.lines):
            self._log("Layer changed -> re-detecting & re-snapping loads...")
            self._detect()

    def _detect(self):
        path = self.dxf_path.get().strip()
        if not path or not os.path.isfile(path):
            messagebox.showwarning("Warning", "Select a valid DXF file.")
            return
        self._log_clear()
        self._log(f"Reading DXF: {path}")

        try:
            wseg = float(self.wall_seg.get())
        except ValueError:
            wseg = 800.0
        try:
            uscale = float(self.unit_var.get())
        except ValueError:
            uscale = 0.001

        def worker():
            try:
                res = read_dxf(path,
                               self.geom_layer.get().strip() or DEFAULT_GEOM_LAYER,
                               self.text_layer.get().strip() or DEFAULT_TEXT_LAYER,
                               self.col_layer.get().strip() or DEFAULT_COL_LAYER,
                               self.wall_layer.get().strip() or DEFAULT_WALL_LAYER,
                               self.edge_layer.get().strip() or DEFAULT_EDGE_LAYER,
                               wseg, uscale)
            except Exception as exc:
                self._log_safe(f"[ERROR] {exc}")
                return
            self.after(0, self._got_loads, res)

        threading.Thread(target=worker, daemon=True).start()

    def _got_loads(self, res):
        self.points = res["points"]
        self.lines = res["lines"]
        self.context = res["context"]
        self._set_layer_values(res["layers"])
        ns_p = sum(1 for p in self.points if p["snapped"])
        ns_l = sum(1 for ln in self.lines if ln["snapped"])
        self._log(f"Detected {len(self.points)} point loads "
                  f"({ns_p} snapped to a column), "
                  f"{len(self.lines)} line loads ({ns_l} snapped to a wall).")
        tr = res.get("transfer")
        if tr and (tr["wall"] or tr["col"] or tr["unmatched"]):
            self._log(f"  Transfer (DL/LL over): {tr['wall']} -> WALL OVER (line, kN/m "
                      f"= DL/length), {tr['col']} -> CO OVER (point, kN)."
                      + (f"  {tr['unmatched']} unmatched (leader tip not on wall/column)."
                         if tr["unmatched"] else ""))
        self._log(f"Context: {len(self.context['polys'])} plan lines, "
                  f"{len(self.context['circles'])} circles drawn.")
        self._fit_view()

    # ---------------- read slab ----------------
    def _read_slab(self):
        cpt = self.cpt_path.get().strip()
        if not cpt or not os.path.isfile(cpt):
            messagebox.showwarning("Warning", "Select a CPT file first.")
            return
        self._log("")
        try:
            from dxf_to_ramconcept import fetch_slab_outline
        except Exception as exc:
            self._log(f"[ERROR] {exc}")
            return

        def worker():
            fetch_slab_outline(cpt, self._log_safe, self._got_slab)

        threading.Thread(target=worker, daemon=True).start()

    def _got_slab(self, polys, bbox):
        def cb():
            if polys:
                self.slab_polys = polys
                self.slab_bbox = bbox
                self._auto_align()
                self._fit_view()
        self.after(0, cb)

    def _auto_align(self):
        """Sau khi read slab: dat transform mac dinh mm->m, Offset X=0, Y=0."""
        self.unit_var.set("0.001")
        self.off_x.set("0.0")
        self.off_y.set("0.0")
        self._log("Read slab: default Unit=0.001 (mm->m), Offset X=0, Y=0. "
                  "Use 'Align 2 points' or adjust Offset X/Y if not aligned.")

    # ---------------- transform / view ----------------
    def w2s(self, x, y):
        return (x * self.vscale + self.tx, -y * self.vscale + self.ty)

    def s2w(self, sx, sy):
        return ((sx - self.tx) / self.vscale, (self.ty - sy) / self.vscale)

    def _all_dxf_points(self):
        pts = [(p["x"], p["y"]) for p in self.points]
        for ln in self.lines:
            pts.append((ln["x1"], ln["y1"])); pts.append((ln["x2"], ln["y2"]))
        for poly, _c in self.context["polys"]:
            pts.extend(poly)
        for cx, cy, r in self.context["circles"]:
            pts.append((cx, cy))
        return pts

    def _slab_to_dxf(self, mx, my):
        try:
            scale = float(self.unit_var.get())
            ox = float(self.off_x.get()); oy = float(self.off_y.get())
        except ValueError:
            return None
        if not scale:
            return None
        return ((mx - ox) / scale, (my - oy) / scale)

    def _fit_view(self):
        pts = list(self._all_dxf_points())
        if self.slab_polys:
            for poly in self.slab_polys:
                for mx, my in poly:
                    d = self._slab_to_dxf(mx, my)
                    if d:
                        pts.append(d)
        if not pts:
            return
        minx, miny, maxx, maxy = _bbox(pts)
        W = max(self.canvas.winfo_width(), 50)
        H = max(self.canvas.winfo_height(), 50)
        m = 40
        dx = (maxx - minx) or 1.0
        dy = (maxy - miny) or 1.0
        self.vscale = min((W - 2 * m) / dx, (H - 2 * m) / dy)
        cx = (minx + maxx) / 2; cy = (miny + maxy) / 2
        self.tx = W / 2 - cx * self.vscale
        self.ty = H / 2 + cy * self.vscale
        self._redraw()

    def _redraw(self):
        c = self.canvas
        c.delete("all")

        # DXF context plan (faint)
        for poly, closed in self.context["polys"]:
            sp = [coord for p in poly for coord in self.w2s(*p)]
            if len(sp) >= 4:
                if closed and len(sp) >= 6:
                    sp += sp[:2]
                c.create_line(*sp, fill=C_CTX, width=1)
        for cx, cy, r in self.context["circles"]:
            sx, sy = self.w2s(cx, cy)
            rr = r * self.vscale
            c.create_oval(sx - rr, sy - rr, sx + rr, sy + rr, outline=C_CTX, width=1)

        # CPT slab outline (red) = alignment target
        if self.slab_polys:
            for poly in self.slab_polys:
                sp = []
                for mx, my in poly:
                    d = self._slab_to_dxf(mx, my)
                    if d:
                        sp.extend(self.w2s(*d))
                if len(sp) >= 6:
                    sp += sp[:2]
                    c.create_line(*sp, fill=C_SLAB, width=2, dash=(5, 3))

        # line loads (snapped, co the nhieu doan theo vach cong)
        for ln in self.lines:
            pmid = None
            for (p1, p2) in ln["segs"]:
                x1, y1 = self.w2s(*p1); x2, y2 = self.w2s(*p2)
                c.create_line(x1, y1, x2, y2, fill=C_LINE, width=3, arrow=tk.BOTH)
                if pmid is None:
                    pmid = ((x1 + x2) / 2, (y1 + y2) / 2)
            if pmid:
                c.create_text(pmid[0], pmid[1] - 10, text=f"{ln['sdl']:g}/{ln['ll']:g}",
                              fill=C_LINE, font=("Segoe UI", 8, "bold"))

        # point loads (snapped); show snap arrow from raw tip
        for p in self.points:
            rx, ry = self.w2s(p["x"], p["y"])
            sx, sy = self.w2s(p["sx"], p["sy"])
            if p["snapped"]:
                c.create_line(rx, ry, sx, sy, fill=C_RAW, width=1, dash=(2, 2))
                c.create_oval(rx - 2, ry - 2, rx + 2, ry + 2, outline=C_RAW)
            c.create_oval(sx - 5, sy - 5, sx + 5, sy + 5, fill=C_POINT, outline="white")
            c.create_text(sx + 8, sy - 8, text=f"{p['sdl']:g}/{p['ll']:g}",
                          fill=C_POINT, font=("Segoe UI", 8, "bold"), anchor="w")

        self.lbl_count.config(text=f"Point: {len(self.points)}  |  Line: {len(self.lines)}")

    # ---------------- zoom / pan ----------------
    def _on_zoom(self, event):
        factor = 1.1 if event.delta > 0 else 1 / 1.1
        wx, wy = self.s2w(event.x, event.y)
        self.vscale *= factor
        self.tx = event.x - wx * self.vscale
        self.ty = event.y + wy * self.vscale
        self._redraw()

    def _pan_start(self, event):
        self._pan = (event.x, event.y, self.tx, self.ty)

    def _pan_move(self, event):
        if not self._pan:
            return
        x0, y0, tx0, ty0 = self._pan
        self.tx = tx0 + (event.x - x0)
        self.ty = ty0 + (event.y - y0)
        self._redraw()

    # ---------------- 2-point align ----------------
    def _start_align(self):
        if not self.slab_polys:
            messagebox.showwarning("Warning", "Click 'Read slab' first to get the slab outline.")
            return
        if not self._all_dxf_points():
            messagebox.showwarning("Warning", "Detect loads first.")
            return
        self.align_stage = 1
        self.align_p1 = self.align_q1 = self.align_p2 = None
        self.canvas.config(cursor="crosshair")
        self.btn_align.config(text="Step 1: click a corner on the DXF plan")
        self.bind("<Escape>", lambda e: self._reset_align())
        self._log("Align 2 points: pick 2 reference corners on the DXF plan, each "
                  "followed by the matching corner on the red slab outline. Far apart = better.")

    def _reset_align(self):
        self.align_stage = 0
        self.canvas.config(cursor="")
        self.btn_align.config(text="Align 2 points (DXF -> slab)")
        self.unbind("<Escape>")
        self._redraw()

    def _nearest_dxf_vertex(self, sx, sy):
        best = None; bd = 1e18
        for x, y in self._all_dxf_points():
            ssx, ssy = self.w2s(x, y)
            d = (ssx - sx) ** 2 + (ssy - sy) ** 2
            if d < bd:
                bd = d; best = (x, y)
        return best

    def _nearest_slab_vertex(self, sx, sy):
        best = None; bd = 1e18
        if not self.slab_polys:
            return None
        for poly in self.slab_polys:
            for mx, my in poly:
                d = self._slab_to_dxf(mx, my)
                if not d:
                    continue
                ssx, ssy = self.w2s(*d)
                dd = (ssx - sx) ** 2 + (ssy - sy) ** 2
                if dd < bd:
                    bd = dd; best = (mx, my)
        return best

    def _draw_marker(self, sx, sy, color, label):
        r = 6
        self.canvas.create_oval(sx - r, sy - r, sx + r, sy + r, outline=color, width=2)
        self.canvas.create_line(sx - r - 4, sy, sx + r + 4, sy, fill=color)
        self.canvas.create_line(sx, sy - r - 4, sx, sy + r + 4, fill=color)
        self.canvas.create_text(sx + 12, sy - 12, text=label, fill=color,
                                font=("Segoe UI", 11, "bold"))

    def _mark_dxf(self, pt, label):
        sx, sy = self.w2s(*pt)
        self._draw_marker(sx, sy, "#2196f3", label)

    def _mark_slab(self, mpt, label):
        d = self._slab_to_dxf(*mpt)
        if d:
            sx, sy = self.w2s(*d)
            self._draw_marker(sx, sy, "#e53935", label)

    def _on_click(self, event):
        if self.align_stage == 0:
            return
        if self.align_stage == 1:
            self.align_p1 = self._nearest_dxf_vertex(event.x, event.y)
            self._mark_dxf(self.align_p1, "D1")
            self.align_stage = 2
            self.btn_align.config(text="Step 2: click matching corner on SLAB (red)")
        elif self.align_stage == 2:
            self.align_q1 = self._nearest_slab_vertex(event.x, event.y)
            self._mark_slab(self.align_q1, "S1")
            self.align_stage = 3
            self.btn_align.config(text="Step 3: click corner 2 on the DXF plan")
        elif self.align_stage == 3:
            self.align_p2 = self._nearest_dxf_vertex(event.x, event.y)
            self._mark_dxf(self.align_p2, "D2")
            self.align_stage = 4
            self.btn_align.config(text="Step 4: click matching corner on SLAB (red)")
        elif self.align_stage == 4:
            q2 = self._nearest_slab_vertex(event.x, event.y)
            self._mark_slab(q2, "S2")
            self._solve_two_point(q2)
            self._reset_align()

    def _solve_two_point(self, q2):
        p1, q1, p2 = self.align_p1, self.align_q1, self.align_p2
        if not (p1 and q1 and p2 and q2):
            return
        dpx, dpy = p2[0] - p1[0], p2[1] - p1[1]
        dqx, dqy = q2[0] - q1[0], q2[1] - q1[1]
        dp = (dpx * dpx + dpy * dpy) ** 0.5
        if dp < 1e-9:
            self._log("  [!] The 2 DXF points are too close. Pick points farther apart.")
            return
        dq = (dqx * dqx + dqy * dqy) ** 0.5
        scale = dq / dp
        ox = q1[0] - p1[0] * scale
        oy = q1[1] - p1[1] * scale
        self.unit_var.set(f"{scale:.6g}")
        self.off_x.set(f"{ox:.4f}")
        self.off_y.set(f"{oy:.4f}")
        self._log(f"  Result: scale={scale:.6g}, Offset X={ox:.4f}, Y={oy:.4f}")
        self._fit_view()

    # ---------------- import ----------------
    def _import(self):
        cpt = self.cpt_path.get().strip()
        if not cpt or not os.path.isfile(cpt):
            messagebox.showwarning("Warning", "Select a CPT file.")
            return
        if not self.points and not self.lines:
            messagebox.showwarning("Warning", "Detect loads first.")
            return
        try:
            scale = float(self.unit_var.get())
            ox = float(self.off_x.get()); oy = float(self.off_y.get())
        except ValueError:
            messagebox.showerror("Error", "Invalid unit scale / Offset.")
            return
        if not messagebox.askyesno(
                "Confirm",
                f"Import {len(self.points)} point loads and {len(self.lines)} line loads "
                f"into:\n  SDL -> {self.sdl_layer.get()}\n  LL  -> {self.ll_layer.get()} ?"):
            return

        self.btn_import.config(state=tk.DISABLED, text="  Importing...  ")
        self._log_clear()
        self._log("=== START IMPORT ===")
        self._log(f"Scale={scale}  Offset X={ox} Y={oy}")

        def worker():
            import_loads(cpt, self.points, self.lines,
                         self.sdl_layer.get().strip(), self.ll_layer.get().strip(),
                         scale, ox, oy, self._log_safe, self._import_done)

        threading.Thread(target=worker, daemon=True).start()

    def _import_done(self, ok):
        def cb():
            self.btn_import.config(state=tk.NORMAL,
                                   text="  IMPORT POINT/LINE LOADS INTO RAM CONCEPT  ")
            if ok:
                messagebox.showinfo("Done", "Import successful! CPT file saved.")
            else:
                messagebox.showerror("Failed", "Import failed. See log.")
        self.after(0, cb)


if __name__ == "__main__":
    App().mainloop()

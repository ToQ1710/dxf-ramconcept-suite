#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
DXF -> RAM Concept 2023 | Area Load Importer (Plan View)
Hien thi mat bang tai tu DXF, click vao tung vung de gan SDL + LL,
roi import vao 2 lop tai: "SI Dead Loading" va "Live (Reducible) Loading".
"""

import sys
import os
import re
import math
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from typing import Dict, List, Optional, Tuple

# RAM Concept 2023 API path
RAM_API_PATH = r"C:\Program Files\Bentley\Engineering\RAM Concept\RAM Concept 2023\python"
if RAM_API_PATH not in sys.path:
    sys.path.insert(0, RAM_API_PATH)

DEFAULT_SDL_LAYER = "SI Dead Loading"
DEFAULT_LL_LAYER  = "Live (Reducible) Loading"


# =============================================================================
# DATA MODEL
# =============================================================================
class AreaItem:
    """Mot vung area load doc tu DXF (toa do raw DXF)."""
    def __init__(self, idx: int, points: List[Tuple[float, float]], dxf_layer: str):
        self.idx       = idx
        self.points    = points        # toa do raw DXF
        self.dxf_layer = dxf_layer
        self.name: str  = ""           # ten area load trong RAM Concept
        self.sdl: float = 0.0          # kN/m2  (do lon, huong xuong)
        self.ll:  float = 0.0          # kN/m2
        self.canvas_id  = None
        self.label_id   = None
        self.selected   = False

    def centroid(self) -> Tuple[float, float]:
        n = len(self.points)
        return (sum(p[0] for p in self.points) / n,
                sum(p[1] for p in self.points) / n)

    def assigned(self) -> bool:
        return self.sdl != 0.0 or self.ll != 0.0


# =============================================================================
# DXF PARSER
# =============================================================================
NODE_ROUND = 1   # lam tron toa do node ve 0.1mm (DXF mm) -> node cung trung khit


def _rp(x: float, y: float) -> Tuple[float, float]:
    """Lam tron 1 diem ve 0.1mm de cac node chung 2 vung trung tuyet doi."""
    return (round(x, NODE_ROUND), round(y, NODE_ROUND))


def _sample_arc(cx, cy, r, a0, a1, max_seg):
    """Chia cung (tam cx,cy ban kinh r, tu goc a0 -> a1 rad) thanh diem,
    sao cho moi doan day <= max_seg. Tra ve list diem tu dau den cuoi (du ca 2 dau)."""
    span = a1 - a0
    arc_len = abs(span) * r
    n = max(1, int(math.ceil(arc_len / max_seg))) if max_seg > 0 else 1
    pts = []
    for i in range(n + 1):
        a = a0 + span * (i / n)
        pts.append(_rp(cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _arc_from_bulge(p0, p1, bulge, max_seg):
    """Chia 1 doan cung (bulge) p0->p1 thanh cac diem <= max_seg. Tra ve gom ca p0 va p1."""
    from ezdxf.math import bulge_to_arc
    (cx, cy), a0, a1, r = bulge_to_arc(p0, p1, bulge)
    pts = _sample_arc(cx, cy, r, a0, a1, max_seg)
    # ep 2 dau bang dung dinh goc (tranh sai lech 0.1mm o endpoint)
    pts[0]  = _rp(p0[0], p0[1])
    pts[-1] = _rp(p1[0], p1[1])
    return pts


def _subdivide(pts, max_seg):
    """Chia nho moi doan thang dai hon max_seg (dung cho spline/ellipse da lam phang)."""
    if max_seg <= 0 or len(pts) < 2:
        return pts
    out = [pts[0]]
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]; x1, y1 = pts[i + 1]
        d = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        if d > max_seg:
            k = int(math.ceil(d / max_seg))
            for j in range(1, k):
                t = j / k
                out.append(_rp(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
        out.append(_rp(x1, y1))
    return out


def _tessellate_hatch_path(pth, max_seg=300.0):
    """Tessellate 1 HATCH boundary path (PolylinePath hoac EdgePath) -> list (x,y).
    Cung ArcEdge duoc chia thanh doan thang <= max_seg. Khong lap diem dong."""
    pts = []

    if hasattr(pth, "vertices") and pth.vertices:
        # PolylinePath: lay bulge tu pth.bulges (ezdxf >= 0.18) hoac tu v[2]
        vertices = list(pth.vertices)
        raw_bulges = getattr(pth, "bulges", None)
        if raw_bulges is not None:
            bulges = list(raw_bulges)
            while len(bulges) < len(vertices):
                bulges.append(0.0)
        else:
            bulges = []
            for v in vertices:
                try:
                    bulges.append(float(v[2]) if len(v) > 2 else 0.0)
                except (TypeError, IndexError):
                    bulges.append(0.0)
        verts = []
        for v, b in zip(vertices, bulges):
            try:
                verts.append((float(v[0]), float(v[1]), float(b)))
            except (TypeError, IndexError):
                try:
                    verts.append((float(v.x), float(v.y), float(b)))
                except Exception:
                    pass
        if verts:
            closed = bool(getattr(pth, "is_closed", True))
            pts = _tessellate_polyline(verts, closed, max_seg)

    elif hasattr(pth, "edges") and pth.edges:
        # EdgePath: phan biet theo EDGE_TYPE (string trong ezdxf) hoac theo class name
        for ed in pth.edges:
            # ezdxf dung EDGE_TYPE = "LineEdge"/"ArcEdge"/"EllipseEdge"/"SplineEdge"
            etype = str(getattr(ed, "EDGE_TYPE", type(ed).__name__))

            if etype in ("LineEdge", "1") or (hasattr(ed, "start") and hasattr(ed, "end")
                                               and not hasattr(ed, "radius")):
                # LineEdge — chi lay diem dau; diem cuoi = dau edge tiep theo
                s = ed.start
                pts.append(_rp(float(s[0]), float(s[1])))

            elif etype in ("ArcEdge", "2") or (hasattr(ed, "radius") and hasattr(ed, "center")
                                                and hasattr(ed, "start_angle")):
                # ArcEdge — tessellate theo huong ccw/cw.
                # ezdxf HATCH ArcEdge khi ccw=False: thuc te di tu end_angle -> start_angle CW
                # (swap a0<->a1 de span < 0 tuc CW)
                c = ed.center; r = float(ed.radius)
                a0 = math.radians(float(ed.start_angle))
                a1 = math.radians(float(ed.end_angle))
                ccw = bool(getattr(ed, "ccw", True))
                if ccw:
                    while a1 <= a0:
                        a1 += 2 * math.pi   # CCW: a1 > a0, span > 0
                else:
                    a0, a1 = a1, a0         # swap: di tu end_angle -> start_angle
                    while a0 <= a1:
                        a0 += 2 * math.pi   # dam bao a0 > a1, span < 0 -> CW
                arc_pts = _sample_arc(float(c[0]), float(c[1]), r, a0, a1, max_seg)
                pts.extend(arc_pts[:-1])    # bo diem cuoi (= dau edge sau)

            elif etype in ("EllipseEdge", "3") or (hasattr(ed, "major_axis")
                                                    and hasattr(ed, "ratio")):
                # EllipseEdge
                try:
                    from ezdxf.math import ConstructionEllipse
                    maj = ed.major_axis
                    ell = ConstructionEllipse(
                        center=(float(ed.center[0]), float(ed.center[1])),
                        major_axis=(float(maj[0]), float(maj[1])),
                        ratio=float(ed.ratio),
                        start_param=float(ed.start_param),
                        end_param=float(ed.end_param)
                    )
                    flat = [_rp(p.x, p.y) for p in ell.flattening(max_seg * 0.05)]
                    flat = _subdivide(flat, max_seg)
                    if flat:
                        pts.extend(flat[:-1])
                except Exception:
                    s = getattr(ed, "start", None)
                    if s is not None:
                        pts.append(_rp(float(s[0]), float(s[1])))

            elif etype in ("SplineEdge", "4") or hasattr(ed, "control_points"):
                # SplineEdge
                try:
                    from ezdxf.math import BSpline
                    cp = [(float(p[0]), float(p[1])) for p in ed.control_points]
                    kv = list(ed.knot_values) if ed.knot_values else None
                    sp = BSpline(control_points=cp, order=int(ed.degree) + 1, knots=kv)
                    flat = [_rp(p.x, p.y) for p in sp.flattening(max_seg * 0.05)]
                    flat = _subdivide(flat, max_seg)
                    if flat:
                        pts.extend(flat[:-1])
                except Exception:
                    s = getattr(ed, "start", None)
                    if s is not None:
                        pts.append(_rp(float(s[0]), float(s[1])))

            else:
                s = getattr(ed, "start", None)
                if s is not None:
                    try:
                        pts.append(_rp(float(s[0]), float(s[1])))
                    except Exception:
                        pass
    return pts


def _tessellate_polyline(verts, closed, max_seg):
    """verts: list (x,y,bulge). Tra ve list diem da chia cung (khong lap diem dong)."""
    n = len(verts)
    seg_count = n if closed else n - 1
    out = []
    for i in range(seg_count):
        x0, y0, b = verts[i]
        x1, y1, _ = verts[(i + 1) % n]
        if abs(b) > 1e-9:
            arc_pts = _arc_from_bulge((x0, y0), (x1, y1), b, max_seg)
            out.extend(arc_pts[:-1])   # bo diem cuoi (la dau doan sau)
        else:
            out.append(_rp(x0, y0))
    if not closed:
        out.append(_rp(verts[-1][0], verts[-1][1]))
    return out


def _is_closed_ring(pts: List[Tuple[float, float]]) -> bool:
    """True neu diem dau ~ diem cuoi (polyline khep kin nhung khong bat co 'closed')."""
    if len(pts) < 3:
        return False
    (x0, y0), (x1, y1) = pts[0], pts[-1]
    dx, dy = x1 - x0, y1 - y0
    dist = (dx * dx + dy * dy) ** 0.5
    # duong cheo bbox cua chinh polyline
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    diag = ((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2) ** 0.5
    return dist <= max(1e-6, diag * 1e-3)


def polygon_area(pts: List[Tuple[float, float]]) -> float:
    """Dien tich tuyet doi (shoelace)."""
    n = len(pts)
    s = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) * 0.5


def dist_point_to_polyline(px, py, pts) -> float:
    """Khoang cach nho nhat tu diem toi cac doan cua polyline."""
    best = float("inf")
    for i in range(len(pts) - 1):
        ax, ay = pts[i]
        bx, by = pts[i + 1]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        if L2 < 1e-12:
            t = 0.0
        else:
            t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
        cx, cy = ax + t * dx, ay + t * dy
        d = ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5
        if d < best:
            best = d
    return best


def parse_dxf(dxf_path: str, max_seg: float = 800.0) -> Dict[str, List[dict]]:
    """Read DXF. Cac cung cong/cung tron duoc chia thanh doan thang <= max_seg (DXF units)."""
    try:
        import ezdxf
    except ImportError:
        raise ImportError("Thieu thu vien ezdxf. Chay: pip install ezdxf")

    doc    = ezdxf.readfile(dxf_path)
    msp    = doc.modelspace()
    layers: Dict[str, List[dict]] = {}

    def add(layer, item):
        layers.setdefault(layer, []).append(item)

    def add_poly(layer, pts, closed):
        if len(pts) >= 3 and closed:
            add(layer, {"type": "area", "points": pts})
        elif len(pts) >= 2:
            add(layer, {"type": "line", "points": pts})

    for e in msp:
        lyr   = e.dxf.layer
        etype = e.dxftype()

        if etype == "LWPOLYLINE":
            verts = [(p[0], p[1], p[4]) for p in e.get_points("xyseb")]  # x,y,start,end,bulge
            closed = bool(e.closed)
            pts = _tessellate_polyline(verts, closed, max_seg)
            if not closed:
                closed = _is_closed_ring(pts)
                if closed and len(pts) > 1 and pts[0] == pts[-1]:
                    pts = pts[:-1]
            add_poly(lyr, pts, closed)

        elif etype == "POLYLINE":
            try:
                verts = [(v.dxf.location.x, v.dxf.location.y,
                          getattr(v.dxf, "bulge", 0.0)) for v in e.vertices]
                closed = bool(e.is_closed)
                pts = _tessellate_polyline(verts, closed, max_seg)
                if not closed:
                    closed = _is_closed_ring(pts)
                    if closed and len(pts) > 1 and pts[0] == pts[-1]:
                        pts = pts[:-1]
                add_poly(lyr, pts, closed)
            except Exception:
                pass

        elif etype == "CIRCLE":
            c = e.dxf.center; r = e.dxf.radius
            pts = _sample_arc(c.x, c.y, r, 0.0, 2 * math.pi, max_seg)[:-1]  # bo diem dong trung
            add(lyr, {"type": "area", "points": pts})

        elif etype == "ARC":
            c = e.dxf.center; r = e.dxf.radius
            a0 = math.radians(e.dxf.start_angle)
            a1 = math.radians(e.dxf.end_angle)
            if a1 <= a0:
                a1 += 2 * math.pi
            add(lyr, {"type": "line", "points": _sample_arc(c.x, c.y, r, a0, a1, max_seg)})

        elif etype in ("ELLIPSE", "SPLINE"):
            try:
                pts = [_rp(p[0], p[1]) for p in e.flattening(max_seg * 0.05)]
                pts = _subdivide(pts, max_seg)
                closed = _is_closed_ring(pts)
                if closed and len(pts) > 1 and pts[0] == pts[-1]:
                    pts = pts[:-1]
                add_poly(lyr, pts, closed)
            except Exception:
                pass

        elif etype == "HATCH":
            try:
                for path in e.paths:
                    pts = _tessellate_hatch_path(path, max_seg)
                    if len(pts) >= 3:
                        if len(pts) > 3 and pts[0] == pts[-1]:
                            pts = pts[:-1]
                        add(lyr, {"type": "area", "points": pts})
            except Exception:
                pass

        elif etype == "LINE":
            s, t = e.dxf.start, e.dxf.end
            add(lyr, {"type": "line", "points": [_rp(s.x, s.y), _rp(t.x, t.y)]})

        elif etype in ("POINT", "INSERT"):
            loc = e.dxf.insert if etype == "INSERT" else e.dxf.location
            add(lyr, {"type": "point", "x": loc.x, "y": loc.y})

    return layers


def point_in_polygon(x: float, y: float, poly: List[Tuple[float, float]]) -> bool:
    """Ray casting."""
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and \
           (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


# =============================================================================
# RAM CONCEPT IMPORTER (background thread)
# =============================================================================
def import_loads(cpt_path, area_items, sdl_layer_name, ll_layer_name,
                 unit_scale, offset_x, offset_y, log_fn, done_fn):
    try:
        from ram_concept.concept    import Concept
        from ram_concept.point_2D   import Point2D
        from ram_concept.polygon_2D import Polygon2D
    except ImportError as exc:
        log_fn(f"[ERROR] Could not load RAM Concept API: {exc}")
        done_fn(False)
        return

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
        cad   = model.cad_manager

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
        ll_layer  = get_layer(ll_layer_name)

        def _clean_model_poly(mpts, tol=1e-4):
            """Bo diem trung lien tiep + diem dong trung lap (toa do model, m)."""
            out = []
            for p in mpts:
                if not out or abs(p[0] - out[-1][0]) > tol or abs(p[1] - out[-1][1]) > tol:
                    out.append(p)
            if len(out) >= 2 and abs(out[0][0] - out[-1][0]) <= tol and abs(out[0][1] - out[-1][1]) <= tol:
                out.pop()
            return out

        def _poly_area(pts):
            a = 0.0
            n = len(pts)
            for i in range(n):
                x1, y1 = pts[i]
                x2, y2 = pts[(i + 1) % n]
                a += x1 * y2 - x2 * y1
            return abs(a) / 2.0

        n_sdl = n_ll = n_skip = 0
        for item in area_items:
            idx = getattr(item, "idx", "?")
            mpts = _clean_model_poly([(x * unit_scale + offset_x,
                                       y * unit_scale + offset_y)
                                      for x, y in item.points])
            # bo vung suy bien (it hon 3 dinh hoac dien tich ~ 0)
            if len(mpts) < 3 or _poly_area(mpts) < 1e-6:
                n_skip += 1
                log_fn(f"  [skip] region #{idx}: degenerate geometry "
                       f"({len(mpts)} pts, area={_poly_area(mpts):.2e} m2)")
                continue

            poly = Polygon2D([Point2D(x, y) for x, y in mpts])
            nm = (item.name or "").strip()   # giu nguyen dau nhu nguoi dung nhap
            try:
                if item.sdl != 0.0:
                    al = sdl_layer.add_area_load(poly)
                    al.set_load_values(0.0, 0.0, item.sdl, 0.0, 0.0)
                    if nm:
                        al.name = nm
                    n_sdl += 1
                if item.ll != 0.0:
                    al = ll_layer.add_area_load(poly)
                    al.set_load_values(0.0, 0.0, item.ll, 0.0, 0.0)
                    if nm:
                        al.name = nm
                    n_ll += 1
            except Exception as e:
                n_skip += 1
                msg = str(e).strip().splitlines()[-1] if str(e).strip() else repr(e)
                log_fn(f"  [skip] region #{idx}: RAM rejected geometry -> {msg}")
                continue

        log_fn(f"\n  '{sdl_layer_name}': {n_sdl} area load (SDL)")
        log_fn(f"  '{ll_layer_name}': {n_ll} area load (LL)")
        if n_skip:
            log_fn(f"  [!] Skipped {n_skip} region(s) with invalid/degenerate geometry.")

        log_fn(f"\nSave file: {cpt_path}")
        model.save_file(cpt_path)
        model.close_model()
        log_fn(f"\n=== DONE: {n_sdl + n_ll} area loads imported ===")
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


def fetch_slab_outline(cpt_path, log_fn, result_fn):
    """Mo CPT, doc cac SlabArea -> tra ve (list_polygons_model_coords, bbox)."""
    try:
        from ram_concept.concept import Concept
    except ImportError as exc:
        log_fn(f"[ERROR] {exc}")
        result_fn(None, None)
        return
    log_fn("Reading slab geometry (SlabArea) from CPT...")
    try:
        concept = Concept.start_concept(headless=True)
        model   = concept.open_file(cpt_path)
        polys   = []
        for sa in model.cad_manager.structure_layer.slab_areas:
            pts = [(p.x, p.y) for p in sa.location.points]
            if len(pts) >= 3:
                polys.append(pts)
        model.close_model()
        concept.shut_down()
        if not polys:
            log_fn("[!] No SlabArea found in model.")
            result_fn(None, None)
            return
        allp = [p for poly in polys for p in poly]
        xs = [p[0] for p in allp]; ys = [p[1] for p in allp]
        bbox = (min(xs), min(ys), max(xs), max(ys))
        log_fn(f"Slab: {len(polys)} SlabArea | "
               f"bbox model X[{bbox[0]:.3f}..{bbox[2]:.3f}] "
               f"Y[{bbox[1]:.3f}..{bbox[3]:.3f}]")
        result_fn(polys, bbox)
    except Exception as exc:
        import traceback
        log_fn(f"[ERROR] {exc}\n{traceback.format_exc()}")
        result_fn(None, None)


def fetch_layer_names(cpt_path, log_fn, result_fn):
    """Mo CPT lay danh sach ten force loading layer."""
    try:
        from ram_concept.concept import Concept
    except ImportError as exc:
        log_fn(f"[ERROR] {exc}")
        result_fn(None)
        return
    log_fn("Reading layer list from CPT...")
    try:
        concept = Concept.start_concept(headless=True)
        model   = concept.open_file(cpt_path)
        names   = [ll.name for ll in model.cad_manager.force_loading_layers]
        model.close_model()
        concept.shut_down()
        log_fn(f"Found {len(names)} layer: {names}")
        result_fn(names)
    except Exception as exc:
        log_fn(f"[ERROR] {exc}")
        result_fn(None)


# =============================================================================
# LOADING LEGEND + HATCH AREA LOADS
# =============================================================================
def _explode_iter(container, depth=0):
    """Duyet entity, explode INSERT (block) -> toa do WORLD."""
    for e in container:
        yield e
        if e.dxftype() == "INSERT" and depth < 4:
            try:
                ves = list(e.virtual_entities())
            except Exception:
                ves = []
            for v in _explode_iter(ves, depth + 1):
                yield v


def _text_plain(e):
    if e.dxftype() == "MTEXT":
        try:
            s = e.plain_text()
        except Exception:
            s = e.text
    else:
        s = e.dxf.text
    return re.sub(r"\s+", " ", s).strip()   # gop tab/nhieu khoang trang -> 1 space


def _hatch_polys(e, max_seg=300.0):
    """Tra ve list polygon (moi boundary path) cua 1 HATCH (co tessellate cung cong)."""
    out = []
    for pth in e.paths:
        pts = _tessellate_hatch_path(pth, max_seg)
        if len(pts) >= 3:
            if len(pts) > 3 and pts[0] == pts[-1]:
                pts = pts[:-1]
            out.append(pts)
    return out


def scan_hatch_layers(dxf_path):
    """Do cac layer co HATCH SOLID nhieu mau (dau hieu hatch tai) trong model + layout.
    Tra ve list (layer, so_hatch, so_mau) sap theo so_mau giam."""
    import ezdxf
    from collections import defaultdict
    doc = ezdxf.readfile(dxf_path)
    info = defaultdict(lambda: [0, set()])   # layer -> [count, colors]
    spaces = [doc.modelspace()] + [l for l in doc.layouts if l.name != "Model"]
    for sp in spaces:
        for e in _explode_iter(sp):
            if e.dxftype() == "HATCH":
                ly = e.dxf.layer
                info[ly][0] += 1
                info[ly][1].add(e.dxf.color)
    out = [(ly, c, len(cols)) for ly, (c, cols) in info.items()]
    out.sort(key=lambda r: (r[2], r[1]), reverse=True)
    return out


def read_legend(dxf_path, hatch_layer="LOAD_HATCH"):
    """Doc LOADING LEGEND o layout (paper space) -> {color: (name, sdl, ll)}.
    Swatch = HATCH layer hatch_layer; cung hang co ten + 2 so (SDL, LL)."""
    import ezdxf
    doc = ezdxf.readfile(dxf_path)
    legend = {}; base = None; base_cands = []
    num_re = re.compile(r"-?\d+(\.\d+)?")
    # Quet CA model space LAN cac layout (legend co the o bat ky dau, ty le bat ky)
    spaces = [doc.modelspace()] + [l for l in doc.layouts if l.name != "Model"]
    for lay in spaces:
        hatches = []; texts = []
        for e in _explode_iter(lay):
            t = e.dxftype()
            if t == "HATCH" and e.dxf.layer == hatch_layer:
                polys = _hatch_polys(e)
                if polys:
                    allp = [p for poly in polys for p in poly]
                    xs = [p[0] for p in allp]; ys = [p[1] for p in allp]
                    hatches.append({"cx": sum(xs)/len(xs), "cy": sum(ys)/len(ys),
                                    "w": max(xs)-min(xs), "h": max(ys)-min(ys),
                                    "col": _hatch_color_key(e)})
            elif t in ("TEXT", "MTEXT"):
                s = _text_plain(e)
                if s:
                    texts.append((e.dxf.insert.x, e.dxf.insert.y, s))
        if not hatches or not texts:
            continue
        # O legend = NHOM hatch CUNG KICH THUOC (cac o mau ve giong het nhau, >=2 o).
        # (Vung hatch plan to/khac nhau -> khong thuoc nhom -> bi loai.)
        from collections import Counter as _Counter
        def _sz(h):
            return (round(h["w"]), round(h["h"]))
        szcnt = _Counter(_sz(h) for h in hatches)
        best_size, best_n = szcnt.most_common(1)[0]
        if best_n >= 2:
            swatches = [h for h in hatches if _sz(h) == best_size]
        else:
            areas = [max(h["w"], 1.0) * max(h["h"], 1.0) for h in hatches]
            amax = max(areas)
            swatches = [h for h, a in zip(hatches, areas) if a <= 0.3 * amax] or hatches

        def _row(cy, ty, cx):
            """Tra ve (name, name_x, [nums]) cua hang. Chi lay so BEN PHAI ten (cot SIDL/LL);
            bo so thu tu (1,2,3...) nam giua swatch va ten."""
            band = sorted([(xx, tt) for xx, yy, tt in texts if abs(yy - cy) < ty and xx > cx])
            words = [(xx, tt) for xx, tt in band
                     if not num_re.fullmatch(tt) and not tt.startswith("(")]
            name = words[0][1] if words else None
            name_x = words[0][0] if words else None
            ref = name_x if name_x is not None else cx
            nums = [float(tt) for xx, tt in band if num_re.fullmatch(tt) and xx > ref]
            return name, name_x, nums

        n_before = len(legend)
        name_cols = []                                 # x cua cot TEN (de doi chieu base)
        for h in swatches:
            ty = h["h"] * 0.7 + 1e-6                   # dung sai chi theo chieu cao hang
            name, name_x, nums = _row(h["cy"], ty, h["cx"])
            if name and len(nums) >= 2:
                legend[h["col"]] = (name, nums[0], nums[1])
                name_cols.append(name_x)
        # BASE = hang LEGEND khong co swatch (vd CAR PARK). Quet rong, doi chieu cot ten.
        if base is None and (len(legend) - n_before) >= 2 and name_cols:
            rowh = max(h["h"] for h in swatches)
            ty0 = rowh * 0.7 + 1e-6
            sxc = sum(h["cx"] for h in swatches) / len(swatches)
            ncx = sum(name_cols) / len(name_cols)      # cot ten trung binh
            symin = min(h["cy"] for h in swatches); symax = max(h["cy"] for h in swatches)
            cands = []
            seen_y = set()
            for xx, yy, tt in sorted(texts, key=lambda r: -r[1]):
                if not num_re.fullmatch(tt):
                    continue
                if not (symin - 12 * rowh <= yy <= symax + 12 * rowh):   # vung legend (rong)
                    continue
                if any(abs(yy - h["cy"]) < ty0 for h in swatches):
                    continue                       # hang nay co swatch -> bo
                yk = round(yy / max(rowh, 1.0))
                if yk in seen_y:
                    continue
                seen_y.add(yk)
                name, name_x, nums = _row(yy, ty0, sxc - 200 * rowh)
                if len(nums) >= 2:
                    aligned = (name is not None and name_x is not None
                               and abs(name_x - ncx) < 12 * rowh)
                    # uu tien hang co ten dung cot; van log de chan doan
                    cands.append((aligned, abs(yy - symax), name or "?", nums[0], nums[1]))
            # log chan doan
            base_cands.extend((nm, s, l) for _a, _d, nm, s, l in cands)
            aligned_c = [c for c in cands if c[0]]
            if aligned_c:
                aligned_c.sort(key=lambda r: r[1])    # gan khoi swatch nhat
                base = (aligned_c[0][2], aligned_c[0][3], aligned_c[0][4])
    return legend, base, base_cands


def read_slab_edge(dxf_path, refs, edge_layer="SLAB EDGE"):
    """Chon polygon bao san (DXF) lam vung tai NEN cho TANG co nhieu vung hatch nhat.
    refs = list cac tam vung hatch. Tra ve (slab_pts, slab_polygon_shapely | None)."""
    import ezdxf
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    try:
        from shapely.geometry import Polygon, Point
    except Exception:
        Polygon = Point = None
    if isinstance(refs, tuple):
        refs = [refs]
    pts_refs = [Point(x, y) for x, y in refs] if Point else []
    cands = []   # (poly_shapely_or_None, pts, area)
    for e in _explode_iter(msp):
        if e.dxf.layer == edge_layer and e.dxftype() == "LWPOLYLINE":
            pts = [(p[0], p[1]) for p in e.get_points("xy")]
            if len(pts) < 3:
                continue
            poly = None
            if Polygon is not None:
                try:
                    poly = Polygon(pts)
                    if not poly.is_valid:
                        poly = poly.buffer(0)
                    if hasattr(poly, "geoms"):
                        poly = max(poly.geoms, key=lambda g: g.area)
                except Exception:
                    poly = None
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            area = poly.area if poly is not None else (max(xs)-min(xs))*(max(ys)-min(ys))
            cands.append((poly, pts, area))
    if not cands:
        return None, None

    chosen = None
    if pts_refs and all(c[0] is not None for c in cands):
        # chon san CHUA NHIEU tam hatch nhat (tang chinh); tie -> dien tich lon nhat
        def _ncontain(c):
            return sum(1 for rp in pts_refs if c[0].contains(rp))
        scored = [(_ncontain(c), c[2], c) for c in cands]
        scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
        if scored[0][0] > 0:
            chosen = scored[0][2]
        else:
            avg = (sum(r.x for r in pts_refs) / len(pts_refs),
                   sum(r.y for r in pts_refs) / len(pts_refs))
            ap = Point(*avg)
            chosen = min(cands, key=lambda c: c[0].distance(ap))
    else:
        chosen = max(cands, key=lambda c: c[2])

    poly, pts, _a = chosen
    if poly is not None:
        try:
            p = poly.simplify(1.0)
            clean = [(x, y) for x, y in list(p.exterior.coords)[:-1]]
            if len(clean) >= 3:
                return clean, p
        except Exception:
            pass
    return pts, poly


# =============================================================================
# CONFORM area-load curved edges to the SLAB EDGE (shared nodes between zones)
# =============================================================================
def _resample_ring(pts, seg):
    """Chia bien san (polygon kin) thanh LUOI NODE CHUNG: giu dinh goc + chen them
    diem sao cho moi canh <= seg. Tra ve list diem (ring kin, khong lap dinh dau)."""
    if seg <= 0:
        seg = 800.0
    out = []
    n = len(pts)
    for i in range(n):
        a = pts[i]; b = pts[(i + 1) % n]
        out.append((a[0], a[1]))
        d = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
        k = int(d / seg)
        for t in range(1, k + 1):
            f = t * seg / d
            if f < 1 - 1e-9:
                out.append((a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])))
    return out


def _ring_path(ring, i, j):
    """Cac node tu i den j doc ring, chon huong NGAN hon (it node hon)."""
    m = len(ring)
    fwd = []; k = i
    while True:
        fwd.append(ring[k])
        if k == j:
            break
        k = (k + 1) % m
    bwd = []; k = i
    while True:
        bwd.append(ring[k])
        if k == j:
            break
        k = (k - 1) % m
    return fwd if len(fwd) <= len(bwd) else bwd


def _plen(pts):
    return sum(((pts[i+1][0]-pts[i][0])**2 + (pts[i+1][1]-pts[i][1])**2) ** 0.5
               for i in range(len(pts)-1))


def _conform_zone(zone, ring, tol):
    """Thay cac doan bien zone NAM DOC bien san bang dung node cua ring (luoi chung)
    -> cac zone chung cung cong se trung node. Giu nguyen phan khong gan bien san.
    Chi thay khi duong ring giua 2 dau ~ doan zone (tranh wrap quanh ca slab)."""
    import math
    m = len(ring); n = len(zone)
    t2 = tol * tol

    def nidx(v):
        bi = -1; bd = t2
        for i in range(m):
            d = (ring[i][0] - v[0]) ** 2 + (ring[i][1] - v[1]) ** 2
            if d < bd:
                bd = d; bi = i
        return bi

    idx = [nidx(v) for v in zone]
    if all(i < 0 for i in idx) or all(i >= 0 for i in idx):
        return zone     # khong gan san, HOAC nam tron tren san (tranh thay het -> wrap)
    out = []; i = 0
    while i < n:
        if idx[i] < 0:
            out.append(zone[i]); i += 1
        else:
            j = i
            while j + 1 < n and idx[j + 1] >= 0:
                j += 1
            path = _ring_path(ring, idx[i], idx[j])
            direct = math.hypot(zone[j][0]-zone[i][0], zone[j][1]-zone[i][1])
            # guard chong wrap: duong ring khong duoc dai bat thuong so voi khoang cach 2 dau
            if _plen(path) <= 3.0 * max(direct, tol):
                out.extend(path)
            else:
                out.extend(zone[i:j+1])      # giu nguyen doan goc
            i = j + 1
    res = [out[0]]
    for p in out[1:]:
        if (p[0] - res[-1][0]) ** 2 + (p[1] - res[-1][1]) ** 2 > 1.0:
            res.append(p)
    return res if len(res) >= 3 else zone


def conform_zones_to_slab(items, slab_pts, seg, tol):
    """Snap bien cong cua cac vung area load vao LUOI NODE CHUNG tren bien san.
    Zone chung cung cong -> trung node. Co guard: zone nao hong thi giu nguyen."""
    if not slab_pts or len(slab_pts) < 3:
        return
    ring = _resample_ring(slab_pts, seg)
    try:
        from shapely.geometry import Polygon
    except Exception:
        Polygon = None
    for it in items:
        try:
            new_pts = _conform_zone(it.points, ring, tol)
        except Exception:
            continue
        if new_pts is it.points or len(new_pts) < 3:
            continue
        if Polygon is not None:                    # guard: hop le, area ~ va hinh khong lech xa (wrap)
            try:
                po = Polygon(it.points); pn = Polygon(new_pts)
                if not pn.is_valid:
                    pn = pn.buffer(0)
                if (not pn.is_valid or pn.is_empty
                        or abs(pn.area - po.area) > 0.25 * max(po.area, 1.0)
                        or pn.hausdorff_distance(po) > 3.0 * seg):
                    continue                       # lech qua nhieu (wrap quanh slab) -> giu goc
            except Exception:
                continue
        it.points = new_pts


def _hatch_color_key(e):
    """Khoa mau de match legend. Uu tien true_color (RGB) vi nhieu hatch dung RGB
    override: vd BIN va TERRACE cung ACI=133 nhung khac RGB -> phai tach theo RGB.
    Khong co RGB -> dung ACI index."""
    try:
        tc = e.dxf.get("true_color", None)
    except Exception:
        tc = None
    if tc:
        return ("rgb", int(tc))
    try:
        return ("aci", int(e.dxf.color))
    except Exception:
        return ("aci", 0)


def _outer_polys(polys):
    """Cac path NGOAI CUNG cua 1 hatch — MOI cai = 1 vung rieng (vd 2 terraces
    cung mau nam trong 1 HATCH entity). Loai:
      • path SUY BIEN / marker trang tri (dien tich ~0, vd ky hieu ben trong),
      • path la LO (nam gon trong path lon hon).
    Lam sach polygon TU CAT (buffer 0) de RAM Concept khong tu choi.
    Khong co shapely -> loc theo bbox."""
    if not polys:
        return []
    try:
        from shapely.geometry import Polygon as _P
    except Exception:
        if len(polys) <= 1:
            return polys
        def _bbarea(p):
            xs = [q[0] for q in p]; ys = [q[1] for q in p]
            return (max(xs)-min(xs)) * (max(ys)-min(ys))
        amax = max((_bbarea(p) for p in polys), default=0.0)
        return [p for p in polys if _bbarea(p) >= amax * 1e-4] or polys
    geoms = []
    for p in polys:
        try:
            g = _P(p)
            if not g.is_valid:
                g = g.buffer(0)
        except Exception:
            g = None
        if g is not None and not g.is_empty and g.area > 0:
            geoms.append(g)
    if not geoms:
        return []
    amax = max(g.area for g in geoms)
    thr = amax * 1e-4                        # bo marker/suy bien (area ~0)
    geoms = [g for g in geoms if g.area >= thr]
    out = []
    for i, gi in enumerate(geoms):
        ci = gi.representative_point()
        if any(j != i and geoms[j].area > gi.area and geoms[j].contains(ci)
               for j in range(len(geoms))):
            continue                          # la lo -> bo
        parts = gi.geoms if gi.geom_type == "MultiPolygon" else [gi]
        for part in parts:                    # buffer 0 co the tach nhieu manh
            if part.area >= thr:
                out.append([(x, y) for x, y in list(part.exterior.coords)[:-1]])
    return out


def parse_hatch_loads(dxf_path, legend, hatch_layer="LOAD_HATCH", max_seg=300.0):
    """Cac vung HATCH tren model -> list AreaItem (match mau voi legend)."""
    import ezdxf
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    def _bb(poly):
        xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
        return (max(xs) - min(xs)) * (max(ys) - min(ys))

    items = []; idx = 0; seen = set()
    for e in _explode_iter(msp):
        if e.dxftype() != "HATCH" or e.dxf.layer != hatch_layer:
            continue
        col = _hatch_color_key(e)
        if col not in legend:
            continue
        name, sdl, ll = legend[col]
        polys = _hatch_polys(e, max_seg)
        if not polys:
            continue
        for poly in _outer_polys(polys):      # MOI path ngoai cung = 1 vung rieng
            cx = sum(p[0] for p in poly) / len(poly)
            cy = sum(p[1] for p in poly) / len(poly)
            key = (col, round(cx), round(cy), round(_bb(poly)))
            if key in seen:                   # bo hatch trung lap (do explode block)
                continue
            seen.add(key)
            it = AreaItem(idx, poly, hatch_layer)
            it.name = name; it.sdl = sdl; it.ll = ll
            items.append(it); idx += 1
    return items


# =============================================================================
# GUI
# =============================================================================
BLUE_DARK = "#1a3a5c"
BLUE_BTN  = "#0078d4"
BLUE_HOV  = "#005a9e"
BG        = "#f4f4f4"
CANVAS_BG = "#ffffff"

C_UNASSIGNED = ("#e2e2e2", "#999999")   # fill, outline
C_ASSIGNED   = ("#bfe3bf", "#3a7d3a")
C_SELECTED   = "#ff8c00"
C_CONTEXT    = "#cfcfcf"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("DXF -> RAM Concept 2023 | Area Load Plan")
        self.geometry("1280x820")
        self.minsize(1000, 680)
        self.configure(bg=BG)

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TLabelframe",       background=BG)
        style.configure("TLabelframe.Label", background=BG, font=("Segoe UI", 9, "bold"))
        style.configure("TLabel",            background=BG, font=("Segoe UI", 9))
        style.configure("TButton",           font=("Segoe UI", 9))

        # state
        self.dxf_path  = tk.StringVar()
        self.cpt_path  = tk.StringVar()
        # Lay san duong dan DXF + CPT output da chon ben Mesh Model Builder
        try:
            import shared_paths
            _sp = shared_paths.load_paths()
            if _sp.get("dxf"):
                self.dxf_path.set(_sp["dxf"])
            if _sp.get("cpt"):
                self.cpt_path.set(_sp["cpt"])
        except Exception:
            pass
        self.unit_var  = tk.StringVar(value="0.001")
        self.maxseg_var = tk.StringVar(value="800")   # chia doan thang dai <= (mm DXF) - Read DXF / conform grid
        self.arcseg_var = tk.StringVar(value="300")   # chia CUNG CONG <= (mm DXF) - hatch loads (toi thieu 300)
        self.sdl_layer = tk.StringVar(value=DEFAULT_SDL_LAYER)
        self.ll_layer  = tk.StringVar(value=DEFAULT_LL_LAYER)
        self.off_x     = tk.StringVar(value="0.0")   # offset model (m)
        self.off_y     = tk.StringVar(value="0.0")
        self.align_mode = tk.StringVar(value="corner")  # corner | center
        self.subtract_base = tk.BooleanVar(value=True)  # tru tai nen khi gan hatch load
        # Conform TAT mac dinh: tessellation cung cong da tu cho node chung tren cung
        # chung giua 2 vung (vi cung GIONG HET trong DXF). Conform chi gay meo cung canh
        # thang (snap vao bien san lech -> RAM tu choi). Bat khi that su can.
        self.conform_var = tk.BooleanVar(value=False)   # khop bien cong zone vao bien san
        self.hatch_layer = tk.StringVar(value="LOAD_HATCH")  # layer chua hatch tai

        # Chia se phep canh (scale + offset) sang Point/Line Load Importer
        try:
            import shared_paths

            def _save_tf(*_a):
                try:
                    shared_paths.save_transform(
                        scale=float(self.unit_var.get()),
                        ox=float(self.off_x.get()),
                        oy=float(self.off_y.get()))
                except Exception:
                    pass

            self.unit_var.trace_add("write", _save_tf)
            self.off_x.trace_add("write", _save_tf)
            self.off_y.trace_add("write", _save_tf)
        except Exception:
            pass

        self.slab_polys: List[List[Tuple[float, float]]] = []  # model coords
        self.slab_bbox: Optional[Tuple[float, float, float, float]] = None

        self.area_items:    List[AreaItem] = []
        self.context_lines: List[List[Tuple[float, float]]] = []
        self.context_pts:   List[Tuple[float, float]]       = []
        self.selected: Optional[AreaItem] = None        # vung dang active (de dien o)
        self.selection: List[AreaItem] = []             # tat ca vung dang chon
        self._box = None                                # rubber-band box select
        self.pick_mode = False
        self.align_stage = 0          # 0 idle | 1..4 cac buoc can 2 diem
        self.align_p1 = None          # diem DXF 1 (raw)
        self.align_q1 = None          # diem san 1 (model)
        self.align_p2 = None          # diem DXF 2 (raw)

        # view transform: screen = world*vscale + (tx,ty)  (y flipped)
        self.vscale = 1.0
        self.tx = 0.0
        self.ty = 0.0
        self._pan = None

        self._build_ui()

    # =========================================================================
    def _build_ui(self):
        hdr = tk.Frame(self, bg=BLUE_DARK, pady=8)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="DXF -> RAM Concept 2023  |  Area Load Plan",
                 font=("Segoe UI", 13, "bold"), fg="white", bg=BLUE_DARK).pack()
        tk.Label(hdr, text="Click a region on the plan to assign SDL + LL",
                 font=("Segoe UI", 9), fg="#a0c4e8", bg=BLUE_DARK).pack()

        body = tk.Frame(self, bg=BG, padx=10, pady=6)
        body.pack(fill=tk.BOTH, expand=True)

        self._build_top(body)

        mid = tk.Frame(body, bg=BG)
        mid.pack(fill=tk.BOTH, expand=True, pady=(6, 6))
        self._build_canvas(mid)
        self._build_side(mid)

        self._build_log(body)
        self._build_import(body)

    # ----- top: files + units + target layers ------------------------------
    def _build_top(self, parent):
        frm = ttk.LabelFrame(parent, text="  Files & Configuration  ", padding=8)
        frm.pack(fill=tk.X)
        frm.columnconfigure(1, weight=1)
        frm.columnconfigure(4, weight=1)

        ttk.Label(frm, text="DXF file:").grid(row=0, column=0, sticky=tk.W, padx=(0, 6))
        ttk.Entry(frm, textvariable=self.dxf_path).grid(row=0, column=1, sticky=tk.EW)
        df = tk.Frame(frm, bg=BG)
        df.grid(row=0, column=2, columnspan=2, sticky=tk.W, padx=(8, 0))
        ttk.Label(df, text="Arc segment <= (mm):").pack(side=tk.LEFT)
        ttk.Entry(df, textvariable=self.maxseg_var, width=7).pack(side=tk.LEFT, padx=(2, 0))
        ttk.Label(df, text="Curve seg <= (mm):").pack(side=tk.LEFT, padx=(8, 0))
        ttk.Entry(df, textvariable=self.arcseg_var, width=7).pack(side=tk.LEFT, padx=(2, 0))
        ttk.Button(frm, text="Browse...", command=self._pick_dxf).grid(row=0, column=4, padx=4)
        ttk.Button(frm, text="Read DXF", command=self._load_dxf).grid(row=0, column=5)
        ttk.Button(frm, text="Hatch loads (legend)", command=self._detect_hatch_loads).grid(
            row=0, column=6, padx=(4, 0))
        ttk.Checkbutton(frm, text="Subtract base", variable=self.subtract_base).grid(
            row=0, column=7, padx=(4, 0))
        ttk.Checkbutton(frm, text="Conform to slab", variable=self.conform_var).grid(
            row=0, column=8, padx=(4, 0))
        ttk.Label(frm, text="Hatch layer:").grid(row=0, column=9, sticky=tk.E, padx=(8, 2))
        ttk.Entry(frm, textvariable=self.hatch_layer, width=14).grid(row=0, column=10)

        ttk.Label(frm, text="CPT file:").grid(row=1, column=0, sticky=tk.W, padx=(0, 6), pady=(6, 0))
        ttk.Entry(frm, textvariable=self.cpt_path).grid(row=1, column=1, columnspan=3, sticky=tk.EW, pady=(6, 0))
        ttk.Button(frm, text="Browse...", command=self._pick_cpt).grid(row=1, column=4, padx=4, pady=(6, 0))
        ttk.Button(frm, text="Read layers", command=self._fetch_layers).grid(row=1, column=5, pady=(6, 0))

        # units
        ttk.Label(frm, text="Unit:").grid(row=2, column=0, sticky=tk.W, pady=(6, 0))
        uf = tk.Frame(frm, bg=BG)
        uf.grid(row=2, column=1, sticky=tk.W, pady=(6, 0))
        for lbl, val in [("mm->m", "0.001"), ("cm->m", "0.01"), ("m->m", "1.0")]:
            ttk.Radiobutton(uf, text=lbl, variable=self.unit_var, value=val).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Entry(uf, textvariable=self.unit_var, width=7).pack(side=tk.LEFT, padx=(4, 0))

        # target layers
        ttk.Label(frm, text="SDL layer:").grid(row=2, column=2, sticky=tk.E, padx=(10, 4), pady=(6, 0))
        self.cb_sdl = ttk.Combobox(frm, textvariable=self.sdl_layer, width=24)
        self.cb_sdl.grid(row=2, column=3, sticky=tk.W, pady=(6, 0))
        ttk.Label(frm, text="LL layer:").grid(row=2, column=4, sticky=tk.E, padx=(10, 4), pady=(6, 0))
        self.cb_ll = ttk.Combobox(frm, textvariable=self.ll_layer, width=24)
        self.cb_ll.grid(row=2, column=5, sticky=tk.W, pady=(6, 0))

        # ---- can vi tri (offset) ----
        ttk.Label(frm, text="Offset X (m):").grid(row=3, column=0, sticky=tk.W, pady=(6, 0))
        of = tk.Frame(frm, bg=BG)
        of.grid(row=3, column=1, sticky=tk.W, pady=(6, 0))
        ttk.Entry(of, textvariable=self.off_x, width=10).pack(side=tk.LEFT)
        ttk.Label(of, text="  Y (m):").pack(side=tk.LEFT)
        ttk.Entry(of, textvariable=self.off_y, width=10).pack(side=tk.LEFT, padx=(2, 0))
        # ve lai overlay khi sua tay
        self.off_x.trace_add("write", lambda *a: self._redraw())
        self.off_y.trace_add("write", lambda *a: self._redraw())
        self.unit_var.trace_add("write", lambda *a: self._redraw())

        af = tk.Frame(frm, bg=BG)
        af.grid(row=3, column=2, columnspan=2, sticky=tk.W, pady=(6, 0), padx=(10, 0))
        ttk.Radiobutton(af, text="Corner", variable=self.align_mode,
                        value="corner").pack(side=tk.LEFT)
        ttk.Radiobutton(af, text="Center", variable=self.align_mode,
                        value="center").pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(frm, text="Read slab + Auto-align",
                   command=self._fetch_slab).grid(row=3, column=4, columnspan=2,
                                                  sticky=tk.W, pady=(6, 0), padx=(10, 0))

    # ----- canvas (plan view) ----------------------------------------------
    def _build_canvas(self, parent):
        frm = ttk.LabelFrame(parent, text="  Load plan (scroll = zoom, right-drag = pan)  ", padding=4)
        frm.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(frm, bg=CANVAS_BG, highlightthickness=1,
                                highlightbackground="#bbb")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.canvas.bind("<Button-1>",        self._on_click)
        self.canvas.bind("<Shift-ButtonPress-1>",   self._box_start)
        self.canvas.bind("<Shift-B1-Motion>",       self._box_move)
        self.canvas.bind("<Shift-ButtonRelease-1>", self._box_end)
        self.canvas.bind("<Configure>",       lambda e: self._redraw())
        self.canvas.bind("<MouseWheel>",      self._on_wheel)        # Windows
        self.canvas.bind("<ButtonPress-3>",   self._pan_start)
        self.canvas.bind("<B3-Motion>",       self._pan_move)
        self.canvas.bind("<ButtonRelease-3>", lambda e: setattr(self, "_pan", None))

        bar = tk.Frame(frm, bg=BG)
        bar.pack(fill=tk.X, pady=(4, 0))
        ttk.Button(bar, text="Fit view", command=self._fit_view).pack(side=tk.LEFT, padx=2)
        self.btn_pick = tk.Button(
            bar, text="+ Add region from boundary", font=("Segoe UI", 9),
            relief=tk.RAISED, bd=1, cursor="hand2", command=self._toggle_pick)
        self.btn_pick.pack(side=tk.LEFT, padx=8)
        self.btn_align = tk.Button(
            bar, text="Align by markers (DXF -> slab)", font=("Segoe UI", 9),
            relief=tk.RAISED, bd=1, cursor="hand2", command=self._start_align)
        self.btn_align.pack(side=tk.LEFT, padx=2)
        self.lbl_count = ttk.Label(bar, text="No data yet")
        self.lbl_count.pack(side=tk.LEFT, padx=12)

    # ----- side: edit panel ------------------------------------------------
    def _build_side(self, parent):
        frm = ttk.LabelFrame(parent, text="  Assign load to region  ", padding=10)
        frm.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))
        frm.configure(width=270)

        self.sel_title = ttk.Label(frm, text="(No region selected)",
                                   font=("Segoe UI", 10, "bold"), foreground="#444")
        self.sel_title.pack(anchor=tk.W, pady=(0, 12))

        grid = tk.Frame(frm, bg=BG)
        grid.pack(fill=tk.X)
        grid.columnconfigure(1, weight=1)

        ttk.Label(grid, text="Load name:").grid(row=0, column=0, sticky=tk.W, pady=6)
        self.ent_name = ttk.Entry(grid, width=12, font=("Segoe UI", 10))
        self.ent_name.grid(row=0, column=1, sticky=tk.EW, pady=6)

        ttk.Label(grid, text="SDL (kN/m2):").grid(row=1, column=0, sticky=tk.W, pady=6)
        self.ent_sdl = ttk.Entry(grid, width=12, font=("Segoe UI", 10))
        self.ent_sdl.grid(row=1, column=1, sticky=tk.EW, pady=6)

        ttk.Label(grid, text="LL  (kN/m2):").grid(row=2, column=0, sticky=tk.W, pady=6)
        self.ent_ll = ttk.Entry(grid, width=12, font=("Segoe UI", 10))
        self.ent_ll.grid(row=2, column=1, sticky=tk.EW, pady=6)

        # Enter de ap dung nhanh
        self.ent_name.bind("<Return>", lambda e: self._apply_sel())
        self.ent_sdl.bind("<Return>", lambda e: self._apply_sel())
        self.ent_ll.bind("<Return>",  lambda e: self._apply_sel())

        ttk.Separator(frm, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)
        ttk.Button(frm, text="Apply to SELECTED region  (Enter)",
                   command=self._apply_sel).pack(fill=tk.X, pady=2)
        ttk.Button(frm, text="Apply to ALL regions",
                   command=self._apply_all).pack(fill=tk.X, pady=2)
        ttk.Button(frm, text="Clear selected region assignment",
                   command=self._clear_sel).pack(fill=tk.X, pady=2)

        ttk.Separator(frm, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)
        note = ("Convention:\n"
                "- Enter the CORRECT Fz sign per model\n"
                "  convention (e.g. -0.5 -> -0.5).\n"
                "- SDL -> layer 'SI Dead Loading'\n"
                "- LL  -> layer 'Live (Reducible)\n"
                "  Loading'\n"
                "- Each region makes 2 area loads\n"
                "  (1 SDL + 1 LL) if non-zero.\n\n"
                "Select multiple regions:\n"
                "- Ctrl+click: add/remove a region\n"
                "- Shift+drag: rubber-band select\n"
                "  (by each centroid)\n\n"
                "Color: gray = unassigned,\n"
                "     green = assigned,\n"
                "     orange = selected.")
        ttk.Label(frm, text=note, font=("Segoe UI", 8),
                  foreground="#666", justify=tk.LEFT).pack(anchor=tk.W)

    def _build_log(self, parent):
        frm = ttk.LabelFrame(parent, text="  Log  ", padding=4)
        frm.pack(fill=tk.X, pady=(0, 6))
        self.log_box = scrolledtext.ScrolledText(
            frm, height=6, state=tk.DISABLED, font=("Consolas", 9),
            bg="#1e1e1e", fg="#d4d4d4", insertbackground="white")
        self.log_box.pack(fill=tk.X)

    def _build_import(self, parent):
        self.btn_import = tk.Button(
            parent, text="   IMPORT AREA LOAD INTO RAM CONCEPT   ",
            font=("Segoe UI", 11, "bold"), bg=BLUE_BTN, fg="white",
            activebackground=BLUE_HOV, activeforeground="white",
            relief=tk.FLAT, bd=0, pady=9, cursor="hand2",
            command=self._run_import)
        self.btn_import.pack(fill=tk.X)

    # =========================================================================
    # COORDINATE TRANSFORM
    # =========================================================================
    def w2s(self, x, y):
        return (x * self.vscale + self.tx, -y * self.vscale + self.ty)

    def s2w(self, sx, sy):
        return ((sx - self.tx) / self.vscale, (self.ty - sy) / self.vscale)

    def _all_points(self):
        pts = []
        for it in self.area_items:
            pts.extend(it.points)
        for ln in self.context_lines:
            pts.extend(ln)
        pts.extend(self.context_pts)
        return pts

    def _fit_view(self):
        pts = list(self._all_points())
        # gom them vien san (doi model -> DXF world) de ca 2 deu hien
        if self.slab_polys:
            try:
                scale = float(self.unit_var.get())
                ox = float(self.off_x.get()); oy = float(self.off_y.get())
            except ValueError:
                scale, ox, oy = 1.0, 0.0, 0.0
            if scale:
                for poly in self.slab_polys:
                    for mx, my in poly:
                        pts.append(((mx - ox) / scale, (my - oy) / scale))
        if not pts:
            return
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
        W = max(self.canvas.winfo_width(), 50)
        H = max(self.canvas.winfo_height(), 50)
        m = 30
        dx = maxx - minx or 1.0
        dy = maxy - miny or 1.0
        self.vscale = min((W - 2 * m) / dx, (H - 2 * m) / dy)
        # center
        cx = (minx + maxx) / 2
        cy = (miny + maxy) / 2
        self.tx = W / 2 - cx * self.vscale
        self.ty = H / 2 + cy * self.vscale
        self._redraw()

    # =========================================================================
    # DRAW
    # =========================================================================
    def _redraw(self):
        c = self.canvas
        c.delete("all")
        if not self.area_items and not self.context_lines:
            return

        # overlay vien san mesh (do): chuyen model -> DXF: dxf = (model - offset)/scale
        if self.slab_polys:
            try:
                scale = float(self.unit_var.get())
                ox = float(self.off_x.get()); oy = float(self.off_y.get())
            except ValueError:
                scale, ox, oy = 1.0, 0.0, 0.0
            if scale != 0:
                for poly in self.slab_polys:
                    sp = []
                    for mx, my in poly:
                        wx = (mx - ox) / scale
                        wy = (my - oy) / scale
                        sp.extend(self.w2s(wx, wy))
                    if len(sp) >= 6:
                        sp += sp[:2]   # khep kin
                        c.create_line(*sp, fill="#e53935", width=2, dash=(5, 3))

        # context (mo nhat)
        for ln in self.context_lines:
            sp = [coord for p in ln for coord in self.w2s(*p)]
            if len(sp) >= 4:
                c.create_line(*sp, fill=C_CONTEXT, width=1)
        for p in self.context_pts:
            sx, sy = self.w2s(*p)
            c.create_oval(sx-2, sy-2, sx+2, sy+2, fill=C_CONTEXT, outline="")

        # areas: ve vung LON truoc de vung nho nam tren, de nhin/chon
        for it in sorted(self.area_items,
                         key=lambda a: polygon_area(a.points), reverse=True):
            sp = [coord for p in it.points for coord in self.w2s(*p)]
            if len(sp) < 6:
                continue
            if it.assigned():
                fill, outline, stip = C_ASSIGNED[0], C_ASSIGNED[1], "gray25"
            else:
                fill, outline, stip = "", C_UNASSIGNED[1], ""   # trong suot
            width = 1
            if it.selected:
                outline = C_SELECTED
                width = 3
            it.canvas_id = c.create_polygon(*sp, fill=fill, outline=outline,
                                             width=width, stipple=stip)
            # label
            if it.assigned():
                cx, cy = self.w2s(*it.centroid())
                txt = f"S{it.sdl:g}/L{it.ll:g}"
                if it.name:
                    txt = f"{it.name}\n{txt}"
                c.create_text(cx, cy, text=txt, justify=tk.CENTER,
                              font=("Segoe UI", 8, "bold"), fill="#1a3a5c")

        self._update_count()

    def _update_count(self):
        n = len(self.area_items)
        a = sum(1 for it in self.area_items if it.assigned())
        self.lbl_count.config(text=f"Area regions: {n}  |  assigned: {a}  |  unassigned: {n - a}")

    # =========================================================================
    # EVENTS
    # =========================================================================
    def _pick_dxf(self):
        p = filedialog.askopenfilename(title="Select DXF",
                                       filetypes=[("DXF", "*.dxf"), ("All", "*.*")])
        if p:
            self.dxf_path.set(p)
            self._load_dxf()

    def _pick_cpt(self):
        p = filedialog.askopenfilename(title="Select CPT",
                                       filetypes=[("RAM Concept", "*.cpt"), ("All", "*.*")])
        if p:
            self.cpt_path.set(p)

    def _load_dxf(self):
        path = self.dxf_path.get().strip()
        if not path or not os.path.isfile(path):
            messagebox.showwarning("Warning", "Select a valid DXF file.")
            return
        try:
            max_seg = float(self.maxseg_var.get())
        except ValueError:
            max_seg = 800.0
        self._log_clear()
        self._log(f"Read DXF: {path}  (arc segment <= {max_seg:g} mm)")
        try:
            data = parse_dxf(path, max_seg)
        except Exception as exc:
            messagebox.showerror("DXF Error", str(exc))
            self._log(f"[ERROR] {exc}")
            return

        self.area_items.clear()
        self.context_lines.clear()
        self.context_pts.clear()
        self.selected = None
        self.selection = []
        self.sel_title.config(text="(No region selected)")

        idx = 0
        for lyr, ents in data.items():
            for e in ents:
                if e["type"] == "area":
                    self.area_items.append(AreaItem(idx, e["points"], lyr))
                    idx += 1
                elif e["type"] == "line":
                    self.context_lines.append(e["points"])
                elif e["type"] == "point":
                    self.context_pts.append((e["x"], e["y"]))

        self._log(f"Done: {len(self.area_items)} area regions | "
                  f"{len(self.context_lines)} line | {len(self.context_pts)} point.")
        if not self.area_items:
            self._log("[!] No CLOSED polyline/hatch found to use as area load.")
        self._fit_view()

    def _detect_hatch_loads(self):
        """Doc LOADING LEGEND + gan tai cho cac vung HATCH theo mau (ten + SDL/LL)."""
        path = self.dxf_path.get().strip()
        if not path or not os.path.isfile(path):
            messagebox.showwarning("Warning", "Select a valid DXF file.")
            return
        self._log_clear()
        hlayer = self.hatch_layer.get().strip() or "LOAD_HATCH"
        self._log(f"Reading LOADING LEGEND + hatch loads (layer '{hlayer}')...")
        sub = bool(self.subtract_base.get())
        do_conform = bool(self.conform_var.get())
        try:
            aseg = float(self.arcseg_var.get())     # chia CUNG CONG <= (mm), tu o 'Curve seg'
        except (ValueError, AttributeError):
            aseg = 300.0
        if aseg < 300.0:                            # khong nho hon 300mm theo yeu cau
            aseg = 300.0
        try:
            cseg = float(self.maxseg_var.get())     # buoc luoi node chung khi conform (mm)
        except (ValueError, AttributeError):
            cseg = 800.0

        def worker():
            try:
                legend, base, bcands = read_legend(path, hlayer)
                items = parse_hatch_loads(path, legend, hlayer, aseg)
                if not items:
                    # Khong thay -> do cac layer co hatch nhieu mau de goi y
                    cand = scan_hatch_layers(path)
                    self._log_safe("[!] No hatch matched on layer '%s'. "
                                   "Layers having SOLID hatches (layer | #hatch | #colors):"
                                   % hlayer)
                    for ly, c, ncol in cand[:12]:
                        self._log_safe(f"     {ly!r} | {c} | {ncol}")
                    # tu thu lai voi layer co nhieu mau nhat (neu khac)
                    best = next((r for r in cand if r[2] >= 2 and r[0] != hlayer), None)
                    if best:
                        self._log_safe(f"Auto-retry with layer '{best[0]}'...")
                        legend, base, bcands = read_legend(path, best[0])
                        items = parse_hatch_loads(path, legend, best[0], aseg)
                slab = None
                if items:
                    cents = [it.centroid() for it in items]
                    slab, slab_poly = read_slab_edge(path, cents)
                    # CHI giu hatch CHONG (overlap) voi slab nay (giu ca zone sat mep);
                    # bo zone tang khac (xa, khong chong). Dung overlap thay vi tam.
                    if slab_poly is not None:
                        try:
                            from shapely.geometry import Polygon as _Pg
                            kept = []
                            for it in items:
                                zp = _Pg(it.points)
                                if not zp.is_valid:
                                    zp = zp.buffer(0)
                                # giu zone CHAM slab (overlap > ~1% dien tich zone);
                                # chi bo zone tang khac (xa, khong chong slab nay)
                                inter = slab_poly.intersection(zp).area
                                if inter > 0.01 * max(zp.area, 1.0):
                                    kept.append(it)
                            n_drop = len(items) - len(kept)
                            if kept and n_drop:
                                self._log_safe(f"Filtered to slab floor: kept {len(kept)} "
                                               f"hatch, dropped {n_drop} on other floors.")
                                items = kept
                        except Exception:
                            pass
                    # Khop bien cong cua zone vao LUOI NODE CHUNG tren bien san
                    # -> cac zone chung cung cong trung node, khit nhau.
                    if slab and do_conform:
                        conform_zones_to_slab(items, slab, cseg, cseg)
                        self._log_safe(f"Conformed curved edges to slab edge "
                                       f"(shared nodes, seg={cseg:g}mm).")
            except Exception as exc:
                import traceback
                self._log_safe(f"[ERROR] {exc}\n{traceback.format_exc()}")
                return
            self.after(0, self._got_hatch_loads, legend, base, bcands, items, slab, sub)

        threading.Thread(target=worker, daemon=True).start()

    def _got_hatch_loads(self, legend, base, bcands, items, slab, sub):
        self._log("Legend (color -> name, SDL, LL):")
        for col, (nm, sdl, ll) in legend.items():
            self._log(f"  [{col}] {nm}: SDL={sdl} LL={ll}")
        if bcands:
            self._log("Base candidates (no-swatch rows): "
                      + "; ".join(f"{nm}={s}/{l}" for nm, s, l in bcands))
        if base:
            self._log(f"  BASE -> {base[0]}: SDL={base[1]} LL={base[2]}")
        else:
            self._log("  [!] BASE not detected -> zones kept at FULL value (no base).")
        if not items:
            self._log("[!] No hatch region matched the legend. Check layer 'LOAD_HATCH'.")
            return

        result = []
        if sub and base and slab:
            b_sdl, b_ll = base[1], base[2]
            base_item = AreaItem(0, slab, "SLAB EDGE")
            base_item.name = base[0]; base_item.sdl = b_sdl; base_item.ll = b_ll
            result.append(base_item)
            self._log(f"\nBase '{base[0]}' over slab edge (SDL={b_sdl}, LL={b_ll}).")
            result.extend(self._build_overlay_zones(items, b_sdl, b_ll))
        else:
            result = items
            if sub and not slab:
                self._log("[!] No SLAB EDGE outline found near loads -> base NOT added "
                          "(zones kept at full value).")

        for i, it in enumerate(result):
            it.idx = i
        self.area_items = result
        self.context_lines.clear(); self.context_pts.clear()
        self.selected = None; self.selection = []
        self.sel_title.config(text="(No region selected)")
        from collections import Counter
        cc = Counter(it.name for it in result)
        self._log(f"\nAssigned {len(result)} regions:")
        for nm, n in cc.items():
            self._log(f"  {nm}: {n}")
        self._log("\nReview/edit values on the canvas, align, then IMPORT.")
        self._fit_view()

    def _build_overlay_zones(self, items, b_sdl, b_ll):
        """Winner-takes-all: net tai moi diem = zone gia tri lon nhat phu len (+ nen).
        GIU zone DUOI nguyen ven; TACH zone TREN; moi vung deu mang ten zone cua no.
        - zone ngoai vung chong: gia tri (zone - base)  -> net = zone
        - zone tren CHONG zone duoi L: gia tri (zone - L) -> net (base + (L-base) + (zone-L)) = zone
        Tra ve list AreaItem (chua co base)."""
        out = []
        try:
            from shapely.geometry import Polygon
            from shapely.ops import unary_union
        except Exception:
            for it in items:
                it.sdl = round(it.sdl - b_sdl, 4); it.ll = round(it.ll - b_ll, 4)
            return list(items)

        def geom_polys(g, min_area=1e4):
            res = []
            if g.is_empty:
                return res
            for gg in (list(g.geoms) if hasattr(g, "geoms") else [g]):
                if getattr(gg, "geom_type", "") != "Polygon" or gg.area < min_area:
                    continue
                pts = [(x, y) for x, y in list(gg.exterior.coords)[:-1]]
                if len(pts) >= 3:
                    res.append(pts)
            return res

        zones = []
        for it in items:
            try:
                p = Polygon(it.points)
                if not p.is_valid:
                    p = p.buffer(0)
            except Exception:
                p = None
            zones.append({"name": it.name, "s": it.sdl, "l": it.ll, "p": p, "pts": it.points})

        def mk(pts, name, s, l):
            ci = AreaItem(0, pts, "LOAD"); ci.name = name
            ci.sdl = round(s, 4); ci.ll = round(l, 4); out.append(ci)

        nsplit = 0
        for z in zones:
            p = z["p"]
            if p is None or p.is_empty:
                mk(z["pts"], z["name"], z["s"] - b_sdl, z["l"] - b_ll)
                continue
            lowers = [o for o in zones if o is not z and o["p"] is not None
                      and (o["s"], o["l"]) < (z["s"], z["l"]) and p.intersects(o["p"])]
            if not lowers:
                mk(z["pts"], z["name"], z["s"] - b_sdl, z["l"] - b_ll)
                continue
            # phan NGOAI cac zone duoi -> (zone - base)
            ulow = unary_union([o["p"] for o in lowers])
            for gp in geom_polys(p.difference(ulow)):
                mk(gp, z["name"], z["s"] - b_sdl, z["l"] - b_ll)
            # phan CHONG tung zone duoi -> (zone - L), clip theo zone duoi gia tri cao hon
            lowers.sort(key=lambda o: (o["s"], o["l"]), reverse=True)
            higher_low = None
            for o in lowers:
                piece = p.intersection(o["p"])
                if higher_low is not None:
                    piece = piece.difference(higher_low)
                for gp in geom_polys(piece):
                    mk(gp, z["name"], z["s"] - o["s"], z["l"] - o["l"])
                higher_low = o["p"] if higher_low is None else unary_union([higher_low, o["p"]])
            nsplit += 1
        if nsplit:
            self._log(f"Overlap: {nsplit} higher zone(s) split over lower zones "
                      f"(lower zones kept whole; net = dominant zone everywhere).")
        return out

    def _on_click(self, event):
        wx, wy = self.s2w(event.x, event.y)

        # Che do: can 2 diem moc (giai scale + offset)
        if self.align_stage == 1:
            self.align_p1 = self._nearest_dxf_vertex(event.x, event.y)
            self._draw_marker(*self.w2s(*self.align_p1), "#2196f3", "D1")
            self.align_stage = 2
            self.btn_align.config(text="Step 2: click point 1 on SLAB outline (red)")
            self._log(f"  D1 (DXF) = ({self.align_p1[0]:.1f}, {self.align_p1[1]:.1f}). "
                      f"Now click the EXACT matching point on the red slab outline.")
            return
        if self.align_stage == 2:
            q = self._nearest_slab_vertex(event.x, event.y)
            if q is None:
                self._log("  [!] No slab outline yet. Click 'Read slab + Auto-align' first.")
                self._reset_align()
                return
            self.align_q1 = q
            self._draw_marker(*self._slab_world_screen(q), "#e53935", "S1")
            self.align_stage = 3
            self.btn_align.config(text="Step 3: click marker 2 on DXF")
            self._log(f"  S1 (slab) = ({q[0]:.3f}, {q[1]:.3f}). "
                      f"Now click the 2nd marker on DXF (far from point 1).")
            return
        if self.align_stage == 3:
            self.align_p2 = self._nearest_dxf_vertex(event.x, event.y)
            self._draw_marker(*self.w2s(*self.align_p2), "#2196f3", "D2")
            self.align_stage = 4
            self.btn_align.config(text="Step 4: click point 2 on SLAB outline (red)")
            self._log(f"  D2 (DXF) = ({self.align_p2[0]:.1f}, {self.align_p2[1]:.1f}). "
                      f"Click the matching point on the red slab outline.")
            return
        if self.align_stage == 4:
            q2 = self._nearest_slab_vertex(event.x, event.y)
            if q2 is None:
                self._reset_align()
                return
            self._solve_two_point(q2)
            return

        # Che do: chuyen duong bao -> vung
        if self.pick_mode:
            self._convert_boundary(wx, wy, event.x, event.y)
            return

        if not self.area_items:
            return
        ctrl = bool(event.state & 0x0004)   # giu Ctrl?
        # Chon vung NHO NHAT chua diem click (cu the nhat khi cac vung chong nhau)
        hits = [it for it in self.area_items if point_in_polygon(wx, wy, it.points)]
        hit = min(hits, key=lambda it: polygon_area(it.points)) if hits else None

        if ctrl and hit:
            # toggle vung trong selection
            if hit in self.selection:
                self.selection.remove(hit)
                hit.selected = False
                self.selected = self.selection[-1] if self.selection else None
            else:
                self.selection.append(hit)
                hit.selected = True
                self.selected = hit
        elif hit:
            for it in self.area_items:
                it.selected = False
            self.selection = [hit]
            hit.selected = True
            self.selected = hit
        else:
            if not ctrl:
                for it in self.area_items:
                    it.selected = False
                self.selection = []
                self.selected = None

        self._sync_panel()
        self._redraw()

    def _sync_panel(self):
        """Cap nhat tieu de + cac o nhap theo vung active / so vung chon."""
        n = len(self.selection)
        if n == 0:
            self.sel_title.config(text="(No region selected)")
            return
        a = self.selected or self.selection[-1]
        if n == 1:
            self.sel_title.config(text=f"Region #{a.idx}  (layer: {a.dxf_layer})")
        else:
            self.sel_title.config(text=f"Selected {n} regions  "
                                       f"(ap dung cho ca {n})")
        self.ent_name.delete(0, tk.END); self.ent_name.insert(0, a.name)
        self.ent_sdl.delete(0, tk.END); self.ent_sdl.insert(0, f"{a.sdl:g}")
        self.ent_ll.delete(0, tk.END);  self.ent_ll.insert(0, f"{a.ll:g}")
        self.ent_name.focus_set()
        self.ent_name.selection_range(0, tk.END)

    def _toggle_pick(self):
        self.pick_mode = not self.pick_mode
        if self.pick_mode:
            self.btn_pick.config(relief=tk.SUNKEN, bg="#ffe0a0",
                                 text="* Click a boundary... (ESC to cancel)")
            self.canvas.config(cursor="crosshair")
            self.bind("<Escape>", lambda e: self._toggle_pick())
            self._log("Boundary pick mode: click a closed boundary to create a region.")
        else:
            self.btn_pick.config(relief=tk.RAISED, bg="SystemButtonFace",
                                 text="+ Add region from boundary")
            self.canvas.config(cursor="")
            self.unbind("<Escape>")

    def _convert_boundary(self, wx, wy, sx, sy):
        """Tim context line gan click nhat va chuyen thanh vung area."""
        thr = 10.0 / self.vscale   # 10px -> world
        best, best_d = None, float("inf")
        for ln in self.context_lines:
            if len(ln) < 3:
                continue
            d = dist_point_to_polyline(wx, wy, ln)
            if d < best_d:
                best_d, best = d, ln
        if best is None or best_d > thr:
            self._log("  No closed boundary found near the click.")
            return
        idx = (max((it.idx for it in self.area_items), default=-1)) + 1
        item = AreaItem(idx, list(best), "DUONG_BAO")
        self.area_items.append(item)
        self.context_lines.remove(best)
        # tat che do, chon luon vung moi
        self._toggle_pick()
        for it in self.area_items:
            it.selected = False
        item.selected = True
        self.selected = item
        self.selection = [item]
        self.sel_title.config(text=f"Region #{item.idx}  (from boundary)")
        self.ent_sdl.delete(0, tk.END); self.ent_sdl.insert(0, "0")
        self.ent_ll.delete(0, tk.END);  self.ent_ll.insert(0, "0")
        self.ent_sdl.focus_set()
        self._log(f"  Created region #{item.idx} from boundary ({len(best)} points).")
        self._redraw()

    def _start_align(self):
        if not self.slab_polys:
            messagebox.showwarning("Warning",
                                   "Click 'Read slab + Auto-align' first to get the slab outline.")
            return
        if self.pick_mode:
            self._toggle_pick()
        self.align_stage = 1
        self.align_p1 = self.align_q1 = self.align_p2 = None
        self.canvas.config(cursor="crosshair")
        self.btn_align.config(relief=tk.SUNKEN, bg="#ffe0a0",
                              text="Step 1: click marker 1 on DXF (ESC to cancel)")
        self.bind("<Escape>", lambda e: self._reset_align())
        self._log("Align 2 points (solve scale + offset). Pick 2 CORRESPONDING point pairs, "
                  "each pair = 1 point on DXF + the same point on the red slab outline. "
                  "Choose 2 diagonal points; the farther apart, the more accurate.")

    def _reset_align(self):
        self.align_stage = 0
        self.align_p1 = self.align_q1 = self.align_p2 = None
        self.canvas.config(cursor="")
        self.btn_align.config(relief=tk.RAISED, bg="SystemButtonFace",
                              text="Align 2 points (DXF -> slab)")
        self.unbind("<Escape>")
        self._redraw()

    def _slab_world_screen(self, model_pt):
        """Doi 1 diem san (model) -> toa do screen theo scale/offset hien tai."""
        try:
            scale = float(self.unit_var.get())
            ox = float(self.off_x.get()); oy = float(self.off_y.get())
        except ValueError:
            scale, ox, oy = 1.0, 0.0, 0.0
        wx = (model_pt[0] - ox) / (scale or 1.0)
        wy = (model_pt[1] - oy) / (scale or 1.0)
        return self.w2s(wx, wy)

    def _solve_two_point(self, q2):
        """Tu 2 cap (p1->q1, p2->q2) giai uniform scale + offset (model = dxf*scale + off)."""
        p1, q1, p2 = self.align_p1, self.align_q1, self.align_p2
        dpx, dpy = p2[0] - p1[0], p2[1] - p1[1]
        dqx, dqy = q2[0] - q1[0], q2[1] - q1[1]
        dp = (dpx * dpx + dpy * dpy) ** 0.5
        dq = (dqx * dqx + dqy * dqy) ** 0.5
        if dp < 1e-9:
            self._log("  [!] The 2 DXF points are too close. Pick 2 points farther apart.")
            self._reset_align()
            return
        scale = dq / dp
        ox = q1[0] - p1[0] * scale
        oy = q1[1] - p1[1] * scale
        # canh bao neu huong lech (co xoay)
        if dq > 1e-9:
            cross = (dpx * dqy - dpy * dqx) / (dp * dq)
            if abs(cross) > 0.02:
                self._log(f"  [!] The 2 plans may be ROTATED (orientation off {abs(cross)*100:.1f}%). "
                          f"This tool only handles scale+shift, not rotation.")
        self.unit_var.set(f"{scale:.6g}")
        self.off_x.set(f"{ox:.4f}")
        self.off_y.set(f"{oy:.4f}")
        self._log(f"  Result: scale={scale:.6g}, Offset X={ox:.4f}, Y={oy:.4f}. "
                  f"The red slab outline should now match the load regions.")
        self._reset_align()
        self._redraw()

    def _draw_marker(self, sx, sy, color, label=""):
        r = 6
        self.canvas.create_oval(sx-r, sy-r, sx+r, sy+r, outline=color, width=2)
        self.canvas.create_line(sx-r-3, sy, sx+r+3, sy, fill=color)
        self.canvas.create_line(sx, sy-r-3, sx, sy+r+3, fill=color)
        if label:
            self.canvas.create_text(sx+12, sy-10, text=label, fill=color,
                                    font=("Segoe UI", 8, "bold"))

    def _nearest_dxf_vertex(self, sx, sy):
        """Diem DXF (raw) gan vi tri click nhat (snap vao dinh)."""
        cand = []
        for it in self.area_items:
            cand.extend(it.points)
        for ln in self.context_lines:
            cand.extend(ln)
        cand.extend(self.context_pts)
        if not cand:
            return self.s2w(sx, sy)
        best, bd = None, float("inf")
        for (rx, ry) in cand:
            wsx, wsy = self.w2s(rx, ry)
            d = (wsx - sx) ** 2 + (wsy - sy) ** 2
            if d < bd:
                bd, best = d, (rx, ry)
        return best

    def _nearest_slab_vertex(self, sx, sy):
        """Dinh san (toa do model) gan vi tri click nhat."""
        if not self.slab_polys:
            return None
        try:
            scale = float(self.unit_var.get())
            ox = float(self.off_x.get()); oy = float(self.off_y.get())
        except ValueError:
            return None
        if scale == 0:
            return None
        best, bd = None, float("inf")
        for poly in self.slab_polys:
            for (mx, my) in poly:
                wx = (mx - ox) / scale
                wy = (my - oy) / scale
                wsx, wsy = self.w2s(wx, wy)
                d = (wsx - sx) ** 2 + (wsy - sy) ** 2
                if d < bd:
                    bd, best = d, (mx, my)
        return best

    def _on_wheel(self, event):
        factor = 1.1 if event.delta > 0 else 1 / 1.1
        wx, wy = self.s2w(event.x, event.y)
        self.vscale *= factor
        self.tx = event.x - wx * self.vscale
        self.ty = event.y + wy * self.vscale
        self._redraw()

    def _box_start(self, event):
        if not self.area_items or self.pick_mode or self.align_stage:
            return
        self._box = (event.x, event.y,
                     self.canvas.create_rectangle(event.x, event.y, event.x, event.y,
                                                  outline="#ff8c00", dash=(4, 2)))

    def _box_move(self, event):
        if not self._box:
            return
        x0, y0, rid = self._box
        self.canvas.coords(rid, x0, y0, event.x, event.y)

    def _box_end(self, event):
        if not self._box:
            return
        x0, y0, rid = self._box
        self.canvas.delete(rid)
        self._box = None
        xmin, xmax = sorted((x0, event.x))
        ymin, ymax = sorted((y0, event.y))
        if abs(xmax - xmin) < 3 and abs(ymax - ymin) < 3:
            return
        # chon moi vung co TAM nam trong khung -> them vao selection
        added = 0
        for it in self.area_items:
            csx, csy = self.w2s(*it.centroid())
            if xmin <= csx <= xmax and ymin <= csy <= ymax:
                if it not in self.selection:
                    self.selection.append(it)
                    it.selected = True
                    self.selected = it
                    added += 1
        self._log(f"Rubber-band selected {added} regions (total {len(self.selection)}).")
        self._sync_panel()
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

    def _parse_entry(self, ent):
        v = ent.get().strip()
        if v == "":
            return 0.0
        try:
            return float(v)
        except ValueError:
            return None

    def _apply_sel(self):
        if not self.selection:
            messagebox.showinfo("Notice", "Please select a region first "
                                "(Ctrl+click or Shift+drag to select multiple).")
            return
        sdl = self._parse_entry(self.ent_sdl)
        ll  = self._parse_entry(self.ent_ll)
        if sdl is None or ll is None:
            messagebox.showerror("Error", "Invalid SDL/LL value.")
            return
        name = self.ent_name.get().strip()
        for it in self.selection:
            it.name = name
            it.sdl  = sdl
            it.ll   = ll
        ids = ", ".join(f"#{it.idx}" for it in self.selection)
        self._log(f"Applied to {len(self.selection)} regions ({ids}): "
                  f"name='{name}', SDL={sdl}, LL={ll}")
        self._redraw()

    def _apply_all(self):
        sdl = self._parse_entry(self.ent_sdl)
        ll  = self._parse_entry(self.ent_ll)
        if sdl is None or ll is None:
            messagebox.showerror("Error", "Invalid SDL/LL value.")
            return
        if not messagebox.askyesno(
                "Confirm",
                f"Assign SDL={sdl}, LL={ll} to ALL {len(self.area_items)} regions?"):
            return
        name = self.ent_name.get().strip()
        for it in self.area_items:
            it.sdl = sdl
            it.ll  = ll
            if name:                       # chi ghi de ten neu co nhap
                it.name = name
        self._log(f"Assigned SDL={sdl}, LL={ll}"
                  + (f", name='{name}'" if name else "")
                  + f" to all {len(self.area_items)} regions.")
        self._redraw()

    def _clear_sel(self):
        if not self.selection:
            return
        for it in self.selection:
            it.sdl  = 0.0
            it.ll   = 0.0
            it.name = ""
        self.ent_name.delete(0, tk.END)
        self.ent_sdl.delete(0, tk.END); self.ent_sdl.insert(0, "0")
        self.ent_ll.delete(0, tk.END);  self.ent_ll.insert(0, "0")
        self._log(f"Cleared assignment of {len(self.selection)} regions.")
        self._redraw()

    # ----- fetch layers from CPT -------------------------------------------
    def _fetch_layers(self):
        cpt = self.cpt_path.get().strip()
        if not cpt or not os.path.isfile(cpt):
            messagebox.showwarning("Warning", "Select a CPT file first.")
            return
        self._log("")
        threading.Thread(
            target=fetch_layer_names,
            args=(cpt, self._log_safe, self._got_layers),
            daemon=True).start()

    def _got_layers(self, names):
        def cb():
            if not names:
                return
            self.cb_sdl["values"] = names
            self.cb_ll["values"]  = names
            # auto match
            for n in names:
                if "dead" in n.lower() and "self" not in n.lower():
                    self.sdl_layer.set(n); break
            for n in names:
                if "reducible" in n.lower():
                    self.ll_layer.set(n); break
        self.after(0, cb)

    # ----- fetch slab + auto align -----------------------------------------
    def _fetch_slab(self):
        cpt = self.cpt_path.get().strip()
        if not cpt or not os.path.isfile(cpt):
            messagebox.showwarning("Warning", "Select a CPT file first.")
            return
        if not self.area_items:
            messagebox.showwarning("Warning", "Read the DXF file first.")
            return
        self._log("")
        threading.Thread(
            target=fetch_slab_outline,
            args=(cpt, self._log_safe, self._got_slab),
            daemon=True).start()

    def _got_slab(self, polys, bbox):
        def cb():
            if not polys:
                return
            self.slab_polys = polys
            self.slab_bbox  = bbox
            # Transform mac dinh sau khi read slab: mm->m, Offset X=0, Y=100
            self.unit_var.set("0.001")
            self.off_x.set("0.0")
            self.off_y.set("100.0")
            self._log("Read slab: default Unit=0.001 (mm->m), Offset X=0, Y=100.")
            self._log("RED outline = slab mesh. If not aligned, use 'Align 2 points' "
                      "or adjust Offset X/Y manually.")
            self._fit_view()
        self.after(0, cb)

    # ----- import ----------------------------------------------------------
    def _run_import(self):
        if not self.cpt_path.get().strip():
            messagebox.showwarning("Warning", "Select a CPT file.")
            return
        if not self.area_items:
            messagebox.showwarning("Warning", "Read the DXF file first.")
            return
        assigned = [it for it in self.area_items if it.assigned()]
        if not assigned:
            messagebox.showwarning("Warning", "No load assigned to any region.")
            return
        try:
            scale = float(self.unit_var.get())
            ox    = float(self.off_x.get())
            oy    = float(self.off_y.get())
        except ValueError:
            messagebox.showerror("Error", "Invalid unit scale / Offset.")
            return

        self.btn_import.config(state=tk.DISABLED, text="  Importing...  ")
        self._log_clear()
        self._log("=== START IMPORT ===")
        self._log(f"DXF      : {self.dxf_path.get()}")
        self._log(f"CPT      : {self.cpt_path.get()}")
        self._log(f"Scale    : x{scale}")
        self._log(f"Offset   : X={ox} m, Y={oy} m")
        self._log(f"SDL layer: {self.sdl_layer.get()}")
        self._log(f"LL layer : {self.ll_layer.get()}")
        self._log(f"Assigned regions: {len(assigned)}\n")

        threading.Thread(
            target=import_loads,
            args=(self.cpt_path.get(), assigned,
                  self.sdl_layer.get().strip(), self.ll_layer.get().strip(),
                  scale, ox, oy, self._log_safe, self._import_done),
            daemon=True).start()

    def _import_done(self, success):
        def cb():
            self.btn_import.config(state=tk.NORMAL,
                                   text="   IMPORT AREA LOAD INTO RAM CONCEPT   ")
            if success:
                messagebox.showinfo("Done", "Import successful! CPT file saved.")
            else:
                messagebox.showerror("Failed", "Import failed. See log.")
        self.after(0, cb)

    # ----- logging ---------------------------------------------------------
    def _log(self, msg):
        self.log_box.configure(state=tk.NORMAL)
        self.log_box.insert(tk.END, msg + "\n")
        self.log_box.see(tk.END)
        self.log_box.configure(state=tk.DISABLED)

    def _log_safe(self, msg):
        self.after(0, lambda m=msg: self._log(m))

    def _log_clear(self):
        self.log_box.configure(state=tk.NORMAL)
        self.log_box.delete("1.0", tk.END)
        self.log_box.configure(state=tk.DISABLED)


if __name__ == "__main__":
    App().mainloop()

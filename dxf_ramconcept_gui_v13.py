# ============================================================
# GUI: DXF → RAM Concept Mesh Model Builder  v13
# v12: FIX cột nằm ngang — swap w↔d
# v13: FIX cột swap → xoay thêm 90° để RAM Concept mesh đúng hướng
#
# Yêu cầu: pip install ezdxf
# Chạy:    python dxf_ramconcept_gui.py
# ============================================================

import os, sys, threading, math
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from datetime import datetime

# ─────────────────────────────────────────────────────────────
# PALETTE / STYLE  —  PTX brand (navy + steel-gray)
# ─────────────────────────────────────────────────────────────
BG_DARK    = "#0D1626"   # navy rất tối
BG_PANEL   = "#162040"   # navy tối
BG_CARD    = "#1C2B52"   # navy trung
BG_HOVER   = "#243565"
ACCENT     = "#4A74B8"   # PTX blue
ACCENT2    = "#8FA5C8"   # PTX silver-blue
SUCCESS    = "#34D399"
WARNING    = "#FBBF24"
ERROR      = "#F87171"
TEXT_PRI   = "#E8EDF8"   # trắng xanh nhạt
TEXT_SEC   = "#8FA5C8"   # PTX silver
TEXT_DIM   = "#4A5E7A"
BORDER     = "#26395E"
TAG_SLAB   = "#34D399"
TAG_COL    = "#FBBF24"
TAG_WALL   = "#60A5FA"
TAG_OPEN   = "#F87171"

# PTX brand colors (logo)
PTX_NAVY   = "#1C2C4E"   # màu chữ PT trong logo (trên nền sáng → đảo cho dark mode)
PTX_STEEL  = "#8090A8"   # màu chữ X trong logo

FONT_MAIN  = ("Segoe UI", 10)
FONT_BOLD  = ("Segoe UI", 10, "bold")
FONT_TITLE = ("Segoe UI", 14, "bold")
FONT_SMALL = ("Segoe UI", 9)
FONT_MONO  = ("Consolas", 9)


# ─────────────────────────────────────────────────────────────
# ĐỌC LAYER TỪ FILE DXF
# ─────────────────────────────────────────────────────────────

def get_dxf_layers(dxf_path: str):
    """Trả về (layers, error_msg). layers=[] nếu lỗi."""
    try:
        import ezdxf
    except ImportError:
        return [], "ezdxf is not installed.\nOpen CMD and run:  pip install ezdxf"
    try:
        doc = ezdxf.readfile(dxf_path)
        layers = sorted({e.dxf.layer for e in doc.modelspace()})
        return layers, None
    except Exception as e:
        return [], str(e)


# ─────────────────────────────────────────────────────────────
# LOGIC CHUYỂN ĐỔI
# ─────────────────────────────────────────────────────────────

def _round_to(value, base):
    """Làm tròn value tới bội số gần nhất của base (vd base=5 → 0,5,10,15...)."""
    if base <= 0:
        return round(value, 1)
    return round(value / base) * base


def _norm_col_angle(b, d, ang, snap_tol=1.0):
    """Chuẩn hoá angle cột về (-45°, 45°], hoán đổi b↔d khi cần.
    → Cột vuông angle trục (đứng/ngang) có angle 0°, width=cạnh X, depth=cạnh Y
      (cùng 1 hình chữ nhật, chỉ đổi cách biểu diễn b/d/góc).
    snap_tol: angle |a| < snap_tol (độ) → ép về đúng 0."""
    a = ang
    while a > 90.0:   a -= 180.0
    while a <= -90.0: a += 180.0
    if a > 45.0:
        a -= 90.0; b, d = d, b
    elif a <= -45.0:
        a += 90.0; b, d = d, b
    if abs(a) < snap_tol:
        a = 0.0
    return b, d, a


def _arc_grid_points(cx, cy, R, a_start, theta, min_seg):
    """Điểm trung gian trên cung tròn, đặt tại các angle theo LƯỚI TOÀN CỤC
    (bội số của bước angle Δ tính từ trục 0) thay vì chia đều từng cung.
    → 2 cung trên CÙNG đường tròn (cạnh chung 2 sàn) cho cùng các node → TRÙNG KHÍT.
    Trả về list (x,y) theo thứ tự dọc cung (không gồm 2 đầu mút)."""
    if R <= 1e-9 or abs(theta) < 1e-9:
        return []
    ratio = min(0.9999, min_seg / (2.0 * R))
    if ratio <= 1e-9:
        return []
    dstep = 2.0 * math.asin(ratio)          # bước angle cho dây cung = min_seg
    if dstep < 1e-9:
        return []
    tau = 2.0 * math.pi
    a_end = a_start + theta
    lo, hi = (a_start, a_end) if a_start <= a_end else (a_end, a_start)
    m_lo = math.floor(lo / dstep) - 1
    m_hi = math.ceil(hi / dstep) + 1
    out, seen = [], set()
    for m in range(m_lo, m_hi + 1):
        alpha = m * dstep                   # angle lưới toàn cục
        # Kiểm tra alpha có nằm TRÊN cung (theo modular, an toàn wrap ±π)
        if theta > 0:
            d = (alpha - a_start) % tau      # quãng CCW từ đầu cung
            if not (1e-7 < d < theta - 1e-7):
                continue
            frac = d
        else:
            d = (a_start - alpha) % tau      # quãng CW từ đầu cung
            if not (1e-7 < d < -theta - 1e-7):
                continue
            frac = d
        px, py = cx + R*math.cos(alpha), cy + R*math.sin(alpha)
        keyp = (round(px, 6), round(py, 6))
        if keyp in seen:
            continue
        seen.add(keyp)
        out.append((frac, (px, py)))
    out.sort(key=lambda t: t[0])            # thứ tự từ đầu cung
    return [p for _, p in out]


def _snap_shared_nodes(polys, tol=0.05):
    """Snap các node GẦN NHAU (< tol) giữa CÁC polygon khác nhau về 1 vị trí chung
    → edges chung của 2 miếng sàn có node trùng khít. polys: list[list[(x,y)]].
    Sửa trực tiếp và trả về polys."""
    reps = []   # các điểm đại diện đã chốt
    def find_rep(p):
        for r in reps:
            if math.hypot(p[0]-r[0], p[1]-r[1]) < tol:
                return r
        reps.append((p[0], p[1]))
        return reps[-1]
    for poly in polys:
        for i in range(len(poly)):
            poly[i] = find_rep(poly[i])
    return polys


def _clean_polygon(pts, dup_tol=0.002, col_tol=0.001):
    """Làm sạch polygon trước khi gửi RAM Concept (tránh TriSlabElement lỗi):
    - bỏ đỉnh trùng liên tiếp (< dup_tol)
    - bỏ đỉnh đóng trùng đỉnh đầu
    - bỏ đỉnh THẲNG HÀNG (nằm trên đoạn 2 đỉnh kề, lệch < col_tol) và đỉnh gai
    Trả về list điểm sạch (>=3) hoặc None nếu suy biến."""
    if not pts:
        return None
    out = []
    for p in pts:
        if not out or math.hypot(p[0]-out[-1][0], p[1]-out[-1][1]) > dup_tol:
            out.append((p[0], p[1]))
    if len(out) >= 2 and math.hypot(out[0][0]-out[-1][0], out[0][1]-out[-1][1]) <= dup_tol:
        out.pop()
    if len(out) < 3:
        return None
    changed = True
    while changed and len(out) > 3:
        changed = False
        for i in range(len(out)):
            a, b, c = out[i-1], out[i], out[(i+1) % len(out)]
            dx, dy = c[0]-a[0], c[1]-a[1]
            L = math.hypot(dx, dy)
            if L < 1e-9:                       # a≈c → b là gai → bỏ
                out.pop(i); changed = True; break
            d = abs(dy*(b[0]-a[0]) - dx*(b[1]-a[1])) / L
            if d < col_tol:                    # b thẳng hàng → bỏ
                out.pop(i); changed = True; break
    return out if len(out) >= 3 else None


def subdivide_slabs_by_depth(slabs, msp, unit_scale, layers, log_fn, slab_seg=0.8):
    """Chia mỗi tấm sàn thành nhiều VÙNG theo nét STEP / SOFFIT STEP, rồi gán
    bề dày (SLAB_DEPTH) và cao độ TOC cho từng vùng.

    Quy ước (đã chốt với người dùng):
      • STEP   = bậc MẶT TRÊN  -> qua STEP đổi TOC.
      • SOFFIT STEP = bậc ĐÁY  -> qua SOFFIT chỉ đổi bề dày, TOC GIỮ NGUYÊN.
      • Bề dày: callout SLAB_DEPTH; ưu tiên ĐÍCH LEADER (circle) khi có, vì text
        hexagon có thể nằm ở vùng khác (leader trỏ sang vùng thật).
      • Cao độ TOC: nếu có S.F.L tuyệt đối ("+119.350") -> lấy cao nhất = 0.
        Nếu KHÔNG có S.F.L -> dùng BƯỚC NHẢY trên layer STRUCTURAL FINISH FLOOR
        (số nằm trên sàn THẤP hơn = độ chênh mm); vùng cao nhất = 0.
        Vùng chỉ ngăn bởi SOFFIT dùng chung TOC (lan truyền).
      • Có cả S.F.L lẫn step-jump -> kiểm tra chéo, lệch thì cảnh báo.

    Trả về danh sách slab-dict mới (giữ nguyên slab không có callout bên trong).
    """
    try:
        from shapely.geometry import Polygon, LineString, Point
        from shapely.ops import unary_union, polygonize
    except Exception:
        log_fn("  ⚠ shapely chưa cài → bỏ qua auto-detect slab depth", "warning")
        return slabs

    import math as _m
    s = unit_scale

    def q(layer, etype):
        return msp.query('%s[layer=="%s"]' % (etype, layer))

    try:
        from ezdxf.math import bulge_to_arc as _b2a
    except Exception:
        _b2a = None

    def _flatten_poly(e):
        """LWPOLYLINE → điểm (m); CUNG CONG (bulge) chia thành đoạn thẳng theo
        LƯỚI ANGLE TOÀN CỤC (_arc_grid_points) — giống xử lý SLAB EDGE — để cung
        là biên chung của 2 vùng LUÔN TRÙNG node."""
        raw = list(e.get_points("xyb"))
        n = len(raw)
        if n < 2:
            return [(p[0]*s, p[1]*s) for p in raw]
        closed = bool(getattr(e, "is_closed", False))
        out = []
        cnt = n if closed else n - 1
        for i in range(cnt):
            x1, y1, b = raw[i][0]*s, raw[i][1]*s, raw[i][2]
            x2, y2 = raw[(i+1) % n][0]*s, raw[(i+1) % n][1]*s
            out.append((x1, y1))
            if abs(b) > 1e-6 and _b2a is not None:
                try:
                    center, _a0, _a1, R = _b2a((x1, y1), (x2, y2), b)
                    theta = 4.0 * _m.atan(b)            # angle cung có dấu
                    if R > 1e-9:
                        a_start = _m.atan2(y1 - center.y, x1 - center.x)
                        for ip in _arc_grid_points(center.x, center.y, R,
                                                   a_start, theta, slab_seg):
                            out.append(ip)
                except Exception:
                    pass
        out.append((raw[0][0]*s, raw[0][1]*s) if closed
                   else (raw[-1][0]*s, raw[-1][1]*s))
        return out

    def _circle_ring(cx, cy, r):
        ring = _arc_grid_points(cx, cy, r, 0.0, 2*_m.pi, slab_seg)
        if len(ring) < 3:
            ring = [(cx + r*_m.cos(2*_m.pi*k/12),
                     cy + r*_m.sin(2*_m.pi*k/12)) for k in range(12)]
        ring.append(ring[0])               # đóng vòng → tạo vùng tròn
        return ring

    def collect_lines(layer):
        out = []
        for e in q(layer, "LWPOLYLINE"):
            pts = _flatten_poly(e)
            if len(pts) >= 2:
                out.append(LineString(pts))
        for e in q(layer, "ARC"):          # cung tròn rời
            cx, cy, r = e.dxf.center.x*s, e.dxf.center.y*s, e.dxf.radius*s
            a0 = _m.radians(e.dxf.start_angle)
            theta = (_m.radians(e.dxf.end_angle) - a0) % (2*_m.pi)
            pts = [(cx + r*_m.cos(a0), cy + r*_m.sin(a0))]
            pts += _arc_grid_points(cx, cy, r, a0, theta, slab_seg)
            pts.append((cx + r*_m.cos(a0+theta), cy + r*_m.sin(a0+theta)))
            if len(pts) >= 2:
                out.append(LineString(pts))
        for e in q(layer, "CIRCLE"):       # đường tròn → vòng kín → vùng tròn
            out.append(LineString(_circle_ring(
                e.dxf.center.x*s, e.dxf.center.y*s, e.dxf.radius*s)))
        return out

    step_l  = layers.get("step",   "STEP")
    soff_l  = layers.get("soffit", "SOFFIT STEP")
    depth_l = layers.get("depth",  "SLAB_DEPTH")
    sfl_l   = layers.get("sfl",    "STRUCTURAL FINISH FLOOR")

    steps = collect_lines(step_l)
    soffs = collect_lines(soff_l)

    def _d(a, b):
        return _m.hypot(a[0]-b[0], a[1]-b[1])

    # ── Callout bề dày: pairing theo CIRCLE (đích leader thật) ──
    dtexts = []
    for t in q(depth_l, "TEXT"):
        try:
            v = int(round(float(t.dxf.text.strip())))
        except (ValueError, TypeError):
            continue
        dtexts.append((v, (t.dxf.insert.x*s, t.dxf.insert.y*s)))
    circles = [(c.dxf.center.x*s, c.dxf.center.y*s) for c in q(depth_l, "CIRCLE")]
    segs = []                            # đoạn leader ứng viên (LINE + polyline hở)
    for e in q(depth_l, "LINE"):
        segs.append(((e.dxf.start.x*s, e.dxf.start.y*s),
                     (e.dxf.end.x*s,   e.dxf.end.y*s)))
    for e in q(depth_l, "LWPOLYLINE"):
        if not getattr(e, "is_closed", False):
            pts = _ring(e)
            if len(pts) >= 2:
                segs.append((pts[0], pts[-1]))

    depth_pts = []
    used = set()
    for c in circles:
        leader = None
        for sg in segs:                  # leader = đoạn có 1 đầu CHẠM circle
            if _d(sg[0], c) <= 0.12 or _d(sg[1], c) <= 0.12:
                leader = sg
                break
        if leader is None:
            continue
        far = leader[1] if _d(leader[0], c) <= _d(leader[1], c) else leader[0]
        if dtexts:
            ti = min(range(len(dtexts)), key=lambda i: _d(dtexts[i][1], far))
            if _d(dtexts[ti][1], far) <= 2.0:
                depth_pts.append((dtexts[ti][0], Point(c)))
                used.add(ti)
    for i, (v, tp) in enumerate(dtexts):
        if i not in used:                # text không có leader -> dùng chính vị trí
            depth_pts.append((v, Point(tp)))

    if not depth_pts:
        log_fn("  ⚠ Không thấy callout SLAB_DEPTH → bỏ qua auto-detect", "warning")
        return slabs

    # ── Cao độ: S.F.L tuyệt đối ("+119.350") và bước nhảy (số thường) ──
    sfl_pts, step_pts = [], []
    for t in q(sfl_l, "TEXT"):
        txt = t.dxf.text.strip()
        p = (t.dxf.insert.x*s, t.dxf.insert.y*s)
        if txt.startswith("+"):
            try:
                sfl_pts.append((float(txt.replace("+", "")), Point(p)))
            except ValueError:
                pass
        else:
            try:
                step_pts.append((int(round(float(txt))), Point(p)))
            except ValueError:
                pass
    datum_sfl = max((v for v, _ in sfl_pts), default=None)

    log_fn(f"  Slab-depth: {len(depth_pts)} callout, {len(sfl_pts)} S.F.L, "
           f"{len(step_pts)} step-jump, {len(steps)} STEP, {len(soffs)} SOFFIT", "info")

    def snap_ends(ls, boundary, tol=0.25):
        pts = list(ls.coords)
        for idx in (0, -1):
            p = Point(pts[idx])
            if boundary.distance(p) <= tol:
                pr = boundary.interpolate(boundary.project(p))
                pts[idx] = (pr.x, pr.y)
        return LineString(pts)

    out_slabs = []
    region_no = 0
    for sd in slabs:
        base_pr  = sd.get("priority", 1)
        base_t   = sd.get("thickness", 200)
        base_toc = sd.get("toc", 0)
        try:
            poly = Polygon(sd["pts"])
            if not poly.is_valid:
                poly = poly.buffer(0)
        except Exception:
            out_slabs.append(sd); continue

        # Chỉ subdivide slab CÓ callout bên trong (bỏ bản vẽ phụ không callout)
        if poly.is_empty or not any(poly.contains(p) for _, p in depth_pts):
            out_slabs.append(sd); continue

        rstep = [l for l in steps if l.intersects(poly)]
        rsoff = [l for l in soffs if l.intersects(poly)]
        cut = [snap_ends(l, poly.boundary) for l in rstep + rsoff]
        if cut:
            merged = unary_union([poly.boundary] + cut)
            regions = [g for g in polygonize(merged)
                       if poly.buffer(-0.005).contains(g.representative_point())]
        else:
            regions = [poly]
        if not regions:
            regions = [poly]
        n = len(regions)
        cent = [g.representative_point() for g in regions]

        def near_val(pts, g, c):
            cand = [(v, p) for v, p in pts if g.contains(p)]
            if not cand:
                return None, 0
            cand.sort(key=lambda vp: c.distance(vp[1]))
            return cand[0][0], len(set(v for v, _ in cand))

        # Bề dày từng vùng
        thick = [None]*n
        for i in range(n):
            dv, nd = near_val(depth_pts, regions[i], cent[i])
            thick[i] = dv
            if dv is not None and nd > 1:
                log_fn(f"  ⚠ Vùng sàn #{region_no+i+1} có nhiều giá trị bề dày → "
                       f"chọn {dv}mm (gần trọng tâm), kiểm tra lại", "warning")

        # Phân loại biên: SOFFIT (cùng TOC) / STEP (khác TOC)
        soffadj = [[] for _ in range(n)]
        stepadj = [dict() for _ in range(n)]
        for i in range(n):
            for j in range(i+1, n):
                sh = regions[i].boundary.intersection(regions[j].boundary)
                if sh.is_empty or sh.length < 0.05:
                    continue
                mid = sh.interpolate(sh.length/2)
                dso = min((so.distance(mid) for so in rsoff), default=9e9)
                dst = min((st.distance(mid) for st in rstep), default=9e9)
                if dso < 0.06 and dso <= dst:
                    soffadj[i].append(j); soffadj[j].append(i)
                elif dst < 0.20:
                    stepadj[i][j] = sh; stepadj[j][i] = sh

        # Anchor S.F.L (nếu có)
        toc_anchor = [None]*n
        if datum_sfl is not None:
            for i in range(n):
                sv, _ = near_val(sfl_pts, regions[i], cent[i])
                if sv is not None:
                    toc_anchor[i] = int(round((sv - datum_sfl) * 1000))

        # Bước nhảy: số ở vùng THẤP; vùng cao = step-neighbor gần text nhất
        jumps = []
        for val, p in step_pts:
            li = next((i for i in range(n) if regions[i].contains(p)), None)
            if li is None or not stepadj[li]:
                continue
            hj = min(stepadj[li], key=lambda j: stepadj[li][j].distance(p))
            jumps.append((li, hj, val))

        # Đồ thị delta: rel[v] = rel[u] + delta
        graph = [[] for _ in range(n)]
        for i in range(n):
            for j in soffadj[i]:
                graph[i].append((j, 0))
        for li, hj, val in jumps:
            graph[li].append((hj, +val))   # rel[lower] = rel[higher] - val
            graph[hj].append((li, -val))

        rel = [None]*n
        for start in range(n):
            if rel[start] is not None:
                continue
            rel[start] = toc_anchor[start] if toc_anchor[start] is not None else 0
            stack = [start]
            while stack:
                u = stack.pop()
                for v, dlt in graph[u]:
                    if rel[v] is None:
                        rel[v] = rel[u] + dlt
                        stack.append(v)
        if datum_sfl is None and any(r is not None for r in rel):
            mx = max(r for r in rel if r is not None)
            rel = [None if r is None else r - mx for r in rel]
        toc = rel

        # Kiểm tra chéo S.F.L vs step-jump
        if datum_sfl is not None:
            for i in range(n):
                sv, _ = near_val(sfl_pts, regions[i], cent[i])
                if sv is not None and toc[i] is not None:
                    expect = int(round((sv - datum_sfl)*1000))
                    if toc[i] != expect:
                        log_fn(f"  ⚠ Vùng #{region_no+i+1}: S.F.L→TOC={expect} nhưng "
                               f"step-jump→{toc[i]} — kiểm tra chéo", "warning")
        for li, hj, val in jumps:
            if toc[li] is not None and toc[hj] is not None \
                    and abs((toc[hj]-toc[li]) - val) > 1:
                log_fn(f"  ⚠ Bước nhảy {val}mm không khớp cao độ tính được "
                       f"({toc[hj]-toc[li]}mm) — kiểm tra", "warning")

        # Kế thừa khi thiếu
        fulladj = [[] for _ in range(n)]
        for i in range(n):
            for j in range(i+1, n):
                sh = regions[i].boundary.intersection(regions[j].boundary)
                if not sh.is_empty and sh.length >= 0.05:
                    fulladj[i].append(j); fulladj[j].append(i)
        for i in range(n):
            if thick[i] is None:
                inh = next((thick[j] for j in fulladj[i] if thick[j] is not None), None)
                thick[i] = inh if inh is not None else base_t
                log_fn(f"  ⚠ Vùng sàn #{region_no+i+1} thiếu bề dày → "
                       f"{'kế thừa' if inh else 'mặc định'} {thick[i]}mm", "warning")
            if toc[i] is None:
                toc[i] = base_toc
                log_fn(f"  ⚠ Vùng sàn #{region_no+i+1} thiếu cao độ → TOC={base_toc}mm",
                       "warning")

        # Priority theo độ LỒNG: vùng nằm TRONG vùng khác (đảo soffit/step kín).
        # Khi xuất ta lấp lỗ (chỉ giữ exterior) nên vùng ngoài ĐÈ lên vùng trong
        # -> vùng trong phải priority CAO hơn để thắng trong RAM Concept.
        filled = [Polygon(g.exterior) for g in regions]
        prio = [base_pr]*n
        for i in range(n):
            depth = 0
            for j in range(n):
                if j != i and filled[j].area > regions[i].area * 1.001 \
                        and filled[j].contains(cent[i]):
                    depth += 1
            prio[i] = base_pr + depth

        for i, g in enumerate(regions):
            ring = list(g.exterior.coords)[:-1]
            out_slabs.append({"pts": ring, "thickness": thick[i],
                              "toc": toc[i], "priority": prio[i]})
            if n > 1:
                log_fn(f"  ✓ Vùng sàn #{region_no+i+1}: {g.area:.1f} m² → "
                       f"dày {thick[i]}mm, TOC {toc[i]:+d}mm, Priority={prio[i]}",
                       "success")
        region_no += n

    return out_slabs


def run_conversion(config: dict, log_fn) -> bool:
    dxf_file     = config["dxf_file"]
    cpt_template = config["cpt_template"]
    cpt_output   = config["cpt_output"]
    ram_api_path = config["ram_api_path"]
    unit_scale   = config["unit_scale"]
    slab_thick   = config["slab_thick"]
    col_height   = config["col_height"]
    wall_thick   = config["wall_thick"]
    mesh_size    = config["mesh_size"]
    opening_seg  = config.get("opening_seg", 1.0)  # edges tối thiểu xấp xỉ lỗ tròn (m)
    slab_seg     = config.get("slab_seg", 0.8)     # edges tối thiểu khi làm phẳng biên sàn cong (m)
    wall_seg     = config.get("wall_seg", 0.8)     # day cung toi thieu khi chia vach cong (m)
    layer_map    = config["layer_map"]   # {"slabs": "L1", "columns": "L2", ...}

    if not os.path.isfile(dxf_file):
        log_fn(f"[ERROR] DXF file not found: {dxf_file}", "error")
        return False

    try:
        import ezdxf
    except ImportError:
        log_fn("[ERROR] ezdxf missing. Run: pip install ezdxf", "error")
        return False

    log_fn("STEP 1 — READ DXF FILE", "title")
    log_fn(f"  File  : {dxf_file}", "info")
    # Chuẩn hoá slabs config → list of dict
    slabs_cfg = layer_map.get("slabs", [])
    if isinstance(slabs_cfg, str):
        slabs_cfg = ([{"layer": slabs_cfg, "thickness": slab_thick, "priority": 1}]
                     if slabs_cfg else [])
    slab_layer_cfg = {}   # UPPER_NAME → config dict
    for cfg in slabs_cfg:
        ln = cfg.get("layer", "").strip()
        if ln:
            slab_layer_cfg[ln.upper()] = cfg

    slab_names = [c.get("layer","") for c in slabs_cfg if c.get("layer")]
    log_fn(f"  Layers: Slab={slab_names or '—'}  "
           f"Column={layer_map.get('columns','') or '—'}  "
           f"Wall={layer_map.get('walls','') or '—'}  "
           f"Opening={layer_map.get('openings','') or '—'}", "info")

    try:
        doc = ezdxf.readfile(dxf_file)
        msp = doc.modelspace()
    except Exception as e:
        log_fn(f"[ERROR] Could not read DXF: {e}", "error")
        return False

    # Đảo ngược layer_map: tên layer → key (slabs xử lý riêng)
    rev_map = {}
    for key, lname in layer_map.items():
        if key == "slabs":
            continue
        if lname:
            rev_map[lname.upper()] = key
    for ln in slab_layer_cfg:
        rev_map[ln] = "slabs"

    data = {"slabs": [], "columns": [], "walls": [], "openings": [], "walls_curved": []}

    import math

    # ── Hàm lọc vách trùng nhau ───────────────────────────────
    def wall_key(p1, p2, tol=0.010):
        """Tạo key chuẩn hoá cho đoạn vách (không phân biệt chiều)."""
        # Làm tròn để gộp các đoạn gần nhau
        a = (round(p1[0]/tol)*tol, round(p1[1]/tol)*tol)
        b = (round(p2[0]/tol)*tol, round(p2[1]/tol)*tol)
        return (min(a,b), max(a,b))

    # ── Xấp xỉ đường tròn bằng đa giác đều ────────────────────
    def circle_to_polygon(cx, cy, r, min_seg):
        """Trả về list đỉnh đa giác đều xấp xỉ đường tròn (cx,cy,r),
        sao cho MỖI edges (dây cung) >= min_seg.
        chord = 2·r·sin(π/N) ≥ min_seg  →  N ≤ π / asin(min_seg/(2r))."""
        import math as _mm
        if r <= 0:
            return []
        ratio = min_seg / (2.0 * r)
        if ratio >= 1.0:
            n = 3                      # tròn quá nhỏ so với edges → tam giác
        else:
            n = int(_mm.floor(_mm.pi / _mm.asin(ratio)))
        n = max(3, min(n, 64))         # kẹp [3, 64] đỉnh
        return [(cx + r*_mm.cos(2*_mm.pi*i/n),
                 cy + r*_mm.sin(2*_mm.pi*i/n)) for i in range(n)]

    # ── Làm phẳng LWPOLYLINE có cung tròn (bulge) ─────────────
    def flatten_lwpolyline(entity, scale, min_seg):
        """Đọc LWPOLYLINE → list (x,y) đã *scale, các CUNG TRÒN (bulge)
        được chia thành đoạn thẳng sao cho mỗi dây cung >= min_seg.
        - Bán kính lớn (cung thoải): nhiều đoạn dài.
        - Bán kính nhỏ (cung gắt): ít đoạn, nhưng dây cung vẫn >= min_seg.
        Đoạn thẳng (bulge≈0) giữ nguyên."""
        import math as _mm
        try:
            from ezdxf.math import bulge_to_arc
        except Exception:
            bulge_to_arc = None

        raw = list(entity.get_points("xyb"))   # (x, y, bulge)
        n = len(raw)
        if n < 2:
            return [(p[0]*scale, p[1]*scale) for p in raw]
        closed = entity.is_closed
        out = []
        count = n if closed else n - 1
        for i in range(count):
            x1, y1, b = raw[i][0], raw[i][1], raw[i][2]
            x2, y2    = raw[(i+1) % n][0], raw[(i+1) % n][1]
            p1 = (x1*scale, y1*scale)
            p2 = (x2*scale, y2*scale)
            out.append(p1)
            if abs(b) > 1e-6 and bulge_to_arc is not None:
                try:
                    center, _a0, _a1, R = bulge_to_arc(p1, p2, b)
                    theta = 4.0 * _mm.atan(b)          # angle cung có dấu
                    if R > 1e-9:
                        cx, cy = center.x, center.y
                        a_start = _mm.atan2(p1[1]-cy, p1[0]-cx)
                        # Node theo lưới angle toàn cục → edges chung 2 sàn trùng khít
                        for ip in _arc_grid_points(cx, cy, R, a_start, theta, min_seg):
                            out.append(ip)
                except Exception:
                    pass
        if not closed:
            out.append((raw[-1][0]*scale, raw[-1][1]*scale))
        return out

    # ── Hàm tính tim vách từ LWPOLYLINE 2 đường viền ──────────
    def extract_wall_centerline(pts, is_closed):
        """
        Trả về list các (p1, p2, kind, thick_m):
          - kind="rect": tim hình chữ nhật 4 điểm — AUTHORITATIVE,
            thick_m = bề thickness thực (cạnh ngắn). KHÔNG bao giờ bị lọc stub.
          - kind="poly": edges của polyline >4 điểm / hở — thick=None,
            sẽ được _merge_parallel_walls gộp cặp song song & lọc stub.
        """
        import math as _math

        def seg_len(a, b):
            return _math.hypot(b[0]-a[0], b[1]-a[1])

        n = len(pts)
        if n < 2:
            return []

        # Phát hiện pseudo-closed (điểm đầu ≈ điểm cuối)
        pseudo_closed = (n >= 4 and seg_len(pts[0], pts[-1]) < 0.001)
        effectively_closed = is_closed or pseudo_closed

        # Chuẩn hoá bỏ điểm cuối trùng đầu
        work = list(pts)
        if effectively_closed and seg_len(work[0], work[-1]) < 0.001:
            work = work[:-1]
        m = len(work)

        if m < 2:
            return []

        # ── Closed 4 điểm → tim hình chữ nhật (AUTHORITATIVE) ────
        if effectively_closed and m == 4:
            sides = sorted(
                [(seg_len(work[i], work[(i+1)%4]), i) for i in range(4)],
                reverse=True
            )
            mids = []
            for _, si in sides[2:]:      # 2 edges ngắn nhất = đầu/cuối vách
                a = work[si]; b = work[(si+1) % 4]
                mids.append(((a[0]+b[0])/2, (a[1]+b[1])/2))
            L = seg_len(mids[0], mids[1])
            if L > 0.001:
                # thick = bề thickness thực = trung bình 2 edges ngắn
                thick = (sides[2][0] + sides[3][0]) / 2
                return [(mids[0], mids[1], "rect", thick)]
            return []

        # ── Mọi trường hợp còn lại → trả tất cả các đoạn (poly) ──
        # (closed >4 điểm hoặc open): _merge_parallel_walls sẽ xử lý sau
        segs = []
        for i in range(m - 1):
            L = seg_len(work[i], work[i+1])
            if L > 0.001:
                segs.append((work[i], work[i+1], "poly", None))
        if effectively_closed:
            L = seg_len(work[-1], work[0])
            if L > 0.001:
                segs.append((work[-1], work[0], "poly", None))
        return segs

    # ── Tim vách CONG (LWPOLYLINE có bulge) bằng MEDIAL (ghép điểm đối diện) ──
    def curved_wall_segments(entity, scale, min_seg):
        """Vách cong → list (p1,p2,thick) tim vách, mỗi đoạn ≈ min_seg.
        Bền cho cong thuần / thẳng+cong / đầu vách phức tạp.
        Trả None nếu KHÔNG cong (để đường thẳng xử lý như cũ)."""
        import math as _mm
        try:
            from ezdxf.math import bulge_to_arc as _b2a
        except Exception:
            _b2a = None
        try:
            raw = list(entity.get_points("xyb"))
        except Exception:
            return None
        verts = [(p[0]*scale, p[1]*scale, p[2]) for p in raw]
        n = len(verts)
        if n < 3:
            return None
        closed = bool(entity.is_closed)
        cnt = n if closed else n - 1
        if not any(abs(verts[i][2]) > 1e-6 for i in range(cnt)):
            return None   # không cong → để path cũ xử lý

        # 1) Làm phẳng outline (cả cạnh thẳng & cung) thành điểm dày ~ min_seg/4
        fine = max(0.03, min_seg / 4.0)
        FP = []
        for i in range(cnt):
            x1, y1, b = verts[i]
            j = (i + 1) % n
            x2, y2 = verts[j][0], verts[j][1]
            FP.append((x1, y1))
            if abs(b) > 1e-6 and _b2a:
                try:
                    c, _a, _a2, R = _b2a((x1, y1), (x2, y2), b)
                    theta = 4.0 * _mm.atan(b)
                    if R > 1e-9:
                        cx, cy = c.x, c.y; a0 = _mm.atan2(y1 - cy, x1 - cx)
                        npn = max(1, int(abs(R * theta) / fine))
                        for k in range(1, npn):
                            a = a0 + theta * k / npn
                            FP.append((cx + R * _mm.cos(a), cy + R * _mm.sin(a)))
                except Exception:
                    pass
            else:
                L = _mm.hypot(x2 - x1, y2 - y1)
                npn = max(1, int(L / fine))
                for k in range(1, npn):
                    FP.append((x1 + (x2 - x1) * k / npn, y1 + (y2 - y1) * k / npn))
        M = len(FP)
        if M < 6:
            return None

        # 2) Ghép điểm đối diện (cách ~nửa vòng) → bề dày + nhãn "đang trên mặt vách"
        lo, hi = int(M * 0.15), int(M * 0.85)
        opp = [0] * M; ds = [0.0] * M
        for i in range(M):
            best = 1e18; bj = i
            for off in range(lo, hi + 1):
                j = (i + off) % M
                d = _mm.hypot(FP[i][0] - FP[j][0], FP[i][1] - FP[j][1])
                if d < best:
                    best = d; bj = j
            opp[i] = bj; ds[i] = best
        sd = sorted(ds); thick = sd[len(sd) // 2]      # bề dày ≈ trung vị khoảng cách đối diện
        if thick < 1e-6:
            return None
        marked = [0.55 * thick <= ds[i] <= 1.6 * thick for i in range(M)]

        # 3) Lấy MẶT dài nhất (run liên tục dài nhất) → tim theo thứ tự dọc mặt (không zigzag)
        dbl = marked + marked; bs = bl = cs = cl = 0
        for i in range(2 * M):
            if dbl[i]:
                if cl == 0:
                    cs = i
                cl += 1
                if cl > bl:
                    bl = cl; bs = cs
            else:
                cl = 0
        if bl > M:
            bl = M
        if bl < 2:
            return None
        faceA = [(bs + k) % M for k in range(bl)]
        center = [((FP[i][0] + FP[opp[i]][0]) / 2, (FP[i][1] + FP[opp[i]][1]) / 2)
                  for i in faceA]
        # bỏ điểm trùng
        order = [center[0]]
        for p in center[1:]:
            if _mm.hypot(p[0] - order[-1][0], p[1] - order[-1][1]) > thick * 0.15:
                order.append(p)
        # bỏ spike (rẽ > 55° tại 1 điểm = nhiễu, vì ở độ phân giải mịn vách không rẽ gắt vậy)
        i = 1
        while i < len(order) - 1:
            a1 = _mm.atan2(order[i][1]-order[i-1][1], order[i][0]-order[i-1][0])
            a2 = _mm.atan2(order[i+1][1]-order[i][1], order[i+1][0]-order[i][0])
            dd = abs(a2 - a1) % (2 * _mm.pi)
            if min(dd, 2 * _mm.pi - dd) > _mm.radians(55):
                order.pop(i)
            else:
                i += 1
        if len(order) < 2:
            return None

        # 4) min_seg CHỈ chia phần CONG; phần THẲNG giữ nguyên 1 đoạn.
        m2 = len(order)
        if m2 < 2:
            return None
        TH = _mm.radians(2.5)
        curved = [False] * m2
        for i in range(1, m2 - 1):
            a1 = _mm.atan2(order[i][1]-order[i-1][1], order[i][0]-order[i-1][0])
            a2 = _mm.atan2(order[i+1][1]-order[i][1], order[i+1][0]-order[i][0])
            dd = abs(a2 - a1) % (2 * _mm.pi)
            curved[i] = min(dd, 2 * _mm.pi - dd) > TH
        # làm mượt nhãn (1 đỉnh cong nếu nó hoặc lân cận cong) -> tránh nhiễu chuyển tiếp
        sm = [curved[i] or (i > 0 and curved[i-1]) or (i < m2-1 and curved[i+1])
              for i in range(m2)]
        # gom thành các run liên tiếp cùng loại (thẳng / cong)
        runs = []; s = 0
        for i in range(1, m2):
            if sm[i] != sm[s]:
                runs.append((s, i, sm[s])); s = i
        runs.append((s, m2 - 1, sm[s]))

        def _seglen(a, b):
            return sum(_mm.hypot(order[t+1][0]-order[t][0], order[t+1][1]-order[t][1])
                       for t in range(a, b))

        def _sample_range(a, b, tt):
            tot = _seglen(a, b)
            if tot < 1e-9:
                return order[a]
            tg = tt * tot; acc = 0.0
            for t in range(a, b):
                s2 = _mm.hypot(order[t+1][0]-order[t][0], order[t+1][1]-order[t][1])
                if acc + s2 >= tg:
                    f = (tg - acc) / (s2 or 1e-9)
                    return (order[t][0]+f*(order[t+1][0]-order[t][0]),
                            order[t][1]+f*(order[t+1][1]-order[t][1]))
                acc += s2
            return order[b]

        outpts = [order[0]]
        for (a, b, isc) in runs:
            if not isc:
                outpts.append(order[b])               # đoạn thẳng -> 1 đoạn
            else:
                L = _seglen(a, b)
                N = max(1, round(L / min_seg))         # cong -> chia đều ≈ min_seg
                for k in range(1, N + 1):
                    outpts.append(_sample_range(a, b, k / N))

        # GIỮ mọi đoạn (kể cả < min_seg) để KHÔNG thiếu wall; chỉ bỏ điểm trùng (<1mm)
        cleaned = [outpts[0]]
        for p in outpts[1:]:
            if _mm.hypot(p[0]-cleaned[-1][0], p[1]-cleaned[-1][1]) > 0.001:
                cleaned.append(p)
        # Kéo dài 2 đầu medial tới ĐÚNG mút vách.
        # Phép ghép điểm đối diện (offset 15%-85% chu vi) KHÔNG bắt được cặp mặt
        # ngang qua end-cap ở đầu tự do -> tim bị CẮT CỤT ~0.075*chu_vi mỗi đầu
        # (vd vách L này mất ~1.6m mỗi đầu). Snap đầu tim vào GIỮA cạnh end-cap.
        if len(cleaned) >= 2:
            # cạnh outline dài ≈ bề dày = end-cap (mặt bịt đầu nối 2 mặt vách)
            caps = []
            for i in range(cnt):
                cx1, cy1, _bb = verts[i]
                cj = (i + 1) % n
                cx2, cy2 = verts[cj][0], verts[cj][1]
                Lc = _mm.hypot(cx2 - cx1, cy2 - cy1)
                if 0.6 * thick <= Lc <= 1.5 * thick:
                    caps.append(((cx1 + cx2) / 2, (cy1 + cy2) / 2))

            def _ext(a, b):
                """Snap đầu 'a' (tiếp theo là 'b' phía trong) vào end-cap nằm đúng
                hướng tangent đi ra ngoài; nếu không có cap thì nới ~½ bề dày."""
                dx, dy = a[0] - b[0], a[1] - b[1]
                L = _mm.hypot(dx, dy)
                if L < 1e-9:
                    return a
                ux, uy = dx / L, dy / L
                best = None; bestd = 1e18
                for cm in caps:
                    vx, vy = cm[0] - a[0], cm[1] - a[1]
                    # cap phải ở phía NGOÀI (cùng hướng tangent) & gần như thẳng hàng
                    if vx * ux + vy * uy > 0 and abs(vx * uy - vy * ux) <= thick:
                        d = _mm.hypot(vx, vy)
                        if d < bestd:
                            bestd = d; best = cm
                if best is not None:
                    return best
                return (a[0] + ux * thick / 2, a[1] + uy * thick / 2)
            cleaned[0] = _ext(cleaned[0], cleaned[1])
            cleaned[-1] = _ext(cleaned[-1], cleaned[-2])
        return [(cleaned[i], cleaned[i+1], thick) for i in range(len(cleaned)-1)]

    seen_walls = set()   # dùng để lọc vách trùng
    rect_info  = {}      # wall_key → thick_m cho centerline rect (authoritative)

    for entity in msp:
        layer = entity.dxf.layer.upper()
        key   = rev_map.get(layer)
        if key is None:
            continue

        # ── LWPOLYLINE ────────────────────────────────────────
        if entity.dxftype() == "LWPOLYLINE":
            pts = [(v[0]*unit_scale, v[1]*unit_scale)
                   for v in entity.get_points("xy")]

            if key == "walls":
                # Vách CONG (có bulge) -> tim 2 mặt -> chia đoạn thẳng >= wall_seg.
                cw = curved_wall_segments(entity, unit_scale, wall_seg)
                if cw is not None:
                    # Vach cong: tim da chuan -> KHONG cho qua hau xu ly (merge/snap)
                    for p1, p2, thick in cw:
                        k = wall_key(p1, p2)
                        if k not in seen_walls:
                            seen_walls.add(k)
                            data["walls_curved"].append((p1, p2, thick))
                else:
                    # Vách thẳng (4 diem) -> tim hcn nhu cu.
                    pts_w = flatten_lwpolyline(entity, unit_scale, wall_seg)
                    segs = extract_wall_centerline(pts_w, entity.is_closed)
                    for p1, p2, kind, thick in segs:
                        k = wall_key(p1, p2)
                        if k not in seen_walls:
                            seen_walls.add(k)
                            data["walls"].append((p1, p2))
                            if kind == "rect":
                                rect_info[k] = thick   # authoritative, không lọc

            else:
                # Chỉ đọc LWPOLYLINE KHÉP KÍN cho slab / column / opening.
                # Polyline HỞ (trừ walls) -> bỏ qua, không tạo phần tử.
                is_closed_poly = bool(getattr(entity, "is_closed", False)) or (
                    len(pts) >= 3 and
                    (pts[0][0]-pts[-1][0])**2 + (pts[0][1]-pts[-1][1])**2 < 1e-6)
                if not is_closed_poly:
                    log_fn(f"  ⚠ Skipped open polyline on layer '{layer}' ({key})", "warning")
                    continue

                if key == "columns":
                    if len(pts) >= 3:
                        # Bỏ điểm đóng trùng điểm đầu
                        work = list(pts)
                        if (len(work) >= 2 and
                                (work[0][0]-work[-1][0])**2 + (work[0][1]-work[-1][1])**2 < 1e-6):
                            work = work[:-1]

                        if len(work) == 4:
                            # ── Hình chữ nhật CÓ THỂ XOAY → kích thước & angle THỰC ──
                            cx = sum(p[0] for p in work) / 4.0
                            cy = sum(p[1] for p in work) / 4.0
                            s1 = (work[1][0]-work[0][0], work[1][1]-work[0][1])
                            s2 = (work[2][0]-work[1][0], work[2][1]-work[1][1])
                            b_col = math.hypot(s1[0], s1[1])
                            d_col = math.hypot(s2[0], s2[1])
                            ang = math.degrees(math.atan2(s1[1], s1[0]))
                            # Chuẩn hoá về (-45,45]: cột đứng/ngang → angle 0, b=X, d=Y
                            b_col, d_col, ang = _norm_col_angle(b_col, d_col, ang)
                        else:
                            # Đa giác khác → bbox, không xoay
                            xs = [p[0] for p in work]; ys = [p[1] for p in work]
                            cx = (max(xs)+min(xs))/2; cy = (max(ys)+min(ys))/2
                            b_col = max(xs)-min(xs); d_col = max(ys)-min(ys); ang = 0.0

                        data["columns"].append({
                            "cx": cx, "cy": cy,
                            "w": b_col, "d": d_col,
                            "angle": ang        # độ, 0 = edges b dọc trục x global
                        })
                else:
                    # Sàn / lỗ mở: làm phẳng cung tròn (bulge) → đoạn thẳng ≥ seg_min
                    seg_min = opening_seg if key == "openings" else slab_seg
                    pts_f = flatten_lwpolyline(entity, unit_scale, seg_min)
                    if len(pts_f) >= 3:
                        if key == "slabs":
                            cfg = slab_layer_cfg.get(layer, {})
                            data["slabs"].append({
                                "pts":       pts_f,
                                "thickness": cfg.get("thickness", round(slab_thick * 1000)),
                                "toc":       cfg.get("toc", 0),
                                "priority":  cfg.get("priority", 1),
                            })
                        else:
                            data[key].append(pts_f)

        # ── LINE → wall ───────────────────────────────────────
        # ── CIRCLE → cột tròn ────────────────────────────────────
        elif entity.dxftype() == "CIRCLE" and key == "columns":
            cx  = entity.dxf.center.x * unit_scale
            cy  = entity.dxf.center.y * unit_scale
            dia = entity.dxf.radius * unit_scale * 2
            if dia > 0.001:
                data["columns"].append({
                    "cx": cx, "cy": cy,
                    "w": 0.0,   # b=0 → RAM Concept nhận dạng cột tròn
                    "d": dia,   # d = đường kính
                    "angle": 0.0,
                    "circular": True
                })

        # ── CIRCLE → lỗ mở / sàn tròn (xấp xỉ đa giác) ───────────
        elif entity.dxftype() == "CIRCLE" and key in ("openings", "slabs"):
            cx = entity.dxf.center.x * unit_scale
            cy = entity.dxf.center.y * unit_scale
            r  = entity.dxf.radius   * unit_scale
            seg_min = slab_seg if key == "slabs" else opening_seg
            poly = circle_to_polygon(cx, cy, r, seg_min)
            if len(poly) >= 3:
                cedge = 2*r*math.sin(math.pi/len(poly))*1000
                if key == "slabs":
                    cfg = slab_layer_cfg.get(layer, {})
                    data["slabs"].append({
                        "pts":       poly,
                        "thickness": cfg.get("thickness", round(slab_thick * 1000)),
                        "toc":       cfg.get("toc", 0),
                        "priority":  cfg.get("priority", 1),
                    })
                    log_fn(f"  Circular slab Ø{r*2000:.0f}mm → polygon {len(poly)} edges "
                           f"(edge ≈{cedge:.0f}mm)", "info")
                else:
                    data["openings"].append(poly)
                    log_fn(f"  Circular hole Ø{r*2000:.0f}mm → polygon {len(poly)} edges "
                           f"(edge ≈{cedge:.0f}mm)", "info")

        elif entity.dxftype() == "LINE" and key == "walls":
            p1 = (entity.dxf.start.x*unit_scale, entity.dxf.start.y*unit_scale)
            p2 = (entity.dxf.end.x  *unit_scale, entity.dxf.end.y  *unit_scale)
            L  = ((p2[0]-p1[0])**2+(p2[1]-p1[1])**2)**0.5
            if L > 0.001:
                k = wall_key(p1, p2)
                if k not in seen_walls:
                    seen_walls.add(k)
                    data["walls"].append((p1, p2))

        # ── INSERT (block) → column ───────────────────────────
        elif entity.dxftype() == "INSERT" and key == "columns":
            cx    = entity.dxf.insert.x * unit_scale
            cy    = entity.dxf.insert.y * unit_scale
            angle = getattr(entity.dxf, "rotation", 0.0)   # độ

            # ── Tâm cột: từ bbox global của hình học đã explode ──
            # (AABB của hcn xoay vẫn ĐỐI XỨNG TÂM → tâm AABB = tâm cột)
            try:
                xs_w, ys_w = [], []
                for ve in entity.virtual_entities():
                    if ve.dxftype() == "LWPOLYLINE":
                        for v in ve.get_points("xy"):
                            xs_w.append(v[0]*unit_scale)
                            ys_w.append(v[1]*unit_scale)
                    elif ve.dxftype() == "LINE":
                        xs_w += [ve.dxf.start.x*unit_scale, ve.dxf.end.x*unit_scale]
                        ys_w += [ve.dxf.start.y*unit_scale, ve.dxf.end.y*unit_scale]
                if xs_w and ys_w:
                    cx = (max(xs_w)+min(xs_w))/2
                    cy = (max(ys_w)+min(ys_w))/2
            except Exception:
                pass

            # ── Kích thước LOCAL của block (CHƯA xoay) × scale ──
            # b/d thực = edges block; angle quay = rotation của INSERT
            w_final, d_final = 0.0, 0.0
            try:
                block = doc.blocks[entity.dxf.name]
                xs_b, ys_b = [], []
                for be in block:
                    if be.dxftype() == "LWPOLYLINE":
                        for v in be.get_points("xy"):
                            xs_b.append(v[0]); ys_b.append(v[1])
                    elif be.dxftype() == "LINE":
                        xs_b += [be.dxf.start.x, be.dxf.end.x]
                        ys_b += [be.dxf.start.y, be.dxf.end.y]
                if xs_b and ys_b:
                    xscale = abs(getattr(entity.dxf, "xscale", 1.0))
                    yscale = abs(getattr(entity.dxf, "yscale", 1.0))
                    w_final = (max(xs_b)-min(xs_b)) * unit_scale * xscale
                    d_final = (max(ys_b)-min(ys_b)) * unit_scale * yscale
            except Exception:
                pass

            if w_final < 0.001: w_final = 0.3
            if d_final < 0.001: d_final = 0.3

            # Chuẩn hoá (-45,45]: cột đứng/ngang → angle 0, b/d khớp X/Y
            w_final, d_final, ang = _norm_col_angle(w_final, d_final, angle)
            data["columns"].append({
                "cx":    cx,
                "cy":    cy,
                "w":     w_final,
                "d":     d_final,
                "angle": ang
            })

    log_fn(f"  ✓ Slab:{len(data['slabs'])}  Column:{len(data['columns'])}"
           f"  Wall:{len(data['walls'])}  Opening:{len(data['openings'])}", "success")

    # ── Gộp các cặp LINE song song thành 1 tim vách ────────────
    # Xử lý trường hợp vách DXF vẽ bằng 2 LINE song song (2 mặt vách)
    def _merge_parallel_walls(walls, rect_keys, max_gap=0.8):
        """
        Tìm và gộp các cặp đoạn thẳng song song gần nhau
        (khoảng cách < max_gap, overlap >30%) → tim trung bình.

        rect_keys: dict wall_key → thick_m. Các segment có key trong đây là
        centerline rect AUTHORITATIVE → giữ nguyên, KHÔNG gộp, KHÔNG lọc stub.
        Chỉ segment poly (outline >4 điểm) mới qua merge + lọc stub.
        """
        import math as _m

        def seg_len(a, b):
            return _m.hypot(b[0]-a[0], b[1]-a[1])

        def seg_angle(a, b):
            return _m.atan2(b[1]-a[1], b[0]-a[0]) % _m.pi

        def pt_line_dist(pt, a, b):
            dx, dy = b[0]-a[0], b[1]-a[1]
            L = _m.hypot(dx, dy)
            if L < 1e-9:
                return _m.hypot(pt[0]-a[0], pt[1]-a[1])
            return abs(dy*(pt[0]-a[0]) - dx*(pt[1]-a[1])) / L

        def overlap_len(a1, a2, b1, b2):
            """Độ dài overlap dọc trục a1→a2 của hình chiếu b lên a (mét)."""
            dx, dy = a2[0]-a1[0], a2[1]-a1[1]
            L = _m.hypot(dx, dy)
            if L < 1e-9:
                return 0.0
            ux, uy = dx/L, dy/L
            tb1 = (b1[0]-a1[0])*ux + (b1[1]-a1[1])*uy
            tb2 = (b2[0]-a1[0])*ux + (b2[1]-a1[1])*uy
            lo, hi = min(tb1, tb2), max(tb1, tb2)
            return min(L, hi) - max(0.0, lo)

        def centerline(a1, a2, b1, b2):
            """Tim của 2 đoạn song song.
            Tim NẰM GIỮA 2 mặt (về pháp tuyến) và TRẢI HẾT phần chung+riêng của
            2 mặt (UNION theo trục dọc). Tránh cắt cụt khi 1 mặt bị NGẮT bởi vách
            vuông góc tại T-junction: mặt 'xuyên' còn nguyên -> tim phải dài hết
            theo mặt dài, không bị kéo về theo mặt ngắn."""
            dx, dy = a2[0]-a1[0], a2[1]-a1[1]
            L = _m.hypot(dx, dy)
            if L < 1e-9:
                return (((a1[0]+b1[0])/2, (a1[1]+b1[1])/2),
                        ((a2[0]+b2[0])/2, (a2[1]+b2[1])/2))
            ux, uy = dx/L, dy/L
            # Điểm tựa = trung điểm 2 trung điểm mặt -> luôn cách đều 2 mặt (½ bề dày)
            mA = ((a1[0]+a2[0])/2, (a1[1]+a2[1])/2)
            mB = ((b1[0]+b2[0])/2, (b1[1]+b2[1])/2)
            base = ((mA[0]+mB[0])/2, (mA[1]+mB[1])/2)
            # Trải hết theo trục dọc: union hình chiếu của cả 4 đầu mặt
            ts = [(p[0]-base[0])*ux + (p[1]-base[1])*uy for p in (a1, a2, b1, b2)]
            t0, t1 = min(ts), max(ts)
            return ((base[0]+ux*t0, base[1]+uy*t0),
                    (base[0]+ux*t1, base[1]+uy*t1))

        def stitch_collinear(segs, gap_tol=0.35):
            """Nối các đoạn COLLINEAR (mặt wall bị chia bởi vertex lỗ cửa hoặc bị
            ngắt tại junction vách vuông góc) thành 1 đoạn đầy đủ. gap_tol ~0.35m
            bắc cầu qua khe junction (≈ bề thickness vách) nhưng KHÔNG nối qua lỗ cửa
            thật (≥0.7m) hay 2 wall riêng biệt xa nhau."""
            groups = {}
            for p1, p2 in segs:
                L = seg_len(p1, p2)
                if L < 1e-9:
                    continue
                # Bucket angle CUỘN quanh π (0 và π là cùng phương) để tránh mất
                # ổn định ở biên do sai số float → tách nhầm 2 đoạn cùng đường.
                ang = seg_angle(p1, p2)             # [0, pi)
                nb = round(_m.pi / _m.radians(2))   # số bucket trong [0, pi)
                ab = round(ang / _m.radians(2)) % nb
                ba = ab * _m.radians(2)             # angle lượng tử nhất quán
                nx, ny = -_m.sin(ba), _m.cos(ba)    # pháp tuyến chuẩn theo bucket
                off = p1[0]*nx + p1[1]*ny           # khoảng cách có dấu tới gốc
                key = (ab, round(off / 0.03))
                groups.setdefault(key, []).append((p1, p2))
            out = []
            for gsegs in groups.values():
                if len(gsegs) == 1:
                    out.append(gsegs[0])
                    continue
                rp = gsegs[0][0]
                L0 = seg_len(gsegs[0][0], gsegs[0][1])
                ux, uy = ((gsegs[0][1][0]-rp[0])/L0, (gsegs[0][1][1]-rp[1])/L0)
                ivs = []
                for p1, p2 in gsegs:
                    t1 = (p1[0]-rp[0])*ux + (p1[1]-rp[1])*uy
                    t2 = (p2[0]-rp[0])*ux + (p2[1]-rp[1])*uy
                    ivs.append((min(t1, t2), max(t1, t2)))
                ivs.sort()
                cs, ce = ivs[0]
                merged_iv = []
                for s, e in ivs[1:]:
                    if s <= ce + gap_tol:
                        ce = max(ce, e)
                    else:
                        merged_iv.append((cs, ce)); cs, ce = s, e
                merged_iv.append((cs, ce))
                for s, e in merged_iv:
                    out.append(((rp[0]+ux*s, rp[1]+uy*s),
                                (rp[0]+ux*e, rp[1]+uy*e)))
            return out

        # Tách authoritative rect (giữ nguyên) khỏi poly (merge + lọc)
        auth = []     # (p1, p2, thick_m) — rect centerline, pass-through
        poly = []     # (p1, p2) — edges poly, ứng viên merge
        for e in walls:
            k = wall_key(e[0], e[1])
            if k in rect_keys:
                auth.append((e[0], e[1], rect_keys[k]))
            else:
                poly.append((e[0], e[1]))

        # Nối các mặt wall bị chia nhỏ bởi vertex lỗ cửa
        poly = stitch_collinear(poly)

        n = len(poly)
        used = [False] * n
        # merged_segs: (p1, p2, thickness_m) — thickness = khoảng cách 2 mặt vách
        merged_segs = []
        # orphans: (p1, p2)
        orphans = []

        for i in range(n):
            if used[i]:
                continue
            a1, a2 = poly[i][0], poly[i][1]
            La = seg_len(a1, a2)
            if La < 0.001:
                used[i] = True
                continue
            ang_a = seg_angle(a1, a2)
            # Chọn partner song song GẦN NHẤT (2 mặt cùng 1 wall là cặp gần nhất),
            # không lấy partner đầu tiên gặp → tránh ghép nhầm mặt wall khác.
            best_j, best_d = -1, max_gap
            for j in range(i+1, n):
                if used[j]:
                    continue
                b1, b2 = poly[j][0], poly[j][1]
                Lb = seg_len(b1, b2)
                if Lb < 0.001:
                    continue
                ang_b = seg_angle(b1, b2)
                diff = abs(ang_a - ang_b) % _m.pi
                if diff > _m.radians(3) and (_m.pi - diff) > _m.radians(3):
                    continue
                d = pt_line_dist(b1, a1, a2)
                if d > max_gap:
                    continue
                # Near-duplicate: CHỈ bỏ j nếu collinear VÀ chồng lấn thực sự.
                # Collinear nhưng rời nhau = 2 đoạn wall khác nhau → GIỮ j.
                if d < 0.001:
                    if overlap_len(a1, a2, b1, b2) > 0.05:
                        used[j] = True
                    continue
                ov = overlap_len(a1, a2, b1, b2)
                minlen = min(La, Lb)
                # 2 mặt cùng 1 wall: overlap >= 30% và overlap >= bề thickness d
                if ov <= 0.3 * minlen or ov < d:
                    continue
                if d < best_d:
                    best_d, best_j = d, j
            if best_j >= 0:
                b1, b2 = poly[best_j][0], poly[best_j][1]
                r1, r2 = centerline(a1, a2, b1, b2)
                merged_segs.append((r1, r2, best_d))   # độ thickness thực từ DXF
                used[i] = used[best_j] = True
            elif not used[i]:
                orphans.append((a1, a2))

        # Lọc stub: chỉ bỏ nếu cả 2 đầu đều gần endpoint của CÙNG 1 merged wall
        # (end-cap thật: nối 2 đầu của 1 wall)
        # Vách tại T-junction có 2 đầu gần 2 merged wall KHÁC NHAU → giữ lại
        eps = max_gap * 0.6

        def near_same_merged_wall(pa, pb):
            """True nếu pa và pb đều gần 2 endpoint của CÙNG 1 merged segment
            VÀ độ dài stub ≈ bề thickness (đặc trưng end-cap, không phải wall thật)."""
            Ls = _m.hypot(pb[0]-pa[0], pb[1]-pa[1])
            for r1, r2, d in merged_segs:
                if Ls > d * 1.5 + 0.05:
                    continue   # stub dài hơn bề thickness nhiều → wall thật, không lọc
                near_r1_pa = _m.hypot(pa[0]-r1[0], pa[1]-r1[1]) < eps
                near_r2_pa = _m.hypot(pa[0]-r2[0], pa[1]-r2[1]) < eps
                near_r1_pb = _m.hypot(pb[0]-r1[0], pb[1]-r1[1]) < eps
                near_r2_pb = _m.hypot(pb[0]-r2[0], pb[1]-r2[1]) < eps
                if (near_r1_pa and near_r2_pb) or (near_r2_pa and near_r1_pb):
                    return True
            return False

        def is_junction_endcap(pa, pb):
            """Phát hiện end-cap stub tại T/cross junction (không phải wall nối hợp lệ).
            Điều kiện: độ dài ≈ bề thickness + vuông angle với wall đã merge + cả 2 đầu
            trong dải bề thickness + midpoint NẰM TRÊN (rất gần) tim wall đó.
            Wall nối hợp lệ tại angle L: midpoint LỆCH SANG BÊN (xa tim) → không lọc.
            Wall step dài (L >> bề dày): bị loại bởi điều kiện độ dài → không lọc."""
            ang = seg_angle(pa, pb)
            Ls  = _m.hypot(pb[0]-pa[0], pb[1]-pa[1])
            mid = ((pa[0]+pb[0])/2, (pa[1]+pb[1])/2)
            for r1, r2, d in merged_segs:
                if Ls > d * 1.5 + 0.05:
                    continue   # stub dài hơn bề thickness nhiều → wall thật, không lọc
                ang_r = seg_angle(r1, r2)
                diff = abs(ang - ang_r) % _m.pi
                if abs(diff - _m.pi/2) > _m.radians(20):
                    continue   # Không vuông góc
                half = d / 2 + 0.02   # nửa bề thickness + 2 cm
                if (pt_line_dist(pa, r1, r2) >= half
                        or pt_line_dist(pb, r1, r2) >= half):
                    continue   # Ít nhất 1 đầu ra ngoài dải → wall nối hợp lệ
                # Midpoint phải GẦN tim wall (end-cap thật: midpoint ≈ 0 từ tim)
                # Wall nối hợp lệ: midpoint lệch ≥ d/4 so với tim
                d_mid = pt_line_dist(mid, r1, r2)
                if d_mid >= d * 0.15 + 0.01:
                    continue   # Midpoint xa tim → giữ lại (wall nối thật)
                # Midpoint phải chiếu TRONG đoạn wall (không nằm ngoài 2 đầu)
                Lr = seg_len(r1, r2)
                if Lr < 1e-9:
                    continue
                ux, uy = (r2[0]-r1[0])/Lr, (r2[1]-r1[1])/Lr
                t = (mid[0]-r1[0])*ux + (mid[1]-r1[1])*uy
                if -(d + 0.05) <= t <= Lr + (d + 0.05):
                    return True
            return False

        # Centerline tham chiếu (merged + authoritative rect) để lọc fragment dư
        ref_lines = [(r1, r2, d) for r1, r2, d in merged_segs] \
                  + [(p1, p2, t if t else 0.20) for p1, p2, t in auth]

        def inside_existing_wall(pa, pb):
            """True nếu fragment SONG SONG và nằm TRONG dải bề thickness của 1 wall đã có
            (mảnh vụn dư thừa từ outline có lỗ cửa) → lọc bỏ."""
            ang = seg_angle(pa, pb)
            for r1, r2, d in ref_lines:
                ang_r = seg_angle(r1, r2)
                diff = abs(ang - ang_r) % _m.pi
                if diff > _m.radians(5) and (_m.pi - diff) > _m.radians(5):
                    continue   # không song song
                half = d / 2 + 0.03
                if pt_line_dist(pa, r1, r2) >= half or pt_line_dist(pb, r1, r2) >= half:
                    continue   # ra ngoài dải bề dày
                # Hình chiếu phải nằm trong đoạn wall (chồng lấn)
                Lr = seg_len(r1, r2)
                if Lr < 1e-9:
                    continue
                ux, uy = (r2[0]-r1[0])/Lr, (r2[1]-r1[1])/Lr
                ta = (pa[0]-r1[0])*ux + (pa[1]-r1[1])*uy
                tb = (pb[0]-r1[0])*ux + (pb[1]-r1[1])*uy
                if min(ta, tb) > Lr + 0.05 or max(ta, tb) < -0.05:
                    continue   # nằm ngoài 2 đầu wall
                return True
            return False

        def ep_on_network(pt):
            """True nếu điểm pt nằm SÁT (trong nửa bề dày) 1 tim wall đã có,
            và hình chiếu rơi trong thân wall (±bề thickness ở 2 đầu)."""
            for r1, r2, d in ref_lines:
                Lr = seg_len(r1, r2)
                if Lr < 1e-9:
                    continue
                ux, uy = (r2[0]-r1[0])/Lr, (r2[1]-r1[1])/Lr
                t = (pt[0]-r1[0])*ux + (pt[1]-r1[1])*uy
                if t < -(d + 0.05) or t > Lr + (d + 0.05):
                    continue
                perp = abs((pt[1]-r1[1])*ux - (pt[0]-r1[0])*uy)
                if perp <= d / 2 + 0.06:
                    return True
            return False

        def both_ends_on_network(pa, pb):
            """Jog/notch nội bộ trong outline phức tạp: đoạn ngắn có CẢ 2 đầu
            nằm trên mạng wall (trong dải bề dày)."""
            return ep_on_network(pa) and ep_on_network(pb)

        # Endpoint của các merged wall (để bắt cap/tab tại đầu pier)
        merged_eps = [r1 for r1, r2, _ in merged_segs] \
                   + [r2 for r1, r2, _ in merged_segs]

        def ep_near_network(pt, near=0.7):
            """pt nằm trên thân wall (dải bề dày) HOẶC gần 1 endpoint merged ≤ near."""
            if ep_on_network(pt):
                return True
            for ep in merged_eps:
                if _m.hypot(pt[0]-ep[0], pt[1]-ep[1]) < near:
                    return True
            return False

        def is_cap_or_jog(pa, pb):
            """Đoạn poly ngắn (<1m) còn sót trong outline phức tạp: cap/tab/jog
            tại đầu hoặc thân pier. Đặc trưng: ≥1 đầu sát mạng wall đã dựng.
            Wall thật luôn được pair (merged); orphan ngắn sát mạng = artifact."""
            if seg_len(pa, pb) >= 1.0:
                return False
            return ep_near_network(pa) or ep_near_network(pb)

        # result: authoritative rects + merged poly centerlines + poly orphans hợp lệ
        result = list(auth) + list(merged_segs)
        for a1, a2 in orphans:
            is_stub = ((seg_len(a1, a2) < max_gap
                        and (near_same_merged_wall(a1, a2)
                             or is_junction_endcap(a1, a2)
                             or inside_existing_wall(a1, a2)
                             or both_ends_on_network(a1, a2)))
                       or is_cap_or_jog(a1, a2))
            if not is_stub:
                result.append((a1, a2, None))   # None → dùng wall_thick fallback

        return result

    if data["walls"]:
        before = len(data["walls"])
        data["walls"] = _merge_parallel_walls(data["walls"], rect_info)
        after = len(data["walls"])
        if before != after:
            log_fn(f"  Merged parallel walls: {before} → {after} centerline segments", "info")

    # ── Snap endpoint vách ngang → tim vách dọc (V-primary) ────
    def _snap_h_to_v(walls, snap_dist=1.0):
        """
        V-primary: endpoint của vách ngang (angle gần 0°/180°) snap vào
        tim của vách dọc (angle gần 90°) gần nhất.
        Tạo liên kết sạch: vách dọc xuyên qua, vách ngang dừng tại tim vách dọc.
        """
        import math as _m

        def seg_angle(p1, p2):
            return abs(_m.atan2(p2[1]-p1[1], p2[0]-p1[0])) % _m.pi

        def is_vertical(p1, p2):
            a = seg_angle(p1, p2)
            return a > _m.radians(45) and a < _m.radians(135)

        def snap_pt_onto_seg(pt, s1, s2, max_perp):
            """Project pt onto line s1-s2; return snapped point if perp < max_perp."""
            dx, dy = s2[0]-s1[0], s2[1]-s1[1]
            L = _m.hypot(dx, dy)
            if L < 1e-9:
                return None
            ux, uy = dx/L, dy/L
            t = (pt[0]-s1[0])*ux + (pt[1]-s1[1])*uy
            # Projection must be within segment (±snap_dist tolerance at ends)
            if t < -snap_dist or t > L + snap_dist:
                return None
            perp = abs((pt[1]-s1[1])*ux - (pt[0]-s1[0])*uy)
            if perp > max_perp:
                return None
            return (s1[0] + t*ux, s1[1] + t*uy)

        # Tách vách dọc và ngang
        vert_walls = [(e[0], e[1], (e[2] if len(e) > 2 else None))
                      for e in walls if is_vertical(e[0], e[1])]

        result = []
        for entry in walls:
            p1, p2 = entry[0], entry[1]
            thick  = entry[2] if len(entry) > 2 else None

            if is_vertical(p1, p2):
                # Vách dọc giữ nguyên (primary)
                result.append(entry)
                continue

            # Vách ngang: thử snap p1 và p2 vào tim vách dọc gần nhất
            new_p1, new_p2 = p1, p2
            best1, best2 = snap_dist, snap_dist

            L_orig = _m.hypot(p2[0]-p1[0], p2[1]-p1[1])
            for v1, v2, vth in vert_walls:
                # CHỈ snap khe NHỎ = mối nối thật (~nửa bề dày vách dọc), KHÔNG
                # kéo đầu vách qua LỖ CỬA lớn -> tránh "kéo thừa ra ngoài".
                cap = max(0.25, (vth / 2 + 0.10) if vth else 0.0)
                snp = snap_pt_onto_seg(p1, v1, v2, cap)
                if snp:
                    # CHỈ snap khi KHÔNG làm NGẮN vách: vách dọc cắt ngang ở GIỮA
                    # (vách ngang xuyên qua) -> đầu này là MÚT thật, không kéo lùi.
                    # Cho phép khi snap GIỮ NGUYÊN/NỚI DÀI (đầu lỏng -> chạm tim dọc).
                    if _m.hypot(snp[0]-p2[0], snp[1]-p2[1]) >= L_orig - 0.02:
                        d = _m.hypot(p1[0]-snp[0], p1[1]-snp[1])
                        if d < best1:
                            best1, new_p1 = d, snp

                snp = snap_pt_onto_seg(p2, v1, v2, cap)
                if snp:
                    if _m.hypot(snp[0]-p1[0], snp[1]-p1[1]) >= L_orig - 0.02:
                        d = _m.hypot(p2[0]-snp[0], p2[1]-snp[1])
                        if d < best2:
                            best2, new_p2 = d, snp

            # Nếu sau snap 2 đầu trùng nhau → bỏ snap (giữ nguyên original)
            snapped_len = _m.hypot(new_p2[0]-new_p1[0], new_p2[1]-new_p1[1])
            if snapped_len < 0.05:
                new_p1, new_p2 = p1, p2   # revert to original

            result.append((new_p1, new_p2, thick))

        return result

    if data["walls"]:
        data["walls"] = _snap_h_to_v(data["walls"])

    # ── Bỏ wall collinear trùng/chồng (over+under cùng 1 đường) ──
    def _dedup_collinear(walls):
        import math as _m

        def sl(a, b):
            return _m.hypot(b[0]-a[0], b[1]-a[1])

        def ang(a, b):
            return _m.atan2(b[1]-a[1], b[0]-a[0]) % _m.pi

        def pld(pt, a, b):
            dx, dy = b[0]-a[0], b[1]-a[1]
            L = _m.hypot(dx, dy)
            if L < 1e-9:
                return _m.hypot(pt[0]-a[0], pt[1]-a[1])
            return abs(dy*(pt[0]-a[0]) - dx*(pt[1]-a[1])) / L

        def ov(a1, a2, b1, b2):
            dx, dy = a2[0]-a1[0], a2[1]-a1[1]
            L = _m.hypot(dx, dy)
            if L < 1e-9:
                return 0.0
            ux, uy = dx/L, dy/L
            t1 = (b1[0]-a1[0])*ux + (b1[1]-a1[1])*uy
            t2 = (b2[0]-a1[0])*ux + (b2[1]-a1[1])*uy
            return min(L, max(t1, t2)) - max(0.0, min(t1, t2))

        n = len(walls)
        drop = [False] * n
        for i in range(n):
            if drop[i]:
                continue
            a1, a2 = walls[i][0], walls[i][1]
            La = sl(a1, a2)
            for j in range(n):
                if i == j or drop[j]:
                    continue
                b1, b2 = walls[j][0], walls[j][1]
                Lb = sl(b1, b2)
                diff = abs(ang(a1, a2) - ang(b1, b2)) % _m.pi
                if diff > _m.radians(3) and (_m.pi - diff) > _m.radians(3):
                    continue
                if pld(b1, a1, a2) > 0.08:
                    continue   # không collinear (lệch > 80mm)
                # j ngắn hơn & nằm gần trọn trong i → bỏ j
                if Lb <= La + 1e-6 and ov(a1, a2, b1, b2) >= 0.9 * Lb:
                    drop[j] = True
        return [w for k, w in enumerate(walls) if not drop[k]]

    # ── Khép mối nối chữ T: đầu vách chạm MẶT vách vuông angle →
    #    kéo dài tới TIM vách đó (đóng khe ~½ bề dày) ──────────────
    def _close_t_junctions(walls, max_ext=0.16):
        import math as _m

        def sl(a, b):
            return _m.hypot(b[0]-a[0], b[1]-a[1])

        def ang(a, b):
            return _m.atan2(b[1]-a[1], b[0]-a[0]) % _m.pi

        def inter(p, d, q, e):
            den = d[0]*e[1] - d[1]*e[0]
            if abs(den) < 1e-9:
                return None
            t = ((q[0]-p[0])*e[1] - (q[1]-p[1])*e[0]) / den
            return (p[0] + d[0]*t, p[1] + d[1]*t)

        W = [[list(w[0]), list(w[1]), (w[2] if len(w) > 2 else None)]
             for w in walls]
        n = len(W)
        for i in range(n):
            p1, p2 = W[i][0], W[i][1]
            Lw = sl(p1, p2)
            if Lw < 1e-9:
                continue
            di = ((p2[0]-p1[0])/Lw, (p2[1]-p1[1])/Lw)
            for idx in (0, 1):
                ep = W[i][idx]
                best, bestd = None, max_ext
                for j in range(n):
                    if i == j:
                        continue
                    q1, q2 = W[j][0], W[j][1]
                    Lj = sl(q1, q2)
                    if Lj < 1e-9:
                        continue
                    diff = abs(ang(p1, p2) - ang(q1, q2)) % _m.pi
                    if abs(diff - _m.pi/2) > _m.radians(20):
                        continue   # không vuông góc
                    ej = ((q2[0]-q1[0])/Lj, (q2[1]-q1[1])/Lj)
                    I = inter(ep, di, q1, ej)
                    if I is None:
                        continue
                    dist = _m.hypot(I[0]-ep[0], I[1]-ep[1])
                    if dist >= bestd:
                        continue
                    tj = (I[0]-q1[0])*ej[0] + (I[1]-q1[1])*ej[1]
                    if tj < -0.05 or tj > Lj + 0.05:
                        continue   # giao điểm ngoài thân vách j
                    bestd, best = dist, I
                if best is not None and bestd > 1e-4:
                    W[i][idx][0], W[i][idx][1] = best[0], best[1]
        return [(tuple(w[0]), tuple(w[1]), w[2]) for w in W]

    if data["walls"]:
        b0 = len(data["walls"])
        data["walls"] = _dedup_collinear(data["walls"])
        if len(data["walls"]) != b0:
            log_fn(f"  Removed duplicate collinear walls: {b0} → {len(data['walls'])}", "info")
        data["walls"] = _close_t_junctions(data["walls"])

    # ── Snap node chung giữa các miếng sàn/lỗ mở cong (cạnh tiếp giáp) ──
    if data["slabs"] or data["openings"]:
        polys, refs = [], []
        for s in data["slabs"]:
            polys.append([list(p) for p in s["pts"]]); refs.append(("slab", s))
        for idx, op in enumerate(data["openings"]):
            polys.append([list(p) for p in op]); refs.append(("open", idx))
        _snap_shared_nodes(polys, tol=0.05)
        for pl, (kind, ref) in zip(polys, refs):
            snapped = [tuple(p) for p in pl]
            if kind == "slab":
                ref["pts"] = snapped
            else:
                data["openings"][ref] = snapped
        log_fn("  Synced shared edge nodes of slab/opening (snap ≤50mm)", "info")

    # Vách cong: gộp vào danh sách wall SAU hậu xử lý (giữ nguyên tim cong)
    if data["walls_curved"]:
        data["walls"].extend(data["walls_curved"])
        log_fn(f"  Curved walls: added {len(data['walls_curved'])} centerline "
               f"segments (no merge/snap)", "info")

    # ── Tự dò bề dày + cao độ sàn theo STEP / SOFFIT STEP ──────
    if config.get("detect_slab_depth") and data["slabs"]:
        before = len(data["slabs"])
        log_fn("\n  → Detect slab depth & TOC by STEP / SOFFIT STEP...", "info")
        data["slabs"] = subdivide_slabs_by_depth(
            data["slabs"], msp, unit_scale,
            config.get("slab_depth_layers", {}), log_fn, slab_seg)
        log_fn(f"  Slab regions: {before} → {len(data['slabs'])} "
               f"(per-region thickness/TOC)", "info")

    # ── RAM Concept ────────────────────────────────────────────
    log_fn("\nSTEP 2 — CONNECT RAM CONCEPT API", "title")
    if ram_api_path and ram_api_path not in sys.path:
        sys.path.append(ram_api_path)
    try:
        import ram_concept
        from ram_concept.concept    import Concept
        from ram_concept.model      import DesignCode, StructureType
        from ram_concept.point_2D   import Point2D
        from ram_concept.polygon_2D import Polygon2D
    except ImportError as e:
        log_fn(f"[ERROR] RAM Concept API: {e}", "error")
        return False
    log_fn("  ✓ API ready", "success")

    log_fn("\nSTEP 3 — CREATE MODEL", "title")
    try:
        concept = Concept.start_concept(headless=True)
        if cpt_template and os.path.isfile(cpt_template):
            log_fn(f"  Open template: {cpt_template}", "info")
            model = concept.open_file(cpt_template)
        else:
            log_fn("  Create new model", "info")
            model = concept.new_model()
            model.design_code    = DesignCode.ACI318_14_METRIC
            model.structure_type = StructureType.TWO_WAY_SLAB

        # ── Lấy cad_manager (đã xác nhận từ debug log) ────────
        cad = model.cad_manager
        log_fn("  ✓ Connected cad_manager successfully", "success")

        # ── Xác định structure_layer để tạo phần tử ───────────
        # Từ debug log: cad_manager có 'structure_layer', 'element_layer'
        # structure_layer = nơi chứa slab, column, wall, opening
        mesh_layer = None

        # Thử 1: cad_manager.structure_layer (xác nhận từ debug log)
        if hasattr(cad, "structure_layer"):
            try:
                mesh_layer = cad.structure_layer
                layer_attrs = [a for a in dir(mesh_layer) if not a.startswith("_")]
                log_fn(f"  ✓ Using: cad_manager.structure_layer", "success")
                log_fn(f"  [DEBUG] structure_layer methods: {layer_attrs}", "info")
            except Exception as e:
                log_fn(f"  structure_layer error: {e}", "warning")
                mesh_layer = None

        # Thử 2: cad_manager.element_layer
        if mesh_layer is None and hasattr(cad, "element_layer"):
            try:
                mesh_layer = cad.element_layer
                layer_attrs = [a for a in dir(mesh_layer) if not a.startswith("_")]
                log_fn(f"  ✓ Using: cad_manager.element_layer", "success")
                log_fn(f"  [DEBUG] element_layer methods: {layer_attrs}", "info")
            except Exception as e:
                log_fn(f"  element_layer error: {e}", "warning")
                mesh_layer = None

        # Thử 3: cad_manager.default_slab_area → dùng cad trực tiếp
        # (một số version gọi method trực tiếp trên cad_manager)
        if mesh_layer is None:
            cad_attrs = [a for a in dir(cad) if not a.startswith("_")]
            if any("slab" in a.lower() for a in cad_attrs):
                log_fn("  ✓ Using cad_manager directly (has slab methods)", "success")
                mesh_layer = cad
            else:
                log_fn(f"  [DEBUG] cad_manager attrs: {cad_attrs}", "info")

        if mesh_layer is None:
            log_fn("[ERROR] Could not find a layer to create elements!", "error")
            concept.shut_down()
            return False

        # ── Tìm tên method chính xác trên layer tìm được ──────
        def find_method(obj, keywords):
            attrs = [a for a in dir(obj) if not a.startswith("_")]
            # Khớp chính xác trước
            for kw in keywords:
                if kw in attrs:
                    return kw
            # Khớp một phần
            for kw in keywords:
                matches = [a for a in attrs if kw.lower() in a.lower()]
                if matches:
                    return matches[0]
            return None

        slab_method    = find_method(mesh_layer, [
            "new_slab_area", "add_slab_area", "create_slab_area",
            "slab_area", "add_slab", "new_slab"])
        col_method     = find_method(mesh_layer, [
            "new_column", "add_column", "create_column", "column"])
        wall_method    = find_method(mesh_layer, [
            "new_wall", "add_wall", "create_wall", "wall"])
        opening_method = find_method(mesh_layer, [
            "new_slab_opening", "add_slab_opening", "new_opening",
            "add_opening", "opening"])

        log_fn(f"  Slab method   → {slab_method or '❌ not found'}", "info")
        log_fn(f"  Column method → {col_method  or '❌ not found'}", "info")
        log_fn(f"  Wall method   → {wall_method  or '❌ not found'}", "info")
        log_fn(f"  Opening method→ {opening_method or '❌ not found'}", "info")

        # ── Tạo SLAB ──────────────────────────────────────────
        if data["slabs"]:
            log_fn(f"\n  → Create {len(data['slabs'])} slabs...", "info")
            if not slab_method:
                log_fn("  ⚠ Skipped — slab creation method not found", "warning")
            else:
                for i, slab_item in enumerate(data["slabs"]):
                    if isinstance(slab_item, dict):
                        pts  = slab_item["pts"]
                        t    = slab_item.get("thickness", slab_thick)
                        toc  = slab_item.get("toc", 0.0)
                        prio = slab_item.get("priority", 1)
                    else:
                        pts = slab_item; t = slab_thick; toc = 0.0; prio = 1
                    pts = _clean_polygon(pts)
                    if pts is None:
                        log_fn(f"  ⚠ Slab #{i+1} skipped — degenerate geometry", "warning")
                        continue
                    poly = Polygon2D([Point2D(x, y) for x, y in pts])
                    s = getattr(mesh_layer, slab_method)(poly)
                    try:
                        s.thickness = float(t)    # mm
                        s.toc       = float(toc)  # mm
                        s.priority  = prio
                    except Exception as e:
                        log_fn(f"  ⚠ Slab #{i+1} set property error: {e}", "warning")
                    log_fn(f"  ✓ Slab #{i+1} — {len(pts)} vertices, "
                           f"thickness {t:.0f}mm, TOC={toc}mm, priority={prio}", "success")

        # ── Tạo COLUMN ────────────────────────────────────────
        if data["columns"]:
            log_fn(f"\n  → Create {len(data['columns'])} columns...", "info")
            if not col_method:
                log_fn("  ⚠ Skipped — column creation method not found", "warning")
            else:
                for i, col_data in enumerate(data["columns"]):
                    if isinstance(col_data, dict):
                        cx    = col_data["cx"]
                        cy    = col_data["cy"]
                        w     = col_data["w"]
                        d     = col_data["d"]
                        angle = col_data["angle"]
                    else:
                        pts = col_data
                        xs=[p[0] for p in pts]; ys=[p[1] for p in pts]
                        cx=sum(xs)/len(xs);     cy=sum(ys)/len(ys)
                        w=max(xs)-min(xs);      d=max(ys)-min(ys)
                        angle=0.0

                    is_circ = isinstance(col_data, dict) and col_data.get("circular", False)

                    col = getattr(mesh_layer, col_method)(Point2D(cx, cy))
                    try:
                        if is_circ:
                            col.b = 0.0                       # b=0 → cột tròn
                            col.d = _round_to(d * 1000, 10)   # đường kính (mm), tròn 10
                        else:
                            col.b = _round_to(w * 1000, 10)   # mm, edges local-x, tròn 10
                            col.d = _round_to(d * 1000, 10)   # mm, edges vuông góc, tròn 10
                        col.height = col_height
                        col.angle  = round(float(angle), 3)   # độ (RAM dùng degrees)
                    except Exception as e:
                        log_fn(f"  ⚠ Column #{i+1} set property error: {e}", "warning")

                    if is_circ:
                        log_fn(f"  ✓ Column #{i+1} — round ⌀{d*1000:.0f}mm "
                               f"@ ({cx:.3f},{cy:.3f})", "success")
                    else:
                        log_fn(f"  ✓ Column #{i+1} — b={w*1000:.0f}×d={d*1000:.0f}mm "
                               f"angle {angle:.1f}° @ ({cx:.3f},{cy:.3f})", "success")


        # ── Tạo WALL ──────────────────────────────────────────
        if data["walls"]:
            log_fn(f"\n  → Create {len(data['walls'])} walls...", "info")
            if not wall_method:
                log_fn("  ⚠ Skipped — wall creation method not found", "warning")
            else:
                for i, wall_entry in enumerate(data["walls"]):
                    p1, p2 = wall_entry[0], wall_entry[1]
                    # thickness từ DXF (đã đo được khi merge); None → dùng fallback
                    detected_thick_m = wall_entry[2] if len(wall_entry) > 2 else None
                    L = ((p2[0]-p1[0])**2 + (p2[1]-p1[1])**2)**0.5
                    # Skip degenerate segments (zero/near-zero length after snapping)
                    if L < 0.05:
                        log_fn(f"  ⚠ Wall #{i+1} skipped — too short ({L*1000:.1f}mm)", "warning")
                        continue
                    wall = None

                    # add_wall chỉ nhận 1 argument → thử các dạng khác nhau
                    # Dạng 1: add_wall(line_segment)  — truyền LineSegment2D
                    try:
                        from ram_concept.line_segment_2D import LineSegment2D
                        seg = LineSegment2D(Point2D(*p1), Point2D(*p2))
                        wall = getattr(mesh_layer, wall_method)(seg)
                        log_fn(f"  ✓ Wall #{i+1} — LineSegment2D, length {L:.2f}m", "success")
                    except Exception:
                        wall = None

                    # Dạng 2: add_wall(polyline)  — truyền Polygon2D / list điểm
                    if wall is None:
                        try:
                            poly = Polygon2D([Point2D(*p1), Point2D(*p2)])
                            wall = getattr(mesh_layer, wall_method)(poly)
                            log_fn(f"  ✓ Wall #{i+1} — Polygon2D, length {L:.2f}m", "success")
                        except Exception:
                            wall = None

                    # Dạng 3: add_wall(p1, p2) — 2 Point2D (cách cũ, nhưng thử lại)
                    if wall is None:
                        try:
                            wall = getattr(mesh_layer, wall_method)(
                                Point2D(*p1), Point2D(*p2))
                            log_fn(f"  ✓ Wall #{i+1} — 2 Point2D, length {L:.2f}m", "success")
                        except Exception:
                            wall = None

                    # Dạng 4: add_wall(x1,y1,x2,y2) — 4 số
                    if wall is None:
                        try:
                            wall = getattr(mesh_layer, wall_method)(
                                p1[0], p1[1], p2[0], p2[1])
                            log_fn(f"  ✓ Wall #{i+1} — 4 floats, length {L:.2f}m", "success")
                        except Exception:
                            wall = None

                    if wall is None:
                        log_fn(f"  ⚠ Wall #{i+1} — could not create, skipped", "warning")
                        continue

                    try:
                        # Ưu tiên độ thickness đo từ DXF, fallback về wall_thick config
                        # Làm tròn bề thickness vách tới bội số 5mm
                        raw_t = (detected_thick_m * 1000 if detected_thick_m is not None
                                 else wall_thick * 1000)
                        t_mm = _round_to(raw_t, 5)
                        wall.thickness = t_mm
                        wall.height    = col_height
                        log_fn(f"    thickness={t_mm:.0f}mm  height={col_height:.2f}m", "info")
                    except Exception as e:
                        log_fn(f"  ⚠ Wall #{i+1} set property error: {e}", "warning")

        # ── Tạo OPENING ───────────────────────────────────────
        if data["openings"]:
            log_fn(f"\n  → Create {len(data['openings'])} openings...", "info")
            if not opening_method:
                log_fn("  ⚠ Skipped — opening creation method not found", "warning")
            else:
                for i, pts in enumerate(data["openings"]):
                    cpts = _clean_polygon(pts)
                    if cpts is None:
                        log_fn(f"  ⚠ Opening #{i+1} skipped — degenerate geometry", "warning")
                        continue
                    poly = Polygon2D([Point2D(x, y) for x, y in cpts])
                    getattr(mesh_layer, opening_method)(poly)
                    log_fn(f"  ✓ Opening #{i+1} — {len(cpts)} vertices", "success")

        # ── Mesh ──────────────────────────────────────────────
        log_fn(f"\n  Creating FEM mesh (max element = {mesh_size}m)...", "info")
        mesh_fn = find_method(model, ["mesh_model", "generate_mesh", "mesh", "calc_all"])
        if not mesh_fn:
            log_fn("  ⚠ Mesh method not found — skipped", "warning")
        else:
            mesh_ok = False
            mesh_err = None
            # Thử các dạng chữ ký. TypeError = sai chữ ký → thử dạng kế.
            # Lỗi runtime khác (vd hình học suy biến) → KHÔNG fatal: dừng mesh
            # nhưng vẫn lưu file để mesh thủ công trong RAM Concept.
            for desc, caller in (
                ("max_element_size=", lambda: getattr(model, mesh_fn)(max_element_size=mesh_size)),
                ("positional",        lambda: getattr(model, mesh_fn)(mesh_size)),
                ("no args",           lambda: getattr(model, mesh_fn)()),
            ):
                try:
                    caller()
                    log_fn(f"  ✓ Mesh completed ({desc})", "success")
                    mesh_ok = True
                    break
                except TypeError:
                    continue          # sai chữ ký → thử dạng kế
                except Exception as e:
                    mesh_err = e       # chữ ký đúng nhưng mesh lỗi → dừng
                    break

            if not mesh_ok and mesh_err is not None:
                log_fn(f"  ⚠ Mesh failed: {mesh_err}", "warning")
                log_fn("  → Geometry was still created. The file will be saved; "
                       "open it in RAM Concept and run mesh manually "
                       "(usually openings/slabs near edges create degenerate elements).", "warning")
            elif not mesh_ok:
                log_fn(f"  ⚠ All call forms of {mesh_fn}() failed", "warning")

        # ── Lưu file ──────────────────────────────────────────
        log_fn(f"\n  Saving file: {cpt_output}", "info")

        # Debug: xem concept có method gì để lưu
        concept_attrs = [a for a in dir(concept) if not a.startswith("_")]
        save_candidates = [a for a in concept_attrs
                           if any(k in a.lower() for k in ["save", "write", "export"])]
        close_candidates = [a for a in concept_attrs
                            if any(k in a.lower() for k in ["shut", "close", "exit", "quit", "stop"])]
        log_fn(f"  [DEBUG] Save methods  : {save_candidates}", "info")
        log_fn(f"  [DEBUG] Close methods : {close_candidates}", "info")

        # Thử lưu — nhiều dạng
        saved = False

        # Dạng 1: concept.save_file(path)
        if not saved:
            try:
                concept.save_file(cpt_output)
                saved = True
                log_fn("  ✓ Saved: concept.save_file()", "success")
            except Exception: pass

        # Dạng 2: model.save_file(path)
        if not saved:
            try:
                model.save_file(cpt_output)
                saved = True
                log_fn("  ✓ Saved: model.save_file()", "success")
            except Exception: pass

        # Dạng 3: concept.save(path)
        if not saved:
            try:
                concept.save(cpt_output)
                saved = True
                log_fn("  ✓ Saved: concept.save()", "success")
            except Exception: pass

        # Dạng 4: model.save(path)
        if not saved:
            try:
                model.save(cpt_output)
                saved = True
                log_fn("  ✓ Saved: model.save()", "success")
            except Exception: pass

        # Dạng 5: dùng method đầu tiên tìm được
        if not saved and save_candidates:
            try:
                getattr(concept, save_candidates[0])(cpt_output)
                saved = True
                log_fn(f"  ✓ Saved: concept.{save_candidates[0]}()", "success")
            except Exception: pass

        if not saved:
            log_fn("  ⚠ Could not save file — check the API", "warning")

        # ── Đóng RAM Concept ──────────────────────────────────
        closed = False
        for fn in ["shut_down", "shutdown", "close", "exit", "quit", "stop"]:
            if hasattr(concept, fn):
                try:
                    getattr(concept, fn)()
                    closed = True
                    break
                except Exception:
                    pass
        if not closed:
            log_fn("  ⚠ Concept close method not found", "warning")

        if saved:
            log_fn(f"\n✓ SAVED: {cpt_output}", "success")
            return True
        else:
            log_fn("\n✗ Failed to save file!", "error")
            return False

    except AttributeError as e:
        log_fn(f"[ERROR] AttributeError: {e}", "error")
        for fn in ["shut_down","shutdown","close","exit","quit"]:
            if hasattr(concept, fn):
                try: getattr(concept, fn)(); break
                except: pass
        return False
    except Exception as e:
        log_fn(f"[ERROR] {e}", "error")
        for fn in ["shut_down","shutdown","close","exit","quit"]:
            if hasattr(concept, fn):
                try: getattr(concept, fn)(); break
                except: pass
        return False



# ─────────────────────────────────────────────────────────────
# POPUP CHỌN LAYER
# ─────────────────────────────────────────────────────────────

class LayerPickerDialog(tk.Toplevel):
    OTHER_TYPES = [
        ("🟨 Column", "columns",  TAG_COL),
        ("🟦 Wall",   "walls",    TAG_WALL),
        ("🟥 Opening","openings", TAG_OPEN),
    ]

    def __init__(self, parent, layers: list, current: dict):
        super().__init__(parent)
        self.title("Assign DXF Layers to Structural Elements")
        self.geometry("740x640")
        self.resizable(True, True)
        self.configure(bg=BG_DARK)
        self.grab_set()
        self.result   = None
        self._all_layers = ["(Not used)"] + layers
        self._vars    = {}
        self._current = current
        self._slab_rows = []   # list of (layer_var, thick_var, prio_var)
        self._build(layers)

    # ── Build ─────────────────────────────────────────────────
    def _build(self, layers):
        hdr = tk.Frame(self, bg=BG_DARK)
        hdr.pack(fill="x", padx=20, pady=(16, 6))
        tk.Label(hdr, text="🗂  Assign DXF Layers",
                 bg=BG_DARK, fg=TEXT_PRI, font=FONT_BOLD).pack(side="left")
        tk.Label(hdr, text=f"({len(layers)} layers found)",
                 bg=BG_DARK, fg=TEXT_SEC, font=FONT_SMALL).pack(side="left", padx=8)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=20, pady=4)

        body = tk.Frame(self, bg=BG_DARK)
        body.pack(fill="both", expand=True, padx=20, pady=8)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        # ── Danh sách layer (trái) ──────────────────────────
        lf = tk.LabelFrame(body, text="  Layers in DXF  ",
                           bg=BG_PANEL, fg=ACCENT2, font=FONT_BOLD,
                           relief="flat", highlightbackground=BORDER,
                           highlightthickness=1, padx=8, pady=8)
        lf.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        sb = tk.Scrollbar(lf)
        sb.pack(side="right", fill="y")
        self.layer_list = tk.Listbox(lf, bg=BG_CARD, fg=TEXT_PRI,
                                     selectbackground=ACCENT,
                                     selectforeground="white",
                                     font=FONT_MONO, bd=0, relief="flat",
                                     yscrollcommand=sb.set,
                                     activestyle="none", height=20)
        self.layer_list.pack(fill="both", expand=True)
        sb.config(command=self.layer_list.yview)
        for ly in layers:
            self.layer_list.insert("end", f"  {ly}")

        # ── Panel phải ─────────────────────────────────────
        right = tk.Frame(body, bg=BG_DARK)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)

        self._build_slab_section(right)
        self._build_other_section(right)

        # style combobox — red text for easy reading on dark background
        st = ttk.Style(self)
        st.configure("TCombobox", fieldbackground=BG_CARD,
                     background=BG_CARD, foreground="#FF4444",
                     selectbackground=ACCENT)

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=20, pady=6)

        btn_row = tk.Frame(self, bg=BG_DARK)
        btn_row.pack(fill="x", padx=20, pady=(0, 16))
        tk.Button(btn_row, text="Cancel",
                  bg=BG_CARD, fg=TEXT_SEC, relief="flat",
                  font=FONT_MAIN, padx=16, pady=6, cursor="hand2",
                  command=self.destroy).pack(side="right", padx=(8, 0))
        tk.Button(btn_row, text="✓  Confirm Layer Assignment",
                  bg=ACCENT, fg="white", relief="flat",
                  activebackground="#3A6FE8", activeforeground="white",
                  font=FONT_BOLD, padx=16, pady=6, cursor="hand2",
                  command=self._confirm).pack(side="right")
        tk.Label(btn_row,
                 text="Tip: Click a layer on the left → press '← Assign' to assign",
                 bg=BG_DARK, fg=TEXT_DIM, font=FONT_SMALL).pack(side="left")

    # ── Slab section (multi-row) ───────────────────────────────
    def _build_slab_section(self, parent):
        sf = tk.LabelFrame(parent, text="  🟩 Slabs  ",
                           bg=BG_PANEL, fg=TAG_SLAB, font=FONT_BOLD,
                           relief="flat", highlightbackground=TAG_SLAB,
                           highlightthickness=1, padx=10, pady=8)
        sf.pack(fill="x", pady=(0, 8))

        # Header labels
        hdr = tk.Frame(sf, bg=BG_PANEL)
        hdr.pack(fill="x", pady=(0, 2))
        tk.Label(hdr, text="DXF Layer", bg=BG_PANEL, fg=TEXT_SEC,
                 font=FONT_SMALL, width=18, anchor="w").pack(side="left")
        tk.Label(hdr, text="Thick (mm)", bg=BG_PANEL, fg=TEXT_SEC,
                 font=FONT_SMALL, width=8, anchor="w").pack(side="left", padx=(28, 0))
        tk.Label(hdr, text="TOC (mm)", bg=BG_PANEL, fg=TEXT_SEC,
                 font=FONT_SMALL, width=8, anchor="w").pack(side="left", padx=(6, 0))
        tk.Label(hdr, text="Priority", bg=BG_PANEL, fg=TEXT_SEC,
                 font=FONT_SMALL, width=7, anchor="w").pack(side="left", padx=(6, 0))

        # Container for dynamic rows
        self._slab_container = tk.Frame(sf, bg=BG_PANEL)
        self._slab_container.pack(fill="x")

        # Load existing entries
        existing = self._current.get("slabs", [])
        if isinstance(existing, str):
            existing = ([{"layer": existing, "thickness": 0.20, "toc": 0.0, "priority": 1}]
                        if existing else [])
        if not existing:
            existing = [{"layer": "", "thickness": 200, "toc": 0, "priority": 1}]
        for entry in existing:
            self._add_slab_row(entry.get("layer", ""),
                               entry.get("thickness", 200),
                               entry.get("toc", 0),
                               entry.get("priority", 1))

        tk.Button(sf, text="＋  Add slab layer",
                  bg=BG_CARD, fg=TAG_SLAB, relief="flat",
                  font=FONT_SMALL, padx=8, pady=3, cursor="hand2",
                  command=self._add_slab_row).pack(anchor="w", pady=(6, 0))

    def _add_slab_row(self, layer="", thickness=200, toc=0, priority=1):
        row = tk.Frame(self._slab_container, bg=BG_PANEL)
        row.pack(fill="x", pady=2)

        layer_var = tk.StringVar(value=layer if layer else "(Not used)")
        thick_var = tk.IntVar(value=int(thickness))
        toc_var   = tk.IntVar(value=int(toc))
        prio_var  = tk.IntVar(value=priority)

        combo = ttk.Combobox(row, textvariable=layer_var,
                             values=self._all_layers,
                             state="readonly", width=16, font=FONT_MONO)
        combo.pack(side="left")

        tk.Button(row, text="←", bg=BG_CARD, fg=ACCENT,
                  relief="flat", font=FONT_SMALL, padx=5, pady=2,
                  cursor="hand2",
                  command=lambda v=layer_var: self._assign(v)
                  ).pack(side="left", padx=(3, 8))

        # Thickness (mm)
        ttk.Spinbox(row, from_=50, to=2000, increment=5,
                    textvariable=thick_var, width=6, font=FONT_MAIN
                    ).pack(side="left")
        tk.Label(row, text="mm", bg=BG_PANEL, fg=TEXT_SEC,
                 font=FONT_SMALL).pack(side="left", padx=(2, 8))

        # TOC (mm)
        ttk.Spinbox(row, from_=-20000, to=200000, increment=50,
                    textvariable=toc_var, width=7, font=FONT_MAIN
                    ).pack(side="left")
        tk.Label(row, text="mm", bg=BG_PANEL, fg=TEXT_SEC,
                 font=FONT_SMALL).pack(side="left", padx=(2, 8))

        # Priority
        ttk.Spinbox(row, from_=1, to=20, increment=1,
                    textvariable=prio_var, width=4, font=FONT_MAIN
                    ).pack(side="left")

        entry_tuple = (layer_var, thick_var, toc_var, prio_var)
        tk.Button(row, text="✕", bg=BG_PANEL, fg=ERROR,
                  relief="flat", font=FONT_SMALL, padx=4, pady=2,
                  cursor="hand2",
                  command=lambda r=row, e=entry_tuple: self._remove_slab_row(r, e)
                  ).pack(side="left", padx=(6, 0))

        self._slab_rows.append(entry_tuple)

    def _remove_slab_row(self, row_frame, entry):
        row_frame.destroy()
        if entry in self._slab_rows:
            self._slab_rows.remove(entry)

    # ── Other elements (col / wall / opening) ─────────────────
    def _build_other_section(self, parent):
        af = tk.LabelFrame(parent, text="  Column / Wall / Opening  ",
                           bg=BG_PANEL, fg=ACCENT2, font=FONT_BOLD,
                           relief="flat", highlightbackground=BORDER,
                           highlightthickness=1, padx=12, pady=10)
        af.pack(fill="x")
        af.columnconfigure(1, weight=1)

        for row_i, (label, key, color) in enumerate(self.OTHER_TYPES):
            tk.Label(af, text="●", bg=BG_PANEL, fg=color,
                     font=("Segoe UI", 11)).grid(
                         row=row_i*2, column=0, sticky="w", pady=(8, 0))
            tk.Label(af, text=label, bg=BG_PANEL, fg=TEXT_PRI,
                     font=FONT_SMALL).grid(
                         row=row_i*2, column=1, sticky="w",
                         pady=(8, 0), padx=(4, 0))

            var = tk.StringVar(value=self._current.get(key, "(Not used)"))
            self._vars[key] = var

            ttk.Combobox(af, textvariable=var, values=self._all_layers,
                         state="readonly", width=20, font=FONT_MONO
                         ).grid(row=row_i*2+1, column=0, columnspan=2,
                                sticky="ew", pady=(2, 0))

            tk.Button(af, text="← Assign selected layer",
                      bg=BG_CARD, fg=ACCENT, relief="flat",
                      font=FONT_SMALL, cursor="hand2", padx=6, pady=3,
                      command=lambda v=var: self._assign(v)
                      ).grid(row=row_i*2+1, column=2, padx=(6, 0),
                             pady=(2, 0), sticky="w")

    # ── Helpers ───────────────────────────────────────────────
    def _assign(self, var: tk.StringVar):
        sel = self.layer_list.curselection()
        if not sel:
            messagebox.showinfo("No layer selected",
                                "Please click a layer on the left list first.",
                                parent=self)
            return
        var.set(self.layer_list.get(sel[0]).strip())

    def _confirm(self):
        slabs = []
        for layer_var, thick_var, toc_var, prio_var in self._slab_rows:
            ln = layer_var.get()
            if ln and ln != "(Not used)":
                try:    t = int(thick_var.get())
                except: t = 200
                try:    toc = int(toc_var.get())
                except: toc = 0
                try:    p = int(prio_var.get())
                except: p = 1
                slabs.append({"layer": ln, "thickness": t, "toc": toc, "priority": p})

        self.result = {
            "slabs": slabs,
            **{key: (v.get() if v.get() != "(Not used)" else "")
               for key, v in self._vars.items()}
        }
        self.destroy()


# ─────────────────────────────────────────────────────────────
# MAIN APP
# ─────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PTX Tools — DXF → RAM Concept Builder  by TOQ")
        self.geometry("940x740")
        self.resizable(True, True)
        self.configure(bg=BG_DARK)
        self.minsize(800, 620)

        # Layer assignments (mặc định rỗng)
        self._layer_map = {"slabs": [], "columns": "", "walls": "", "openings": ""}
        self._dxf_layers: list = []

        self._build_ui()

    # ── Widget helpers ────────────────────────────────────────
    def _entry_row(self, parent, label, row, browse_fn=None, is_save=False):
        tk.Label(parent, text=label, bg=BG_PANEL, fg=TEXT_SEC,
                 font=FONT_SMALL, anchor="w").grid(
                     row=row, column=0, sticky="w", padx=(0,8), pady=4)
        var = tk.StringVar()
        entry = tk.Entry(parent, textvariable=var,
                         bg=BG_CARD, fg=TEXT_PRI,
                         insertbackground=TEXT_PRI, relief="flat",
                         font=FONT_MONO, bd=0,
                         highlightthickness=1,
                         highlightbackground=BORDER,
                         highlightcolor=ACCENT)
        entry.grid(row=row, column=1, sticky="ew", pady=4, ipady=6, padx=(0,8))
        if browse_fn:
            tk.Button(parent, text="📂 Browse",
                      bg=BG_CARD, fg=ACCENT, relief="flat",
                      font=FONT_SMALL, cursor="hand2",
                      padx=10, pady=4,
                      command=lambda: browse_fn(var, is_save)
                      ).grid(row=row, column=2, pady=4, sticky="w")
        return var

    def _spin_row(self, parent, label, row, from_, to, inc, init):
        tk.Label(parent, text=label, bg=BG_PANEL, fg=TEXT_SEC,
                 font=FONT_SMALL, anchor="w").grid(
                     row=row, column=0, sticky="w", padx=(0,8), pady=4)
        var = tk.DoubleVar(value=init)
        ttk.Spinbox(parent, from_=from_, to=to, increment=inc,
                    textvariable=var, width=10, font=FONT_MAIN
                    ).grid(row=row, column=1, sticky="w", pady=4, ipady=4)
        return var

    # ── Build UI ──────────────────────────────────────────────
    # ── PTX logo (Canvas) ─────────────────────────────────────
    @staticmethod
    def _make_ptx_logo(parent):
        """Vẽ logo PTX bằng Canvas để khớp brand màu sắc."""
        W, H = 90, 46
        c = tk.Canvas(parent, width=W, height=H,
                      bg=BG_DARK, highlightthickness=0)
        fnt_big  = ("Segoe UI", 26, "bold")
        fnt_sub  = ("Segoe UI", 7)
        # "PT" — màu trắng-xanh sáng (navy brand đảo cho dark mode)
        c.create_text(28, 20, text="PT", font=fnt_big,
                      fill="#C8D8EE", anchor="center")
        # "X" — màu steel-gray
        c.create_text(66, 20, text="X",  font=fnt_big,
                      fill=PTX_STEEL, anchor="center")
        # Đường kẻ phân cách PT | X
        c.create_line(46, 4, 46, 36, fill=BORDER, width=1)
        # Tagline nhỏ
        c.create_text(45, 40, text="POST TENSION EXPERTS",
                      font=fnt_sub, fill=TEXT_DIM, anchor="center")
        return c

    def _build_ui(self):
        # ── Header ────────────────────────────────────────────
        hdr = tk.Frame(self, bg=BG_DARK)
        hdr.pack(fill="x", padx=20, pady=(16, 4))

        # Logo PTX
        logo = self._make_ptx_logo(hdr)
        logo.pack(side="left", padx=(0, 16))

        # Divider dọc
        tk.Frame(hdr, bg=BORDER, width=1).pack(side="left", fill="y",
                                               padx=(0, 16), pady=4)

        # Title + subtitle
        tf = tk.Frame(hdr, bg=BG_DARK)
        tf.pack(side="left")
        tk.Label(tf, text="DXF → RAM Concept Builder",
                 bg=BG_DARK, fg=TEXT_PRI, font=FONT_TITLE).pack(anchor="w")
        sub = tk.Frame(tf, bg=BG_DARK)
        sub.pack(anchor="w")
        tk.Label(sub, text="Read DXF drawing · Assign layers · Auto-generate mesh model",
                 bg=BG_DARK, fg=TEXT_SEC, font=FONT_SMALL).pack(side="left")
        tk.Label(sub, text="   by TOQ",
                 bg=BG_DARK, fg=ACCENT2, font=("Segoe UI", 9, "italic")).pack(side="left")

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=20, pady=6)

        # Body
        body = tk.Frame(self, bg=BG_DARK)
        body.pack(fill="both", expand=True, padx=20)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        left  = tk.Frame(body, bg=BG_DARK)
        right = tk.Frame(body, bg=BG_DARK)
        left.grid (row=0, column=0, sticky="nsew", padx=(0,8))
        right.grid(row=0, column=1, sticky="nsew", padx=(8,0))
        left.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        # ══ LEFT ══════════════════════════════════════════════
        self._section(left, "📁  File Paths",          0, self._build_paths)
        self._section(left, "🗂  Assign DXF Layers",  1, self._build_layer_panel)
        self._section(left, "⚙️  Structural Params",  2, self._build_params)

        # ══ RIGHT: Log ════════════════════════════════════════
        log_card = tk.Frame(right, bg=BG_PANEL,
                            highlightbackground=BORDER, highlightthickness=1)
        log_card.grid(row=0, column=0, sticky="nsew")
        log_card.rowconfigure(1, weight=1)
        log_card.columnconfigure(0, weight=1)

        log_hdr = tk.Frame(log_card, bg=BG_PANEL)
        log_hdr.grid(row=0, column=0, sticky="ew", padx=14, pady=(12,4))
        tk.Label(log_hdr, text="📋  Processing Log",
                 bg=BG_PANEL, fg=TEXT_PRI, font=FONT_BOLD).pack(side="left")
        tk.Button(log_hdr, text="Clear", bg=BG_CARD, fg=TEXT_SEC,
                  relief="flat", font=FONT_SMALL, cursor="hand2",
                  padx=8, pady=2,
                  command=self._clear_log).pack(side="right")

        self.log_box = scrolledtext.ScrolledText(
            log_card, bg=BG_DARK, fg=TEXT_PRI,
            font=FONT_MONO, bd=0, relief="flat",
            state="disabled", wrap="word",
            selectbackground=ACCENT)
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0,10))
        self.log_box.tag_config("title",   foreground=ACCENT2, font=("Consolas",9,"bold"))
        self.log_box.tag_config("success", foreground=SUCCESS)
        self.log_box.tag_config("error",   foreground=ERROR)
        self.log_box.tag_config("warning", foreground=WARNING)
        self.log_box.tag_config("info",    foreground=TEXT_SEC)

        # Footer
        foot = tk.Frame(self, bg=BG_DARK)
        foot.pack(fill="x", padx=20, pady=(8,16))
        self.progress = ttk.Progressbar(foot, mode="indeterminate",
                                        style="Accent.Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=(0,8))
        btn_row = tk.Frame(foot, bg=BG_DARK)
        btn_row.pack(fill="x")
        self.status_lbl = tk.Label(btn_row, text="Ready",
                                   bg=BG_DARK, fg=TEXT_SEC, font=FONT_SMALL)
        self.status_lbl.pack(side="left")
        tk.Button(btn_row, text="▶  Run Conversion",
                  bg=ACCENT, fg="white",
                  activebackground="#3A6FE8", activeforeground="white",
                  relief="flat", font=FONT_BOLD,
                  padx=24, pady=8, cursor="hand2",
                  command=self._run).pack(side="right")

        self._style_widgets()

    def _section(self, parent, title, row, builder_fn):
        card = tk.LabelFrame(parent, text=f"  {title}  ",
                             bg=BG_PANEL, fg=ACCENT2,
                             font=FONT_BOLD, relief="flat",
                             highlightbackground=BORDER, highlightthickness=1,
                             padx=14, pady=10)
        card.grid(row=row, column=0, sticky="ew", pady=(0,10))
        card.columnconfigure(1, weight=1)
        builder_fn(card)

    # ── Sections ──────────────────────────────────────────────
    def _build_paths(self, f):
        self.v_dxf = self._entry_row(f, "DXF Drawing File *",     0, self._browse_dxf)
        self.v_tpl = self._entry_row(f, "RAM Template (.cpt)",    1, self._browse_file)
        self.v_out = self._entry_row(f, "Output File (.cpt) *",   2, self._browse_file, is_save=True)
        # Chia se duong dan sang Area Load Importer (cung bo Suite)
        try:
            import shared_paths
            self.v_dxf.trace_add(
                "write", lambda *a: shared_paths.save_paths(dxf=self.v_dxf.get().strip()))
            self.v_out.trace_add(
                "write", lambda *a: shared_paths.save_paths(cpt=self.v_out.get().strip()))
        except Exception:
            pass

    def _build_layer_panel(self, f):
        """Panel hiển thị layer đã gán + nút mở dialog."""
        f.columnconfigure(1, weight=1)

        # Hàng mô tả
        tk.Label(f, text="Select DXF layers corresponding to each structural element type.",
                 bg=BG_PANEL, fg=TEXT_SEC, font=FONT_SMALL,
                 wraplength=340, justify="left"
                 ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0,8))

        # 4 badge hiển thị layer đã gán
        DEFS = [
            ("🟩 Slab",    "slabs",   TAG_SLAB),
            ("🟨 Column",  "columns", TAG_COL),
            ("🟦 Wall",    "walls",   TAG_WALL),
            ("🟥 Opening", "openings",TAG_OPEN),
        ]
        self._badge_vars = {}
        badge_row = tk.Frame(f, bg=BG_PANEL)
        badge_row.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0,8))

        for i, (lbl, key, color) in enumerate(DEFS):
            cell = tk.Frame(badge_row, bg=BG_CARD,
                            highlightbackground=color,
                            highlightthickness=1)
            cell.grid(row=0, column=i, sticky="ew", padx=(0,6), ipadx=6, ipady=4)
            badge_row.columnconfigure(i, weight=1)

            tk.Label(cell, text=lbl, bg=BG_CARD, fg=color,
                     font=FONT_SMALL).pack(anchor="w")
            var = tk.StringVar(value="—")
            self._badge_vars[key] = var
            tk.Label(cell, textvariable=var, bg=BG_CARD,
                     fg=TEXT_PRI, font=FONT_MONO,
                     wraplength=110).pack(anchor="w")

        # Nút mở dialog
        btn_f = tk.Frame(f, bg=BG_PANEL)
        btn_f.grid(row=2, column=0, columnspan=3, sticky="w")

        tk.Button(btn_f, text="🗂  Open DXF Layer List...",
                  bg=ACCENT2, fg=BG_DARK,
                  activebackground="#8B6FE0", activeforeground=BG_DARK,
                  relief="flat", font=FONT_BOLD,
                  padx=14, pady=6, cursor="hand2",
                  command=self._open_layer_picker
                  ).pack(side="left")

        tk.Button(btn_f, text="↺ Reset layers",
                  bg=BG_CARD, fg=TEXT_SEC,
                  relief="flat", font=FONT_SMALL,
                  padx=10, pady=6, cursor="hand2",
                  command=self._reset_layers
                  ).pack(side="left", padx=(8,0))

        self._layer_status = tk.Label(btn_f, text="No layers loaded",
                                      bg=BG_PANEL, fg=TEXT_DIM,
                                      font=FONT_SMALL)
        self._layer_status.pack(side="left", padx=12)

    def _build_params(self, f):
        self.v_colh = self._spin_row(f, "Column height (m)",      0, 1.00, 6.00, 0.10, 3.00)
        self.v_mesh = self._spin_row(f, "Mesh size (m)",          1, 0.10, 2.00, 0.05, 0.50)
        self.v_oseg = self._spin_row(f, "Circle opening seg (m)", 2, 0.20, 5.00, 0.10, 1.00)
        self.v_sseg = self._spin_row(f, "Curved slab edge seg (m)", 3, 0.20, 5.00, 0.10, 0.80)
        self.v_wseg = self._spin_row(f, "Curved wall seg (m)",     4, 0.20, 5.00, 0.10, 0.80)

        # Tự dò bề dày + cao độ sàn theo nét STEP / SOFFIT STEP + SLAB_DEPTH + S.F.L
        self.v_detect_depth = tk.BooleanVar(value=True)
        tk.Checkbutton(
            f, text="Auto-detect slab depth & TOC (STEP / SOFFIT STEP)",
            variable=self.v_detect_depth, bg=BG_PANEL, fg=TEXT_SEC,
            selectcolor=BG_CARD, activebackground=BG_PANEL,
            activeforeground=TEXT_PRI, font=FONT_SMALL, anchor="w",
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 2))

    # ── Browse / Layer ────────────────────────────────────────
    def _browse_dxf(self, var, *_):
        path = filedialog.askopenfilename(
            filetypes=[("DXF", "*.dxf"), ("All files", "*.*")])
        if path:
            var.set(path)
            self._load_layers(path)

    def _browse_file(self, var, is_save=False):
        if is_save:
            path = filedialog.asksaveasfilename(
                defaultextension=".cpt",
                filetypes=[("RAM Concept", "*.cpt"), ("All files", "*.*")])
        else:
            path = filedialog.askopenfilename(
                filetypes=[("RAM Concept", "*.cpt"), ("DXF", "*.dxf"), ("All files", "*.*")])
        if path:
            var.set(path)

    def _browse_dir(self, var, *_):
        path = filedialog.askdirectory(title="Select RAM Concept Python API folder")
        if path:
            var.set(path)

    def _load_layers(self, dxf_path: str):
        """Đọc layer từ DXF và cập nhật trạng thái."""
        self._layer_status.config(text="Reading layers...", fg=WARNING)
        self.update_idletasks()

        def worker():
            layers, err = get_dxf_layers(dxf_path)
            self._dxf_layers = layers
            self.after(0, self._on_layers_loaded, layers, err)

        threading.Thread(target=worker, daemon=True).start()

    def _on_layers_loaded(self, layers, err=None):
        if layers:
            done = self._auto_assign_layers(layers)
            if done:
                self._layer_status.config(
                    text=f"✓ {len(layers)} layers — auto-assigned: {', '.join(done)}",
                    fg=SUCCESS)
            else:
                self._layer_status.config(
                    text=f"✓ {len(layers)} layers — click 'Open DXF Layer List' to assign",
                    fg=SUCCESS)
        else:
            msg = f"⚠ {err}" if err else "⚠ Could not read layers"
            self._layer_status.config(text=msg[:80], fg=WARNING)

    # Gán layer mặc định theo tên chuẩn của PTX sau khi load DXF
    DEFAULT_LAYERS = {
        "slabs":    "SLAB EDGE",
        "columns":  "CO UNDER",
        "walls":    "WALL UNDER",
        "openings": "OPENING EDGE",
    }

    def _auto_assign_layers(self, layers):
        low = {ly.strip().lower(): ly for ly in layers}
        done = []
        sl = low.get(self.DEFAULT_LAYERS["slabs"].lower())
        if sl:
            self._layer_map["slabs"] = [{"layer": sl, "thickness": 200,
                                         "toc": 0, "priority": 1}]
            done.append(f"slab={sl}")
        for key, lbl in (("columns", "column"), ("walls", "wall"), ("openings", "opening")):
            nm = low.get(self.DEFAULT_LAYERS[key].lower())
            if nm:
                self._layer_map[key] = nm
                done.append(f"{lbl}={nm}")
        try:
            self._refresh_badges()
        except Exception:
            pass
        return done

    def _open_layer_picker(self):
        dxf = self.v_dxf.get().strip()
        if not dxf or not os.path.isfile(dxf):
            messagebox.showwarning("No DXF file selected",
                                   "Please select a DXF file before assigning layers!")
            return

        if not self._dxf_layers:
            self._dxf_layers, err = get_dxf_layers(dxf)
        else:
            err = None

        if not self._dxf_layers:
            detail = f"\n\nError detail:\n{err}" if err else ""
            messagebox.showerror("Cannot read layers",
                                 f"Could not read layers from DXF file.{detail}")
            return

        dlg = LayerPickerDialog(self, self._dxf_layers, self._layer_map)
        self.wait_window(dlg)

        if dlg.result is not None:
            self._layer_map = dlg.result
            self._refresh_badges()
            slabs = self._layer_map.get("slabs", [])
            slab_info = ", ".join(
                f"{s['layer']}({s.get('thickness',0.2)*1000:.0f}mm/P{s.get('priority',1)})"
                for s in slabs) or "—"
            self._log(f"Layers assigned: Slabs=[{slab_info}]  "
                      f"Columns={self._layer_map.get('columns','') or '—'}  "
                      f"Walls={self._layer_map.get('walls','') or '—'}  "
                      f"Openings={self._layer_map.get('openings','') or '—'}", "info")

    def _refresh_badges(self):
        for key, var in self._badge_vars.items():
            if key == "slabs":
                slabs = self._layer_map.get("slabs", [])
                if isinstance(slabs, list) and slabs:
                    names = [s.get("layer", "") for s in slabs if s.get("layer")]
                    var.set("\n".join(names) if names else "—")
                else:
                    var.set("—")
            else:
                val = self._layer_map.get(key, "")
                var.set(val if val else "—")

    def _reset_layers(self):
        self._layer_map = {"slabs": [], "columns": "", "walls": "", "openings": ""}
        self._refresh_badges()

    # ── Log ──────────────────────────────────────────────────
    def _log(self, msg, tag="info"):
        self.log_box.configure(state="normal")
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_box.insert("end", f"[{ts}] {msg}\n", tag)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    # ── Run ───────────────────────────────────────────────────
    def _run(self):
        dxf = self.v_dxf.get().strip()
        out = self.v_out.get().strip()
        if not dxf:
            messagebox.showwarning("Missing input", "Please select a DXF file!")
            return
        if not out:
            messagebox.showwarning("Missing input", "Please select an output file!")
            return
        _has_layer = (bool(self._layer_map.get("slabs")) or
                      any(self._layer_map.get(k, "") for k in ("columns","walls","openings")))
        if not _has_layer:
            if not messagebox.askyesno("No layers assigned",
                                       "No layers have been assigned!\n"
                                       "Continuing will create no structural elements.\n\n"
                                       "Continue anyway?"):
                return

        config = {
            "dxf_file":     dxf,
            "cpt_template": self.v_tpl.get().strip(),
            "cpt_output":   out,
            "ram_api_path": "",
            "unit_scale":   0.001,   # DXF đơn vị mm
            "slab_thick":   0.20,    # fallback, thickness sàn đặt theo layer
            "col_height":   self.v_colh.get(),
            "wall_thick":   0.20,    # mặc định 200mm
            "mesh_size":    self.v_mesh.get(),
            "opening_seg":  self.v_oseg.get(),   # edges tối thiểu khi xấp xỉ lỗ tròn
            "slab_seg":     self.v_sseg.get(),   # edges tối thiểu khi làm phẳng biên sàn cong
            "wall_seg":     self.v_wseg.get(),   # day cung toi thieu khi chia vach cong
            "layer_map":    self._layer_map,
            "detect_slab_depth": bool(self.v_detect_depth.get()),
            "slab_depth_layers": {                # tên layer nguồn (chuẩn PTX)
                "step":   "STEP",
                "soffit": "SOFFIT STEP",
                "depth":  "SLAB_DEPTH",
                "sfl":    "STRUCTURAL FINISH FLOOR",
            },
        }

        self._clear_log()
        self._log("══════════════════════════════════════", "title")
        self._log("  DXF → RAM CONCEPT BUILDER  v2", "title")
        self._log("══════════════════════════════════════", "title")
        self.status_lbl.config(text="Processing...", fg=WARNING)
        self.progress.start(12)

        def worker():
            ok = run_conversion(config, self._log)
            self.after(0, self._done, ok)

        threading.Thread(target=worker, daemon=True).start()

    def _done(self, ok):
        self.progress.stop()
        if ok:
            self.status_lbl.config(text="✓ Done!", fg=SUCCESS)
            self._log("\n══ COMPLETED ══", "success")
            messagebox.showinfo("Success",
                                f"Model created successfully!\n\n{self.v_out.get()}")
        else:
            self.status_lbl.config(text="✗ Error", fg=ERROR)
            self._log("\n══ FAILED ══", "error")

    def _style_widgets(self):
        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("Accent.Horizontal.TProgressbar",
                        troughcolor=BG_CARD, background=ACCENT,
                        darkcolor=ACCENT, lightcolor=ACCENT,
                        bordercolor=BORDER)
        style.configure("TSpinbox",
                        fieldbackground=BG_CARD,
                        background=BG_CARD,
                        foreground=TEXT_PRI)


# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = App()
    app.mainloop()

# DXF → RAM Concept Suite

A single Windows application that bundles **three tools** for moving structural
data from DXF drawings into **RAM Concept 2023**:

| Tool | Purpose |
|------|---------|
| **Mesh Model Builder** | Read a DXF plan, map layers to structural elements (slab / column / wall / opening), auto-detect **thickness + TOC + drop panels**, and generate a meshed RAM Concept model (`.cpt`). |
| **Area Load Importer** | Read a DXF load plan (hatched regions), snap it onto an existing RAM Concept slab, assign **SDL** and **LL** loads and import them into the model. |
| **Point / Line Load Importer** | Read **point loads** and **line loads** straight from DXF annotations and import them into the model. |

When you open the app, a **launcher** appears — click a card to start the tool
you need. Each tool opens in its own window, so you can run them at once.

---

## 1. Requirements

- **Windows 10/11 (64-bit).**
- **RAM Concept 2023** installed in the default location
  `C:\Program Files\Bentley\Engineering\RAM Concept\RAM Concept 2023\python`.
  This is required to actually **create / import** into a model. The app talks
  to RAM Concept through its Python API.
- No Python installation is needed — everything (including the `ezdxf` library)
  is bundled inside the `.exe`.

> If RAM Concept is not installed you can still open DXF files and lay out the
> work, but the final "Run / Import" step that writes the `.cpt` will fail.

---

## 2. Getting started

1. Double-click **`DXF_RAMConcept_Suite.exe`**.
2. On the launcher, choose one of the three tools.

### Shared file paths
The **DXF file** and the **output CPT file** you pick in one tool are remembered
and **pre-filled automatically** in the others. A typical workflow is therefore:

1. Build the mesh model first (this defines the DXF + the `.cpt`).
2. Open the load tools — the same paths are already filled in.

---

## 3. Mesh Model Builder

1. **DXF Drawing File** — browse to your plan `.dxf`.
2. **RAM Template (.cpt)** *(optional)* — start from an existing template;
   leave empty to create a brand-new model.
3. **Output File (.cpt)** — where the generated model will be saved.
4. Click **Open DXF Layer List…** and assign each DXF layer to a structural
   element type:
   - 🟩 Slab  ·  🟨 Column  ·  🟦 Wall  ·  🟥 Opening
   - For slabs you can also set thickness, TOC and priority.
5. Click **Confirm Layer Assignment**.
6. Press **▶ Run Conversion**. The **Processing Log** shows each step
   (read DXF → connect API → create elements → mesh → save).
7. When finished you get **✓ Done!** and the `.cpt` file is written to the
   output path.

### Auto-detect slab depth / TOC / drop panels
Enable **Auto-detect slab depth & TOC** to let the app subdivide the slab into
regions based on the drawing annotations (PTX annotation convention):

- **Thickness**: callouts on the **`SLAB_DEPTH`** layer (the leader target —
  a circle — is preferred when present, because the hexagon holding the value
  may sit in a different area while its leader points to the real region).
- **TOC elevation**: if **absolute S.F.L** values (e.g. `+119.350`) exist on the
  **`STRUCTURAL FINISH FLOOR`** layer, the highest one becomes datum 0. If no
  S.F.L is present, the app uses the **step jumps** between **`STEP`** /
  **`SOFFIT STEP`** lines. If both exist they are cross-checked and a warning is
  raised on mismatch.
- **Drop panels**: closed polylines on the **`SLAB_PANEL`** layer are the
  authoritative drop-panel regions; in addition the app auto-closes pocket bands
  around a leader-circle between parallel STEP and SOFFIT lines. Panel thickness
  comes from the callout inside it; TOC is inherited from the region below.
- **Setdown**: the default value is read from a `SETDOWN <n>mm U.N.O` legend.

The layer names above are the PTX defaults — if your drawing uses different
names, change them in the layer configuration. The **Curved slab edge seg (m)**
field controls how finely curved slab edges are flattened.

**Tips**
- Columns drawn as circles/rectangles are detected automatically; wall thickness
  is measured from parallel lines in the DXF.
- If meshing fails, the geometry is still saved — open the `.cpt` in RAM Concept
  and mesh it manually.

---

## 4. Area Load Importer

1. **DXF file** — the load plan `.dxf` (areas drawn as closed polylines/hatches).
2. **CPT file** — the existing RAM Concept model that already contains the slab.
3. Load the regions one of two ways:
   - **Read DXF** — load every closed polyline/hatch as a load region (assign
     values manually afterwards).
   - **Hatch loads (legend)** — read the **LOADING LEGEND** in the drawing and
     **auto-assign name + SDL/LL** to each hatched region by **color**. This is
     the fastest path when the drawing carries a legend.
4. Click **Read slab + Auto-align** to pull the slab outline (red) from the CPT
   and auto-fit the plan onto it.
5. **Align (optional, for best accuracy):** click **Align 2 points** and follow
   the 4 steps (pick 2 matching points on the DXF and on the red slab outline).
   The tool solves the scale + offset for you.
6. **Assign loads:**
   - Click a region (or **Ctrl+click** / **Shift+drag** to select several).
   - Enter **Load name**, **SDL (kN/m²)** and **LL (kN/m²)**.
   - **Apply to SELECTED region** or **Apply to ALL regions**.
   - Region colors: **gray** = unassigned, **green** = assigned,
     **orange** = currently selected.
7. Click **IMPORT AREA LOAD INTO RAM CONCEPT**. Loads are written to the
   `SI Dead Loading` (SDL) and `Live (Reducible) Loading` (LL) layers and the
   `.cpt` is saved.

### Region-geometry options
- **Arc segment ≤ (mm)** — the general subdivision step for Read DXF / the
  conform grid (default **800**).
- **Curve seg ≤ (mm)** — a separate step for **curved arcs** in hatch loads
  (default **300**, **never smaller than 300 mm**). Arcs are split into short
  straight segments so the imported region keeps the exact drawing shape.
- Two regions that **share a curved edge** end up with **matching nodes on the
  curve** (the arcs are identical in the DXF, so tessellating at the same step
  produces the same points).
- **Subtract base** — subtract the base load (the legend base value) when
  assigning hatch loads, so each region only carries the delta over the base.
- **Conform to slab** *(default OFF)* — snap the curved region edges onto the
  slab-edge grid. Keeping it **off** makes the imported region **match the hatch
  shape exactly** (turning it on can distort straight edges → RAM rejects them).
  Only enable it when you genuinely need curved edges conformed to the slab.

**Canvas controls:** scroll = zoom, right-drag = pan, **Fit view** to reset.

---

## 4b. Point / Line Load Importer

Reads **point loads** and **line loads** directly from the DXF annotations and
imports them into RAM Concept — no manual clicking of values.

**DXF convention** (matches the PTX run-length annotation style):
- Loads live on the **`RUNLENGTH`** layer.
- **Point load** = a `LEADER` (one arrow). Location = the arrow tip.
- **Line load** = a `DIMENSION` (two arrows). Span = the two measured points.
- The two values next to each load are `TEXT` on the **`TEXT_35`** layer,
  stacked vertically: **top = SDL, bottom = LL**.
- Point loads are in **kN**, line loads in **kN/m**; `Fz` is applied **positive**.

**Steps**
1. **DXF file** / **CPT file** — pre-filled from the other tools if already used.
2. (Optional) change **Geometry layer** / **Value text layer** if your drawing
   uses different layer names.
3. **Detect loads** — parses the DXF; detected point/line loads are listed in
   the log and drawn on the canvas (green dots = point, orange lines = line).
4. **Read slab** — pulls the slab outline (red) from the CPT and does an
   approximate **bbox auto-align**.
5. For precise placement, click **Align 2 points** and pick 2 load points on the
   DXF plus the matching points on the red slab outline (or type **Unit scale**
   and **Offset X/Y** directly). The scale/offset is shared with the Area Load
   Importer.
6. **IMPORT POINT/LINE LOADS INTO RAM CONCEPT** — point loads use
   `add_point_load`, line loads use `add_line_load`, written to the
   `SI Dead Loading` (SDL) and `Live (Reducible) Loading` (LL) layers.

**Transfer loads from columns/walls above (DL/LL over)**
The tool also auto-detects **transfer loads** written as `DL=950(kN)` /
`LL=160(kN)` (on the text layer) with a **leader** pointing to an element above:
- Arrow on a **WALL OVER** → **line load** along the wall **centerline**, value =
  DL/length and LL/length (kN/m).
- Arrow on a **CO OVER** (column) → **point load** at the **column center**,
  value = DL and LL (kN).
- Moments `MyEQX/MyEQY` are **ignored** (vertical Fz only). DL goes to
  `SI Dead Loading`, LL to `Live (Reducible) Loading`.
- Any leader whose tip is not on a WALL OVER/CO OVER element is reported as
  **unmatched** in the log for manual handling.

> Always check the canvas overlay (loads sitting on the red slab outline) before
> importing — that is your verification that the alignment is correct.

---

## 5. Sign / unit conventions

- Enter the **correct Fz sign** following your model convention
  (e.g. a downward load of 0.5 → `-0.5`).
- Area loads are in **kN/m²**; point loads in **kN**; line loads in **kN/m**.
- Each region with a non-zero value creates one SDL and/or one LL area load.

---

## 6. Troubleshooting

| Symptom | Likely cause / fix |
|---------|--------------------|
| "Could not load / start RAM Concept" | RAM Concept 2023 not installed, or installed in a non-default folder. |
| "No CLOSED polyline/hatch found" | The load areas in the DXF are not closed shapes. |
| Red slab outline doesn't match the plan | Use **Align 2 points**, or adjust **Offset X/Y** manually. |
| Imported region is distorted / not straight | **Turn off Conform to slab** — the region then keeps the exact hatch shape. |
| Curved edges import too coarse | Lower **Curve seg** (minimum 300 mm). |
| One region fails to import | Usually a self-intersecting polygon after conform → turn off Conform to slab. |
| Mesh failed but file saved | Open the `.cpt` in RAM Concept and run mesh manually. |
| Slab depth / TOC not detected | Check the `SLAB_DEPTH` / `STRUCTURAL FINISH FLOOR` / `STEP` / `SOFFIT STEP` / `SLAB_PANEL` / `SETDOWN` layer names match your drawing. |

---

*Built with PyInstaller. Bundles `ezdxf`; uses the RAM Concept 2023 Python API
at runtime.*

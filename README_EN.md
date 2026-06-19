# DXF → RAM Concept Suite

A single Windows application that bundles **two tools** for moving structural
data from DXF drawings into **RAM Concept 2023**:

| Tool | Purpose |
|------|---------|
| **Mesh Model Builder** | Read a DXF plan, map layers to structural elements (slab / column / wall / opening) and auto-generate a meshed RAM Concept model (`.cpt`). |
| **Area Load Importer** | Read a DXF load plan, snap it onto an existing RAM Concept slab, then click regions to assign **SDL** and **LL** area loads and import them into the model. |

When you open the app, a **launcher** appears — click a card to start the tool
you need. Each tool opens in its own window, so you can run both at once.

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
2. On the launcher, choose:
   - **Mesh Model Builder** — to create a new model from geometry, or
   - **Area Load Importer** — to add area loads to an existing model.

### Shared file paths
The **DXF file** and the **output CPT file** you pick in *Mesh Model Builder*
are remembered and **pre-filled automatically** in *Area Load Importer*. A
typical workflow is therefore:

1. Build the mesh model first (this defines the DXF + the `.cpt`).
2. Open the Area Load Importer — the same paths are already filled in.

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

**Tips**
- Columns drawn as circles/rectangles are detected automatically; wall
  thickness is measured from parallel lines in the DXF.
- If meshing fails, the geometry is still saved — open the `.cpt` in RAM
  Concept and mesh it manually.

---

## 4. Area Load Importer

1. **DXF file** — the load plan `.dxf` (areas drawn as closed polylines/hatches).
2. **CPT file** — the existing RAM Concept model that already contains the slab.
3. Click **Read DXF** to load the regions, then **Read slab + Auto-align** to
   pull the slab outline from the CPT and auto-fit the plan onto it.
4. **Align (optional, for best accuracy):** click **Align 2 points** and follow
   the 4 steps (pick 2 matching points on the DXF and on the red slab outline).
   The tool solves the scale + offset for you.
5. **Assign loads:**
   - Click a region (or **Ctrl+click** / **Shift+drag** to select several).
   - Enter **Load name**, **SDL (kN/m²)** and **LL (kN/m²)**.
   - **Apply to SELECTED region** or **Apply to ALL regions**.
   - Region colors: **gray** = unassigned, **green** = assigned,
     **orange** = currently selected.
6. Click **IMPORT AREA LOAD INTO RAM CONCEPT**. Loads are written to the
   `SI Dead Loading` (SDL) and `Live (Reducible) Loading` (LL) layers and the
   `.cpt` is saved.

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

> Always check the canvas overlay (loads sitting on the red slab outline) before
> importing — that is your verification that the alignment is correct.

---

## 5. Sign / unit conventions

- Enter the **correct Fz sign** following your model convention
  (e.g. a downward load of 0.5 → `-0.5`).
- Loads are in **kN/m²**.
- Each region with a non-zero value creates one SDL and/or one LL area load.

---

## 6. Troubleshooting

| Symptom | Likely cause / fix |
|---------|--------------------|
| "Could not load / start RAM Concept" | RAM Concept 2023 not installed, or installed in a non-default folder. |
| "No CLOSED polyline/hatch found" | The load areas in the DXF are not closed shapes. |
| Red slab outline doesn't match the plan | Use **Align 2 points**, or adjust **Offset X/Y** manually. |
| Mesh failed but file saved | Open the `.cpt` in RAM Concept and run mesh manually. |

---

*Built with PyInstaller. Bundles `ezdxf`; uses the RAM Concept 2023 Python API
at runtime.*

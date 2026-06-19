# -*- coding: utf-8 -*-
"""
Chia se duong dan giua cac cong cu trong bo DXF -> RAM Concept Suite.
Mesh Model Builder GHI (dxf, cpt output) -> Area Load Importer DOC lai
de dien san, khoi phai chon lai.
Luu o %LOCALAPPDATA%\\PTX_DXF_RAMConcept\\shared_paths.json
"""

import os
import json
import tempfile

_base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
_DIR = os.path.join(_base, "PTX_DXF_RAMConcept")
_STORE = os.path.join(_DIR, "shared_paths.json")


def load_paths():
    """Tra ve dict {'dxf': ..., 'cpt': ...} (rong neu chua co/loi)."""
    try:
        with open(_STORE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_paths(dxf=None, cpt=None):
    """Cap nhat duong dan. Chi ghi field duoc truyen (khac None)."""
    data = load_paths()
    if dxf is not None:
        data["dxf"] = dxf
    if cpt is not None:
        data["cpt"] = cpt
    _write(data)


def save_transform(scale=None, ox=None, oy=None):
    """Chia se phep canh DXF->model (scale + offset) giua cac tool."""
    data = load_paths()
    if scale is not None:
        data["scale"] = scale
    if ox is not None:
        data["ox"] = ox
    if oy is not None:
        data["oy"] = oy
    _write(data)


def _write(data):
    try:
        os.makedirs(_DIR, exist_ok=True)
        with open(_STORE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass

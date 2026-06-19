#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PTX · DXF -> RAM Concept Suite  (Launcher)
============================================================
Gop 2 cong cu vao 1 file .exe duy nhat:
  1. Mesh Model Builder   -> module dxf_ramconcept_gui_v13
  2. Area Load Importer   -> module dxf_to_ramconcept

Moi cong cu chay trong 1 TIEN TRINH RIENG (exe tu chay lai chinh no
voi tham so --mesh / --load) de tranh xung dot 2 root tkinter.
"""

import os
import sys
import subprocess
import tkinter as tk

TOOL_MESH = "--mesh"
TOOL_LOAD = "--load"
TOOL_PLOAD = "--ploads"

# PTX palette
BG     = "#0D1626"
CARD   = "#1C2B52"
HOVER  = "#243565"
ACCENT = "#4A74B8"
TXT    = "#E8EDF8"
SEC    = "#8FA5C8"


def run_mesh():
    import dxf_ramconcept_gui_v13 as m
    m.App().mainloop()


def run_load():
    import dxf_to_ramconcept as m
    m.App().mainloop()


def run_ploads():
    import dxf_pointline_load as m
    m.App().mainloop()


def _spawn(flag):
    """Chay lai chinh exe/script voi tham so cong cu, trong tien trinh moi."""
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, flag]
    else:
        cmd = [sys.executable, os.path.abspath(__file__), flag]
    subprocess.Popen(cmd, close_fds=True)


def launcher():
    root = tk.Tk()
    root.title("PTX · DXF -> RAM Concept Suite")
    root.configure(bg=BG)
    root.geometry("500x460")
    root.resizable(False, False)

    tk.Label(root, text="DXF -> RAM Concept Suite", bg=BG, fg=TXT,
             font=("Segoe UI", 17, "bold")).pack(pady=(30, 2))
    tk.Label(root, text="Select a tool to open", bg=BG, fg=SEC,
             font=("Segoe UI", 10)).pack(pady=(0, 22))

    def make_card(title, desc, flag):
        f = tk.Frame(root, bg=CARD, cursor="hand2")
        f.pack(fill="x", padx=40, pady=9)
        lt = tk.Label(f, text=title, bg=CARD, fg=TXT,
                      font=("Segoe UI", 13, "bold"), anchor="w")
        lt.pack(fill="x", padx=18, pady=(12, 0))
        ld = tk.Label(f, text=desc, bg=CARD, fg=SEC,
                      font=("Segoe UI", 9), anchor="w")
        ld.pack(fill="x", padx=18, pady=(1, 12))
        widgets = (f, lt, ld)

        def on_click(_e=None):
            _spawn(flag)

        def on_enter(_e=None):
            for w in widgets:
                w.configure(bg=HOVER)

        def on_leave(_e=None):
            for w in widgets:
                w.configure(bg=CARD)

        for w in widgets:
            w.bind("<Button-1>", on_click)
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)

    make_card("Mesh Model Builder",
              "Build geometry / mesh model from DXF", TOOL_MESH)
    make_card("Area Load Importer",
              "Assign & import SDL / LL loads from DXF", TOOL_LOAD)
    make_card("Point / Line Load Importer",
              "Auto-read point & line loads from DXF", TOOL_PLOAD)

    tk.Label(root, text="PTX Engineering", bg=BG, fg="#4A5E7A",
             font=("Segoe UI", 8)).pack(side="bottom", pady=10)

    root.mainloop()


def main():
    if TOOL_MESH in sys.argv:
        run_mesh()
    elif TOOL_LOAD in sys.argv:
        run_load()
    elif TOOL_PLOAD in sys.argv:
        run_ploads()
    else:
        launcher()


if __name__ == "__main__":
    main()

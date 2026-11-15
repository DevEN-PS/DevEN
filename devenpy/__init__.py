"""
DevEN (devenpy)
Power system study engine · Made in India from Bengaluru.
GitHub: https://github.com/DevEN-PS/DevEN
"""

import sys
import os
import shutil
from pathlib import Path

# Add package directory to dll search path on Windows
_pkg_dir = Path(__file__).parent.resolve()
if hasattr(os, "add_dll_directory"):
    try:
        os.add_dll_directory(str(_pkg_dir))
    except Exception:
        pass

# Import all native symbols from compiled C-extension (.pyd)
try:
    from .devenpy import *
except ImportError:
    # Fallback to direct import if running uninstalled
    try:
        import devenpy
        from devenpy import *
    except ImportError as e:
        raise ImportError(f"Cannot load native DevEN C-extension from {_pkg_dir}: {e}")

# Import universal extended I/O ingestion parser layer (.m, .cdf, .xlsx, .aux, .def, .xml, etc.)
try:
    from . import deven_io
    from .deven_io import load_grid_file, DevenCircuit
except ImportError:
    pass

__version__ = "1.0.0"
__author__ = "DevEN Developers"


def get_docs_path() -> Path:
    """Return the absolute path to the local single-file HTML documentation."""
    docs_path = _pkg_dir / "docs" / "index.html"
    if docs_path.exists():
        return docs_path
    # Fallback to package root docs
    p = _pkg_dir.parent / "docs" / "index.html"
    if p.exists():
        return p
    return docs_path


def open_docs(port: int = 8080) -> None:
    """
    Launch a local zero-dependency web server and open the interactive documentation portal
    in the default web browser.
    """
    import http.server
    import socketserver
    import threading
    import webbrowser

    docs_file = get_docs_path()
    if not docs_file.exists():
        print(f"[DevEN Error] Documentation file not found at: {docs_file}")
        return

    docs_dir = str(docs_file.parent)

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=docs_dir, **kwargs)

        def log_message(self, format, *args):
            pass  # suppress request access logs

    # Find free port if requested port is in use
    for p in range(port, port + 50):
        try:
            httpd = socketserver.TCPServer(("127.0.0.1", p), QuietHandler)
            port = p
            break
        except OSError:
            continue
    else:
        print("[DevEN Error] Could not find an open local port.")
        return

    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    url = f"http://127.0.0.1:{port}/index.html"
    print("=" * 76)
    print(" DevEN Interactive Documentation Portal")
    print("=" * 76)
    print(f" Serving documentation locally at : {url}")
    print(" Opening your web browser automatically...")
    print(" Press Ctrl+C in terminal to stop.")
    print("=" * 76)

    webbrowser.open(url)

    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping DevEN documentation server.")
        httpd.shutdown()


def export_runners(destination: str = None) -> None:
    """
    Export the 6 standalone study runners (LFA, SCS, HA, 3PH, AF, BC), universal I/O parser,
    and benchmark grid cases to your current directory (default) or a specified target folder
    so you can edit and customize them directly.
    """
    if destination is None or str(destination).strip() in ("", "."):
        dst = Path.cwd().resolve()
    else:
        dst = Path(destination).resolve()

    dst.mkdir(parents=True, exist_ok=True)

    templates_dir = _pkg_dir / "templates"
    runners = ["run_lfa.py", "run_scs.py", "run_ha.py", "run_3ph.py", "run_af.py", "run_bc.py", "deven_io.py"]

    copied_files = []

    # Copy runner scripts & deven_io.py
    for r in runners:
        src = templates_dir / r
        if not src.exists():
            src = _pkg_dir.parent / "runners" / r
        if not src.exists() and r == "deven_io.py":
            src = _pkg_dir / "deven_io.py"
        if src.exists():
            shutil.copy2(src, dst / r)
            copied_files.append(r)

    # Copy cases folder
    src_cases = templates_dir / "cases"
    if not src_cases.exists():
        src_cases = _pkg_dir.parent / "examples" / "cases"
    if src_cases.exists():
        dst_cases = dst / "cases"
        dst_cases.mkdir(parents=True, exist_ok=True)
        for cf in src_cases.iterdir():
            if cf.is_file():
                shutil.copy2(cf, dst_cases / cf.name)
        copied_files.append(f"cases/ ({len(list(src_cases.iterdir()))} benchmark grids)")

    print("=" * 76)
    print(" DevEN Study Runners & Benchmark Grids Export")
    print("=" * 76)
    print(f" The study runner files and sample cases have been successfully pasted here:")
    print(f"   -> {dst}\n")
    print(" Exported Editable Files:")
    print("   * run_lfa.py  — Load Flow Analysis (NR, FDLF, DC, Gauss-Seidel)")
    print("   * run_scs.py  — Short Circuit Studies (IEC 60909:2016, ANSI C37)")
    print("   * run_ha.py   — Harmonic Analysis & Resonance Frequency Scan")
    print("   * run_3ph.py  — Three-Phase Unbalanced Power Flow")
    print("   * run_af.py   — Arc Flash Hazard Evaluation (IEEE 1584-2018)")
    print("   * run_bc.py   — Batch Contingency & N-1 Outage Screening")
    print("   * deven_io.py — Universal Multi-Format Grid Ingestion (MATPOWER, CDF, Excel, AUX, etc.)")
    print("   * cases/      — Benchmark grids (bench.rawx, case14.raw, bench2.raw, etc.)\n")
    print(" You can now directly edit and run any script in this folder:")
    print("   python run_lfa.py")
    print("   python run_scs.py")
    print("   python run_bc.py")
    print("=" * 76)

"""
run_3ph.py — DevEN Three-Phase Unbalanced Power Flow Runner
Full Phase-Coordinate (ABC+N) Unbalanced Load Flow Solver
Part of the DevEN Power System Study Engine (devenpy)
Made in India from Bengaluru.

USAGE:
    python run_3ph.py
"""

import sys
import os
import time
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG — Edit parameters for your study
#  ★ PSS/E RAWX (.rawx) [First Preference]
#  Recommended standard: Modern schema-validated XML/JSON format with high
#  numerical precision and structured definitions.
# ══════════════════════════════════════════════════════════════════════════════

INPUT_PATHS = [
    # r"cases/bench.rawx",           # Recommended: PSS/E RAWX format
    # r"cases/case14.raw",            # IEEE 14-bus benchmark
    # r"cases/bench2.raw",            # PSS/E benchmark
]

# ── 3-Phase Solver Configuration ──────────────────────────────────────────────
WIRE_CONFIG       = "4wire"           # "4wire" (a, b, c + neutral return) | "3wire" (Kron-reduced)
METHOD            = "fcim"            # "fcim" (Forward Current Injection) | "nr"
TOLERANCE         = 1e-5              # Mismatch tolerance in p.u.
MAX_ITER          = 30                # Maximum iteration limit
DEFAULT_UNBALANCE = 0.15              # Synthetic default unbalance ratio (15%)

# ── Power Quality & Unbalance Limits ──────────────────────────────────────────
CHECK_UNBALANCE   = True              # Verify compliance with IEEE / IEC unbalance limits
MAX_VUF_PCT       = 2.0               # Maximum allowable Voltage Unbalance Factor (V2/V1 %) under IEEE

# ══════════════════════════════════════════════════════════════════════════════
#  CUSTOM UNBALANCED PHASE LOADS (Edit directly in code)
# ══════════════════════════════════════════════════════════════════════════════
# Define explicit phase-by-phase load allocations (Phase A, B, C):
#
#   - FORMAT:
#       {"bus": <int>, "pa_mw": <float>, "qa_mvar": <float>,
#                      "pb_mw": <float>, "qb_mvar": <float>,
#                      "pc_mw": <float>, "qc_mvar": <float>, "name": <str>}
#
CUSTOM_PHASE_LOADS = [
    {"bus": 3, "pa_mw": 8.0,  "qa_mvar": 2.5, "pb_mw": 14.0, "qb_mvar": 4.5, "pc_mw": 6.0,  "qc_mvar": 1.8, "name": "Bus 3 Commercial Unbalance"},
    {"bus": 4, "pa_mw": 15.0, "qa_mvar": 5.0, "pb_mw": 10.0, "qb_mvar": 3.0, "pc_mw": 18.0, "qc_mvar": 6.0, "name": "Bus 4 Industrial Single-Phase Load"},
    {"bus": 5, "pa_mw": 5.0,  "qa_mvar": 1.5, "pb_mw": 7.5,  "qb_mvar": 2.2, "pc_mw": 5.0,  "qc_mvar": 1.5, "name": "Bus 5 Residential Phase Shift"},
]

# ── Reports ───────────────────────────────────────────────────────────────────
WRITE_CSV_REPORT  = True              # Export detailed phase voltage & flow table as CSV
OUTPUT_DIR        = None              # None = same folder as input file


# ══════════════════════════════════════════════════════════════════════════════
#  Implementation
# ══════════════════════════════════════════════════════════════════════════════

def _import_devenpy():
    try:
        import devenpy
        return devenpy
    except ImportError:
        for p in [Path(__file__).parent, Path(__file__).parent.parent]:
            if (p / "devenpy.pyd").exists():
                sys.path.insert(0, str(p))
                break
        import devenpy
        return devenpy


def _prompt_paths():
    if INPUT_PATHS:
        return [Path(p) for p in INPUT_PATHS]
    print("=" * 72)
    print(" DevEN Three-Phase Unbalanced Flow — Enter File Paths")
    print("=" * 72)
    print("Paste one path per line (.rawx / .raw / .deven / .m / .cdf / .xlsx).")
    print("Note: .rawx (PSS/E RAWX) is first preference for high-fidelity studies.\n")
    paths = []
    while True:
        try:
            line = input("  path > ").strip().strip('"').strip("'")
        except EOFError:
            break
        if not line:
            break
        p = Path(line)
        if not p.exists():
            print(f"  [not found] {p}")
            continue
        paths.append(p)
    return paths


def _load_case_file(devenpy, path):
    ext = path.suffix.lower()
    # 1. First Preference: RAWX
    if ext == ".rawx":
        case = devenpy.PyCase()
        case.load_rawx(str(path))
        return case
    # 2. Legacy RAW
    elif ext == ".raw":
        case = devenpy.PyCase()
        case.load_raw(str(path))
        return case
    # 3. Encrypted .deven database
    elif ext == ".deven":
        case = devenpy.PyCase()
        case.load_deven(str(path))
        return case
    # 4. Extended I/O formats (.m, .cdf, .xlsx, .aux, .def, .xml)
    elif ext in (".m", ".cdf", ".xlsx", ".xls", ".aux", ".def", ".xml"):
        try:
            import deven_io
            return deven_io.load_grid_file(str(path))
        except ImportError:
            try:
                import devenpy.deven_io as deven_io
                return deven_io.load_grid_file(str(path))
            except Exception as e:
                raise ImportError(f"Cannot load extended format {ext}: {e}")
    # 5. Default auto-detect
    else:
        case = devenpy.PyCase()
        case.load(str(path))
        return case


def main():
    devenpy = _import_devenpy()
    paths = _prompt_paths()
    if not paths:
        print("No paths specified. Exiting.")
        return

    print("\n" + "=" * 72)
    print(f" DevEN Three-Phase Unbalanced Power Flow — {len(paths)} file(s)")
    print(f" Conductor   : {WIRE_CONFIG.upper()} system")
    print(f" Solver      : {METHOD.upper()}")
    print(f" Tolerance   : {TOLERANCE:.1e} pu (Max iter: {MAX_ITER})")
    print(f" IEEE Limit  : Max VUF = {MAX_VUF_PCT} %")
    print("=" * 72)

    for i, path in enumerate(paths, 1):
        print(f"\n[{i}/{len(paths)}] {path.name}")
        try:
            case = _load_case_file(devenpy, path)

            t0 = time.perf_counter()
            res = case.solve_three_phase_lfa(
                wire=WIRE_CONFIG,
                method=METHOD,
                tol=TOLERANCE,
                max_iter=MAX_ITER,
                unbalance_ratio=DEFAULT_UNBALANCE,
            )
            dt = (time.perf_counter() - t0) * 1000.0

            conv = res.get("converged", True)
            iters = res.get("iterations", 1)
            print(f"  -> 3-Phase Unbalanced Flow {'CONVERGED' if conv else 'DID NOT CONVERGE'} in {iters} iters ({dt:.2f} ms)")

            bus_results = case.three_phase_bus_results() if hasattr(case, "three_phase_bus_results") else []
            if not bus_results and "buses" in res:
                bus_results = res["buses"]

            if bus_results:
                print(f"\n  Three-Phase Voltage Profile & Unbalance (Top 12):")
                print(f"  {'Bus':<6} {'Va (pu)':<12} {'Vb (pu)':<12} {'Vc (pu)':<12} {'VUF (%)':<10} {'Status':<14}")
                print("  " + "-" * 70)
                for b in bus_results[:12]:
                    bid = b.get("bus_id", 0)
                    va = b.get("va_mag", 1.0)
                    vb = b.get("vb_mag", 1.0)
                    vc = b.get("vc_mag", 1.0)
                    vuf = b.get("vuf_pct", 0.0)
                    status = "OK" if vuf <= MAX_VUF_PCT else "FAIL (Unbal)"
                    print(f"  {bid:<6} {va:<12.4f} {vb:<12.4f} {vc:<12.4f} {vuf:<10.2f} {status:<14}")

            out_dir = Path(OUTPUT_DIR) if OUTPUT_DIR else path.parent
            if WRITE_CSV_REPORT and bus_results:
                csv_p = out_dir / f"{path.stem}_3phase_results.csv"
                with open(csv_p, "w", encoding="utf-8") as f:
                    f.write("bus_id,va_mag_pu,va_ang_deg,vb_mag_pu,vb_ang_deg,vc_mag_pu,vc_ang_deg,vuf_pct,v0_mag,v1_mag,v2_mag\n")
                    for b in bus_results:
                        f.write(f"{b.get('bus_id',0)},{b.get('va_mag',1.0):.5f},{b.get('va_ang',0.0):.2f},{b.get('vb_mag',1.0):.5f},{b.get('vb_ang',-120.0):.2f},{b.get('vc_mag',1.0):.5f},{b.get('vc_ang',120.0):.2f},{b.get('vuf_pct',0.0):.3f},{b.get('v0_mag',0.0):.5f},{b.get('v1_mag',1.0):.5f},{b.get('v2_mag',0.0):.5f}\n")
                print(f"  -> Exported 3-Phase CSV: {csv_p}")

        except Exception as e:
            print(f"  -> ERROR: {e}")

    print("\n" + "=" * 72)
    print(" Three-Phase Flow Finished.")
    print("=" * 72)


if __name__ == "__main__":
    main()

"""
run_lfa.py — DevEN Load Flow Analysis (LFA) Runner
High-Performance AC & DC Power Flow Engine (NR, FDLF, DC, Gauss-Seidel)
Part of the DevEN Power System Study Engine (devenpy)
Made in India from Bengaluru.

USAGE:
    python run_lfa.py
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
    # r"cases/case14.raw",            # IEEE 14-bus test case
    # r"cases/bench2.raw",            # PSS/E benchmark case
]

# ── Solver Parameters ─────────────────────────────────────────────────────────
METHOD            = "nr"             # "nr" (Newton-Raphson) | "fdlf" (Fast Decoupled)
                                      # "dc" (DC Linear)     | "gs" (Gauss-Seidel)
                                      # "dishonest" (Constant Jacobian Newton)
TOLERANCE         = 0.0001            # Convergence mismatch tolerance (p.u.)
MAX_ITER          = 50                # Maximum iteration limit
ENFORCE_Q_LIMITS  = True              # Enforce generator reactive capability limits (PV -> PQ)
SHOW_Q_LIMITS     = True              # Display [DevEN Q-LIMIT] lines during solve
WORK_WITH_SLACK   = True              # True: strict slack generator | False: distributed slack
FLAT_START        = False             # True: initialize V = 1.0 pu, angle = 0.0 deg
ISLAND_POLICY     = "auto_isolate"   # "auto_isolate" (prune & solve) | "skip" (abort on split)

# ── Voltage Limits Checking ───────────────────────────────────────────────────
CHECK_VOLTAGE     = True              # Flag overvoltage and undervoltage buses
V_MIN_PU          = 0.95              # Continuous operating lower voltage limit
V_MAX_PU          = 1.05              # Continuous operating upper voltage limit

# ── Custom In-Memory Modifications (Edit directly in code) ────────────────────
# Customize generator setpoints, loads, or branch statuses before solving:

CUSTOM_GEN_EDITS = [
    # Example: {"bus": 2, "id": "1", "pg": 45.0, "vs": 1.04, "qmax": 50.0, "qmin": -20.0},
]

CUSTOM_LOAD_EDITS = [
    # Example: {"bus": 3, "id": "1", "pl": 100.0, "ql": 35.0},
]

CUSTOM_BRANCH_EDITS = [
    # Example: {"from_bus": 1, "to_bus": 2, "ckt": "1", "status": 1},
]

# ── Reports & Exports ─────────────────────────────────────────────────────────
WRITE_OUT_REPORT  = True              # Standard columnar PSS/E-style report (.out)
WRITE_KCL_REPORT  = True              # Bus-by-bus active/reactive energy balance (.kcl)
WRITE_CSV_REPORT  = True              # Tabular CSV results (voltages & branch flows)
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
    print(" DevEN Load Flow Runner — Enter File Paths")
    print("=" * 72)
    print("Paste one path per line (.rawx / .raw / .deven / .m / .cdf / .xlsx).")
    print("Note: .rawx (PSS/E RAWX) is strongly recommended for best fidelity.\n")
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
            return deven_io.load_grid_file(str(path), work_with_slack=WORK_WITH_SLACK)
        except ImportError:
            try:
                import devenpy.deven_io as deven_io
                return deven_io.load_grid_file(str(path), work_with_slack=WORK_WITH_SLACK)
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

    active_reports = []
    if WRITE_OUT_REPORT: active_reports.append(".out (Columnar)")
    if WRITE_KCL_REPORT: active_reports.append(".kcl (Balance)")
    if WRITE_CSV_REPORT: active_reports.append(".csv (Bus & Flows)")
    rep_str = ", ".join(active_reports) if active_reports else "None"

    print("\n" + "=" * 72)
    print(f" DevEN Load Flow Runner — {len(paths)} file(s)")
    print(f" Method     : {METHOD.upper()}")
    print(f" Tolerance  : {TOLERANCE} pu (Max iter: {MAX_ITER})")
    print(f" Q limits   : {'enforced' if ENFORCE_Q_LIMITS else 'ignored'}")
    print(f" Islanding  : {ISLAND_POLICY}")
    print(f" Reports    : {rep_str}")
    print("=" * 72)

    for i, path in enumerate(paths, 1):
        print(f"\n[{i}/{len(paths)}] {path.name}")
        try:
            case = _load_case_file(devenpy, path)

            # Apply custom edits if defined
            for g in CUSTOM_GEN_EDITS:
                case.chng_gen(g["bus"], g.get("id", ""), pg=g.get("pg"), qg=g.get("qg"), vs=g.get("vs"),
                              status=g.get("status"), qmax=g.get("qmax"), qmin=g.get("qmin"))
            for l in CUSTOM_LOAD_EDITS:
                case.chng_load(l["bus"], l.get("id", ""), pl=l.get("pl"), ql=l.get("ql"), status=l.get("status"))
            for b in CUSTOM_BRANCH_EDITS:
                case.chng_brn(b["from_bus"], b["to_bus"], b.get("ckt", ""), status=b.get("status"),
                              r=b.get("r"), x=b.get("x"), b=b.get("b"))

            t0 = time.perf_counter()
            status = case.solve_load_flow(
                method=METHOD,
                tol=TOLERANCE,
                max_iter=MAX_ITER,
                work_with_slack=WORK_WITH_SLACK,
                island_policy=ISLAND_POLICY,
                enforce_q_limits=ENFORCE_Q_LIMITS,
                show_q_limits=SHOW_Q_LIMITS,
                flat_start=FLAT_START,
            )
            dt = (time.perf_counter() - t0) * 1000.0

            if status.get("converged", False):
                print(f"  -> Solution CONVERGED in {status['iterations']} iterations ({dt:.2f} ms)")
                print(f"     Max residual: |dP| = {status.get('max_dp', 0.0):.2e}, |dQ| = {status.get('max_dq', 0.0):.2e}")
            else:
                print(f"  -> Solution DID NOT CONVERGE after {status['iterations']} iterations ({dt:.2f} ms)")

            # Voltage limits check
            if CHECK_VOLTAGE:
                vm = case.bus_data_array("VM")
                v_low = sum(1 for v in vm if v < V_MIN_PU)
                v_high = sum(1 for v in vm if v > V_MAX_PU)
                if v_low > 0 or v_high > 0:
                    print(f"  -> [VOLTAGE LIMITS] {v_low} bus(es) < {V_MIN_PU} pu | {v_high} bus(es) > {V_MAX_PU} pu")
                else:
                    print(f"  -> [VOLTAGE LIMITS] All {len(vm)} buses within normal bandwidth [{V_MIN_PU} - {V_MAX_PU} pu]")

            out_dir = Path(OUTPUT_DIR) if OUTPUT_DIR else path.parent

            # Reports
            if WRITE_OUT_REPORT:
                try:
                    out_p = out_dir / f"{path.stem}.out"
                    case.write_out(str(out_p))
                    print(f"  -> Exported .out : {out_p}")
                except Exception as e_out:
                    print(f"  -> [WARNING] .out export failed: {e_out}")

            if WRITE_KCL_REPORT:
                try:
                    kcl_p = out_dir / f"{path.stem}.kcl"
                    kcl_text = case.kcl_report()
                    with open(kcl_p, "w", encoding="utf-8") as f:
                        f.write(kcl_text)
                    print(f"  -> Exported .kcl : {kcl_p}")
                except Exception as e_kcl:
                    print(f"  -> [WARNING] .kcl export failed: {e_kcl}")

            if WRITE_CSV_REPORT:
                try:
                    rep = case.report_dict()
                    csv_buses = out_dir / f"{path.stem}_lfa_buses.csv"
                    with open(csv_buses, "w", encoding="utf-8") as f:
                        f.write("bus_id,bus_name,base_kv,v_mag_pu,v_ang_deg,p_gen_mw,q_gen_mvar,p_load_mw,q_load_mvar\n")
                        for b in rep.get("bus_results", []):
                            f.write(f"{b['bus_number']},{b['name']},{b['base_kv']},{b['v_mag']:.5f},{b['v_angle_deg']:.3f},{b.get('p_gen_mw', 0.0):.2f},{b.get('q_gen_mvar', 0.0):.2f},{b.get('p_load_mw', 0.0):.2f},{b.get('q_load_mvar', 0.0):.2f}\n")
                    print(f"  -> Exported .csv (Buses)    : {csv_buses}")

                    if rep.get("branch_flows"):
                        csv_branches = out_dir / f"{path.stem}_lfa_branches.csv"
                        with open(csv_branches, "w", encoding="utf-8") as f:
                            f.write("from_bus,to_bus,ckt,type,p_fwd_mw,q_fwd_mvar,p_rev_mw,q_rev_mvar,losses_mw,loading_pct\n")
                            for br in rep["branch_flows"]:
                                f.write(f"{br['from_bus']},{br['to_bus']},{br.get('ckt','1')},{br.get('type','line')},{br.get('p_fwd_mw',0.0):.2f},{br.get('q_fwd_mvar',0.0):.2f},{br.get('p_rev_mw',0.0):.2f},{br.get('q_rev_mvar',0.0):.2f},{br.get('losses_mw',0.0):.3f},{br.get('loading_pct',0.0):.1f}\n")
                        print(f"  -> Exported .csv (Branches) : {csv_branches}")
                except Exception as e_csv:
                    print(f"  -> [WARNING] CSV export failed: {e_csv}")

        except Exception as e:
            print(f"  -> ERROR: {e}")

    print("\n" + "=" * 72)
    print(" LFA Finished.")
    print("=" * 72)


if __name__ == "__main__":
    main()

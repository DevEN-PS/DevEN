"""
run_bc.py — DevEN Batch Contingency & N-1 Outage Screening Runner
High-Speed Parallel Outage Simulation & Security Screening
Part of the DevEN Power System Study Engine (devenpy)
Made in India from Bengaluru.

USAGE:
    python run_bc.py
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

# ── Contingency Mode ──────────────────────────────────────────────────────────
# "custom" : Run only user-defined contingencies in CUSTOM_CONTINGENCIES below (default)
# "auto"   : Screen every AC line, transformer, and generator in the network (Full N-1)
# "both"   : Run custom list first, then perform full automatic N-1
CONTINGENCY_MODE  = "custom"          # "custom" | "auto" | "both"

# ── Solver Parameters ─────────────────────────────────────────────────────────
METHOD            = "fdlf"            # "fdlf" (Fast Decoupled - ultra-fast) | "nr" (Newton-Raphson)
TOLERANCE         = 0.001             # Mismatch tolerance in p.u. (0.001 = 0.1 MVA)
MAX_ITER          = 30                # Maximum iteration limit per contingency
ISLAND_POLICY     = "auto_isolate"    # "auto_isolate" (prune & solve) | "skip" (abort if island forms)

# ── Voltage Screening Limits ──────────────────────────────────────────────────
V_MIN_PU          = 0.90              # Lower voltage emergency threshold (pu)
V_MAX_PU          = 1.10              # Upper voltage emergency threshold (pu)

# ══════════════════════════════════════════════════════════════════════════════
#  CUSTOM CONTINGENCIES (Edit directly inside this block)
# ══════════════════════════════════════════════════════════════════════════════
# Define your lines, transformers, and generators to trip below:
#
#   - TRANSMISSION LINES:
#       {"type": "line", "from_bus": <int>, "to_bus": <int>, "ckt": <str>, "name": <str>}
#
#   - POWER TRANSFORMERS:
#       {"type": "trf",  "from_bus": <int>, "to_bus": <int>, "ckt": <str>, "name": <str>}
#
#   - GENERATOR TRIPS:
#       {"type": "gen",  "bus": <int>, "id": <str>, "name": <str>}
#
CUSTOM_CONTINGENCIES = [
    # ── Transmission Lines to Trip: (from_bus, to_bus, ckt)
    {"type": "line", "from_bus": 1, "to_bus": 2, "ckt": "1", "name": "Trip Line 1-2"},
    {"type": "line", "from_bus": 2, "to_bus": 3, "ckt": "1", "name": "Trip Line 2-3"},
    {"type": "line", "from_bus": 1, "to_bus": 5, "ckt": "1", "name": "Trip Line 1-5"},
    {"type": "line", "from_bus": 4, "to_bus": 5, "ckt": "1", "name": "Trip Line 4-5"},

    # ── Transformers to Trip: (from_bus, to_bus, ckt)
    {"type": "trf",  "from_bus": 4, "to_bus": 7, "ckt": "1", "name": "Trip Trf 4-7"},
    {"type": "trf",  "from_bus": 5, "to_bus": 6, "ckt": "1", "name": "Trip Trf 5-6"},

    # ── Generators to Trip: (bus number, id)
    {"type": "gen",  "bus": 2, "id": "1", "name": "Trip Gen Bus 2 (Unit 1)"},
    {"type": "gen",  "bus": 3, "id": "1", "name": "Trip Gen Bus 3 (Unit 1)"},
    {"type": "gen",  "bus": 6, "id": "1", "name": "Trip Gen Bus 6 (Unit 1)"},
]

# ── Reports ───────────────────────────────────────────────────────────────────
WRITE_CSV_REPORT  = True              # Export contingency ranking CSV
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
    print(" DevEN Batch Contingency (N-1) — Enter File Paths")
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


def _solve_contingency(base_case, ctg):
    c = base_case.copy()
    ctype = ctg.get("type", "").lower()
    name = ctg.get("name", "")

    if ctype in ("line", "trf", "branch"):
        f = ctg["from_bus"]
        t = ctg["to_bus"]
        ckt = str(ctg.get("ckt", "1"))
        c.chng_brn(f, t, ckt, status=0)
        label = name or f"Outage {ctype.upper()} {f}-{t} ({ckt})"
    elif ctype == "gen":
        b = ctg["bus"]
        gid = str(ctg.get("id", "1"))
        c.chng_gen(b, gid, status=0)
        label = name or f"Trip Gen Bus {b} ({gid})"
    else:
        label = name or "Base Case"

    t0 = time.perf_counter()
    st = c.solve_load_flow(
        method=METHOD,
        tol=TOLERANCE,
        max_iter=MAX_ITER,
        island_policy=ISLAND_POLICY,
        show_q_limits=False,
    )
    dt = (time.perf_counter() - t0) * 1000.0

    v_viol_count = 0
    min_v = 1.0
    max_v = 1.0
    if st.get("converged", False):
        try:
            vm = c.bus_data_array("VM")
            if vm:
                min_v = min(vm)
                max_v = max(vm)
                v_viol_count = sum(1 for v in vm if v < V_MIN_PU or v > V_MAX_PU)
        except Exception:
            pass

    return {
        "name": label,
        "type": ctype,
        "converged": st.get("converged", False),
        "iterations": st.get("iterations", 0),
        "max_dp": st.get("max_dp", 0.0),
        "max_dq": st.get("max_dq", 0.0),
        "time_ms": dt,
        "v_viols": v_viol_count,
        "min_v": min_v,
        "max_v": max_v,
    }


def main():
    devenpy = _import_devenpy()
    paths = _prompt_paths()
    if not paths:
        print("No paths specified. Exiting.")
        return

    print("\n" + "=" * 72)
    print(f" DevEN Batch Contingency (N-1) Runner — {len(paths)} file(s)")
    print(f" Mode        : {CONTINGENCY_MODE.upper()}")
    print(f" Method      : {METHOD.upper()}")
    print(f" Tolerance   : {TOLERANCE} pu (Max iter: {MAX_ITER})")
    print(f" Islanding   : {ISLAND_POLICY}")
    print(f" Voltage Band: {V_MIN_PU} - {V_MAX_PU} pu")
    print("=" * 72)

    for i, path in enumerate(paths, 1):
        print(f"\n[{i}/{len(paths)}] {path.name}")
        try:
            case = _load_case_file(devenpy, path)

            # 1. Base case solve
            base_st = case.solve_load_flow(method="nr", tol=TOLERANCE, island_policy=ISLAND_POLICY, show_q_limits=False)
            if not base_st.get("converged", False):
                print("  [ERROR] Base case did not converge! Skipping N-1 screening.")
                continue

            print("  -> Base case solved successfully.")

            # Build list of contingencies
            ctg_list = []
            if CONTINGENCY_MODE in ("custom", "both"):
                ctg_list.extend(CUSTOM_CONTINGENCIES)

            if CONTINGENCY_MODE in ("auto", "both"):
                rep = case.report_dict()
                # Auto branches
                for br in rep.get("branch_flows", []):
                    f = br.get("from_bus", 0)
                    t = br.get("to_bus", 0)
                    ckt = br.get("ckt", "1")
                    btype = br.get("type", "line")
                    ctg_list.append({
                        "type": btype,
                        "from_bus": f,
                        "to_bus": t,
                        "ckt": ckt,
                        "name": f"N1_{btype.upper()}_{f}_{t}_{ckt}"
                    })
                # Auto generators
                for g in rep.get("gen_results", []):
                    b = g.get("bus_number", 0)
                    gid = g.get("id", "1")
                    ctg_list.append({
                        "type": "gen",
                        "bus": b,
                        "id": gid,
                        "name": f"N1_GEN_{b}_{gid}"
                    })

            print(f"  -> Screening {len(ctg_list)} contingencies...")
            print(f"\n  {'Contingency Name':<32} {'Status':<10} {'Iter':<6} {'Max |dP|':<12} {'V_min':<8} {'V_max':<8} {'V-Viol':<6} {'Time':<8}")
            print("  " + "-" * 92)

            results = []
            t_total_start = time.perf_counter()
            for ctg in ctg_list:
                res = _solve_contingency(case, ctg)
                results.append(res)
                st_str = "CONVERGED" if res["converged"] else "DIVERGED"
                print(f"  {res['name'][:30]:<32} {st_str:<10} {res['iterations']:<6} {res['max_dp']:<12.2e} {res['min_v']:<8.4f} {res['max_v']:<8.4f} {res['v_viols']:<6} {res['time_ms']:<6.1f}ms")

            total_ms = (time.perf_counter() - t_total_start) * 1000.0
            n_conv = sum(1 for r in results if r["converged"])
            n_viols = sum(1 for r in results if r["v_viols"] > 0)

            print("  " + "-" * 92)
            print(f"  Total: {len(results)} contingencies solved in {total_ms:.1f} ms ({total_ms/max(1,len(results)):.2f} ms/contingency)")
            print(f"  Converged : {n_conv} / {len(results)} ({n_conv/max(1,len(results))*100:.1f}%)")
            print(f"  Violations: {n_viols} scenario(s) caused voltage bandwidth violations")

            out_dir = Path(OUTPUT_DIR) if OUTPUT_DIR else path.parent
            if WRITE_CSV_REPORT:
                csv_p = out_dir / f"{path.stem}_contingency_results.csv"
                with open(csv_p, "w", encoding="utf-8") as f:
                    f.write("contingency_name,type,converged,iterations,max_dp,max_dq,min_v_pu,max_v_pu,voltage_violations,solve_time_ms\n")
                    for r in results:
                        f.write(f"\"{r['name']}\",{r['type']},{r['converged']},{r['iterations']},{r['max_dp']:.6e},{r['max_dq']:.6e},{r['min_v']:.5f},{r['max_v']:.5f},{r['v_viols']},{r['time_ms']:.2f}\n")
                print(f"  -> Exported CSV: {csv_p}")

        except Exception as e:
            print(f"  -> ERROR: {e}")

    print("\n" + "=" * 72)
    print(" Batch Contingency Finished.")
    print("=" * 72)


if __name__ == "__main__":
    main()

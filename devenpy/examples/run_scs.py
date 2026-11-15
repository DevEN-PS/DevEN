"""
run_scs.py — DevEN Short Circuit Studies (SCS) Runner
Standards: IEC 60909:2016 / ANSI/IEEE C37.010 / C37.5
Part of the DevEN Power System Study Engine (devenpy)
Made in India from Bengaluru.

USAGE:
    python run_scs.py
"""

import sys
import os
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
    # r"cases/iec60909_testnetwork_50Hz.raw",
]

# ── SCS Mode ──────────────────────────────────────────────────────────────────
# "custom" : Run list of custom fault scenarios defined in CUSTOM_FAULTS below
# "single" : Detailed single-bus fault with branch & gen fault contributions
# "scan"   : Full system-wide fault calculation across all buses (< 1 ms)
STUDY_MODE        = "custom"          # "custom" | "single" | "scan"

# ── Default Single-Bus Settings (Used when STUDY_MODE == "single") ───────────
FAULT_BUS         = 1                 # Bus number where fault occurs
FAULT_TYPE        = "3phase"          # "3phase" | "slg" | "ll" | "dlg"
METHOD            = "iec"             # "iec" (IEC 60909:2016) | "ansi" (ANSI C37.010)
C_FACTOR          = 1.10              # Voltage factor c (1.10 max fault / 1.00 min fault)
R_FAULT           = 0.0               # Fault resistance Rf in ohms
X_FAULT           = 0.0               # Fault reactance Xf in ohms
BREAKER_CHECK     = True              # Check breaker interrupting duty & safety margin
BREAKER_MVA       = 2000.0            # Rated circuit breaker interrupting MVA at fault bus

# ══════════════════════════════════════════════════════════════════════════════
#  CUSTOM FAULTS (Edit directly in code)
# ══════════════════════════════════════════════════════════════════════════════
# Define multiple fault scenarios across different buses, fault types, methods,
# fault impedances, and breaker ratings:
#
#   - FAULT TYPES : "3phase" (three-phase bolted), "slg" (single line-to-ground),
#                   "ll" (line-to-line), "dlg" (double line-to-ground)
#   - METHODS     : "iec" (IEC 60909:2016) | "ansi" (ANSI C37.010 / C37.5)
#   - RF / XF     : Fault impedance in ohms (0.0 = bolted fault, >0 = arc/impedance)
#   - CB_MVA      : Rated circuit breaker interrupting capacity in MVA
#
CUSTOM_FAULTS = [
    {"bus": 1, "type": "3phase", "method": "iec",  "rf": 0.0, "xf": 0.0, "cb_mva": 2000.0, "name": "Bus 1 - 3PH IEC Bolted Fault"},
    {"bus": 1, "type": "slg",    "method": "iec",  "rf": 0.0, "xf": 0.0, "cb_mva": 2000.0, "name": "Bus 1 - SLG Earth Fault"},
    {"bus": 2, "type": "3phase", "method": "ansi", "rf": 0.0, "xf": 0.0, "cb_mva": 1500.0, "name": "Bus 2 - 3PH ANSI Fault"},
    {"bus": 3, "type": "ll",     "method": "iec",  "rf": 1.5, "xf": 0.0, "cb_mva": 1200.0, "name": "Bus 3 - Line-to-Line Arc Fault"},
    {"bus": 4, "type": "dlg",    "method": "iec",  "rf": 0.5, "xf": 0.2, "cb_mva": 1000.0, "name": "Bus 4 - Double Line-to-Ground"},
]

# ── In-Memory Sequence & Grounding Overrides (Optional) ──────────────────────
# Modify generator or transformer zero-sequence impedances before fault calculation:
CUSTOM_GEN_SCS = [
    # {"bus": 1, "id": "1", "xd_sub": 0.18, "x0": 0.04, "conn": "G", "gnd_r": 0.0, "gnd_x": 0.0},
]
CUSTOM_BRN_SCS = [
    # {"from_bus": 1, "to_bus": 2, "ckt": "1", "x0": 0.15, "from_conn": "G", "to_conn": "D"},
]

# ── Reports ───────────────────────────────────────────────────────────────────
WRITE_CSV_REPORT  = True              # Export scan/results table as CSV
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
    print(" DevEN Short Circuit Studies (SCS) — Enter File Paths")
    print("=" * 72)
    print("Paste one path per line (.rawx / .raw / .deven / .m / .cdf / .xlsx).")
    print("Note: .rawx (PSS/E RAWX) is the recommended first preference.\n")
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
    if ext == ".rawx":
        case = devenpy.PyCase()
        case.load_rawx(str(path))
        return case
    elif ext == ".raw":
        case = devenpy.PyCase()
        case.load_raw(str(path))
        return case
    elif ext == ".deven":
        case = devenpy.PyCase()
        case.load_deven(str(path))
        return case
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
    else:
        case = devenpy.PyCase()
        case.load(str(path))
        return case


def _run_single_fault(case, bus, ftype, method, rf, xf, cb_mva, name=""):
    if cb_mva:
        case.scs_chng_bus(bus, cb_mva=cb_mva)
    res = case.solve_short_circuit(
        fault_bus=bus,
        fault_type=ftype,
        method=method,
        r_f=rf,
        x_f=xf,
        c_factor=C_FACTOR,
        breaker_check=BREAKER_CHECK,
    )
    v_base = res.get("v_base_kv", 0.0)
    ik = res.get("ik_ka", 0.0)
    ip = res.get("ip_ka", 0.0)
    ib = res.get("ib_ka", 0.0)
    sk = res.get("sk_mva", 0.0)
    xr = res.get("xr_ratio", 0.0)

    duty_str = "N/A"
    if cb_mva:
        try:
            bd = case.scs_breaker_duty(bus)
            duty_str = f"{bd.get('duty_pct', 0.0):.1f}% [{bd.get('status', 'OK')}]"
        except Exception:
            pass

    return {
        "name": name or f"Bus {bus} {ftype.upper()}",
        "bus": bus,
        "type": ftype,
        "method": method,
        "v_base_kv": v_base,
        "ik_ka": ik,
        "ip_ka": ip,
        "ib_ka": ib,
        "sk_mva": sk,
        "xr_ratio": xr,
        "duty": duty_str,
        "raw": res,
    }


def main():
    devenpy = _import_devenpy()
    paths = _prompt_paths()
    if not paths:
        print("No paths specified. Exiting.")
        return

    print("\n" + "=" * 72)
    print(f" DevEN Short Circuit Study Runner — {len(paths)} file(s)")
    print(f" Mode       : {STUDY_MODE.upper()}")
    print("=" * 72)

    for i, path in enumerate(paths, 1):
        print(f"\n[{i}/{len(paths)}] {path.name}")
        try:
            case = _load_case_file(devenpy, path)

            # Apply generator/branch SCS parameter customizations
            for g in CUSTOM_GEN_SCS:
                case.scs_chng_gen(g["bus"], g.get("id", ""), xd_sub=g.get("xd_sub"), x0=g.get("x0"),
                                  conn=g.get("conn"), gnd_r=g.get("gnd_r"), gnd_x=g.get("gnd_x"))
            for b in CUSTOM_BRN_SCS:
                case.scs_chng_brn(b["from_bus"], b["to_bus"], b.get("ckt", ""), x0=b.get("x0"), r0=b.get("r0"),
                                  from_conn=b.get("from_conn"), to_conn=b.get("to_conn"))

            out_dir = Path(OUTPUT_DIR) if OUTPUT_DIR else path.parent

            if STUDY_MODE == "scan":
                scan_res = case.solve_short_circuit_scan(
                    method=METHOD,
                    c_factor=C_FACTOR,
                )
                print(f"  -> System scan completed: {len(scan_res)} buses evaluated.")
                print(f"  {'Bus':<8} {'Name':<14} {'Base kV':<10} {'3PH Ik\" (kA)':<14} {'SLG Ik\" (kA)':<14} {'X/R':<8}")
                print("  " + "-" * 68)
                for r in scan_res[:15]:
                    name = r.get("bus_name", f"Bus_{r['bus_id']}")
                    bkv = r.get("base_kv", 0.0)
                    print(f"  {r['bus_id']:<8} {name:<14} {bkv:<10.1f} {r['ik_3ph_ka']:<14.3f} {r['ik_slg_ka']:<14.3f} {r['xr_ratio']:<8.2f}")
                if len(scan_res) > 15:
                    print(f"  ... [{len(scan_res) - 15} more buses in report]")

                if WRITE_CSV_REPORT:
                    csv_p = out_dir / f"{path.stem}_scs_scan.csv"
                    with open(csv_p, "w", encoding="utf-8") as f:
                        f.write("bus_id,bus_name,base_kv,ik_3ph_ka,sk_3ph_mva,ip_3ph_ka,ik_slg_ka,xr_ratio\n")
                        for r in scan_res:
                            f.write(f"{r['bus_id']},{r.get('bus_name','')},{r.get('base_kv',0.0)},{r['ik_3ph_ka']:.4f},{r.get('sk_3ph_mva',0.0):.2f},{r.get('ip_3ph_ka',0.0):.4f},{r['ik_slg_ka']:.4f},{r['xr_ratio']:.3f}\n")
                    print(f"  -> Exported CSV: {csv_p}")

            elif STUDY_MODE == "custom":
                print(f"  -> Executing {len(CUSTOM_FAULTS)} custom fault scenarios:")
                print(f"  {'Scenario Name':<32} {'Bus':<6} {'Type':<8} {'Method':<7} {'Ik\" (kA)':<10} {'ip (kA)':<10} {'Sk\" (MVA)':<12} {'X/R':<6}")
                print("  " + "-" * 95)
                results = []
                for sc in CUSTOM_FAULTS:
                    r = _run_single_fault(case, sc["bus"], sc.get("type", "3phase"), sc.get("method", "iec"),
                                          sc.get("rf", 0.0), sc.get("xf", 0.0), sc.get("cb_mva"), sc.get("name", ""))
                    results.append(r)
                    print(f"  {r['name'][:30]:<32} {r['bus']:<6} {r['type'].upper():<8} {r['method'].upper():<7} {r['ik_ka']:<10.3f} {r['ip_ka']:<10.3f} {r['sk_mva']:<12.1f} {r['xr_ratio']:<6.2f}")

                if WRITE_CSV_REPORT:
                    csv_p = out_dir / f"{path.stem}_scs_custom_faults.csv"
                    with open(csv_p, "w", encoding="utf-8") as f:
                        f.write("scenario_name,bus,fault_type,method,base_kv,ik_ka,ip_ka,ib_ka,sk_mva,xr_ratio,cb_duty\n")
                        for r in results:
                            f.write(f"\"{r['name']}\",{r['bus']},{r['type']},{r['method']},{r['v_base_kv']:.1f},{r['ik_ka']:.4f},{r['ip_ka']:.4f},{r['ib_ka']:.4f},{r['sk_mva']:.2f},{r['xr_ratio']:.3f},\"{r['duty']}\"\n")
                    print(f"  -> Exported CSV: {csv_p}")

            else:  # single
                r = _run_single_fault(case, FAULT_BUS, FAULT_TYPE, METHOD, R_FAULT, X_FAULT, BREAKER_MVA, f"Bus {FAULT_BUS} Fault")
                print(f"  -> Fault at Bus {FAULT_BUS} ({FAULT_TYPE.upper()} - {METHOD.upper()}):")
                print(f"     Base Voltage             : {r['v_base_kv']:.1f} kV")
                print(f"     Initial Symmetrical Ik\" : {r['ik_ka']:.3f} kA")
                print(f"     Short-Circuit Power Sk\" : {r['sk_mva']:.1f} MVA")
                print(f"     Peak Asymmetrical ip   : {r['ip_ka']:.3f} kA")
                print(f"     Symmetrical Breaking Ib : {r['ib_ka']:.3f} kA")
                print(f"     Equivalent X/R Ratio   : {r['xr_ratio']:.2f}")
                print(f"     Breaker Duty           : {r['duty']}")

                # Generator fault contributions
                gens_at_bus = case.get_gens_at_bus(FAULT_BUS)
                if gens_at_bus:
                    print("\n     Local Generator Contributions:")
                    for gid in gens_at_bus:
                        try:
                            gc = case.scs_gen_contrib(FAULT_BUS, gid)
                            print(f"       * Gen {gid}: Ia = {gc['ia_ka']:.3f} kA, Ib = {gc['ib_ka']:.3f} kA, Ic = {gc['ic_ka']:.3f} kA (Max = {gc['i_max_ka']:.3f} kA)")
                        except Exception:
                            pass

                # Connected branch fault flows
                brns = case.get_branches_at_bus(FAULT_BUS)
                if brns:
                    print("\n     Branch Fault Inflows:")
                    for f_bus, t_bus, ckt in brns:
                        try:
                            bf = case.scs_brn_flow(f_bus, t_bus, ckt)
                            print(f"       * Branch {f_bus}->{t_bus} (ckt {ckt}): Max Current = {bf['i_max_ka']:.3f} kA")
                        except Exception:
                            pass

        except Exception as e:
            print(f"  -> ERROR: {e}")

    print("\n" + "=" * 72)
    print(" SCS Finished.")
    print("=" * 72)


if __name__ == "__main__":
    main()

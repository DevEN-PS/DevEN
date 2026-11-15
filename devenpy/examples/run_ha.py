"""
run_ha.py — DevEN Harmonic Analysis & Resonance Frequency Scan Runner
Standards: IEEE 519-2022 / IEC 61000-4-7
Part of the DevEN Power System Study Engine (devenpy)
Made in India from Bengaluru.

USAGE:
    python run_ha.py
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
    # r"cases/case14.raw",            # IEEE 14-bus benchmark
    # r"cases/bench2.raw",            # PSS/E benchmark
]

# ── Study Selection ───────────────────────────────────────────────────────────
# "scan"      : Frequency scan impedance profile Z(f) and parallel resonance detection
# "harmonics" : Multi-order harmonic penetration, bus THD, and IEEE 519 compliance
# "both"      : Execute both frequency scan and harmonic penetration
STUDY_TYPE        = "both"            # "scan" | "harmonics" | "both"

# ── Frequency Scan Parameters ─────────────────────────────────────────────────
F_START_HZ        = 50.0              # Starting frequency (Hz)
F_END_HZ          = 2500.0            # Ending frequency (Hz) (2500 Hz = 50th harmonic @ 50 Hz)
F_STEP_HZ         = 5.0               # Frequency step resolution (Hz)
TARGET_BUSES      = None              # List of buses to scan [e.g. 1, 2, 3] or None for all
INJECT_AMP        = 1.0               # Test current injection magnitude (Amps)

# ── Harmonic Penetration & IEEE 519 Parameters ────────────────────────────────
SOLVER            = "cim"             # "cim" (Current Injection Method) | "coupled"
MAX_ORDER         = 50                # Maximum harmonic order to analyze (e.g. 50)
SKIN_EFFECT       = True              # Model frequency-dependent resistance R(h) = R0 * sqrt(h)
PCC_BUS           = 1                 # Point of Common Coupling (PCC) bus number
PCC_KV            = 138.0             # Nominal voltage at PCC (kV)
ISC_IL_RATIO      = 35.0              # Short circuit to load current ratio (Isc / IL)
THD_V_LIMIT_PCT   = 5.0               # Maximum allowable bus voltage THD (%) under IEEE 519

# ══════════════════════════════════════════════════════════════════════════════
#  CUSTOM HARMONIC SOURCES & MITIGATION FILTERS (Edit directly in code)
# ══════════════════════════════════════════════════════════════════════════════
# Define harmonic current-injecting non-linear loads and mitigation filters:
#
#   - HARMONIC SOURCES:
#       {"bus": <int>, "name": <str>, "phase": "3PH", "i_fund_amps": <float>,
#        "ang_deg": <float>, "spectrum_type": "6pulse" | "12pulse" | "pwm" | "custom"}
#
#   - HARMONIC FILTERS:
#       {"bus": <int>, "name": <str>, "filter_type": "single_tuned" | "high_pass",
#        "tuning_order": <float>, "q_factor": <float>, "mvar_rating": <float>, "status": 1}
#
CUSTOM_HARMONIC_SOURCES = [
    {"bus": 3, "name": "VFD Drive 1 (6-Pulse)", "phase": "3PH", "i_fund_amps": 60.0, "ang_deg": 0.0, "spectrum_type": "6pulse"},
    {"bus": 4, "name": "Industrial Rectifier",  "phase": "3PH", "i_fund_amps": 45.0, "ang_deg": 30.0, "spectrum_type": "6pulse"},
    {"bus": 5, "name": "Arc Furnace / UPS",     "phase": "3PH", "i_fund_amps": 30.0, "ang_deg": 45.0, "spectrum_type": "custom"},
]

CUSTOM_HARMONIC_FILTERS = [
    {"bus": 3, "name": "5th Harmonic Notch Filter", "filter_type": "single_tuned", "tuning_order": 4.85, "q_factor": 40.0, "mvar_rating": 2.5, "status": 1},
    {"bus": 4, "name": "7th High-Pass Damped Filter","filter_type": "high_pass",    "tuning_order": 6.85, "q_factor": 2.5,  "mvar_rating": 3.0, "status": 1},
]

# ── Reports ───────────────────────────────────────────────────────────────────
WRITE_CSV_REPORT  = True              # Export scan profiles and THD summary to CSV
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
    print(" DevEN Harmonic Analysis & Scan — Enter File Paths")
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
    print(f" DevEN Harmonic Analysis & Scan Runner — {len(paths)} file(s)")
    print(f" Scope       : {STUDY_TYPE.upper()}")
    print(f" Standard    : IEEE 519-2022 (THD limit: {THD_V_LIMIT_PCT}%)")
    print(f" Scan Range  : {F_START_HZ:.0f} Hz to {F_END_HZ:.0f} Hz (Step: {F_STEP_HZ:.1f} Hz)")
    print("=" * 72)

    for i, path in enumerate(paths, 1):
        print(f"\n[{i}/{len(paths)}] {path.name}")
        try:
            case = _load_case_file(devenpy, path)

            # Solve base power flow first
            base_st = case.solve_load_flow(method="nr", show_q_limits=False)
            if not base_st.get("converged", False):
                print("  [WARNING] Base power flow did not converge with NR, attempting flat start...")
                case.solve_load_flow(method="fdlf", flat_start=True, show_q_limits=False)

            # Inject harmonic sources
            for src in CUSTOM_HARMONIC_SOURCES:
                case.add_harmonic_source(
                    bus=src["bus"],
                    name=src.get("name", "HarmonicSource"),
                    phase=src.get("phase", "3PH"),
                    i_fund_amps=src.get("i_fund_amps", 50.0),
                    ang_deg=src.get("ang_deg", 0.0),
                    spectrum_type=src.get("spectrum_type", "6pulse"),
                )

            # Install mitigation filters
            for flt in CUSTOM_HARMONIC_FILTERS:
                case.add_harmonic_filter(
                    bus=flt["bus"],
                    name=flt.get("name", "HarmonicFilter"),
                    filter_type=flt.get("filter_type", "single_tuned"),
                    tuning_order=flt.get("tuning_order", 4.85),
                    q_factor=flt.get("q_factor", 40.0),
                    mvar_rating=flt.get("mvar_rating", 2.5),
                    status=flt.get("status", 1),
                )

            out_dir = Path(OUTPUT_DIR) if OUTPUT_DIR else path.parent

            # 1. Frequency Scan
            if STUDY_TYPE in ("scan", "both"):
                print(f"  -> Running parallel driving-point impedance scan...")
                scan_res = case.solve_frequency_scan(
                    buses=TARGET_BUSES,
                    start_hz=F_START_HZ,
                    end_hz=F_END_HZ,
                    step_hz=F_STEP_HZ,
                    inject_amp=INJECT_AMP,
                )
                print(f"     Calculated {len(scan_res)} frequency scan data points across grid.")

                # Resonance detection
                resonances = case.harmonic_detected_resonances() if hasattr(case, "harmonic_detected_resonances") else []
                if resonances:
                    print(f"\n  Detected Parallel Resonance Peaks:")
                    print(f"  {'Bus':<8} {'Freq (Hz)':<12} {'Harmonic':<10} {'|Z| (Ohms)':<14} {'Severity':<10}")
                    print("  " + "-" * 56)
                    for r in resonances[:10]:
                        print(f"  {r.get('bus_id',0):<8} {r.get('freq_hz',0.0):<12.1f} {r.get('order',0.0):<10.2f} {r.get('z_mag',0.0):<14.2f} {r.get('severity','HIGH'):<10}")
                else:
                    print("     No severe unmitigated parallel resonances detected in target bandwidth.")

                if WRITE_CSV_REPORT and scan_res:
                    csv_scan = out_dir / f"{path.stem}_freq_scan.csv"
                    with open(csv_scan, "w", encoding="utf-8") as f:
                        f.write("bus_id,freq_hz,harmonic_order,r_ohms,x_ohms,z_mag_ohms,phase_deg\n")
                        for pt in scan_res:
                            f.write(f"{pt.get('bus_id',0)},{pt.get('freq_hz',0.0):.2f},{pt.get('harmonic_order',0.0):.3f},{pt.get('r_ohms',0.0):.4f},{pt.get('x_ohms',0.0):.4f},{pt.get('z_mag_ohms',0.0):.4f},{pt.get('phase_deg',0.0):.2f}\n")
                    print(f"  -> Exported Frequency Scan CSV: {csv_scan}")

            # 2. Harmonic Penetration & IEEE 519
            if STUDY_TYPE in ("harmonics", "both"):
                print(f"  -> Solving multi-order harmonic power flow (1 to {MAX_ORDER})...")
                h_res = case.solve_harmonics(
                    solver=SOLVER,
                    max_order=MAX_ORDER,
                    skin_effect=SKIN_EFFECT,
                    pcc_bus=PCC_BUS,
                    pcc_kv=PCC_KV,
                    isc_il_ratio=ISC_IL_RATIO,
                    standard="ieee519",
                )
                print(f"     Harmonic flow converged: {h_res.get('converged', True)}")

                # Bus THD results
                bus_thd = case.harmonic_bus_results() if hasattr(case, "harmonic_bus_results") else []
                if bus_thd:
                    print(f"\n  Bus Voltage THD & Distortion Summary (Top 10):")
                    print(f"  {'Bus':<8} {'V_fund (pu)':<14} {'V_rms (pu)':<14} {'V_THD (%)':<12} {'IEEE 519 Status':<16}")
                    print("  " + "-" * 66)
                    for b in bus_thd[:10]:
                        thd = b.get("v_thd_pct", 0.0)
                        status = "PASS" if thd <= THD_V_LIMIT_PCT else "FAIL (Exceeded)"
                        print(f"  {b.get('bus_id',0):<8} {b.get('v_fund_pu',1.0):<14.4f} {b.get('v_rms_pu',1.0):<14.4f} {thd:<12.2f} {status:<16}")

                if WRITE_CSV_REPORT and bus_thd:
                    csv_thd = out_dir / f"{path.stem}_harmonics_thd.csv"
                    with open(csv_thd, "w", encoding="utf-8") as f:
                        f.write("bus_id,v_fund_pu,v_rms_pu,v_thd_pct,ieee519_status\n")
                        for b in bus_thd:
                            thd = b.get("v_thd_pct", 0.0)
                            st = "PASS" if thd <= THD_V_LIMIT_PCT else "FAIL"
                            f.write(f"{b.get('bus_id',0)},{b.get('v_fund_pu',1.0):.5f},{b.get('v_rms_pu',1.0):.5f},{thd:.3f},{st}\n")
                    print(f"  -> Exported Harmonics THD CSV: {csv_thd}")

        except Exception as e:
            print(f"  -> ERROR: {e}")

    print("\n" + "=" * 72)
    print(" Harmonic Analysis Finished.")
    print("=" * 72)


if __name__ == "__main__":
    main()

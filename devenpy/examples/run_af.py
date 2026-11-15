"""
run_af.py — DevEN Arc Flash Hazard Analysis Runner
Standards: IEEE 1584-2018 / NFPA 70E-2024 / OSHA 1910.269
Part of the DevEN Power System Study Engine (devenpy)
Made in India from Bengaluru.

USAGE:
    python run_af.py
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

# ── Arc Flash Study Mode ──────────────────────────────────────────────────────
# "custom" : Run list of custom equipment locations defined in CUSTOM_ARC_FLASH_BUSES
# "single" : Detailed calculation at a single specified bus
# "scan"   : Scan all buses in the electrical network using default enclosure sizes
STUDY_MODE        = "custom"          # "custom" | "single" | "scan"

# ── Default Parameters (Used when STUDY_MODE == "single" or "scan") ──────────
FAULT_BUS         = 1                 # Target bus number
ELECTRODE_CONFIG  = "vcb"             # "vcb" (Vertical in Box) | "vcbb" (Vertical Barrier)
                                      # "hcb" (Horizontal in Box) | "voa" (Open Air Vert)
                                      # "hoa" (Open Air Horiz)
WORKING_DIST_MM   = 457.2             # Working distance (457.2 mm = 18 inches)
CLEARING_TIME_SEC = 0.10              # Protective relay + breaker total clearing time (sec)
GAP_MM            = 32.0              # Electrode conductor gap (32 mm for LV, 104 mm for MV)
BOX_WIDTH_MM      = 508.0             # Enclosure width (mm) (508 mm = 20 in)
BOX_HEIGHT_MM     = 508.0             # Enclosure height (mm)
BOX_DEPTH_MM      = 508.0             # Enclosure depth (mm)

# ══════════════════════════════════════════════════════════════════════════════
#  CUSTOM ARC FLASH EQUIPMENT LOCATIONS (Edit directly in code)
# ══════════════════════════════════════════════════════════════════════════════
# Define equipment enclosures, electrode configurations, conductor gaps,
# working distances, and fault clearing times:
#
#   - ELECTRODE CONFIGS : "vcb", "vcbb", "hcb", "voa", "hoa"
#   - WORKING DISTANCES : 457.2 mm (18 in - Panel/MCC), 610.0 mm (24 in - Switchgear), 914.4 mm (36 in - EHV)
#
CUSTOM_ARC_FLASH_BUSES = [
    {"bus": 1, "config": "vcb",  "working_dist_mm": 610.0, "gap_mm": 104.0, "clearing_time": 0.08, "name": "13.8kV Main Incomer Switchgear"},
    {"bus": 2, "config": "vcbb", "working_dist_mm": 457.2, "gap_mm": 25.0,  "clearing_time": 0.12, "name": "4.16kV Motor Control Center (MCC)"},
    {"bus": 3, "config": "hcb",  "working_dist_mm": 457.2, "gap_mm": 25.0,  "clearing_time": 0.15, "name": "480V Low Voltage Distribution Board"},
    {"bus": 4, "config": "vcb",  "working_dist_mm": 457.2, "gap_mm": 32.0,  "clearing_time": 0.10, "name": "480V Emergency Lighting Panel"},
    {"bus": 5, "config": "voa",  "working_dist_mm": 914.4, "gap_mm": 152.0, "clearing_time": 0.05, "name": "138kV Substation Open-Air Yard"},
]

# ── Reports ───────────────────────────────────────────────────────────────────
WRITE_CSV_REPORT  = True              # Export arc flash hazard table as CSV
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
    print(" DevEN Arc Flash Hazard Analysis — Enter File Paths")
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


def _calc_ppe_category(e_cal_cm2):
    if e_cal_cm2 <= 1.2:
        return "Category 0 / Non-Arc"
    elif e_cal_cm2 <= 4.0:
        return "Category 1 (4 cal/cm²)"
    elif e_cal_cm2 <= 8.0:
        return "Category 2 (8 cal/cm²)"
    elif e_cal_cm2 <= 25.0:
        return "Category 3 (25 cal/cm²)"
    elif e_cal_cm2 <= 40.0:
        return "Category 4 (40 cal/cm²)"
    else:
        return "DANGER (> 40 cal/cm²)"


def main():
    devenpy = _import_devenpy()
    paths = _prompt_paths()
    if not paths:
        print("No paths specified. Exiting.")
        return

    print("\n" + "=" * 72)
    print(f" DevEN Arc Flash Hazard Runner — {len(paths)} file(s)")
    print(f" Standard    : IEEE 1584-2018 / NFPA 70E-2024")
    print(f" Mode        : {STUDY_MODE.upper()}")
    print("=" * 72)

    for i, path in enumerate(paths, 1):
        print(f"\n[{i}/{len(paths)}] {path.name}")
        try:
            case = _load_case_file(devenpy, path)

            out_dir = Path(OUTPUT_DIR) if OUTPUT_DIR else path.parent

            if STUDY_MODE == "custom":
                print(f"  -> Evaluating {len(CUSTOM_ARC_FLASH_BUSES)} custom equipment locations:")
                print(f"  {'Equipment / Location':<32} {'Bus':<6} {'Cfg':<6} {'I_arc (kA)':<12} {'Energy (cal)':<14} {'AFB (mm)':<10} {'PPE Level':<18}")
                print("  " + "-" * 102)
                results = []
                for eq in CUSTOM_ARC_FLASH_BUSES:
                    res = case.solve_arc_flash(
                        bus=eq["bus"],
                        config=eq.get("config", "vcb"),
                        working_dist_mm=eq.get("working_dist_mm", WORKING_DIST_MM),
                        gap_mm=eq.get("gap_mm", GAP_MM),
                        clearing_time_arc=eq.get("clearing_time", CLEARING_TIME_SEC),
                    )
                    i_arc = res.get("i_arc_ka", res.get("arcing_current_ka", 0.0))
                    energy = res.get("incident_energy_cal_cm2", res.get("energy_cal_cm2", 0.0))
                    afb = res.get("arc_flash_boundary_mm", res.get("afb_mm", 0.0))
                    ppe = _calc_ppe_category(energy)
                    name = eq.get("name", f"Bus {eq['bus']}")
                    print(f"  {name[:30]:<32} {eq['bus']:<6} {eq.get('config','vcb').upper():<6} {i_arc:<12.3f} {energy:<14.2f} {afb:<10.0f} {ppe:<18}")
                    results.append({
                        "name": name,
                        "bus": eq["bus"],
                        "config": eq.get("config", "vcb"),
                        "working_dist_mm": eq.get("working_dist_mm", WORKING_DIST_MM),
                        "i_arc_ka": i_arc,
                        "energy_cal_cm2": energy,
                        "afb_mm": afb,
                        "ppe": ppe,
                    })

                if WRITE_CSV_REPORT:
                    csv_p = out_dir / f"{path.stem}_arc_flash_results.csv"
                    with open(csv_p, "w", encoding="utf-8") as f:
                        f.write("location_name,bus,electrode_config,working_dist_mm,arcing_current_ka,incident_energy_cal_cm2,afb_mm,ppe_category\n")
                        for r in results:
                            f.write(f"\"{r['name']}\",{r['bus']},{r['config']},{r['working_dist_mm']:.1f},{r['i_arc_ka']:.4f},{r['energy_cal_cm2']:.2f},{r['afb_mm']:.1f},\"{r['ppe']}\"\n")
                    print(f"  -> Exported Arc Flash CSV: {csv_p}")

            elif STUDY_MODE == "scan":
                scan_res = case.solve_arc_flash_scan() if hasattr(case, "solve_arc_flash_scan") else []
                print(f"  -> System-wide scan evaluated across {len(scan_res)} buses.")

            else:  # single
                res = case.solve_arc_flash(
                    bus=FAULT_BUS,
                    config=ELECTRODE_CONFIG,
                    working_dist_mm=WORKING_DIST_MM,
                    gap_mm=GAP_MM,
                    clearing_time_arc=CLEARING_TIME_SEC,
                    width_mm=BOX_WIDTH_MM,
                    height_mm=BOX_HEIGHT_MM,
                    depth_mm=BOX_DEPTH_MM,
                )
                i_arc = res.get("i_arc_ka", res.get("arcing_current_ka", 0.0))
                energy = res.get("incident_energy_cal_cm2", res.get("energy_cal_cm2", 0.0))
                afb = res.get("arc_flash_boundary_mm", res.get("afb_mm", 0.0))
                ppe = _calc_ppe_category(energy)

                print(f"  -> Arc Flash Hazard at Bus {FAULT_BUS}:")
                print(f"     Electrode Config   : {ELECTRODE_CONFIG.upper()}")
                print(f"     Working Distance   : {WORKING_DIST_MM:.1f} mm ({WORKING_DIST_MM/25.4:.1f} in)")
                print(f"     Arcing Current     : {i_arc:.3f} kA")
                print(f"     Incident Energy    : {energy:.2f} cal/cm²")
                print(f"     Arc Flash Boundary : {afb:.0f} mm ({afb/25.4:.1f} in)")
                print(f"     Required PPE Level : {ppe}")

        except Exception as e:
            print(f"  -> ERROR: {e}")

    print("\n" + "=" * 72)
    print(" Arc Flash Finished.")
    print("=" * 72)


if __name__ == "__main__":
    main()

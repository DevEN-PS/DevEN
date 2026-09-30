#!/usr/bin/env python3

# ─── DevEN License Gate ──────────────────────────────────────────────────────
import sys as _sys, os as _os
_lic_dir = _os.path.dirname(_os.path.abspath(__file__))
if _lic_dir not in _sys.path:
    _sys.path.insert(0, _lic_dir)
try:
    from license_core import find_best_license, check_study_allowed, CONTACT_EMAIL, FREE_BUS_LIMIT
    _LICENSE_CORE = True
except ImportError:
    _LICENSE_CORE = False


def _check_license_gate(module, bus_count=0):
    """Exit with error if this module/bus_count combination is not licensed."""
    if not _LICENSE_CORE:
        return
    lic = find_best_license()
    allowed, reason = check_study_allowed(module, bus_count, lic)
    if not allowed:
        print()
        print("=" * 60)
        print("  DevEN — Licence Required")
        print("  Module: {}  |  Buses: {}".format(module, bus_count))
        print()
        print(reason)
        print()
        print("  Contact: {}".format(CONTACT_EMAIL))
        print("=" * 60)
        _sys.exit(1)
    if lic:
        print("[LICENSE] {} validated for: {}".format(module, lic.customer))
    else:
        print("[LICENSE] Free tier — {} (<= {} buses)".format(module, FREE_BUS_LIMIT))

# ─────────────────────────────────────────────────────────────────────────────

# -*- coding: utf-8 -*-
"""
===============================================================================
DevEN — Native Short Circuit Analysis Runner (CLI & Headless Automation)
Standards: IEC 60909 / ANSI/IEEE C37
===============================================================================

Usage Examples:
  1. System-wide Fault Calculation (All Buses):
     DevEN_SCS_Engine.exe case.py
     DevEN_SCS_Engine.exe case.db --project-id 1

  2. Single Bus Fault (Detailed Branch & Generator Contributions):
     DevEN_SCS_Engine.exe case.py --bus 1 --fault-type 3phase
     DevEN_SCS_Engine.exe case.py --bus 5 --fault-type slg --method classical

  3. Display Units Toggle (MVA vs kA):
     DevEN_SCS_Engine.exe case.py --units mva

  4. Open Conductor (Broken Line) Fault:
     DevEN_SCS_Engine.exe case.py --bus 2 --fault-type open1p

  5. Custom Output Directory and Fault Impedance:
     DevEN_SCS_Engine.exe case.py --rf 0.5 --xf 1.0 -o results_scs

  6. Arc Flash Hazard Analysis Integration:
     DevEN_SCS_Engine.exe case.py --arc-flash --config VCB --clearing-time 0.1
===============================================================================
"""

import sys
import os
import argparse
import csv
from datetime import datetime

try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# Path Bootstrapping — go up from runners/ to deven_api/ root
_runners_dir = os.path.dirname(os.path.abspath(__file__))
_root_dir = os.path.dirname(_runners_dir)   # deven_api/
if _root_dir not in sys.path:
    sys.path.insert(0, _root_dir)
if _runners_dir not in sys.path:
    sys.path.insert(0, _runners_dir)
for _sub in ('engines', 'utils', 'cli', 'tools'):
    _p = os.path.join(_root_dir, _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from input_reader import InputReader
except ImportError:
    from utils.input_reader import InputReader

try:
    import short_circuit_solver as scs
except ImportError:
    import engines.short_circuit_solver as scs

try:
    from license_manager import LicenseManager
except ImportError:
    from utils.license_manager import LicenseManager


def run_scs(case_path, bus_id=None, fault_type="3phase", r_f=0.0, x_f=0.0,
            c_factor=1.1, zero_seq_factor=3.0, output_folder=None,
            method="iec", units="ka", project_id=None, breaker_check=True,
            generate_reports=False, reports=None, csv_report=False, txt_report=False,
            to_terminal=False, print_report=None):
    """Executes Short Circuit calculation with license verification."""
    if not os.path.exists(case_path):
        print(f"\n❌ [ERROR] Case file not found: {case_path}")
        return 1

    case_name = os.path.splitext(os.path.basename(case_path))[0]
    if case_name.endswith('_converted'):
        case_name = case_name[:-10]

    # Reporting flags resolution (Default: False unless requested)
    if reports:
        rep_list = [r.strip().lower() for r in (reports.split(',') if isinstance(reports, str) else reports)]
        if 'all' in rep_list:
            csv_report = txt_report = True
            generate_reports = True
        elif 'none' in rep_list:
            csv_report = txt_report = False
            generate_reports = False
        else:
            if 'csv' in rep_list: csv_report = True
            if any(x in rep_list for x in ('txt', 'summary')): txt_report = True
            generate_reports = csv_report or txt_report
    elif generate_reports and not (csv_report or txt_report):
        csv_report = txt_report = True

    method_label = "IEEE 3002.2 / ANSI C37 Standard" if any(w in str(method).lower() for w in ('ansi', 'ieee', 'classical')) else "IEC 60909 Standard"
    print("\n" + "=" * 80)
    print(f"⚡ DevEN SHORT CIRCUIT ANALYSIS ENGINE ({method_label.upper()})")
    print("=" * 80)
    print(f"📂 Loading Case: {case_path}" + (f" (Project ID: {project_id})" if project_id else ""))

    # Read case data with project_id propagation
    if project_id:
        os.environ['DEVEN_PROJECT_ID'] = str(project_id)
    data = InputReader.read_from_python(case_path, project_id=project_id)
    if not data:
        print("\n❌ [ERROR] Failed to load case database.")
        return 1

    buses = data.get('buses', {})
    lines = data.get('lines', {})
    transformers = data.get('transformers', {})
    three_w_xfmrs = data.get('three_winding_transformers', {})
    gens = data.get('generators', {})
    loads = data.get('loads', {})
    base_mva = float(data.get('base_mva', 100.0))

    # Cryptographic License Verification (SCS)
    n_buses = len(buses)
    is_valid, lic_msg, lic_data = LicenseManager.verify_license(study_code="SCS", num_buses=n_buses)
    if not is_valid:
        print("\n" + "=" * 80)
        print("🔒 DevEN COMMERCIAL LICENSE VERIFICATION FAILED")
        print("=" * 80)
        print(lic_msg)
        print("=" * 80 + "\n")
        return 1

    print(f"🔑 License Valid: {lic_msg}")
    print(f"📊 System: {n_buses} Buses, {len(gens)} Generators, {len(lines)} Lines, {len(transformers)} Transformers, {len(three_w_xfmrs)} 3W-Transformers")

    # Build unified branch list with complete sequence parameters
    branches = []
    for lid, l in lines.items():
        if l.get('status', 1) != 0:
            l_km = float(l.get('length_km', l.get('length', 1.0)) or 1.0)
            branches.append({
                'num': lid,
                'name': l.get('name', f"Line_{lid}"),
                'from_bus': l['from_bus'],
                'to_bus': l['to_bus'],
                'r': float(l.get('r', 0.001)),
                'x': float(l.get('x', 0.01)),
                'b': float(l.get('b', 0.0)),
                'status': 1,
                'type': 'line',
                'ratio': 1.0,
                'r0': float(l.get('r0', l.get('R0_per_km', 0.0) * l_km if l.get('R0_per_km', 0.0) > 0 else float(l.get('r', 0.001)) * zero_seq_factor)),
                'x0': float(l.get('x0', l.get('X0_per_km', 0.0) * l_km if l.get('X0_per_km', 0.0) > 0 else float(l.get('x', 0.01)) * zero_seq_factor)),
                'b0': float(l.get('b0', l.get('B0_per_km', 0.0) * l_km if l.get('B0_per_km', 0.0) > 0 else float(l.get('b', 0.0)) / zero_seq_factor)),
                'from_cb_mva': float(l.get('from_cb_mva', 0.0)),
                'to_cb_mva': float(l.get('to_cb_mva', 0.0))
            })

    for tid, t in transformers.items():
        if t.get('status', 1) != 0:
            tap = float(t.get('ratio', t.get('tap_ratio', t.get('tap', 1.0))) or 1.0)
            branches.append({
                'num': tid,
                'name': t.get('name', f"Xfmr_{tid}"),
                'from_bus': t['from_bus'],
                'to_bus': t['to_bus'],
                'r': float(t.get('r', 0.0001)),
                'x': float(t.get('x', 0.05)),
                'b': 0.0,
                'ratio': tap,
                'status': 1,
                'type': 'transformer',
                'r0': float(t.get('r0', t.get('R0_pu', 0.0)) or t.get('r', 0.0001)),
                'x0': float(t.get('x0', t.get('X0_pu', 0.0)) or t.get('x', 0.05)),
                'from_conn': str(t.get('from_conn', '0')),
                'to_conn': str(t.get('to_conn', '0')),
                'from_gnd_r': float(t.get('from_gnd_r', 0.0)),
                'from_gnd_x': float(t.get('from_gnd_x', 0.0)),
                'to_gnd_r': float(t.get('to_gnd_r', 0.0)),
                'to_gnd_x': float(t.get('to_gnd_x', 0.0)),
                'from_cb_mva': float(t.get('from_cb_mva', 0.0)),
                'to_cb_mva': float(t.get('to_cb_mva', 0.0))
            })

    # Prepare output folder
    if not output_folder:
        output_folder = os.path.join(os.path.dirname(os.path.abspath(case_path)), f"{case_name}_SHORTCIRCUIT")
    os.makedirs(output_folder, exist_ok=True)

    if bus_id is not None:
        target_bus = int(bus_id) if str(bus_id).isdigit() else bus_id
        if target_bus not in buses:
            print(f"\n❌ [ERROR] Bus ID '{bus_id}' not found in network.")
            return 1

        print(f"\n🎯 Calculating Single Bus Fault on Bus {target_bus} ({fault_type.upper()})...")
        res = scs.solve_short_circuit(
            bus_data=buses,
            branch_data=branches,
            generators=gens,
            loads=loads,
            fault_bus=target_bus,
            fault_type=fault_type,
            r_f=r_f,
            x_f=x_f,
            voltage_scaling_factor_c=c_factor,
            zero_seq_factor=zero_seq_factor,
            base_mva=base_mva,
            method=method,
            units=units,
            breaker_check=breaker_check,
            three_w_xfmrs=three_w_xfmrs
        )

        b_info = buses.get(target_bus, {})
        v_base = float(b_info.get('base_kV', 138.0))
        ik = float(res.get('I_fault_kA', res.get('Ik_ss_kA', 0.0)))
        ip = float(res.get('Ip_kA', 0.0))
        sk = float(res.get('Sk_MVA', 0.0))
        xr = float(res.get('XR_ratio', 0.0))

        text_rep = res.get('text_summary')
        if not text_rep:
            lines_buf = [
                "=" * 80,
                f"  SHORT CIRCUIT RESULTS — BUS {target_bus} ({b_info.get('name', 'Bus')})",
                "=" * 80,
                f"  Nominal Voltage (Un)       : {v_base:.2f} kV",
                f"  Fault Type                 : {fault_type.upper()}",
                f"  Method                     : {method_label}",
                f"  Initial Symmetrical Ik''    : {ik:.3f} kA",
                f"  Peak Current Ip             : {ip:.3f} kA",
                f"  Short-Circuit Power Sk''    : {sk:.2f} MVA",
                f"  Equivalent X/R Ratio        : {xr:.2f}",
                "=" * 80,
            ]
            text_rep = "\n".join(lines_buf)

        csv_rows = [
            ["Parameter", "Value", "Unit"],
            ["Bus_ID", target_bus, ""],
            ["Fault_Type", fault_type.upper(), ""],
            ["Method", method_label, ""],
            ["Nominal_Voltage_kV", f"{v_base:.2f}", "kV"],
            ["Ik_Symmetrical_kA", f"{ik:.3f}", "kA"],
            ["Ip_Peak_kA", f"{ip:.3f}", "kA"],
            ["Sk_ShortCircuit_MVA", f"{sk:.2f}", "MVA"],
            ["XR_Ratio", f"{xr:.2f}", ""],
        ]
        if res.get('P_ngr_kW', 0.0) > 0:
            csv_rows.append(["NGR_Power_Loss_kW", f"{res.get('P_ngr_kW'):.2f}", "kW"])
        csv_str = "\n".join([",".join(map(str, row)) for row in csv_rows])

        # Terminal diversion
        if print_report == 'csv':
            print("\n" + "=" * 80)
            print("  SHORT CIRCUIT CSV REPORT (TERMINAL)")
            print("=" * 80)
            print(csv_str)
            print("=" * 80 + "\n")
        elif to_terminal or print_report in ('summary', 'txt', 'all') or not (generate_reports or csv_report or txt_report):
            print("\n" + text_rep)

        saved_files = []
        if csv_report:
            out_csv = os.path.join(output_folder, f"{case_name}_FAULT_BUS_{target_bus}.csv")
            with open(out_csv, 'w', newline='', encoding='utf-8') as f:
                f.write(csv_str)
            saved_files.append(out_csv)
            print(f"📁 CSV results saved: {out_csv}")

        if txt_report:
            out_txt = os.path.join(output_folder, f"{case_name}_FAULT_BUS_{target_bus}.txt")
            with open(out_txt, 'w', encoding='utf-8') as f:
                f.write(text_rep)
            saved_files.append(out_txt)
            print(f"📁 Text summary saved: {out_txt}")

        if not saved_files:
            print("  Simulation completed with zero report files written to disk (as configured).\n")

    else:
        print(f"\n🌐 Performing Full System-Wide Short Circuit Scan ({method_label})...")
        results = scs.solve_system_short_circuit(
            bus_data=buses,
            branch_data=branches,
            generators=gens,
            loads=loads,
            r_f=r_f,
            x_f=x_f,
            voltage_scaling_factor_c=c_factor,
            zero_seq_factor=zero_seq_factor,
            base_mva=base_mva,
            method=method,
            units=units,
            breaker_check=breaker_check,
            three_w_xfmrs=three_w_xfmrs
        )

        col_3ph = "3PH Sk (MVA)" if units.lower() == "mva" else "3PH Ik (kA)"
        col_slg = "SLG Sk (MVA)" if units.lower() == "mva" else "SLG Ik (kA)"

        table_lines = [
            "\n" + "=" * 92,
            f"{'Bus':<6} | {'Name':<14} | {'Base kV':<8} | {col_3ph:<14} | {'3PH Sk (MVA)':<13} | {col_slg:<14} | {'X/R':<6}",
            "─" * 92
        ]
        csv_rows = [
            ["Bus_ID", "Bus_Name", "Base_kV", "3PH_Ik_kA", "3PH_Ip_kA", "3PH_Sk_MVA", "3PH_XR",
             "SLG_Ik_kA", "SLG_Sk_MVA", "LL_Ik_kA", "DLG_Ik_kA", "Breaker_Duty_Pct", "Breaker_Status"]
        ]

        for bid in sorted(results.keys(), key=lambda x: int(x) if str(x).isdigit() else str(x)):
            r = results[bid]
            bname = r.get('bus_name', f"Bus_{bid}")[:14]
            kv = r.get('base_kV', 0.0)
            ik3 = r.get('3ph_current_kA', 0.0)
            sk3 = r.get('3ph_mva', 0.0)
            ik_slg = r.get('slg_current_kA', 0.0)
            xr = r.get('3ph_xr', 0.0)

            disp_3ph = sk3 if units.lower() == "mva" else ik3
            disp_slg = r.get('slg_mva', 0.0) if units.lower() == "mva" else ik_slg

            table_lines.append(f"{bid:<6} | {bname:<14} | {kv:<8.1f} | {disp_3ph:<14.3f} | {sk3:<13.1f} | {disp_slg:<14.3f} | {xr:<6.2f}")

            cb_info = r.get('breaker_duty') or {}
            cb_duty_str = f"{cb_info.get('duty_pct', 0.0):.1f}%" if cb_info else "N/A"
            cb_stat = cb_info.get('status', "N/A") if cb_info else "N/A"

            csv_rows.append([
                bid, r.get('bus_name', ''), kv,
                ik3, r.get('3ph_ip_kA', 0.0), sk3, xr,
                ik_slg, r.get('slg_mva', 0.0),
                r.get('ll_current_kA', 0.0), r.get('dlg_current_kA', 0.0),
                cb_duty_str, cb_stat
            ])

        table_lines.append("=" * 92)
        table_str = "\n".join(table_lines)
        csv_str = "\n".join([",".join(map(str, row)) for row in csv_rows])

        # Terminal diversion
        if print_report == 'csv':
            print("\n" + "=" * 92)
            print("  SHORT CIRCUIT SYSTEM CSV REPORT (TERMINAL)")
            print("=" * 92)
            print(csv_str)
            print("=" * 92 + "\n")
        elif to_terminal or print_report in ('summary', 'txt', 'all') or not (generate_reports or csv_report or txt_report):
            print(table_str)

        saved_files = []
        if csv_report:
            out_csv = os.path.join(output_folder, f"{case_name}_SYSTEM_FAULTS.csv")
            with open(out_csv, 'w', newline='', encoding='utf-8') as f:
                f.write(csv_str)
            saved_files.append(out_csv)
            print(f"\n📁 System fault results saved to: {out_csv}")

        if txt_report:
            out_txt = os.path.join(output_folder, f"{case_name}_SYSTEM_FAULTS.txt")
            with open(out_txt, 'w', encoding='utf-8') as f:
                f.write(table_str)
            saved_files.append(out_txt)
            print(f"📁 System fault text summary saved to: {out_txt}")

        if not saved_files:
            print("  Simulation completed with zero report files written to disk (as configured).\n")

    return 0


def main():
    _check_license_gate("SCS")
    parser = argparse.ArgumentParser(
        prog="DevEN_SCS_Engine.exe",
        description="DevEN Native Short Circuit Analysis Engine (IEC 60909 / ANSI C37)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=r"""
Examples:
  1. System-wide Short Circuit Scan (All Buses):
     DevEN_SCS_Engine.exe case.py
     DevEN_SCS_Engine.exe case.db --project-id 1

  2. Single Bus Fault (Detailed Contributions):
     DevEN_SCS_Engine.exe case.py --bus 1 --fault-type 3phase
     DevEN_SCS_Engine.exe case.py --bus 5 --fault-type slg --method classical

  3. Display Units Toggle (MVA vs kA):
     DevEN_SCS_Engine.exe case.py --units mva

  4. Open Conductor (Broken Line) Fault:
     DevEN_SCS_Engine.exe case.py --bus 2 --fault-type open1p

  5. Custom Output Directory and Fault Impedance:
     DevEN_SCS_Engine.exe case.py --bus 2 --rf 0.5 --xf 1.0 --c-factor 1.10 -o results_scs

  6. Arc Flash Hazard Analysis Integration:
     DevEN_SCS_Engine.exe case.py --arc-flash --config VCB --clearing-time 0.1
        """
    )
    parser.add_argument("case", type=str, help="Input network case file (.py, .db)")
    parser.add_argument("-b", "--bus", type=str, default=None, help="Specific fault bus ID (default: scans all buses)")
    parser.add_argument("-f", "--fault-type", type=str, default="3phase",
                        choices=["3phase", "slg", "ll", "dlg", "open1p", "open2p"],
                        help="Fault type: 3phase, slg, ll, dlg, open1p, open2p (default: 3phase)")
    parser.add_argument("-m", "--method", type=str, default="iec", choices=["iec", "classical"],
                        help="Calculation method: iec (IEC 60909) or classical (ANSI Symmetrical Components) [default: iec]")
    parser.add_argument("-u", "--units", type=str, default="ka", choices=["ka", "mva"],
                        help="Display units: ka (Current) or mva (Power) [default: ka]")
    parser.add_argument("--project-id", type=str, default=None, help="Target Project ID for SQLite database containers")
    parser.add_argument("--rf", type=float, default=0.0, help="Fault resistance Rf in ohms (default: 0.0)")
    parser.add_argument("--xf", type=float, default=0.0, help="Fault reactance Xf in ohms (default: 0.0)")
    parser.add_argument("--c-factor", type=float, default=1.05, help="Voltage factor c (IEC 60909: 1.05 for LV, 1.10 for MV/HV)")
    parser.add_argument("-o", "--output", type=str, default=None, help="Custom output directory")
    parser.add_argument("--no-breaker-check", action="store_true", help="Disable circuit breaker interrupting duty evaluation")
    parser.add_argument("--arc-flash", action="store_true", help="Execute IEEE 1584-2018 / NFPA 70E Arc Flash Hazard Analysis")
    parser.add_argument("--config", default="VCB", choices=["VCB", "VCBB", "HCB", "VOA", "HOA"], help="Electrode configuration (default: VCB)")
    parser.add_argument("--working-dist", type=float, default=None, help="Working distance in inches")
    parser.add_argument("--clearing-time", type=float, default=0.1, help="Upstream clearing time in seconds (default: 0.1s)")

    # ── Report Generation Options (Default: No files written to disk) ──────────
    rep_group = parser.add_argument_group("Reporting Options",
                                         "Controls for report generation and terminal output (Default: no reports written to disk).")
    rep_group.add_argument("--reports", type=str, default=None,
                           help="Comma-separated list of reports: csv, txt, all, none")
    rep_group.add_argument("--all-reports", action="store_true", default=False,
                           help="Generate all standard report files (CSV, TXT)")
    rep_group.add_argument("--no-reports", action="store_true", default=False,
                           help="Disable saving report files to disk (default)")
    rep_group.add_argument("--csv", action="store_true", default=False,
                           help="Generate CSV results file")
    rep_group.add_argument("--txt", action="store_true", default=False,
                           help="Generate text summary report file (.txt)")
    rep_group.add_argument("--to-terminal", action="store_true", default=False,
                           help="Print simulation summary report directly to terminal / stdout")
    rep_group.add_argument("--print-report", type=str, default=None,
                           choices=["summary", "csv", "txt", "all"],
                           help="Divert specified report to terminal / stdout (e.g. --print-report summary)")

    args, _ = parser.parse_known_args()

    if getattr(args, 'arc_flash', False):
        try:
            from runners.run_arcflash import main as af_main
        except ImportError:
            from run_arcflash import main as af_main
        sys.argv = [sys.argv[0], args.case]
        if args.bus:
            sys.argv.extend(["-b", str(args.bus)])
        else:
            sys.argv.append("--all-buses")
        sys.argv.extend(["--config", args.config, "--clearing-time", str(args.clearing_time)])
        if args.working_dist:
            sys.argv.extend(["--working-dist", str(args.working_dist)])
        if args.output:
            sys.argv.extend(["-o", args.output])
        sys.exit(af_main())

    csv_report = args.csv
    txt_report = args.txt
    generate_reports = args.all_reports

    if args.all_reports:
        csv_report = txt_report = True
        generate_reports = True
    elif args.no_reports:
        csv_report = txt_report = False
        generate_reports = False
    elif args.reports:
        rep_list = [r.strip().lower() for r in args.reports.split(',')]
        if 'all' in rep_list:
            csv_report = txt_report = True
            generate_reports = True
        elif 'none' in rep_list:
            csv_report = txt_report = False
            generate_reports = False
        else:
            if 'csv' in rep_list: csv_report = True
            if any(x in rep_list for x in ('txt', 'summary')): txt_report = True
            generate_reports = csv_report or txt_report
    else:
        generate_reports = csv_report or txt_report

    to_terminal = args.to_terminal or (args.print_report is not None)

    ret = run_scs(
        case_path=args.case,
        bus_id=args.bus,
        fault_type=args.fault_type,
        r_f=args.rf,
        x_f=args.xf,
        c_factor=args.c_factor,
        output_folder=args.output,
        method=args.method,
        units=args.units,
        project_id=args.project_id,
        breaker_check=not getattr(args, 'no_breaker_check', False),
        generate_reports=generate_reports,
        reports=args.reports,
        csv_report=csv_report,
        txt_report=txt_report,
        to_terminal=to_terminal,
        print_report=args.print_report
    )
    sys.exit(ret)


if __name__ == "__main__":
    main()

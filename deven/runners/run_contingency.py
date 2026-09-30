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
DevEN — Native Contingency Analysis Runner (CLI & Headless Automation)
Supports N-1 Line Outages, Transformer Outages, Generator Outages, and Bus Outages
===============================================================================

Usage Examples:
  1. Run All N-1 Contingencies:
     python run_contingency.py case.py --all
     DevEN_CA_Engine.exe case.py --all

  2. Run Top N Outages:
     python run_contingency.py case.py --top 5

  3. Outages of Specific Lines:
     python run_contingency.py case.py --lines 1,2,3 -o results_ca
===============================================================================
"""

import sys
import os
import argparse
import json
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
    from contingency_batch import ContingencyBatch, run_single_simulation, ReportConsolidator
except ImportError:
    from engines.contingency_batch import ContingencyBatch, run_single_simulation, ReportConsolidator

try:
    from power_flow_engine import PowerFlowEngine
except ImportError:
    from engines.power_flow_engine import PowerFlowEngine

try:
    from report_writer import ReportWriter
except ImportError:
    from utils.report_writer import ReportWriter

try:
    from license_manager import LicenseManager
except ImportError:
    from utils.license_manager import LicenseManager


def run_contingency(case_path, run_all=False, top_n=None, lines=None,
                    engine_choice="deven_nr", tol=0.000001, max_iter=20,
                    output_folder=None,
                    generate_reports=False, reports=None, csv_report=False, txt_report=False,
                    to_terminal=False, print_report=None):
    """Executes N-1 Contingency Analysis with license verification."""
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

    print("\n" + "=" * 80)
    print("⚡ DevEN N-1 CONTINGENCY ANALYSIS ENGINE (BATCH SCREENING)")
    print("=" * 80)
    print(f"📂 Loading Case: {case_path}")

    # Read case data for license check
    raw_data = InputReader.read_from_python(case_path)
    if not raw_data:
        print("\n❌ [ERROR] Failed to load case database.")
        return 1

    buses = raw_data.get('buses', {})
    n_buses = len(buses)

    # Cryptographic License Verification (CA)
    is_valid, lic_msg, lic_data = LicenseManager.verify_license(study_code="CA", num_buses=n_buses)
    if not is_valid:
        print("\n" + "=" * 80)
        print("🔒 DevEN COMMERCIAL LICENSE VERIFICATION FAILED")
        print("=" * 80)
        print(lic_msg)
        print("=" * 80 + "\n")
        return 1

    print(f"🔑 License Valid: {lic_msg}")

    # Initialize Contingency Batch
    batch = ContingencyBatch(os.path.abspath(case_path))
    if not batch.load_system():
        print("❌ [ERROR] Failed to initialize network in contingency engine.")
        return 1

    # Configure solver options
    eng_raw = engine_choice.lower()
    if "_" in eng_raw:
        parts = eng_raw.split("_", 1)
        batch.engine_choice = parts[0]
        batch.method = parts[1]
    else:
        batch.engine_choice = eng_raw
        batch.method = "nr"

    batch.tol = tol
    batch.max_iter = max_iter
    batch.v_init_base = "flat"
    batch.v_init_cont = "warm"

    all_contingencies = batch.get_all_contingencies()
    selected_contingencies = []

    if lines:
        target_lines = set(str(l).strip() for l in lines.split(",") if str(l).strip())
        for c in all_contingencies:
            lid = str(c.get('num', c.get('index', '')))
            if c.get('type') == 'line' and lid in target_lines:
                selected_contingencies.append(c)
        print(f"📋 Selected {len(selected_contingencies)} line outage contingencies.")
    elif top_n:
        selected_contingencies = all_contingencies[:int(top_n)]
        print(f"📋 Selected top {len(selected_contingencies)} contingencies.")
    elif run_all:
        selected_contingencies = all_contingencies
        print(f"📋 Running ALL {len(selected_contingencies)} contingencies.")
    else:
        # Default: First 10 or all if less than 10
        limit = min(10, len(all_contingencies))
        selected_contingencies = all_contingencies[:limit]
        print(f"📋 Running default {limit} contingencies (use --all to run all {len(all_contingencies)}).")

    if not selected_contingencies:
        print("⚠️ No matching contingencies found to execute.")
        return 0

    if not output_folder:
        output_folder = os.path.join(os.path.dirname(os.path.abspath(case_path)), f"{case_name}_CONTINGENCY")
    os.makedirs(output_folder, exist_ok=True)

    # 1. RUN BASE CASE
    print("\n" + "=" * 80)
    print(" 🚀 RUNNING BASE CASE (Pre-Contingency Benchmark)")
    print("=" * 80)
    batch.reset_to_base()
    bus_data_engine = batch.bus_data
    branch_data_engine = batch.branch_data
    full_data_engine = batch.original_data

    solver_meth = f"{batch.engine_choice}_{batch.method}" if '_' not in batch.method and batch.engine_choice in ('andes', 'deven') else batch.method
    engine = PowerFlowEngine(baseMVA=batch.baseMVA)
    engine.initialize(
        bus_data_engine, branch_data_engine, full_data=full_data_engine,
        solver_method=solver_meth, tol=batch.tol, max_iter=batch.max_iter,
        ignore_q_tol=batch.ignore_q_tol, ignore_islands=batch.ignore_islands,
        industry_std_pv=batch.industry_std_pv, v_init_mode="flat",
        fallback_opts=batch.fallback_opts
    )

    samples, valid_count = engine.run_batch(n_samples=1, variation_strength=0.0)
    if not samples:
        print("❌ Base Case Diverged! Check network parameters.")
        return 1

    batch.base_case_v_mag = samples[0].get('V_mag')
    batch.base_case_v_angle = samples[0].get('V_angle')

    if csv_report or txt_report:
        reporter = ReportWriter(engine, full_data_engine, samples, 0.0)
        if csv_report:
            reporter.write_csv_all_data(os.path.join(output_folder, "BASE_CASE_ALL_DATA.csv"))
        if txt_report:
            reporter.write_txt_summary(os.path.join(output_folder, "BASE_CASE_SUMMARY.txt"))
        print("✅ Base Case Solved & Saved Successfully.")
    else:
        print("✅ Base Case Solved Successfully.")

    # 2. RUN CONTINGENCY LOOP
    print("\n" + "=" * 80)
    print(f" ⚡ EXECUTING {len(selected_contingencies)} N-1 CONTINGENCIES")
    print("=" * 80)

    generated_files = []
    converged_cnt = 0
    violation_cnt = 0
    cont_status_list = []

    for idx, cont in enumerate(selected_contingencies, 1):
        disp = cont.get('display', cont.get('type', 'Contingency'))[:60]
        sys.stdout.write(f"  [{idx:>3}/{len(selected_contingencies)}] {disp:<60} ... ")
        sys.stdout.flush()

        c_samples, c_valid, c_eng, c_full_data, c_info = batch.run_single_contingency(cont, 0.0, 1)

        is_conv = c_samples and bool(c_samples[0].get('converged', True))
        status_str = "CONVERGED" if is_conv else "DIVERGED"
        cont_status_list.append((cont, status_str))
        if is_conv:
            converged_cnt += 1
            sys.stdout.write("[CONVERGED]\n")
        else:
            sys.stdout.write("[DIVERGED]\n")

        if generate_reports or csv_report or txt_report:
            run_single_simulation(
                c_eng, c_full_data, c_samples, c_valid,
                output_folder, c_info, 0.0, 1, case_name, generated_files
            )

    # 3. CONSOLIDATE REPORTS
    consolidated = None
    if generate_reports or csv_report or txt_report:
        consolidator = ReportConsolidator(output_folder, case_name)
        consolidated = consolidator.consolidate_all()

    # 4. TERMINAL SUMMARY / DIVERSION
    summary_lines = [
        "\n" + "=" * 80,
        "  CONTINGENCY ANALYSIS SUMMARY TABLE",
        "=" * 80,
        f"  Total Evaluated : {len(selected_contingencies)}",
        f"  Converged       : {converged_cnt}",
        f"  Diverged        : {len(selected_contingencies) - converged_cnt}",
        "-" * 80,
        f"{'#':<4} | {'Contingency ID / Outage':<56} | {'Status':<12}",
        "-" * 80,
    ]
    for idx, (cont, status) in enumerate(cont_status_list, 1):
        disp = cont.get('display', cont.get('name', cont.get('id', 'Unknown')))[:56]
        summary_lines.append(f"{idx:<4} | {disp:<56} | {status:<12}")
    summary_lines.append("=" * 80)
    summary_str = "\n".join(summary_lines)

    csv_rows = [["Index", "Contingency", "Status"]]
    for idx, (cont, status) in enumerate(cont_status_list, 1):
        disp = cont.get('display', cont.get('name', cont.get('id', 'Unknown')))
        csv_rows.append([idx, disp, status])
    csv_str = "\n".join([",".join(map(str, row)) for row in csv_rows])

    if print_report == 'csv':
        print("\n" + "=" * 80)
        print("  CONTINGENCY CSV REPORT (TERMINAL)")
        print("=" * 80)
        print(csv_str)
        print("=" * 80 + "\n")
    elif to_terminal or print_report in ('summary', 'txt', 'all') or not (generate_reports or csv_report or txt_report):
        print(summary_str)

    print("\n" + "=" * 80)
    print(" 🏁 BATCH CONTINGENCY ANALYSIS COMPLETE!")
    print("=" * 80)
    print(f"  Total Evaluated : {len(selected_contingencies)}")
    print(f"  Converged       : {converged_cnt}")
    print(f"  Diverged        : {len(selected_contingencies) - converged_cnt}")
    if generate_reports or csv_report or txt_report:
        print(f"  Results Folder  : {output_folder}")
        if consolidated:
            print(f"  Master Summary  : {os.path.basename(consolidated.get('csv', ''))}")
    else:
        print("  Simulation completed with zero report files written to disk (as configured).")
    print("=" * 80 + "\n")

    return 0


def main():

    _check_license_gate("CONTINGENCY")
    parser = argparse.ArgumentParser(
        description="DevEN Native Contingency Analysis Engine (N-1 Security Screening)",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("case", type=str, help="Input network case file (.py, .db)")
    parser.add_argument("--all", action="store_true", help="Run all available contingencies")
    parser.add_argument("--top", type=int, default=None, help="Run top N contingencies")
    parser.add_argument("--lines", type=str, default=None, help="Comma-separated line IDs (e.g. 1,2,3)")
    parser.add_argument("-e", "--engine", type=str, default="deven_nr", help="Solver engine (deven_nr, andes_nr, etc. default: deven_nr)")
    parser.add_argument("-t", "--tol", type=float, default=0.000001, help="Tolerance (default: 1e-6)")
    parser.add_argument("--max-iter", type=int, default=20, help="Max iterations (default: 20)")
    parser.add_argument("-o", "--output", type=str, default=None, help="Custom output directory")

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
                           help="Generate CSV results files")
    rep_group.add_argument("--txt", action="store_true", default=False,
                           help="Generate text summary report file (.txt)")
    rep_group.add_argument("--to-terminal", action="store_true", default=False,
                           help="Print simulation summary report directly to terminal / stdout")
    rep_group.add_argument("--print-report", type=str, default=None,
                           choices=["summary", "csv", "txt", "all"],
                           help="Divert specified report to terminal / stdout (e.g. --print-report summary)")

    args = parser.parse_args()

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

    ret = run_contingency(
        case_path=args.case,
        run_all=args.all,
        top_n=args.top,
        lines=args.lines,
        engine_choice=args.engine,
        tol=args.tol,
        max_iter=args.max_iter,
        output_folder=args.output,
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

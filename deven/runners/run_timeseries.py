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
DevEN — Chronological Time Series Power Flow Runner (CLI & Headless Automation)
Supports multi-timeline profiles, 13 missing-data imputation methods, warm-starting,
and full 3-Phase Unbalanced Time Series analysis.
===============================================================================

Usage Examples:
  1. 24-Hour Simulation with Hourly Steps (1-phase):
     python run_timeseries.py case.py -d 24 -s 1

  2. 7-Day Simulation with 15-Minute Steps:
     python run_timeseries.py case.py -d 7 --dur-unit Days -s 15 --step-unit Minutes

  3. 3-Phase Newton-Raphson, 24-Hour, custom load split:
     python run_timeseries.py case.py -d 24 -s 1 -e 3p_nr --load-dist custom --load-pct 40,30,30

  4. 3-Phase FBS with Q-limit disabled:
     python run_timeseries.py case.py -d 12 -s 0.5 -e 3p_fbs --no-enforce-q

  5. Custom Output Directory:
     python run_timeseries.py case.py -d 12 -o results_ts --tol 1e-6
===============================================================================
"""

import sys
import os
import argparse
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
    from time_series_engine import TimeSeriesEngine
except ImportError:
    from engines.time_series_engine import TimeSeriesEngine

try:
    from license_manager import LicenseManager
except ImportError:
    from utils.license_manager import LicenseManager


def run_ts(case_path, duration=24.0, dur_unit="Hours", step_size=1.0, step_unit="Hours",
           start_time="2026-01-01 00:00:00", imputation="linear",
           engine_choice="deven_nr", tol=0.000001, max_iter=20,
           v_init_base="flat", v_init_step="warm", output_folder=None,
           load_dist="equal", gen_dist="equal",
           load_pct=(33.333, 33.334, 33.333), gen_pct=(33.333, 33.334, 33.333),
           enforce_q=True,
           generate_reports=False, reports=None, csv_report=False, py_report=False, txt_report=False,
           to_terminal=False, print_report=None):
    """Executes Time Series Simulation with license verification.

    3-Phase arguments (load_dist, gen_dist, load_pct, gen_pct, enforce_q) are
    only active when a 3-phase engine is selected (3p_nr, 3p_fbs, deven_3p_nr,
    deven_3p_fbs, nr_3p, fbs_3p). They are silently ignored for 1-phase engines.
    """
    if not os.path.exists(case_path):
        print(f"\n[ERROR] Case file not found: {case_path}")
        return 1

    case_name = os.path.splitext(os.path.basename(case_path))[0]
    if case_name.endswith('_converted'):
        case_name = case_name[:-10]

    print("\n" + "=" * 80)
    print("  DevEN CHRONOLOGICAL TIME SERIES SIMULATION ENGINE")
    print("=" * 80)
    print(f"  Loading Case: {case_path}")

    # Read case data for license check
    data = InputReader.read_from_python(case_path)
    if not data:
        print("\n[ERROR] Failed to load case database.")
        return 1

    buses = data.get('buses', {})
    n_buses = len(buses)

    # Cryptographic License Verification (TS)
    is_valid, lic_msg, lic_data = LicenseManager.verify_license(study_code="TS", num_buses=n_buses)
    if not is_valid:
        print("\n" + "=" * 80)
        print("  DevEN COMMERCIAL LICENSE VERIFICATION FAILED")
        print("=" * 80)
        print(lic_msg)
        print("=" * 80 + "\n")
        return 1

    print(f"  License Valid: {lic_msg}")

    time_settings = {
        'duration': float(duration),
        'duration_unit': str(dur_unit),
        'step_size': float(step_size),
        'step_unit': str(step_unit),
        'start_time': str(start_time),
        'imputation_method': str(imputation),
    }

    if not output_folder:
        output_folder = os.path.join(os.path.dirname(os.path.abspath(case_path)),
                                     f"{case_name}_TIMESERIES")
    os.makedirs(output_folder, exist_ok=True)

    solver_settings = {
        'engine': engine_choice,
        'tol': float(tol),
        'max_iter': int(max_iter),
        'v_init_base': v_init_base,
        'v_init_step': v_init_step,
        'output_folder': output_folder,
        # ── 3-Phase options (ignored when 1-phase engine selected) ──────────
        'load_dist': load_dist,
        'gen_dist': gen_dist,
        'load_pct': tuple(load_pct),
        'gen_pct': tuple(gen_pct),
        'enforce_q_limits': bool(enforce_q),
        # ── Reporting options ──────────────────────────────────────────────
        'generate_reports': bool(generate_reports),
        'reports': reports,
        'csv_report': bool(csv_report),
        'py_report': bool(py_report),
        'txt_report': bool(txt_report),
        'to_terminal': bool(to_terminal),
        'print_report': print_report,
    }

    ts_engine = TimeSeriesEngine(
        input_file=os.path.abspath(case_path),
        time_settings=time_settings,
        solver_settings=solver_settings
    )
    results = ts_engine.run()

    print("\n" + "=" * 80)
    print("  TIME SERIES SIMULATION COMPLETED SUCCESSFULLY!")
    print("=" * 80)
    if generate_reports or csv_report or py_report or txt_report or (reports and reports.lower() != 'none'):
        print(f"  Results saved in: {output_folder}")
    else:
        print("  Simulation completed with zero report files written to disk (as configured).")
    print("=" * 80 + "\n")
    return 0


def main():

    _check_license_gate("TIMESERIES")
    parser = argparse.ArgumentParser(
        description="DevEN Chronological Time Series Power Flow Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
3-Phase Engine Choices:
  3p_nr          Newton-Raphson 3-Phase (default distribution method)
  3p_fbs         Forward-Backward Sweep 3-Phase
  deven_3p_nr    DevEN Sparse NR 3-Phase
  deven_3p_fbs   DevEN Sparse FBS 3-Phase

Load / Gen Distribution Rules (--load-dist / --gen-dist):
  equal          Split evenly across phases A, B, C (default)
  custom         Use percentages from --load-pct / --gen-pct
  single_phase   All load/gen on Phase A only
  two_phase      Split across Phase A and B only

Examples:
  python run_timeseries.py case.py -d 24 -s 1 -e deven_nr
  python run_timeseries.py case.py -d 24 -s 1 --print-report summary
  python run_timeseries.py case.py -d 24 -s 1 --reports csv
  python run_timeseries.py case.py -d 12 -s 0.5 -e 3p_fbs --no-enforce-q
"""
    )
    parser.add_argument("case", type=str, help="Input network case file (.py, .db)")
    parser.add_argument("-d", "--duration", type=float, default=24.0,
                        help="Simulation duration (default: 24)")
    parser.add_argument("--dur-unit", type=str, default="Hours",
                        help="Duration unit: Seconds | Minutes | Hours | Days | Weeks | Months | Years (default: Hours)")
    parser.add_argument("-s", "--step-size", type=float, default=1.0,
                        help="Step size value (default: 1.0)")
    parser.add_argument("--step-unit", type=str, default="Hours",
                        help="Step unit: Seconds | Minutes | Hours | Days (default: Hours)")
    parser.add_argument("--start-time", type=str, default="2026-01-01 00:00:00",
                        help="Simulation start timestamp (default: '2026-01-01 00:00:00')")
    parser.add_argument("--imputation", type=str, default="linear",
                        help="Missing data imputation: linear | forward | backward | mean | zero | "
                             "spline | gaussian | kalman | ... (default: linear)")
    parser.add_argument("-e", "--engine", type=str, default="deven_nr",
                        help="Solver engine: deven_nr | andes_nr | deven_fdxb | "
                             "3p_nr | 3p_fbs | deven_3p_nr | deven_3p_fbs (default: deven_nr)")
    parser.add_argument("-t", "--tol", type=float, default=0.000001,
                        help="Convergence tolerance (default: 1e-6)")
    parser.add_argument("--max-iter", type=int, default=20,
                        help="Max solver iterations per step (default: 20)")
    parser.add_argument("-o", "--output", type=str, default=None,
                        help="Custom output directory path")

    # ── Report Generation Options (Default: No files written to disk) ──────────
    rep_group = parser.add_argument_group("Reporting Options",
                                         "Controls for report generation and terminal output (Default: no reports written to disk).")
    rep_group.add_argument("--reports", type=str, default=None,
                           help="Comma-separated list of reports: csv, py, txt, all, none")
    rep_group.add_argument("--all-reports", action="store_true", default=False,
                           help="Generate all standard report files (CSV, Python, TXT)")
    rep_group.add_argument("--no-reports", action="store_true", default=False,
                           help="Disable saving report files to disk (default)")
    rep_group.add_argument("--csv", action="store_true", default=False,
                           help="Generate CSV results files")
    rep_group.add_argument("--py", dest="py_rep", action="store_true", default=False,
                           help="Generate Python results file (.py)")
    rep_group.add_argument("--txt", action="store_true", default=False,
                           help="Generate text summary report file (.txt)")
    rep_group.add_argument("--to-terminal", action="store_true", default=False,
                           help="Print simulation summary report directly to terminal / stdout")
    rep_group.add_argument("--print-report", type=str, default=None,
                           choices=["summary", "all"],
                           help="Divert specified report to terminal / stdout (e.g. --print-report summary)")

    # ── 3-Phase Engine Options ─────────────────────────────────────────────────
    phase3_group = parser.add_argument_group("3-Phase Engine Options",
                                             "Applicable only when a 3-phase engine is selected.")
    phase3_group.add_argument("--load-dist", type=str, default="equal",
                              metavar="RULE",
                              help="Load distribution rule: equal | custom | single_phase | two_phase "
                                   "(default: equal)")
    phase3_group.add_argument("--gen-dist", type=str, default="equal",
                              metavar="RULE",
                              help="Generation distribution rule: equal | custom "
                                   "(default: equal)")
    phase3_group.add_argument("--load-pct", type=str, default="33.333,33.334,33.333",
                              metavar="A,B,C",
                              help="Custom load split %%: 'A,B,C' must sum to ~100 "
                                   "(default: '33.333,33.334,33.333')")
    phase3_group.add_argument("--gen-pct", type=str, default="33.333,33.334,33.333",
                              metavar="A,B,C",
                              help="Custom gen split %%: 'A,B,C' must sum to ~100 "
                                   "(default: '33.333,33.334,33.333')")
    phase3_group.add_argument("--enforce-q", dest="enforce_q", action="store_true", default=True,
                              help="Enforce generator Q limits in 3-phase simulation (default: enabled)")
    phase3_group.add_argument("--no-enforce-q", dest="enforce_q", action="store_false",
                              help="Disable Q limit enforcement in 3-phase simulation")

    args = parser.parse_args()

    def _parse_pct(s):
        """Parse 'A,B,C' percentage string into a 3-tuple of floats."""
        try:
            parts = [float(x.strip()) for x in str(s).split(',')]
            if len(parts) == 3:
                return tuple(parts)
        except Exception:
            pass
        return (33.333, 33.334, 33.333)

    # Determine reporting flags
    csv_report = args.csv
    py_report = args.py_rep
    txt_report = args.txt
    generate_reports = args.all_reports

    if args.all_reports:
        csv_report = py_report = txt_report = True
        generate_reports = True
    elif args.no_reports:
        csv_report = py_report = txt_report = False
        generate_reports = False
    elif args.reports:
        rep_list = [r.strip().lower() for r in args.reports.split(',')]
        if 'all' in rep_list:
            csv_report = py_report = txt_report = True
            generate_reports = True
        elif 'none' in rep_list:
            csv_report = py_report = txt_report = False
            generate_reports = False
        else:
            if 'csv' in rep_list: csv_report = True
            if any(x in rep_list for x in ('py', 'python')): py_report = True
            if any(x in rep_list for x in ('txt', 'summary')): txt_report = True
            generate_reports = csv_report or py_report or txt_report
    else:
        generate_reports = csv_report or py_report or txt_report

    to_terminal = args.to_terminal or (args.print_report is not None)

    ret = run_ts(
        case_path=args.case,
        duration=args.duration,
        dur_unit=args.dur_unit,
        step_size=args.step_size,
        step_unit=args.step_unit,
        start_time=args.start_time,
        imputation=args.imputation,
        engine_choice=args.engine,
        tol=args.tol,
        max_iter=args.max_iter,
        output_folder=args.output,
        load_dist=args.load_dist,
        gen_dist=args.gen_dist,
        load_pct=_parse_pct(args.load_pct),
        gen_pct=_parse_pct(args.gen_pct),
        enforce_q=args.enforce_q,
        generate_reports=generate_reports,
        reports=args.reports,
        csv_report=csv_report,
        py_report=py_report,
        txt_report=txt_report,
        to_terminal=to_terminal,
        print_report=args.print_report,
    )
    sys.exit(ret)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
deven_api — Time Series Load Flow Analysis Runner
==================================================
Runs a 24-hour Time Series Load Flow simulation (hourly steps, flat 100% load profile)
via DevENSession. Writes CSV + TXT reports to the specified output folder.

Usage:
    python runners/run_tslfa.py <case_file> [output_folder]

Examples:
    python runners/run_tslfa.py E:/invlfa/Example/PSSE/bench.py results/bench/TS
    python runners/run_tslfa.py E:/invlfa/Example/PSSE/bench2.py results/bench2/TS
"""

import sys
import os

try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# Path Bootstrapping
_runners_dir = os.path.dirname(os.path.abspath(__file__))
_pkg_dir = os.path.dirname(_runners_dir)
_repo_dir = os.path.dirname(_pkg_dir)
for _d in (_repo_dir, _pkg_dir, _runners_dir):
    if _d not in sys.path:
        sys.path.insert(0, _d)

from deven.core.deven_api import DevENSession


def run_tslfa(case_path: str, output_folder: str) -> dict:
    """Run Time Series Load Flow (24 hours, 1-hour steps, flat 100% profile)."""
    os.makedirs(output_folder, exist_ok=True)

    print("\n" + "=" * 80)
    print("  DevEN TIME SERIES LOAD FLOW ANALYSIS (TS-LFA)")
    print("  Profile: 24-Hour, 1-Hour Steps, Flat 100% Load")
    print("=" * 80)
    print(f"  Case     : {case_path}")
    print(f"  Output   : {output_folder}")
    print("=" * 80)

    sess = DevENSession()
    print("\n[1/3] Loading case...")
    sess.load_case(case_path)
    print(f"      Buses loaded: {len(sess.grid.buses) if sess.grid else '?'}")

    print("\n[2/3] Running Time Series LFA (24h, 1h steps)...")
    result = sess.run_timeseries(
        duration=24,
        dur_unit="Hours",
        step_size=1.0,
        step_unit="Hours",
        engine="deven_nr",
        generate_reports=True,
        csv_report=True,
        txt_report=True,
        output_folder=output_folder,
        to_terminal=False,
    )

    print("\n[3/3] Time Series LFA Complete.")
    print(f"  Status   : {result.get('status', 'unknown')}")
    print(f"  Steps    : {result.get('steps_completed', '?')}")
    print(f"  Reports  : {output_folder}")
    print("=" * 80)
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_tslfa.py <case_file> [output_folder]")
        sys.exit(1)

    case = os.path.abspath(sys.argv[1])
    case_name = os.path.splitext(os.path.basename(case))[0].replace('_converted', '')

    out = os.path.abspath(sys.argv[2]) if len(sys.argv) >= 3 else \
        os.path.join(_root_dir, "results", case_name, "TS")

    run_tslfa(case, out)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
deven_api — Contingency Analysis Runner (N-1)
==============================================
Runs N-1 Contingency Analysis for a specific set of elements:
  - Lines      : IDs 1, 2, 3, 4  (4 line outages)
  - Transformers: IDs 1, 2        (2 transformer outages)
  Total: 6 contingencies per case

Uses ContingencyBatch directly to select both lines AND transformers.
Writes CSV + TXT reports to the specified output folder.

Usage:
    python runners/run_ca.py <case_file> [output_folder]

Examples:
    python runners/run_ca.py E:/invlfa/Example/PSSE/bench.py results/bench/CA
    python runners/run_ca.py E:/invlfa/Example/PSSE/bench2.py results/bench2/CA
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

# --- Target contingency element IDs ---
TARGET_LINES = {1, 2, 3, 4}          # Line IDs to outage (N-1)
TARGET_XFMRS = {1, 2}               # Transformer IDs to outage (N-1)


def run_ca(case_path: str, output_folder: str) -> dict:
    """
    Run Contingency Analysis for Lines 1-4 + Transformers 1-2.
    Uses ContingencyBatch directly to support mixed line + transformer selection.
    """
    os.makedirs(output_folder, exist_ok=True)

    print("\n" + "=" * 80)
    print("  DevEN N-1 CONTINGENCY ANALYSIS (CA)")
    print(f"  Lines: {sorted(TARGET_LINES)}   Transformers: {sorted(TARGET_XFMRS)}")
    print("=" * 80)
    print(f"  Case     : {case_path}")
    print(f"  Output   : {output_folder}")
    print("=" * 80)

    # ── Import engine components ──────────────────────────────────────────────
    try:
        from deven.engines.contingency_batch import ContingencyBatch, run_single_simulation, ReportConsolidator
        from deven.engines.power_flow_engine import PowerFlowEngine
        from deven.utils.report_writer import ReportWriter
    except ImportError:
        from engines.contingency_batch import ContingencyBatch, run_single_simulation, ReportConsolidator
        from engines.power_flow_engine import PowerFlowEngine
        from utils.report_writer import ReportWriter

    # ── Load system into ContingencyBatch ────────────────────────────────────
    print("\n[1/4] Loading case into ContingencyBatch...")
    batch = ContingencyBatch(os.path.abspath(case_path))
    if not batch.load_system():
        print("  ERROR: Failed to initialize network in contingency engine.")
        return {"status": "failed", "error": "load_system() returned False"}

    batch.engine_choice = "deven"
    batch.method = "nr"
    batch.tol = 1e-6
    batch.max_iter = 50
    batch.v_init_base = "flat"
    batch.v_init_cont = "warm"

    # ── Build targeted contingency list (lines + transformers) ───────────────
    print("\n[2/4] Building contingency list...")
    all_contingencies = batch.get_all_contingencies()
    selected = []
    for c in all_contingencies:
        ctype = c.get('type', '')
        cnum = c.get('num', '')
        try:
            cnum_int = int(cnum)
        except (ValueError, TypeError):
            cnum_int = None

        if ctype == 'line' and cnum_int in TARGET_LINES:
            selected.append(c)
        elif ctype == 'transformer' and cnum_int in TARGET_XFMRS:
            selected.append(c)

    if not selected:
        print("  WARNING: No matching contingencies found in the case file.")
        print(f"  Available types: {set(c.get('type') for c in all_contingencies[:20])}")
        return {"status": "no_contingencies"}

    print(f"  Selected {len(selected)} contingencies:")
    for c in selected:
        print(f"    [{c.get('type'):12s}] ID={c.get('num')}  {c.get('display','').strip()}")

    # ── Run Base Case ─────────────────────────────────────────────────────────
    print("\n[3/4] Solving Base Case...")
    batch.reset_to_base()
    bus_data = batch.bus_data
    branch_data = batch.branch_data
    full_data = batch.original_data

    solver_meth = f"{batch.engine_choice}_{batch.method}"
    engine = PowerFlowEngine(baseMVA=batch.baseMVA)
    engine.initialize(
        bus_data, branch_data, full_data=full_data,
        solver_method=solver_meth, tol=batch.tol, max_iter=batch.max_iter,
        v_init_mode="flat"
    )
    samples, valid_count = engine.run_batch(n_samples=1, variation_strength=0.0)
    if not samples:
        print("  ERROR: Base case diverged!")
        return {"status": "failed", "error": "base_case_diverged"}

    batch.base_case_v_mag = samples[0].get('V_mag')
    batch.base_case_v_angle = samples[0].get('V_angle')

    # Write base case reports
    base_csv = os.path.join(output_folder, "BASE_CASE_ALL_DATA.csv")
    base_txt = os.path.join(output_folder, "BASE_CASE_SUMMARY.txt")
    reporter = ReportWriter(engine, full_data, samples, 0.0)
    reporter.write_csv_all_data(base_csv)
    reporter.write_txt_summary(base_txt)
    print(f"  Base case solved and saved.")

    # ── Run N-1 Contingency Loop ──────────────────────────────────────────────
    case_name = os.path.splitext(os.path.basename(case_path))[0].replace('_converted', '')
    print(f"\n[4/4] Running {len(selected)} N-1 contingencies...")
    print("-" * 80)

    generated_files = []
    converged_cnt = 0
    cont_status_list = []

    for idx, cont in enumerate(selected, 1):
        disp = cont.get('display', cont.get('type', 'Contingency'))[:60]
        sys.stdout.write(f"  [{idx:>2}/{len(selected)}] {disp:<60} ... ")
        sys.stdout.flush()

        c_samples, c_valid, c_eng, c_full_data, c_info = batch.run_single_contingency(cont, 0.0, 1)
        is_conv = c_samples and bool(c_samples[0].get('converged', True))
        status_str = "CONVERGED" if is_conv else "DIVERGED"
        cont_status_list.append((cont, status_str))
        if is_conv:
            converged_cnt += 1
        sys.stdout.write(f"[{status_str}]\n")

        run_single_simulation(
            c_eng, c_full_data, c_samples, c_valid,
            output_folder, c_info, 0.0, 1, case_name, generated_files
        )

    # ── Consolidate Reports ───────────────────────────────────────────────────
    try:
        consolidator = ReportConsolidator(output_folder, case_name)
        consolidated = consolidator.consolidate_all()
    except Exception as e:
        consolidated = {}
        print(f"  [WARN] Report consolidation failed: {e}")

    # ── Summary Table ─────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("  CONTINGENCY ANALYSIS SUMMARY")
    print("=" * 80)
    print(f"  {'#':<3}  {'Type':<14}  {'Element ID':<12}  {'Description':<36}  {'Status'}")
    print("  " + "-" * 75)
    for idx, (cont, status) in enumerate(cont_status_list, 1):
        ctype = cont.get('type', '')
        cnum = cont.get('num', '')
        disp = cont.get('display', cont.get('name', '')).strip()[:36]
        mark = "OK" if status == "CONVERGED" else "**DIVERGED**"
        print(f"  {idx:<3}  {ctype:<14}  {str(cnum):<12}  {disp:<36}  {mark}")
    print("  " + "-" * 75)
    print(f"  Total Evaluated : {len(selected)}")
    print(f"  Converged       : {converged_cnt}")
    print(f"  Diverged        : {len(selected) - converged_cnt}")
    print(f"  Reports Folder  : {output_folder}")
    if consolidated:
        print(f"  Master Summary  : {os.path.basename(consolidated.get('csv', ''))}")
    print("=" * 80)

    return {
        "status": "completed",
        "total": len(selected),
        "converged": converged_cnt,
        "diverged": len(selected) - converged_cnt,
        "output_folder": output_folder,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_ca.py <case_file> [output_folder]")
        sys.exit(1)

    case = os.path.abspath(sys.argv[1])
    case_name = os.path.splitext(os.path.basename(case))[0].replace('_converted', '')

    out = os.path.abspath(sys.argv[2]) if len(sys.argv) >= 3 else \
        os.path.join(_root_dir, "results", case_name, "CA")

    result = run_ca(case, out)
    sys.exit(0 if result.get("status") in ("completed", "no_contingencies") else 1)

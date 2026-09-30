# DevEN Path Bootstrapper
import sys
import os

try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

_root_dir = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(_root_dir) in ('engines', 'utils', 'cli'):
    _root_dir = os.path.dirname(_root_dir)
if _root_dir not in sys.path:
    sys.path.insert(0, _root_dir)
for _sub in ('engines', 'utils', 'cli'):
    _p = os.path.join(_root_dir, _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)

"""
DevEN Direct Batch Contingency Runner
Executes selected contingencies programmatically without interactive menu prompts or stdin piping.
Supports all 22 solver & reporting options, flat start recovery pipeline, and voltage init strategies.
"""

import argparse
import json
import os
from datetime import datetime

try:
    from engines.contingency_batch import ContingencyBatch, run_single_simulation, ReportConsolidator
except ImportError:
    from contingency_batch import ContingencyBatch, run_single_simulation, ReportConsolidator

try:
    from utils.input_reader import InputReader
except ImportError:
    from input_reader import InputReader

try:
    from engines.power_flow_engine import PowerFlowEngine
except ImportError:
    from power_flow_engine import PowerFlowEngine

try:
    from utils.report_writer import ReportWriter
except ImportError:
    from report_writer import ReportWriter


def main():
    parser = argparse.ArgumentParser(description="DevEN Direct Batch Contingency Runner")
    parser.add_argument("-i", "--input", type=str, required=True, help="Input python case file")
    parser.add_argument("-s", "--selected", type=str, default="", help="JSON string or file path containing selected contingency dicts")
    parser.add_argument("--all", action="store_true", help="Run ALL contingencies")
    parser.add_argument("-v", "--variation", type=float, default=10.0, help="Variation strength percentage")
    parser.add_argument("-n", "--samples", type=int, default=200, help="Samples per contingency")
    parser.add_argument("-e", "--engine", type=str, default="andes_nr", help="Engine choice (andes_nr, deven_nr, inverse, etc.)")
    parser.add_argument("-m", "--method", type=str, default="nr", help="Solver method")
    parser.add_argument("-t", "--tol", type=float, default=0.000001, help="Tolerance")
    parser.add_argument("--max-iter", type=int, default=20, help="Max iterations")
    parser.add_argument("--v-init-base", type=str, default="flat", help="Base case voltage init (flat or initial)")
    parser.add_argument("--v-init-cont", type=str, default="warm", help="Contingency voltage init (warm, flat, initial, seq_warm)")
    parser.add_argument("--ignore-q", action="store_true", help="Ignore Q limits / tolerance")
    parser.add_argument("--industry-std-pv", dest="industry_std_pv", action="store_true", default=True, help="Industry standard PV mode")
    parser.add_argument("--no-industry-std-pv", dest="industry_std_pv", action="store_false")
    parser.add_argument("--ignore-islands", dest="ignore_islands", action="store_true", default=True, help="Ignore floating islands")
    parser.add_argument("--no-ignore-islands", dest="ignore_islands", action="store_false")
    parser.add_argument("--fb-enable", dest="fb_enable", action="store_true", default=True, help="Enable multi-stage fallback pipeline")
    parser.add_argument("--no-fb", dest="fb_enable", action="store_false")
    parser.add_argument("--fb-stage-max-iter", type=int, default=20, help="Fallback stage max iters")
    parser.add_argument("--fb-dc-angle", dest="fb_dc_angle", action="store_true", default=True)
    parser.add_argument("--fb-q-delay", dest="fb_q_delay", action="store_true", default=True)
    parser.add_argument("--fb-step-damping", dest="fb_step_damping", action="store_true", default=True)
    parser.add_argument("--fb-lm", dest="fb_lm", action="store_true", default=True)
    parser.add_argument("--fb-homotopy", dest="fb_homotopy", action="store_true", default=True)
    parser.add_argument("--fb-diagnostics", dest="fb_diagnostics", action="store_true", default=True)
    parser.add_argument("--ieee-report", dest="ieee_report", action="store_true", default=True)
    parser.add_argument("--cea-report", dest="cea_report", action="store_true", default=True)
    parser.add_argument("--overwrite", dest="overwrite", action="store_true", default=True)
    parser.add_argument("--no-overwrite", dest="overwrite", action="store_false")
    parser.add_argument("--save-samples", action="store_true", default=False)
    parser.add_argument("-o", "--output", type=str, default="", help="Output directory")

    args = parser.parse_args()

    input_file = os.path.abspath(args.input)
    if not os.path.isfile(input_file):
        print(f"❌ Input file not found: {input_file}")
        sys.exit(1)

    batch = ContingencyBatch(input_file)
    
    # Parse engine and method
    eng_raw = args.engine.lower()
    if "_" in eng_raw:
        eng_parts = eng_raw.split("_", 1)
        batch.engine_choice = eng_parts[0]
        batch.method = eng_parts[1]
    else:
        batch.engine_choice = eng_raw
        batch.method = args.method.lower()

    batch.tol = args.tol
    batch.max_iter = args.max_iter
    batch.v_init_base = args.v_init_base
    batch.v_init_cont = args.v_init_cont
    batch.ignore_q_tol = args.ignore_q
    batch.ignore_islands = args.ignore_islands
    batch.industry_std_pv = args.industry_std_pv
    batch.fallback_opts = {
        'enable_fallback_pipeline': args.fb_enable,
        'stage_max_iter': min(int(args.max_iter), int(args.fb_stage_max_iter)) if args.fb_stage_max_iter else int(args.max_iter),
        'use_dc_angle_init': args.fb_dc_angle,
        'use_postponed_q_limits': args.fb_q_delay,
        'use_step_damping': args.fb_step_damping,
        'use_levenberg_marquardt': args.fb_lm,
        'use_homotopy_ramping': args.fb_homotopy,
        'use_diagnostics': args.fb_diagnostics
    }

    if not batch.load_system():
        print("❌ Failed to load input system file")
        sys.exit(1)

    all_contingencies = batch.get_all_contingencies()
    selected_contingencies = []

    if args.all:
        selected_contingencies = all_contingencies
        print(f"📋 Running ALL {len(selected_contingencies)} contingencies")
    elif args.selected:
        selected_list = []
        if os.path.isfile(args.selected):
            with open(args.selected, 'r', encoding='utf-8') as f:
                selected_list = json.load(f)
        else:
            try:
                selected_list = json.loads(args.selected)
            except Exception as e:
                print(f"❌ Failed to parse JSON selected contingencies: {e}")
                sys.exit(1)

        # Match selected dicts with all_contingencies
        for sel in selected_list:
            sel_type = sel.get('type', '').lower()
            sel_num = sel.get('num')
            sel_name = sel.get('name', '')
            matched = False

            for c in all_contingencies:
                type_match = (c['type'] == sel_type) or (c['type'] in ('generator', 'sync_motor') and sel_type in ('generator', 'sync_motor'))
                if type_match and (c['num'] == sel_num or (sel_name and c['name'] == sel_name)):
                    selected_contingencies.append(c)
                    matched = True
                    break

            if not matched:
                selected_contingencies.append({
                    'type': sel_type,
                    'num': sel_num,
                    'name': sel_name or f"{sel_type.upper()}_{sel_num}",
                    'display': f"Outage of {sel_type.upper()} {sel_num}"
                })

        print(f"📋 Matched & Running {len(selected_contingencies)} selected contingencies")
    else:
        print("⚠️ No contingencies specified. Running ALL contingencies by default.")
        selected_contingencies = all_contingencies

    # Determine Output directory
    if args.output:
        output_folder = os.path.abspath(args.output)
    else:
        case_name = batch.case_name
        output_folder = os.path.join(os.path.dirname(input_file), f"{case_name}_CONTINGENCY")

    os.makedirs(output_folder, exist_ok=True)
    batch.output_folder = output_folder
    generated_files = []

    variation = args.variation / 100.0
    n_samples = args.samples if batch.engine_choice == 'inverse' else 1

    print(f"\n📂 Output folder: {output_folder}")
    print(f"⚙️ Engine: {batch.engine_choice.upper()} | Method: {batch.method.upper()} | Tol: {args.tol} | Max Iter: {args.max_iter}")
    print(f"⚡ Base Init: {batch.v_init_base.upper()} | Contingency Init: {batch.v_init_cont.upper()}")
    print(f"🚀 Flat Start Recovery Pipeline: {'ENABLED' if args.fb_enable else 'DISABLED'}")
    if batch.engine_choice == 'inverse':
        print(f"📊 Variation: {args.variation}% | Samples per contingency: {n_samples}")

    # =========================================================
    # BASE CASE
    # =========================================================
    print(f"\n{'='*80}")
    print(f" RUNNING BASE CASE (No Contingency)")
    print(f"{'='*80}")

    batch.reset_to_base()
    bus_data_engine = batch.bus_data
    branch_data_engine = batch.branch_data
    full_data_engine = batch.original_data

    v_init_mode_base = 'initial' if 'initial' in str(batch.v_init_base).lower() else 'flat'
    solver_meth = f"{batch.engine_choice}_{batch.method}" if '_' not in batch.method and batch.engine_choice in ('andes', 'deven') else batch.method
    if batch.engine_choice == 'inverse': solver_meth = 'inverse'

    engine = PowerFlowEngine(baseMVA=batch.baseMVA)
    engine.initialize(
        bus_data_engine, branch_data_engine, full_data=full_data_engine,
        solver_method=solver_meth, tol=batch.tol, max_iter=batch.max_iter,
        ignore_q_tol=batch.ignore_q_tol, ignore_islands=batch.ignore_islands,
        industry_std_pv=batch.industry_std_pv, v_init_mode=v_init_mode_base,
        fallback_opts=batch.fallback_opts
    )

    samples, valid_count = engine.run_batch(n_samples=n_samples, variation_strength=variation)

    # Save Base Case Solution for Warm Starting
    if samples:
        batch.base_case_v_mag = samples[0].get('V_mag')
        batch.base_case_v_angle = samples[0].get('V_angle')

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_prefix = "BASE_CASE" if args.overwrite else f"BASE_CASE_{timestamp}"
    
    reporter = ReportWriter(engine, full_data_engine, samples, variation)
    reporter.write_csv_all_data(os.path.join(output_folder, f"{base_prefix}_ALL_DATA.csv"))
    reporter.write_py_all_data(os.path.join(output_folder, f"{base_prefix}_ALL_DATA.py"))
    reporter.write_txt_summary(os.path.join(output_folder, f"{base_prefix}_SUMMARY.txt"))

    if args.ieee_report:
        reporter.write_ieee_report(os.path.join(output_folder, f"{base_prefix}_IEEE.IEEE"))
    if args.cea_report:
        reporter.write_cea_report(os.path.join(output_folder, f"{base_prefix}_CEA.cea"))

    with open(os.path.join(output_folder, f"{base_prefix}_CONTINGENCY_INFO.txt"), 'w', encoding='utf-8') as f:
        f.write("="*80 + "\n")
        f.write("BASE CASE - NO CONTINGENCY\n")
        f.write("="*80 + "\n")
        f.write(f"Description: Base Case - All elements in normal operation\n")
        f.write(f"Base Case Voltage Init: {batch.v_init_base.upper()}\n")
        f.write(f"Valid Samples: {valid_count}/{n_samples}\n")
        f.write("="*80 + "\n")

    print(f"✅ Base Case completed")

    # =========================================================
    # CONTINGENCIES LOOP
    # =========================================================
    case_name = batch.case_name
    for idx, contingency in enumerate(selected_contingencies, 1):
        print(f"\n{'='*80}")
        print(f" CONTINGENCY {idx}/{len(selected_contingencies)}: {contingency.get('display', '')[:70]}")
        print(f"{'='*80}")

        samples, valid_count, engine, full_data_after, info = batch.run_single_contingency(
            contingency, variation, n_samples
        )

        run_single_simulation(engine, full_data_after, samples, valid_count, 
                             output_folder, info, variation, n_samples, case_name, generated_files)

        print(f"✅ Contingency {idx}/{len(selected_contingencies)} completed")

    # =========================================================
    # CONSOLIDATE ALL REPORTS
    # =========================================================
    consolidator = ReportConsolidator(output_folder, case_name)
    consolidated = consolidator.consolidate_all()

    print("\n" + "="*80)
    print(" BATCH CONTINGENCY ANALYSIS COMPLETE!")
    print("="*80)
    print(f"\n All results saved in: {output_folder}")
    if consolidated:
        print(f"    CSV Master: {os.path.basename(consolidated['csv'])}")
        print(f"    TXT Master: {os.path.basename(consolidated['txt'])}")
        print(f"    PY Master:  {os.path.basename(consolidated['py'])}")
    print("="*80)

if __name__ == "__main__":
    main()

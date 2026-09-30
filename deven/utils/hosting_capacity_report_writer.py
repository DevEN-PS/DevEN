# DevEN Path Bootstrapper
import sys
import os
import csv
import math
import json
from datetime import datetime

"""
DevEN Hosting Capacity & Injection Limit Report Writer
Generates complete step-by-step audit logs (.invout, .csv, .py) documenting Base Case,
every Bisection Iteration (N-0 status & all N-1 Contingencies), and Final Executive Summaries.
Supports incremental on-the-fly writing.
"""

class HostingCapacityReportWriter:
    def __init__(self, output_folder, case_name, v_min_limit=0.95, v_max_limit=1.05, branch_loading_limit=100.0):
        self.output_folder = output_folder
        self.case_name = case_name
        self.v_min_limit = float(v_min_limit)
        self.v_max_limit = float(v_max_limit)
        self.branch_loading_limit = float(branch_loading_limit)
        os.makedirs(self.output_folder, exist_ok=True)

        self.invout_path = os.path.join(self.output_folder, f"{self.case_name}_HOSTING_CAPACITY_REPORT.invout")
        self.summary_csv_path = os.path.join(self.output_folder, f"{self.case_name}_HOSTING_CAPACITY_SUMMARY.csv")
        self.detailed_csv_path = os.path.join(self.output_folder, f"{self.case_name}_HOSTING_CAPACITY_STEP_LOG.csv")
        self.py_results_path = os.path.join(self.output_folder, f"{self.case_name}_HOSTING_CAPACITY_RESULTS.py")

        # Initialize Files with Headers
        self._init_invout_header()
        self._init_csv_headers()

    def _init_invout_header(self):
        with open(self.invout_path, "w", encoding="utf-8") as f:
            f.write("=" * 130 + "\n")
            f.write("⚡ DevEN INVERSE & HOSTING CAPACITY INJECTION LIMIT SYSTEM OUTPUT REPORT (.INVOUT)\n")
            f.write(f"Case: {self.case_name} | Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Security Criteria: N-0 Base Grid Loading <= {self.branch_loading_limit:.1f}% & Voltage [{self.v_min_limit:.2f} - {self.v_max_limit:.2f} pu] + N-1 Monitored Branch Contingencies\n")
            f.write("=" * 130 + "\n\n")

    def _init_csv_headers(self):
        with open(self.summary_csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Bus_ID", "Bus_Name", "Base_kV", "Target_MW", "Max_Feasible_MW",
                "Feasibility_Status", "Binding_Constraint", "Critical_N1_Outage",
                "V_at_Max_MW_pu", "Max_Branch_Loading_pct", "Iterations_Count"
            ])

        with open(self.detailed_csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Candidate_Bus", "Iteration", "P_Test_MW", "N0_Pass", "N0_Max_Loading_pct",
                "N0_Crit_Branch", "N0_Vmin_pu", "N0_Vmax_pu", "N1_Outages_Tested",
                "N1_Failed_Count", "Step_Verdict", "Updated_P_Range"
            ])

    def log_base_case(self, base_case_info):
        """Append Pre-Injection Base Case (0 MW) results to .invout"""
        with open(self.invout_path, "a", encoding="utf-8") as f:
            f.write("--- [STAGE 1: PRE-INJECTION HEALTHY BASE CASE AUDIT (0.00 MW)] ---\n")
            f.write(f"   • Total System Generation  : {base_case_info.get('total_gen_mw', 0.0):>10.2f} MW\n")
            f.write(f"   • Total System Load Demand : {base_case_info.get('total_load_mw', 0.0):>10.2f} MW\n")
            f.write(f"   • Total System Losses      : {base_case_info.get('total_loss_mw', 0.0):>10.2f} MW ({base_case_info.get('loss_pct', 0.0):.2f}%)\n")
            f.write(f"   • Maximum Branch Loading   : {base_case_info.get('max_loading_pct', 0.0):>10.2f}% ({base_case_info.get('max_loading_branch', 'N/A')})\n")
            f.write(f"   • Minimum Substation Voltage: {base_case_info.get('v_min_pu', 1.0):>10.4f} pu (Bus {base_case_info.get('v_min_bus', 'N/A')})\n")
            f.write(f"   • Maximum Substation Voltage: {base_case_info.get('v_max_pu', 1.0):>10.4f} pu (Bus {base_case_info.get('v_max_bus', 'N/A')})\n")
            f.write("-" * 130 + "\n\n")

    def log_bus_header(self, bus_id, bus_name, base_kv, target_mw):
        """Log candidate bus assessment header"""
        with open(self.invout_path, "a", encoding="utf-8") as f:
            f.write("\n" + "=" * 130 + "\n")
            f.write(f"🔍 EVALUATING CANDIDATE INJECTION BUS: Bus {bus_id} ({bus_name}) | Voltage: {base_kv:.1f} kV | Target: {target_mw:.1f} MW\n")
            f.write("-" * 130 + "\n")

    def log_iteration_step(self, cand_bus, iter_idx, p_test, n0_result, n1_results, verdict, updated_range):
        """Log one bisection step to detailed CSV and .invout"""
        # 1. Append to Detailed CSV
        n0_pass = n0_result.get('pass', False)
        n0_status = "✅ PASS" if n0_pass else "❌ FAIL"
        n0_load = n0_result.get('max_loading_pct', 0.0)
        n0_branch = n0_result.get('max_loading_branch', 'N/A')
        n0_vmin = n0_result.get('v_min_pu', 1.0)
        n0_vmax = n0_result.get('v_max_pu', 1.0)

        n1_failed_outages = [r for r in n1_results if not r.get('pass', False)]

        with open(self.detailed_csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                cand_bus, iter_idx, f"{p_test:.2f}",
                "PASS" if n0_pass else "FAIL", f"{n0_load:.2f}", n0_branch,
                f"{n0_vmin:.4f}", f"{n0_vmax:.4f}", len(n1_results), len(n1_failed_outages),
                verdict, f"[{updated_range[0]:.2f} - {updated_range[1]:.2f}]"
            ])

        # 2. Append to Master .invout Report immediately
        with open(self.invout_path, "a", encoding="utf-8") as f:
            f.write(f"\n   [Step {iter_idx:02d}] Testing Injection P_test = {p_test:8.2f} MW  -->  Verdict: {verdict:<10} (Search Range: {updated_range[0]:.2f} to {updated_range[1]:.2f} MW)\n")
            f.write(f"      ├─ N-0 Base Check: {n0_status} | Max Loading: {n0_load:6.2f}% ({n0_branch}) | V_min: {n0_vmin:.4f} pu | V_max: {n0_vmax:.4f} pu\n")
            
            n0_ovs = n0_result.get('overloads', [])
            n0_vvs = n0_result.get('voltage_violations', [])
            if n0_ovs:
                f.write(f"      │  🔥 Thermal Overloads ({len(n0_ovs)} branches > {self.branch_loading_limit:.1f}%):\n")
                for ov in n0_ovs[:6]:
                    hop_str = f"[Hop {ov['hop']}] " if ov.get('hop') else ""
                    f.write(f"      │     • {hop_str}{ov['name']} ({ov['from_bus']}->{ov['to_bus']}): {ov['loading_pct']:.2f}% (Flow: {ov['flow_mva']:.1f} MVA / Rating: {ov['rating_mva']:.1f} MVA)\n")
            if n0_vvs:
                f.write(f"      │  ⚡ Voltage Violations ({len(n0_vvs)} buses outside [{self.v_min_limit:.2f} - {self.v_max_limit:.2f} pu]):\n")
                for vv in n0_vvs[:6]:
                    hop_str = f"[Hop {vv['hop']}] " if vv.get('hop') else ""
                    f.write(f"      │     • {hop_str}Bus {vv['bus']} ({vv['name']}): {vv['v_mag']:.4f} pu ({vv['type']} limit: {vv['limit']:.2f} pu)\n")

            if n0_pass and n1_results:
                f.write(f"      └─ N-1 Contingency Check ({len(n1_results)} outages tested, {len(n1_failed_outages)} failed):\n")
                # Print table of N-1 outages tested in this iteration with Hop diagnostics
                f.write(f"         {'#':<4} {'Outage Element [Hop]':<35} {'Status':<8} {'Post-Fault Max Loading [Hop]':<35} {'Post-Fault V_min [Hop]':<26} {'Reason/Bottleneck'}\n")
                f.write(f"         {'-'*125}\n")
                for idx, n1 in enumerate(n1_results, 1):
                    st = "PASS" if n1.get('pass', False) else "FAIL"
                    st_icon = "✅ PASS" if n1.get('pass', False) else "❌ FAIL"
                    out_hop_str = f"[Hop {n1.get('outage_hop', 1)}] " if n1.get('outage_hop') else ""
                    outage_display = f"{out_hop_str}{n1.get('outage_name', 'N/A')}"
                    
                    ld_hop_str = f"[Hop {n1.get('max_loading_hop')}] " if n1.get('max_loading_hop') else ""
                    max_ld = f"{ld_hop_str}{n1.get('max_loading_pct', 0.0):.2f}% ({n1.get('max_loading_branch', 'N/A')[:18]})"
                    
                    vm_hop_str = f"[Hop {n1.get('v_min_hop')}] " if n1.get('v_min_hop') else ""
                    vmin_str = f"{vm_hop_str}{n1.get('v_min_pu', 1.0):.4f} pu (Bus {n1.get('v_min_bus', '')})"
                    
                    reason = n1.get('fail_reason', 'OK (Within Limits)')
                    f.write(f"         {idx:<4} {outage_display[:35]:<35} {st_icon:<8} {max_ld[:35]:<35} {vmin_str[:26]:<26} {reason}\n")
            elif not n0_pass:
                f.write(f"      └─ N-1 Contingencies: SKIPPED (N-0 Base Check Failed: {n0_result.get('fail_reason', 'Limits Violated')})\n")

    def log_bus_final_summary(self, bus_summary):
        """Append candidate bus final summary to summary CSV and .invout"""
        # 1. Summary CSV
        with open(self.summary_csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                bus_summary['bus_id'], bus_summary['bus_name'], f"{bus_summary['base_kV']:.1f}",
                f"{bus_summary['target_mw']:.2f}", f"{bus_summary['max_feasible_mw']:.2f}",
                bus_summary['status'], bus_summary['binding_constraint'], bus_summary['critical_n1_outage'],
                f"{bus_summary['v_at_max_pu']:.4f}", f"{bus_summary['max_loading_pct']:.2f}",
                bus_summary['iterations_count']
            ])

        # 2. Append to .invout
        with open(self.invout_path, "a", encoding="utf-8") as f:
            f.write("\n" + "=" * 130 + "\n")
            f.write(f"🏁 RESULT FOR BUS {bus_summary['bus_id']} ({bus_summary['bus_name']}) — {bus_summary['base_kV']:.1f} kV:\n")
            f.write(f"   • Maximum Feasible Injection : {bus_summary['max_feasible_mw']:>10.2f} MW  (Target: {bus_summary['target_mw']:.2f} MW)\n")
            f.write(f"   • Allocation Status          : {bus_summary['status']}\n")
            f.write(f"   • Most Binding Constraint    : {bus_summary['binding_constraint']}\n")
            f.write(f"   • Most Critical Outage       : {bus_summary['critical_n1_outage']}\n")
            f.write(f"   • Solved Voltage at Bus Point: {bus_summary['v_at_max_pu']:.4f} pu ({(bus_summary['v_at_max_pu']*bus_summary['base_kV']):.2f} kV)\n")
            f.write(f"   • Total Bisection Iterations : {bus_summary['iterations_count']}\n")
            f.write("=" * 130 + "\n\n")

    def finalize_executive_report(self, all_buses_summaries, total_duration_sec):
        """
        Writes the master executive comparison table across all candidate buses at top of .invout
        and generates the Python database file.
        """
        # Rewrite .invout to place executive summary directly after header
        temp_path = self.invout_path + ".tmp"
        with open(self.invout_path, "r", encoding="utf-8") as fin:
            existing_content = fin.read()

        with open(self.invout_path, "w", encoding="utf-8") as fout:
            fout.write("=" * 130 + "\n")
            fout.write("⚡ DevEN INVERSE & HOSTING CAPACITY INJECTION LIMIT SYSTEM OUTPUT REPORT (.INVOUT)\n")
            fout.write(f"Case: {self.case_name} | Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Elapsed: {total_duration_sec:.2f}s\n")
            fout.write(f"Security Criteria: N-0 Base Loading <= {self.branch_loading_limit:.1f}% & Voltage [{self.v_min_limit:.2f} - {self.v_max_limit:.2f} pu] + N-1 Monitored Branch Outages\n")
            fout.write("=" * 130 + "\n\n")

            fout.write("📊 MASTER EXECUTIVE HOSTING CAPACITY COMPARISON TABLE\n")
            fout.write("-" * 130 + "\n")
            fout.write(f"{'Bus#':<6} {'Bus Name':<18} {'Base kV':<9} {'Target MW':<11} {'Max Feasible MW':<17} {'Status':<12} {'Critical Limiting Outage':<30} {'Limiting Bottleneck Element'}\n")
            fout.write("-" * 130 + "\n")
            for b in all_buses_summaries:
                fout.write(f"{b['bus_id']:<6} {str(b['bus_name'])[:18]:<18} {b['base_kV']:<9.1f} {b['target_mw']:<11.2f} "
                           f"{b['max_feasible_mw']:<17.2f} {b['status']:<12} {str(b['critical_n1_outage'])[:30]:<30} {b['binding_constraint']}\n")
            fout.write("=" * 130 + "\n\n")

            # Append the rest of the existing step-by-step audit trail
            cut_idx = -1
            markers = [
                "--- [STAGE 1: PRE-INJECTION",
                "📊 INITIAL PRE-INJECTION BASE CASE",
                "🔍 EVALUATING CANDIDATE INJECTION BUS"
            ]
            for m in markers:
                pos = existing_content.find(m)
                if pos != -1:
                    cut_idx = pos
                    break

            if cut_idx != -1:
                fout.write(existing_content[cut_idx:])
            else:
                fout.write(existing_content)

        # Generate Python database
        with open(self.py_results_path, "w", encoding="utf-8") as f:
            f.write('"""\n')
            f.write(f'DevEN Hosting Capacity Assessment Results — Python Database\n')
            f.write(f'Case: {self.case_name} | Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
            f.write('"""\n\n')
            f.write(f"CASE_NAME = '{self.case_name}'\n")
            f.write(f"TOTAL_BUSES_EVALUATED = {len(all_buses_summaries)}\n\n")
            f.write(f"HOSTING_CAPACITY_SUMMARY = {repr(all_buses_summaries)}\n")

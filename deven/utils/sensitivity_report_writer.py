"""
====================================================================================================
DevEN Grid Sensitivity Report & Export Writer (.SENOUT & CSV Matrices)
====================================================================================================
Generates:
  1. Master Formatted Sensitivity Audit Report (*_SENSITIVITY_REPORT.senout)
  2. PTDF Full Matrix CSV (*_PTDF_FULL_MATRIX.csv)
  3. LODF Full Matrix CSV (*_LODF_FULL_MATRIX.csv)
  4. Generator Shift Factor (GSF) Impact Ranking CSV (*_GENERATOR_IMPACT_RANKING.csv)
  5. Line Dominating Injection Corridors CSV (*_LINE_DOMINATING_INJECTIONS.csv)
  6. Rapid N-1 Contingency Screening Summary CSV (*_FAST_N1_SCREENING_SUMMARY.csv)
====================================================================================================
"""

import os
import csv
import datetime
import numpy as np


class SensitivityReportWriter:
    def __init__(self, engine, output_dir=None, case_name="System"):
        self.engine = engine
        self.case_name = case_name
        self.output_dir = output_dir or os.path.join(os.getcwd(), f"{self.case_name}_SENSITIVITY")
        os.makedirs(self.output_dir, exist_ok=True)

        self.timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def export_all_reports(self, screening_results=None, gen_sens=None, line_doms=None, elapsed_sec=0.0):
        """Generates all reports and exports CSV files into the destination folder."""
        # 1. Master Audit Report (.senout)
        senout_path = self.write_senout_report(screening_results, gen_sens, line_doms, elapsed_sec)

        # 2. PTDF Full Matrix CSV
        ptdf_path = self.export_ptdf_csv()

        # 3. LODF Full Matrix CSV
        lodf_path = self.export_lodf_csv()

        # 4. Generator GSF CSV
        gsf_path = self.export_generator_sensitivities_csv(gen_sens)

        # 5. Line Dominators CSV
        dom_path = self.export_line_dominators_csv(line_doms)

        # 6. Fast N-1 Screening CSV
        n1_path = self.export_fast_n1_csv(screening_results)

        return {
            'output_dir': self.output_dir,
            'senout_path': senout_path,
            'ptdf_csv': ptdf_path,
            'lodf_csv': lodf_path,
            'gsf_csv': gsf_path,
            'dom_csv': dom_path,
            'n1_csv': n1_path
        }

    def write_senout_report(self, screening_results=None, gen_sens=None, line_doms=None, elapsed_sec=0.0):
        """Creates the formatted executive master .senout report."""
        report_filename = f"{self.case_name}_SENSITIVITY_REPORT.senout"
        report_path = os.path.join(self.output_dir, report_filename)

        num_buses = len(self.engine.bus_ids)
        num_branches = len(self.engine.branches)
        slack_bus = self.engine.slack_bus
        base_source = self.engine.base_flow_source

        with open(report_path, "w", encoding="utf-8") as f:
            f.write("=" * 130 + "\n")
            f.write("⚡ DevEN GRID SENSITIVITY ANALYZER — PTDF & LODF SYSTEM OUTPUT REPORT (.SENOUT)\n")
            f.write(f"Case: {self.case_name} | Generated: {self.timestamp} | Computation Time: {elapsed_sec:.4f}s\n")
            f.write(f"Reference/Slack Bus: Bus {slack_bus} ({self.engine.bus_names.get(slack_bus, '')}) | "
                    f"Base Flow Source: {base_source} Power Flow | Tap Model: {self.engine.config.tap_model}\n")
            f.write("=" * 130 + "\n\n")

            # Executive Network Summary
            f.write("📊 1. SYSTEM TOPOLOGY & PARAMETER SUMMARY\n")
            f.write("-" * 130 + "\n")
            f.write(f"   • Total System Buses           : {num_buses}\n")
            f.write(f"   • Monitored Transmission Lines : {sum(1 for b in self.engine.branches if b['type'] == 'line')}\n")
            f.write(f"   • Monitored Transformers       : {sum(1 for b in self.engine.branches if b['type'] == 'transformer')}\n")
            f.write(f"   • Three-Winding Star Branches  : {sum(1 for b in self.engine.branches if b['type'] == '3w_transformer')}\n")
            f.write(f"   • Series Compensators/Reactors : {sum(1 for b in self.engine.branches if b['type'] == 'series_reactor')}\n")
            f.write(f"   • Total Network Branches (L)   : {num_branches}\n")
            parallel_corridors = sum(1 for p, indices in self.engine.parallel_groups.items() if len(indices) > 1)
            f.write(f"   • Multi-Circuit Parallel Pairs : {parallel_corridors} corridors\n")
            radial_count = sum(1 for s in self.engine.status_flags.values() if s == 'RADIAL_TRIP')
            f.write(f"   • Radial / Cut-Edge Branches   : {radial_count} branches (Tripping causes islanding)\n")
            f.write("-" * 130 + "\n\n")

            # Generator Generation Shift Factors (GSF)
            if gen_sens is None:
                gen_sens = self.engine.rank_generator_sensitivities()

            f.write("🏭 2. GENERATOR SHIFT FACTORS (GSF) — TOP SENSITIVE TRANSMISSION CORRIDORS\n")
            f.write("-" * 130 + "\n")
            f.write(f"{'Gen ID':<10} {'Gen Name':<20} {'Bus#':<6} {'P_gen (MW)':<12} {'Rank':<6} {'Most Affected Line':<24} "
                    f"{'From->To':<14} {'PTDF (p.u.)':<14} {'MW / 100MW':<14} {'Flow Direction':<20}\n")
            f.write("-" * 130 + "\n")

            for g_id, g_data in gen_sens.items():
                first = True
                for item in g_data.get('sensitivities', []):
                    from_to = f"{item['from_bus']}->{item['to_bus']}"
                    if first:
                        f.write(f"{str(g_id):<10} {g_data['gen_name'][:18]:<20} {str(g_data['bus_id']):<6} "
                                f"{g_data['p_out_mw']:<12.2f} {item['rank']:<6} {item['branch_name'][:22]:<24} "
                                f"{from_to:<14} {item['ptdf']:<14.4f} {item['mw_per_100mw']:<14.2f} {item['direction']:<20}\n")
                        first = False
                    else:
                        f.write(f"{'':<10} {'':<20} {'':<6} {'':<12} {item['rank']:<6} {item['branch_name'][:22]:<24} "
                                f"{from_to:<14} {item['ptdf']:<14.4f} {item['mw_per_100mw']:<14.2f} {item['direction']:<20}\n")
                f.write("." * 130 + "\n")

            f.write("\n\n")

            # Dominating Injection Corridors per Line
            if line_doms is None:
                line_doms = self.engine.rank_line_dominators()

            f.write("⚡ 3. TRANSMISSION CORRIDOR VULNERABILITY — TOP DRIVING INJECTION BUSES\n")
            f.write("-" * 130 + "\n")
            f.write(f"{'Branch Name':<26} {'From->To':<14} {'Rating (MVA)':<14} {'Rank':<6} {'Driving Bus#':<14} "
                    f"{'Bus Name':<22} {'PTDF (p.u.)':<14} {'MW / 100MW Injected':<20}\n")
            f.write("-" * 130 + "\n")

            for br_key, br_data in list(line_doms.items())[:25]:  # Show top 25 branches in text report
                from_to = f"{br_data['from_bus']}->{br_data['to_bus']}"
                first = True
                for item in br_data.get('dominators', []):
                    if first:
                        f.write(f"{br_data['branch_name'][:24]:<26} {from_to:<14} {br_data['rating_mva']:<14.1f} "
                                f"{item['rank']:<6} {str(item['bus_id']):<14} {item['bus_name'][:20]:<22} "
                                f"{item['ptdf']:<14.4f} {item['mw_per_100mw']:<20.2f}\n")
                        first = False
                    else:
                        f.write(f"{'':<26} {'':<14} {'':<14} {item['rank']:<6} {str(item['bus_id']):<14} "
                                f"{item['bus_name'][:20]:<22} {item['ptdf']:<14.4f} {item['mw_per_100mw']:<20.2f}\n")
                f.write("." * 130 + "\n")

            f.write("\n\n")

            # Fast N-1 Screening Results Table
            if screening_results:
                f.write("🚨 4. RAPID LODF N-1 CONTINGENCY SCREENING RESULTS\n")
                f.write("-" * 130 + "\n")
                f.write(f"{'#':<4} {'Outage Element':<28} {'From->To':<14} {'Pre Flow':<12} {'Status':<10} {'Verdict':<10} "
                        f"{'Max Post Load%':<16} {'Critical Bottleneck Line':<26} {'Overloads':<10}\n")
                f.write("-" * 130 + "\n")

                for res in screening_results:
                    from_to = f"{res['from_bus']}->{res['to_bus']}"
                    pre_fl = f"{res['pre_flow_mw']:.1f} MW"
                    verdict = "✅ PASS" if res['pass'] else "❌ FAIL"
                    max_ld = f"{res['max_loading_pct']:.2f}%"
                    crit = res['critical_branch'][:24]

                    f.write(f"{res['outage_index']:<4} {res['outage_name'][:26]:<28} {from_to:<14} {pre_fl:<12} "
                            f"{res['status']:<10} {verdict:<10} {max_ld:<16} {crit:<26} {res['overload_count']:<10}\n")

                    if res['overloads']:
                        for ov in res['overloads'][:3]:
                            f.write(f"      └─ Overload: {ov['branch']} -> Flow: {ov['flow_mw']:.1f} MW / "
                                    f"Rating: {ov['rating_mva']:.1f} MVA ({ov['loading_pct']:.2f}%)\n")

                f.write("-" * 130 + "\n\n")

            # Islanding / Cut-Edge Outage Notice
            if self.engine.islanding_map:
                f.write("⚠️ 5. GRAPH ISLANDING & RADIAL CUT-EDGE DISCONNECTION AUDIT\n")
                f.write("-" * 130 + "\n")
                for out_key, isl_branches in self.engine.islanding_map.items():
                    br_info = self.engine.branches[self.engine.branch_index_map[out_key]]
                    f.write(f"   • Outage: {br_info['name']} ({br_info['from_bus']}->{br_info['to_bus']}) "
                            f"causes islanding of {len(isl_branches)} surviving branches: {', '.join(isl_branches[:6])}\n")
                f.write("-" * 130 + "\n\n")

            f.write("=" * 130 + "\n")
            f.write("END OF GRID SENSITIVITY AUDIT REPORT\n")
            f.write("=" * 130 + "\n")

        return report_path

    def export_ptdf_csv(self):
        """Exports the full (L x N) PTDF matrix to CSV."""
        csv_filename = f"{self.case_name}_PTDF_FULL_MATRIX.csv"
        csv_path = os.path.join(self.output_dir, csv_filename)

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            # Header: Branch Key, Branch Name, From Bus, To Bus, [Bus_1, Bus_2, ...]
            header = ["Branch_Key", "Branch_Name", "From_Bus", "To_Bus", "Rating_MVA"] + [
                f"Bus_{b_id}" for b_id in self.engine.bus_ids
            ]
            writer.writerow(header)

            ptdf = self.engine.ptdf_matrix
            for l_idx, br in enumerate(self.engine.branches):
                row = [
                    br['key'],
                    br['name'],
                    br['from_bus'],
                    br['to_bus'],
                    br['rating']
                ] + [f"{ptdf[l_idx, b_idx]:.6f}" for b_idx in range(len(self.engine.bus_ids))]
                writer.writerow(row)

        return csv_path

    def export_lodf_csv(self):
        """Exports the full (L x L) LODF matrix to CSV."""
        csv_filename = f"{self.case_name}_LODF_FULL_MATRIX.csv"
        csv_path = os.path.join(self.output_dir, csv_filename)

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            # Columns: Monitored Branch Key, Monitored Branch Name, [Outage_1, Outage_2, ...]
            header = ["Monitored_Branch_Key", "Monitored_Branch_Name", "From_Bus", "To_Bus"] + [
                br['key'] for br in self.engine.branches
            ]
            writer.writerow(header)

            lodf = self.engine.lodf_matrix
            num_branches = len(self.engine.branches)
            for l_idx, br in enumerate(self.engine.branches):
                row = [
                    br['key'],
                    br['name'],
                    br['from_bus'],
                    br['to_bus']
                ] + [f"{lodf[l_idx, k_idx]:.6f}" for k_idx in range(num_branches)]
                writer.writerow(row)

        return csv_path

    def export_generator_sensitivities_csv(self, gen_sens=None):
        """Exports the ranked generator sensitivities to CSV."""
        if gen_sens is None:
            gen_sens = self.engine.rank_generator_sensitivities()

        csv_filename = f"{self.case_name}_GENERATOR_IMPACT_RANKING.csv"
        csv_path = os.path.join(self.output_dir, csv_filename)

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Gen_ID", "Gen_Name", "Bus_ID", "Bus_Name", "P_Gen_MW",
                "Rank", "Branch_Key", "Branch_Name", "From_Bus", "To_Bus",
                "PTDF_pu", "MW_per_100MW", "Direction"
            ])

            for g_id, g_data in gen_sens.items():
                for item in g_data.get('sensitivities', []):
                    writer.writerow([
                        g_id,
                        g_data['gen_name'],
                        g_data['bus_id'],
                        g_data['bus_name'],
                        f"{g_data['p_out_mw']:.2f}",
                        item['rank'],
                        item['branch_key'],
                        item['branch_name'],
                        item['from_bus'],
                        item['to_bus'],
                        f"{item['ptdf']:.6f}",
                        f"{item['mw_per_100mw']:.4f}",
                        item['direction']
                    ])

        return csv_path

    def export_line_dominators_csv(self, line_doms=None):
        """Exports the top driving injection buses per line to CSV."""
        if line_doms is None:
            line_doms = self.engine.rank_line_dominators()

        csv_filename = f"{self.case_name}_LINE_DOMINATING_INJECTIONS.csv"
        csv_path = os.path.join(self.output_dir, csv_filename)

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Branch_Key", "Branch_Name", "From_Bus", "To_Bus", "Rating_MVA",
                "Rank", "Driving_Bus_ID", "Driving_Bus_Name", "PTDF_pu", "MW_per_100MW"
            ])

            for br_key, br_data in line_doms.items():
                for item in br_data.get('dominators', []):
                    writer.writerow([
                        br_key,
                        br_data['branch_name'],
                        br_data['from_bus'],
                        br_data['to_bus'],
                        f"{br_data['rating_mva']:.1f}",
                        item['rank'],
                        item['bus_id'],
                        item['bus_name'],
                        f"{item['ptdf']:.6f}",
                        f"{item['mw_per_100mw']:.4f}"
                    ])

        return csv_path

    def export_fast_n1_csv(self, screening_results=None):
        """Exports the rapid N-1 screening results to CSV."""
        if not screening_results:
            return None

        csv_filename = f"{self.case_name}_FAST_N1_SCREENING_SUMMARY.csv"
        csv_path = os.path.join(self.output_dir, csv_filename)

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Outage_Index", "Outage_Key", "Outage_Name", "Outage_Type",
                "From_Bus", "To_Bus", "Pre_Flow_MW", "Status", "Verdict",
                "Max_Post_Loading_Pct", "Critical_Branch", "Overload_Count", "Severity_Index"
            ])

            for res in screening_results:
                writer.writerow([
                    res['outage_index'],
                    res['outage_key'],
                    res['outage_name'],
                    res['outage_type'],
                    res['from_bus'],
                    res['to_bus'],
                    f"{res['pre_flow_mw']:.2f}",
                    res['status'],
                    "PASS" if res['pass'] else "FAIL",
                    f"{res['max_loading_pct']:.2f}",
                    res['critical_branch'],
                    res['overload_count'],
                    f"{res['severity_index']:.4f}"
                ])

        return csv_path

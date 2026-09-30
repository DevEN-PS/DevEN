# DevEN Path Bootstrapper
import sys
import os
import csv
import math
import json
from datetime import datetime

"""
===============================================================================
DevEN — Total & Available Transfer Capability (TTC / ATC) Report Writer
Generates comprehensive audit logs (.invout, .csv, .json) documenting:
- Transfer definition (Source & Sink areas/buses, base transfer)
- Calculation method (Linear Thermal TTC vs. Full AC Bisection)
- Limiting constraint & contingency (Thermal MVA or Voltage sag)
- Margins breakdown (TRM, CBM, ETC, Firm ATC, Non-Firm ATC)
- Monitored branch loadings and bus voltages
===============================================================================
"""

class TTCReportWriter:
    def __init__(self, output_folder, case_name):
        self.output_folder = output_folder
        self.case_name = case_name
        os.makedirs(self.output_folder, exist_ok=True)

        self.invout_path = os.path.join(self.output_folder, f"{self.case_name}_TTC_ATC_REPORT.invout")
        self.summary_csv_path = os.path.join(self.output_folder, f"{self.case_name}_TTC_ATC_SUMMARY.csv")
        self.branches_csv_path = os.path.join(self.output_folder, f"{self.case_name}_TTC_ATC_BRANCH_FLOWS.csv")
        self.buses_csv_path = os.path.join(self.output_folder, f"{self.case_name}_TTC_ATC_BUS_VOLTAGES.csv")
        self.json_path = os.path.join(self.output_folder, f"{self.case_name}_TTC_ATC_DATA.json")

    def write_full_report(self, results):
        """
        Writes all output files (.invout, .csv, .json) based on results dictionary.
        """
        self._write_invout(results)
        self._write_summary_csv(results)
        self._write_branches_csv(results)
        self._write_buses_csv(results)
        self._write_json(results)

    def _write_invout(self, res):
        with open(self.invout_path, "w", encoding="utf-8") as f:
            w = f.write
            w("=" * 110 + "\n")
            w("⚡ DevEN — TOTAL & AVAILABLE TRANSFER CAPABILITY (TTC / ATC) AUDIT REPORT (.INVOUT)\n")
            w(f"Case: {self.case_name} | Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            w(f"Method: {res.get('method_label', 'Unknown')} | Scope: {res.get('contingency_scope', 'N-1')}\n")
            w("=" * 110 + "\n\n")

            w("1. TRANSFER PATHWAY SPECIFICATION\n")
            w("-" * 60 + "\n")
            w(f"  Source Direction:     {res.get('source_desc', 'Area 1')}\n")
            w(f"  Sink Direction:       {res.get('sink_desc', 'Area 2')}\n")
            w(f"  Base Flow Source:     {res.get('base_transfer_mode', 'Auto')}\n")
            w(f"  Existing Base Flow:   {res.get('base_transfer_mw', 0.0):.2f} MW\n")
            w(f"  Transfer Headroom:    {res.get('incremental_headroom_mw', 0.0):.2f} MW\n")
            w("-" * 60 + "\n\n")

            w("2. COMMERCIAL TRANSFER CAPABILITY SUMMARY\n")
            w("=" * 60 + "\n")
            w(f"  ★ TOTAL TRANSFER CAPABILITY (TTC):    {res.get('ttc_mw', 0.0):10.2f} MW\n")
            w(f"    - Base Transfer (Existing Flow):    {res.get('base_transfer_mw', 0.0):10.2f} MW\n")
            w(f"    - Additional Incremental Headroom:  {res.get('incremental_headroom_mw', 0.0):10.2f} MW\n")
            w("  ------------------------------------------------------------\n")
            w(f"  Transmission Reliability Margin (TRM):{res.get('trm_mw', 0.0):10.2f} MW\n")
            w(f"  Capacity Benefit Margin (CBM):        {res.get('cbm_mw', 0.0):10.2f} MW\n")
            w(f"  Existing Transmission Commitments:    {res.get('etc_firm_mw', 0.0):10.2f} MW\n")
            w("  ============================================================\n")
            w(f"  ★ FIRM ATC:                           {res.get('firm_atc_mw', 0.0):10.2f} MW\n")
            w(f"  ★ NON-FIRM ATC:                       {res.get('non_firm_atc_mw', 0.0):10.2f} MW\n")
            w("=" * 60 + "\n\n")

            w("3. GOVERNING BOTTLENECK & CRITICAL CONTINGENCY\n")
            w("-" * 60 + "\n")
            w(f"  Limiting Constraint:  {res.get('bottleneck_element', 'N/A')}\n")
            w(f"  Constraint Type:      {res.get('bottleneck_type', 'N/A')}\n")
            w(f"  Critical Contingency: {res.get('critical_contingency', 'Base Case (N-0)')}\n")
            w(f"  Binding Value:        {res.get('binding_value_str', 'N/A')}\n")
            w(f"  Limiting Rating / Threshold: {res.get('binding_limit_str', 'N/A')}\n")
            w("-" * 60 + "\n\n")

            # Inter-area tie lines
            tie_lines = res.get('tie_lines', [])
            if tie_lines:
                w("4. INTER-AREA TIE-LINES\n")
                w(f"{'Branch ID':<15} {'Name':<22} {'From':<8} {'To':<8} {'Base MW':<12} {'Base MVAR':<12} {'Rating MVA':<12}\n")
                w("-" * 95 + "\n")
                for t in tie_lines:
                    w(f"{t.get('id', ''):<15} {t.get('name', ''):<22} {str(t.get('from_bus', '')):<8} {str(t.get('to_bus', '')):<8} {t.get('p_mw', 0.0):<12.2f} {t.get('q_mvar', 0.0):<12.2f} {t.get('rateA', 0.0):<12.1f}\n")
                w("-" * 95 + "\n\n")

            # Top critical branches
            crit_branches = res.get('critical_branches', [])
            if crit_branches:
                w("5. TOP MONITORED BRANCH LOADINGS AT TTC LIMIT\n")
                w(f"{'Branch':<18} {'From':<8} {'To':<8} {'Flow MVA':<12} {'Rating MVA':<12} {'Loading %':<12} {'Contingency':<25} {'Status':<10}\n")
                w("-" * 110 + "\n")
                for b in crit_branches[:25]:
                    w(f"{b.get('name', ''):<18} {str(b.get('from_bus', '')):<8} {str(b.get('to_bus', '')):<8} {b.get('flow_mva', 0.0):<12.2f} {b.get('rating_mva', 0.0):<12.1f} {b.get('loading_pct', 0.0):<12.1f} {b.get('contingency', 'Base (N-0)'):<25} {b.get('status', 'OK'):<10}\n")
                w("-" * 110 + "\n\n")

            # Bus voltage summary
            crit_buses = res.get('critical_buses', [])
            if crit_buses:
                w("6. BUS VOLTAGES AT TTC LIMIT\n")
                w(f"{'Bus ID':<10} {'Name':<20} {'Base kV':<10} {'Voltage (pu)':<15} {'Limits [pu]':<18} {'Status':<10}\n")
                w("-" * 85 + "\n")
                for bu in crit_buses[:25]:
                    w(f"{bu.get('bus_id', ''):<10} {bu.get('name', ''):<20} {bu.get('base_kv', 0.0):<10.1f} {bu.get('vm_pu', 1.0):<15.4f} [{bu.get('vmin_pu', 0.9):.2f} - {bu.get('vmax_pu', 1.1):.2f}]      {bu.get('status', 'OK'):<10}\n")
                w("-" * 85 + "\n\n")

            w("=" * 110 + "\n")
            w("END OF DEV EN TTC / ATC AUDIT REPORT\n")
            w("=" * 110 + "\n")

    def _write_summary_csv(self, res):
        with open(self.summary_csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Metric", "Value", "Unit", "Description"])
            w.writerow(["Case_Name", self.case_name, "", "Power system case name"])
            w.writerow(["Calculation_Method", res.get("method_label", ""), "", "Algorithm used"])
            w.writerow(["Contingency_Scope", res.get("contingency_scope", ""), "", "N-0, N-1 branches, or N-1 branches+gens"])
            w.writerow(["Source_Pathway", res.get("source_desc", ""), "", "Injection source definition"])
            w.writerow(["Sink_Pathway", res.get("sink_desc", ""), "", "Withdrawal sink definition"])
            w.writerow(["Base_Transfer", f"{res.get('base_transfer_mw', 0.0):.2f}", "MW", "Pre-transfer base corridor flow"])
            w.writerow(["Incremental_Headroom", f"{res.get('incremental_headroom_mw', 0.0):.2f}", "MW", "Available physical headroom"])
            w.writerow(["TTC", f"{res.get('ttc_mw', 0.0):.2f}", "MW", "Total Transfer Capability = Base + Headroom"])
            w.writerow(["TRM", f"{res.get('trm_mw', 0.0):.2f}", "MW", "Transmission Reliability Margin"])
            w.writerow(["CBM", f"{res.get('cbm_mw', 0.0):.2f}", "MW", "Capacity Benefit Margin"])
            w.writerow(["ETC_Firm", f"{res.get('etc_firm_mw', 0.0):.2f}", "MW", "Existing Transmission Commitments (Firm)"])
            w.writerow(["Firm_ATC", f"{res.get('firm_atc_mw', 0.0):.2f}", "MW", "Available Transfer Capability (Firm)"])
            w.writerow(["Non_Firm_ATC", f"{res.get('non_firm_atc_mw', 0.0):.2f}", "MW", "Available Transfer Capability (Non-Firm)"])
            w.writerow(["Bottleneck_Element", res.get("bottleneck_element", ""), "", "Limiting line, transformer, or bus"])
            w.writerow(["Bottleneck_Type", res.get("bottleneck_type", ""), "", "Thermal Overload or Voltage Sag/Swell"])
            w.writerow(["Critical_Contingency", res.get("critical_contingency", ""), "", "Outage causing the binding limit"])
            w.writerow(["Binding_Value", res.get("binding_value_str", ""), "", "Monitored value at limit"])
            w.writerow(["Limit_Threshold", res.get("binding_limit_str", ""), "", "Enforced security threshold"])

    def _write_branches_csv(self, res):
        with open(self.branches_csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([
                "Branch_Key", "Name", "From_Bus", "To_Bus", "Base_Flow_MVA",
                "Limit_Flow_MVA", "Rating_MVA", "Loading_Pct", "Critical_Contingency", "Status"
            ])
            for b in res.get("critical_branches", []):
                w.writerow([
                    b.get("key", ""), b.get("name", ""), b.get("from_bus", ""), b.get("to_bus", ""),
                    f"{b.get('base_flow_mva', 0.0):.2f}", f"{b.get('flow_mva', 0.0):.2f}",
                    f"{b.get('rating_mva', 0.0):.2f}", f"{b.get('loading_pct', 0.0):.1f}",
                    b.get("contingency", "Base Case (N-0)"), b.get("status", "OK")
                ])

    def _write_buses_csv(self, res):
        with open(self.buses_csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Bus_ID", "Name", "Base_kV", "Base_V_pu", "Limit_V_pu", "V_Min_Limit", "V_Max_Limit", "Status"])
            for bu in res.get("critical_buses", []):
                w.writerow([
                    bu.get("bus_id", ""), bu.get("name", ""), f"{bu.get('base_kv', 0.0):.1f}",
                    f"{bu.get('base_vm_pu', 1.0):.4f}", f"{bu.get('vm_pu', 1.0):.4f}",
                    f"{bu.get('vmin_pu', 0.9):.2f}", f"{bu.get('vmax_pu', 1.1):.2f}",
                    bu.get("status", "OK")
                ])

    def _write_json(self, res):
        cleaned = {}
        for k, v in res.items():
            if isinstance(v, (int, float, str, bool, list, dict)) or v is None:
                cleaned[k] = v
            else:
                cleaned[k] = str(v)
        with open(self.json_path, "w", encoding="utf-8") as f:
            json.dump(cleaned, f, indent=2)

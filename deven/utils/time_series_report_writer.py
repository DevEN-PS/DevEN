# DevEN Path Bootstrapper
import sys
import os
import csv
import math
import json
from datetime import datetime

"""
DevEN Time Series Multi-Format Report Writer
Generates complete LFA-standard result files (.csv, .py, .invout) with chronological time step columns
and consolidated executive summaries at the top of each file.
"""

def write_timeseries_all_data_csv(filename, case_name, full_data, step_records, total_gen_mwh=0.0, total_load_mwh=0.0, total_loss_mwh=0.0):
    """
    Generates a full LFA-standard multi-section CSV report containing all components
    across all chronological time steps with the executive summary at the top.
    """
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)

        # Header Comments & Executive Summary
        loss_pct_agg = (total_loss_mwh / max(1e-6, total_gen_mwh) * 100.0) if total_gen_mwh > 0 else 0.0
        peak_r = max(step_records, key=lambda x: x.get('total_p_load_mw', 0.0)) if step_records else {}
        min_v_r = min(step_records, key=lambda x: x.get('v_min_pu', 1.0)) if step_records else {}
        max_ld_r = max(step_records, key=lambda x: x.get('max_branch_loading_pct', 0.0)) if step_records else {}

        writer.writerow(['# ============================================================================'])
        writer.writerow([f'# DevEN CHRONOLOGICAL TIME SERIES POWER FLOW — CONSOLIDATED MASTER REPORT'])
        writer.writerow([f'# Case: {case_name} | Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'])
        writer.writerow([f'# Total Steps Solved: {len(step_records)}'])
        writer.writerow([f'# Total Energy Generation : {total_gen_mwh:.2f} MWh'])
        writer.writerow([f'# Total Energy Demand     : {total_load_mwh:.2f} MWh'])
        writer.writerow([f'# Total Transmission Loss : {total_loss_mwh:.2f} MWh ({loss_pct_agg:.2f}% of generation)'])
        if peak_r:
            writer.writerow([f'# Peak Demand             : {peak_r.get("total_p_load_mw", 0.0):.2f} MW at {peak_r.get("timestamp", "")} ({peak_r.get("time_label", "")})'])
        if min_v_r:
            writer.writerow([f'# Minimum Voltage Point   : {min_v_r.get("v_min_pu", 1.0):.4f} p.u. (Bus {min_v_r.get("v_min_bus", 0)}) at {min_v_r.get("timestamp", "")}'])
        if max_ld_r:
            writer.writerow([f'# Maximum Branch Loading  : {max_ld_r.get("max_branch_loading_pct", 0.0):.2f}% ({max_ld_r.get("max_loading_branch", "")})'])
        writer.writerow(['# ============================================================================'])
        writer.writerow([])

        # =========================================================
        # SECTION 1: SYSTEM SUMMARY & CONVERGENCE
        # =========================================================
        writer.writerow(['# ========== SECTION 1: SYSTEM SUMMARY & CHRONOLOGICAL PERFORMANCE =========='])
        writer.writerow([
            'Time_Step', 'Timestamp', 'Time_Label', 'Status', 'Iterations',
            'P_gen_MW', 'Q_gen_MVar', 'P_load_MW', 'Q_load_MVar',
            'P_loss_MW', 'Q_loss_MVar', 'Loss_Pct_Gen',
            'V_min_pu', 'V_min_bus', 'V_max_pu', 'V_max_bus',
            'Max_Branch_Loading_pct', 'Critical_Branch'
        ])
        for rec in step_records:
            p_gen = rec.get('total_p_gen_mw', 0.0)
            p_loss = rec.get('total_p_loss_mw', 0.0)
            loss_pct = (p_loss / max(1e-6, p_gen) * 100.0) if p_gen > 0 else 0.0
            writer.writerow([
                rec['step_index'], rec['timestamp'], rec['time_label'],
                "CONVERGED" if rec['converged'] else "DIVERGED",
                rec.get('iterations', 0),
                f"{p_gen:.3f}", f"{rec.get('total_q_gen_mvar', 0.0):.3f}",
                f"{rec.get('total_p_load_mw', 0.0):.3f}", f"{rec.get('total_q_load_mvar', 0.0):.3f}",
                f"{p_loss:.3f}", f"{rec.get('total_q_loss_mvar', 0.0):.3f}",
                f"{loss_pct:.2f}",
                f"{rec.get('v_min_pu', 1.0):.4f}", rec.get('v_min_bus', 0),
                f"{rec.get('v_max_pu', 1.0):.4f}", rec.get('v_max_bus', 0),
                f"{rec.get('max_branch_loading_pct', 0.0):.2f}", rec.get('max_loading_branch', 'N/A')
            ])
        writer.writerow([])

        # =========================================================
        # SECTION 2: BUS RESULTS
        # =========================================================
        writer.writerow(['# ========== SECTION 2: BUS VOLTAGES & ANGLES =========='])
        writer.writerow([
            'Time_Step', 'Timestamp', 'Time_Label', 'bus_num', 'bus_name', 'bus_type', 'base_kV',
            'area', 'zone', 'owner', 'O_V_final_pu', 'O_V_final_kV', 'O_angle_deg', 'O_voltage_status'
        ])
        buses = full_data.get('buses', {})
        for rec in step_records:
            b_res = rec.get('bus_results', {})
            for b_num, b_data in sorted(buses.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
                b_name = b_data.get('name', f'Bus_{b_num}')
                b_type = b_data.get('type', 1)
                base_kv = float(b_data.get('base_kV', 132.0))
                area = b_data.get('area', 1)
                zone = b_data.get('zone', 1)
                owner = b_data.get('owner', 1)

                cur_b = b_res.get(b_num, {})
                vm = cur_b.get('V_mag', 1.0)
                va = cur_b.get('V_ang_deg', 0.0)
                vkV = vm * base_kv
                v_stat = "NORMAL" if 0.95 <= vm <= 1.05 else ("UNDERVOLTAGE" if vm < 0.95 else "OVERVOLTAGE")

                writer.writerow([
                    rec['step_index'], rec['timestamp'], rec['time_label'],
                    b_num, b_name, b_type, f"{base_kv:.2f}",
                    area, zone, owner,
                    f"{vm:.5f}", f"{vkV:.3f}", f"{va:.3f}", v_stat
                ])
        writer.writerow([])

        # =========================================================
        # SECTION 3: GENERATOR RESULTS
        # =========================================================
        writer.writerow(['# ========== SECTION 3: GENERATOR DISPATCH & VOLTAGES =========='])
        writer.writerow([
            'Time_Step', 'Timestamp', 'Time_Label', 'gen_num', 'gen_name', 'gen_type', 'bus',
            'area', 'zone', 'I_P_set_MW', 'I_Q_set_Mvar', 'I_V_set_pu', 'I_Qmin_Mvar', 'I_Qmax_Mvar',
            'O_P_out_MW', 'O_Q_out_Mvar', 'O_V_actual_pu', 'O_V_actual_kV', 'O_Q_status', 'O_status'
        ])
        gens = full_data.get('generators', {})
        for rec in step_records:
            b_res = rec.get('bus_results', {})
            g_res = rec.get('gen_results', {})
            for g_num, g_data in sorted(gens.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
                bus_num = g_data.get('bus', 0)
                base_kv = float(buses.get(bus_num, {}).get('base_kV', 132.0)) if bus_num in buses else 132.0
                cur_g = g_res.get(g_num, {})
                p_out = cur_g.get('P_out_MW', float(g_data.get('P_out', 0.0)))
                q_out = cur_g.get('Q_out_Mvar', float(g_data.get('Q_out', 0.0)))
                qmin = float(g_data.get('Qmin', -999.0))
                qmax = float(g_data.get('Qmax', 999.0))
                vm = b_res.get(bus_num, {}).get('V_mag', float(g_data.get('V_set', 1.0)))

                q_stat = "WITHIN_LIMITS"
                if q_out < qmin: q_stat = "BELOW_QMIN"
                elif q_out > qmax: q_stat = "ABOVE_QMAX"

                writer.writerow([
                    rec['step_index'], rec['timestamp'], rec['time_label'],
                    g_num, g_data.get('name', f'Gen_{g_num}'), g_data.get('type', 'SYNC'), bus_num,
                    g_data.get('area', 1), g_data.get('zone', 1),
                    f"{float(g_data.get('P_out', 0.0)):.2f}", f"{float(g_data.get('Q_out', 0.0)):.2f}",
                    f"{float(g_data.get('V_set', 1.0)):.4f}", f"{qmin:.2f}", f"{qmax:.2f}",
                    f"{p_out:.3f}", f"{q_out:.3f}", f"{vm:.5f}", f"{(vm * base_kv):.3f}",
                    q_stat, "ONLINE" if g_data.get('status', 1) == 1 else "OFFLINE"
                ])
        writer.writerow([])

        # =========================================================
        # SECTION 4: LOAD RESULTS
        # =========================================================
        writer.writerow(['# ========== SECTION 4: LOAD DEMAND & SUPPLIED POWER =========='])
        writer.writerow([
            'Time_Step', 'Timestamp', 'Time_Label', 'load_num', 'load_name', 'bus', 'model',
            'area', 'zone', 'I_P_demand_MW', 'I_Q_demand_Mvar', 'O_P_supplied_MW', 'O_Q_supplied_Mvar',
            'O_V_actual_pu', 'O_V_actual_kV', 'O_status'
        ])
        loads = full_data.get('loads', {})
        for rec in step_records:
            b_res = rec.get('bus_results', {})
            l_res = rec.get('load_results', {})
            for l_num, l_data in sorted(loads.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
                bus_num = l_data.get('bus', 0)
                base_kv = float(buses.get(bus_num, {}).get('base_kV', 132.0)) if bus_num in buses else 132.0
                cur_l = l_res.get(l_num, {})
                p_sup = cur_l.get('P_supplied_MW', float(l_data.get('P_demand', 0.0)))
                q_sup = cur_l.get('Q_supplied_Mvar', float(l_data.get('Q_demand', 0.0)))
                vm = b_res.get(bus_num, {}).get('V_mag', 1.0)

                writer.writerow([
                    rec['step_index'], rec['timestamp'], rec['time_label'],
                    l_num, l_data.get('name', f'Load_{l_num}'), bus_num, l_data.get('model', 'CONSTANT_POWER'),
                    l_data.get('area', 1), l_data.get('zone', 1),
                    f"{float(l_data.get('P_demand', 0.0)):.2f}", f"{float(l_data.get('Q_demand', 0.0)):.2f}",
                    f"{p_sup:.3f}", f"{q_sup:.3f}", f"{vm:.5f}", f"{(vm * base_kv):.3f}",
                    "ONLINE" if l_data.get('status', 1) == 1 else "OFFLINE"
                ])
        writer.writerow([])

        # =========================================================
        # SECTION 5: TRANSMISSION LINE RESULTS
        # =========================================================
        writer.writerow(['# ========== SECTION 5: TRANSMISSION LINE POWER FLOWS & LOSSES =========='])
        writer.writerow([
            'Time_Step', 'Timestamp', 'Time_Label', 'line_num', 'line_name', 'from_bus', 'to_bus',
            'length_km', 'rateA_MVA', 'area', 'zone', 'owner',
            'O_P_fwd_MW', 'O_Q_fwd_Mvar', 'O_MVA_fwd',
            'O_P_rev_MW', 'O_Q_rev_Mvar', 'O_MVA_rev',
            'O_losses_MW', 'O_loading_pct', 'O_status'
        ])
        lines = full_data.get('lines', {})
        for rec in step_records:
            br_res = rec.get('branch_results', {})
            for l_num, l_data in sorted(lines.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
                br_key = f"Line_{l_num}"
                cur_br = br_res.get(br_key, {})
                pf = cur_br.get('P_MW', 0.0)
                qf = cur_br.get('Q_MVar', 0.0)
                sf = cur_br.get('S_MVA', math.sqrt(pf**2 + qf**2))
                pr = cur_br.get('P_rev_MW', 0.0)
                qr = cur_br.get('Q_rev_Mvar', 0.0)
                sr = cur_br.get('S_rev_MVA', math.sqrt(pr**2 + qr**2))
                rate = float(l_data.get('rateA', 9999.0) or 9999.0)
                loading = cur_br.get('Loading_Pct', (sf / rate * 100.0) if rate > 0 else 0.0)
                loss = cur_br.get('Loss_MW', 0.0)

                writer.writerow([
                    rec['step_index'], rec['timestamp'], rec['time_label'],
                    l_num, l_data.get('name', f'Line_{l_num}'), l_data.get('from_bus', 0), l_data.get('to_bus', 0),
                    f"{float(l_data.get('length_km', 1.0)):.2f}", f"{rate:.2f}",
                    l_data.get('area', 1), l_data.get('zone', 1), l_data.get('owner', 1),
                    f"{pf:.3f}", f"{qf:.3f}", f"{sf:.3f}",
                    f"{pr:.3f}", f"{qr:.3f}", f"{sr:.3f}",
                    f"{loss:.4f}", f"{loading:.2f}",
                    "ONLINE" if l_data.get('status', 1) == 1 else "OFFLINE"
                ])
        writer.writerow([])

        # =========================================================
        # SECTION 6: TRANSFORMER RESULTS
        # =========================================================
        writer.writerow(['# ========== SECTION 6: TRANSFORMER POWER FLOWS & TAPS =========='])
        writer.writerow([
            'Time_Step', 'Timestamp', 'Time_Label', 'xfmr_num', 'xfmr_name', 'from_bus', 'to_bus',
            'rateA_MVA', 'tap_ratio', 'area', 'zone',
            'O_P_fwd_MW', 'O_Q_fwd_Mvar', 'O_MVA_fwd',
            'O_P_rev_MW', 'O_Q_rev_Mvar', 'O_MVA_rev',
            'O_losses_MW', 'O_loading_pct', 'O_status'
        ])
        xfmrs = full_data.get('transformers', {})
        for rec in step_records:
            br_res = rec.get('branch_results', {})
            for x_num, x_data in sorted(xfmrs.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
                br_key = f"Xfmr_{x_num}"
                cur_br = br_res.get(br_key, {})
                pf = cur_br.get('P_MW', 0.0)
                qf = cur_br.get('Q_MVar', 0.0)
                sf = cur_br.get('S_MVA', math.sqrt(pf**2 + qf**2))
                pr = cur_br.get('P_rev_MW', 0.0)
                qr = cur_br.get('Q_rev_Mvar', 0.0)
                sr = cur_br.get('S_rev_MVA', math.sqrt(pr**2 + qr**2))
                rate = float(x_data.get('rateA', 9999.0) or 9999.0)
                loading = cur_br.get('Loading_Pct', (sf / rate * 100.0) if rate > 0 else 0.0)
                tap = cur_br.get('tap_ratio', float(x_data.get('tap_ratio', 1.0)))

                writer.writerow([
                    rec['step_index'], rec['timestamp'], rec['time_label'],
                    x_num, x_data.get('name', f'Xfmr_{x_num}'), x_data.get('from_bus', 0), x_data.get('to_bus', 0),
                    f"{rate:.2f}", f"{tap:.4f}",
                    x_data.get('area', 1), x_data.get('zone', 1),
                    f"{pf:.3f}", f"{qf:.3f}", f"{sf:.3f}",
                    f"{pr:.3f}", f"{qr:.3f}", f"{sr:.3f}",
                    f"{cur_br.get('Loss_MW', 0.0):.4f}", f"{loading:.2f}",
                    "ONLINE" if x_data.get('status', 1) == 1 else "OFFLINE"
                ])
        writer.writerow([])

        # =========================================================
        # SECTION 7: SHUNTS, CAPACITORS & REACTORS
        # =========================================================
        writer.writerow(['# ========== SECTION 7: SHUNTS, CAPACITORS & REACTORS =========='])
        writer.writerow([
            'Time_Step', 'Timestamp', 'Time_Label', 'Type', 'num', 'name', 'bus',
            'I_Q_rated_Mvar', 'O_Q_injected_Mvar', 'O_V_actual_pu', 'O_status'
        ])
        caps = full_data.get('capacitors', {})
        reacts = full_data.get('reactors', {})
        shunts = full_data.get('shunts', {})
        for rec in step_records:
            b_res = rec.get('bus_results', {})
            for c_num, c_data in sorted(caps.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
                bus_num = c_data.get('bus', 0)
                vm = b_res.get(bus_num, {}).get('V_mag', 1.0)
                writer.writerow([
                    rec['step_index'], rec['timestamp'], rec['time_label'],
                    "CAPACITOR", c_num, c_data.get('name', f'Cap_{c_num}'), bus_num,
                    f"{float(c_data.get('Q_cap', 0.0)):.2f}",
                    f"{(float(c_data.get('Q_cap', 0.0)) * (vm**2)):.3f}",
                    f"{vm:.5f}", "ONLINE" if c_data.get('status', 1) == 1 else "OFFLINE"
                ])
            for r_num, r_data in sorted(reacts.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
                bus_num = r_data.get('bus', 0)
                vm = b_res.get(bus_num, {}).get('V_mag', 1.0)
                writer.writerow([
                    rec['step_index'], rec['timestamp'], rec['time_label'],
                    "REACTOR", r_num, r_data.get('name', f'Reactor_{r_num}'), bus_num,
                    f"{float(r_data.get('Q_react', 0.0)):.2f}",
                    f"{(float(r_data.get('Q_react', 0.0)) * (vm**2)):.3f}",
                    f"{vm:.5f}", "ONLINE" if r_data.get('status', 1) == 1 else "OFFLINE"
                ])
            for s_num, s_data in sorted(shunts.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
                bus_num = s_data.get('bus', 0)
                vm = b_res.get(bus_num, {}).get('V_mag', 1.0)
                writer.writerow([
                    rec['step_index'], rec['timestamp'], rec['time_label'],
                    "SHUNT", s_num, s_data.get('name', f'Shunt_{s_num}'), bus_num,
                    f"{float(s_data.get('Q_shunt', 0.0)):.2f}",
                    f"{(float(s_data.get('Q_shunt', 0.0)) * (vm**2)):.3f}",
                    f"{vm:.5f}", "ONLINE" if s_data.get('status', 1) == 1 else "OFFLINE"
                ])


def write_timeseries_all_data_py(filename, case_name, full_data, step_records, total_gen_mwh=0.0, total_load_mwh=0.0, total_loss_mwh=0.0):
    """
    Generates a Python dictionary results file with single-line dictionaries
    and consolidated summary metadata at the top.
    """
    with open(filename, 'w', encoding='utf-8') as f:
        f.write('"""\n')
        f.write(f'DevEN Chronological Time Series Power Flow Results — Python Database\n')
        f.write(f'Case: {case_name} | Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
        f.write(f'Total Energy Generation : {total_gen_mwh:.2f} MWh\n')
        f.write(f'Total Energy Demand     : {total_load_mwh:.2f} MWh\n')
        f.write(f'Total Transmission Loss : {total_loss_mwh:.2f} MWh\n')
        f.write('"""\n\n')

        f.write(f"CASE_NAME = '{case_name}'\n")
        f.write(f"TOTAL_STEPS = {len(step_records)}\n")
        f.write(f"TOTAL_GEN_MWH = {round(total_gen_mwh, 2)}\n")
        f.write(f"TOTAL_LOAD_MWH = {round(total_load_mwh, 2)}\n")
        f.write(f"TOTAL_LOSS_MWH = {round(total_loss_mwh, 2)}\n\n")

        # Compact step summaries
        summaries = []
        for r in step_records:
            summaries.append({
                'step': r['step_index'],
                'timestamp': r['timestamp'],
                'label': r['time_label'],
                'converged': r['converged'],
                'iterations': r.get('iterations', 0),
                'p_gen_mw': round(r.get('total_p_gen_mw', 0.0), 3),
                'q_gen_mvar': round(r.get('total_q_gen_mvar', 0.0), 3),
                'p_load_mw': round(r.get('total_p_load_mw', 0.0), 3),
                'q_load_mvar': round(r.get('total_q_load_mvar', 0.0), 3),
                'p_loss_mw': round(r.get('total_p_loss_mw', 0.0), 3),
                'v_min_pu': round(r.get('v_min_pu', 1.0), 4),
                'v_min_bus': r.get('v_min_bus', 0),
                'v_max_pu': round(r.get('v_max_pu', 1.0), 4),
                'v_max_bus': r.get('v_max_bus', 0),
                'max_loading_pct': round(r.get('max_branch_loading_pct', 0.0), 2),
                'critical_branch': r.get('max_loading_branch', 'N/A')
            })

        f.write(f"TIME_SERIES_SUMMARY = {repr(summaries)}\n\n")

        # Step detailed results dictionary
        f.write("# Detailed Results per Step\n")
        f.write("TIME_SERIES_RESULTS = {\n")
        for rec in step_records:
            step_dict = {
                'step_index': rec['step_index'],
                'timestamp': rec['timestamp'],
                'time_label': rec['time_label'],
                'converged': rec['converged'],
                'bus_results': rec.get('bus_results', {}),
                'branch_results': rec.get('branch_results', {}),
                'gen_results': rec.get('gen_results', {}),
                'load_results': rec.get('load_results', {})
            }
            f.write(f"    {rec['step_index']}: {repr(step_dict)},\n")
        f.write("}\n")


def write_timeseries_invout_report(filename, case_name, full_data, step_records, total_gen_mwh=0.0, total_load_mwh=0.0, total_loss_mwh=0.0):
    """
    Generates an exhaustive, full-featured .invout formatted chronological text report
    containing executive aggregates, timeline summary table, and detailed tables for
    buses, generators, loads, lines, transformers, and reactive elements.
    """
    loss_pct_agg = (total_loss_mwh / max(1e-6, total_gen_mwh) * 100.0) if total_gen_mwh > 0 else 0.0
    peak_r = max(step_records, key=lambda x: x.get('total_p_load_mw', 0.0)) if step_records else {}
    min_v_r = min(step_records, key=lambda x: x.get('v_min_pu', 1.0)) if step_records else {}
    max_ld_r = max(step_records, key=lambda x: x.get('max_branch_loading_pct', 0.0)) if step_records else {}

    buses = full_data.get('buses', {})
    gens = full_data.get('generators', {})
    loads = full_data.get('loads', {})
    lines = full_data.get('lines', {})
    xfmrs = full_data.get('transformers', {})
    caps = full_data.get('capacitors', {})
    reacts = full_data.get('reactors', {})
    shunts = full_data.get('shunts', {})

    with open(filename, 'w', encoding='utf-8') as f:
        # 1. Executive Master Header
        f.write("=" * 125 + "\n")
        f.write("⚡ DevEN INVERSE & CHRONOLOGICAL POWER FLOW SYSTEM OUTPUT REPORT (.INVOUT)\n")
        f.write(f"Case: {case_name} | Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 125 + "\n\n")

        f.write("📊 EXECUTIVE ENERGY & LOSS SUMMARY\n")
        f.write("-" * 125 + "\n")
        f.write(f"   • Total Steps Solved       : {len(step_records)}\n")
        f.write(f"   • Total Energy Generation  : {total_gen_mwh:>12.2f} MWh\n")
        f.write(f"   • Total Energy Demand      : {total_load_mwh:>12.2f} MWh\n")
        f.write(f"   • Total Transmission Loss  : {total_loss_mwh:>12.2f} MWh ({loss_pct_agg:.2f}% of generation)\n")
        if peak_r:
            f.write(f"   • Peak Demand Step         : {peak_r.get('total_p_load_mw', 0.0):.2f} MW at {peak_r.get('timestamp', '')} ({peak_r.get('time_label', '')})\n")
        if min_v_r:
            f.write(f"   • Minimum Voltage Point    : {min_v_r.get('v_min_pu', 1.0):.4f} p.u. (Bus {min_v_r.get('v_min_bus', 0)}) at {min_v_r.get('timestamp', '')}\n")
        if max_ld_r:
            f.write(f"   • Maximum Branch Loading   : {max_ld_r.get('max_branch_loading_pct', 0.0):.2f}% ({max_ld_r.get('max_loading_branch', '')})\n")
        f.write("=" * 125 + "\n\n")

        # 2. Section 1: System Timeline Summary Table
        f.write("SECTION 1: CHRONOLOGICAL SYSTEM TIMELINE & CONVERGENCE PERFORMANCE\n")
        f.write("-" * 125 + "\n")
        f.write(f"{'Step':<5} {'Timestamp':<20} {'Time':<6} {'Status':<7} {'Iter':<5} {'P_Gen(MW)':<11} {'Q_Gen(MVar)':<12} {'P_Load(MW)':<11} {'Q_Load(MVar)':<12} {'Loss(MW)':<10} {'V_min(pu)':<10} {'MaxLoad(%)':<11} {'Critical Branch':<20}\n")
        f.write("-" * 125 + "\n")
        for r in step_records:
            st = "CONV" if r['converged'] else "DIV"
            f.write(f"{r['step_index']:<5} {r['timestamp']:<20} {r['time_label']:<6} {st:<7} {r.get('iterations', 0):<5} "
                    f"{r.get('total_p_gen_mw', 0.0):<11.2f} {r.get('total_q_gen_mvar', 0.0):<12.2f} "
                    f"{r.get('total_p_load_mw', 0.0):<11.2f} {r.get('total_q_load_mvar', 0.0):<12.2f} "
                    f"{r.get('total_p_loss_mw', 0.0):<10.2f} {r.get('v_min_pu', 1.0):<10.4f} "
                    f"{r.get('max_branch_loading_pct', 0.0):<11.2f} {str(r.get('max_loading_branch', 'N/A'))[:20]:<20}\n")
        f.write("=" * 125 + "\n\n")

        # 3. Section 2: Bus Results Table
        f.write("SECTION 2: BUS VOLTAGE & ANGLE RESULTS (CHRONOLOGICAL)\n")
        f.write("-" * 125 + "\n")
        f.write(f"{'Step':<5} {'Timestamp':<20} {'Time':<6} {'Bus#':<6} {'Bus Name':<18} {'Type':<5} {'Base_kV':<9} {'V_final(pu)':<13} {'V_final(kV)':<13} {'Angle(deg)':<12} {'Status':<12}\n")
        f.write("-" * 125 + "\n")
        for rec in step_records:
            b_res = rec.get('bus_results', {})
            for b_num, b_data in sorted(buses.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
                base_kv = float(b_data.get('base_kV', 132.0))
                cur_b = b_res.get(b_num, {})
                vm = cur_b.get('V_mag', 1.0)
                va = cur_b.get('V_ang_deg', 0.0)
                vkV = vm * base_kv
                v_stat = "NORMAL" if 0.95 <= vm <= 1.05 else ("UNDERVOLT" if vm < 0.95 else "OVERVOLT")
                f.write(f"{rec['step_index']:<5} {rec['timestamp']:<20} {rec['time_label']:<6} {b_num:<6} {str(b_data.get('name', f'Bus_{b_num}'))[:18]:<18} {b_data.get('type', 1):<5} {base_kv:<9.2f} {vm:<13.5f} {vkV:<13.3f} {va:<12.3f} {v_stat:<12}\n")
        f.write("=" * 125 + "\n\n")

        # 4. Section 3: Generator Dispatch Table
        f.write("SECTION 3: GENERATOR DISPATCH & VOLTAGE RESULTS (CHRONOLOGICAL)\n")
        f.write("-" * 125 + "\n")
        f.write(f"{'Step':<5} {'Timestamp':<20} {'Time':<6} {'Gen#':<6} {'Gen Name':<18} {'Bus#':<6} {'P_out(MW)':<12} {'Q_out(MVar)':<13} {'V_act(pu)':<12} {'V_act(kV)':<12} {'Q_Status':<15} {'State':<8}\n")
        f.write("-" * 125 + "\n")
        for rec in step_records:
            b_res = rec.get('bus_results', {})
            g_res = rec.get('gen_results', {})
            for g_num, g_data in sorted(gens.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
                bus_num = g_data.get('bus', 0)
                base_kv = float(buses.get(bus_num, {}).get('base_kV', 132.0)) if bus_num in buses else 132.0
                cur_g = g_res.get(g_num, {})
                p_out = cur_g.get('P_out_MW', float(g_data.get('P_out', 0.0)))
                q_out = cur_g.get('Q_out_Mvar', float(g_data.get('Q_out', 0.0)))
                qmin = float(g_data.get('Qmin', -999.0))
                qmax = float(g_data.get('Qmax', 999.0))
                vm = b_res.get(bus_num, {}).get('V_mag', float(g_data.get('V_set', 1.0)))

                q_stat = "WITHIN_LIMITS"
                if q_out < qmin: q_stat = "BELOW_QMIN"
                elif q_out > qmax: q_stat = "ABOVE_QMAX"

                f.write(f"{rec['step_index']:<5} {rec['timestamp']:<20} {rec['time_label']:<6} {g_num:<6} {str(g_data.get('name', f'Gen_{g_num}'))[:18]:<18} {bus_num:<6} {p_out:<12.3f} {q_out:<13.3f} {vm:<12.5f} {(vm*base_kv):<12.3f} {q_stat:<15} {'ONLINE' if g_data.get('status', 1)==1 else 'OFFLINE':<8}\n")
        f.write("=" * 125 + "\n\n")

        # 5. Section 4: Load Demand Table
        f.write("SECTION 4: LOAD DEMAND & SUPPLIED POWER RESULTS (CHRONOLOGICAL)\n")
        f.write("-" * 125 + "\n")
        f.write(f"{'Step':<5} {'Timestamp':<20} {'Time':<6} {'Load#':<6} {'Load Name':<18} {'Bus#':<6} {'P_sup(MW)':<12} {'Q_sup(MVar)':<13} {'V_act(pu)':<12} {'V_act(kV)':<12} {'State':<8}\n")
        f.write("-" * 125 + "\n")
        for rec in step_records:
            b_res = rec.get('bus_results', {})
            l_res = rec.get('load_results', {})
            for l_num, l_data in sorted(loads.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
                bus_num = l_data.get('bus', 0)
                base_kv = float(buses.get(bus_num, {}).get('base_kV', 132.0)) if bus_num in buses else 132.0
                cur_l = l_res.get(l_num, {})
                p_sup = cur_l.get('P_supplied_MW', float(l_data.get('P_demand', 0.0)))
                q_sup = cur_l.get('Q_supplied_Mvar', float(l_data.get('Q_demand', 0.0)))
                vm = b_res.get(bus_num, {}).get('V_mag', 1.0)
                f.write(f"{rec['step_index']:<5} {rec['timestamp']:<20} {rec['time_label']:<6} {l_num:<6} {str(l_data.get('name', f'Load_{l_num}'))[:18]:<18} {bus_num:<6} {p_sup:<12.3f} {q_sup:<13.3f} {vm:<12.5f} {(vm*base_kv):<12.3f} {'ONLINE' if l_data.get('status', 1)==1 else 'OFFLINE':<8}\n")
        f.write("=" * 125 + "\n\n")

        # 6. Section 5: Transmission Line Results Table
        f.write("SECTION 5: TRANSMISSION LINE POWER FLOWS, LOSSES & LOADINGS (CHRONOLOGICAL)\n")
        f.write("-" * 125 + "\n")
        f.write(f"{'Step':<5} {'Timestamp':<20} {'Time':<6} {'Line#':<6} {'Line Name':<18} {'From->To':<10} {'P_fwd(MW)':<11} {'Q_fwd(MVar)':<12} {'S_fwd(MVA)':<12} {'Loss(MW)':<10} {'Loading(%)':<12} {'State':<8}\n")
        f.write("-" * 125 + "\n")
        for rec in step_records:
            br_res = rec.get('branch_results', {})
            for l_num, l_data in sorted(lines.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
                br_key = f"Line_{l_num}"
                cur_br = br_res.get(br_key, {})
                pf = cur_br.get('P_MW', 0.0)
                qf = cur_br.get('Q_MVar', 0.0)
                sf = cur_br.get('S_MVA', math.sqrt(pf**2 + qf**2))
                loss = cur_br.get('Loss_MW', 0.0)
                loading = cur_br.get('Loading_Pct', 0.0)
                f_bus = l_data.get('from_bus', 0)
                t_bus = l_data.get('to_bus', 0)
                pair_str = f"{f_bus}->{t_bus}"
                l_name_str = str(l_data.get('name', f'Line_{l_num}'))[:18]
                f.write(f"{rec['step_index']:<5} {rec['timestamp']:<20} {rec['time_label']:<6} {l_num:<6} {l_name_str:<18} {pair_str:<10} {pf:<11.3f} {qf:<12.3f} {sf:<12.3f} {loss:<10.4f} {loading:<12.2f} {'ONLINE' if l_data.get('status', 1)==1 else 'OFFLINE':<8}\n")
        f.write("=" * 125 + "\n\n")

        # 7. Section 6: Transformer Results Table
        f.write("SECTION 6: TRANSFORMER POWER FLOWS, LOSSES, TAPS & LOADINGS (CHRONOLOGICAL)\n")
        f.write("-" * 125 + "\n")
        f.write(f"{'Step':<5} {'Timestamp':<20} {'Time':<6} {'Xfmr#':<6} {'Xfmr Name':<18} {'From->To':<10} {'P_fwd(MW)':<11} {'Q_fwd(MVar)':<12} {'S_fwd(MVA)':<12} {'Loss(MW)':<10} {'Tap':<8} {'Loading(%)':<12} {'State':<8}\n")
        f.write("-" * 125 + "\n")
        for rec in step_records:
            br_res = rec.get('branch_results', {})
            for x_num, x_data in sorted(xfmrs.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
                br_key = f"Xfmr_{x_num}"
                cur_br = br_res.get(br_key, {})
                pf = cur_br.get('P_MW', 0.0)
                qf = cur_br.get('Q_MVar', 0.0)
                sf = cur_br.get('S_MVA', math.sqrt(pf**2 + qf**2))
                loss = cur_br.get('Loss_MW', 0.0)
                loading = cur_br.get('Loading_Pct', 0.0)
                tap = cur_br.get('tap_ratio', float(x_data.get('tap_ratio', 1.0)))
                f_bus = x_data.get('from_bus', 0)
                t_bus = x_data.get('to_bus', 0)
                pair_str = f"{f_bus}->{t_bus}"
                x_name_str = str(x_data.get('name', f'Xfmr_{x_num}'))[:18]
                f.write(f"{rec['step_index']:<5} {rec['timestamp']:<20} {rec['time_label']:<6} {x_num:<6} {x_name_str:<18} {pair_str:<10} {pf:<11.3f} {qf:<12.3f} {sf:<12.3f} {loss:<10.4f} {tap:<8.4f} {loading:<12.2f} {'ONLINE' if x_data.get('status', 1)==1 else 'OFFLINE':<8}\n")
        f.write("=" * 125 + "\n\n")

        # 8. Section 7: Shunts, Capacitors & Reactors Table
        f.write("SECTION 7: SHUNTS, CAPACITORS & REACTORS COMPENSATION (CHRONOLOGICAL)\n")
        f.write("-" * 125 + "\n")
        f.write(f"{'Step':<5} {'Timestamp':<20} {'Time':<6} {'Type':<12} {'Num#':<6} {'Name':<18} {'Bus#':<6} {'Q_rated(MVar)':<15} {'Q_inj/abs(MVar)':<16} {'V_act(pu)':<12} {'State':<8}\n")
        f.write("-" * 125 + "\n")
        for rec in step_records:
            b_res = rec.get('bus_results', {})
            for c_num, c_data in sorted(caps.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
                bus_num = c_data.get('bus', 0)
                vm = b_res.get(bus_num, {}).get('V_mag', 1.0)
                f.write(f"{rec['step_index']:<5} {rec['timestamp']:<20} {rec['time_label']:<6} {'CAPACITOR':<12} {c_num:<6} {str(c_data.get('name', f'Cap_{c_num}'))[:18]:<18} {bus_num:<6} {float(c_data.get('Q_cap', 0.0)):<15.2f} {(float(c_data.get('Q_cap', 0.0))*(vm**2)):<16.3f} {vm:<12.5f} {'ONLINE' if c_data.get('status', 1)==1 else 'OFFLINE':<8}\n")
            for r_num, r_data in sorted(reacts.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
                bus_num = r_data.get('bus', 0)
                vm = b_res.get(bus_num, {}).get('V_mag', 1.0)
                f.write(f"{rec['step_index']:<5} {rec['timestamp']:<20} {rec['time_label']:<6} {'REACTOR':<12} {r_num:<6} {str(r_data.get('name', f'Reactor_{r_num}'))[:18]:<18} {bus_num:<6} {float(r_data.get('Q_react', 0.0)):<15.2f} {(float(r_data.get('Q_react', 0.0))*(vm**2)):<16.3f} {vm:<12.5f} {'ONLINE' if r_data.get('status', 1)==1 else 'OFFLINE':<8}\n")
            for s_num, s_data in sorted(shunts.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
                bus_num = s_data.get('bus', 0)
                vm = b_res.get(bus_num, {}).get('V_mag', 1.0)
                f.write(f"{rec['step_index']:<5} {rec['timestamp']:<20} {rec['time_label']:<6} {'SHUNT':<12} {s_num:<6} {str(s_data.get('name', f'Shunt_{s_num}'))[:18]:<18} {bus_num:<6} {float(s_data.get('Q_shunt', 0.0)):<15.2f} {(float(s_data.get('Q_shunt', 0.0))*(vm**2)):<16.3f} {vm:<12.5f} {'ONLINE' if s_data.get('status', 1)==1 else 'OFFLINE':<8}\n")
        f.write("=" * 125 + "\n\n")

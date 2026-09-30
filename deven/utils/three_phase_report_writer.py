#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
  DevEN (Develop Electric Network) - 3-Phase Unbalanced Report Writer
=============================================================================
  Generates 100% native 3-Phase reports matching the exact formatting,
  visual hierarchy, alignment, and column contracts of 1-Phase LFA:
    1. <case_name>_ALL_DATA.csv
    2. <case_name>_ALL_DATA.py
    3. <case_name>_SUMMARY.invout
    4. <case_name>_IEEE.IEEE (IEEE Std 3002.2 / IEEE 1159 Unbalance)
    5. <case_name>_CEA.cea   (CEA Transmission Planning / IEGC Criteria)
=============================================================================
"""

import os
import sys
import math
import cmath
import csv
from datetime import datetime
from typing import Dict, Any, List, Optional
import numpy as np

# Ensure root paths
_this_dir = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
_root_dir = os.path.dirname(_this_dir) if os.path.basename(_this_dir) in ('engines', 'utils', 'cli') else _this_dir
if _root_dir not in sys.path:
    sys.path.insert(0, _root_dir)


class ThreePhaseReportWriter:
    """
    Exhaustive 3-Phase Report Writer generating:
      - _ALL_DATA.csv (Columns 0-50 inputs preserved, 51+ outputs with full 3-phase metrics)
      - _ALL_DATA.py  (Standard Python case structures + 3-Phase Results dictionaries)
      - _SUMMARY.invout (DevEN standard layout with full 3-phase sections)
      - _IEEE.IEEE    (IEEE Std 3002.2 steady-state format + IEEE 1159 VUF audit)
      - _CEA.cea      (CEA Transmission Planning report + IEGC unbalance compliance)
    """

    def __init__(self, engine_3p, full_data: Dict[str, Any], solver_info: Optional[Dict[str, Any]] = None):
        self.engine_3p = engine_3p
        self.full_data = full_data
        self.solver_info = solver_info or {}

        self.bus_list = list(engine_3p.bus_list)
        self.bus_idx = dict(engine_3p.bus_idx)
        self.base_mva = float(engine_3p.base_mva)
        self.n_buses = len(self.bus_list)

        self.results_buses = getattr(engine_3p, 'results_buses', {})
        self.results_branches = getattr(engine_3p, 'results_branches', [])
        self.summary = engine_3p.get_system_summary() if hasattr(engine_3p, 'get_system_summary') else {}

        self.buses = self.full_data.get('buses', {})
        self.generators = self.full_data.get('generators', {})
        self.loads = self.full_data.get('loads', {})
        self.lines = self.full_data.get('lines', {})
        self.transformers = self.full_data.get('transformers', {})
        self.capacitors = self.full_data.get('capacitors', {})
        self.reactors = self.full_data.get('reactors', {})
        self.shunts = self.full_data.get('shunts', {})

        # Compute nodal active & reactive power injections across all buses
        # S_calc = 1/3 * V * conj(Y3P * V) * base_mva
        V_flat = np.array([engine_3p.V_abc[i][p] for i in range(self.n_buses) for p in range(3)])
        I_calc = engine_3p.Y3P.dot(V_flat)
        self.S_calc = (V_flat * np.conj(I_calc)).reshape(-1, 3) * (self.base_mva / 3.0)

        # Precompute generator 3-phase outputs
        self._compute_generator_outputs()

        # Precompute load 3-phase consumptions
        self._compute_load_consumptions()

        # Precompute system balance
        self._compute_power_balance()

    def _compute_generator_outputs(self):
        """Calculates per-phase generator MW and MVAr dispatch."""
        self.gen_outputs = {}
        for gid, gn in self.generators.items():
            st = gn.get('status', 1)
            bid = gn.get('bus')
            if st == 0 or bid not in self.bus_idx:
                self.gen_outputs[gid] = {
                    'Pa': 0.0, 'Pb': 0.0, 'Pc': 0.0, 'P_tot': 0.0,
                    'Qa': 0.0, 'Qb': 0.0, 'Qc': 0.0, 'Q_tot': 0.0,
                    'status': 'OFFLINE'
                }
                continue

            b_idx = self.bus_idx[bid]
            b_type = self.buses.get(bid, {}).get('type', 1)

            # Bus connected load
            p_ld = [0.0, 0.0, 0.0]
            q_ld = [0.0, 0.0, 0.0]
            for lid, ld in self.loads.items():
                if ld.get('bus') == bid and ld.get('status', 1) != 0:
                    exp = getattr(self.engine_3p, 'expanded_loads', {}).get(lid, {})
                    p_ld[0] += exp.get('Pa', 0.0)
                    p_ld[1] += exp.get('Pb', 0.0)
                    p_ld[2] += exp.get('Pc', 0.0)
                    q_ld[0] += exp.get('Qa', 0.0)
                    q_ld[1] += exp.get('Qb', 0.0)
                    q_ld[2] += exp.get('Qc', 0.0)

            # Bus connected shunt
            q_sh = [0.0, 0.0, 0.0]
            b_info = self.buses.get(bid, {})
            b_sh_pu = float(b_info.get('shunt_B', 0.0)) / 3.0
            for p in range(3):
                vm = abs(self.engine_3p.V_abc[b_idx][p])
                q_sh[p] -= (vm ** 2) * b_sh_pu * (self.base_mva / 3.0)

            if bid == getattr(self.engine_3p, 'slack_bus_id', None):
                p_out = [float(self.S_calc[b_idx][p].real) + p_ld[p] for p in range(3)]
                q_out = [float(self.S_calc[b_idx][p].imag) + q_ld[p] + q_sh[p] for p in range(3)]
            elif b_type == 2:  # PV Bus
                exp = getattr(self.engine_3p, 'expanded_gens', {}).get(gid, {})
                p_out = [float(exp.get('Pa', 0.0)), float(exp.get('Pb', 0.0)), float(exp.get('Pc', 0.0))]
                q_out = [float(self.S_calc[b_idx][p].imag) + q_ld[p] + q_sh[p] for p in range(3)]
            else:
                exp = getattr(self.engine_3p, 'expanded_gens', {}).get(gid, {})
                p_out = [float(exp.get('Pa', 0.0)), float(exp.get('Pb', 0.0)), float(exp.get('Pc', 0.0))]
                q_out = [float(exp.get('Qa', 0.0)), float(exp.get('Qb', 0.0)), float(exp.get('Qc', 0.0))]

            self.gen_outputs[gid] = {
                'Pa': p_out[0], 'Pb': p_out[1], 'Pc': p_out[2], 'P_tot': sum(p_out),
                'Qa': q_out[0], 'Qb': q_out[1], 'Qc': q_out[2], 'Q_tot': sum(q_out),
                'status': 'ONLINE'
            }

    def _compute_load_consumptions(self):
        """Calculates per-phase load MW and MVAr consumptions."""
        self.load_outputs = {}
        for lid, ld in self.loads.items():
            st = ld.get('status', 1)
            if st == 0:
                self.load_outputs[lid] = {
                    'Pa': 0.0, 'Pb': 0.0, 'Pc': 0.0, 'P_tot': 0.0,
                    'Qa': 0.0, 'Qb': 0.0, 'Qc': 0.0, 'Q_tot': 0.0,
                    'status': 'OFFLINE'
                }
                continue

            exp = getattr(self.engine_3p, 'expanded_loads', {}).get(lid, {})
            pa = float(exp.get('Pa', 0.0))
            pb = float(exp.get('Pb', 0.0))
            pc = float(exp.get('Pc', 0.0))
            qa = float(exp.get('Qa', 0.0))
            qb = float(exp.get('Qb', 0.0))
            qc = float(exp.get('Qc', 0.0))

            bid = ld.get('bus')
            v_avg = 1.0
            if bid in self.results_buses:
                rb = self.results_buses[bid]
                v_avg = (rb['Va_pu'] + rb['Vb_pu'] + rb['Vc_pu']) / 3.0

            self.load_outputs[lid] = {
                'Pa': pa, 'Pb': pb, 'Pc': pc, 'P_tot': pa + pb + pc,
                'Qa': qa, 'Qb': qb, 'Qc': qc, 'Q_tot': qa + qb + qc,
                'V_avg': v_avg,
                'status': 'NORMAL' if v_avg >= 0.95 else 'VOLTAGE LOW'
            }

    def _compute_power_balance(self):
        """Precomputes total system active and reactive power balance per phase and overall."""
        self.tot_p_gen = [sum(g['Pa'] for g in self.gen_outputs.values()),
                          sum(g['Pb'] for g in self.gen_outputs.values()),
                          sum(g['Pc'] for g in self.gen_outputs.values())]
        self.tot_q_gen = [sum(g['Qa'] for g in self.gen_outputs.values()),
                          sum(g['Qb'] for g in self.gen_outputs.values()),
                          sum(g['Qc'] for g in self.gen_outputs.values())]

        self.tot_p_load = [sum(l['Pa'] for l in self.load_outputs.values()),
                           sum(l['Pb'] for l in self.load_outputs.values()),
                           sum(l['Pc'] for l in self.load_outputs.values())]
        self.tot_q_load = [sum(l['Qa'] for l in self.load_outputs.values()),
                           sum(l['Qb'] for l in self.load_outputs.values()),
                           sum(l['Qc'] for l in self.load_outputs.values())]

        self.tot_p_loss = [float(self.summary.get('total_P_loss_a_MW', sum(br['Ploss_a'] for br in self.results_branches))),
                           float(self.summary.get('total_P_loss_b_MW', sum(br['Ploss_b'] for br in self.results_branches))),
                           float(self.summary.get('total_P_loss_c_MW', sum(br['Ploss_c'] for br in self.results_branches)))]
        self.tot_q_loss = float(self.summary.get('total_Q_loss_MVAR', sum(br.get('Qloss_tot', 0.0) for br in self.results_branches)))

        self.tot_cap_q = sum(float(c.get('MVAR', c.get('Q_rated', 0.0))) for c in self.capacitors.values())
        self.tot_react_q = sum(float(r.get('MVAR', r.get('Q_rated', 0.0))) for r in self.reactors.values())

    def generate_summary_header_block(self) -> str:
        """Standard DevEN System Summary & Convergence Header block."""
        conv_bool = bool(self.engine_3p.converged)
        conv_status = "✅ CONVERGED SUCCESSFUL" if conv_bool else "❌ NOT CONVERGED (MAX ITER EXCEEDED)"
        iters = int(self.engine_3p.iterations)
        tol_val = getattr(self.engine_3p, 'tol', 1e-4)
        max_iter_val = getattr(self.engine_3p, 'max_iter', 30)
        res_val = float(getattr(self.engine_3p, 'max_residual', 0.0))

        tot_gen_mw = sum(self.tot_p_gen)
        tot_gen_mvar = sum(self.tot_q_gen)
        tot_gen_mva = math.sqrt(tot_gen_mw**2 + tot_gen_mvar**2)

        tot_ld_mw = sum(self.tot_p_load)
        tot_ld_mvar = sum(self.tot_q_load)
        tot_ld_mva = math.sqrt(tot_ld_mw**2 + tot_ld_mvar**2)

        tot_loss_mw = sum(self.tot_p_loss)

        slack_id = getattr(self.engine_3p, 'slack_bus_id', None)
        slack_gen_id = None
        slack_gen = None
        for gid, g in self.generators.items():
            if g.get('bus') == slack_id and g.get('status', 1) != 0:
                slack_gen_id = gid
                slack_gen = g
                break

        sb_out = self.gen_outputs.get(slack_gen_id, {'P_tot': 0.0, 'Q_tot': 0.0, 'Pa': 0.0, 'Pb': 0.0, 'Pc': 0.0, 'Qa': 0.0, 'Qb': 0.0, 'Qc': 0.0})
        sb_rb = self.results_buses.get(slack_id, {'Va_pu': 1.0, 'Vb_pu': 1.0, 'Vc_pu': 1.0, 'Va_kV': 0.0, 'ang_a_deg': 0.0, 'ang_b_deg': -120.0, 'ang_c_deg': 120.0})

        lines = []
        lines.append("=" * 105)
        lines.append("⚡ 3-PHASE LOAD FLOW ANALYSIS — SYSTEM SUMMARY & CONVERGENCE REPORT")
        lines.append("=" * 105)
        lines.append(f"Solver Engine           : DevEN 3-Phase Newton-Raphson (3P-NR Power Flow Solver)")
        lines.append("-" * 105)
        lines.append("📌 SOLVER CONVERGENCE & PARAMETERS:")
        lines.append("-" * 105)
        lines.append(f"Convergence Status      : {conv_status}")
        lines.append(f"Iterations Executed     : {iters} iterations")
        lines.append(f"Input Tolerance Setting : {tol_val}")
        lines.append(f"Input Max Iterations    : {max_iter_val}")
        lines.append(f"Final Max Mismatch      : Max |dPQ| = {res_val:.6f} p.u. ({res_val * (self.base_mva / 3.0):.6f} MW/phase)")
        lines.append("-" * 105)
        lines.append("📊 SYSTEM POWER BALANCE (INPUT DEMAND vs OUTPUT GENERATION):")
        lines.append("-" * 105)
        lines.append(f"Total Network Buses     : {self.n_buses}")
        lines.append(f"Total Lines/Xfmrs       : {len(self.lines)} lines , {len(self.transformers)} transformers")
        lines.append(f"Total Input Demand      : -{tot_ld_mw:.6f} MW , -{tot_ld_mvar:.6f} Mvar ({tot_ld_mva:.6f} MVA)")
        lines.append(f"   • Phase A Demand     : -{self.tot_p_load[0]:.4f} MW , -{self.tot_q_load[0]:.4f} Mvar")
        lines.append(f"   • Phase B Demand     : -{self.tot_p_load[1]:.4f} MW , -{self.tot_q_load[1]:.4f} Mvar")
        lines.append(f"   • Phase C Demand     : -{self.tot_p_load[2]:.4f} MW , -{self.tot_q_load[2]:.4f} Mvar")
        lines.append(f"Total Output Generation : +{tot_gen_mw:.6f} MW , +{tot_gen_mvar:.6f} Mvar ({tot_gen_mva:.6f} MVA)")
        lines.append(f"   • Phase A Generation : +{self.tot_p_gen[0]:.4f} MW , +{self.tot_q_gen[0]:.4f} Mvar")
        lines.append(f"   • Phase B Generation : +{self.tot_p_gen[1]:.4f} MW , +{self.tot_q_gen[1]:.4f} Mvar")
        lines.append(f"   • Phase C Generation : +{self.tot_p_gen[2]:.4f} MW , +{self.tot_q_gen[2]:.4f} Mvar")
        lines.append(f"Total Network Losses    : {tot_loss_mw:.6f} MW (Phase A: {self.tot_p_loss[0]:.4f}, B: {self.tot_p_loss[1]:.4f}, C: {self.tot_p_loss[2]:.4f} MW)")
        lines.append(f"Max Voltage Unbalance   : {self.summary.get('max_VUF_pct', 0.0):.4f}% at Bus {self.summary.get('worst_bus_VUF', '-')}")
        lines.append("-" * 105)
        lines.append("🔥 SLACK BUS GENERATION & VOLTAGE DETAILS:")
        lines.append("-" * 105)
        lines.append(f"  Generator ID          : Gen {slack_gen_id} ({slack_gen.get('name', 'Slack_Gen') if slack_gen else 'Slack'})")
        lines.append(f"  Connected Bus         : Bus {slack_id} ({self.buses.get(slack_id, {}).get('name', '')}) [Slack Bus Type 3]")
        lines.append(f"  Active Power (P)      : +{sb_out['P_tot']:.5f} MW (Pa: {sb_out['Pa']:.4f}, Pb: {sb_out['Pb']:.4f}, Pc: {sb_out['Pc']:.4f} MW)")
        lines.append(f"  Reactive Power (Q)    : +{sb_out['Q_tot']:.5f} Mvar (Qa: {sb_out['Qa']:.4f}, Qb: {sb_out['Qb']:.4f}, Qc: {sb_out['Qc']:.4f} Mvar)")
        lines.append(f"  Bus Phase Voltages    : Va = {sb_rb['Va_pu']:.5f} pu, Vb = {sb_rb['Vb_pu']:.5f} pu, Vc = {sb_rb['Vc_pu']:.5f} pu")
        lines.append(f"  Bus Phase Angles      : angA = {sb_rb['ang_a_deg']:.2f}°, angB = {sb_rb['ang_b_deg']:.2f}°, angC = {sb_rb['ang_c_deg']:.2f}°")
        lines.append(f"  Generator Status      : ONLINE")
        lines.append("-" * 105)
        return "\n".join(lines) + "\n\n"

    # -------------------------------------------------------------------------
    # 1. SUMMARY .invout Report
    # -------------------------------------------------------------------------
    def write_txt_summary(self, filename: str) -> str:
        """
        Generates master .invout report formatted in exact DevEN layout,
        containing 100% 3-Phase tables for Voltages, Gens, Loads, Lines, and Transformers.
        """
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(self.generate_summary_header_block())
            f.write("=" * 105 + "\n")
            f.write("3-PHASE LOAD FLOW ANALYSIS - COMPLETE SYSTEM SUMMARY REPORT\n")
            f.write("ಮೂರು ಹಂತದ ವಿದ್ಯುತ್ ಹರಿವಿನ ವಿಶ್ಲೇಷಣೆ (3-Phase Power Flow Analysis)\n")
            f.write("=" * 105 + "\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Governing Standards: IEEE Std 3002.2 / IEEE Std 1159 (Power Quality) / IEC 61000-4-30\n")
            f.write("=" * 105 + "\n\n")

            # SECTION 1: 3-PHASE BUS VOLTAGE & UNBALANCE SUMMARY
            f.write("SECTION 1: 3-PHASE BUS VOLTAGE & UNBALANCE PROFILE (VUF% Limit <= 2.0%)\n")
            f.write("-" * 145 + "\n")
            f.write(f"{'Bus#':<6} {'Name':<16} {'Base_kV':<8} {'Va(pu)':<9} {'Vb(pu)':<9} {'Vc(pu)':<9} "
                    f"{'angA(°)':<9} {'angB(°)':<9} {'angC(°)':<9} {'V0(pu)':<9} {'V1(pu)':<9} {'V2(pu)':<9} {'VUF(%)':<9} {'Status':<8}\n")
            f.write("-" * 145 + "\n")
            for bid in self.bus_list:
                r = self.results_buses.get(bid, {})
                f.write(f"{bid:<6} {r.get('name', f'Bus_{bid}')[:15]:<16} {r.get('base_kV', 132.0):<8.1f} "
                        f"{r.get('Va_pu', 1.0):<9.5f} {r.get('Vb_pu', 1.0):<9.5f} {r.get('Vc_pu', 1.0):<9.5f} "
                        f"{r.get('ang_a_deg', 0.0):<9.2f} {r.get('ang_b_deg', -120.0):<9.2f} {r.get('ang_c_deg', 120.0):<9.2f} "
                        f"{r.get('V0_pu', 0.0):<9.5f} {r.get('V1_pu', 1.0):<9.5f} {r.get('V2_pu', 0.0):<9.5f} "
                        f"{r.get('VUF_pct', 0.0):<9.3f} {r.get('status', 'NORMAL'):<8}\n")
            f.write("-" * 145 + "\n\n")

            # SECTION 2: 3-PHASE GENERATOR SUMMARY
            f.write("SECTION 2: 3-PHASE GENERATOR DISPATCH SUMMARY\n")
            f.write("-" * 145 + "\n")
            f.write(f"{'Gen#':<6} {'Name':<16} {'Bus':<6} {'P_tot(MW)':<11} {'Pa(MW)':<10} {'Pb(MW)':<10} {'Pc(MW)':<10} "
                    f"{'Q_tot(Mvar)':<12} {'Qa(Mvar)':<10} {'Qb(Mvar)':<10} {'Qc(Mvar)':<10} {'V_set(pu)':<10} {'Status':<8}\n")
            f.write("-" * 145 + "\n")
            for gid, gn in sorted(self.generators.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
                gout = self.gen_outputs.get(gid, {'P_tot': 0.0, 'Pa': 0.0, 'Pb': 0.0, 'Pc': 0.0,
                                                   'Q_tot': 0.0, 'Qa': 0.0, 'Qb': 0.0, 'Qc': 0.0, 'status': 'OFFLINE'})
                f.write(f"{gid:<6} {gn.get('name', f'Gen_{gid}')[:15]:<16} {gn.get('bus', ''):<6} "
                        f"{gout['P_tot']:<+11.4f} {gout['Pa']:<+10.3f} {gout['Pb']:<+10.3f} {gout['Pc']:<+10.3f} "
                        f"{gout['Q_tot']:<+12.4f} {gout['Qa']:<+10.3f} {gout['Qb']:<+10.3f} {gout['Qc']:<+10.3f} "
                        f"{gn.get('V_set', 1.0):<10.4f} {gout['status']:<8}\n")
            f.write("-" * 145 + "\n\n")

            # SECTION 3: 3-PHASE LOAD DATA
            f.write("SECTION 3: 3-PHASE LOAD CONSUMPTION SUMMARY\n")
            f.write("-" * 145 + "\n")
            f.write(f"{'Load#':<6} {'Name':<16} {'Bus':<6} {'P_tot(MW)':<11} {'Pa(MW)':<10} {'Pb(MW)':<10} {'Pc(MW)':<10} "
                    f"{'Q_tot(Mvar)':<12} {'Qa(Mvar)':<10} {'Qb(Mvar)':<10} {'Qc(Mvar)':<10} {'V_avg(pu)':<10} {'Status':<10}\n")
            f.write("-" * 145 + "\n")
            for lid, ld in sorted(self.loads.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
                lout = self.load_outputs.get(lid, {'P_tot': 0.0, 'Pa': 0.0, 'Pb': 0.0, 'Pc': 0.0,
                                                    'Q_tot': 0.0, 'Qa': 0.0, 'Qb': 0.0, 'Qc': 0.0, 'V_avg': 1.0, 'status': 'NORMAL'})
                f.write(f"{lid:<6} {ld.get('name', f'Load_{lid}')[:15]:<16} {ld.get('bus', ''):<6} "
                        f"{lout['P_tot']:<11.4f} {lout['Pa']:<10.3f} {lout['Pb']:<10.3f} {lout['Pc']:<10.3f} "
                        f"{lout['Q_tot']:<12.4f} {lout['Qa']:<10.3f} {lout['Qb']:<10.3f} {lout['Qc']:<10.3f} "
                        f"{lout['V_avg']:<10.4f} {lout['status']:<10}\n")
            f.write("-" * 145 + "\n\n")

            # SECTION 4: 3-PHASE TRANSMISSION LINE FLOWS
            f.write("SECTION 4: 3-PHASE TRANSMISSION LINE FLOWS, NEUTRAL CURRENTS & LOSSES\n")
            f.write("-" * 165 + "\n")
            f.write(f"{'Line#':<6} {'From->To':<14} {'Pa(MW)':<9} {'Pb(MW)':<9} {'Pc(MW)':<9} {'Ptot(MW)':<10} "
                    f"{'Qa(Mvar)':<9} {'Qb(Mvar)':<9} {'Qc(Mvar)':<9} {'Qtot(Mvar)':<11} {'In(A)':<8} {'Loss(kW)':<10} {'Load%':<7} {'Status':<8}\n")
            f.write("-" * 165 + "\n")
            for br in self.results_branches:
                fb = br['from_bus']
                tb = br['to_bus']
                is_xfmr = any(x.get('from_bus') == fb and x.get('to_bus') == tb for x in self.transformers.values())
                if is_xfmr:
                    continue
                tag = f"{fb}->{tb}"
                lid = str(br.get('line_id', ''))
                ptot = br['P_from_a'] + br['P_from_b'] + br['P_from_c']
                qtot = br['Q_from_a'] + br['Q_from_b'] + br['Q_from_c']
                f.write(f"{lid:<6} {tag:<14} "
                        f"{br['P_from_a']:<9.2f} {br['P_from_b']:<9.2f} {br['P_from_c']:<9.2f} {ptot:<10.2f} "
                        f"{br['Q_from_a']:<9.2f} {br['Q_from_b']:<9.2f} {br['Q_from_c']:<9.2f} {qtot:<11.2f} "
                        f"{br['I_neutral_A']:<8.1f} {br['Ploss_tot'] * 1000.0:<10.1f} {br.get('loading_pct', 0.0):<7.1f} {'NORMAL':<8}\n")
            f.write("-" * 165 + "\n\n")

            # SECTION 5: 3-PHASE TRANSFORMER FLOWS
            f.write("SECTION 5: 3-PHASE TRANSFORMER FLOWS & LOSSES\n")
            f.write("-" * 165 + "\n")
            f.write(f"{'Xfmr#':<6} {'From->To':<14} {'Pa(MW)':<9} {'Pb(MW)':<9} {'Pc(MW)':<9} {'Ptot(MW)':<10} "
                    f"{'Qa(Mvar)':<9} {'Qb(Mvar)':<9} {'Qc(Mvar)':<9} {'Qtot(Mvar)':<11} {'In(A)':<8} {'Loss(kW)':<10} {'Tap':<6} {'Load%':<7} {'Status':<8}\n")
            f.write("-" * 165 + "\n")
            for br in self.results_branches:
                fb = br['from_bus']
                tb = br['to_bus']
                is_xfmr = any(x.get('from_bus') == fb and x.get('to_bus') == tb for x in self.transformers.values())
                if not is_xfmr:
                    continue
                tag = f"{fb}->{tb}"
                xid = str(br.get('line_id', ''))
                ptot = br['P_from_a'] + br['P_from_b'] + br['P_from_c']
                qtot = br['Q_from_a'] + br['Q_from_b'] + br['Q_from_c']
                f.write(f"{xid:<6} {tag:<14} "
                        f"{br['P_from_a']:<9.2f} {br['P_from_b']:<9.2f} {br['P_from_c']:<9.2f} {ptot:<10.2f} "
                        f"{br['Q_from_a']:<9.2f} {br['Q_from_b']:<9.2f} {br['Q_from_c']:<9.2f} {qtot:<11.2f} "
                        f"{br['I_neutral_A']:<8.1f} {br['Ploss_tot'] * 1000.0:<10.1f} {1.0:<6.3f} {br.get('loading_pct', 0.0):<7.1f} {'NORMAL':<8}\n")
            f.write("-" * 165 + "\n\n")

            # SECTION 6-10: Compensation Devices
            f.write("SECTION 6: CAPACITOR BANK DATA\n")
            f.write("-" * 90 + "\n")
            if self.capacitors:
                f.write(f"{'Cap#':<6} {'Name':<18} {'Bus':<6} {'Q_cap(Mvar)':<14} {'V_actual(pu)':<14} {'Status':<10}\n")
                f.write("-" * 90 + "\n")
                for cid, cap in self.capacitors.items():
                    bid = cap.get('bus')
                    v_act = self.results_buses.get(bid, {}).get('V1_pu', 1.0)
                    f.write(f"{cid:<6} {cap.get('name', f'Cap_{cid}')[:17]:<18} {bid:<6} {float(cap.get('MVAR', cap.get('Q_rated', 0.0))):<14.3f} {v_act:<14.4f} {'ONLINE':<10}\n")
            else:
                f.write("No capacitor banks present in network.\n")
            f.write("\n")

            f.write("SECTION 7: REACTOR DATA\n")
            f.write("-" * 90 + "\n")
            if self.reactors:
                f.write(f"{'React#':<6} {'Name':<18} {'Bus':<6} {'Q_react(Mvar)':<14} {'V_actual(pu)':<14} {'Status':<10}\n")
                f.write("-" * 90 + "\n")
                for rid, r in self.reactors.items():
                    bid = r.get('bus')
                    v_act = self.results_buses.get(bid, {}).get('V1_pu', 1.0)
                    f.write(f"{rid:<6} {r.get('name', f'React_{rid}')[:17]:<18} {bid:<6} {float(r.get('MVAR', r.get('Q_rated', 0.0))):<14.3f} {v_act:<14.4f} {'ONLINE':<10}\n")
            else:
                f.write("No shunt reactors present in network.\n")
            f.write("\n")

            # SECTION 12: SYSTEM UNBALANCE & STANDARDS AUDIT
            f.write("SECTION 12: 3-PHASE SYSTEM UNBALANCE & STANDARDS COMPLIANCE AUDIT\n")
            f.write("=" * 105 + "\n")
            f.write(f"  • Maximum System VUF%   : {self.summary.get('max_VUF_pct', 0.0):.4f}% at Bus {self.summary.get('worst_bus_VUF')}\n")
            f.write(f"  • IEEE Std 1159 Limit   : VUF% <= 2.0% (Point of Common Coupling) -> {'✅ PASS' if self.summary.get('max_VUF_pct', 0.0) <= 2.0 else '⚠️ VIOLATION'}\n")
            f.write(f"  • IEC 61000-4-30 Limit  : VUF% <= 2.0% (Class A Power Quality)  -> {'✅ PASS' if self.summary.get('max_VUF_pct', 0.0) <= 2.0 else '⚠️ VIOLATION'}\n")
            f.write(f"  • NEMA MG-1 Derating    : VUF% <= 1.0% (Zero Derating Required)   -> {'✅ OPTIMAL' if self.summary.get('max_VUF_pct', 0.0) <= 1.0 else '⚠️ DERATING APPLIES'}\n")
            f.write(f"  • Total Active Losses   : Phase A = {self.tot_p_loss[0]:.3f} MW | Phase B = {self.tot_p_loss[1]:.3f} MW | Phase C = {self.tot_p_loss[2]:.3f} MW\n")
            f.write(f"  • Net 3-Phase Losses    : {sum(self.tot_p_loss):.4f} MW ({sum(self.tot_p_loss)*100.0/max(sum(self.tot_p_gen), 1e-5):.2f}% of Generation)\n")
            f.write("=" * 105 + "\n")

        return filename

    # -------------------------------------------------------------------------
    # 2. IEEE Std 3002.2 / IEEE 1159 Report (.IEEE)
    # -------------------------------------------------------------------------
    def write_ieee_report(self, filename: str) -> str:
        """
        Generates IEEE Std 3002.2 steady-state load flow report enriched with
        genuine 3-phase per-phase tables and IEEE Std 1159 unbalance audit.
        """
        case_name = os.path.basename(filename).replace('_IEEE.IEEE', '').replace('.IEEE', '')
        tot_gen_mw = sum(self.tot_p_gen)
        tot_gen_mvar = sum(self.tot_q_gen)
        tot_gen_mva = math.sqrt(tot_gen_mw**2 + tot_gen_mvar**2)

        tot_ld_mw = sum(self.tot_p_load)
        tot_ld_mvar = sum(self.tot_q_load)
        tot_ld_mva = math.sqrt(tot_ld_mw**2 + tot_ld_mvar**2)
        tot_loss_mw = sum(self.tot_p_loss)

        with open(filename, 'w', encoding='utf-8') as f:
            f.write("=" * 145 + "\n")
            f.write("                        IEEE Std 3002.2-2018 / IEEE Std 1159 3-PHASE LOAD FLOW & UNBALANCE REPORT                        \n")
            f.write("                             (IEEE Recommended Practice for Conduct of Power Flow Studies)                         \n")
            f.write("=========================================================================================================================================\n")
            f.write(f"Case / System Name:       {case_name}\n")
            f.write(f"Study Timestamp:          {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Governing Standard:       IEEE Std 3002.2-2018 & IEEE Std 1159 (Power Quality Voltage Unbalance <= 2%)\n")
            f.write(f"Solver Engine:            DevEN 3-Phase Newton-Raphson Physics Engine (3P-NR)\n")
            f.write(f"Convergence Status:       {'✅ CONVERGED' if self.engine_3p.converged else '❌ DIVERGED'} in {self.engine_3p.iterations} iteration(s)\n")
            f.write(f"Max Voltage Unbalance:    {self.summary.get('max_VUF_pct', 0.0):.4f}% (Bus {self.summary.get('worst_bus_VUF')})\n")
            f.write(f"System Base Power:        {self.base_mva:.1f} MVA (Phase Base: {self.base_mva/3.0:.1f} MVA)\n")
            f.write(f"Network Inventory:        {self.n_buses} Buses, {len(self.generators)} Generators, {len(self.loads)} Loads, {len(self.lines)} Lines, {len(self.transformers)} Transformers\n")
            f.write("-" * 145 + "\n\n")

            # PART 1: POWER BALANCE
            f.write("PART 1: 3-PHASE SYSTEM ACTIVE & REACTIVE POWER BALANCE SUMMARY\n")
            f.write("-" * 145 + "\n")
            f.write(f"  • Gross Active Generation (P_gen):     {tot_gen_mw:12.4f} MW   (Phase A: {self.tot_p_gen[0]:.2f}, B: {self.tot_p_gen[1]:.2f}, C: {self.tot_p_gen[2]:.2f} MW)\n")
            f.write(f"  • Gross Reactive Generation (Q_gen):   {tot_gen_mvar:12.4f} Mvar (Phase A: {self.tot_q_gen[0]:.2f}, B: {self.tot_q_gen[1]:.2f}, C: {self.tot_q_gen[2]:.2f} Mvar)  Apparent S: {tot_gen_mva:.2f} MVA\n")
            f.write(f"  • Total Active Demand (P_load):        {tot_ld_mw:12.4f} MW   (Phase A: {self.tot_p_load[0]:.2f}, B: {self.tot_p_load[1]:.2f}, C: {self.tot_p_load[2]:.2f} MW)\n")
            f.write(f"  • Total Reactive Demand (Q_load):      {tot_ld_mvar:12.4f} Mvar (Phase A: {self.tot_q_load[0]:.2f}, B: {self.tot_q_load[1]:.2f}, C: {self.tot_q_load[2]:.2f} Mvar)  Apparent S: {tot_ld_mva:.2f} MVA\n")
            f.write(f"  • Shunt Inflow (Cap/Reactor):          {self.tot_cap_q - self.tot_react_q:+12.4f} Mvar\n")
            f.write(f"  • Net Active Losses (P_loss):          {tot_loss_mw:12.4f} MW   (Phase A: {self.tot_p_loss[0]:.2f}, B: {self.tot_p_loss[1]:.2f}, C: {self.tot_p_loss[2]:.2f} MW)\n")
            f.write("=" * 145 + "\n\n")

            # PART 2: 3-PHASE BUS VOLTAGE & UNBALANCE TABLE
            f.write("PART 2: 3-PHASE BUS VOLTAGE, ANGLE & UNBALANCE PROFILE TABLE (IEEE +/-5% Steady-State Range: 0.950 - 1.050 p.u.)\n")
            f.write("-" * 145 + "\n")
            f.write(f"{'Bus#':<6} {'Bus Name':<16} {'Type':<6} {'Base kV':<8} {'Va(pu)':<8} {'Vb(pu)':<8} {'Vc(pu)':<8} "
                    f"{'AngA(°)':<8} {'AngB(°)':<8} {'AngC(°)':<8} {'V0(pu)':<8} {'V1(pu)':<8} {'V2(pu)':<8} {'VUF(%)':<8} {'IEEE Status'}\n")
            f.write("-" * 145 + "\n")
            for bid in self.bus_list:
                r = self.results_buses.get(bid, {})
                b_info = self.buses.get(bid, {})
                b_type = b_info.get('type', 1)
                type_str = 'Slack' if b_type == 3 else ('PV' if b_type == 2 else 'PQ')

                va = r.get('Va_pu', 1.0)
                vb = r.get('Vb_pu', 1.0)
                vc = r.get('Vc_pu', 1.0)
                vuf = r.get('VUF_pct', 0.0)

                v_min = min(va, vb, vc)
                v_max = max(va, vb, vc)

                if v_min < 0.95:
                    st_str = "⚠️ LOW (<0.95)"
                elif v_max > 1.05:
                    st_str = "⚠️ HIGH (>1.05)"
                elif vuf > 2.0:
                    st_str = "⚠️ VUF VIOLATION"
                else:
                    st_str = "✅ NORMAL"

                f.write(f"{bid:<6} {r.get('name', f'Bus_{bid}')[:15]:<16} {type_str:<6} {r.get('base_kV', 132.0):<8.1f} "
                        f"{va:<8.4f} {vb:<8.4f} {vc:<8.4f} "
                        f"{r.get('ang_a_deg', 0.0):<8.1f} {r.get('ang_b_deg', -120.0):<8.1f} {r.get('ang_c_deg', 120.0):<8.1f} "
                        f"{r.get('V0_pu', 0.0):<8.4f} {r.get('V1_pu', 1.0):<8.4f} {r.get('V2_pu', 0.0):<8.4f} "
                        f"{vuf:<8.3f} {st_str}\n")
            f.write("=" * 145 + "\n\n")

            # PART 3: 3-PHASE BRANCH POWER FLOWS & LOADING
            f.write("PART 3: 3-PHASE TRANSMISSION LINE & TRANSFORMER POWER FLOWS & THERMAL LOADING\n")
            f.write("-" * 155 + "\n")
            f.write(f"{'Type':<5} {'ID':<5} {'From->To':<14} {'Pa(MW)':<9} {'Pb(MW)':<9} {'Pc(MW)':<9} "
                    f"{'Qa(Mvar)':<9} {'Qb(Mvar)':<9} {'Qc(Mvar)':<9} {'Ptot(MW)':<10} {'Qtot(Mvar)':<11} {'In(A)':<8} {'Loss(kW)':<10} {'Load%':<7} {'Status'}\n")
            f.write("-" * 155 + "\n")
            for br in self.results_branches:
                fb = br['from_bus']
                tb = br['to_bus']
                is_xfmr = any(x.get('from_bus') == fb and x.get('to_bus') == tb for x in self.transformers.values())
                b_type_str = 'XFMR' if is_xfmr else 'LINE'
                tag = f"{fb}->{tb}"
                bid = str(br.get('line_id', ''))
                ptot = br['P_from_a'] + br['P_from_b'] + br['P_from_c']
                qtot = br['Q_from_a'] + br['Q_from_b'] + br['Q_from_c']
                ld = float(br.get('loading_pct', 0.0))
                st = "❌ OVERLOAD" if ld > 100.0 else ("⚠️ HIGH" if ld > 80.0 else "✅ NORMAL")

                f.write(f"{b_type_str:<5} {bid:<5} {tag:<14} "
                        f"{br['P_from_a']:<9.2f} {br['P_from_b']:<9.2f} {br['P_from_c']:<9.2f} "
                        f"{br['Q_from_a']:<9.2f} {br['Q_from_b']:<9.2f} {br['Q_from_c']:<9.2f} "
                        f"{ptot:<10.2f} {qtot:<11.2f} {br['I_neutral_A']:<8.1f} {br['Ploss_tot'] * 1000.0:<10.1f} {ld:<7.1f} {st}\n")
            f.write("=" * 155 + "\n\n")

            # PART 4: 3-PHASE GENERATOR DISPATCH
            f.write("PART 4: 3-PHASE GENERATOR DISPATCH & REACTIVE POWER UTILIZATION\n")
            f.write("-" * 145 + "\n")
            f.write(f"{'Gen#':<6} {'Bus':<6} {'Bus Name':<16} {'Pa(MW)':<10} {'Pb(MW)':<10} {'Pc(MW)':<10} "
                    f"{'Qa(Mvar)':<10} {'Qb(Mvar)':<10} {'Qc(Mvar)':<10} {'Ptot(MW)':<11} {'Qtot(Mvar)':<11} {'V_set':<8} {'Status'}\n")
            f.write("-" * 145 + "\n")
            for gid, gn in sorted(self.generators.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
                gout = self.gen_outputs.get(gid, {'P_tot': 0.0, 'Pa': 0.0, 'Pb': 0.0, 'Pc': 0.0,
                                                   'Q_tot': 0.0, 'Qa': 0.0, 'Qb': 0.0, 'Qc': 0.0, 'status': 'OFFLINE'})
                bid = gn.get('bus', '')
                bname = self.buses.get(bid, {}).get('name', f"Bus_{bid}")
                f.write(f"{gid:<6} {bid:<6} {bname[:15]:<16} "
                        f"{gout['Pa']:<+10.2f} {gout['Pb']:<+10.2f} {gout['Pc']:<+10.2f} "
                        f"{gout['Qa']:<+10.2f} {gout['Qb']:<+10.2f} {gout['Qc']:<+10.2f} "
                        f"{gout['P_tot']:<+11.2f} {gout['Q_tot']:<+11.2f} {gn.get('V_set', 1.0):<8.3f} {gout['status']}\n")
            f.write("=" * 145 + "\n\n")

            # PART 5: IEEE 1159 VOLTAGE UNBALANCE ASSESSMENT
            f.write("PART 5: IEEE Std 1159 VOLTAGE UNBALANCE ASSESSMENT (VUF% = |V2| / |V1| * 100%)\n")
            f.write("=" * 145 + "\n")
            vuf_max = self.summary.get('max_VUF_pct', 0.0)
            worst_b = self.summary.get('worst_bus_VUF', '-')
            viols = [b for b, r in self.results_buses.items() if r.get('VUF_pct', 0.0) > 2.0]
            f.write(f"  • Maximum System VUF%   : {vuf_max:.4f}% at Bus {worst_b}\n")
            f.write(f"  • IEEE Std 1159 Limit   : VUF% <= 2.0% at Point of Common Coupling (PCC)\n")
            f.write(f"  • Compliant Buses       : {self.n_buses - len(viols)} / {self.n_buses} ({(self.n_buses - len(viols))*100.0/self.n_buses:.1f}%)\n")
            f.write(f"  • Unbalance Violations  : {len(viols)} buses\n")
            f.write(f"  • Overall Verdict       : {'✅ COMPLIANT' if len(viols) == 0 else '⚠️ UNBALANCE VIOLATION DETECTED'}\n")
            f.write("=" * 145 + "\n")

        return filename

    # -------------------------------------------------------------------------
    # 3. CEA Official Transmission Planning Report (.cea)
    # -------------------------------------------------------------------------
    def write_cea_report(self, filename: str) -> str:
        """
        Generates CEA Transmission Planning Report with per-phase kV/pu profiles,
        statutory Indian Electricity Grid Code (IEGC) voltage limits, and unbalance compliance.
        """
        case_name = os.path.basename(filename).replace('_CEA.cea', '').replace('.cea', '')
        tot_gen_mw = sum(self.tot_p_gen)
        tot_gen_mvar = sum(self.tot_q_gen)
        tot_ld_mw = sum(self.tot_p_load)
        tot_ld_mvar = sum(self.tot_q_load)
        tot_loss_mw = sum(self.tot_p_loss)

        def _get_cea_limits_info(base_kv):
            kv = float(base_kv)
            if kv >= 700.0: return 0.95, 1.05, "728.0 - 800.0 kV (0.95 - 1.05 pu)"
            elif kv >= 380.0: return 0.95, 1.05, "380.0 - 420.0 kV (0.95 - 1.05 pu)"
            elif kv >= 190.0: return 0.90, 1.1136, "198.0 - 245.0 kV (0.90 - 1.11 pu)"
            elif kv >= 100.0: return 0.9242, 1.0985, "122.0 - 145.0 kV (0.92 - 1.10 pu)"
            elif kv >= 50.0: return 0.909, 1.098, "60.0 - 72.5 kV (+/-10%)"
            elif kv >= 30.0: return 0.909, 1.090, "30.0 - 36.0 kV (+/-10%)"
            else: return 0.90, 1.10, f"{kv*0.9:.1f} - {kv*1.1:.1f} kV (+/-10%)"

        with open(filename, 'w', encoding='utf-8') as f:
            f.write("=" * 145 + "\n")
            f.write("                    CENTRAL ELECTRICITY AUTHORITY (CEA) — 3-PHASE TRANSMISSION PLANNING LOAD FLOW REPORT                    \n")
            f.write("                         (Governed by CEA Manual on Transmission Planning Criteria & IEGC)                          \n")
            f.write("=========================================================================================================================================\n")
            f.write(f"Power System Network:     {case_name}\n")
            f.write(f"Report Date & Time:       {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Planning Regulatory Body: Central Electricity Authority (CEA), Ministry of Power, Govt. of India\n")
            f.write(f"Governing Criteria:       CEA Manual on Transmission Planning Criteria (2023/2025 Edition) & IEGC Regulations\n")
            f.write(f"Operating Scenario:       3-Phase Unbalanced Steady-State Base Case (Normal N-0 Operating Condition)\n")
            f.write(f"Load Flow Engine:         DevEN 3-Phase Newton-Raphson Engine (3P-NR)\n")
            f.write(f"Solution Convergence:     {'✅ CONVERGED' if self.engine_3p.converged else '❌ DIVERGED'} in {self.engine_3p.iterations} iteration(s)\n")
            f.write(f"System Base MVA:          {self.base_mva:.1f} MVA\n")
            f.write(f"Network Substations:      {self.n_buses} Substations/Nodes\n")
            f.write(f"Transmission Feeders:     {len(self.lines)} Overhead Lines, {len(self.transformers)} Interconnecting Transformers (ICTs)\n")
            f.write("-" * 145 + "\n\n")

            # SECTION 1: ASSET INVENTORY
            f.write("SECTION 1: SUBSTATION VOLTAGE LEVEL HIERARCHY & NETWORK ASSET INVENTORY\n")
            f.write("-" * 145 + "\n")
            f.write(f"  • Total Substations     : {self.n_buses}\n")
            f.write(f"  • Transmission Lines    : {len(self.lines)}\n")
            f.write(f"  • Power Transformers    : {len(self.transformers)}\n")
            f.write(f"  • Generating Stations   : {len(self.generators)}\n")
            f.write(f"  • Bulk Demand Centers   : {len(self.loads)}\n\n")

            # SECTION 2: GRID GENERATION, BULK DEMAND & LOSS BALANCE
            f.write("SECTION 2: 3-PHASE GRID GENERATION, BULK DEMAND & TRANSMISSION LOSS BALANCE\n")
            f.write("-" * 145 + "\n")
            f.write(f"  • Total Grid Generation : {tot_gen_mw:.4f} MW , {tot_gen_mvar:.4f} Mvar (Pa: {self.tot_p_gen[0]:.2f}, Pb: {self.tot_p_gen[1]:.2f}, Pc: {self.tot_p_gen[2]:.2f} MW)\n")
            f.write(f"  • Total Bulk Demand     : {tot_ld_mw:.4f} MW , {tot_ld_mvar:.4f} Mvar (Pa: {self.tot_p_load[0]:.2f}, Pb: {self.tot_p_load[1]:.2f}, Pc: {self.tot_p_load[2]:.2f} MW)\n")
            f.write(f"  • Total Shunt VAr Inflow: {self.tot_cap_q - self.tot_react_q:+.4f} Mvar\n")
            f.write(f"  • Total Transmission Loss: {tot_loss_mw:.4f} MW ({tot_loss_mw*100.0/max(tot_gen_mw, 1e-5):.2f}% of Grid Gen)\n")
            f.write(f"    - Phase A Losses      : {self.tot_p_loss[0]:.3f} MW\n")
            f.write(f"    - Phase B Losses      : {self.tot_p_loss[1]:.3f} MW\n")
            f.write(f"    - Phase C Losses      : {self.tot_p_loss[2]:.3f} MW\n\n")

            # SECTION 3: SUBSTATION VOLTAGE REGULATION & IEGC COMPLIANCE
            f.write("SECTION 3: CEA STEADY-STATE SUBSTATION 3-PHASE VOLTAGE REGULATION & IEGC UNBALANCE COMPLIANCE\n")
            f.write("-" * 155 + "\n")
            f.write(f"{'Bus#':<6} {'Substation Name':<18} {'Base kV':<8} {'Va (kV)':<9} {'Vb (kV)':<9} {'Vc (kV)':<9} "
                    f"{'Va (pu)':<8} {'Vb (pu)':<8} {'Vc (pu)':<8} {'CEA Statutory Range':<28} {'VUF (%)':<8} {'IEGC Compliance'}\n")
            f.write("-" * 155 + "\n")
            for bid in self.bus_list:
                r = self.results_buses.get(bid, {})
                base_kv = float(r.get('base_kV', 132.0))
                min_pu, max_pu, limit_desc = _get_cea_limits_info(base_kv)

                va_pu = r.get('Va_pu', 1.0)
                vb_pu = r.get('Vb_pu', 1.0)
                vc_pu = r.get('Vc_pu', 1.0)
                vuf = r.get('VUF_pct', 0.0)

                v_min = min(va_pu, vb_pu, vc_pu)
                v_max = max(va_pu, vb_pu, vc_pu)

                if v_min < min_pu: st = "⚠️ UNDERVOLTAGE"
                elif v_max > max_pu: st = "⚠️ OVERVOLTAGE"
                elif vuf > 2.0: st = "⚠️ VUF > 2% VIOLATION"
                else: st = "✅ COMPLIANT"

                f.write(f"{bid:<6} {r.get('name', f'Bus_{bid}')[:17]:<18} {base_kv:<8.1f} "
                        f"{r.get('Va_kV', 0.0):<9.2f} {r.get('Vb_kV', 0.0):<9.2f} {r.get('Vc_kV', 0.0):<9.2f} "
                        f"{va_pu:<8.4f} {vb_pu:<8.4f} {vc_pu:<8.4f} {limit_desc:<28} {vuf:<8.3f} {st}\n")
            f.write("=" * 155 + "\n\n")

            # SECTION 4: THERMAL LOADING ANALYSIS
            f.write("SECTION 4: 3-PHASE TRANSMISSION LINE & ICT TRANSFORMER THERMAL LOADING ANALYSIS (CEA Section 3 & 4)\n")
            f.write("-" * 155 + "\n")
            f.write(f"{'Type':<5} {'ID':<5} {'Feeder/ICT Name':<20} {'From->To':<14} {'Pa(MW)':<9} {'Pb(MW)':<9} {'Pc(MW)':<9} "
                    f"{'Ptot(MW)':<10} {'Stot(MVA)':<10} {'In(A)':<8} {'Loss(kW)':<10} {'Load%':<7} {'Thermal Status'}\n")
            f.write("-" * 155 + "\n")
            for br in self.results_branches:
                fb = br['from_bus']
                tb = br['to_bus']
                is_xfmr = any(x.get('from_bus') == fb and x.get('to_bus') == tb for x in self.transformers.values())
                b_type_str = 'ICT' if is_xfmr else 'LINE'
                tag = f"{fb}->{tb}"
                bid = str(br.get('line_id', ''))
                bname = br.get('name', f"Ckt_{fb}_{tb}")
                ptot = br['P_from_a'] + br['P_from_b'] + br['P_from_c']
                qtot = br['Q_from_a'] + br['Q_from_b'] + br['Q_from_c']
                stot = math.sqrt(ptot**2 + qtot**2)
                ld = float(br.get('loading_pct', 0.0))
                st = "❌ OVERLOAD" if ld > 100.0 else ("⚠️ HIGH" if ld > 80.0 else "✅ NORMAL")

                f.write(f"{b_type_str:<5} {bid:<5} {bname[:19]:<20} {tag:<14} "
                        f"{br['P_from_a']:<9.2f} {br['P_from_b']:<9.2f} {br['P_from_c']:<9.2f} "
                        f"{ptot:<10.2f} {stot:<10.2f} {br['I_neutral_A']:<8.1f} {br['Ploss_tot'] * 1000.0:<10.1f} {ld:<7.1f} {st}\n")
            f.write("=" * 155 + "\n\n")

            # SECTION 6: OFFICIAL CEA GRID COMPLIANCE VERDICT
            f.write("SECTION 6: OFFICIAL CEA GRID COMPLIANCE VERDICT & 3-PHASE UNBALANCE AUDIT\n")
            f.write("=" * 145 + "\n")
            f.write(f"  • Maximum System VUF%   : {self.summary.get('max_VUF_pct', 0.0):.4f}% at Bus {self.summary.get('worst_bus_VUF')}\n")
            f.write(f"  • IEGC Permissible Limit: Maximum 2.0% Voltage Unbalance Factor across All Voltage Levels\n")
            f.write(f"  • Overall Verdict       : {'✅ FULLY COMPLIANT WITH CEA & IEGC CRITERIA' if self.summary.get('max_VUF_pct', 0.0) <= 2.0 else '⚠️ STATUTORY UNBALANCE VIOLATION DETECTED'}\n")
            f.write("=" * 145 + "\n")

        return filename

    # -------------------------------------------------------------------------
    # 4. ALL_DATA .csv Report
    # -------------------------------------------------------------------------
    def write_csv_all_data(self, filename: str) -> str:
        """
        Generates <case_name>_ALL_DATA.csv matching exact DevEN format:
        Columns 0-50 reserved for exact original inputs across all sections,
        and columns 51+ enriched with genuine 3-phase per-phase metrics.
        """
        OUTPUT_START_COL = 51

        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)

            # Header info comments
            writer.writerow(["# ====================================================================================="])
            writer.writerow(["# ⚡ 3-PHASE LOAD FLOW ANALYSIS — SYSTEM SUMMARY & ALL DATA REPORT"])
            writer.writerow(["# ====================================================================================="])
            writer.writerow([f"# Solver Engine           : DevEN 3-Phase Newton-Raphson (3P-NR)"])
            writer.writerow([f"# Convergence Status      : {'✅ CONVERGED' if self.engine_3p.converged else '❌ DIVERGED'} in {self.engine_3p.iterations} iterations"])
            writer.writerow([f"# Total Buses             : {self.n_buses}"])
            writer.writerow([f"# Total Generation        : {sum(self.tot_p_gen):.4f} MW , {sum(self.tot_q_gen):.4f} Mvar"])
            writer.writerow([f"# Total Demand            : {sum(self.tot_p_load):.4f} MW , {sum(self.tot_q_load):.4f} Mvar"])
            writer.writerow([f"# Total Losses            : {sum(self.tot_p_loss):.4f} MW (Phase A: {self.tot_p_loss[0]:.2f}, B: {self.tot_p_loss[1]:.2f}, C: {self.tot_p_loss[2]:.2f} MW)"])
            writer.writerow([f"# Max Voltage Unbalance   : {self.summary.get('max_VUF_pct', 0.0):.4f}% at Bus {self.summary.get('worst_bus_VUF')}"])
            writer.writerow([])

            # Column header reference
            writer.writerow(['# ============================================================================'])
            writer.writerow(['# COLUMN HEADERS REFERENCE (Columns 0-50 reserved for input)'])
            writer.writerow(['# ============================================================================'])
            writer.writerow(['# SECTION 1: BUS DATA (Output at columns 51+):'])
            writer.writerow(['#   51: O_V_final_pu, 52: O_V_final_kV, 53: O_angle_deg, 54: O_voltage_status, 55: O_angle_status,'])
            writer.writerow(['#   56: O_Va_pu, 57: O_Vb_pu, 58: O_Vc_pu, 59: O_Va_kV, 60: O_Vb_kV, 61: O_Vc_kV,'])
            writer.writerow(['#   62: O_anga_deg, 63: O_angb_deg, 64: O_angc_deg, 65: O_V0_pu, 66: O_V1_pu, 67: O_V2_pu,'])
            writer.writerow(['#   68: O_VUF_pct, 69: O_PVUR_pct, 70: O_unbalance_status'])
            writer.writerow(['#'])
            writer.writerow(['# SECTION 2: GENERATOR DATA (Output at columns 51+):'])
            writer.writerow(['#   51: O_P_out_MW, 52: O_Q_out_Mvar, 53: O_V_actual_pu, 54: O_V_actual_kV, 55: O_Q_status, 56: O_limit_flag, 57: O_status,'])
            writer.writerow(['#   58: O_Pa_MW, 59: O_Pb_MW, 60: O_Pc_MW, 61: O_Qa_Mvar, 62: O_Qb_Mvar, 63: O_Qc_Mvar, 64: O_Ptot_MW, 65: O_Qtot_Mvar'])
            writer.writerow(['#'])
            writer.writerow(['# SECTION 3: LOAD DATA (Output at columns 51+):'])
            writer.writerow(['#   51: O_P_supplied_MW, 52: O_Q_supplied_Mvar, 53: O_V_actual_pu, 54: O_V_actual_kV, 55: O_supply_status,'])
            writer.writerow(['#   56: O_Pa_MW, 57: O_Pb_MW, 58: O_Pc_MW, 59: O_Qa_Mvar, 60: O_Qb_Mvar, 61: O_Qc_Mvar, 62: O_Ptot_MW, 63: O_Qtot_Mvar'])
            writer.writerow(['#'])
            writer.writerow(['# SECTION 4 & 5: LINE & TRANSFORMER DATA (Output at columns 51+):'])
            writer.writerow(['#   51: O_P_fwd_MW, 52: O_Q_fwd_Mvar, 53: O_MVA_fwd_MVA, 54: O_P_rev_MW, 55: O_Q_rev_Mvar, 56: O_MVA_rev_MVA,'])
            writer.writerow(['#   57: O_losses_MW, 58: O_loss_per_km, 59: O_loading_pct, 60: O_status,'])
            writer.writerow(['#   61: O_Pa_fwd_MW, 62: O_Pb_fwd_MW, 63: O_Pc_fwd_MW, 64: O_Qa_fwd_Mvar, 65: O_Qb_fwd_Mvar, 66: O_Qc_fwd_Mvar,'])
            writer.writerow(['#   67: O_Pa_rev_MW, 68: O_Pb_rev_MW, 69: O_Pc_rev_MW, 70: O_Qa_rev_Mvar, 71: O_Qb_rev_Mvar, 72: O_Qc_rev_Mvar, 73: O_In_A, 74: O_loss_tot_MW'])
            writer.writerow(['# ============================================================================'])
            writer.writerow([])

            # -----------------------------------------------------------------
            # 1. BUS DATA
            # -----------------------------------------------------------------
            writer.writerow(['# ========== BUS DATA =========='])
            headers = [f'col_{i}' for i in range(OUTPUT_START_COL)]
            headers.extend([
                'O_V_final_pu', 'O_V_final_kV', 'O_angle_deg', 'O_voltage_status', 'O_angle_status',
                'O_Va_pu', 'O_Vb_pu', 'O_Vc_pu', 'O_Va_kV', 'O_Vb_kV', 'O_Vc_kV',
                'O_anga_deg', 'O_angb_deg', 'O_angc_deg', 'O_V0_pu', 'O_V1_pu', 'O_V2_pu',
                'O_VUF_pct', 'O_PVUR_pct', 'O_unbalance_status'
            ])
            writer.writerow(headers)

            for bid in self.bus_list:
                bus = self.buses.get(bid, {})
                r = self.results_buses.get(bid, {})
                row = [''] * len(headers)

                row[0] = bid
                row[1] = bus.get('name', f'Bus_{bid}')
                row[2] = bus.get('type', 1)
                row[3] = bus.get('base_kV', 132)
                row[4] = bus.get('area', 1)
                row[5] = bus.get('zone', 1)
                row[6] = bus.get('owner', 1)
                row[7] = bus.get('V_init', 1.0)
                row[8] = bus.get('angle_init', 0.0)
                row[9] = bus.get('shunt_G', 0)
                row[10] = bus.get('shunt_B', 0)

                # Positive sequence compatibility (51-55)
                row[OUTPUT_START_COL + 0] = f"{r.get('V1_pu', 1.0):.6f}"
                row[OUTPUT_START_COL + 1] = f"{r.get('V1_pu', 1.0) * float(bus.get('base_kV', 132)):.6f}"
                row[OUTPUT_START_COL + 2] = f"{r.get('ang_a_deg', 0.0):.6f}"
                row[OUTPUT_START_COL + 3] = "NORMAL" if 0.95 <= r.get('V1_pu', 1.0) <= 1.05 else ("LOW" if r.get('V1_pu', 1.0) < 0.95 else "HIGH")
                row[OUTPUT_START_COL + 4] = "NORMAL"

                # 3-Phase enriched columns (56-70)
                row[OUTPUT_START_COL + 5] = f"{r.get('Va_pu', 1.0):.6f}"
                row[OUTPUT_START_COL + 6] = f"{r.get('Vb_pu', 1.0):.6f}"
                row[OUTPUT_START_COL + 7] = f"{r.get('Vc_pu', 1.0):.6f}"
                row[OUTPUT_START_COL + 8] = f"{r.get('Va_kV', 0.0):.6f}"
                row[OUTPUT_START_COL + 9] = f"{r.get('Vb_kV', 0.0):.6f}"
                row[OUTPUT_START_COL + 10] = f"{r.get('Vc_kV', 0.0):.6f}"
                row[OUTPUT_START_COL + 11] = f"{r.get('ang_a_deg', 0.0):.4f}"
                row[OUTPUT_START_COL + 12] = f"{r.get('ang_b_deg', -120.0):.4f}"
                row[OUTPUT_START_COL + 13] = f"{r.get('ang_c_deg', 120.0):.4f}"
                row[OUTPUT_START_COL + 14] = f"{r.get('V0_pu', 0.0):.6f}"
                row[OUTPUT_START_COL + 15] = f"{r.get('V1_pu', 1.0):.6f}"
                row[OUTPUT_START_COL + 16] = f"{r.get('V2_pu', 0.0):.6f}"
                row[OUTPUT_START_COL + 17] = f"{r.get('VUF_pct', 0.0):.4f}"
                row[OUTPUT_START_COL + 18] = f"{r.get('PVUR_pct', 0.0):.4f}"
                row[OUTPUT_START_COL + 19] = r.get('status', 'NORMAL')

                writer.writerow(row)
            writer.writerow([])

            # -----------------------------------------------------------------
            # 2. GENERATOR DATA
            # -----------------------------------------------------------------
            writer.writerow(['# ========== GENERATOR DATA =========='])
            headers_g = [f'col_{i}' for i in range(OUTPUT_START_COL)]
            headers_g.extend([
                'O_P_out_MW', 'O_Q_out_Mvar', 'O_V_actual_pu', 'O_V_actual_kV', 'O_Q_status', 'O_limit_flag', 'O_status',
                'O_Pa_MW', 'O_Pb_MW', 'O_Pc_MW', 'O_Qa_Mvar', 'O_Qb_Mvar', 'O_Qc_Mvar', 'O_Ptot_MW', 'O_Qtot_Mvar'
            ])
            writer.writerow(headers_g)

            for gid, gen in sorted(self.generators.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
                gout = self.gen_outputs.get(gid, {'P_tot': 0.0, 'Pa': 0.0, 'Pb': 0.0, 'Pc': 0.0,
                                                   'Q_tot': 0.0, 'Qa': 0.0, 'Qb': 0.0, 'Qc': 0.0, 'status': 'OFFLINE'})
                bid = gen.get('bus', '')
                base_kv = float(self.buses.get(bid, {}).get('base_kV', 132.0))
                v_act = self.results_buses.get(bid, {}).get('V1_pu', 1.0)
                row = [''] * len(headers_g)

                row[0] = gid
                row[1] = gen.get('name', f'Gen_{gid}')
                row[2] = gen.get('type', 'SYNC')
                row[3] = bid
                row[4] = gen.get('P_out', 0)
                row[5] = gen.get('Q_out', 0)
                row[6] = gen.get('V_set', 1.0)
                row[7] = gen.get('Qmin', -999)
                row[8] = gen.get('Qmax', 999)
                row[9] = gen.get('status', 1)

                row[OUTPUT_START_COL + 0] = f"{gout['P_tot']:.5f}"
                row[OUTPUT_START_COL + 1] = f"{gout['Q_tot']:.5f}"
                row[OUTPUT_START_COL + 2] = f"{v_act:.5f}"
                row[OUTPUT_START_COL + 3] = f"{v_act * base_kv:.5f}"
                row[OUTPUT_START_COL + 4] = "NORMAL"
                row[OUTPUT_START_COL + 5] = "0"
                row[OUTPUT_START_COL + 6] = gout['status']

                row[OUTPUT_START_COL + 7] = f"{gout['Pa']:.5f}"
                row[OUTPUT_START_COL + 8] = f"{gout['Pb']:.5f}"
                row[OUTPUT_START_COL + 9] = f"{gout['Pc']:.5f}"
                row[OUTPUT_START_COL + 10] = f"{gout['Qa']:.5f}"
                row[OUTPUT_START_COL + 11] = f"{gout['Qb']:.5f}"
                row[OUTPUT_START_COL + 12] = f"{gout['Qc']:.5f}"
                row[OUTPUT_START_COL + 13] = f"{gout['P_tot']:.5f}"
                row[OUTPUT_START_COL + 14] = f"{gout['Q_tot']:.5f}"

                writer.writerow(row)
            writer.writerow([])

            # -----------------------------------------------------------------
            # 3. LOAD DATA
            # -----------------------------------------------------------------
            writer.writerow(['# ========== LOAD DATA =========='])
            headers_l = [f'col_{i}' for i in range(OUTPUT_START_COL)]
            headers_l.extend([
                'O_P_supplied_MW', 'O_Q_supplied_Mvar', 'O_V_actual_pu', 'O_V_actual_kV', 'O_supply_status',
                'O_Pa_MW', 'O_Pb_MW', 'O_Pc_MW', 'O_Qa_Mvar', 'O_Qb_Mvar', 'O_Qc_Mvar', 'O_Ptot_MW', 'O_Qtot_Mvar'
            ])
            writer.writerow(headers_l)

            for lid, ld in sorted(self.loads.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
                lout = self.load_outputs.get(lid, {'P_tot': 0.0, 'Pa': 0.0, 'Pb': 0.0, 'Pc': 0.0,
                                                    'Q_tot': 0.0, 'Qa': 0.0, 'Qb': 0.0, 'Qc': 0.0, 'V_avg': 1.0, 'status': 'NORMAL'})
                bid = ld.get('bus', '')
                base_kv = float(self.buses.get(bid, {}).get('base_kV', 132.0))
                row = [''] * len(headers_l)

                row[0] = lid
                row[1] = ld.get('name', f'Load_{lid}')
                row[2] = bid
                row[3] = ld.get('P_demand', 0)
                row[4] = ld.get('Q_demand', 0)
                row[5] = ld.get('area', 1)
                row[6] = ld.get('zone', 1)
                row[7] = ld.get('status', 1)

                row[OUTPUT_START_COL + 0] = f"{lout['P_tot']:.5f}"
                row[OUTPUT_START_COL + 1] = f"{lout['Q_tot']:.5f}"
                row[OUTPUT_START_COL + 2] = f"{lout['V_avg']:.5f}"
                row[OUTPUT_START_COL + 3] = f"{lout['V_avg'] * base_kv:.5f}"
                row[OUTPUT_START_COL + 4] = lout['status']

                row[OUTPUT_START_COL + 5] = f"{lout['Pa']:.5f}"
                row[OUTPUT_START_COL + 6] = f"{lout['Pb']:.5f}"
                row[OUTPUT_START_COL + 7] = f"{lout['Pc']:.5f}"
                row[OUTPUT_START_COL + 8] = f"{lout['Qa']:.5f}"
                row[OUTPUT_START_COL + 9] = f"{lout['Qb']:.5f}"
                row[OUTPUT_START_COL + 10] = f"{lout['Qc']:.5f}"
                row[OUTPUT_START_COL + 11] = f"{lout['P_tot']:.5f}"
                row[OUTPUT_START_COL + 12] = f"{lout['Q_tot']:.5f}"

                writer.writerow(row)
            writer.writerow([])

            # -----------------------------------------------------------------
            # 4. LINE DATA
            # -----------------------------------------------------------------
            writer.writerow(['# ========== LINE DATA =========='])
            headers_br = [f'col_{i}' for i in range(OUTPUT_START_COL)]
            headers_br.extend([
                'O_P_fwd_MW', 'O_Q_fwd_Mvar', 'O_MVA_fwd_MVA', 'O_P_rev_MW', 'O_Q_rev_Mvar', 'O_MVA_rev_MVA',
                'O_losses_MW', 'O_loss_per_km', 'O_loading_pct', 'O_status',
                'O_Pa_fwd_MW', 'O_Pb_fwd_MW', 'O_Pc_fwd_MW', 'O_Qa_fwd_Mvar', 'O_Qb_fwd_Mvar', 'O_Qc_fwd_Mvar',
                'O_Pa_rev_MW', 'O_Pb_rev_MW', 'O_Pc_rev_MW', 'O_Qa_rev_Mvar', 'O_Qb_rev_Mvar', 'O_Qc_rev_Mvar',
                'O_In_A', 'O_loss_tot_MW'
            ])
            writer.writerow(headers_br)

            branch_map = {}
            for br in self.results_branches:
                key = (br['from_bus'], br['to_bus'])
                branch_map[key] = br

            for lid, line in sorted(self.lines.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
                fb = line.get('from_bus')
                tb = line.get('to_bus')
                br = branch_map.get((fb, tb), {})
                row = [''] * len(headers_br)

                row[0] = lid
                row[1] = line.get('name', f'Line_{lid}')
                row[2] = fb
                row[3] = tb
                row[4] = line.get('circuit', '1')
                row[5] = line.get('r', 0.0)
                row[6] = line.get('x', 0.01)
                row[7] = line.get('b', 0.0)
                row[8] = line.get('rateA', 0)
                row[9] = line.get('status', 1)

                p_fwd = br.get('P_from_a', 0.0) + br.get('P_from_b', 0.0) + br.get('P_from_c', 0.0)
                q_fwd = br.get('Q_from_a', 0.0) + br.get('Q_from_b', 0.0) + br.get('Q_from_c', 0.0)
                p_rev = br.get('P_to_a', 0.0) + br.get('P_to_b', 0.0) + br.get('P_to_c', 0.0)
                q_rev = br.get('Q_to_a', 0.0) + br.get('Q_to_b', 0.0) + br.get('Q_to_c', 0.0)
                loss_tot = br.get('Ploss_tot', 0.0)

                row[OUTPUT_START_COL + 0] = f"{p_fwd:.5f}"
                row[OUTPUT_START_COL + 1] = f"{q_fwd:.5f}"
                row[OUTPUT_START_COL + 2] = f"{math.sqrt(p_fwd**2 + q_fwd**2):.5f}"
                row[OUTPUT_START_COL + 3] = f"{p_rev:.5f}"
                row[OUTPUT_START_COL + 4] = f"{q_rev:.5f}"
                row[OUTPUT_START_COL + 5] = f"{math.sqrt(p_rev**2 + q_rev**2):.5f}"
                row[OUTPUT_START_COL + 6] = f"{loss_tot:.5f}"
                row[OUTPUT_START_COL + 7] = "0.000000"
                row[OUTPUT_START_COL + 8] = f"{br.get('loading_pct', 0.0):.2f}"
                row[OUTPUT_START_COL + 9] = "NORMAL"

                row[OUTPUT_START_COL + 10] = f"{br.get('P_from_a', 0.0):.5f}"
                row[OUTPUT_START_COL + 11] = f"{br.get('P_from_b', 0.0):.5f}"
                row[OUTPUT_START_COL + 12] = f"{br.get('P_from_c', 0.0):.5f}"
                row[OUTPUT_START_COL + 13] = f"{br.get('Q_from_a', 0.0):.5f}"
                row[OUTPUT_START_COL + 14] = f"{br.get('Q_from_b', 0.0):.5f}"
                row[OUTPUT_START_COL + 15] = f"{br.get('Q_from_c', 0.0):.5f}"

                row[OUTPUT_START_COL + 16] = f"{br.get('P_to_a', 0.0):.5f}"
                row[OUTPUT_START_COL + 17] = f"{br.get('P_to_b', 0.0):.5f}"
                row[OUTPUT_START_COL + 18] = f"{br.get('P_to_c', 0.0):.5f}"
                row[OUTPUT_START_COL + 19] = f"{br.get('Q_to_a', 0.0):.5f}"
                row[OUTPUT_START_COL + 20] = f"{br.get('Q_to_b', 0.0):.5f}"
                row[OUTPUT_START_COL + 21] = f"{br.get('Q_to_c', 0.0):.5f}"

                row[OUTPUT_START_COL + 22] = f"{br.get('I_neutral_A', 0.0):.3f}"
                row[OUTPUT_START_COL + 23] = f"{loss_tot:.5f}"

                writer.writerow(row)
            writer.writerow([])

            # -----------------------------------------------------------------
            # 5. TRANSFORMER DATA
            # -----------------------------------------------------------------
            writer.writerow(['# ========== TRANSFORMER DATA =========='])
            writer.writerow(headers_br)

            for xid, xfmr in sorted(self.transformers.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
                fb = xfmr.get('from_bus')
                tb = xfmr.get('to_bus')
                br = branch_map.get((fb, tb), {})
                row = [''] * len(headers_br)

                row[0] = xid
                row[1] = xfmr.get('name', f'Xfmr_{xid}')
                row[2] = fb
                row[3] = tb
                row[4] = xfmr.get('circuit', '1')
                row[5] = xfmr.get('r', 0.0)
                row[6] = xfmr.get('x', 0.01)
                row[7] = xfmr.get('tap_ratio', 1.0)
                row[8] = xfmr.get('rateA', 0)
                row[9] = xfmr.get('status', 1)

                p_fwd = br.get('P_from_a', 0.0) + br.get('P_from_b', 0.0) + br.get('P_from_c', 0.0)
                q_fwd = br.get('Q_from_a', 0.0) + br.get('Q_from_b', 0.0) + br.get('Q_from_c', 0.0)
                p_rev = br.get('P_to_a', 0.0) + br.get('P_to_b', 0.0) + br.get('P_to_c', 0.0)
                q_rev = br.get('Q_to_a', 0.0) + br.get('Q_to_b', 0.0) + br.get('Q_to_c', 0.0)
                loss_tot = br.get('Ploss_tot', 0.0)

                row[OUTPUT_START_COL + 0] = f"{p_fwd:.5f}"
                row[OUTPUT_START_COL + 1] = f"{q_fwd:.5f}"
                row[OUTPUT_START_COL + 2] = f"{math.sqrt(p_fwd**2 + q_fwd**2):.5f}"
                row[OUTPUT_START_COL + 3] = f"{p_rev:.5f}"
                row[OUTPUT_START_COL + 4] = f"{q_rev:.5f}"
                row[OUTPUT_START_COL + 5] = f"{math.sqrt(p_rev**2 + q_rev**2):.5f}"
                row[OUTPUT_START_COL + 6] = f"{loss_tot:.5f}"
                row[OUTPUT_START_COL + 7] = "0.000000"
                row[OUTPUT_START_COL + 8] = f"{br.get('loading_pct', 0.0):.2f}"
                row[OUTPUT_START_COL + 9] = "NORMAL"

                row[OUTPUT_START_COL + 10] = f"{br.get('P_from_a', 0.0):.5f}"
                row[OUTPUT_START_COL + 11] = f"{br.get('P_from_b', 0.0):.5f}"
                row[OUTPUT_START_COL + 12] = f"{br.get('P_from_c', 0.0):.5f}"
                row[OUTPUT_START_COL + 13] = f"{br.get('Q_from_a', 0.0):.5f}"
                row[OUTPUT_START_COL + 14] = f"{br.get('Q_from_b', 0.0):.5f}"
                row[OUTPUT_START_COL + 15] = f"{br.get('Q_from_c', 0.0):.5f}"

                row[OUTPUT_START_COL + 16] = f"{br.get('P_to_a', 0.0):.5f}"
                row[OUTPUT_START_COL + 17] = f"{br.get('P_to_b', 0.0):.5f}"
                row[OUTPUT_START_COL + 18] = f"{br.get('P_to_c', 0.0):.5f}"
                row[OUTPUT_START_COL + 19] = f"{br.get('Q_to_a', 0.0):.5f}"
                row[OUTPUT_START_COL + 20] = f"{br.get('Q_to_b', 0.0):.5f}"
                row[OUTPUT_START_COL + 21] = f"{br.get('Q_to_c', 0.0):.5f}"

                row[OUTPUT_START_COL + 22] = f"{br.get('I_neutral_A', 0.0):.3f}"
                row[OUTPUT_START_COL + 23] = f"{loss_tot:.5f}"

                writer.writerow(row)
            writer.writerow([])

        return filename

    # -------------------------------------------------------------------------
    # 5. ALL_DATA .py Script
    # -------------------------------------------------------------------------
    def write_py_all_data(self, filename: str) -> str:
        """
        Generates <case_name>_ALL_DATA.py with standard DevEN case definitions,
        51+ column output lists, and comprehensive 3-phase structured dictionaries.
        """
        OUTPUT_START_COL = 51

        with open(filename, 'w', encoding='utf-8') as f:
            f.write('"""\n')
            f.write('============================================================================\n')
            f.write('DevEN 3-PHASE UNBALANCED POWER FLOW ANALYSIS - COMPLETE DATA & RESULTS\n')
            f.write(f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
            f.write('Output data starts at column 51 (0-50 reserved for input)\n')
            f.write('============================================================================\n')
            f.write('"""\n\n')

            f.write(f'BASE_MVA = {self.base_mva}\n')
            f.write(f'OUTPUT_START_COL = {OUTPUT_START_COL}\n\n')

            # 1. BUS_DATA
            f.write('# ========== BUS DATA ==========\n')
            f.write('# [0-10: input, 51-70: 3-phase output]\n')
            f.write('BUS_DATA = [\n')
            for bid in self.bus_list:
                bus = self.buses.get(bid, {})
                r = self.results_buses.get(bid, {})
                row = ['""'] * (OUTPUT_START_COL + 20)
                row[0] = str(bid)
                row[1] = f'"{bus.get("name", f"Bus_{bid}")}"'
                row[2] = str(bus.get("type", 1))
                row[3] = str(bus.get("base_kV", 132))
                row[4] = str(bus.get("area", 1))
                row[5] = str(bus.get("zone", 1))
                row[6] = str(bus.get("owner", 1))
                row[7] = str(bus.get("V_init", 1.0))
                row[8] = str(bus.get("angle_init", 0.0))
                row[9] = str(bus.get("shunt_G", 0))
                row[10] = str(bus.get("shunt_B", 0))

                row[OUTPUT_START_COL + 0] = f"{r.get('V1_pu', 1.0):.6f}"
                row[OUTPUT_START_COL + 1] = f"{r.get('V1_pu', 1.0) * float(bus.get('base_kV', 132)):.6f}"
                row[OUTPUT_START_COL + 2] = f"{r.get('ang_a_deg', 0.0):.6f}"
                row[OUTPUT_START_COL + 3] = '"NORMAL"'
                row[OUTPUT_START_COL + 4] = '"NORMAL"'

                row[OUTPUT_START_COL + 5] = f"{r.get('Va_pu', 1.0):.6f}"
                row[OUTPUT_START_COL + 6] = f"{r.get('Vb_pu', 1.0):.6f}"
                row[OUTPUT_START_COL + 7] = f"{r.get('Vc_pu', 1.0):.6f}"
                row[OUTPUT_START_COL + 8] = f"{r.get('Va_kV', 0.0):.6f}"
                row[OUTPUT_START_COL + 9] = f"{r.get('Vb_kV', 0.0):.6f}"
                row[OUTPUT_START_COL + 10] = f"{r.get('Vc_kV', 0.0):.6f}"
                row[OUTPUT_START_COL + 11] = f"{r.get('ang_a_deg', 0.0):.4f}"
                row[OUTPUT_START_COL + 12] = f"{r.get('ang_b_deg', -120.0):.4f}"
                row[OUTPUT_START_COL + 13] = f"{r.get('ang_c_deg', 120.0):.4f}"
                row[OUTPUT_START_COL + 14] = f"{r.get('V0_pu', 0.0):.6f}"
                row[OUTPUT_START_COL + 15] = f"{r.get('V1_pu', 1.0):.6f}"
                row[OUTPUT_START_COL + 16] = f"{r.get('V2_pu', 0.0):.6f}"
                row[OUTPUT_START_COL + 17] = f"{r.get('VUF_pct', 0.0):.4f}"
                row[OUTPUT_START_COL + 18] = f"{r.get('PVUR_pct', 0.0):.4f}"
                row[OUTPUT_START_COL + 19] = f'"{r.get("status", "NORMAL")}"'

                f.write('    [' + ', '.join(row) + '],\n')
            f.write(']\n\n')

            # 2. GENERATOR_DATA
            f.write('# ========== GENERATOR DATA ==========\n')
            f.write('GENERATOR_DATA = [\n')
            for gid, gen in sorted(self.generators.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
                gout = self.gen_outputs.get(gid, {'P_tot': 0.0, 'Pa': 0.0, 'Pb': 0.0, 'Pc': 0.0,
                                                   'Q_tot': 0.0, 'Qa': 0.0, 'Qb': 0.0, 'Qc': 0.0, 'status': 'OFFLINE'})
                row = ['""'] * (OUTPUT_START_COL + 15)
                row[0] = str(gid)
                row[1] = f'"{gen.get("name", f"Gen_{gid}")}"'
                row[2] = f'"{gen.get("type", "SYNC")}"'
                row[3] = str(gen.get("bus", ""))
                row[4] = str(gen.get("P_out", 0))
                row[5] = str(gen.get("Q_out", 0))
                row[6] = str(gen.get("V_set", 1.0))
                row[7] = str(gen.get("Qmin", -999))
                row[8] = str(gen.get("Qmax", 999))
                row[9] = str(gen.get("status", 1))

                row[OUTPUT_START_COL + 0] = f"{gout['P_tot']:.5f}"
                row[OUTPUT_START_COL + 1] = f"{gout['Q_tot']:.5f}"
                row[OUTPUT_START_COL + 2] = "1.00000"
                row[OUTPUT_START_COL + 3] = "132.00000"
                row[OUTPUT_START_COL + 4] = '"NORMAL"'
                row[OUTPUT_START_COL + 5] = '"0"'
                row[OUTPUT_START_COL + 6] = f'"{gout["status"]}"'

                row[OUTPUT_START_COL + 7] = f"{gout['Pa']:.5f}"
                row[OUTPUT_START_COL + 8] = f"{gout['Pb']:.5f}"
                row[OUTPUT_START_COL + 9] = f"{gout['Pc']:.5f}"
                row[OUTPUT_START_COL + 10] = f"{gout['Qa']:.5f}"
                row[OUTPUT_START_COL + 11] = f"{gout['Qb']:.5f}"
                row[OUTPUT_START_COL + 12] = f"{gout['Qc']:.5f}"
                row[OUTPUT_START_COL + 13] = f"{gout['P_tot']:.5f}"
                row[OUTPUT_START_COL + 14] = f"{gout['Q_tot']:.5f}"

                f.write('    [' + ', '.join(row) + '],\n')
            f.write(']\n\n')

            # 3. LOAD_DATA
            f.write('# ========== LOAD DATA ==========\n')
            f.write('LOAD_DATA = [\n')
            for lid, ld in sorted(self.loads.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
                lout = self.load_outputs.get(lid, {'P_tot': 0.0, 'Pa': 0.0, 'Pb': 0.0, 'Pc': 0.0,
                                                    'Q_tot': 0.0, 'Qa': 0.0, 'Qb': 0.0, 'Qc': 0.0, 'V_avg': 1.0, 'status': 'NORMAL'})
                row = ['""'] * (OUTPUT_START_COL + 13)
                row[0] = str(lid)
                row[1] = f'"{ld.get("name", f"Load_{lid}")}"'
                row[2] = str(ld.get("bus", ""))
                row[3] = str(ld.get("P_demand", 0))
                row[4] = str(ld.get("Q_demand", 0))
                row[5] = str(ld.get("area", 1))
                row[6] = str(ld.get("zone", 1))
                row[7] = str(ld.get("status", 1))

                row[OUTPUT_START_COL + 0] = f"{lout['P_tot']:.5f}"
                row[OUTPUT_START_COL + 1] = f"{lout['Q_tot']:.5f}"
                row[OUTPUT_START_COL + 2] = f"{lout['V_avg']:.5f}"
                row[OUTPUT_START_COL + 3] = "132.00000"
                row[OUTPUT_START_COL + 4] = f'"{lout["status"]}"'

                row[OUTPUT_START_COL + 5] = f"{lout['Pa']:.5f}"
                row[OUTPUT_START_COL + 6] = f"{lout['Pb']:.5f}"
                row[OUTPUT_START_COL + 7] = f"{lout['Pc']:.5f}"
                row[OUTPUT_START_COL + 8] = f"{lout['Qa']:.5f}"
                row[OUTPUT_START_COL + 9] = f"{lout['Qb']:.5f}"
                row[OUTPUT_START_COL + 10] = f"{lout['Qc']:.5f}"
                row[OUTPUT_START_COL + 11] = f"{lout['P_tot']:.5f}"
                row[OUTPUT_START_COL + 12] = f"{lout['Q_tot']:.5f}"

                f.write('    [' + ', '.join(row) + '],\n')
            f.write(']\n\n')

            # 4. STRUCTURED 3-PHASE DICTIONARIES
            f.write('# ============================================================================\n')
            f.write('# 3-PHASE RESULTS DICTIONARIES\n')
            f.write('# ============================================================================\n')
            f.write('SYSTEM_SUMMARY_3PHASE = {\n')
            f.write(f"    'converged': {self.engine_3p.converged},\n")
            f.write(f"    'iterations': {self.engine_3p.iterations},\n")
            f.write(f"    'max_VUF_pct': {self.summary.get('max_VUF_pct', 0.0):.4f},\n")
            f.write(f"    'worst_bus_VUF': {self.summary.get('worst_bus_VUF')},\n")
            f.write(f"    'total_losses_MW': {sum(self.tot_p_loss):.4f},\n")
            f.write(f"    'loss_phase_a_MW': {self.tot_p_loss[0]:.4f},\n")
            f.write(f"    'loss_phase_b_MW': {self.tot_p_loss[1]:.4f},\n")
            f.write(f"    'loss_phase_c_MW': {self.tot_p_loss[2]:.4f},\n")
            f.write(f"    'total_generation_MW': {sum(self.tot_p_gen):.4f},\n")
            f.write(f"    'total_demand_MW': {sum(self.tot_p_load):.4f},\n")
            f.write('}\n\n')

            f.write('BUS_RESULTS_3PHASE = {\n')
            for bid in self.bus_list:
                r = self.results_buses.get(bid, {})
                f.write(f"    {bid}: {{\n")
                f.write(f"        'Va_pu': {r.get('Va_pu', 1.0):.6f}, 'Vb_pu': {r.get('Vb_pu', 1.0):.6f}, 'Vc_pu': {r.get('Vc_pu', 1.0):.6f},\n")
                f.write(f"        'ang_a_deg': {r.get('ang_a_deg', 0.0):.4f}, 'ang_b_deg': {r.get('ang_b_deg', -120.0):.4f}, 'ang_c_deg': {r.get('ang_c_deg', 120.0):.4f},\n")
                f.write(f"        'V0_pu': {r.get('V0_pu', 0.0):.6f}, 'V1_pu': {r.get('V1_pu', 1.0):.6f}, 'V2_pu': {r.get('V2_pu', 0.0):.6f},\n")
                f.write(f"        'VUF_pct': {r.get('VUF_pct', 0.0):.4f}, 'PVUR_pct': {r.get('PVUR_pct', 0.0):.4f}, 'status': '{r.get('status', 'NORMAL')}'\n")
                f.write("    },\n")
            f.write('}\n\n')

            f.write('BRANCH_RESULTS_3PHASE = [\n')
            for br in self.results_branches:
                f.write(f"    {{\n")
                f.write(f"        'line_id': {br.get('line_id')}, 'from_bus': {br['from_bus']}, 'to_bus': {br['to_bus']},\n")
                f.write(f"        'Pa_fwd': {br['P_from_a']:.4f}, 'Pb_fwd': {br['P_from_b']:.4f}, 'Pc_fwd': {br['P_from_c']:.4f},\n")
                f.write(f"        'Qa_fwd': {br['Q_from_a']:.4f}, 'Qb_fwd': {br['Q_from_b']:.4f}, 'Qc_fwd': {br['Q_from_c']:.4f},\n")
                f.write(f"        'In_A': {br['I_neutral_A']:.2f}, 'loss_MW': {br['Ploss_tot']:.4f}, 'loading_pct': {br.get('loading_pct', 0.0):.2f}\n")
                f.write("    },\n")
            f.write(']\n')

        return filename

    # -------------------------------------------------------------------------
    # Master One-Call Report Generator
    # -------------------------------------------------------------------------
    def write_all_reports(
        self,
        output_folder: str,
        base_name: str,
        generate_txt: bool = True,
        generate_csv: bool = True,
        generate_py: bool = True,
        generate_ieee: bool = True,
        generate_cea: bool = True
    ) -> Dict[str, str]:
        """
        Generates standard DevEN reports directly into output_folder:
          1. <base_name>_ALL_DATA.csv (if generate_csv)
          2. <base_name>_ALL_DATA.py (if generate_py)
          3. <base_name>_SUMMARY.invout (if generate_txt)
          4. <base_name>_IEEE.IEEE (if generate_ieee)
          5. <base_name>_CEA.cea   (if generate_cea)
        Eliminates non-standard intermediate clutter files.
        """
        os.makedirs(output_folder, exist_ok=True)
        paths = {}

        # Remove any existing legacy companion files to keep folder clean
        stale_suffixes = [
            '_3PHASE_REPORT.txt',
            '_3PHASE_BUS_VOLTAGES.csv',
            '_3PHASE_BRANCH_FLOWS.csv',
            '_3PHASE_RESULTS.json'
        ]
        for sfx in stale_suffixes:
            stale_p = os.path.join(output_folder, f"{base_name}{sfx}")
            if os.path.isfile(stale_p):
                try:
                    os.remove(stale_p)
                except Exception:
                    pass

        # 1. Base files (Generated if requested)
        if generate_csv:
            csv_path = os.path.join(output_folder, f"{base_name}_ALL_DATA.csv")
            paths['ALL_DATA_csv'] = self.write_csv_all_data(csv_path)

        if generate_py:
            py_path = os.path.join(output_folder, f"{base_name}_ALL_DATA.py")
            paths['ALL_DATA_py'] = self.write_py_all_data(py_path)

        if generate_txt:
            txt_path = os.path.join(output_folder, f"{base_name}_SUMMARY.invout")
            paths['SUMMARY_invout'] = self.write_txt_summary(txt_path)

        # 2. Conditional Standards Reports
        if generate_ieee:
            ieee_path = os.path.join(output_folder, f"{base_name}_IEEE.IEEE")
            paths['IEEE'] = self.write_ieee_report(ieee_path)

        if generate_cea:
            cea_path = os.path.join(output_folder, f"{base_name}_CEA.cea")
            paths['CEA'] = self.write_cea_report(cea_path)

        return paths

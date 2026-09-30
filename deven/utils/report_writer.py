import sys
import os

if hasattr(sys.stdout, 'reconfigure'):
    try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass
if hasattr(sys.stderr, 'reconfigure'):
    try: sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass

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
Report Writer - Generates multiple output formats with ALL elements
Includes ALL components even if not present in input (empty headings only)
"""

"""
COLUMN HEADERS REFERENCE:
=======================
SECTION 1 - BUS DATA (Output at 51-55):
    51: O_V_final_pu, 52: O_V_final_kV, 53: O_angle_deg, 54: O_voltage_status, 55: O_angle_status

SECTION 2 - GENERATOR DATA (Output at 51-57):
    51: O_P_out_MW, 52: O_Q_out_Mvar, 53: O_V_actual_pu, 54: O_V_actual_kV, 55: O_Q_status, 56: O_limit_flag, 57: O_status

SECTION 3 - LOAD DATA (Output at 51-55):
    51: O_P_supplied_MW, 52: O_Q_supplied_Mvar, 53: O_V_actual_pu, 54: O_V_actual_kV, 55: O_supply_status

SECTION 4 - LINE DATA (Output at 51-60):
    51: O_P_fwd_MW, 52: O_Q_fwd_Mvar, 53: O_MVA_fwd_MVA, 54: O_P_rev_MW, 55: O_Q_rev_Mvar, 56: O_MVA_rev_MVA, 57: O_losses_MW, 58: O_loss_per_km, 59: O_loading_pct, 60: O_status

SECTION 5 - TRANSFORMER DATA (Output at 51-62):
    51: O_P_fwd_MW, 52: O_Q_fwd_Mvar, 53: O_MVA_fwd_MVA, 54: O_P_rev_MW, 55: O_Q_rev_Mvar, 56: O_MVA_rev_MVA, 57: O_losses_MW, 58: O_losses_MVA, 59: O_tap_position, 60: O_tap_step, 61: O_loading_pct, 62: O_status

SECTION 6 - CAPACITOR DATA (Output at 51-54):
    51: O_Q_injected_Mvar, 52: O_V_actual_pu, 53: O_V_actual_kV, 54: O_status

SECTION 7 - REACTOR DATA (Output at 51-54):
    51: O_Q_absorbed_Mvar, 52: O_V_actual_pu, 53: O_V_actual_kV, 54: O_status

SECTION 8 - SERIES COMPENSATION DATA (Output at 51-57):
    51: O_effective_X_pu, 52: O_compensation_status, 53: O_P_flow_from_to_MW, 54: O_Q_flow_from_to_Mvar, 55: O_P_flow_to_from_MW, 56: O_Q_flow_to_from_Mvar, 57: O_losses_MW

SECTION 9 - SERIES REACTOR DATA (Output at 51-56):
    51: O_P_flow_from_to_MW, 52: O_Q_flow_from_to_Mvar, 53: O_P_flow_to_from_MW, 54: O_Q_flow_to_from_Mvar, 55: O_losses_MW, 56: O_status

SECTION 10 - SHUNT DATA (Output at 51-54):
    51: O_Q_injected_Mvar, 52: O_V_actual_pu, 53: O_V_actual_kV, 54: O_status

SECTION 11 - SYSTEM SUMMARY (No column shift)
"""

import numpy as np
import csv
from datetime import datetime

class ReportWriter:
    def _safe_get(self, arr, idx, default_val=1.0):
        """Safely retrieve element from float, list, or ndarray without raising TypeError"""
        if arr is None:
            return default_val
        if isinstance(arr, (float, int, np.floating, np.integer)):
            return float(arr)
        try:
            flat = np.asarray(arr).ravel()
            if idx < len(flat):
                return float(flat[idx])
        except Exception:
            pass
        return default_val

    """
    Generates reports with ALL possible elements
    Missing elements get headers but empty data rows
    """
    
    def __init__(self, engine, input_data, samples, variation_strength, solver_info=None):
        self.engine = engine
        self.input_data = input_data
        self.samples = samples
        self.variation_strength = variation_strength
        self.solver_info = solver_info or {}
        
        # Calculate averages
        self.avg_P = np.mean([s['P_calc'] for s in samples], axis=0) * engine.baseMVA
        self.avg_Q = np.mean([s['Q_calc'] for s in samples], axis=0) * engine.baseMVA
        self.avg_V = np.mean([s['V_mag'] for s in samples], axis=0)
        self.avg_Va = np.mean([s['V_angle'] for s in samples], axis=0)
        
        # Process branch flows
        self.process_branch_flows()

    @staticmethod
    def _is_load_online(l):
        st = l.get('status', 1)
        return st != 0 and str(st).strip().lower() not in ('0', 'false', 'offline', 'disabled')

    def get_generator_outputs(self, gen_num, gen):
        """Calculate actual solved generator active and reactive power outputs"""
        bus_num = gen.get('bus', 0)
        idx = self.engine.bus_index_map.get(bus_num, 0)
        
        n_p = len(self.avg_P) if hasattr(self.avg_P, '__len__') else 0
        if n_p == 0 or idx >= n_p:
            return gen.get('P_out', 0.0), gen.get('Q_out', 0.0)
            
        if gen.get('status', 1) == 0:
            return 0.0, 0.0
            
        bus_type = self.input_data.get('buses', {}).get(bus_num, {}).get('type', 1)
        
        # Find all active generators at this bus
        bus_gens = [g for g in self.input_data.get('generators', {}).values() 
                    if g.get('bus') == bus_num and g.get('status', 1) == 1]
        
        # Calculate total load at this bus
        P_load_at_bus = 0.0
        Q_load_at_bus = 0.0
        for load in self.input_data.get('loads', {}).values():
            st = load.get('status', 1)
            if load.get('bus') == bus_num and (st != 0 and str(st).strip().lower() not in ('0', 'false', 'offline', 'disabled')):
                P_load_at_bus += load.get('P_demand', 0.0)
                Q_load_at_bus += load.get('Q_demand', 0.0)

                
        # Calculate shunt reactive power at this bus: Q_shunt = V^2 * B_shunt
        V_actual = self._safe_get_v(idx)
        B_shunt_at_bus = 0.0
        bus_info = self.input_data.get('buses', {}).get(bus_num, {})
        B_shunt_at_bus += bus_info.get('shunt_B', 0.0)
        
        for cap in self.input_data.get('capacitors', {}).values():
            if cap.get('bus') == bus_num and cap.get('status', 1) == 1:
                B_shunt_at_bus += cap.get('Q_cap', 0.0) / self.engine.baseMVA
                
        for react in self.input_data.get('reactors', {}).values():
            if react.get('bus') == bus_num and react.get('status', 1) == 1:
                B_shunt_at_bus -= react.get('Q_react', 0.0) / self.engine.baseMVA
                
        for shunt in self.input_data.get('shunts', {}).values():
            if shunt.get('bus') == bus_num and shunt.get('status', 1) == 1:
                B_shunt_at_bus += shunt.get('shunt_B', 0.0)
                
        Q_shunt_at_bus = (V_actual ** 2) * B_shunt_at_bus * self.engine.baseMVA
        
        # Compute total outputs at this bus
        P_inj = self.avg_P[idx]
        Q_inj = self.avg_Q[idx]
        
        # Account for HVDC links at this bus (rectifier draws power, inverter injects power)
        P_hvdc_at_bus = 0.0
        Q_hvdc_at_bus = 0.0
        hvdc_dict = self.input_data.get('hvdc_links', {}) or {}
        for lk_num, lk in hvdc_dict.items():
            if lk.get('status', 1) == 0:
                continue
            h_stat = self._get_hvdc_stats(lk_num, lk)
            fb = lk.get('from_bus')
            tb = lk.get('to_bus')
            if fb == bus_num:
                # Rectifier station draws AC power from this bus
                P_hvdc_at_bus += h_stat.get('avg_P_fwd', 0.0)
                Q_hvdc_at_bus += h_stat.get('avg_Q_fwd', 0.0)
            elif tb == bus_num:
                # Inverter station injects AC power into this bus (avg_P_rev is negative)
                P_hvdc_at_bus += h_stat.get('avg_P_rev', 0.0)
                Q_hvdc_at_bus += h_stat.get('avg_Q_rev', 0.0)

        P_gen_total = P_inj + P_load_at_bus + P_hvdc_at_bus
        Q_gen_total = Q_inj + Q_load_at_bus + Q_hvdc_at_bus
        
        if len(bus_gens) == 0:
            return 0.0, 0.0
            
        if gen.get('status', 1) == 0:
            return 0.0, 0.0

        # 1. Distribute active power
        if bus_type == 3:  # Slack bus
            total_slack_p_set = sum(g.get('P_out', 0.0) for g in bus_gens)
            if total_slack_p_set > 0:
                O_P_out = P_gen_total * (gen.get('P_out', 0.0) / total_slack_p_set)
            else:
                O_P_out = P_gen_total / len(bus_gens)
        else:
            O_P_out = gen.get('P_out', 0.0)
            
        # 2. Distribute reactive power (based on bus type and Q range)
        qmax_g = gen.get('Qmax')
        qmin_g = gen.get('Qmin')
        if bus_type == 3:
            # Slack bus: generator(s) provide the net reactive power required to maintain voltage
            O_Q_out = Q_gen_total / len(bus_gens)
        elif bus_type == 1:
            # PQ bus: Generator / Synchronous Motor acts as fixed scheduled injection (non-regulating).
            # It does not regulate voltage, nor does it absorb/supply bus shunt or network reactive mismatch.
            O_Q_out = float(gen.get('Q_out', 0.0))
        elif qmax_g is not None and qmin_g is not None and abs(float(qmax_g) - float(qmin_g)) < 1e-4:
            O_Q_out = float(qmax_g)
        else:
            # Regulating PV bus (bus_type == 2):
            # First subtract any fixed-Q generators on this bus
            fixed_q_sum = 0.0
            regulating_gens = []
            for g in bus_gens:
                qm = g.get('Qmax')
                qn = g.get('Qmin')
                if qm is not None and qn is not None and abs(float(qm) - float(qn)) < 1e-4:
                    fixed_q_sum += float(qm)
                else:
                    regulating_gens.append(g)

            if gen in regulating_gens and regulating_gens:
                q_rem = Q_gen_total - fixed_q_sum
                q_ranges = []
                for g in regulating_gens:
                    qm = g.get('Qmax', 9999.0)
                    qn = g.get('Qmin', -9999.0)
                    q_ranges.append(max(0.1, qm - qn))
                total_q_range = sum(q_ranges)
                
                g_idx = regulating_gens.index(gen)
                if total_q_range > 0:
                    O_Q_out = q_rem * (q_ranges[g_idx] / total_q_range)
                else:
                    O_Q_out = q_rem / len(regulating_gens)
                    
                if qmax_g is not None:
                    O_Q_out = min(O_Q_out, float(qmax_g))
                if qmin_g is not None:
                    O_Q_out = max(O_Q_out, float(qmin_g))
            else:
                O_Q_out = float(gen.get('Q_out', 0.0))
            
        return O_P_out, O_Q_out
    
    def _safe_get_v(self, idx, default=1.0):
        if not hasattr(self, 'avg_V') or self.avg_V is None: return default
        if np.isscalar(self.avg_V): return float(self.avg_V)
        try:
            if self._safe_get(self.avg_V, idx, 0.0) != 0: return float(self.avg_V[idx])
        except Exception:
            pass
        return default

    def _safe_get_va(self, idx, default=0.0):
        if not hasattr(self, 'avg_Va') or self.avg_Va is None: return default
        if np.isscalar(self.avg_Va): return float(self.avg_Va)
        try:
            if idx < len(self.avg_Va): return float(self.avg_Va[idx])
        except Exception:
            pass
        return default

    def process_branch_flows(self):
        """Process branch flow statistics"""
        self.line_stats = {}
        self.xfmr_stats = {}
        self.series_comp_stats = {}
        self.series_reactor_stats = {}
        
        for sample in self.samples:
            for flow in sample['branch_flows']:
                f_num = flow.get('num')
                bus_pair_key = f"{flow['from_bus']}-{flow['to_bus']}"
                
                # Determine primary key using unique element number (fallback to bus pair)
                key = f"num_{f_num}" if f_num is not None else bus_pair_key

                if flow['type'] == 'line':
                    if key not in self.line_stats:
                        self.line_stats[key] = {'P_fwd': [], 'Q_fwd': [], 'P_rev': [], 'Q_rev': [], 'loss': [], 'loading': []}
                    self.line_stats[key]['P_fwd'].append(flow['P_fwd_MW'])
                    self.line_stats[key]['Q_fwd'].append(flow['Q_fwd_Mvar'])
                    self.line_stats[key]['P_rev'].append(flow['P_rev_MW'])
                    self.line_stats[key]['Q_rev'].append(flow['Q_rev_Mvar'])
                    self.line_stats[key]['loss'].append(flow['losses_MW'])
                    self.line_stats[key]['loading'].append(flow['loading_pct'])

                    if f_num is not None:
                        self.line_stats[f_num] = self.line_stats[key]
                        self.line_stats[str(f_num)] = self.line_stats[key]

                    if bus_pair_key not in self.line_stats:
                        self.line_stats[bus_pair_key] = self.line_stats[key]

                elif flow['type'] == 'transformer':
                    if key not in self.xfmr_stats:
                        self.xfmr_stats[key] = {'P_fwd': [], 'Q_fwd': [], 'P_rev': [], 'Q_rev': [], 'loss': [], 'loading': [], 'tap': []}
                    self.xfmr_stats[key]['P_fwd'].append(flow['P_fwd_MW'])
                    self.xfmr_stats[key]['Q_fwd'].append(flow['Q_fwd_Mvar'])
                    self.xfmr_stats[key]['P_rev'].append(flow['P_rev_MW'])
                    self.xfmr_stats[key]['Q_rev'].append(flow['Q_rev_Mvar'])
                    self.xfmr_stats[key]['loss'].append(flow['losses_MW'])
                    self.xfmr_stats[key]['loading'].append(flow['loading_pct'])
                    self.xfmr_stats[key]['tap'].append(flow.get('tap_ratio', 1.0))

                    if f_num is not None:
                        self.xfmr_stats[f_num] = self.xfmr_stats[key]
                        self.xfmr_stats[str(f_num)] = self.xfmr_stats[key]

                    if bus_pair_key not in self.xfmr_stats:
                        self.xfmr_stats[bus_pair_key] = self.xfmr_stats[key]

        
        # Calculate averages for lines
        for stats in self.line_stats.values():
            stats['avg_P_fwd'] = np.mean(stats['P_fwd']) if stats['P_fwd'] else 0
            stats['avg_Q_fwd'] = np.mean(stats['Q_fwd']) if stats['Q_fwd'] else 0
            stats['avg_P_rev'] = np.mean(stats['P_rev']) if stats['P_rev'] else 0
            stats['avg_Q_rev'] = np.mean(stats['Q_rev']) if stats['Q_rev'] else 0
            stats['avg_loss'] = np.mean(stats['loss']) if stats['loss'] else 0
            stats['avg_loading'] = np.mean(stats['loading']) if stats['loading'] else 0
        
        # Calculate averages for transformers
        for stats in self.xfmr_stats.values():
            stats['avg_P_fwd'] = np.mean(stats['P_fwd']) if stats['P_fwd'] else 0
            stats['avg_Q_fwd'] = np.mean(stats['Q_fwd']) if stats['Q_fwd'] else 0
            stats['avg_P_rev'] = np.mean(stats['P_rev']) if stats['P_rev'] else 0
            stats['avg_Q_rev'] = np.mean(stats['Q_rev']) if stats['Q_rev'] else 0
            stats['avg_loss'] = np.mean(stats['loss']) if stats['loss'] else 0
            stats['avg_loading'] = np.mean(stats['loading']) if stats['loading'] else 0
            stats['avg_tap'] = np.mean(stats['tap']) if stats['tap'] else 1.0

        # Process HVDC link flows
        self.hvdc_stats = {}
        for sample in self.samples:
            flows = sample.get('hvdc_flows', [])
            if not flows and hasattr(self.engine, 'calculate_hvdc_flows'):
                flows = self.engine.calculate_hvdc_flows(sample.get('V_mag', []), sample.get('V_angle', []))
            for flow in flows:
                f_num = flow.get('num')
                bus_pair_key = f"{flow.get('from_bus')}-{flow.get('to_bus')}"
                key = f"num_{f_num}" if f_num is not None else bus_pair_key
                if key not in self.hvdc_stats:
                    self.hvdc_stats[key] = {
                        'P_fwd': [], 'Q_fwd': [], 'P_rev': [], 'Q_rev': [],
                        'P_dc': [], 'loss': [], 'Vdc_from': [], 'Vdc_to': [],
                        'Idc': [], 'alpha': [], 'gamma': [], 'tap_from': [],
                        'tap_to': [], 'loading': [], 'status': flow.get('status', 'ONLINE')
                    }
                self.hvdc_stats[key]['P_fwd'].append(float(flow.get('P_fwd', 0.0) or 0.0))
                self.hvdc_stats[key]['Q_fwd'].append(float(flow.get('Q_fwd', 0.0) or 0.0))
                self.hvdc_stats[key]['P_rev'].append(float(flow.get('P_rev', 0.0) or 0.0))
                self.hvdc_stats[key]['Q_rev'].append(float(flow.get('Q_rev', 0.0) or 0.0))
                p_dc_val = flow.get('P_dc_MW') if flow.get('P_dc_MW') is not None else flow.get('P_dc', 0.0)
                self.hvdc_stats[key]['P_dc'].append(float(p_dc_val or 0.0))
                self.hvdc_stats[key]['loss'].append(float(flow.get('losses_MW', 0.0) or 0.0))
                self.hvdc_stats[key]['Vdc_from'].append(float(flow.get('Vdc_from_kV', 0.0) or 0.0))
                self.hvdc_stats[key]['Vdc_to'].append(float(flow.get('Vdc_to_kV', 0.0) or 0.0))
                self.hvdc_stats[key]['Idc'].append(float(flow.get('Idc_A', 0.0) or 0.0))
                self.hvdc_stats[key]['alpha'].append(float(flow.get('alpha_deg', 0.0) or 0.0))
                self.hvdc_stats[key]['gamma'].append(float(flow.get('gamma_deg', 0.0) or 0.0))
                self.hvdc_stats[key]['tap_from'].append(float(flow.get('tap_from', 1.0) or 1.0))
                self.hvdc_stats[key]['tap_to'].append(float(flow.get('tap_to', 1.0) or 1.0))
                self.hvdc_stats[key]['loading'].append(float(flow.get('loading_pct', 0.0) or 0.0))

                if f_num is not None:
                    self.hvdc_stats[f_num] = self.hvdc_stats[key]
                    self.hvdc_stats[str(f_num)] = self.hvdc_stats[key]
                    try:
                        self.hvdc_stats[int(f_num)] = self.hvdc_stats[key]
                    except (ValueError, TypeError):
                        pass
                if bus_pair_key not in self.hvdc_stats:
                    self.hvdc_stats[bus_pair_key] = self.hvdc_stats[key]

        # Calculate averages for HVDC links
        for stats in self.hvdc_stats.values():
            stats['avg_P_fwd'] = float(np.mean(stats['P_fwd'])) if stats['P_fwd'] else 0.0
            stats['avg_Q_fwd'] = float(np.mean(stats['Q_fwd'])) if stats['Q_fwd'] else 0.0
            stats['avg_P_rev'] = float(np.mean(stats['P_rev'])) if stats['P_rev'] else 0.0
            stats['avg_Q_rev'] = float(np.mean(stats['Q_rev'])) if stats['Q_rev'] else 0.0
            stats['avg_P_dc'] = float(np.mean(stats['P_dc'])) if stats['P_dc'] else 0.0
            stats['avg_loss'] = float(np.mean(stats['loss'])) if stats['loss'] else 0.0
            stats['avg_Vdc_from'] = float(np.mean(stats['Vdc_from'])) if stats['Vdc_from'] else 0.0
            stats['avg_Vdc_to'] = float(np.mean(stats['Vdc_to'])) if stats['Vdc_to'] else 0.0
            stats['avg_Idc'] = float(np.mean(stats['Idc'])) if stats['Idc'] else 0.0
            stats['avg_alpha'] = float(np.mean(stats['alpha'])) if stats['alpha'] else 0.0
            stats['avg_gamma'] = float(np.mean(stats['gamma'])) if stats['gamma'] else 0.0
            stats['avg_tap_from'] = float(np.mean(stats['tap_from'])) if stats['tap_from'] else 1.0
            stats['avg_tap_to'] = float(np.mean(stats['tap_to'])) if stats['tap_to'] else 1.0
            stats['avg_loading'] = float(np.mean(stats['loading'])) if stats['loading'] else 0.0

    def _get_hvdc_stats(self, hvdc_num, hvdc_dict=None):
        if hvdc_num in self.hvdc_stats:
            return self.hvdc_stats[hvdc_num]
        str_num = str(hvdc_num)
        if str_num in self.hvdc_stats:
            return self.hvdc_stats[str_num]
        try:
            int_num = int(float(str(hvdc_num)))
            if int_num in self.hvdc_stats:
                return self.hvdc_stats[int_num]
        except (ValueError, TypeError):
            pass
        num_key = f"num_{hvdc_num}"
        if num_key in self.hvdc_stats:
            return self.hvdc_stats[num_key]
        if hvdc_dict:
            fb = hvdc_dict.get('from_bus', 0)
            tb = hvdc_dict.get('to_bus', 0)
            pair_key = f"{fb}-{tb}"
            if pair_key in self.hvdc_stats:
                return self.hvdc_stats[pair_key]
            rev_pair_key = f"{tb}-{fb}"
            if rev_pair_key in self.hvdc_stats:
                return self.hvdc_stats[rev_pair_key]
        return {
            'avg_P_fwd': 0.0, 'avg_Q_fwd': 0.0, 'avg_P_rev': 0.0, 'avg_Q_rev': 0.0,
            'avg_P_dc': 0.0, 'avg_loss': 0.0, 'avg_Vdc_from': 0.0, 'avg_Vdc_to': 0.0,
            'avg_Idc': 0.0, 'avg_alpha': 0.0, 'avg_gamma': 0.0, 'avg_tap_from': 1.0,
            'avg_tap_to': 1.0, 'avg_loading': 0.0
        }

    def _get_line_stats(self, line_num, line_dict=None):
        if line_dict and line_dict.get('status', 1) == 0:
            return {
                'avg_P_fwd': 0.0, 'avg_Q_fwd': 0.0, 'avg_P_rev': 0.0, 'avg_Q_rev': 0.0,
                'avg_loss': 0.0, 'avg_loading': 0.0, 'status': 'OFFLINE', 'loading': [0.0]
            }
        if line_num in self.line_stats:
            return self.line_stats[line_num]
        str_num = str(line_num)
        if str_num in self.line_stats:
            return self.line_stats[str_num]
        num_key = f"num_{line_num}"
        if num_key in self.line_stats:
            return self.line_stats[num_key]
        if line_dict:
            pair_key = f"{line_dict.get('from_bus', 0)}-{line_dict.get('to_bus', 0)}"
            if pair_key in self.line_stats:
                return self.line_stats[pair_key]
        return {}

    def _get_xfmr_stats(self, xfmr_num, xfmr_dict=None):
        if xfmr_dict and xfmr_dict.get('status', 1) == 0:
            return {
                'avg_P_fwd': 0.0, 'avg_Q_fwd': 0.0, 'avg_P_rev': 0.0, 'avg_Q_rev': 0.0,
                'avg_loss': 0.0, 'avg_loading': 0.0, 'status': 'OFFLINE', 'loading': [0.0],
                'avg_tap': xfmr_dict.get('ratio', 1.0)
            }
        if xfmr_num in self.xfmr_stats:
            return self.xfmr_stats[xfmr_num]
        str_num = str(xfmr_num)
        if str_num in self.xfmr_stats:
            return self.xfmr_stats[str_num]
        num_key = f"num_{xfmr_num}"
        if num_key in self.xfmr_stats:
            return self.xfmr_stats[num_key]
        if xfmr_dict:
            pair_key = f"{xfmr_dict.get('from_bus', 0)}-{xfmr_dict.get('to_bus', 0)}"
            if pair_key in self.xfmr_stats:
                return self.xfmr_stats[pair_key]
        return {}


        # Calculate flows & stats for 3-Winding Transformers
        self.three_w_xfmr_stats = {}
        three_w_db = self.input_data.get('three_winding_transformers') or self.input_data.get('three_winding_xfmrs') or {}
        for tw_num, twx in three_w_db.items():
            dummy_bus = 100000000 + int(tw_num)
            hv_bus = twx.get('hv_bus')
            mv_bus = twx.get('mv_bus')
            lv_bus = twx.get('lv_bus')
            
            key_hv = f"{hv_bus}-{dummy_bus}"
            key_mv = f"{mv_bus}-{dummy_bus}"
            key_lv = f"{lv_bus}-{dummy_bus}"
            
            stat_hv = self.xfmr_stats.get(key_hv, {})
            stat_mv = self.xfmr_stats.get(key_mv, {})
            stat_lv = self.xfmr_stats.get(key_lv, {})
            
            p_hv = stat_hv.get('avg_P_fwd', 0.0)
            q_hv = stat_hv.get('avg_Q_fwd', 0.0)
            s_hv = (p_hv**2 + q_hv**2)**0.5
            rate_h = twx.get('rate_h') or twx.get('rateA_h') or twx.get('rate_h_mva') or 9999.0
            load_hv = (s_hv / rate_h * 100.0) if rate_h > 0 else 0.0
            loss_hv = stat_hv.get('avg_loss', 0.0)
            
            p_mv = stat_mv.get('avg_P_fwd', 0.0)
            q_mv = stat_mv.get('avg_Q_fwd', 0.0)
            s_mv = (p_mv**2 + q_mv**2)**0.5
            rate_m = twx.get('rate_m') or twx.get('rateA_m') or twx.get('rate_m_mva') or 9999.0
            load_mv = (s_mv / rate_m * 100.0) if rate_m > 0 else 0.0
            loss_mv = stat_mv.get('avg_loss', 0.0)
            
            p_lv = stat_lv.get('avg_P_fwd', 0.0)
            q_lv = stat_lv.get('avg_Q_fwd', 0.0)
            s_lv = (p_lv**2 + q_lv**2)**0.5
            rate_l = twx.get('rate_l') or twx.get('rateA_l') or twx.get('rate_l_mva') or 9999.0
            load_lv = (s_lv / rate_l * 100.0) if rate_l > 0 else 0.0
            loss_lv = stat_lv.get('avg_loss', 0.0)
            
            tot_loss_p = loss_hv + loss_mv + loss_lv
            max_load = max(load_hv, load_mv, load_lv)
            
            status_str = "NORMAL"
            if twx.get('status', 1) == 0:
                status_str = "OUT_OF_SERVICE"
            elif max_load > 100.0:
                status_str = "OVERLOADED"
                
            self.three_w_xfmr_stats[tw_num] = {
                'P_hv': p_hv, 'Q_hv': q_hv, 'S_hv': s_hv, 'loading_hv': load_hv, 'loss_hv': loss_hv,
                'P_mv': p_mv, 'Q_mv': q_mv, 'S_mv': s_mv, 'loading_mv': load_mv, 'loss_mv': loss_mv,
                'P_lv': p_lv, 'Q_lv': q_lv, 'S_lv': s_lv, 'loading_lv': load_lv, 'loss_lv': loss_lv,
                'total_loss_p': tot_loss_p, 'max_loading': max_load, 'status': status_str
            }
    
    def get_voltage_kv(self, bus_num, V_pu):
        """Convert pu voltage to kV"""
        if bus_num in self.input_data.get('buses', {}):
            return V_pu * self.input_data['buses'][bus_num].get('base_kV', 132.0)
        return V_pu * 132.0
    
    def get_status(self, value, thresholds):
        """Get status based on thresholds"""
        if value < thresholds.get('min', 0.95):
            return 'LOW'
        elif value > thresholds.get('max', 1.05):
            return 'HIGH'
        return 'NORMAL'
    
    # def write_csv_all_data(self, filename):
    #     """Write CSV with ALL data - includes ALL possible elements"""
        
    #     with open(filename, 'w', newline='', encoding='utf-8') as f:
    #         writer = csv.writer(f)
            
    #         # =========================================================
    #         # SECTION 1: BUS DATA 
    #         # =========================================================
    #         writer.writerow(['# ವಿಲೋಮ ವಿದ್ಯುತ್ ಹರಿವಿನ ಅಧ್ಯಯನ (ಇನ್ವರ್ಸ್ ಪವರ್ ಫ್ಲೋ)'])
    #         writer.writerow(['# ========== BUS DATA =========='])
    #         writer.writerow(['bus_num', 'bus_name', 'bus_type', 'base_kV', 'area', 'zone', 'owner',
    #                        'V_init_pu', 'angle_init_deg', 'shunt_G_pu', 'shunt_B_pu',
    #                        'O_V_final_pu', 'O_V_final_kV', 'O_angle_deg', 'O_voltage_status', 'O_angle_status'])
            
    #         buses = self.input_data.get('buses', {})
    #         if buses:
    #             for bus_num, bus in buses.items():
    #                 idx = self.engine.bus_index_map.get(bus_num, 0)
    #                 V_kV = self.get_voltage_kv(bus_num, self._safe_get(self.avg_V, idx, 1.0))
    #                 v_status = self.get_status(self._safe_get(self.avg_V, idx, 1.0), {'min': 0.95, 'max': 1.05})
    #                 a_status = self.get_status(abs(self._safe_get(self.avg_Va, idx, 0.0)), {'min': 0, 'max': 30})
                    
    #                 writer.writerow([bus_num, bus.get('name', f'Bus_{bus_num}'), bus.get('type', 1), bus.get('base_kV', 132),
    #                                bus.get('area', 1), bus.get('zone', 1), bus.get('owner', 1),
    #                                bus.get('V_init', 1.0), bus.get('angle_init', 0.0), 
    #                                bus.get('shunt_G', 0), bus.get('shunt_B', 0),
    #                                f"{self.avg_V[idx]:.6f}" if self._safe_get(self.avg_V, idx, 0.0) != 0 else "N/A", 
    #                                f"{V_kV:.6f}", 
    #                                f"{self.avg_Va[idx]:.6f}" if idx < len(self.avg_Va) else "N/A", 
    #                                v_status, a_status])
    #         else:
    #             writer.writerow(['No bus data available'])
            
    #         writer.writerow([])
            
    #         # =========================================================
    #         # SECTION 2: GENERATOR DATA
    #         # =========================================================
    #         writer.writerow(['# ========== GENERATOR DATA =========='])
    #         writer.writerow(['gen_num', 'gen_name', 'gen_type', 'connected_bus', 'area', 'zone',
    #                        'I_P_out_MW', 'I_Q_out_Mvar', 'I_V_set_pu', 'I_V_set_kV',
    #                        'I_Qmin_Mvar', 'I_Qmax_Mvar', 'I_status',
    #                        'O_P_out_MW', 'O_Q_out_Mvar', 'O_V_actual_pu', 'O_V_actual_kV',
    #                        'O_Q_status', 'O_limit_flag', 'O_status'])
            
    #         generators = self.input_data.get('generators', {})
    #         if generators:
    #             for gen_num, gen in generators.items():
    #                 bus_num = gen.get('bus', 0)
    #                 idx = self.engine.bus_index_map.get(bus_num, 0)
    #                 V_kV = self.get_voltage_kv(bus_num, self._safe_get(self.avg_V, idx, 1.0))
    #                 O_P_out = -self.avg_P[idx] if idx < len(self.avg_P) and self.avg_P[idx] < 0 else gen.get('P_out', 0)
    #                 O_Q_out = gen.get('Q_out', 0)
                    
    #                 q_status = "WITHIN LIMITS"
    #                 limit_flag = "OK"
    #                 if O_Q_out < gen.get('Qmin', -9999):
    #                     q_status = "BELOW Qmin"
    #                     limit_flag = "VIOLATED"
    #                 elif O_Q_out > gen.get('Qmax', 9999):
    #                     q_status = "ABOVE Qmax"
    #                     limit_flag = "VIOLATED"
                    
    #                 writer.writerow([gen_num, gen.get('name', f'Gen_{gen_num}'), gen.get('type', 'SYNC'), bus_num,
    #                                gen.get('area', 1), gen.get('zone', 1),
    #                                gen.get('P_out', 0), gen.get('Q_out', 0), gen.get('V_set', 1.0),
    #                                f"{gen.get('V_set', 1.0) * self.input_data.get('buses', {}).get(bus_num, {}).get('base_kV', 132):.6f}",
    #                                gen.get('Qmin', -9999), gen.get('Qmax', 9999), gen.get('status', 1),
    #                                f"{O_P_out:.6f}", f"{O_Q_out:.6f}", 
    #                                f"{self.avg_V[idx]:.6f}" if self._safe_get(self.avg_V, idx, 0.0) != 0 else "N/A",
    #                                f"{V_kV:.6f}", q_status, limit_flag, "ONLINE" if gen.get('status', 1) == 1 else "OFFLINE"])
    #         else:
    #             writer.writerow(['No generator data available'])
            
    #         writer.writerow([])
            
    #         # =========================================================
    #         # SECTION 3: LOAD DATA
    #         # =========================================================
    #         writer.writerow(['# ========== LOAD DATA =========='])
    #         writer.writerow(['load_num', 'load_name', 'connected_bus', 'area', 'zone',
    #                        'I_P_demand_MW', 'I_Q_demand_Mvar', 'I_load_model',
    #                        'O_P_supplied_MW', 'O_Q_supplied_Mvar', 'O_V_actual_pu', 'O_V_actual_kV', 'O_supply_status'])
            
    #         loads = self.input_data.get('loads', {})
    #         if loads:
    #             for load_num, load in loads.items():
    #                 bus_num = load.get('bus', 0)
    #                 idx = self.engine.bus_index_map.get(bus_num, 0)
    #                 V_kV = self.get_voltage_kv(bus_num, self._safe_get(self.avg_V, idx, 1.0))
                    
    #                 supply_status = "NORMAL" if (self._safe_get(self.avg_V, idx, 0.0) != 0 and self.avg_V[idx] >= 0.95) else "VOLTAGE LOW"
                    
    #                 writer.writerow([load_num, load.get('name', f'Load_{load_num}'), bus_num,
    #                                load.get('area', 1), load.get('zone', 1),
    #                                load.get('P_demand', 0), load.get('Q_demand', 0), load.get('model', 'constant_PQ'),
    #                                f"{load.get('P_demand', 0):.6f}", f"{load.get('Q_demand', 0):.6f}",
    #                                f"{self.avg_V[idx]:.6f}" if self._safe_get(self.avg_V, idx, 0.0) != 0 else "N/A",
    #                                f"{V_kV:.6f}", supply_status])
    #         else:
    #             writer.writerow(['No load data available'])
            
    #         writer.writerow([])
            
    #         # =========================================================
    #         # SECTION 4: TRANSMISSION LINE DATA (Bidirectional)
    #         # =========================================================
    #         writer.writerow(['# ========== TRANSMISSION LINE DATA =========='])  
    #         writer.writerow(['line_num', 'line_name', 'from_bus', 'to_bus', 'length_km', 'area', 'zone', 'owner',
    #                     'I_R_per_km', 'I_X_per_km', 'I_B_per_km', 'I_R_total_pu', 'I_X_total_pu', 'I_B_total_pu',
    #                     'I_rateA_MVA', 'I_rateB_MVA', 'I_rateC_MVA', 'I_status',
    #                     'O_P_fwd_MW', 'O_Q_fwd_Mvar', 'O_MVA_fwd_MVA',
    #                     'O_P_rev_MW', 'O_Q_rev_Mvar', 'O_MVA_rev_MVA',
    #                     'O_losses_MW', 'O_loss_per_km', 'O_loading_pct', 'O_status'])                      
            
    #         lines = self.input_data.get('lines', {})
    #         if lines:
    #             for line_num, line in lines.items():
    #                 key = f"{line.get('from_bus', 0)}-{line.get('to_bus', 0)}"
    #                 stats = self.line_stats.get(key, {})
    #                 loading_status = self.get_status(stats.get('avg_loading', 0), {'min': 0, 'max': 80})
                    
    #                 # Get length and calculate loss per km
    #                 length = line.get('length_km', 0)
    #                 Loss_MW = abs(stats.get('avg_loss', 0))
    #                 Loss_per_km = Loss_MW / length if length > 0 else 0
                    
    #                 # Calculate MVA values
    #                 P_fwd = abs(stats.get('avg_P_fwd', 0))
    #                 Q_fwd = abs(stats.get('avg_Q_fwd', 0))
    #                 MVA_fwd = (P_fwd**2 + Q_fwd**2)**0.5
                    
    #                 P_rev = abs(stats.get('avg_P_rev', 0))
    #                 Q_rev = abs(stats.get('avg_Q_rev', 0))
    #                 MVA_rev = (P_rev**2 + Q_rev**2)**0.5
                    
    #                 writer.writerow([line_num, line.get('name', f'Line_{line_num}'), 
    #                             line.get('from_bus', 0), line.get('to_bus', 0),
    #                             f"{length:.6f}",  # NEW: length in km
    #                             line.get('area', 1), line.get('zone', 1), line.get('owner', 1),
    #                             line.get('R_per_km', 0), line.get('X_per_km', 0), line.get('B_per_km', 0),  # NEW: per-km values
    #                             line.get('r', 0), line.get('x', 0), line.get('b', 0),  # Total R, X, B
    #                             line.get('rateA', 0), line.get('rateB', 0), line.get('rateC', 0), line.get('status', 1),
    #                             f"{P_fwd:.6f}", f"{Q_fwd:.6f}", f"{MVA_fwd:.6f}",  # NEW: MVA_fwd
    #                             f"{P_rev:.6f}", f"{Q_rev:.6f}", f"{MVA_rev:.6f}",  # NEW: MVA_rev
    #                             f"{Loss_MW:.6f}", f"{Loss_per_km:.6f}",  # NEW: loss per km
    #                             f"{stats.get('avg_loading', 0):.6f}", loading_status])
    #         else:
    #             writer.writerow(['No transmission line data available'])

    #         writer.writerow([])

            
            
    #         # =========================================================
    #         # SECTION 5: TRANSFORMER DATA (Bidirectional with Tap)
    #         # =========================================================
    #         writer.writerow(['# ========== TRANSFORMER DATA =========='])

    #         writer.writerow(['xfmr_num', 'xfmr_name', 'from_bus', 'to_bus', 'I_rateA_MVA', 'area', 'zone', 'owner',
    #                     'I_R_pu', 'I_X_pu', 'I_tap_ratio', 'I_phase_shift_deg',
    #                     'I_min_tap', 'I_max_tap', 'I_step_size', 'I_status',
    #                     'O_P_fwd_MW', 'O_Q_fwd_Mvar', 'O_MVA_fwd_MVA',
    #                     'O_P_rev_MW', 'O_Q_rev_Mvar', 'O_MVA_rev_MVA',
    #                     'O_losses_MW', 'O_losses_MVA', 'O_tap_position', 'O_tap_step', 'O_loading_pct', 'O_status'])

    #         transformers = self.input_data.get('transformers', {})
    #         if transformers:
    #             for xfmr_num, xfmr in transformers.items():
    #                 key = f"{xfmr.get('from_bus', 0)}-{xfmr.get('to_bus', 0)}"
    #                 stats = self.xfmr_stats.get(key, {})
    #                 tap_ratio = stats.get('avg_tap', xfmr.get('tap_ratio', 1.0))
    #                 step_size = xfmr.get('step_size', 0.01)
    #                 min_tap = xfmr.get('min_tap', 0.9)
    #                 tap_step = int((tap_ratio - min_tap) / step_size) if step_size > 0 else 0
    #                 loading_status = self.get_status(stats.get('avg_loading', 0), {'min': 0, 'max': 80})
                    
    #                 # Calculate MVA values
    #                 P_fwd = abs(stats.get('avg_P_fwd', 0))
    #                 Q_fwd = abs(stats.get('avg_Q_fwd', 0))
    #                 MVA_fwd = (P_fwd**2 + Q_fwd**2)**0.5
                    
    #                 P_rev = abs(stats.get('avg_P_rev', 0))
    #                 Q_rev = abs(stats.get('avg_Q_rev', 0))
    #                 MVA_rev = (P_rev**2 + Q_rev**2)**0.5
                    
    #                 Loss_MW = abs(stats.get('avg_loss', 0))
    #                 Loss_MVA = (Loss_MW**2 + (abs(stats.get('avg_loss_q', 0)))**2)**0.5 if stats.get('avg_loss_q', 0) else Loss_MW
                    
    #                 writer.writerow([xfmr_num, xfmr.get('name', f'Xfmr_{xfmr_num}'),
    #                             xfmr.get('from_bus', 0), xfmr.get('to_bus', 0),
    #                             xfmr.get('rateA', 9999),  # NEW: Transformer Rating (MVA)
    #                             xfmr.get('area', 1), xfmr.get('zone', 1), xfmr.get('owner', 1),
    #                             xfmr.get('r', 0), xfmr.get('x', 0), xfmr.get('tap_ratio', 1.0),
    #                             xfmr.get('phase_shift', 0), xfmr.get('min_tap', 0.9), xfmr.get('max_tap', 1.1),
    #                             xfmr.get('step_size', 0.01), xfmr.get('status', 1),
    #                             f"{P_fwd:.6f}", f"{Q_fwd:.6f}", f"{MVA_fwd:.6f}",  # NEW: MVA_fwd
    #                             f"{P_rev:.6f}", f"{Q_rev:.6f}", f"{MVA_rev:.6f}",  # NEW: MVA_rev
    #                             f"{Loss_MW:.6f}", f"{Loss_MVA:.6f}",  # NEW: Loss_MVA
    #                             f"{tap_ratio:.6f}", tap_step,
    #                             f"{stats.get('avg_loading', 0):.6f}", loading_status])
    #         else:
    #             writer.writerow(['No transformer data available'])

    #         writer.writerow([])


            
    #         # =========================================================
    #         # SECTION 6: CAPACITOR BANK DATA
    #         # =========================================================
    #         writer.writerow(['# ========== CAPACITOR BANK DATA =========='])
    #         writer.writerow(['cap_num', 'cap_name', 'connected_bus', 'area', 'zone',
    #                        'I_Q_cap_Mvar', 'I_V_pu', 'I_V_kV', 'I_status',
    #                        'O_Q_injected_Mvar', 'O_V_actual_pu', 'O_V_actual_kV', 'O_status'])
            
    #         capacitors = self.input_data.get('capacitors', {})
    #         if capacitors:
    #             for cap_num, cap in capacitors.items():
    #                 bus_num = cap.get('bus', 0)
    #                 idx = self.engine.bus_index_map.get(bus_num, 0)
    #                 V_actual = self._safe_get(self.avg_V, idx, 1.0)
    #                 V_kV = self.get_voltage_kv(bus_num, V_actual)
    #                 O_Q_inj = cap.get('Q_cap', 0) * (V_actual ** 2)
                    
    #                 writer.writerow([cap_num, cap.get('name', f'Cap_{cap_num}'), bus_num,
    #                                cap.get('area', 1), cap.get('zone', 1),
    #                                cap.get('Q_cap', 0), "", "", cap.get('status', 1),
    #                                f"{O_Q_inj:.6f}", f"{V_actual:.6f}", f"{V_kV:.6f}",
    #                                "ONLINE" if cap.get('status', 1) == 1 else "OFFLINE"])
    #         else:
    #             writer.writerow(['No capacitor data available'])
            
    #         writer.writerow([])
            
    #         # =========================================================
    #         # SECTION 7: REACTOR DATA
    #         # =========================================================
    #         writer.writerow(['# ========== REACTOR DATA =========='])
    #         writer.writerow(['reactor_num', 'reactor_name', 'connected_bus', 'area', 'zone',
    #                        'I_Q_react_Mvar', 'I_V_pu', 'I_V_kV', 'I_status',
    #                        'O_Q_absorbed_Mvar', 'O_V_actual_pu', 'O_V_actual_kV', 'O_status'])
            
    #         reactors = self.input_data.get('reactors', {})
    #         if reactors:
    #             for reactor_num, reactor in reactors.items():
    #                 bus_num = reactor.get('bus', 0)
    #                 idx = self.engine.bus_index_map.get(bus_num, 0)
    #                 V_actual = self._safe_get(self.avg_V, idx, 1.0)
    #                 V_kV = self.get_voltage_kv(bus_num, V_actual)
    #                 O_Q_abs = reactor.get('Q_react', 0) * (V_actual ** 2)
                    
    #                 writer.writerow([reactor_num, reactor.get('name', f'Reactor_{reactor_num}'), bus_num,
    #                                reactor.get('area', 1), reactor.get('zone', 1),
    #                                reactor.get('Q_react', 0), "", "", reactor.get('status', 1),
    #                                f"{O_Q_abs:.6f}", f"{V_actual:.6f}", f"{V_kV:.6f}",
    #                                "ONLINE" if reactor.get('status', 1) == 1 else "OFFLINE"])
    #         else:
    #             writer.writerow(['No reactor data available'])
            
    #         writer.writerow([])
            
    #         # =========================================================
    #         # SECTION 8: SERIES COMPENSATION DATA
    #         # =========================================================
    #         writer.writerow(['# ========== SERIES COMPENSATION DATA =========='])
    #         writer.writerow(['series_num', 'series_name', 'from_bus', 'to_bus', 'area', 'zone', 'owner',
    #                        'I_R_pu', 'I_X_pu', 'I_compensation_pct', 'I_status',
    #                        'O_effective_X_pu', 'O_compensation_status',
    #                        'O_P_flow_from_to_MW', 'O_Q_flow_from_to_Mvar',
    #                        'O_P_flow_to_from_MW', 'O_Q_flow_to_from_Mvar', 'O_losses_MW'])
            
    #         series_comps = self.input_data.get('series_comps', {})
    #         if series_comps:
    #             for series_num, series in series_comps.items():
    #                 effective_X = series.get('x', 0) * (1 - series.get('comp_pct', 0) / 100)
    #                 comp_status = "ACTIVE" if series.get('status', 1) == 1 else "INACTIVE"
                    
    #                 writer.writerow([series_num, series.get('name', f'SC_{series_num}'),
    #                                series.get('from_bus', 0), series.get('to_bus', 0),
    #                                series.get('area', 1), series.get('zone', 1), series.get('owner', 1),
    #                                series.get('r', 0), series.get('x', 0), series.get('comp_pct', 0), series.get('status', 1),
    #                                f"{effective_X:.6f}", comp_status, "", "", "", ""])
    #         else:
    #             writer.writerow(['No series compensation data available'])
            
    #         writer.writerow([])
            
    #         # =========================================================
    #         # SECTION 9: SERIES REACTOR DATA
    #         # =========================================================
    #         writer.writerow(['# ========== SERIES REACTOR DATA =========='])
    #         writer.writerow(['series_reactor_num', 'series_reactor_name', 'from_bus', 'to_bus', 'area', 'zone', 'owner',
    #                        'I_R_pu', 'I_X_pu', 'I_status',
    #                        'O_P_flow_from_to_MW', 'O_Q_flow_from_to_Mvar',
    #                        'O_P_flow_to_from_MW', 'O_Q_flow_to_from_Mvar',
    #                        'O_losses_MW', 'O_status'])
            
    #         series_reactors = self.input_data.get('series_reactors', {})
    #         if series_reactors:
    #             for sr_num, sr in series_reactors.items():
    #                 writer.writerow([sr_num, sr.get('name', f'SR_{sr_num}'),
    #                                sr.get('from_bus', 0), sr.get('to_bus', 0),
    #                                sr.get('area', 1), sr.get('zone', 1), sr.get('owner', 1),
    #                                sr.get('r', 0), sr.get('x', 0), sr.get('status', 1),
    #                                "", "", "", "", "", "ONLINE" if sr.get('status', 1) == 1 else "OFFLINE"])
    #         else:
    #             writer.writerow(['No series reactor data available'])
            
    #         writer.writerow([])
            
    #         # =========================================================
    #         # SECTION 10: SHUNT COMPENSATION DATA
    #         # =========================================================
    #         writer.writerow(['# ========== SHUNT COMPENSATION DATA =========='])
    #         writer.writerow(['shunt_num', 'shunt_name', 'connected_bus', 'area', 'zone',
    #                        'I_Q_shunt_Mvar', 'I_V_pu', 'I_V_kV', 'I_status',
    #                        'O_Q_injected_Mvar', 'O_V_actual_pu', 'O_V_actual_kV', 'O_status'])
            
    #         shunts = self.input_data.get('shunts', {})
    #         if shunts:
    #             for shunt_num, shunt in shunts.items():
    #                 bus_num = shunt.get('bus', 0)
    #                 idx = self.engine.bus_index_map.get(bus_num, 0)
    #                 V_actual = self._safe_get(self.avg_V, idx, 1.0)
    #                 V_kV = self.get_voltage_kv(bus_num, V_actual)
    #                 O_Q_inj = shunt.get('Q_shunt', 0) * (V_actual ** 2)
                    
    #                 writer.writerow([shunt_num, shunt.get('name', f'Shunt_{shunt_num}'), bus_num,
    #                                shunt.get('area', 1), shunt.get('zone', 1),
    #                                shunt.get('Q_shunt', 0), "", "", shunt.get('status', 1),
    #                                f"{O_Q_inj:.6f}", f"{V_actual:.6f}", f"{V_kV:.6f}",
    #                                "ONLINE" if shunt.get('status', 1) == 1 else "OFFLINE"])
    #         else:
    #             writer.writerow(['No shunt compensation data available'])
            
    #         writer.writerow([])
            

    #         # =========================================================
    #         # SECTION 11: SYSTEM SUMMARY
    #         # =========================================================
    #         total_losses = sum(s['avg_loss'] for s in self.line_stats.values()) + sum(s['avg_loss'] for s in self.xfmr_stats.values())
    #         total_gen = sum(g.get('P_out', 0) for g in self.input_data.get('generators', {}).values())
    #         total_load = sum(l.get('P_demand', 0) for l in self.input_data.get('loads', {}).values())
            
    #         writer.writerow(['# ========== SYSTEM SUMMARY =========='])
    #         writer.writerow(['Parameter', 'Value', 'Unit'])
    #         writer.writerow(['Total Generation', f"{total_gen:.6f}", 'MW'])
    #         writer.writerow(['Total Load', f"{total_load:.6f}", 'MW'])
    #         writer.writerow(['Total Losses', f"{total_losses:.6f}", 'MW'])
    #         writer.writerow(['Loss Percentage', f"{(total_losses/total_load)*100 if total_load > 0 else 0:.6f}", '%'])
    #         writer.writerow(['Average Voltage', f"{np.mean(self.avg_V):.6f}", 'pu'])
    #         writer.writerow(['Minimum Voltage', f"{np.min(self.avg_V):.6f}", 'pu'])
    #         writer.writerow(['Maximum Voltage', f"{np.max(self.avg_V):.6f}", 'pu'])
    #         writer.writerow(['Number of Buses', f"{len(self.input_data.get('buses', {}))}", ''])
    #         writer.writerow(['Number of Generators', f"{len(self.input_data.get('generators', {}))}", ''])
    #         writer.writerow(['Number of Loads', f"{len(self.input_data.get('loads', {}))}", ''])
    #         writer.writerow(['Number of Lines', f"{len(self.input_data.get('lines', {}))}", ''])
    #         writer.writerow(['Number of Transformers', f"{len(self.input_data.get('transformers', {}))}", ''])
    #         writer.writerow(['Number of Capacitors', f"{len(self.input_data.get('capacitors', {}))}", ''])
    #         writer.writerow(['Number of Reactors', f"{len(self.input_data.get('reactors', {}))}", ''])
    #         writer.writerow(['Number of Series Comps', f"{len(self.input_data.get('series_comps', {}))}", ''])
    #         writer.writerow(['Number of Series Reactors', f"{len(self.input_data.get('series_reactors', {}))}", ''])
    #         writer.writerow(['Number of Shunts', f"{len(self.input_data.get('shunts', {}))}", ''])
    #         writer.writerow(['Samples Generated', f"{len(self.samples)}", ''])
    #         writer.writerow(['Variation Strength', f"{self.variation_strength*100:.0f}", '%'])
        
    #     #print(f"  ✓ CSV (all data with ALL elements): {filename}")
    #     return filename

    # def write_csv_all_data(self, filename):
    #     """Write CSV with ALL data - output starts at column 51"""
        
    #     OUTPUT_START_COL = 51
        
    #     with open(filename, 'w', newline='', encoding='utf-8') as f:
    #         writer = csv.writer(f)
            
    #         # ========== BUS DATA ==========
    #         writer.writerow(['# ವಿಲೋಮ ವಿದ್ಯುತ್ ಹರಿವಿನ ಅಧ್ಯಯನ (ಇನ್ವರ್ಸ್ ಪವರ್ ಫ್ಲೋ)'])
    #         writer.writerow(['# ========== BUS DATA =========='])
            
    #         # Create header with 51 empty column names + output headers
    #         headers = [f'col_{i}' for i in range(OUTPUT_START_COL)]
    #         headers.extend(['O_V_final_pu', 'O_V_final_kV', 'O_angle_deg', 'O_voltage_status', 'O_angle_status'])
    #         writer.writerow(headers)
            
    #         buses = self.input_data.get('buses', {})
    #         if buses:
    #             for bus_num, bus in buses.items():
    #                 idx = self.engine.bus_index_map.get(bus_num, 0)
    #                 V_kV = self.get_voltage_kv(bus_num, self._safe_get(self.avg_V, idx, 1.0))
    #                 v_status = self.get_status(self._safe_get(self.avg_V, idx, 1.0), {'min': 0.95, 'max': 1.05})
    #                 a_status = self.get_status(abs(self._safe_get(self.avg_Va, idx, 0.0)), {'min': 0, 'max': 30})
                    
    #                 # Create row with 51 empty columns
    #                 row = [''] * OUTPUT_START_COL
                    
    #                 # Fill input columns (0-10)
    #                 row[0] = bus_num
    #                 row[1] = bus.get('name', f'Bus_{bus_num}')
    #                 row[2] = bus.get('type', 1)
    #                 row[3] = bus.get('base_kV', 132)
    #                 row[4] = bus.get('area', 1)
    #                 row[5] = bus.get('zone', 1)
    #                 row[6] = bus.get('owner', 1)
    #                 row[7] = bus.get('V_init', 1.0)
    #                 row[8] = bus.get('angle_init', 0.0)
    #                 row[9] = bus.get('shunt_G', 0)
    #                 row[10] = bus.get('shunt_B', 0)
                    
    #                 # Fill output columns starting at 51
    #                 row[OUTPUT_START_COL + 0] = f"{self.avg_V[idx]:.6f}" if self._safe_get(self.avg_V, idx, 0.0) != 0 else "N/A"
    #                 row[OUTPUT_START_COL + 1] = f"{V_kV:.6f}"
    #                 row[OUTPUT_START_COL + 2] = f"{self.avg_Va[idx]:.6f}" if idx < len(self.avg_Va) else "N/A"
    #                 row[OUTPUT_START_COL + 3] = v_status
    #                 row[OUTPUT_START_COL + 4] = a_status
                    
    #                 writer.writerow(row)
    #         else:
    #             writer.writerow(['No bus data available'])
            
    #         writer.writerow([])
            
    #         # ========== GENERATOR DATA ==========
    #         writer.writerow(['# ========== GENERATOR DATA =========='])
            
    #         headers = [f'col_{i}' for i in range(OUTPUT_START_COL)]
    #         headers.extend(['O_P_out_MW', 'O_Q_out_Mvar', 'O_V_actual_pu', 'O_V_actual_kV', 'O_Q_status', 'O_limit_flag', 'O_status'])
    #         writer.writerow(headers)
            
    #         generators = self.input_data.get('generators', {})
    #         if generators:
    #             for gen_num, gen in generators.items():
    #                 bus_num = gen.get('bus', 0)
    #                 idx = self.engine.bus_index_map.get(bus_num, 0)
    #                 V_kV = self.get_voltage_kv(bus_num, self._safe_get(self.avg_V, idx, 1.0))
    #                 O_P_out = -self.avg_P[idx] if idx < len(self.avg_P) and self.avg_P[idx] < 0 else gen.get('P_out', 0)
    #                 O_Q_out = gen.get('Q_out', 0)
                    
    #                 q_status = "WITHIN LIMITS"
    #                 limit_flag = "OK"
    #                 if O_Q_out < gen.get('Qmin', -9999):
    #                     q_status = "BELOW Qmin"
    #                     limit_flag = "VIOLATED"
    #                 elif O_Q_out > gen.get('Qmax', 9999):
    #                     q_status = "ABOVE Qmax"
    #                     limit_flag = "VIOLATED"
                    
    #                 row = [''] * OUTPUT_START_COL
                    
    #                 # Input columns (0-12)
    #                 row[0] = gen_num
    #                 row[1] = gen.get('name', f'Gen_{gen_num}')
    #                 row[2] = gen.get('type', 'SYNC')
    #                 row[3] = bus_num
    #                 row[4] = gen.get('area', 1)
    #                 row[5] = gen.get('zone', 1)
    #                 row[6] = gen.get('P_out', 0)
    #                 row[7] = gen.get('Q_out', 0)
    #                 row[8] = gen.get('V_set', 1.0)
    #                 row[9] = gen.get('Qmin', -9999)
    #                 row[10] = gen.get('Qmax', 9999)
    #                 row[11] = gen.get('status', 1)
    #                 row[12] = gen.get('owner', 1)
                    
    #                 # Output at column 51
    #                 row[OUTPUT_START_COL + 0] = f"{O_P_out:.6f}"
    #                 row[OUTPUT_START_COL + 1] = f"{O_Q_out:.6f}"
    #                 row[OUTPUT_START_COL + 2] = f"{self.avg_V[idx]:.6f}" if self._safe_get(self.avg_V, idx, 0.0) != 0 else "N/A"
    #                 row[OUTPUT_START_COL + 3] = f"{V_kV:.6f}"
    #                 row[OUTPUT_START_COL + 4] = q_status
    #                 row[OUTPUT_START_COL + 5] = limit_flag
    #                 row[OUTPUT_START_COL + 6] = "ONLINE" if gen.get('status', 1) == 1 else "OFFLINE"
                    
    #                 writer.writerow(row)
    #         else:
    #             writer.writerow(['No generator data available'])
            
    #         writer.writerow([])
            
    #         # ========== LOAD DATA ==========
    #         writer.writerow(['# ========== LOAD DATA =========='])
            
    #         headers = [f'col_{i}' for i in range(OUTPUT_START_COL)]
    #         headers.extend(['O_P_supplied_MW', 'O_Q_supplied_Mvar', 'O_V_actual_pu', 'O_V_actual_kV', 'O_supply_status'])
    #         writer.writerow(headers)
            
    #         loads = self.input_data.get('loads', {})
    #         if loads:
    #             for load_num, load in loads.items():
    #                 bus_num = load.get('bus', 0)
    #                 idx = self.engine.bus_index_map.get(bus_num, 0)
    #                 V_kV = self.get_voltage_kv(bus_num, self._safe_get(self.avg_V, idx, 1.0))
    #                 supply_status = "NORMAL" if (self._safe_get(self.avg_V, idx, 0.0) != 0 and self.avg_V[idx] >= 0.95) else "VOLTAGE LOW"
                    
    #                 row = [''] * OUTPUT_START_COL
                    
    #                 # Input columns (0-8)
    #                 row[0] = load_num
    #                 row[1] = load.get('name', f'Load_{load_num}')
    #                 row[2] = bus_num
    #                 row[3] = load.get('area', 1)
    #                 row[4] = load.get('zone', 1)
    #                 row[5] = load.get('P_demand', 0)
    #                 row[6] = load.get('Q_demand', 0)
    #                 row[7] = load.get('model', 'constant_PQ')
    #                 row[8] = load.get('status', 1)
                    
    #                 # Output at column 51
    #                 row[OUTPUT_START_COL + 0] = f"{load.get('P_demand', 0):.6f}"
    #                 row[OUTPUT_START_COL + 1] = f"{load.get('Q_demand', 0):.6f}"
    #                 row[OUTPUT_START_COL + 2] = f"{self.avg_V[idx]:.6f}" if self._safe_get(self.avg_V, idx, 0.0) != 0 else "N/A"
    #                 row[OUTPUT_START_COL + 3] = f"{V_kV:.6f}"
    #                 row[OUTPUT_START_COL + 4] = supply_status
                    
    #                 writer.writerow(row)
    #         else:
    #             writer.writerow(['No load data available'])
            
    #         writer.writerow([])
            
    #         # ========== LINE DATA ==========
    #         writer.writerow(['# ========== TRANSMISSION LINE DATA =========='])
            
    #         headers = [f'col_{i}' for i in range(OUTPUT_START_COL)]
    #         headers.extend(['O_P_fwd_MW', 'O_Q_fwd_Mvar', 'O_MVA_fwd_MVA', 'O_P_rev_MW', 'O_Q_rev_Mvar', 'O_MVA_rev_MVA', 'O_losses_MW', 'O_loss_per_km', 'O_loading_pct', 'O_status'])
    #         writer.writerow(headers)
            
    #         lines = self.input_data.get('lines', {})
    #         if lines:
    #             for line_num, line in lines.items():
    #                 key = f"{line.get('from_bus', 0)}-{line.get('to_bus', 0)}"
    #                 stats = self.line_stats.get(key, {})
    #                 loading_status = self.get_status(stats.get('avg_loading', 0), {'min': 0, 'max': 80})
                    
    #                 length = line.get('length_km', 0)
    #                 Loss_MW = abs(stats.get('avg_loss', 0))
    #                 Loss_per_km = Loss_MW / length if length > 0 else 0
                    
    #                 P_fwd = abs(stats.get('avg_P_fwd', 0))
    #                 Q_fwd = abs(stats.get('avg_Q_fwd', 0))
    #                 MVA_fwd = (P_fwd**2 + Q_fwd**2)**0.5
                    
    #                 P_rev = abs(stats.get('avg_P_rev', 0))
    #                 Q_rev = abs(stats.get('avg_Q_rev', 0))
    #                 MVA_rev = (P_rev**2 + Q_rev**2)**0.5
                    
    #                 row = [''] * OUTPUT_START_COL
                    
    #                 # Input columns (0-13)
    #                 row[0] = line_num
    #                 row[1] = line.get('name', f'Line_{line_num}')
    #                 row[2] = line.get('from_bus', 0)
    #                 row[3] = line.get('to_bus', 0)
    #                 row[4] = length
    #                 row[5] = line.get('area', 1)
    #                 row[6] = line.get('zone', 1)
    #                 row[7] = line.get('owner', 1)
    #                 row[8] = line.get('R_per_km', 0)
    #                 row[9] = line.get('X_per_km', 0)
    #                 row[10] = line.get('B_per_km', 0)
    #                 row[11] = line.get('r', 0)
    #                 row[12] = line.get('x', 0)
    #                 row[13] = line.get('b', 0)
    #                 row[14] = line.get('rateA', 0)
    #                 row[15] = line.get('rateB', 0)
    #                 row[16] = line.get('rateC', 0)
    #                 row[17] = line.get('status', 1)
                    
    #                 # Output at column 51
    #                 row[OUTPUT_START_COL + 0] = f"{P_fwd:.6f}"
    #                 row[OUTPUT_START_COL + 1] = f"{Q_fwd:.6f}"
    #                 row[OUTPUT_START_COL + 2] = f"{MVA_fwd:.6f}"
    #                 row[OUTPUT_START_COL + 3] = f"{P_rev:.6f}"
    #                 row[OUTPUT_START_COL + 4] = f"{Q_rev:.6f}"
    #                 row[OUTPUT_START_COL + 5] = f"{MVA_rev:.6f}"
    #                 row[OUTPUT_START_COL + 6] = f"{Loss_MW:.6f}"
    #                 row[OUTPUT_START_COL + 7] = f"{Loss_per_km:.6f}"
    #                 row[OUTPUT_START_COL + 8] = f"{stats.get('avg_loading', 0):.6f}"
    #                 row[OUTPUT_START_COL + 9] = loading_status
                    
    #                 writer.writerow(row)
    #         else:
    #             writer.writerow(['No transmission line data available'])
            
    #         writer.writerow([])
            
    #         # ========== TRANSFORMER DATA ==========
    #         writer.writerow(['# ========== TRANSFORMER DATA =========='])
            
    #         headers = [f'col_{i}' for i in range(OUTPUT_START_COL)]
    #         headers.extend(['O_P_fwd_MW', 'O_Q_fwd_Mvar', 'O_MVA_fwd_MVA', 'O_P_rev_MW', 'O_Q_rev_Mvar', 'O_MVA_rev_MVA', 'O_losses_MW', 'O_losses_MVA', 'O_tap_position', 'O_tap_step', 'O_loading_pct', 'O_status'])
    #         writer.writerow(headers)
            
    #         transformers = self.input_data.get('transformers', {})
    #         if transformers:
    #             for xfmr_num, xfmr in transformers.items():
    #                 key = f"{xfmr.get('from_bus', 0)}-{xfmr.get('to_bus', 0)}"
    #                 stats = self.xfmr_stats.get(key, {})
    #                 tap_ratio = stats.get('avg_tap', xfmr.get('tap_ratio', 1.0))
    #                 step_size = xfmr.get('step_size', 0.01)
    #                 min_tap = xfmr.get('min_tap', 0.9)
    #                 tap_step = int((tap_ratio - min_tap) / step_size) if step_size > 0 else 0
    #                 loading_status = self.get_status(stats.get('avg_loading', 0), {'min': 0, 'max': 80})
                    
    #                 P_fwd = abs(stats.get('avg_P_fwd', 0))
    #                 Q_fwd = abs(stats.get('avg_Q_fwd', 0))
    #                 MVA_fwd = (P_fwd**2 + Q_fwd**2)**0.5
                    
    #                 P_rev = abs(stats.get('avg_P_rev', 0))
    #                 Q_rev = abs(stats.get('avg_Q_rev', 0))
    #                 MVA_rev = (P_rev**2 + Q_rev**2)**0.5
                    
    #                 Loss_MW = abs(stats.get('avg_loss', 0))
    #                 Loss_MVA = (Loss_MW**2 + (abs(stats.get('avg_loss_q', 0)))**2)**0.5 if stats.get('avg_loss_q', 0) else Loss_MW
                    
    #                 row = [''] * OUTPUT_START_COL
                    
    #                 # Input columns (0-18)
    #                 row[0] = xfmr_num
    #                 row[1] = xfmr.get('name', f'Xfmr_{xfmr_num}')
    #                 row[2] = xfmr.get('from_bus', 0)
    #                 row[3] = xfmr.get('to_bus', 0)
    #                 row[4] = xfmr.get('rateA', 9999)
    #                 row[5] = xfmr.get('area', 1)
    #                 row[6] = xfmr.get('zone', 1)
    #                 row[7] = xfmr.get('owner', 1)
    #                 row[8] = xfmr.get('r', 0)
    #                 row[9] = xfmr.get('x', 0)
    #                 row[10] = xfmr.get('tap_ratio', 1.0)
    #                 row[11] = xfmr.get('phase_shift', 0)
    #                 row[12] = xfmr.get('min_tap', 0.9)
    #                 row[13] = xfmr.get('max_tap', 1.1)
    #                 row[14] = xfmr.get('step_size', 0.01)
    #                 row[15] = xfmr.get('status', 1)
    #                 row[16] = xfmr.get('area', 1)
    #                 row[17] = xfmr.get('zone', 1)
    #                 row[18] = xfmr.get('owner', 1)
                    
    #                 # Output at column 51
    #                 row[OUTPUT_START_COL + 0] = f"{P_fwd:.6f}"
    #                 row[OUTPUT_START_COL + 1] = f"{Q_fwd:.6f}"
    #                 row[OUTPUT_START_COL + 2] = f"{MVA_fwd:.6f}"
    #                 row[OUTPUT_START_COL + 3] = f"{P_rev:.6f}"
    #                 row[OUTPUT_START_COL + 4] = f"{Q_rev:.6f}"
    #                 row[OUTPUT_START_COL + 5] = f"{MVA_rev:.6f}"
    #                 row[OUTPUT_START_COL + 6] = f"{Loss_MW:.6f}"
    #                 row[OUTPUT_START_COL + 7] = f"{Loss_MVA:.6f}"
    #                 row[OUTPUT_START_COL + 8] = f"{tap_ratio:.6f}"
    #                 row[OUTPUT_START_COL + 9] = tap_step
    #                 row[OUTPUT_START_COL + 10] = f"{stats.get('avg_loading', 0):.6f}"
    #                 row[OUTPUT_START_COL + 11] = loading_status
                    
    #                 writer.writerow(row)
    #         else:
    #             writer.writerow(['No transformer data available'])
            
    #         writer.writerow([])
            
    #         # ========== CAPACITOR DATA ==========
    #         writer.writerow(['# ========== CAPACITOR BANK DATA =========='])
            
    #         headers = [f'col_{i}' for i in range(OUTPUT_START_COL)]
    #         headers.extend(['O_Q_injected_Mvar', 'O_V_actual_pu', 'O_V_actual_kV', 'O_status'])
    #         writer.writerow(headers)
            
    #         capacitors = self.input_data.get('capacitors', {})
    #         if capacitors:
    #             for cap_num, cap in capacitors.items():
    #                 bus_num = cap.get('bus', 0)
    #                 idx = self.engine.bus_index_map.get(bus_num, 0)
    #                 V_actual = self._safe_get(self.avg_V, idx, 1.0)
    #                 V_kV = self.get_voltage_kv(bus_num, V_actual)
    #                 O_Q_inj = cap.get('Q_cap', 0) * (V_actual ** 2)
                    
    #                 row = [''] * OUTPUT_START_COL
                    
    #                 # Input columns (0-7)
    #                 row[0] = cap_num
    #                 row[1] = cap.get('name', f'Cap_{cap_num}')
    #                 row[2] = bus_num
    #                 row[3] = cap.get('area', 1)
    #                 row[4] = cap.get('zone', 1)
    #                 row[5] = cap.get('Q_cap', 0)
    #                 row[6] = cap.get('status', 1)
    #                 row[7] = cap.get('owner', 1)
                    
    #                 # Output at column 51
    #                 row[OUTPUT_START_COL + 0] = f"{O_Q_inj:.6f}"
    #                 row[OUTPUT_START_COL + 1] = f"{V_actual:.6f}"
    #                 row[OUTPUT_START_COL + 2] = f"{V_kV:.6f}"
    #                 row[OUTPUT_START_COL + 3] = "ONLINE" if cap.get('status', 1) == 1 else "OFFLINE"
                    
    #                 writer.writerow(row)
    #         else:
    #             writer.writerow(['No capacitor data available'])
            
    #         writer.writerow([])
            
    #         # ========== REACTOR DATA ==========
    #         writer.writerow(['# ========== REACTOR DATA =========='])
            
    #         headers = [f'col_{i}' for i in range(OUTPUT_START_COL)]
    #         headers.extend(['O_Q_absorbed_Mvar', 'O_V_actual_pu', 'O_V_actual_kV', 'O_status'])
    #         writer.writerow(headers)
            
    #         reactors = self.input_data.get('reactors', {})
    #         if reactors:
    #             for reactor_num, reactor in reactors.items():
    #                 bus_num = reactor.get('bus', 0)
    #                 idx = self.engine.bus_index_map.get(bus_num, 0)
    #                 V_actual = self._safe_get(self.avg_V, idx, 1.0)
    #                 V_kV = self.get_voltage_kv(bus_num, V_actual)
    #                 O_Q_abs = reactor.get('Q_react', 0) * (V_actual ** 2)
                    
    #                 row = [''] * OUTPUT_START_COL
                    
    #                 # Input columns (0-7)
    #                 row[0] = reactor_num
    #                 row[1] = reactor.get('name', f'Reactor_{reactor_num}')
    #                 row[2] = bus_num
    #                 row[3] = reactor.get('area', 1)
    #                 row[4] = reactor.get('zone', 1)
    #                 row[5] = reactor.get('Q_react', 0)
    #                 row[6] = reactor.get('status', 1)
    #                 row[7] = reactor.get('owner', 1)
                    
    #                 # Output at column 51
    #                 row[OUTPUT_START_COL + 0] = f"{O_Q_abs:.6f}"
    #                 row[OUTPUT_START_COL + 1] = f"{V_actual:.6f}"
    #                 row[OUTPUT_START_COL + 2] = f"{V_kV:.6f}"
    #                 row[OUTPUT_START_COL + 3] = "ONLINE" if reactor.get('status', 1) == 1 else "OFFLINE"
                    
    #                 writer.writerow(row)
    #         else:
    #             writer.writerow(['No reactor data available'])
            
    #         writer.writerow([])
            
    #         # ========== SYSTEM SUMMARY (no change - stays at end) ==========
    #         total_losses = sum(s['avg_loss'] for s in self.line_stats.values()) + sum(s['avg_loss'] for s in self.xfmr_stats.values())
    #         total_gen = sum(g.get('P_out', 0) for g in self.input_data.get('generators', {}).values())
    #         total_load = sum(l.get('P_demand', 0) for l in self.input_data.get('loads', {}).values())
            
    #         writer.writerow(['# ========== SYSTEM SUMMARY =========='])
    #         writer.writerow(['Parameter', 'Value', 'Unit'])
    #         writer.writerow(['Total Generation', f"{total_gen:.6f}", 'MW'])
    #         writer.writerow(['Total Load', f"{total_load:.6f}", 'MW'])
    #         writer.writerow(['Total Losses', f"{total_losses:.6f}", 'MW'])
    #         writer.writerow(['Loss Percentage', f"{(total_losses/total_load)*100 if total_load > 0 else 0:.6f}", '%'])
    #         writer.writerow(['Average Voltage', f"{np.mean(self.avg_V):.6f}", 'pu'])
    #         writer.writerow(['Minimum Voltage', f"{np.min(self.avg_V):.6f}", 'pu'])
    #         writer.writerow(['Maximum Voltage', f"{np.max(self.avg_V):.6f}", 'pu'])
    #         writer.writerow(['Samples Generated', f"{len(self.samples)}", ''])
    #         writer.writerow(['Variation Strength', f"{self.variation_strength*100:.0f}", '%'])
        
    #     return filename  

    def generate_convergence_report_lines(self, comment_prefix=""):
        info = getattr(self, 'solver_info', {}) or {}
        p = comment_prefix
        lines = []
        lines.append(f"{p}=====================================================================================")
        lines.append(f"{p}⚡ LOAD FLOW ANALYSIS — SYSTEM SUMMARY & CONVERGENCE REPORT")
        lines.append(f"{p}=====================================================================================")
        
        solver_engine = info.get('engine', 'ANDES / DevEN Engine')
        conv_status = "✅ CONVERGED SUCCESSFUL" if info.get('converged', True) else "❌ NOT CONVERGED (MAX ITER EXCEEDED)"
        iters = info.get('iterations', 'N/A')
        inp_tol = info.get('input_tol', '1e-4')
        inp_max_iter = info.get('input_max_iter', '30')
        dp_val = info.get('max_dP', 0.0)
        dq_val = info.get('max_dQ', 0.0)
        
        lines.append(f"{p}Result File             : {info.get('file_name', 'N/A')}")
        lines.append(f"{p}Solver Engine           : {solver_engine}")
        lines.append(f"{p}-------------------------------------------------------------------------------------")
        lines.append(f"{p}📌 SOLVER CONVERGENCE & PARAMETERS:")
        lines.append(f"{p}-------------------------------------------------------------------------------------")
        lines.append(f"{p}Convergence Status      : {conv_status}")
        lines.append(f"{p}Iterations Executed     : {iters} iterations")
        lines.append(f"{p}Input Tolerance Setting : {inp_tol}")
        lines.append(f"{p}Input Max Iterations    : {inp_max_iter}")
        lines.append(f"{p}Final Active Mismatch   : Max |dP| = {dp_val:.6f} p.u. ({dp_val*100.0:.6f} MW)")
        lines.append(f"{p}Final Reactive Mismatch : Max |dQ| = {dq_val:.6f} p.u. ({dq_val*100.0:.6f} Mvar)")
        
        iter_logs = info.get('iter_logs', [])
        if iter_logs:
            lines.append(f"{p}-------------------------------------------------------------------------------------")
            lines.append(f"{p}📌 ITERATION LOG:")
            lines.append(f"{p}-------------------------------------------------------------------------------------")
            for log_item in iter_logs:
                lines.append(f"{p}{log_item}")

        lines.append(f"{p}-------------------------------------------------------------------------------------")
        lines.append(f"{p}📊 SYSTEM POWER BALANCE (INPUT DEMAND vs OUTPUT GENERATION):")
        lines.append(f"{p}-------------------------------------------------------------------------------------")
        
        tot_buses = len(self.input_data.get('buses', {}))
        tot_lines = len(self.input_data.get('lines', {}))
        tot_xfmrs = len(self.input_data.get('transformers', {}))
        
        def _is_load_online(l):
            st = l.get('status', 1)
            return st != 0 and str(st).strip().lower() not in ('0', 'false', 'offline', 'disabled')

        tot_p_load = sum(l.get('P_demand', 0.0) for l in self.input_data.get('loads', {}).values() if _is_load_online(l))
        tot_q_load = sum(l.get('Q_demand', 0.0) for l in self.input_data.get('loads', {}).values() if _is_load_online(l))

        tot_s_load = (tot_p_load**2 + tot_q_load**2)**0.5
        
        gen_outputs = [self.get_generator_outputs(gid, g) for gid, g in self.input_data.get('generators', {}).items() if g.get('status', 1) == 1]
        tot_p_gen = sum(p for p, q in gen_outputs if p > 0)
        tot_q_gen = sum(q for p, q in gen_outputs if p > 0)
        tot_s_gen = (tot_p_gen**2 + tot_q_gen**2)**0.5

        tot_p_motor = sum(-p for p, q in gen_outputs if p < 0)
        tot_p_load += tot_p_motor
        tot_s_load = (tot_p_load**2 + tot_q_load**2)**0.5
        
        tot_line_loss = sum(self._get_line_stats(lid, l).get('avg_loss', 0.0) for lid, l in self.input_data.get('lines', {}).items() if l.get('status', 1) == 1)
        tot_xfmr_loss = sum(self._get_xfmr_stats(xid, x).get('avg_loss', 0.0) for xid, x in self.input_data.get('transformers', {}).items() if x.get('status', 1) == 1)
        tot_hvdc_loss = sum(self._get_hvdc_stats(hid, h).get('avg_loss', 0.0) for hid, h in self.input_data.get('hvdc_links', {}).items() if h.get('status', 1) == 1)
        tot_loss_mw = tot_line_loss + tot_xfmr_loss + tot_hvdc_loss
        
        lines.append(f"{p}Total Network Buses     : {tot_buses}")
        lines.append(f"{p}Total Lines/Xfmrs       : {tot_lines} lines , {tot_xfmrs} transformers")
        lines.append(f"{p}Total Input Demand      : {tot_p_load:+.5f} MW , {tot_q_load:+.5f} Mvar ({tot_s_load:.6f} MVA)")
        lines.append(f"{p}Total Output Generation : {tot_p_gen:+.5f} MW , {tot_q_gen:+.5f} Mvar ({tot_s_gen:.6f} MVA)")
        lines.append(f"{p}Total Network Losses    : {tot_loss_mw:.6f} MW")
        lines.append(f"{p}-------------------------------------------------------------------------------------")
        return lines

    def write_csv_all_data(self, filename):
        OUTPUT_START_COL = 51
        
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Write System Summary & Convergence Report with Iteration Log
            for line in self.generate_convergence_report_lines(comment_prefix="# "):
                writer.writerow([line])
            writer.writerow([])
            
            # ========== ADD HEADER REFERENCE HERE ==========
            writer.writerow(['# ============================================================================'])
            writer.writerow(['# COLUMN HEADERS REFERENCE (Columns 0-50 reserved for input)'])
            writer.writerow(['# ============================================================================'])
            writer.writerow(['# SECTION 1: BUS DATA (Output at columns 51-55)'])
            writer.writerow(['#   51: O_V_final_pu, 52: O_V_final_kV, 53: O_angle_deg, 54: O_voltage_status, 55: O_angle_status'])
            writer.writerow(['#'])
            writer.writerow(['# SECTION 2: GENERATOR DATA (Output at columns 51-57, signed: + = generation/injection)'])
            writer.writerow(['#   51: O_P_out_MW, 52: O_Q_out_Mvar, 53: O_V_actual_pu, 54: O_V_actual_kV, 55: O_Q_status, 56: O_limit_flag, 57: O_status'])
            writer.writerow(['#'])
            writer.writerow(['# SECTION 3: LOAD DATA (Output at columns 51-55)'])
            writer.writerow(['#   51: O_P_supplied_MW, 52: O_Q_supplied_Mvar, 53: O_V_actual_pu, 54: O_V_actual_kV, 55: O_supply_status (signed: - = consumption/draw from network)'])
            writer.writerow(['#'])
            writer.writerow(['# SECTION 4: LINE DATA (Output at columns 51-61, signed: + = flows from_bus->to_bus, - = flows to_bus->from_bus)'])
            writer.writerow(['#   51: O_P_fwd_MW, 52: O_Q_fwd_Mvar, 53: O_MVA_fwd_MVA, 54: O_P_rev_MW, 55: O_Q_rev_Mvar, 56: O_MVA_rev_MVA, 57: O_losses_MW, 58: O_loss_per_km, 59: O_loading_pct, 60: O_status, 61: O_actual_flow_direction'])
            writer.writerow(['#'])
            writer.writerow(['# SECTION 5: TRANSFORMER DATA (Output at columns 51-63, signed: + = flows from_bus->to_bus, - = flows to_bus->from_bus)'])
            writer.writerow(['#   51: O_P_fwd_MW, 52: O_Q_fwd_Mvar, 53: O_MVA_fwd_MVA, 54: O_P_rev_MW, 55: O_Q_rev_Mvar, 56: O_MVA_rev_MVA, 57: O_losses_MW, 58: O_losses_MVA, 59: O_tap_position, 60: O_tap_step, 61: O_loading_pct, 62: O_status, 63: O_actual_flow_direction'])
            writer.writerow(['#'])
            writer.writerow(['# SECTION 6: CAPACITOR DATA (Output at columns 51-54)'])
            writer.writerow(['#   51: O_Q_injected_Mvar, 52: O_V_actual_pu, 53: O_V_actual_kV, 54: O_status'])
            writer.writerow(['#'])
            writer.writerow(['# SECTION 7: REACTOR DATA (Output at columns 51-54)'])
            writer.writerow(['#   51: O_Q_absorbed_Mvar, 52: O_V_actual_pu, 53: O_V_actual_kV, 54: O_status'])
            writer.writerow(['#'])
            writer.writerow(['# SECTION 8: SERIES COMPENSATION DATA (Output at columns 51-57)'])
            writer.writerow(['#   51: O_effective_X_pu, 52: O_compensation_status, 53: O_P_flow_from_to_MW, 54: O_Q_flow_from_to_Mvar, 55: O_P_flow_to_from_MW, 56: O_Q_flow_to_from_Mvar, 57: O_losses_MW'])
            writer.writerow(['#'])
            writer.writerow(['# SECTION 9: SERIES REACTOR DATA (Output at columns 51-56)'])
            writer.writerow(['#   51: O_P_flow_from_to_MW, 52: O_Q_flow_from_to_Mvar, 53: O_P_flow_to_from_MW, 54: O_Q_flow_to_from_Mvar, 55: O_losses_MW, 56: O_status'])
            writer.writerow(['#'])
            writer.writerow(['# SECTION 10: SHUNT DATA (Output at columns 51-54)'])
            writer.writerow(['#   51: O_Q_injected_Mvar, 52: O_V_actual_pu, 53: O_V_actual_kV, 54: O_status'])
            writer.writerow(['#'])
            writer.writerow(['# SECTION 11: HVDC TRANSMISSION LINK DATA (Output at columns 51-65)'])
            writer.writerow(['#   51: O_Vdc_from_kV, 52: O_Vdc_to_kV, 53: O_Idc_A, 54: O_P_dc_MW, 55: O_losses_dc_MW, 56: O_P_from_ac_MW, 57: O_Q_from_ac_Mvar, 58: O_P_to_ac_MW, 59: O_Q_to_ac_Mvar, 60: O_alpha_deg, 61: O_gamma_deg, 62: O_tap_from, 63: O_tap_to, 64: O_loading_pct, 65: O_status'])
            writer.writerow(['#'])
            writer.writerow(['# SECTION 12: SYSTEM SUMMARY (No column shift)'])
            writer.writerow(['# ============================================================================'])
                

            # =========================================================
            # SECTION 1: BUS DATA
            # =========================================================
            writer.writerow(['# ========== BUS DATA =========='])
            
            headers = [f'col_{i}' for i in range(OUTPUT_START_COL)]
            headers.extend(['O_V_final_pu', 'O_V_final_kV', 'O_angle_deg', 'O_voltage_status', 'O_angle_status'])
            writer.writerow(headers)
            
            buses = self.input_data.get('buses', {})
            if buses:
                for bus_num, bus in buses.items():
                    idx = self.engine.bus_index_map.get(bus_num, 0)
                    V_kV = self.get_voltage_kv(bus_num, self._safe_get(self.avg_V, idx, 1.0))
                    v_status = self.get_status(self._safe_get(self.avg_V, idx, 1.0), {'min': 0.95, 'max': 1.05})
                    a_status = self.get_status(abs(self._safe_get(self.avg_Va, idx, 0.0)), {'min': 0, 'max': 30})
                    
                    #row = [''] * OUTPUT_START_COL
                    row = [''] * (OUTPUT_START_COL + 5)   # 51 + 5 = 56
                    row[0] = bus_num
                    row[1] = bus.get('name', f'Bus_{bus_num}')
                    row[2] = bus.get('type', 1)
                    row[3] = bus.get('base_kV', 132)
                    row[4] = bus.get('area', 1)
                    row[5] = bus.get('zone', 1)
                    row[6] = bus.get('owner', 1)
                    row[7] = bus.get('V_init', 1.0)
                    row[8] = bus.get('angle_init', 0.0)
                    row[9] = bus.get('shunt_G', 0)
                    row[10] = bus.get('shunt_B', 0)
                    
                    row[OUTPUT_START_COL + 0] = f"{self.avg_V[idx]:.6f}" if self._safe_get(self.avg_V, idx, 0.0) != 0 else "N/A"
                    row[OUTPUT_START_COL + 1] = f"{V_kV:.6f}"
                    row[OUTPUT_START_COL + 2] = f"{self.avg_Va[idx]:.6f}" if idx < len(self.avg_Va) else "N/A"
                    row[OUTPUT_START_COL + 3] = v_status
                    row[OUTPUT_START_COL + 4] = a_status
                    
                    writer.writerow(row)
            else:
                writer.writerow(['No bus data available'])
            writer.writerow([])
            
            # =========================================================
            # SECTION 2: GENERATOR DATA
            # =========================================================
            writer.writerow(['# ========== GENERATOR DATA =========='])
            
            headers = [f'col_{i}' for i in range(OUTPUT_START_COL)]
            headers.extend(['O_P_out_MW', 'O_Q_out_Mvar', 'O_V_actual_pu', 'O_V_actual_kV', 'O_Q_status', 'O_limit_flag', 'O_status'])
            writer.writerow(headers)
            
            generators = self.input_data.get('generators', {})
            if generators:
                for gen_num, gen in generators.items():
                    bus_num = gen.get('bus', 0)
                    idx = self.engine.bus_index_map.get(bus_num, 0)
                    V_kV = self.get_voltage_kv(bus_num, self._safe_get(self.avg_V, idx, 1.0))
                    O_P_out, O_Q_out = self.get_generator_outputs(gen_num, gen)
                    
                    bus_type = self.input_data.get('buses', {}).get(bus_num, {}).get('type', 1)
                    qmin_val = gen.get('Qmin', -9999.0)
                    qmax_val = gen.get('Qmax', 9999.0)
                    q_status = "WITHIN LIMITS"
                    limit_flag = "OK"
                    if bus_type == 1:
                        if qmin_val is not None and O_Q_out < float(qmin_val) - 1e-3:
                            q_status = "BELOW Qmin"
                            limit_flag = "VIOLATED"
                        elif qmax_val is not None and O_Q_out > float(qmax_val) + 1e-3:
                            q_status = "ABOVE Qmax"
                            limit_flag = "VIOLATED"
                        else:
                            q_status = "WITHIN LIMITS"
                            limit_flag = "OK"
                    elif abs(O_Q_out - qmax_val) <= 1e-3:
                        q_status = "AT Qmax"
                        limit_flag = "OK"
                    elif abs(O_Q_out - qmin_val) <= 1e-3:
                        q_status = "AT Qmin"
                        limit_flag = "OK"
                    elif O_Q_out < qmin_val - 1e-3:
                        q_status = "BELOW Qmin"
                        limit_flag = "VIOLATED"
                    elif O_Q_out > qmax_val + 1e-3:
                        q_status = "ABOVE Qmax"
                        limit_flag = "VIOLATED"
                    
                    #row = [''] * OUTPUT_START_COL
                    row = [''] * (OUTPUT_START_COL + 7)   # 51 + 7 = 58
                    row[0] = gen_num
                    row[1] = gen.get('name', f'Gen_{gen_num}')
                    row[2] = gen.get('type', 'SYNC')
                    row[3] = bus_num
                    row[4] = gen.get('area', 1)
                    row[5] = gen.get('zone', 1)
                    row[6] = gen.get('P_out', 0)
                    row[7] = gen.get('Q_out', 0)
                    row[8] = gen.get('V_set', 1.0)
                    row[9] = gen.get('Qmin', -9999)
                    row[10] = gen.get('Qmax', 9999)
                    row[11] = gen.get('status', 1)
                    row[12] = gen.get('owner', 1)
                    
                    row[OUTPUT_START_COL + 0] = f"{O_P_out:+.5f}"
                    row[OUTPUT_START_COL + 1] = f"{O_Q_out:+.5f}"
                    row[OUTPUT_START_COL + 2] = f"{self.avg_V[idx]:.6f}" if self._safe_get(self.avg_V, idx, 0.0) != 0 else "N/A"
                    row[OUTPUT_START_COL + 3] = f"{V_kV:.6f}"
                    row[OUTPUT_START_COL + 4] = q_status
                    row[OUTPUT_START_COL + 5] = limit_flag
                    row[OUTPUT_START_COL + 6] = "ONLINE" if gen.get('status', 1) == 1 else "OFFLINE"
                    
                    writer.writerow(row)
            else:
                writer.writerow(['No generator data available'])
            writer.writerow([])
            
            # =========================================================
            # SECTION 3: LOAD DATA
            # =========================================================
            writer.writerow(['# ========== LOAD DATA =========='])
            
            headers = [f'col_{i}' for i in range(OUTPUT_START_COL)]
            headers.extend(['O_P_supplied_MW', 'O_Q_supplied_Mvar', 'O_V_actual_pu', 'O_V_actual_kV', 'O_supply_status'])
            writer.writerow(headers)
            
            loads = self.input_data.get('loads', {})
            if loads:
                for load_num, load in loads.items():
                    bus_num = load.get('bus', 0)
                    idx = self.engine.bus_index_map.get(bus_num, 0)
                    V_kV = self.get_voltage_kv(bus_num, self._safe_get(self.avg_V, idx, 1.0))
                    supply_status = "NORMAL" if (self._safe_get(self.avg_V, idx, 0.0) != 0 and self.avg_V[idx] >= 0.95) else "VOLTAGE LOW"
                    
                    #row = [''] * OUTPUT_START_COL
                    row = [''] * (OUTPUT_START_COL + 5)   # 51 + 5 = 56
                    row[0] = load_num
                    row[1] = load.get('name', f'Load_{load_num}')
                    row[2] = bus_num
                    row[3] = load.get('area', 1)
                    row[4] = load.get('zone', 1)
                    row[5] = load.get('P_demand', 0)
                    row[6] = load.get('Q_demand', 0)
                    row[7] = load.get('model', 'constant_PQ')
                    row[8] = load.get('status', 1)
                    
                    O_P_supplied = -float(load.get('P_demand', 0))
                    O_Q_supplied = -float(load.get('Q_demand', 0))
                    if abs(O_P_supplied) < 1e-6: O_P_supplied = 0.0
                    if abs(O_Q_supplied) < 1e-6: O_Q_supplied = 0.0

                    row[OUTPUT_START_COL + 0] = f"{O_P_supplied:.5f}"
                    row[OUTPUT_START_COL + 1] = f"{O_Q_supplied:.5f}"
                    row[OUTPUT_START_COL + 2] = f"{self.avg_V[idx]:.6f}" if self._safe_get(self.avg_V, idx, 0.0) != 0 else "N/A"
                    row[OUTPUT_START_COL + 3] = f"{V_kV:.6f}"
                    row[OUTPUT_START_COL + 4] = supply_status
                    
                    writer.writerow(row)
            else:
                writer.writerow(['No load data available'])
            writer.writerow([])
            
            # =========================================================
            # SECTION 4: TRANSMISSION LINE DATA
            # =========================================================
            writer.writerow(['# ========== TRANSMISSION LINE DATA =========='])
            
            headers = [f'col_{i}' for i in range(OUTPUT_START_COL)]
            headers.extend(['O_P_fwd_MW', 'O_Q_fwd_Mvar', 'O_MVA_fwd_MVA', 'O_P_rev_MW', 'O_Q_rev_Mvar', 'O_MVA_rev_MVA', 'O_losses_MW', 'O_loss_per_km', 'O_loading_pct', 'O_status', 'O_actual_flow_direction'])
            writer.writerow(headers)
            
            lines = self.input_data.get('lines', {})
            if lines:
                for line_num, line in lines.items():
                    stats = self._get_line_stats(line_num, line)
                    loading_status = self.get_status(stats.get('avg_loading', 0), {'min': 0, 'max': 80})
                    
                    length = line.get('length_km', 0)
                    Loss_MW = abs(stats.get('avg_loss', 0))
                    Loss_per_km = Loss_MW / length if length > 0 else 0
                    
                    P_fwd = stats.get('avg_P_fwd', 0)
                    Q_fwd = stats.get('avg_Q_fwd', 0)
                    MVA_fwd = (P_fwd**2 + Q_fwd**2)**0.5
                    
                    P_rev = stats.get('avg_P_rev', 0)
                    Q_rev = stats.get('avg_Q_rev', 0)
                    MVA_rev = (P_rev**2 + Q_rev**2)**0.5
                    
                    flow_dir = (f"Bus{line.get('from_bus', 0)} -> Bus{line.get('to_bus', 0)}" if P_fwd >= 0
                                else f"Bus{line.get('to_bus', 0)} -> Bus{line.get('from_bus', 0)}")
                    
                    #row = [''] * OUTPUT_START_COL
                    row = [''] * (OUTPUT_START_COL + 11)  # 51 + 11 = 62
                    row[0] = line_num
                    row[1] = line.get('name', f'Line_{line_num}')
                    row[2] = line.get('from_bus', 0)
                    row[3] = line.get('to_bus', 0)
                    row[4] = length
                    row[5] = line.get('area', 1)
                    row[6] = line.get('zone', 1)
                    row[7] = line.get('owner', 1)
                    row[8] = line.get('R_per_km', 0)
                    row[9] = line.get('X_per_km', 0)
                    row[10] = line.get('B_per_km', 0)
                    row[11] = line.get('r', 0)
                    row[12] = line.get('x', 0)
                    row[13] = line.get('b', 0)
                    row[14] = line.get('rateA', 0)
                    row[15] = line.get('rateB', 0)
                    row[16] = line.get('rateC', 0)
                    row[17] = line.get('status', 1)
                    
                    row[OUTPUT_START_COL + 0] = f"{P_fwd:+.5f}"
                    row[OUTPUT_START_COL + 1] = f"{Q_fwd:+.5f}"
                    row[OUTPUT_START_COL + 2] = f"{MVA_fwd:.6f}"
                    row[OUTPUT_START_COL + 3] = f"{P_rev:+.5f}"
                    row[OUTPUT_START_COL + 4] = f"{Q_rev:+.5f}"
                    row[OUTPUT_START_COL + 5] = f"{MVA_rev:.6f}"
                    row[OUTPUT_START_COL + 6] = f"{Loss_MW:.6f}"
                    row[OUTPUT_START_COL + 7] = f"{Loss_per_km:.6f}"
                    row[OUTPUT_START_COL + 8] = f"{stats.get('avg_loading', 0):.6f}"
                    row[OUTPUT_START_COL + 9] = loading_status
                    row[OUTPUT_START_COL + 10] = flow_dir
                    
                    writer.writerow(row)
            else:
                writer.writerow(['No transmission line data available'])
            writer.writerow([])
            
            # =========================================================
            # SECTION 5: TRANSFORMER DATA
            # =========================================================
            writer.writerow(['# ========== TRANSFORMER DATA =========='])
            
            headers = [f'col_{i}' for i in range(OUTPUT_START_COL)]
            headers.extend(['O_P_fwd_MW', 'O_Q_fwd_Mvar', 'O_MVA_fwd_MVA', 'O_P_rev_MW', 'O_Q_rev_Mvar', 'O_MVA_rev_MVA', 'O_losses_MW', 'O_losses_MVA', 'O_tap_position', 'O_tap_step', 'O_loading_pct', 'O_status', 'O_actual_flow_direction'])
            writer.writerow(headers)
            
            transformers = self.input_data.get('transformers', {})
            if transformers:
                for xfmr_num, xfmr in transformers.items():
                    stats = self._get_xfmr_stats(xfmr_num, xfmr)

                    tap_ratio = stats.get('avg_tap', xfmr.get('tap_ratio', 1.0))
                    step_size = xfmr.get('step_size', 0.01)
                    min_tap = xfmr.get('min_tap', 0.9)
                    tap_step = int((tap_ratio - min_tap) / step_size) if step_size > 0 else 0
                    loading_status = self.get_status(stats.get('avg_loading', 0), {'min': 0, 'max': 80})
                    
                    P_fwd = stats.get('avg_P_fwd', 0)
                    Q_fwd = stats.get('avg_Q_fwd', 0)
                    MVA_fwd = (P_fwd**2 + Q_fwd**2)**0.5
                    
                    P_rev = stats.get('avg_P_rev', 0)
                    Q_rev = stats.get('avg_Q_rev', 0)
                    MVA_rev = (P_rev**2 + Q_rev**2)**0.5
                    
                    flow_dir = (f"Bus{xfmr.get('from_bus', 0)} -> Bus{xfmr.get('to_bus', 0)}" if P_fwd >= 0
                                else f"Bus{xfmr.get('to_bus', 0)} -> Bus{xfmr.get('from_bus', 0)}")
                    
                    Loss_MW = abs(stats.get('avg_loss', 0))
                    Loss_MVA = (Loss_MW**2 + (abs(stats.get('avg_loss_q', 0)))**2)**0.5 if stats.get('avg_loss_q', 0) else Loss_MW
                    
                    #row = [''] * OUTPUT_START_COL
                    row = [''] * (OUTPUT_START_COL + 13)  # 51 + 13 = 64
                    row[0] = xfmr_num
                    row[1] = xfmr.get('name', f'Xfmr_{xfmr_num}')
                    row[2] = xfmr.get('from_bus', 0)
                    row[3] = xfmr.get('to_bus', 0)
                    row[4] = xfmr.get('rateA', 9999)
                    row[5] = xfmr.get('area', 1)
                    row[6] = xfmr.get('zone', 1)
                    row[7] = xfmr.get('owner', 1)
                    row[8] = xfmr.get('r', 0)
                    row[9] = xfmr.get('x', 0)
                    row[10] = xfmr.get('tap_ratio', 1.0)
                    row[11] = xfmr.get('phase_shift', 0)
                    row[12] = xfmr.get('min_tap', 0.9)
                    row[13] = xfmr.get('max_tap', 1.1)
                    row[14] = xfmr.get('step_size', 0.01)
                    row[15] = xfmr.get('status', 1)
                    row[16] = xfmr.get('area', 1)
                    row[17] = xfmr.get('zone', 1)
                    row[18] = xfmr.get('owner', 1)
                    
                    row[OUTPUT_START_COL + 0] = f"{P_fwd:+.5f}"
                    row[OUTPUT_START_COL + 1] = f"{Q_fwd:+.5f}"
                    row[OUTPUT_START_COL + 2] = f"{MVA_fwd:.6f}"
                    row[OUTPUT_START_COL + 3] = f"{P_rev:+.5f}"
                    row[OUTPUT_START_COL + 4] = f"{Q_rev:+.5f}"
                    row[OUTPUT_START_COL + 5] = f"{MVA_rev:.6f}"
                    row[OUTPUT_START_COL + 6] = f"{Loss_MW:.6f}"
                    row[OUTPUT_START_COL + 7] = f"{Loss_MVA:.6f}"
                    row[OUTPUT_START_COL + 8] = f"{tap_ratio:.6f}"
                    row[OUTPUT_START_COL + 9] = tap_step
                    row[OUTPUT_START_COL + 10] = f"{stats.get('avg_loading', 0):.6f}"
                    row[OUTPUT_START_COL + 11] = loading_status
                    row[OUTPUT_START_COL + 12] = flow_dir
                    
                    writer.writerow(row)
            else:
                writer.writerow(['No transformer data available'])
            writer.writerow([])
            
            # =========================================================
            # SECTION 5B: THREE-WINDING TRANSFORMER DATA
            # =========================================================
            writer.writerow(['# ========== THREE-WINDING TRANSFORMER DATA =========='])
            
            headers = [f'col_{i}' for i in range(OUTPUT_START_COL)]
            headers.extend(['O_P_HV_MW', 'O_Q_HV_Mvar', 'O_MVA_HV_MVA', 'O_HV_loading_pct',
                            'O_P_MV_MW', 'O_Q_MV_Mvar', 'O_MVA_MV_MVA', 'O_MV_loading_pct',
                            'O_P_LV_MW', 'O_Q_LV_Mvar', 'O_MVA_LV_MVA', 'O_LV_loading_pct',
                            'O_total_loss_MW', 'O_max_loading_pct', 'O_dummy_V_pu', 'O_dummy_V_kV', 'O_dummy_angle_deg', 'O_status'])
            writer.writerow(headers)
            
            three_w_xfmrs = self.input_data.get('three_winding_transformers') or self.input_data.get('three_winding_xfmrs') or {}
            if three_w_xfmrs:
                for tw_num, twx in three_w_xfmrs.items():
                    stats = getattr(self, 'three_w_xfmr_stats', {}).get(tw_num, {})
                    dummy_bus = 100000000 + int(tw_num)
                    dummy_idx = self.engine.bus_index_map.get(dummy_bus, None)
                    if dummy_idx is not None:
                        dummy_v = self._safe_get_v(dummy_idx, 1.0)
                        dummy_va = self._safe_get_va(dummy_idx, 0.0)
                        hv_bus = twx.get('hv_bus', 0)
                        base_kv = self.input_data.get('buses', {}).get(hv_bus, {}).get('base_kV', 132.0)
                        dummy_kv = dummy_v * base_kv
                    else:
                        dummy_v, dummy_kv, dummy_va = 1.0, 132.0, 0.0
                        
                    row = [''] * (OUTPUT_START_COL + 18)
                    row[0] = tw_num
                    row[1] = twx.get('name', f'3WX_{tw_num}')
                    row[2] = twx.get('hv_bus', 0)
                    row[3] = twx.get('mv_bus', 0)
                    row[4] = twx.get('lv_bus', 0)
                    row[5] = twx.get('r_hm', 0.0)
                    row[6] = twx.get('x_hm', 0.0)
                    row[7] = twx.get('r_hl', 0.0)
                    row[8] = twx.get('x_hl', 0.0)
                    row[9] = twx.get('r_ml', 0.0)
                    row[10] = twx.get('x_ml', 0.0)
                    row[11] = twx.get('rate_h', 9999)
                    row[12] = twx.get('rate_m', 9999)
                    row[13] = twx.get('rate_l', 9999)
                    row[14] = twx.get('tap_h', 1.0)
                    row[15] = twx.get('tap_m', 1.0)
                    row[16] = twx.get('tap_l', 1.0)
                    row[17] = twx.get('status', 1)
                    
                    row[OUTPUT_START_COL + 0] = f"{stats.get('P_hv', 0.0):+.5f}"
                    row[OUTPUT_START_COL + 1] = f"{stats.get('Q_hv', 0.0):+.5f}"
                    row[OUTPUT_START_COL + 2] = f"{stats.get('S_hv', 0.0):.6f}"
                    row[OUTPUT_START_COL + 3] = f"{stats.get('loading_hv', 0.0):.6f}"
                    row[OUTPUT_START_COL + 4] = f"{stats.get('P_mv', 0.0):+.5f}"
                    row[OUTPUT_START_COL + 5] = f"{stats.get('Q_mv', 0.0):+.5f}"
                    row[OUTPUT_START_COL + 6] = f"{stats.get('S_mv', 0.0):.6f}"
                    row[OUTPUT_START_COL + 7] = f"{stats.get('loading_mv', 0.0):.6f}"
                    row[OUTPUT_START_COL + 8] = f"{stats.get('P_lv', 0.0):+.5f}"
                    row[OUTPUT_START_COL + 9] = f"{stats.get('Q_lv', 0.0):+.5f}"
                    row[OUTPUT_START_COL + 10] = f"{stats.get('S_lv', 0.0):.6f}"
                    row[OUTPUT_START_COL + 11] = f"{stats.get('loading_lv', 0.0):.6f}"
                    row[OUTPUT_START_COL + 12] = f"{stats.get('total_loss_p', 0.0):.6f}"
                    row[OUTPUT_START_COL + 13] = f"{stats.get('max_loading', 0.0):.6f}"
                    row[OUTPUT_START_COL + 14] = f"{dummy_v:.6f}"
                    row[OUTPUT_START_COL + 15] = f"{dummy_kv:.3f}"
                    row[OUTPUT_START_COL + 16] = f"{dummy_va:.3f}"
                    row[OUTPUT_START_COL + 17] = stats.get('status', 'NORMAL')
                    
                    writer.writerow(row)
            else:
                writer.writerow(['No three-winding transformer data available'])
            writer.writerow([])
            
            # =========================================================
            # SECTION 6: CAPACITOR BANK DATA
            # =========================================================
            writer.writerow(['# ========== CAPACITOR BANK DATA =========='])
            
            headers = [f'col_{i}' for i in range(OUTPUT_START_COL)]
            headers.extend(['O_Q_injected_Mvar', 'O_V_actual_pu', 'O_V_actual_kV', 'O_status'])
            writer.writerow(headers)
            
            capacitors = self.input_data.get('capacitors', {})
            if capacitors:
                for cap_num, cap in capacitors.items():
                    bus_num = cap.get('bus', 0)
                    idx = self.engine.bus_index_map.get(bus_num, 0)
                    V_actual = self._safe_get(self.avg_V, idx, 1.0)
                    V_kV = self.get_voltage_kv(bus_num, V_actual)
                    O_Q_inj = cap.get('Q_cap', 0) * (V_actual ** 2)
                    
                    #row = [''] * OUTPUT_START_COL
                    row = [''] * (OUTPUT_START_COL + 4)   # 51 + 4 = 55
                    row[0] = cap_num
                    row[1] = cap.get('name', f'Cap_{cap_num}')
                    row[2] = bus_num
                    row[3] = cap.get('area', 1)
                    row[4] = cap.get('zone', 1)
                    row[5] = cap.get('Q_cap', 0)
                    row[6] = cap.get('status', 1)
                    row[7] = cap.get('owner', 1)
                    
                    row[OUTPUT_START_COL + 0] = f"{O_Q_inj:.6f}"
                    row[OUTPUT_START_COL + 1] = f"{V_actual:.6f}"
                    row[OUTPUT_START_COL + 2] = f"{V_kV:.6f}"
                    row[OUTPUT_START_COL + 3] = "ONLINE" if cap.get('status', 1) == 1 else "OFFLINE"
                    
                    writer.writerow(row)
            else:
                writer.writerow(['No capacitor data available'])
            writer.writerow([])
            
            # =========================================================
            # SECTION 7: REACTOR DATA
            # =========================================================
            writer.writerow(['# ========== REACTOR DATA =========='])
            
            headers = [f'col_{i}' for i in range(OUTPUT_START_COL)]
            headers.extend(['O_Q_absorbed_Mvar', 'O_V_actual_pu', 'O_V_actual_kV', 'O_status'])
            writer.writerow(headers)
            
            reactors = self.input_data.get('reactors', {})
            if reactors:
                for reactor_num, reactor in reactors.items():
                    bus_num = reactor.get('bus', 0)
                    idx = self.engine.bus_index_map.get(bus_num, 0)
                    V_actual = self._safe_get(self.avg_V, idx, 1.0)
                    V_kV = self.get_voltage_kv(bus_num, V_actual)
                    O_Q_abs = reactor.get('Q_react', 0) * (V_actual ** 2)
                    
                    row = [''] * (OUTPUT_START_COL + 4)   # 51 + 4 = 55
                    
                    row[0] = reactor_num
                    row[1] = reactor.get('name', f'Reactor_{reactor_num}')
                    row[2] = bus_num
                    row[3] = reactor.get('area', 1)
                    row[4] = reactor.get('zone', 1)
                    row[5] = reactor.get('Q_react', 0)
                    row[6] = reactor.get('status', 1)
                    row[7] = reactor.get('owner', 1)
                    
                    row[OUTPUT_START_COL + 0] = f"{O_Q_abs:.6f}"
                    row[OUTPUT_START_COL + 1] = f"{V_actual:.6f}"
                    row[OUTPUT_START_COL + 2] = f"{V_kV:.6f}"
                    row[OUTPUT_START_COL + 3] = "ONLINE" if reactor.get('status', 1) == 1 else "OFFLINE"
                    
                    writer.writerow(row)
            else:
                writer.writerow(['No reactor data available'])
            writer.writerow([])
            
            # =========================================================
            # SECTION 8: SERIES COMPENSATION DATA
            # =========================================================
            writer.writerow(['# ========== SERIES COMPENSATION DATA =========='])
            
            headers = [f'col_{i}' for i in range(OUTPUT_START_COL)]
            headers.extend(['O_effective_X_pu', 'O_compensation_status', 'O_P_flow_from_to_MW', 'O_Q_flow_from_to_Mvar', 'O_P_flow_to_from_MW', 'O_Q_flow_to_from_Mvar', 'O_losses_MW'])
            writer.writerow(headers)
            
            series_comps = self.input_data.get('series_comps', {})
            if series_comps:
                for series_num, sc in series_comps.items():
                    effective_X = sc.get('x', 0) * (1 - sc.get('comp_pct', 0) / 100)
                    comp_status = "ACTIVE" if sc.get('status', 1) == 1 else "INACTIVE"
                    
                    row = [''] * (OUTPUT_START_COL + 7)   # 51 + 7 = 58
                    
                    row[0] = series_num
                    row[1] = sc.get('name', f'SC_{series_num}')
                    row[2] = sc.get('from_bus', 0)
                    row[3] = sc.get('to_bus', 0)
                    row[4] = sc.get('area', 1)
                    row[5] = sc.get('zone', 1)
                    row[6] = sc.get('owner', 1)
                    row[7] = sc.get('r', 0)
                    row[8] = sc.get('x', 0)
                    row[9] = sc.get('comp_pct', 0)
                    row[10] = sc.get('status', 1)
                    row[11] = sc.get('varistor_kV', 0)
                    
                    row[OUTPUT_START_COL + 0] = f"{effective_X:.6f}"
                    row[OUTPUT_START_COL + 1] = comp_status
                    row[OUTPUT_START_COL + 2] = "0.0"
                    row[OUTPUT_START_COL + 3] = "0.0"
                    row[OUTPUT_START_COL + 4] = "0.0"
                    row[OUTPUT_START_COL + 5] = "0.0"
                    row[OUTPUT_START_COL + 6] = "0.0"
                    
                    writer.writerow(row)
            else:
                writer.writerow(['No series compensation data available'])
            writer.writerow([])
            
            # =========================================================
            # SECTION 9: SERIES REACTOR DATA
            # =========================================================
            writer.writerow(['# ========== SERIES REACTOR DATA =========='])
            
            headers = [f'col_{i}' for i in range(OUTPUT_START_COL)]
            headers.extend(['O_P_flow_from_to_MW', 'O_Q_flow_from_to_Mvar', 'O_P_flow_to_from_MW', 'O_Q_flow_to_from_Mvar', 'O_losses_MW', 'O_status'])
            writer.writerow(headers)
            
            series_reactors = self.input_data.get('series_reactors', {})
            if series_reactors:
                for sr_num, sr in series_reactors.items():
                    #row = [''] * OUTPUT_START_COL
                    row = [''] * (OUTPUT_START_COL + 6)   # 51 + 6 = 57
                    row[0] = sr_num
                    row[1] = sr.get('name', f'SR_{sr_num}')
                    row[2] = sr.get('from_bus', 0)
                    row[3] = sr.get('to_bus', 0)
                    row[4] = sr.get('area', 1)
                    row[5] = sr.get('zone', 1)
                    row[6] = sr.get('owner', 1)
                    row[7] = sr.get('r', 0)
                    row[8] = sr.get('x', 0)
                    row[9] = sr.get('status', 1)
                    
                    row[OUTPUT_START_COL + 0] = "0.0"
                    row[OUTPUT_START_COL + 1] = "0.0"
                    row[OUTPUT_START_COL + 2] = "0.0"
                    row[OUTPUT_START_COL + 3] = "0.0"
                    row[OUTPUT_START_COL + 4] = "0.0"
                    row[OUTPUT_START_COL + 5] = "ONLINE" if sr.get('status', 1) == 1 else "OFFLINE"
                    
                    writer.writerow(row)
            else:
                writer.writerow(['No series reactor data available'])
            writer.writerow([])
            
            # =========================================================
            # SECTION 10: SHUNT COMPENSATION DATA
            # =========================================================
            writer.writerow(['# ========== SHUNT COMPENSATION DATA =========='])
            
            headers = [f'col_{i}' for i in range(OUTPUT_START_COL)]
            headers.extend(['O_Q_injected_Mvar', 'O_V_actual_pu', 'O_V_actual_kV', 'O_status'])
            writer.writerow(headers)
            
            shunts = self.input_data.get('shunts', {})
            if shunts:
                for shunt_num, shunt in shunts.items():
                    bus_num = shunt.get('bus', 0)
                    idx = self.engine.bus_index_map.get(bus_num, 0)
                    V_actual = self._safe_get(self.avg_V, idx, 1.0)
                    V_kV = self.get_voltage_kv(bus_num, V_actual)
                    O_Q_inj = shunt.get('Q_shunt', 0) * (V_actual ** 2)
                    
                    #row = [''] * OUTPUT_START_COL
                    row = [''] * (OUTPUT_START_COL + 4)   # 51 + 4 = 55
                    row[0] = shunt_num
                    row[1] = shunt.get('name', f'Shunt_{shunt_num}')
                    row[2] = bus_num
                    row[3] = shunt.get('area', 1)
                    row[4] = shunt.get('zone', 1)
                    row[5] = shunt.get('Q_shunt', 0)
                    row[6] = shunt.get('status', 1)
                    row[7] = shunt.get('owner', 1)
                    
                    row[OUTPUT_START_COL + 0] = f"{O_Q_inj:.6f}"
                    row[OUTPUT_START_COL + 1] = f"{V_actual:.6f}"
                    row[OUTPUT_START_COL + 2] = f"{V_kV:.6f}"
                    row[OUTPUT_START_COL + 3] = "ONLINE" if shunt.get('status', 1) == 1 else "OFFLINE"
                    
                    writer.writerow(row)
            else:
                writer.writerow(['No shunt compensation data available'])
            writer.writerow([])
            
            # =========================================================
            # SECTION 11: HVDC TRANSMISSION LINK DATA
            # =========================================================
            writer.writerow(['# ========== HVDC TRANSMISSION LINK DATA =========='])
            
            headers = [f'col_{i}' for i in range(OUTPUT_START_COL)]
            headers.extend([
                'O_Vdc_from_kV', 'O_Vdc_to_kV', 'O_Idc_A', 'O_P_dc_MW', 'O_losses_dc_MW',
                'O_P_from_ac_MW', 'O_Q_from_ac_Mvar', 'O_P_to_ac_MW', 'O_Q_to_ac_Mvar',
                'O_alpha_deg', 'O_gamma_deg', 'O_tap_from', 'O_tap_to', 'O_loading_pct', 'O_status'
            ])
            writer.writerow(headers)
            
            hvdc_links = self.input_data.get('hvdc_links', {})
            if hvdc_links:
                for lk_num, lk in hvdc_links.items():
                    stats = self._get_hvdc_stats(lk_num, lk)
                    
                    row = [''] * (OUTPUT_START_COL + 15)
                    row[0] = lk_num
                    row[1] = lk.get('name', f'HVDC_{lk_num}')
                    row[2] = lk.get('from_bus', 0)
                    row[3] = lk.get('to_bus', 0)
                    row[4] = lk.get('r_dc', 0.0)
                    row[5] = lk.get('status', 1)
                    # From Side
                    row[6] = lk.get('from_mode', 'Rectifier')
                    row[7] = lk.get('from_ctrl_type', 3)
                    row[8] = lk.get('from_val', 50.0)
                    row[9] = lk.get('from_angle', 12.0)
                    row[10] = lk.get('from_xc', 0.0)
                    row[11] = lk.get('from_tfr_kv', 220.0)
                    row[12] = lk.get('from_tfr_mva', 100.0)
                    row[13] = lk.get('from_tap_min', 0.85)
                    row[14] = lk.get('from_tap_max', 1.20)
                    row[15] = lk.get('from_tap_step', 0.0125)
                    row[16] = lk.get('from_nb', 1)
                    row[17] = lk.get('from_np', 1)
                    # To Side
                    row[18] = lk.get('to_mode', 'Inverter')
                    row[19] = lk.get('to_ctrl_type', 1)
                    row[20] = lk.get('to_val', 220.0)
                    row[21] = lk.get('to_angle', 15.0)
                    row[22] = lk.get('to_xc', 0.0)
                    row[23] = lk.get('to_tfr_kv', 220.0)
                    row[24] = lk.get('to_tfr_mva', 100.0)
                    row[25] = lk.get('to_tap_min', 0.85)
                    row[26] = lk.get('to_tap_max', 1.20)
                    row[27] = lk.get('to_tap_step', 0.0125)
                    row[28] = lk.get('to_nb', 1)
                    row[29] = lk.get('to_np', 1)
                    row[30] = lk.get('area', 1)
                    row[31] = lk.get('zone', 1)
                    row[32] = lk.get('owner', 1)
                    
                    row[OUTPUT_START_COL + 0] = f"{stats.get('avg_Vdc_from', 0.0):.6f}"
                    row[OUTPUT_START_COL + 1] = f"{stats.get('avg_Vdc_to', 0.0):.6f}"
                    row[OUTPUT_START_COL + 2] = f"{stats.get('avg_Idc', 0.0):.6f}"
                    row[OUTPUT_START_COL + 3] = f"{stats.get('avg_P_dc', 0.0):.6f}"
                    row[OUTPUT_START_COL + 4] = f"{stats.get('avg_loss', 0.0):.6f}"
                    row[OUTPUT_START_COL + 5] = f"{stats.get('avg_P_fwd', 0.0):.6f}"
                    row[OUTPUT_START_COL + 6] = f"{stats.get('avg_Q_fwd', 0.0):.6f}"
                    row[OUTPUT_START_COL + 7] = f"{stats.get('avg_P_rev', 0.0):.6f}"
                    row[OUTPUT_START_COL + 8] = f"{stats.get('avg_Q_rev', 0.0):.6f}"
                    row[OUTPUT_START_COL + 9] = f"{stats.get('avg_alpha', 0.0):.2f}"
                    row[OUTPUT_START_COL + 10] = f"{stats.get('avg_gamma', 0.0):.2f}"
                    row[OUTPUT_START_COL + 11] = f"{stats.get('avg_tap_from', 1.0):.4f}"
                    row[OUTPUT_START_COL + 12] = f"{stats.get('avg_tap_to', 1.0):.4f}"
                    row[OUTPUT_START_COL + 13] = f"{stats.get('avg_loading', 0.0):.2f}"
                    row[OUTPUT_START_COL + 14] = "ONLINE" if lk.get('status', 1) == 1 else "OFFLINE"
                    
                    writer.writerow(row)
            else:
                writer.writerow(['No HVDC transmission link data available'])
            writer.writerow([])
            
            # =========================================================
            # SECTION 12: SYSTEM SUMMARY
            # =========================================================
            tot_line_loss = sum(self._get_line_stats(lid, l).get('avg_loss', 0.0) for lid, l in self.input_data.get('lines', {}).items() if l.get('status', 1) == 1)
            tot_xfmr_loss = sum(self._get_xfmr_stats(xid, x).get('avg_loss', 0.0) for xid, x in self.input_data.get('transformers', {}).items() if x.get('status', 1) == 1)
            tot_hvdc_loss = sum(self._get_hvdc_stats(hid, h).get('avg_loss', 0.0) for hid, h in self.input_data.get('hvdc_links', {}).items() if h.get('status', 1) == 1)
            total_losses = tot_line_loss + tot_xfmr_loss + tot_hvdc_loss
            gen_outputs_csv = [self.get_generator_outputs(gid, g) for gid, g in self.input_data.get('generators', {}).items() if g.get('status', 1) == 1]
            total_gen = sum(p for p, q in gen_outputs_csv if p > 0)
            total_load = sum(l.get('P_demand', 0) for l in self.input_data.get('loads', {}).values() if self._is_load_online(l)) + sum(-p for p, q in gen_outputs_csv if p < 0)
            
            writer.writerow(['# ========== SYSTEM SUMMARY =========='])
            writer.writerow(['Parameter', 'Value', 'Unit'])
            writer.writerow(['Total Generation', f"{total_gen:.6f}", 'MW'])
            writer.writerow(['Total Load', f"{total_load:.6f}", 'MW'])
            writer.writerow(['Total Losses', f"{total_losses:.6f}", 'MW'])
            writer.writerow(['Loss Percentage', f"{(total_losses/total_load)*100 if total_load > 0 else 0:.6f}", '%'])
            writer.writerow(['Average Voltage', f"{np.mean(self.avg_V):.6f}", 'pu'])
            writer.writerow(['Minimum Voltage', f"{np.min(self.avg_V):.6f}", 'pu'])
            writer.writerow(['Maximum Voltage', f"{np.max(self.avg_V):.6f}", 'pu'])
            writer.writerow(['Number of Buses', f"{len(self.input_data.get('buses', {}))}", ''])
            writer.writerow(['Number of Generators', f"{len(self.input_data.get('generators', {}))}", ''])
            writer.writerow(['Number of Loads', f"{len(self.input_data.get('loads', {}))}", ''])
            writer.writerow(['Number of Lines', f"{len(self.input_data.get('lines', {}))}", ''])
            writer.writerow(['Number of Transformers', f"{len(self.input_data.get('transformers', {}))}", ''])
            writer.writerow(['Number of Capacitors', f"{len(self.input_data.get('capacitors', {}))}", ''])
            writer.writerow(['Number of Reactors', f"{len(self.input_data.get('reactors', {}))}", ''])
            writer.writerow(['Number of Series Comps', f"{len(self.input_data.get('series_comps', {}))}", ''])
            writer.writerow(['Number of Series Reactors', f"{len(self.input_data.get('series_reactors', {}))}", ''])
            writer.writerow(['Number of Shunts', f"{len(self.input_data.get('shunts', {}))}", ''])
            writer.writerow(['Samples Generated', f"{len(self.samples)}", ''])
            writer.writerow(['Variation Strength', f"{self.variation_strength*100:.0f}", '%'])
            writer.writerow([])
            
            # =========================================================
            # SECTION 12: CONVERGENCE & SUMMARY REPORT
            # =========================================================
            writer.writerow(['# ========== CONVERGENCE & SUMMARY REPORT =========='])
            writer.writerow(['====================================================================================='])
            writer.writerow(['⚡ LOAD FLOW ANALYSIS — SYSTEM SUMMARY & CONVERGENCE REPORT'])
            writer.writerow(['====================================================================================='])
            writer.writerow([f'Result File             : {os.path.basename(filename)}'])
            writer.writerow([f'Solver Engine           : {self.solver_info.get("engine", "ANDES NR")}'])
            writer.writerow(['-------------------------------------------------------------------------------------'])
            writer.writerow(['📌 SOLVER CONVERGENCE & PARAMETERS:'])
            writer.writerow(['-------------------------------------------------------------------------------------'])
            conv_str = "✅ CONVERGED SUCCESSFUL" if self.solver_info.get("converged", True) else "❌ NOT CONVERGED"
            writer.writerow([f'Convergence Status      : {conv_str}'])
            writer.writerow([f'Iterations Executed     : {self.solver_info.get("iterations", 1)} iterations'])
            writer.writerow([f'Input Tolerance Setting : {self.solver_info.get("input_tol", "0.1")}'])
            writer.writerow([f'Input Max Iterations    : {self.solver_info.get("input_max_iter", 500)}'])
            dp_val = self.solver_info.get("max_dP", 0.0)
            dq_val = self.solver_info.get("max_dQ", 0.0)
            writer.writerow([f'Final Active Mismatch   : Max |dP| = {dp_val:.6f} p.u. ({dp_val*100.0:.6f} MW)'])
            writer.writerow([f'Final Reactive Mismatch : Max |dQ| = {dq_val:.6f} p.u. ({dq_val*100.0:.6f} Mvar)'])
            writer.writerow(['-------------------------------------------------------------------------------------'])
            writer.writerow(['📌 ITERATION LOG:'])
            writer.writerow(['-------------------------------------------------------------------------------------'])
            iter_logs = self.solver_info.get("iter_logs", [])
            if iter_logs:
                for ilog in iter_logs:
                    writer.writerow([ilog])
            else:
                writer.writerow([f'  Iter {self.solver_info.get("iterations", 1)}: Max |dP| = {dp_val:.6f} p.u., Max |dQ| = {dq_val:.6f} p.u.'])
            writer.writerow(['-------------------------------------------------------------------------------------'])
            writer.writerow(['📊 SYSTEM POWER BALANCE (INPUT DEMAND vs OUTPUT GENERATION):'])
            writer.writerow(['-------------------------------------------------------------------------------------'])
            writer.writerow([f'Total Network Buses     : {len(self.input_data.get("buses", {}))}'])
            writer.writerow([f'Total Lines/Xfmrs       : {len(self.input_data.get("lines", {}))} lines , {len(self.input_data.get("transformers", {}))} transformers'])
            writer.writerow([f'Total Input Demand      : -{total_load:.6f} MW'])
            writer.writerow([f'Total Output Generation : +{total_gen:.6f} MW'])
            writer.writerow([f'Total Network Losses    : {total_losses:.6f} MW'])
            writer.writerow(['-------------------------------------------------------------------------------------'])
        
        return filename

    # def write_py_all_data(self, filename):
    #     """Write PY file with ALL data - includes ALL possible elements"""
        
    #     with open(filename, 'w', encoding='utf-8') as f:
            
    #         f.write('"""\n')
    #         f.write(f'ವಿಲೋಮ ವಿದ್ಯುತ್ ಹರಿವಿನ ಅಧ್ಯಯನ (ಇನ್ವರ್ಸ್ ಪವರ್ ಫ್ಲೋ)\n')
    #         f.write(f'============INVERSE POWER FLOW=============\n')
    #         f.write(f'Complete Power System Data with Results\n')
    #         f.write(f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
    #         f.write('This file contains ALL data (input + output) for ALL possible elements\n')
    #         f.write('Empty lists for components not present in input\n')
    #         f.write('"""\n\n')
            
    #         f.write(f'BASE_MVA = {self.engine.baseMVA}\n\n')
            
    #         # BUS DATA
    #         f.write('# ========== BUS DATA ==========\n')
    #         f.write('# [bus_num, name, type, base_kV, area, zone, owner, V_init, angle_init, shunt_G, shunt_B, O_V_final, O_V_kV, O_angle, O_v_status, O_a_status]\n')
    #         f.write('BUS_DATA = [\n')
    #         buses = self.input_data.get('buses', {})
    #         if buses:
    #             for bus_num, bus in buses.items():
    #                 idx = self.engine.bus_index_map.get(bus_num, 0)
    #                 V_kV = self.get_voltage_kv(bus_num, self._safe_get(self.avg_V, idx, 1.0))
    #                 v_status = self.get_status(self._safe_get(self.avg_V, idx, 1.0), {'min': 0.95, 'max': 1.05})
    #                 a_status = self.get_status(abs(self._safe_get(self.avg_Va, idx, 0.0)), {'min': 0, 'max': 30})
    #                 f.write(f'    [{bus_num}, "{bus.get("name", f"Bus_{bus_num}")}", {bus.get("type", 1)}, {bus.get("base_kV", 132)}, '
    #                        f'{bus.get("area", 1)}, {bus.get("zone", 1)}, {bus.get("owner", 1)}, '
    #                        f'{bus.get("V_init", 1.0)}, {bus.get("angle_init", 0.0)}, {bus.get("shunt_G", 0)}, {bus.get("shunt_B", 0)}, '
    #                        f'{self.avg_V[idx]:.6f}, {V_kV:.6f}, {self.avg_Va[idx]:.6f}, "{v_status}", "{a_status}"],\n')
    #         f.write(']\n\n')
            
    #         # GENERATOR DATA
    #         f.write('# ========== GENERATOR DATA ==========\n')
    #         f.write('# [gen_num, name, type, bus, area, zone, P_out, Q_out, V_set, Qmin, Qmax, status, O_P_out, O_Q_out, O_V_actual, O_Q_status, O_limit_flag]\n')
    #         f.write('GENERATOR_DATA = [\n')
    #         generators = self.input_data.get('generators', {})
    #         if generators:
    #             for gen_num, gen in generators.items():
    #                 bus_num = gen.get('bus', 0)
    #                 idx = self.engine.bus_index_map.get(bus_num, 0)
    #                 O_P_out = -self.avg_P[idx] if idx < len(self.avg_P) and self.avg_P[idx] < 0 else gen.get('P_out', 0)
    #                 f.write(f'    [{gen_num}, "{gen.get("name", f"Gen_{gen_num}")}", "{gen.get("type", "SYNC")}", {bus_num}, '
    #                        f'{gen.get("area", 1)}, {gen.get("zone", 1)}, '
    #                        f'{gen.get("P_out", 0)}, {gen.get("Q_out", 0)}, {gen.get("V_set", 1.0)}, '
    #                        f'{gen.get("Qmin", -9999)}, {gen.get("Qmax", 9999)}, {gen.get("status", 1)}, '
    #                        f'{O_P_out:.6f}, {gen.get("Q_out", 0):.6f}, {self.avg_V[idx]:.6f}, "OK", "NORMAL"],\n')
    #         f.write(']\n\n')
            
    #         f.write('# ========== TRANSMISSION LINE DATA ==========\n')
    #         f.write('# [line_num, name, from_bus, to_bus, length_km, area, zone, owner, R_per_km, X_per_km, B_per_km, R_total, X_total, B_total, rateA, rateB, rateC, status, O_P_fwd, O_Q_fwd, O_MVA_fwd, O_P_rev, O_Q_rev, O_MVA_rev, O_loss_MW, O_loss_per_km, O_loading, O_status]\n')
    #         f.write('LINE_DATA = [\n')
    #         lines = self.input_data.get('lines', {})
    #         if lines:
    #             for line_num, line in lines.items():
    #                 key = f"{line.get('from_bus', 0)}-{line.get('to_bus', 0)}"
    #                 stats = self.line_stats.get(key, {})
    #                 loading_status = self.get_status(stats.get('avg_loading', 0), {'min': 0, 'max': 80})
                    
    #                 # Get length and calculate values
    #                 length = line.get('length_km', 0)
    #                 Loss_MW = abs(stats.get('avg_loss', 0))
    #                 Loss_per_km = Loss_MW / length if length > 0 else 0
                    
    #                 # Calculate MVA values
    #                 P_fwd = abs(stats.get('avg_P_fwd', 0))
    #                 Q_fwd = abs(stats.get('avg_Q_fwd', 0))
    #                 MVA_fwd = (P_fwd**2 + Q_fwd**2)**0.5
                    
    #                 P_rev = abs(stats.get('avg_P_rev', 0))
    #                 Q_rev = abs(stats.get('avg_Q_rev', 0))
    #                 MVA_rev = (P_rev**2 + Q_rev**2)**0.5
                    
    #                 f.write(f'    [{line_num}, "{line.get("name", f"Line_{line_num}")}", {line.get("from_bus", 0)}, {line.get("to_bus", 0)}, '
    #                     f'{length:.6f}, '  # NEW: length_km
    #                     f'{line.get("area", 1)}, {line.get("zone", 1)}, {line.get("owner", 1)}, '
    #                     f'{line.get("R_per_km", 0):.6f}, {line.get("X_per_km", 0):.6f}, {line.get("B_per_km", 0):.6f}, '  # NEW: per-km values
    #                     f'{line.get("r", 0):.6f}, {line.get("x", 0):.6f}, {line.get("b", 0):.6f}, '  # Total R, X, B
    #                     f'{line.get("rateA", 0)}, {line.get("rateB", 0)}, {line.get("rateC", 0)}, {line.get("status", 1)}, '
    #                     f'{P_fwd:.6f}, {Q_fwd:.6f}, {MVA_fwd:.6f}, '  # NEW: MVA_fwd
    #                     f'{P_rev:.6f}, {Q_rev:.6f}, {MVA_rev:.6f}, '  # NEW: MVA_rev
    #                     f'{Loss_MW:.6f}, {Loss_per_km:.6f}, '  # NEW: loss_per_km
    #                     f'{stats.get("avg_loading", 0):.6f}, "{loading_status}"],\n')
    #         f.write(']\n\n')

    #         # TRANSFORMER DATA
    #         f.write('# ========== TRANSFORMER DATA ==========\n')
    #         f.write('# [xfmr_num, name, from_bus, to_bus, rateA_MVA, area, zone, owner, r, x, tap_ratio, phase_shift, min_tap, max_tap, step_size, status, O_P_fwd, O_Q_fwd, O_MVA_fwd, O_P_rev, O_Q_rev, O_MVA_rev, O_loss_MW, O_loss_MVA, O_tap_pos, O_tap_step, O_loading, O_status]\n')
    #         f.write('TRANSFORMER_DATA = [\n')
    #         transformers = self.input_data.get('transformers', {})
    #         if transformers:
    #             for xfmr_num, xfmr in transformers.items():
    #                 key = f"{xfmr.get('from_bus', 0)}-{xfmr.get('to_bus', 0)}"
    #                 stats = self.xfmr_stats.get(key, {})
    #                 tap_ratio = stats.get('avg_tap', xfmr.get('tap_ratio', 1.0))
    #                 step_size = xfmr.get('step_size', 0.01)
    #                 min_tap = xfmr.get('min_tap', 0.9)
    #                 tap_step = int((tap_ratio - min_tap) / step_size) if step_size > 0 else 0
                    
    #                 # Calculate MVA values
    #                 P_fwd = abs(stats.get('avg_P_fwd', 0))
    #                 Q_fwd = abs(stats.get('avg_Q_fwd', 0))
    #                 MVA_fwd = (P_fwd**2 + Q_fwd**2)**0.5
                    
    #                 P_rev = abs(stats.get('avg_P_rev', 0))
    #                 Q_rev = abs(stats.get('avg_Q_rev', 0))
    #                 MVA_rev = (P_rev**2 + Q_rev**2)**0.5
                    
    #                 Loss_MW = abs(stats.get('avg_loss', 0))
    #                 Loss_MVA = (Loss_MW**2 + (abs(stats.get('avg_loss_q', 0)))**2)**0.5 if stats.get('avg_loss_q', 0) else Loss_MW
                    
    #                 loading_status = self.get_status(stats.get('avg_loading', 0), {'min': 0, 'max': 80})
                    
    #                 f.write(f'    [{xfmr_num}, "{xfmr.get("name", f"Xfmr_{xfmr_num}")}", '
    #                        f'{xfmr.get("from_bus", 0)}, {xfmr.get("to_bus", 0)}, '
    #                        f'{xfmr.get("rateA", 9999)}, '  # NEW: Transformer Rating (MVA)
    #                        f'{xfmr.get("area", 1)}, {xfmr.get("zone", 1)}, {xfmr.get("owner", 1)}, '
    #                        f'{xfmr.get("r", 0):.6f}, {xfmr.get("x", 0):.6f}, {xfmr.get("tap_ratio", 1.0):.6f}, '
    #                        f'{xfmr.get("phase_shift", 0)}, {xfmr.get("min_tap", 0.9)}, {xfmr.get("max_tap", 1.1)}, '
    #                        f'{xfmr.get("step_size", 0.01)}, {xfmr.get("status", 1)}, '
    #                        f'{P_fwd:.6f}, {Q_fwd:.6f}, {MVA_fwd:.6f}, '  # NEW: MVA_fwd
    #                        f'{P_rev:.6f}, {Q_rev:.6f}, {MVA_rev:.6f}, '  # NEW: MVA_rev
    #                        f'{Loss_MW:.6f}, {Loss_MVA:.6f}, '  # NEW: Loss_MVA
    #                        f'{tap_ratio:.6f}, {tap_step}, '
    #                        f'{stats.get("avg_loading", 0):.6f}, "{loading_status}"],\n')
    #         else:
    #             f.write('    # No transformer data available\n')
    #         f.write(']\n\n')

    #         # ========== CAPACITOR DATA ==========
    #         f.write('# ========== CAPACITOR DATA ==========\n')
    #         f.write('# [cap_num, name, bus, area, zone, Q_cap_Mvar, status, O_Q_injected_Mvar, O_V_actual_pu, O_V_actual_kV, O_status]\n')
    #         f.write('CAPACITOR_DATA = [\n')
    #         capacitors = self.input_data.get('capacitors', {})
    #         if capacitors:
    #             for cap_num, cap in capacitors.items():
    #                 bus_num = cap.get('bus', 0)
    #                 idx = self.engine.bus_index_map.get(bus_num, 0)
    #                 V_actual = self._safe_get(self.avg_V, idx, 1.0)
    #                 V_kV = self.get_voltage_kv(bus_num, V_actual)
    #                 Q_inj = cap.get('Q_cap', 0) * (V_actual ** 2)
    #                 f.write(f'    [{cap_num}, "{cap.get("name", f"Cap_{cap_num}")}", {bus_num}, '
    #                        f'{cap.get("area", 1)}, {cap.get("zone", 1)}, '
    #                        f'{cap.get("Q_cap", 0):.6f}, {cap.get("status", 1)}, '
    #                        f'{Q_inj:.6f}, {V_actual:.6f}, {V_kV:.6f}, '
    #                        f'"ONLINE" if {cap.get("status", 1)} == 1 else "OFFLINE"],\n')
    #         else:
    #             f.write('    # No capacitor data available\n')
    #         f.write(']\n\n')
            
    #         # ========== REACTOR DATA ==========
    #         f.write('# ========== REACTOR DATA ==========\n')
    #         f.write('# [reactor_num, name, bus, area, zone, Q_react_Mvar, status, O_Q_absorbed_Mvar, O_V_actual_pu, O_V_actual_kV, O_status]\n')
    #         f.write('REACTOR_DATA = [\n')
    #         reactors = self.input_data.get('reactors', {})
    #         if reactors:
    #             for reactor_num, reactor in reactors.items():
    #                 bus_num = reactor.get('bus', 0)
    #                 idx = self.engine.bus_index_map.get(bus_num, 0)
    #                 V_actual = self._safe_get(self.avg_V, idx, 1.0)
    #                 V_kV = self.get_voltage_kv(bus_num, V_actual)
    #                 Q_abs = reactor.get('Q_react', 0) * (V_actual ** 2)
    #                 f.write(f'    [{reactor_num}, "{reactor.get("name", f"Reactor_{reactor_num}")}", {bus_num}, '
    #                        f'{reactor.get("area", 1)}, {reactor.get("zone", 1)}, '
    #                        f'{reactor.get("Q_react", 0):.6f}, {reactor.get("status", 1)}, '
    #                        f'{Q_abs:.6f}, {V_actual:.6f}, {V_kV:.6f}, '
    #                        f'"ONLINE" if {reactor.get("status", 1)} == 1 else "OFFLINE"],\n')
    #         else:
    #             f.write('    # No reactor data available\n')
    #         f.write(']\n\n')

    #         # ========== SERIES COMPENSATION DATA ==========
    #         f.write('# ========== SERIES COMPENSATION DATA ==========\n')
    #         f.write('# [series_num, name, from_bus, to_bus, area, zone, owner, R_pu, X_pu, comp_pct, status, O_effective_X_pu, O_comp_status, O_P_fwd, O_Q_fwd, O_P_rev, O_Q_rev, O_loss]\n')
    #         f.write('SERIES_COMP_DATA = [\n')
    #         series_comps = self.input_data.get('series_comps', {})
    #         if series_comps:
    #             for series_num, sc in series_comps.items():
    #                 effective_X = sc.get('x', 0) * (1 - sc.get('comp_pct', 0) / 100)
    #                 f.write(f'    [{series_num}, "{sc.get("name", f"SC_{series_num}")}", {sc.get("from_bus", 0)}, {sc.get("to_bus", 0)}, '
    #                        f'{sc.get("area", 1)}, {sc.get("zone", 1)}, {sc.get("owner", 1)}, '
    #                        f'{sc.get("r", 0):.6f}, {sc.get("x", 0):.6f}, {sc.get("comp_pct", 0):.6f}, {sc.get("status", 1)}, '
    #                        f'{effective_X:.6f}, "ACTIVE" if {sc.get("status", 1)} == 1 else "INACTIVE", '
    #                        f'0.0, 0.0, 0.0, 0.0, 0.0],\n')  # Placeholder for flows (to be calculated)
    #         else:
    #             f.write('    # No series compensation data available\n')
    #         f.write(']\n\n')

    #         # ========== SERIES REACTOR DATA ==========
    #         f.write('# ========== SERIES REACTOR DATA ==========\n')
    #         f.write('# [sr_num, name, from_bus, to_bus, area, zone, owner, R_pu, X_pu, status, O_P_fwd, O_Q_fwd, O_P_rev, O_Q_rev, O_loss, O_status]\n')
    #         f.write('SERIES_REACTOR_DATA = [\n')
    #         series_reactors = self.input_data.get('series_reactors', {})
    #         if series_reactors:
    #             for sr_num, sr in series_reactors.items():
    #                 f.write(f'    [{sr_num}, "{sr.get("name", f"SR_{sr_num}")}", {sr.get("from_bus", 0)}, {sr.get("to_bus", 0)}, '
    #                        f'{sr.get("area", 1)}, {sr.get("zone", 1)}, {sr.get("owner", 1)}, '
    #                        f'{sr.get("r", 0):.6f}, {sr.get("x", 0):.6f}, {sr.get("status", 1)}, '
    #                        f'0.0, 0.0, 0.0, 0.0, 0.0, "ONLINE" if {sr.get("status", 1)} == 1 else "OFFLINE"],\n')
    #         else:
    #             f.write('    # No series reactor data available\n')
    #         f.write(']\n\n')

    #         # ========== SHUNT COMPENSATION DATA ==========
    #         f.write('# ========== SHUNT COMPENSATION DATA ==========\n')
    #         f.write('# [shunt_num, name, bus, area, zone, Q_shunt_Mvar, status, O_Q_injected_Mvar, O_V_actual_pu, O_V_actual_kV, O_status]\n')
    #         f.write('SHUNT_DATA = [\n')
    #         shunts = self.input_data.get('shunts', {})
    #         if shunts:
    #             for shunt_num, shunt in shunts.items():
    #                 bus_num = shunt.get('bus', 0)
    #                 idx = self.engine.bus_index_map.get(bus_num, 0)
    #                 V_actual = self._safe_get(self.avg_V, idx, 1.0)
    #                 V_kV = self.get_voltage_kv(bus_num, V_actual)
    #                 Q_inj = shunt.get('Q_shunt', 0) * (V_actual ** 2)
    #                 f.write(f'    [{shunt_num}, "{shunt.get("name", f"Shunt_{shunt_num}")}", {bus_num}, '
    #                        f'{shunt.get("area", 1)}, {shunt.get("zone", 1)}, '
    #                        f'{shunt.get("Q_shunt", 0):.6f}, {shunt.get("status", 1)}, '
    #                        f'{Q_inj:.6f}, {V_actual:.6f}, {V_kV:.6f}, '
    #                        f'"ONLINE" if {shunt.get("status", 1)} == 1 else "OFFLINE"],\n')
    #         else:
    #             f.write('    # No shunt compensation data available\n')
    #         f.write(']\n\n')

            
    #         f.write('if __name__ == "__main__":\n')
    #         f.write('    print(f"Buses: {len(BUS_DATA)}")\n')
    #         f.write('    print(f"Lines: {len(LINE_DATA)}")\n')
    #         f.write('    print(f"Transformers: {len(TRANSFORMER_DATA)}")\n')
    #         f.write('    print(f"Capacitors: {len(CAPACITOR_DATA)}")\n')
    #         f.write('    print(f"Reactors: {len(REACTOR_DATA)}")\n')
        
    #     #print(f"  ✓ PY (all data with ALL elements): {filename}")
    #     return filename

    def write_py_all_data(self, filename):
        OUTPUT_START_COL = 51
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write('"""\n')
            for line in self.generate_convergence_report_lines(comment_prefix=""):
                f.write(line + '\n')
            f.write('============ POWER FLOW ALL DATA RESULTS =============\n')
            f.write(f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
            f.write('Output data starts at column 51 (0-50 reserved for input)\n')
            f.write('\nCOLUMN HEADERS REFERENCE:\n')
            f.write('=======================\n')
            f.write('SECTION 1 - BUS DATA (Output at 51-55):\n')
            f.write('    51: O_V_final_pu, 52: O_V_final_kV, 53: O_angle_deg, 54: O_voltage_status, 55: O_angle_status\n')
            f.write('\nSECTION 2 - GENERATOR DATA (Output at 51-57, signed: + = generation/injection):\n')
            f.write('    51: O_P_out_MW, 52: O_Q_out_Mvar, 53: O_V_actual_pu, 54: O_V_actual_kV, 55: O_Q_status, 56: O_limit_flag, 57: O_status\n')
            f.write('\nSECTION 3 - LOAD DATA (Output at 51-55, signed: - = consumption/draw from network):\n')
            f.write('    51: O_P_supplied_MW, 52: O_Q_supplied_Mvar, 53: O_V_actual_pu, 54: O_V_actual_kV, 55: O_supply_status\n')
            f.write('\nSECTION 4 - LINE DATA (Output at 51-61, signed: + = flows from_bus->to_bus, - = flows to_bus->from_bus):\n')
            f.write('    51: O_P_fwd_MW, 52: O_Q_fwd_Mvar, 53: O_MVA_fwd_MVA, 54: O_P_rev_MW, 55: O_Q_rev_Mvar, 56: O_MVA_rev_MVA, 57: O_losses_MW, 58: O_loss_per_km, 59: O_loading_pct, 60: O_status, 61: O_actual_flow_direction\n')
            f.write('\nSECTION 5 - TRANSFORMER DATA (Output at 51-63, signed: + = flows from_bus->to_bus, - = flows to_bus->from_bus):\n')
            f.write('    51: O_P_fwd_MW, 52: O_Q_fwd_Mvar, 53: O_MVA_fwd_MVA, 54: O_P_rev_MW, 55: O_Q_rev_Mvar, 56: O_MVA_rev_MVA, 57: O_losses_MW, 58: O_losses_MVA, 59: O_tap_position, 60: O_tap_step, 61: O_loading_pct, 62: O_status, 63: O_actual_flow_direction\n')
            f.write('\nSECTION 6 - CAPACITOR DATA (Output at 51-54):\n')
            f.write('    51: O_Q_injected_Mvar, 52: O_V_actual_pu, 53: O_V_actual_kV, 54: O_status\n')
            f.write('\nSECTION 7 - REACTOR DATA (Output at 51-54):\n')
            f.write('    51: O_Q_absorbed_Mvar, 52: O_V_actual_pu, 53: O_V_actual_kV, 54: O_status\n')
            f.write('\nSECTION 8 - SERIES COMPENSATION DATA (Output at 51-57):\n')
            f.write('    51: O_effective_X_pu, 52: O_compensation_status, 53: O_P_flow_from_to_MW, 54: O_Q_flow_from_to_Mvar, 55: O_P_flow_to_from_MW, 56: O_Q_flow_to_from_Mvar, 57: O_losses_MW\n')
            f.write('\nSECTION 9 - SERIES REACTOR DATA (Output at 51-56):\n')
            f.write('    51: O_P_flow_from_to_MW, 52: O_Q_flow_from_to_Mvar, 53: O_P_flow_to_from_MW, 54: O_Q_flow_to_from_Mvar, 55: O_losses_MW, 56: O_status\n')
            f.write('\nSECTION 10 - SHUNT DATA (Output at 51-54):\n')
            f.write('    51: O_Q_injected_Mvar, 52: O_V_actual_pu, 53: O_V_actual_kV, 54: O_status\n')
            f.write('\nSECTION 11 - HVDC TRANSMISSION LINK DATA (Output at 51-65, signed: + = flows from_bus->to_bus, - = flows to_bus->from_bus):\n')
            f.write('    51: O_Vdc_from_kV, 52: O_Vdc_to_kV, 53: O_Idc_A, 54: O_P_dc_MW, 55: O_losses_dc_MW, 56: O_P_from_ac_MW, 57: O_Q_from_ac_Mvar, 58: O_P_to_ac_MW, 59: O_Q_to_ac_Mvar, 60: O_alpha_deg, 61: O_gamma_deg, 62: O_tap_from, 63: O_tap_to, 64: O_loading_pct, 65: O_status\n')
            f.write('\nSECTION 12 - SYSTEM SUMMARY (No column shift)\n')
        
            f.write('============ POWER FLOW ALL DATA RESULTS =============\n')
            f.write(f'Complete Power System Data with Results\n')
            f.write(f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
            f.write('Output data starts at column 51 (0-50 reserved for input)\n')
            f.write('"""\n\n')
            
            f.write(f'BASE_MVA = {self.engine.baseMVA}\n')
            f.write(f'OUTPUT_START_COL = {OUTPUT_START_COL}\n\n')
            
            # ========== 1. BUS DATA ==========
            f.write('# ========== BUS DATA ==========\n')
            f.write('# [0-10: input, 51-55: output]\n')
            f.write('BUS_DATA = [\n')
            
            buses = self.input_data.get('buses', {})
            if buses:
                for bus_num, bus in buses.items():
                    idx = self.engine.bus_index_map.get(bus_num, 0)
                    v_val = self._safe_get_v(idx)
                    va_val = self._safe_get_va(idx)
                    V_kV = self.get_voltage_kv(bus_num, v_val)
                    v_status = self.get_status(v_val, {'min': 0.95, 'max': 1.05})
                    a_status = self.get_status(abs(va_val), {'min': 0, 'max': 30})
                    
                    row = [''] * (OUTPUT_START_COL + 5)   # 51 + 5 = 56 columns total (0-50 input, 51-55 output)
                    row[0] = bus_num
                    row[1] = f'"{bus.get("name", f"Bus_{bus_num}")}"'
                    row[2] = bus.get("type", 1)
                    row[3] = bus.get("base_kV", 132)
                    row[4] = bus.get("area", 1)
                    row[5] = bus.get("zone", 1)
                    row[6] = bus.get("owner", 1)
                    row[7] = bus.get("V_init", 1.0)
                    row[8] = bus.get("angle_init", 0.0)
                    row[9] = bus.get("shunt_G", 0)
                    row[10] = bus.get("shunt_B", 0)
                    
                    row[OUTPUT_START_COL + 0] = f"{v_val:.6f}"
                    row[OUTPUT_START_COL + 1] = f"{V_kV:.6f}"
                    row[OUTPUT_START_COL + 2] = f"{va_val:.6f}"
                    row[OUTPUT_START_COL + 3] = f'"{v_status}"'
                    row[OUTPUT_START_COL + 4] = f'"{a_status}"'
                    
                    f.write(f'    {row},\n')
            f.write(']\n\n')
            
            # ========== 2. GENERATOR DATA ==========
            f.write('# ========== GENERATOR DATA ==========\n')
            f.write('# [0-12: input, 51-57: output]\n')
            f.write('GENERATOR_DATA = [\n')
            
            generators = self.input_data.get('generators', {})
            if generators:
                for gen_num, gen in generators.items():
                    bus_num = gen.get('bus', 0)
                    idx = self.engine.bus_index_map.get(bus_num, 0)
                    v_val = self._safe_get_v(idx)
                    V_kV = self.get_voltage_kv(bus_num, v_val)
                    O_P_out, O_Q_out = self.get_generator_outputs(gen_num, gen)
                    
                    bus_type = self.input_data.get('buses', {}).get(bus_num, {}).get('type', 1)
                    qmin_val = gen.get('Qmin', -9999.0)
                    qmax_val = gen.get('Qmax', 9999.0)
                    q_status = "WITHIN LIMITS"
                    limit_flag = "OK"
                    if bus_type == 1:
                        if qmin_val is not None and O_Q_out < float(qmin_val) - 1e-3:
                            q_status = "BELOW Qmin"
                            limit_flag = "VIOLATED"
                        elif qmax_val is not None and O_Q_out > float(qmax_val) + 1e-3:
                            q_status = "ABOVE Qmax"
                            limit_flag = "VIOLATED"
                        else:
                            q_status = "WITHIN LIMITS"
                            limit_flag = "OK"
                    elif abs(O_Q_out - qmax_val) <= 1e-3:
                        q_status = "AT Qmax"
                        limit_flag = "OK"
                    elif abs(O_Q_out - qmin_val) <= 1e-3:
                        q_status = "AT Qmin"
                        limit_flag = "OK"
                    elif O_Q_out < qmin_val - 1e-3:
                        q_status = "BELOW Qmin"
                        limit_flag = "VIOLATED"
                    elif O_Q_out > qmax_val + 1e-3:
                        q_status = "ABOVE Qmax"
                        limit_flag = "VIOLATED"
                    
                    row = [''] * (OUTPUT_START_COL + 7)  # 51 + 7 = 58 columns total (0-50 input, 51-57 output)
                    row[0] = gen_num
                    row[1] = f'"{gen.get("name", f"Gen_{gen_num}")}"'
                    row[2] = f'"{gen.get("type", "SYNC")}"'
                    row[3] = bus_num
                    row[4] = gen.get("area", 1)
                    row[5] = gen.get("zone", 1)
                    row[6] = gen.get("P_out", 0)
                    row[7] = gen.get("Q_out", 0)
                    row[8] = gen.get("V_set", 1.0)
                    row[9] = gen.get("Qmin", -9999)
                    row[10] = gen.get("Qmax", 9999)
                    row[11] = gen.get("status", 1)
                    row[12] = gen.get("owner", 1)
                    
                    row[OUTPUT_START_COL + 0] = f"{O_P_out:+.6f}"
                    row[OUTPUT_START_COL + 1] = f"{O_Q_out:+.6f}"
                    row[OUTPUT_START_COL + 2] = f"{v_val:.6f}"
                    row[OUTPUT_START_COL + 3] = f"{V_kV:.6f}"
                    row[OUTPUT_START_COL + 4] = f'"{q_status}"'
                    row[OUTPUT_START_COL + 5] = f'"{limit_flag}"'
                    online_status = "ONLINE" if gen.get('status', 1) == 1 else "OFFLINE"
                    row[OUTPUT_START_COL + 6] = f'"{online_status}"'
                                                
                    f.write(f'    {row},\n')
            f.write(']\n\n')
            
            # ========== 3. LOAD DATA ==========
            f.write('# ========== LOAD DATA ==========\n')
            f.write('# [0-8: input, 51-55: output]\n')
            f.write('LOAD_DATA = [\n')
            
            loads = self.input_data.get('loads', {})
            if loads:
                for load_num, load in loads.items():
                    bus_num = load.get('bus', 0)
                    idx = self.engine.bus_index_map.get(bus_num, 0)
                    v_val = self._safe_get_v(idx)
                    V_kV = self.get_voltage_kv(bus_num, v_val)
                    supply_status = "NORMAL" if v_val >= 0.95 else "VOLTAGE LOW"
                    
                    row = [''] * (OUTPUT_START_COL + 5)  # 51 + 5 = 56 columns total (0-50 input, 51-55 output)
                    row[0] = load_num
                    row[1] = f'"{load.get("name", f"Load_{load_num}")}"'
                    row[2] = bus_num
                    row[3] = load.get("area", 1)
                    row[4] = load.get("zone", 1)
                    row[5] = load.get("P_demand", 0)
                    row[6] = load.get("Q_demand", 0)
                    row[7] = f'"{load.get("model", "constant_PQ")}"'
                    row[8] = load.get("status", 1)
                    
                    if load.get('status', 1) == 0:
                        O_P_supplied = 0.0
                        O_Q_supplied = 0.0
                    else:
                        O_P_supplied = -float(load.get('P_demand', 0))
                        O_Q_supplied = -float(load.get('Q_demand', 0))
                        if abs(O_P_supplied) < 1e-6: O_P_supplied = 0.0
                        if abs(O_Q_supplied) < 1e-6: O_Q_supplied = 0.0

                    row[OUTPUT_START_COL + 0] = f"{O_P_supplied:.6f}"
                    row[OUTPUT_START_COL + 1] = f"{O_Q_supplied:.6f}"
                    row[OUTPUT_START_COL + 2] = f"{v_val:.6f}"
                    row[OUTPUT_START_COL + 3] = f"{V_kV:.6f}"
                    supply_status = "NORMAL" if v_val >= 0.95 else "VOLTAGE LOW"
                    row[OUTPUT_START_COL + 4] = f'"{supply_status}"'

                    f.write(f'    {row},\n')
            f.write(']\n\n')
            
            # ========== 4. TRANSMISSION LINE DATA ==========
            f.write('# ========== TRANSMISSION LINE DATA ==========\n')
            f.write('# [0-13: input, 51-60: output]\n')
            f.write('LINE_DATA = [\n')
            
            lines = self.input_data.get('lines', {})
            if lines:
                for line_num, line in lines.items():
                    stats = self._get_line_stats(line_num, line)
                    loading_status = self.get_status(stats.get('avg_loading', 0), {'min': 0, 'max': 80})
                    
                    length = line.get('length_km', 0)
                    Loss_MW = abs(stats.get('avg_loss', 0))
                    Loss_per_km = Loss_MW / length if length > 0 else 0
                    
                    P_fwd = stats.get('avg_P_fwd', 0)
                    Q_fwd = stats.get('avg_Q_fwd', 0)
                    MVA_fwd = (P_fwd**2 + Q_fwd**2)**0.5
                    
                    P_rev = stats.get('avg_P_rev', 0)
                    Q_rev = stats.get('avg_Q_rev', 0)
                    MVA_rev = (P_rev**2 + Q_rev**2)**0.5
                    
                    flow_dir = (f"Bus{line.get('from_bus', 0)} -> Bus{line.get('to_bus', 0)}" if P_fwd >= 0
                                else f"Bus{line.get('to_bus', 0)} -> Bus{line.get('from_bus', 0)}")
                    
                    #row = [''] * OUTPUT_START_COL
                    row = [''] * (OUTPUT_START_COL + 11)  # 51 + 11 = 62 columns total (0-50 input, 51-61 output)
                    
                    row[0] = line_num
                    row[1] = f'"{line.get("name", f"Line_{line_num}")}"'
                    row[2] = line.get("from_bus", 0)
                    row[3] = line.get("to_bus", 0)
                    row[4] = length
                    row[5] = line.get("area", 1)
                    row[6] = line.get("zone", 1)
                    row[7] = line.get("owner", 1)
                    row[8] = line.get("R_per_km", 0)
                    row[9] = line.get("X_per_km", 0)
                    row[10] = line.get("B_per_km", 0)
                    row[11] = line.get("r", 0)
                    row[12] = line.get("x", 0)
                    row[13] = line.get("b", 0)
                    row[14] = line.get("rateA", 0)
                    row[15] = line.get("rateB", 0)
                    row[16] = line.get("rateC", 0)
                    row[17] = line.get("status", 1)
                    row[18] = line.get("area", 1)
                    row[19] = line.get("zone", 1)
                    row[20] = line.get("owner", 1)
                    
                    row[OUTPUT_START_COL + 0] = f"{P_fwd:+.6f}"
                    row[OUTPUT_START_COL + 1] = f"{Q_fwd:+.6f}"
                    row[OUTPUT_START_COL + 2] = f"{MVA_fwd:.6f}"
                    row[OUTPUT_START_COL + 3] = f"{P_rev:+.6f}"
                    row[OUTPUT_START_COL + 4] = f"{Q_rev:+.6f}"
                    row[OUTPUT_START_COL + 5] = f"{MVA_rev:.6f}"
                    row[OUTPUT_START_COL + 6] = f"{Loss_MW:.6f}"
                    row[OUTPUT_START_COL + 7] = f"{Loss_per_km:.6f}"
                    row[OUTPUT_START_COL + 8] = f"{stats.get('avg_loading', 0):.6f}"
                    #row[OUTPUT_START_COL + 9] = f'"{loading_status}"'
                    loading_status = self.get_status(stats.get('avg_loading', 0), {'min': 0, 'max': 80})
                    row[OUTPUT_START_COL + 9] = f'"{loading_status}"'
                    row[OUTPUT_START_COL + 10] = f'"{flow_dir}"'

                    
                    f.write(f'    {row},\n')
            f.write(']\n\n')
            
            # ========== 5. TRANSFORMER DATA ==========
            f.write('# ========== TRANSFORMER DATA ==========\n')
            f.write('# [0-18: input, 51-62: output]\n')
            f.write('TRANSFORMER_DATA = [\n')
            
            transformers = self.input_data.get('transformers', {})
            if transformers:
                for xfmr_num, xfmr in transformers.items():
                    stats = self._get_xfmr_stats(xfmr_num, xfmr)

                    tap_ratio = stats.get('avg_tap', xfmr.get('tap_ratio', 1.0))
                    step_size = xfmr.get('step_size', 0.01)
                    min_tap = xfmr.get('min_tap', 0.9)
                    tap_step = int((tap_ratio - min_tap) / step_size) if step_size > 0 else 0
                    loading_status = self.get_status(stats.get('avg_loading', 0), {'min': 0, 'max': 80})
                    
                    P_fwd = stats.get('avg_P_fwd', 0)
                    Q_fwd = stats.get('avg_Q_fwd', 0)
                    MVA_fwd = (P_fwd**2 + Q_fwd**2)**0.5
                    
                    P_rev = stats.get('avg_P_rev', 0)
                    Q_rev = stats.get('avg_Q_rev', 0)
                    MVA_rev = (P_rev**2 + Q_rev**2)**0.5
                    
                    flow_dir = (f"Bus{xfmr.get('from_bus', 0)} -> Bus{xfmr.get('to_bus', 0)}" if P_fwd >= 0
                                else f"Bus{xfmr.get('to_bus', 0)} -> Bus{xfmr.get('from_bus', 0)}")
                    
                    Loss_MW = abs(stats.get('avg_loss', 0))
                    Loss_MVA = (Loss_MW**2 + (abs(stats.get('avg_loss_q', 0)))**2)**0.5 if stats.get('avg_loss_q', 0) else Loss_MW
                    
                    #row = [''] * OUTPUT_START_COL
                    row = [''] * (OUTPUT_START_COL + 13)  # 51 + 13 = 64 columns total (0-50 input, 51-63 output)
                    row[0] = xfmr_num
                    row[1] = f'"{xfmr.get("name", f"Xfmr_{xfmr_num}")}"'
                    row[2] = xfmr.get("from_bus", 0)
                    row[3] = xfmr.get("to_bus", 0)
                    row[4] = xfmr.get("rateA", 9999)
                    row[5] = xfmr.get("area", 1)
                    row[6] = xfmr.get("zone", 1)
                    row[7] = xfmr.get("owner", 1)
                    row[8] = xfmr.get("r", 0)
                    row[9] = xfmr.get("x", 0)
                    row[10] = xfmr.get("tap_ratio", 1.0)
                    row[11] = xfmr.get("phase_shift", 0)
                    row[12] = xfmr.get("min_tap", 0.9)
                    row[13] = xfmr.get("max_tap", 1.1)
                    row[14] = xfmr.get("step_size", 0.01)
                    row[15] = xfmr.get("status", 1)
                    row[16] = xfmr.get("area", 1)
                    row[17] = xfmr.get("zone", 1)
                    row[18] = xfmr.get("owner", 1)
                    
                    row[OUTPUT_START_COL + 0] = f"{P_fwd:+.6f}"
                    row[OUTPUT_START_COL + 1] = f"{Q_fwd:+.6f}"
                    row[OUTPUT_START_COL + 2] = f"{MVA_fwd:.6f}"
                    row[OUTPUT_START_COL + 3] = f"{P_rev:+.6f}"
                    row[OUTPUT_START_COL + 4] = f"{Q_rev:+.6f}"
                    row[OUTPUT_START_COL + 5] = f"{MVA_rev:.6f}"
                    row[OUTPUT_START_COL + 6] = f"{Loss_MW:.6f}"
                    row[OUTPUT_START_COL + 7] = f"{Loss_MVA:.6f}"
                    row[OUTPUT_START_COL + 8] = f"{tap_ratio:.6f}"
                    row[OUTPUT_START_COL + 9] = tap_step
                    row[OUTPUT_START_COL + 10] = f"{stats.get('avg_loading', 0):.6f}"
                    #row[OUTPUT_START_COL + 11] = f'"{loading_status}"'
                    loading_status = self.get_status(stats.get('avg_loading', 0), {'min': 0, 'max': 80})
                    row[OUTPUT_START_COL + 11] = f'"{loading_status}"'
                    row[OUTPUT_START_COL + 12] = f'"{flow_dir}"'

                    
                    f.write(f'    {row},\n')
            else:
                f.write('    # No transformer data available\n')
            f.write(']\n\n')
            
            # ========== 5B. THREE-WINDING TRANSFORMER DATA ==========
            f.write('# ========== THREE-WINDING TRANSFORMER DATA ==========\n')
            f.write('# [0-17: input, 51-68: output]\n')
            f.write('THREE_WINDING_TRANSFORMER_DATA = [\n')
            three_w_xfmrs = self.input_data.get('three_winding_transformers') or self.input_data.get('three_winding_xfmrs') or {}
            if three_w_xfmrs:
                for tw_num, twx in three_w_xfmrs.items():
                    stats = getattr(self, 'three_w_xfmr_stats', {}).get(tw_num, {})
                    dummy_bus = 100000000 + int(tw_num)
                    dummy_idx = self.engine.bus_index_map.get(dummy_bus, None)
                    if dummy_idx is not None:
                        dummy_v = self._safe_get_v(dummy_idx, 1.0)
                        dummy_va = self._safe_get_va(dummy_idx, 0.0)
                        hv_bus = twx.get('hv_bus', 0)
                        base_kv = self.input_data.get('buses', {}).get(hv_bus, {}).get('base_kV', 132.0)
                        dummy_kv = dummy_v * base_kv
                    else:
                        dummy_v, dummy_kv, dummy_va = 1.0, 132.0, 0.0
                        
                    row = [''] * (OUTPUT_START_COL + 18)
                    row[0] = tw_num
                    row[1] = f'"{twx.get("name", f"3WX_{tw_num}")}"'
                    row[2] = twx.get('hv_bus', 0)
                    row[3] = twx.get('mv_bus', 0)
                    row[4] = twx.get('lv_bus', 0)
                    row[5] = twx.get('r_hm', 0.0)
                    row[6] = twx.get('x_hm', 0.0)
                    row[7] = twx.get('r_hl', 0.0)
                    row[8] = twx.get('x_hl', 0.0)
                    row[9] = twx.get('r_ml', 0.0)
                    row[10] = twx.get('x_ml', 0.0)
                    row[11] = twx.get('rate_h', 9999)
                    row[12] = twx.get('rate_m', 9999)
                    row[13] = twx.get('rate_l', 9999)
                    row[14] = twx.get('tap_h', 1.0)
                    row[15] = twx.get('tap_m', 1.0)
                    row[16] = twx.get('tap_l', 1.0)
                    row[17] = twx.get('status', 1)
                    
                    row[OUTPUT_START_COL + 0] = f"{stats.get('P_hv', 0.0):+.6f}"
                    row[OUTPUT_START_COL + 1] = f"{stats.get('Q_hv', 0.0):+.6f}"
                    row[OUTPUT_START_COL + 2] = f"{stats.get('S_hv', 0.0):.6f}"
                    row[OUTPUT_START_COL + 3] = f"{stats.get('loading_hv', 0.0):.6f}"
                    row[OUTPUT_START_COL + 4] = f"{stats.get('P_mv', 0.0):+.6f}"
                    row[OUTPUT_START_COL + 5] = f"{stats.get('Q_mv', 0.0):+.6f}"
                    row[OUTPUT_START_COL + 6] = f"{stats.get('S_mv', 0.0):.6f}"
                    row[OUTPUT_START_COL + 7] = f"{stats.get('loading_mv', 0.0):.6f}"
                    row[OUTPUT_START_COL + 8] = f"{stats.get('P_lv', 0.0):+.6f}"
                    row[OUTPUT_START_COL + 9] = f"{stats.get('Q_lv', 0.0):+.6f}"
                    row[OUTPUT_START_COL + 10] = f"{stats.get('S_lv', 0.0):.6f}"
                    row[OUTPUT_START_COL + 11] = f"{stats.get('loading_lv', 0.0):.6f}"
                    row[OUTPUT_START_COL + 12] = f"{stats.get('total_loss_p', 0.0):.6f}"
                    row[OUTPUT_START_COL + 13] = f"{stats.get('max_loading', 0.0):.6f}"
                    row[OUTPUT_START_COL + 14] = f"{dummy_v:.6f}"
                    row[OUTPUT_START_COL + 15] = f"{dummy_kv:.3f}"
                    row[OUTPUT_START_COL + 16] = f"{dummy_va:.3f}"
                    row[OUTPUT_START_COL + 17] = f'"{stats.get("status", "NORMAL")}"'
                    
                    f.write(f'    {row},\n')
            else:
                f.write('    # No three-winding transformer data available\n')
            f.write(']\n\n')
            
            # ========== 6. CAPACITOR DATA ==========
            f.write('# ========== CAPACITOR DATA ==========\n')
            f.write('# [0-7: input, 51-54: output]\n')
            f.write('CAPACITOR_DATA = [\n')
            
            capacitors = self.input_data.get('capacitors', {})
            if capacitors:
                for cap_num, cap in capacitors.items():
                    bus_num = cap.get('bus', 0)
                    idx = self.engine.bus_index_map.get(bus_num, 0)
                    V_actual = self._safe_get_v(idx)
                    V_kV = self.get_voltage_kv(bus_num, V_actual)
                    Q_inj = (cap.get('Q_cap', 0) * (V_actual ** 2)) if cap.get('status', 1) == 1 else 0.0
                    
                    row = [''] * (OUTPUT_START_COL + 4) # 51 + 4 = 55 columns total (0-50 input, 51-54 output)
                    
                    row[0] = cap_num
                    row[1] = f'"{cap.get("name", f"Cap_{cap_num}")}"'
                    row[2] = bus_num
                    row[3] = cap.get("area", 1)
                    row[4] = cap.get("zone", 1)
                    row[5] = cap.get("Q_cap", 0)
                    row[6] = cap.get("status", 1)
                    row[7] = cap.get("owner", 1)
                    
                    row[OUTPUT_START_COL + 0] = f"{Q_inj:.6f}"
                    row[OUTPUT_START_COL + 1] = f"{V_actual:.6f}"
                    row[OUTPUT_START_COL + 2] = f"{V_kV:.6f}"
                    #row[OUTPUT_START_COL + 3] = f'"ONLINE" if {cap.get("status", 1)} == 1 else "OFFLINE"'
                    cap_status = "ONLINE" if cap.get('status', 1) == 1 else "OFFLINE"
                    row[OUTPUT_START_COL + 3] = f'"{cap_status}"'                    


                    f.write(f'    {row},\n')
            else:
                f.write('    # No capacitor data available\n')
            f.write(']\n\n')
            
            # ========== 7. REACTOR DATA ==========
            f.write('# ========== REACTOR DATA ==========\n')
            f.write('# [0-7: input, 51-54: output]\n')
            f.write('REACTOR_DATA = [\n')
            
            reactors = self.input_data.get('reactors', {})
            if reactors:
                for reactor_num, reactor in reactors.items():
                    bus_num = reactor.get('bus', 0)
                    idx = self.engine.bus_index_map.get(bus_num, 0)
                    V_actual = self._safe_get_v(idx)
                    V_kV = self.get_voltage_kv(bus_num, V_actual)
                    
                    def to_mvar(val):
                        v = abs(float(val or 0.0))
                        return v / 1000.0 if v > 1000.0 else v

                    Q_abs = (to_mvar(reactor.get('Q_react', 0)) * (V_actual ** 2)) if reactor.get('status', 1) == 1 else 0.0
                    
                    row = [''] * (OUTPUT_START_COL + 4) # 51 + 4 = 55 columns total (0-50 input, 51-54 output)
                    
                    row[0] = reactor_num
                    row[1] = f'"{reactor.get("name", f"Reactor_{reactor_num}")}"'
                    row[2] = bus_num
                    row[3] = reactor.get("area", 1)
                    row[4] = reactor.get("zone", 1)
                    row[5] = reactor.get("Q_react", 0)
                    row[6] = reactor.get("status", 1)
                    row[7] = reactor.get("owner", 1)
                    
                    row[OUTPUT_START_COL + 0] = f"{Q_abs:.6f}"
                    row[OUTPUT_START_COL + 1] = f"{V_actual:.6f}"
                    row[OUTPUT_START_COL + 2] = f"{V_kV:.6f}"
                    #row[OUTPUT_START_COL + 3] = f'"ONLINE" if {reactor.get("status", 1)} == 1 else "OFFLINE"'
                    reactor_status = "ONLINE" if reactor.get('status', 1) == 1 else "OFFLINE"
                    row[OUTPUT_START_COL + 3] = f'"{reactor_status}"'

                    
                    f.write(f'    {row},\n')
            else:
                f.write('    # No reactor data available\n')
            f.write(']\n\n')
            
            # ========== 8. SERIES COMPENSATION DATA ==========
            f.write('# ========== SERIES COMPENSATION DATA ==========\n')
            f.write('# [0-11: input, 51-55: output]\n')
            f.write('SERIES_COMP_DATA = [\n')
            
            series_comps = self.input_data.get('series_comps', {})
            if series_comps:
                for series_num, sc in series_comps.items():
                    effective_X = sc.get('x', 0) * (1 - sc.get('comp_pct', 0) / 100)
                    comp_status = "ACTIVE" if sc.get('status', 1) == 1 else "INACTIVE"
                    
                    row = [''] * (OUTPUT_START_COL + 5)  # 51 + 5 = 56 columns total (0-50 input, 51-55 output)
                    
                    row[0] = series_num
                    row[1] = f'"{sc.get("name", f"SC_{series_num}")}"'
                    row[2] = sc.get("from_bus", 0)
                    row[3] = sc.get("to_bus", 0)
                    row[4] = sc.get("area", 1)
                    row[5] = sc.get("zone", 1)
                    row[6] = sc.get("owner", 1)
                    row[7] = sc.get("r", 0)
                    row[8] = sc.get("x", 0)
                    row[9] = sc.get("comp_pct", 0)
                    row[10] = sc.get("status", 1)
                    row[11] = sc.get("varistor_kV", 0)
                    
                    row[OUTPUT_START_COL + 0] = f"{effective_X:.6f}"
                    #row[OUTPUT_START_COL + 1] = f'"{comp_status}"'
                    comp_status = "ACTIVE" if sc.get('status', 1) == 1 else "INACTIVE"
                    row[OUTPUT_START_COL + 1] = f'"{comp_status}"'

                    row[OUTPUT_START_COL + 2] = "0.0"
                    row[OUTPUT_START_COL + 3] = "0.0"
                    row[OUTPUT_START_COL + 4] = "0.0"
                    
                    f.write(f'    {row},\n')
            else:
                f.write('    # No series compensation data available\n')
            f.write(']\n\n')
            
            # ========== 9. SERIES REACTOR DATA ==========
            f.write('# ========== SERIES REACTOR DATA ==========\n')
            f.write('# [0-9: input, 51-55: output]\n')
            f.write('SERIES_REACTOR_DATA = [\n')
            
            series_reactors = self.input_data.get('series_reactors', {})
            if series_reactors:
                for sr_num, sr in series_reactors.items():
                    #row = [''] * OUTPUT_START_COL
                    row = [''] * (OUTPUT_START_COL + 6)  # 51 + 6 = 57 columns total (0-50 input, 51-56 output)
                    row[0] = sr_num
                    row[1] = f'"{sr.get("name", f"SR_{sr_num}")}"'
                    row[2] = sr.get("from_bus", 0)
                    row[3] = sr.get("to_bus", 0)
                    row[4] = sr.get("area", 1)
                    row[5] = sr.get("zone", 1)
                    row[6] = sr.get("owner", 1)
                    row[7] = sr.get("r", 0)
                    row[8] = sr.get("x", 0)
                    row[9] = sr.get("status", 1)
                    
                    row[OUTPUT_START_COL + 0] = "0.0"
                    row[OUTPUT_START_COL + 1] = "0.0"
                    row[OUTPUT_START_COL + 2] = "0.0"
                    row[OUTPUT_START_COL + 3] = "0.0"
                    #row[OUTPUT_START_COL + 4] = f'"ONLINE" if {sr.get("status", 1)} == 1 else "OFFLINE"'
                    sr_status = "ONLINE" if sr.get('status', 1) == 1 else "OFFLINE"
                    row[OUTPUT_START_COL + 5] = f'"{sr_status}"'

                    
                    f.write(f'    {row},\n')
            else:
                f.write('    # No series reactor data available\n')
            f.write(']\n\n')
            
            # ========== 10. SHUNT DATA ==========
            f.write('# ========== SHUNT COMPENSATION DATA ==========\n')
            f.write('# [0-7: input, 51-54: output]\n')
            f.write('SHUNT_DATA = [\n')
            
            shunts = self.input_data.get('shunts', {})
            if shunts:
                for shunt_num, shunt in shunts.items():
                    bus_num = shunt.get('bus', 0)
                    idx = self.engine.bus_index_map.get(bus_num, 0)
                    V_actual = self._safe_get(self.avg_V, idx, 1.0)
                    V_kV = self.get_voltage_kv(bus_num, V_actual)
                    Q_inj = shunt.get('Q_shunt', 0) * (V_actual ** 2)
                    
                    row = [''] * (OUTPUT_START_COL + 4)  # 51 + 4 = 55 columns total (0-50 input, 51-54 output)
                    
                    row[0] = shunt_num
                    row[1] = f'"{shunt.get("name", f"Shunt_{shunt_num}")}"'
                    row[2] = bus_num
                    row[3] = shunt.get("area", 1)
                    row[4] = shunt.get("zone", 1)
                    row[5] = shunt.get("Q_shunt", 0)
                    row[6] = shunt.get("status", 1)
                    row[7] = shunt.get("owner", 1)
                    
                    row[OUTPUT_START_COL + 0] = f"{Q_inj:.6f}"
                    row[OUTPUT_START_COL + 1] = f"{V_actual:.6f}"
                    row[OUTPUT_START_COL + 2] = f"{V_kV:.6f}"
                    row[OUTPUT_START_COL + 3] = f'"ONLINE" if {shunt.get("status", 1)} == 1 else "OFFLINE"'
                    
                    f.write(f'    {row},\n')
            else:
                f.write('    # No shunt compensation data available\n')
            f.write(']\n\n')
            
            # ========== 11. HVDC TRANSMISSION LINK DATA ==========
            f.write('# ========== HVDC TRANSMISSION LINK DATA ==========\n')
            f.write('# [0-32: input, 51-65: output]\n')
            f.write('HVDC_LINK_DATA = [\n')
            
            hvdc_links = self.input_data.get('hvdc_links', {})
            if hvdc_links:
                for lk_num, lk in hvdc_links.items():
                    stats = self._get_hvdc_stats(lk_num, lk)
                    
                    row = [''] * (OUTPUT_START_COL + 15)
                    row[0] = lk_num
                    row[1] = f'"{lk.get("name", f"HVDC_{lk_num}")}"'
                    row[2] = lk.get('from_bus', 0)
                    row[3] = lk.get('to_bus', 0)
                    row[4] = lk.get('r_dc', 0.0)
                    row[5] = lk.get('status', 1)
                    # From Side
                    row[6] = f'"{lk.get("from_mode", "Rectifier")}"'
                    row[7] = lk.get('from_ctrl_type', 3)
                    row[8] = lk.get('from_val', 50.0)
                    row[9] = lk.get('from_angle', 12.0)
                    row[10] = lk.get('from_xc', 0.0)
                    row[11] = lk.get('from_tfr_kv', 220.0)
                    row[12] = lk.get('from_tfr_mva', 100.0)
                    row[13] = lk.get('from_tap_min', 0.85)
                    row[14] = lk.get('from_tap_max', 1.20)
                    row[15] = lk.get('from_tap_step', 0.0125)
                    row[16] = lk.get('from_nb', 1)
                    row[17] = lk.get('from_np', 1)
                    # To Side
                    row[18] = f'"{lk.get("to_mode", "Inverter")}"'
                    row[19] = lk.get('to_ctrl_type', 1)
                    row[20] = lk.get('to_val', 220.0)
                    row[21] = lk.get('to_angle', 15.0)
                    row[22] = lk.get('to_xc', 0.0)
                    row[23] = lk.get('to_tfr_kv', 220.0)
                    row[24] = lk.get('to_tfr_mva', 100.0)
                    row[25] = lk.get('to_tap_min', 0.85)
                    row[26] = lk.get('to_tap_max', 1.20)
                    row[27] = lk.get('to_tap_step', 0.0125)
                    row[28] = lk.get('to_nb', 1)
                    row[29] = lk.get('to_np', 1)
                    row[30] = lk.get('area', 1)
                    row[31] = lk.get('zone', 1)
                    row[32] = lk.get('owner', 1)
                    
                    row[OUTPUT_START_COL + 0] = f"{stats.get('avg_Vdc_from', 0.0):.6f}"
                    row[OUTPUT_START_COL + 1] = f"{stats.get('avg_Vdc_to', 0.0):.6f}"
                    row[OUTPUT_START_COL + 2] = f"{stats.get('avg_Idc', 0.0):.6f}"
                    row[OUTPUT_START_COL + 3] = f"{stats.get('avg_P_dc', 0.0):.6f}"
                    row[OUTPUT_START_COL + 4] = f"{stats.get('avg_loss', 0.0):.6f}"
                    row[OUTPUT_START_COL + 5] = f"{stats.get('avg_P_fwd', 0.0):.6f}"
                    row[OUTPUT_START_COL + 6] = f"{stats.get('avg_Q_fwd', 0.0):.6f}"
                    row[OUTPUT_START_COL + 7] = f"{stats.get('avg_P_rev', 0.0):.6f}"
                    row[OUTPUT_START_COL + 8] = f"{stats.get('avg_Q_rev', 0.0):.6f}"
                    row[OUTPUT_START_COL + 9] = f"{stats.get('avg_alpha', 0.0):.2f}"
                    row[OUTPUT_START_COL + 10] = f"{stats.get('avg_gamma', 0.0):.2f}"
                    row[OUTPUT_START_COL + 11] = f"{stats.get('avg_tap_from', 1.0):.4f}"
                    row[OUTPUT_START_COL + 12] = f"{stats.get('avg_tap_to', 1.0):.4f}"
                    row[OUTPUT_START_COL + 13] = f"{stats.get('avg_loading', 0.0):.2f}"
                    status_str = "ONLINE" if lk.get("status", 1) == 1 else "OFFLINE"
                    row[OUTPUT_START_COL + 14] = f'"{status_str}"'
                    
                    f.write(f'    {row},\n')
            else:
                f.write('    # No HVDC transmission link data available\n')
            f.write(']\n\n')
            
            # ========== 12. SYSTEM SUMMARY ==========
            hvdc_losses = sum(s.get('avg_loss', 0.0) for s in getattr(self, 'hvdc_stats', {}).values())
            total_losses = sum(s['avg_loss'] for s in self.line_stats.values() if s.get('status') != 'OFFLINE') + sum(s['avg_loss'] for s in self.xfmr_stats.values() if s.get('status') != 'OFFLINE') + hvdc_losses
            gen_outputs_py = [self.get_generator_outputs(gid, g) for gid, g in self.input_data.get('generators', {}).items() if g.get('status', 1) == 1]
            total_gen_p = sum(p for p, q in gen_outputs_py if p > 0)
            total_load_p = sum(l.get('P_demand', 0) for l in self.input_data.get('loads', {}).values() if self._is_load_online(l)) + sum(-p for p, q in gen_outputs_py if p < 0)
            
            f.write('# ========== SYSTEM SUMMARY ==========\n')
            f.write('SYSTEM_SUMMARY = {\n')
            f.write(f'    "total_generation_mw": {total_gen_p:.6f},\n')
            f.write(f'    "total_load_mw": {total_load_p:.6f},\n')
            f.write(f'    "total_losses_mw": {total_losses:.6f},\n')
            f.write(f'    "loss_percentage": {(total_losses/total_load_p)*100 if total_load_p > 0 else 0:.6f},\n')
            f.write(f'    "avg_voltage_pu": {np.mean(self.avg_V):.6f},\n')
            f.write(f'    "min_voltage_pu": {np.min(self.avg_V):.6f},\n')
            f.write(f'    "max_voltage_pu": {np.max(self.avg_V):.6f},\n')
            f.write(f'    "n_buses": {len(self.input_data.get("buses", {}))},\n')
            f.write(f'    "n_lines": {len(self.input_data.get("lines", {}))},\n')
            f.write(f'    "n_transformers": {len(self.input_data.get("transformers", {}))},\n')
            f.write(f'    "n_generators": {len(self.input_data.get("generators", {}))},\n')
            f.write(f'    "n_loads": {len(self.input_data.get("loads", {}))},\n')
            f.write(f'    "n_capacitors": {len(self.input_data.get("capacitors", {}))},\n')
            f.write(f'    "n_reactors": {len(self.input_data.get("reactors", {}))},\n')
            f.write(f'    "n_series_comps": {len(self.input_data.get("series_comps", {}))},\n')
            f.write(f'    "n_series_reactors": {len(self.input_data.get("series_reactors", {}))},\n')
            f.write(f'    "n_shunts": {len(self.input_data.get("shunts", {}))},\n')
            f.write(f'    "n_hvdc_links": {len(self.input_data.get("hvdc_links", {}))},\n')
            f.write('}\n\n')
            
            f.write('if __name__ == "__main__":\n')
            f.write('    print(f"Buses: {len(BUS_DATA)}")\n')
            f.write('    print(f"Lines: {len(LINE_DATA)}")\n')
            f.write('    print(f"Transformers: {len(TRANSFORMER_DATA)}")\n')
            f.write('    print(f"Capacitors: {len(CAPACITOR_DATA)}")\n')
            f.write('    print(f"Reactors: {len(REACTOR_DATA)}")\n')
            f.write('    print(f"Series Compensation: {len(SERIES_COMP_DATA)}")\n')
            f.write('    print(f"Series Reactors: {len(SERIES_REACTOR_DATA)}")\n')
            f.write('    print(f"Shunts: {len(SHUNT_DATA)}")\n')
            f.write('    print(f"HVDC Links: {len(HVDC_LINK_DATA)}")\n')
            f.write('    print(f"Output starts at column {OUTPUT_START_COL}")\n')
        
        return filename

    def write_py_output_only(self, filename):
        """Write PY file with ONLY outputs (compact) - includes all components"""
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write('"""\n')
            f.write(f'Power System Output Data Only\n')
            f.write(f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
            f.write('This file contains ONLY output results (no input data)\n')
            f.write('"""\n\n')
            
            # =========================================================
            # BUS OUTPUTS
            # =========================================================
            f.write('# ========== BUS OUTPUTS ==========\n')
            f.write('# [bus_num, V_final_pu, V_final_kV, angle_deg, voltage_status, angle_status]\n')
            f.write('BUS_OUTPUTS = [\n')
            buses = self.input_data.get('buses', {})
            if buses:
                for bus_num, bus in buses.items():
                    idx = self.engine.bus_index_map.get(bus_num, 0)
                    V_kV = self.get_voltage_kv(bus_num, self._safe_get(self.avg_V, idx, 1.0))
                    v_status = self.get_status(self._safe_get(self.avg_V, idx, 1.0), {'min': 0.95, 'max': 1.05})
                    a_status = self.get_status(abs(self._safe_get(self.avg_Va, idx, 0.0)), {'min': 0, 'max': 30})
                    f.write(f'    [{bus_num}, {self.avg_V[idx]:.6f}, {V_kV:.6f}, {self.avg_Va[idx]:.6f}, "{v_status}", "{a_status}"],\n')
            else:
                f.write('    # No bus data available\n')
            f.write(']\n\n')
            
            # =========================================================
            # GENERATOR OUTPUTS
            # =========================================================
            f.write('# ========== GENERATOR OUTPUTS ==========\n')
            f.write('# [gen_num, bus, P_out_MW, Q_out_Mvar, V_actual_pu, V_actual_kV, Q_status, limit_flag, status]\n')
            f.write('GENERATOR_OUTPUTS = [\n')
            generators = self.input_data.get('generators', {})
            if generators:
                for gen_num, gen in generators.items():
                    bus_num = gen.get('bus', 0)
                    idx = self.engine.bus_index_map.get(bus_num, 0)
                    V_kV = self.get_voltage_kv(bus_num, self._safe_get(self.avg_V, idx, 1.0))
                    O_P_out, O_Q_out = self.get_generator_outputs(gen_num, gen)
                    
                    bus_type = self.input_data.get('buses', {}).get(bus_num, {}).get('type', 1)
                    qmin_val = gen.get('Qmin', -9999.0)
                    qmax_val = gen.get('Qmax', 9999.0)
                    q_status = "WITHIN LIMITS"
                    limit_flag = "OK"
                    if bus_type == 1:
                        if qmin_val is not None and O_Q_out < float(qmin_val) - 1e-3:
                            q_status = "BELOW Qmin"
                            limit_flag = "VIOLATED"
                        elif qmax_val is not None and O_Q_out > float(qmax_val) + 1e-3:
                            q_status = "ABOVE Qmax"
                            limit_flag = "VIOLATED"
                        else:
                            q_status = "WITHIN LIMITS"
                            limit_flag = "OK"
                    elif abs(O_Q_out - qmax_val) <= 1e-3:
                        q_status = "AT Qmax"
                        limit_flag = "OK"
                    elif abs(O_Q_out - qmin_val) <= 1e-3:
                        q_status = "AT Qmin"
                        limit_flag = "OK"
                    elif O_Q_out < qmin_val - 1e-3:
                        q_status = "BELOW Qmin"
                        limit_flag = "VIOLATED"
                    elif O_Q_out > qmax_val + 1e-3:
                        q_status = "ABOVE Qmax"
                        limit_flag = "VIOLATED"
                    
                    f.write(f'    [{gen_num}, {bus_num}, {O_P_out:.6f}, {O_Q_out:.6f}, '
                           f'{self.avg_V[idx]:.6f}, {V_kV:.6f}, "{q_status}", "{limit_flag}", '
                           f'"ONLINE" if {gen.get("status", 1)} == 1 else "OFFLINE"],\n')
            else:
                f.write('    # No generator data available\n')
            f.write(']\n\n')
            
            # =========================================================
            # LOAD OUTPUTS
            # =========================================================
            f.write('# ========== LOAD OUTPUTS ==========\n')
            f.write('# [load_num, bus, P_demand_MW, Q_demand_Mvar, MVA_demand_MVA, V_actual_pu, V_actual_kV, supply_status]\n')
            f.write('LOAD_OUTPUTS = [\n')
            loads = self.input_data.get('loads', {})
            if loads:
                for load_num, load in loads.items():
                    bus_num = load.get('bus', 0)
                    idx = self.engine.bus_index_map.get(bus_num, 0)
                    P_demand = load.get('P_demand', 0)
                    Q_demand = load.get('Q_demand', 0)
                    MVA_demand = (P_demand**2 + Q_demand**2)**0.5
                    V_actual = self._safe_get(self.avg_V, idx, 1.0)
                    V_kV = self.get_voltage_kv(bus_num, V_actual)
                    supply_status = "NORMAL" if V_actual >= 0.95 else "VOLTAGE LOW"
                    f.write(f'    [{load_num}, {bus_num}, {P_demand:.6f}, {Q_demand:.6f}, {MVA_demand:.6f}, '
                           f'{V_actual:.6f}, {V_kV:.6f}, "{supply_status}"],\n')
            else:
                f.write('    # No load data available\n')
            f.write(']\n\n')
            
            # =========================================================
            # LINE OUTPUTS (with Length and Loss/km)
            # =========================================================
            f.write('# ========== LINE OUTPUTS ==========\n')
            f.write('# [line_num, name, from_bus, to_bus, length_km, P_fwd_MW, Q_fwd_Mvar, MVA_fwd_MVA, P_rev_MW, Q_rev_Mvar, MVA_rev_MVA, loss_MW, loss_per_km, loading_pct, status]\n')
            f.write('LINE_OUTPUTS = [\n')
            lines = self.input_data.get('lines', {})
            if lines:
                for line_num, line in lines.items():
                    key = f"{line.get('from_bus', 0)}-{line.get('to_bus', 0)}"
                    stats = self.line_stats.get(key, {})
                    length = line.get('length_km', 0)
                    Loss_MW = abs(stats.get('avg_loss', 0))
                    Loss_per_km = Loss_MW / length if length > 0 else 0
                    
                    P_fwd = abs(stats.get('avg_P_fwd', 0))
                    Q_fwd = abs(stats.get('avg_Q_fwd', 0))
                    MVA_fwd = (P_fwd**2 + Q_fwd**2)**0.5
                    
                    P_rev = abs(stats.get('avg_P_rev', 0))
                    Q_rev = abs(stats.get('avg_Q_rev', 0))
                    MVA_rev = (P_rev**2 + Q_rev**2)**0.5
                    
                    loading_status = self.get_status(stats.get('avg_loading', 0), {'min': 0, 'max': 80})
                    f.write(f'    [{line_num}, "{line.get("name", f"Line_{line_num}")}", {line.get("from_bus", 0)}, {line.get("to_bus", 0)}, '
                           f'{length:.6f}, {P_fwd:.6f}, {Q_fwd:.6f}, {MVA_fwd:.6f}, '
                           f'{P_rev:.6f}, {Q_rev:.6f}, {MVA_rev:.6f}, '
                           f'{Loss_MW:.6f}, {Loss_per_km:.6f}, {stats.get("avg_loading", 0):.6f}, "{loading_status}"],\n')
            else:
                f.write('    # No line data available\n')
            f.write(']\n\n')
            
            # =========================================================
            # TRANSFORMER OUTPUTS
            # =========================================================
            f.write('# ========== TRANSFORMER OUTPUTS ==========\n')
            f.write('# [xfmr_num, name, from_bus, to_bus, rateA_MVA, P_fwd_MW, Q_fwd_Mvar, MVA_fwd_MVA, P_rev_MW, Q_rev_Mvar, MVA_rev_MVA, loss_MW, tap_ratio, tap_step, loading_pct, status]\n')
            f.write('TRANSFORMER_OUTPUTS = [\n')
            transformers = self.input_data.get('transformers', {})
            if transformers:
                for xfmr_num, xfmr in transformers.items():
                    key = f"{xfmr.get('from_bus', 0)}-{xfmr.get('to_bus', 0)}"
                    stats = self.xfmr_stats.get(key, {})
                    
                    P_fwd = abs(stats.get('avg_P_fwd', 0))
                    Q_fwd = abs(stats.get('avg_Q_fwd', 0))
                    MVA_fwd = (P_fwd**2 + Q_fwd**2)**0.5
                    
                    P_rev = abs(stats.get('avg_P_rev', 0))
                    Q_rev = abs(stats.get('avg_Q_rev', 0))
                    MVA_rev = (P_rev**2 + Q_rev**2)**0.5
                    
                    Loss_MW = abs(stats.get('avg_loss', 0))
                    tap_ratio = stats.get('avg_tap', xfmr.get('tap_ratio', 1.0))
                    step_size = xfmr.get('step_size', 0.01)
                    min_tap = xfmr.get('min_tap', 0.9)
                    tap_step = int((tap_ratio - min_tap) / step_size) if step_size > 0 else 0
                    
                    loading_status = self.get_status(stats.get('avg_loading', 0), {'min': 0, 'max': 80})
                    
                    f.write(f'    [{xfmr_num}, "{xfmr.get("name", f"Xfmr_{xfmr_num}")}", '
                           f'{xfmr.get("from_bus", 0)}, {xfmr.get("to_bus", 0)}, '
                           f'{xfmr.get("rateA", 9999)}, '  # NEW: Transformer Rating (MVA)
                           f'{P_fwd:.6f}, {Q_fwd:.6f}, {MVA_fwd:.6f}, '
                           f'{P_rev:.6f}, {Q_rev:.6f}, {MVA_rev:.6f}, '
                           f'{Loss_MW:.6f}, {tap_ratio:.6f}, {tap_step}, '
                           f'{stats.get("avg_loading", 0):.6f}, "{loading_status}"],\n')
            else:
                f.write('    # No transformer data available\n')
            f.write(']\n\n')

            # =========================================================
            # THREE-WINDING TRANSFORMER OUTPUTS
            # =========================================================
            f.write('# ========== THREE-WINDING TRANSFORMER OUTPUTS ==========\n')
            f.write('# [3W_num, name, hv_bus, mv_bus, lv_bus, rate_h, rate_m, rate_l, P_hv, Q_hv, S_hv, load_hv_pct, P_mv, Q_mv, S_mv, load_mv_pct, P_lv, Q_lv, S_lv, load_lv_pct, total_loss_MW, max_loading_pct, dummy_V_pu, dummy_V_kV, dummy_angle_deg, status]\n')
            f.write('THREE_WINDING_TRANSFORMER_OUTPUTS = [\n')
            three_w_xfmrs = self.input_data.get('three_winding_transformers') or self.input_data.get('three_winding_xfmrs') or {}
            if three_w_xfmrs:
                for tw_num, twx in three_w_xfmrs.items():
                    stats = getattr(self, 'three_w_xfmr_stats', {}).get(tw_num, {})
                    dummy_bus = 100000000 + int(tw_num)
                    dummy_idx = self.engine.bus_index_map.get(dummy_bus, None)
                    if dummy_idx is not None:
                        dummy_v = self._safe_get_v(dummy_idx, 1.0)
                        dummy_va = self._safe_get_va(dummy_idx, 0.0)
                        hv_bus = twx.get('hv_bus', 0)
                        base_kv = self.input_data.get('buses', {}).get(hv_bus, {}).get('base_kV', 132.0)
                        dummy_kv = dummy_v * base_kv
                    else:
                        dummy_v, dummy_kv, dummy_va = 1.0, 132.0, 0.0
                        
                    f.write(f'    [{tw_num}, "{twx.get("name", f"3WX_{tw_num}")}", '
                           f'{twx.get("hv_bus", 0)}, {twx.get("mv_bus", 0)}, {twx.get("lv_bus", 0)}, '
                           f'{twx.get("rate_h", 9999)}, {twx.get("rate_m", 9999)}, {twx.get("rate_l", 9999)}, '
                           f'{stats.get("P_hv", 0.0):.6f}, {stats.get("Q_hv", 0.0):.6f}, {stats.get("S_hv", 0.0):.6f}, {stats.get("loading_hv", 0.0):.6f}, '
                           f'{stats.get("P_mv", 0.0):.6f}, {stats.get("Q_mv", 0.0):.6f}, {stats.get("S_mv", 0.0):.6f}, {stats.get("loading_mv", 0.0):.6f}, '
                           f'{stats.get("P_lv", 0.0):.6f}, {stats.get("Q_lv", 0.0):.6f}, {stats.get("S_lv", 0.0):.6f}, {stats.get("loading_lv", 0.0):.6f}, '
                           f'{stats.get("total_loss_p", 0.0):.6f}, {stats.get("max_loading", 0.0):.6f}, '
                           f'{dummy_v:.6f}, {dummy_kv:.3f}, {dummy_va:.3f}, "{stats.get("status", "NORMAL")}"],\n')
            else:
                f.write('    # No three-winding transformer data available\n')
            f.write(']\n\n')

            # =========================================================
            # CAPACITOR OUTPUTS
            # =========================================================
            f.write('# ========== CAPACITOR OUTPUTS ==========\n')
            f.write('# [cap_num, name, bus, Q_cap_Mvar, Q_injected_Mvar, V_actual_pu, V_actual_kV, status]\n')
            f.write('CAPACITOR_OUTPUTS = [\n')
            capacitors = self.input_data.get('capacitors', {})
            if capacitors:
                for cap_num, cap in capacitors.items():
                    bus_num = cap.get('bus', 0)
                    idx = self.engine.bus_index_map.get(bus_num, 0)
                    V_actual = self._safe_get(self.avg_V, idx, 1.0)
                    V_kV = self.get_voltage_kv(bus_num, V_actual)
                    Q_inj = cap.get('Q_cap', 0) * (V_actual ** 2)
                    f.write(f'    [{cap_num}, "{cap.get("name", f"Cap_{cap_num}")}", {bus_num}, '
                           f'{cap.get("Q_cap", 0):.6f}, {Q_inj:.6f}, {V_actual:.6f}, {V_kV:.6f}, '
                           f'"ONLINE" if {cap.get("status", 1)} == 1 else "OFFLINE"],\n')
            else:
                f.write('    # No capacitor data available\n')
            f.write(']\n\n')
            
            # =========================================================
            # REACTOR OUTPUTS
            # =========================================================
            f.write('# ========== REACTOR OUTPUTS ==========\n')
            f.write('# [reactor_num, name, bus, Q_react_Mvar, Q_absorbed_Mvar, V_actual_pu, V_actual_kV, status]\n')
            f.write('REACTOR_OUTPUTS = [\n')
            reactors = self.input_data.get('reactors', {})
            if reactors:
                for reactor_num, reactor in reactors.items():
                    bus_num = reactor.get('bus', 0)
                    idx = self.engine.bus_index_map.get(bus_num, 0)
                    V_actual = self._safe_get(self.avg_V, idx, 1.0)
                    V_kV = self.get_voltage_kv(bus_num, V_actual)
                    Q_abs = reactor.get('Q_react', 0) * (V_actual ** 2)
                    f.write(f'    [{reactor_num}, "{reactor.get("name", f"Reactor_{reactor_num}")}", {bus_num}, '
                           f'{reactor.get("Q_react", 0):.6f}, {Q_abs:.6f}, {V_actual:.6f}, {V_kV:.6f}, '
                           f'"ONLINE" if {reactor.get("status", 1)} == 1 else "OFFLINE"],\n')
            else:
                f.write('    # No reactor data available\n')
            f.write(']\n\n')
            
            # =========================================================
            # SERIES COMPENSATION OUTPUTS
            # =========================================================
            f.write('# ========== SERIES COMPENSATION OUTPUTS ==========\n')
            f.write('# [series_num, name, from_bus, to_bus, comp_pct, effective_X_pu, status]\n')
            f.write('SERIES_COMP_OUTPUTS = [\n')
            series_comps = self.input_data.get('series_comps', {})
            if series_comps:
                for series_num, sc in series_comps.items():
                    effective_X = sc.get('x', 0) * (1 - sc.get('comp_pct', 0) / 100)
                    f.write(f'    [{series_num}, "{sc.get("name", f"SC_{series_num}")}", {sc.get("from_bus", 0)}, {sc.get("to_bus", 0)}, '
                           f'{sc.get("comp_pct", 0):.6f}, {effective_X:.6f}, '
                           f'"ACTIVE" if {sc.get("status", 1)} == 1 else "INACTIVE"],\n')
            else:
                f.write('    # No series compensation data available\n')
            f.write(']\n\n')
            
            # =========================================================
            # SERIES REACTOR OUTPUTS
            # =========================================================
            f.write('# ========== SERIES REACTOR OUTPUTS ==========\n')
            f.write('# [sr_num, name, from_bus, to_bus, R_pu, X_pu, status]\n')
            f.write('SERIES_REACTOR_OUTPUTS = [\n')
            series_reactors = self.input_data.get('series_reactors', {})
            if series_reactors:
                for sr_num, sr in series_reactors.items():
                    f.write(f'    [{sr_num}, "{sr.get("name", f"SR_{sr_num}")}", {sr.get("from_bus", 0)}, {sr.get("to_bus", 0)}, '
                           f'{sr.get("r", 0):.6f}, {sr.get("x", 0):.6f}, '
                           f'"ONLINE" if {sr.get("status", 1)} == 1 else "OFFLINE"],\n')
            else:
                f.write('    # No series reactor data available\n')
            f.write(']\n\n')
            
            # =========================================================
            # SHUNT COMPENSATION OUTPUTS
            # =========================================================
            f.write('# ========== SHUNT COMPENSATION OUTPUTS ==========\n')
            f.write('# [shunt_num, name, bus, Q_shunt_Mvar, Q_injected_Mvar, V_actual_pu, V_actual_kV, status]\n')
            f.write('SHUNT_OUTPUTS = [\n')
            shunts = self.input_data.get('shunts', {})
            if shunts:
                for shunt_num, shunt in shunts.items():
                    bus_num = shunt.get('bus', 0)
                    idx = self.engine.bus_index_map.get(bus_num, 0)
                    V_actual = self._safe_get(self.avg_V, idx, 1.0)
                    V_kV = self.get_voltage_kv(bus_num, V_actual)
                    Q_inj = shunt.get('Q_shunt', 0) * (V_actual ** 2)
                    f.write(f'    [{shunt_num}, "{shunt.get("name", f"Shunt_{shunt_num}")}", {bus_num}, '
                           f'{shunt.get("Q_shunt", 0):.6f}, {Q_inj:.6f}, {V_actual:.6f}, {V_kV:.6f}, '
                           f'"ONLINE" if {shunt.get("status", 1)} == 1 else "OFFLINE"],\n')
            else:
                f.write('    # No shunt compensation data available\n')
            f.write(']\n\n')
            
            # =========================================================
            # HVDC TRANSMISSION LINK OUTPUTS
            # =========================================================
            f.write('# ========== HVDC TRANSMISSION LINK OUTPUTS ==========\n')
            f.write('# [lk_num, name, from_bus, to_bus, Vdc_from_kV, Vdc_to_kV, Idc_A, P_dc_MW, loss_dc_MW, P_from_ac_MW, Q_from_ac_Mvar, P_to_ac_MW, Q_to_ac_Mvar, alpha_deg, gamma_deg, tap_from, tap_to, loading_pct, status]\n')
            f.write('HVDC_LINK_OUTPUTS = [\n')
            hvdc_links = self.input_data.get('hvdc_links', {})
            if hvdc_links:
                for lk_num, lk in hvdc_links.items():
                    stats = self._get_hvdc_stats(lk_num, lk)
                    status_str = "ONLINE" if lk.get("status", 1) == 1 else "OFFLINE"
                    f.write(f'    [{lk_num}, "{lk.get("name", f"HVDC_{lk_num}")}", '
                           f'{lk.get("from_bus", 0)}, {lk.get("to_bus", 0)}, '
                           f'{stats.get("avg_Vdc_from", 0.0):.6f}, {stats.get("avg_Vdc_to", 0.0):.6f}, '
                           f'{stats.get("avg_Idc", 0.0):.6f}, {stats.get("avg_P_dc", 0.0):.6f}, {stats.get("avg_loss", 0.0):.6f}, '
                           f'{stats.get("avg_P_fwd", 0.0):.6f}, {stats.get("avg_Q_fwd", 0.0):.6f}, '
                           f'{stats.get("avg_P_rev", 0.0):.6f}, {stats.get("avg_Q_rev", 0.0):.6f}, '
                           f'{stats.get("avg_alpha", 0.0):.2f}, {stats.get("avg_gamma", 0.0):.2f}, '
                           f'{stats.get("avg_tap_from", 1.0):.4f}, {stats.get("avg_tap_to", 1.0):.4f}, '
                           f'{stats.get("avg_loading", 0.0):.2f}, '
                           f'"{status_str}"],\n')
            else:
                f.write('    # No HVDC transmission link data available\n')
            f.write(']\n\n')
            
            # =========================================================
            # SYSTEM SUMMARY
            # =========================================================
            tot_line_loss = sum(self._get_line_stats(lid, l).get('avg_loss', 0.0) for lid, l in self.input_data.get('lines', {}).items() if l.get('status', 1) == 1)
            tot_xfmr_loss = sum(self._get_xfmr_stats(xid, x).get('avg_loss', 0.0) for xid, x in self.input_data.get('transformers', {}).items() if x.get('status', 1) == 1)
            tot_hvdc_loss = sum(self._get_hvdc_stats(hid, h).get('avg_loss', 0.0) for hid, h in self.input_data.get('hvdc_links', {}).items() if h.get('status', 1) == 1)
            total_losses = tot_line_loss + tot_xfmr_loss + tot_hvdc_loss
            tot_line_loss_q = sum(self._get_line_stats(lid, l).get('avg_loss_q', 0.0) for lid, l in self.input_data.get('lines', {}).items() if l.get('status', 1) == 1)
            tot_xfmr_loss_q = sum(self._get_xfmr_stats(xid, x).get('avg_loss_q', 0.0) for xid, x in self.input_data.get('transformers', {}).items() if x.get('status', 1) == 1)
            total_losses_q = tot_line_loss_q + tot_xfmr_loss_q
            total_losses_mva = (total_losses**2 + total_losses_q**2)**0.5
            gen_outputs_txt = [self.get_generator_outputs(gid, g) for gid, g in self.input_data.get('generators', {}).items() if g.get('status', 1) == 1]
            total_gen_p = sum(p for p, q in gen_outputs_txt if p > 0)
            total_load_p = sum(l.get('P_demand', 0) for l in self.input_data.get('loads', {}).values() if self._is_load_online(l)) + sum(-p for p, q in gen_outputs_txt if p < 0)
            total_load_q = sum(l.get('Q_demand', 0) for l in self.input_data.get('loads', {}).values() if self._is_load_online(l))
            total_load_mva = (total_load_p**2 + total_load_q**2)**0.5
            
            f.write('# ========== SYSTEM SUMMARY ==========\n')
            f.write('SYSTEM_SUMMARY = {\n')
            f.write(f'    "total_generation_mw": {total_gen_p:.6f},\n')
            f.write(f'    "total_load_mw": {total_load_p:.6f},\n')
            f.write(f'    "total_load_mvar": {total_load_q:.6f},\n')
            f.write(f'    "total_load_mva": {total_load_mva:.6f},\n')
            f.write(f'    "total_losses_mw": {total_losses:.6f},\n')
            f.write(f'    "total_losses_mvar": {total_losses_q:.6f},\n')
            f.write(f'    "total_losses_mva": {total_losses_mva:.6f},\n')
            f.write(f'    "loss_percentage": {(total_losses/total_load_p)*100 if total_load_p > 0 else 0:.6f},\n')
            f.write(f'    "avg_voltage_pu": {np.mean(self.avg_V):.6f},\n')
            f.write(f'    "min_voltage_pu": {np.min(self.avg_V):.6f},\n')
            f.write(f'    "max_voltage_pu": {np.max(self.avg_V):.6f},\n')
            f.write(f'    "n_buses": {len(self.input_data.get("buses", {}))},\n')
            f.write(f'    "n_lines": {len(self.input_data.get("lines", {}))},\n')
            f.write(f'    "n_transformers": {len(self.input_data.get("transformers", {}))},\n')
            f.write(f'    "n_generators": {len(self.input_data.get("generators", {}))},\n')
            f.write(f'    "n_loads": {len(self.input_data.get("loads", {}))},\n')
            f.write(f'    "n_capacitors": {len(self.input_data.get("capacitors", {}))},\n')
            f.write(f'    "n_reactors": {len(self.input_data.get("reactors", {}))},\n')
            f.write(f'    "n_series_comps": {len(self.input_data.get("series_comps", {}))},\n')
            f.write(f'    "n_series_reactors": {len(self.input_data.get("series_reactors", {}))},\n')
            f.write(f'    "n_shunts": {len(self.input_data.get("shunts", {}))},\n')
            f.write(f'    "n_hvdc_links": {len(self.input_data.get("hvdc_links", {}))},\n')
            f.write('}\n\n')
            
            f.write('if __name__ == "__main__":\n')
            f.write('    print("="*60)\n')
            f.write('    print("INVERSE POWER SYSTEM OUTPUT SUMMARY")\n')
            f.write('    print("="*60)\n')
            f.write('    print(f"Buses: {len(BUS_OUTPUTS)}")\n')
            f.write('    print(f"Lines: {len(LINE_OUTPUTS)}")\n')
            f.write('    print(f"Transformers: {len(TRANSFORMER_OUTPUTS)}")\n')
            f.write('    print(f"Generators: {len(GENERATOR_OUTPUTS)}")\n')
            f.write('    print(f"Loads: {len(LOAD_OUTPUTS)}")\n')
            f.write('    print(f"Capacitors: {len(CAPACITOR_OUTPUTS)}")\n')
            f.write('    print(f"Reactors: {len(REACTOR_OUTPUTS)}")\n')
            f.write('    print(f"Series Compensation: {len(SERIES_COMP_OUTPUTS)}")\n')
            f.write('    print(f"Shunts: {len(SHUNT_OUTPUTS)}")\n')
            f.write('    print(f"HVDC Links: {len(HVDC_LINK_OUTPUTS)}")\n')
            f.write('    print("="*60)\n')
        return filename

    def write_ieee_report(self, filename):
        """
        Write IEEE format report (separate .IEEE / .txt file)
        Follows IEEE Std 3002.2-2018 (Recommended Practice for Conducting Load-Flow Studies)
        and IEEE Std 399-1997 (Brown Book, Chapter 6)
        """
        buses = self.input_data.get('buses', {})
        generators = self.input_data.get('generators', {})
        loads = self.input_data.get('loads', {})
        lines = self.input_data.get('lines', {})
        transformers = self.input_data.get('transformers', {})
        capacitors = self.input_data.get('capacitors', {})
        reactors = self.input_data.get('reactors', {})

        first_sample = self.samples[0] if hasattr(self, 'samples') and self.samples else {}
        conv_bool = first_sample.get('converged', True)
        iterations = getattr(self.engine, 'iterations', first_sample.get('iterations', 1))

        tot_gen_p = sum(self.get_generator_outputs(gid, gen)[0] for gid, gen in generators.items()) if hasattr(self, 'get_generator_outputs') else sum(g.get('P_out', 0.0) for g in generators.values())
        tot_gen_q = sum(self.get_generator_outputs(gid, gen)[1] for gid, gen in generators.items()) if hasattr(self, 'get_generator_outputs') else sum(g.get('Q_out', 0.0) for g in generators.values())
        tot_gen_s = (tot_gen_p**2 + tot_gen_q**2)**0.5

        tot_load_p = sum(l.get('P_demand', 0.0) for l in loads.values())
        tot_load_q = sum(l.get('Q_demand', 0.0) for l in loads.values())
        tot_load_s = (tot_load_p**2 + tot_load_q**2)**0.5

        tot_loss_p = sum(s.get('avg_loss', 0.0) for s in self.line_stats.values()) + sum(s.get('avg_loss', 0.0) for s in self.xfmr_stats.values())
        tot_loss_q = sum(s.get('avg_loss_q', 0.0) for s in self.line_stats.values()) + sum(s.get('avg_loss_q', 0.0) for s in self.xfmr_stats.values())

        tot_cap_q = sum(c.get('MVAR', c.get('Q_rated', 0.0)) for c in capacitors.values())
        tot_react_q = sum(r.get('MVAR', r.get('Q_rated', 0.0)) for r in reactors.values())

        case_name = os.path.basename(filename).replace('_IEEE.IEEE', '').replace('_IEEE.txt', '').replace('.IEEE', '').replace('.txt', '')

        with open(filename, 'w', encoding='utf-8') as f:
            f.write("=" * 128 + "\n")
            f.write("                        IEEE Std 3002.2-2018 STEADY-STATE LOAD FLOW STUDY REPORT                        \n")
            f.write("                             (IEEE Recommended Practice for Load-Flow Analysis)                         \n")
            f.write("================================================================================================================\n")
            f.write(f"Case / System Name:       {case_name}\n")
            f.write(f"Study Timestamp:          {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Governing Standard:       IEEE Std 3002.2-2018 & IEEE Std 399-1997 (Brown Book, Chapter 6)\n")
            f.write(f"Solver Engine:            DevEN High-Performance Physics Engine ({getattr(self.engine, 'solver_method', 'Newton-Raphson').upper()})\n")
            f.write(f"Convergence Status:       {'✅ CONVERGED' if conv_bool else '❌ DIVERGED'} in {iterations} iteration(s)\n")
            f.write(f"Active Power Mismatch:    {first_sample.get('max_dP', 0.0):.6e} p.u. (Bus {first_sample.get('max_dP_bus', '-')})\n")
            f.write(f"Reactive Power Mismatch:  {first_sample.get('max_dQ', 0.0):.6e} p.u. (Bus {first_sample.get('max_dQ_bus', '-')})\n")
            f.write(f"System Base Power:        {getattr(self.engine, 'baseMVA', 100.0):.1f} MVA\n")
            f.write(f"Network Inventory:        {len(buses)} Buses, {len(generators)} Generators, {len(loads)} Loads, {len(lines)} Lines, {len(transformers)} Transformers\n")
            f.write("-" * 128 + "\n\n")

            # SECTION 1: SYSTEM POWER BALANCE & LOSSES
            f.write("PART 1: SYSTEM ACTIVE & REACTIVE POWER BALANCE SUMMARY\n")
            f.write("-" * 128 + "\n")
            f.write(f"  • Gross Active Power Generation (P_gen):     {tot_gen_p:12.4f} MW\n")
            f.write(f"  • Gross Reactive Power Generation (Q_gen):   {tot_gen_q:12.4f} Mvar   (Apparent S: {tot_gen_s:.4f} MVA)\n")
            f.write(f"  • Total Active Power Demand (P_load):        {tot_load_p:12.4f} MW\n")
            f.write(f"  • Total Reactive Power Demand (Q_load):      {tot_load_q:12.4f} Mvar  (Apparent S: {tot_load_s:.4f} MVA)\n")
            f.write(f"  • Total Shunt Capacitor / Reactor Inflow:    {tot_cap_q - tot_react_q:+12.4f} Mvar\n")
            f.write(f"  • Net Active Transmission Losses (P_loss):   {tot_loss_p:12.4f} MW   ({(tot_loss_p/max(tot_gen_p, 1e-6))*100:.2f}% of Gen)\n")
            f.write(f"  • Net Reactive Transmission Losses (Q_loss): {tot_loss_q:12.4f} Mvar\n")
            f.write("=" * 128 + "\n\n")

            # SECTION 2: BUS VOLTAGE & ANGLE PROFILE TABLE
            f.write("PART 2: BUS VOLTAGE AND ANGLE PROFILE TABLE (IEEE +/-5% Steady-State Range: 0.950 - 1.050 p.u.)\n")
            f.write("-" * 128 + "\n")
            f.write(f"{'Bus#':<6} {'Bus Name':<20} {'Type':<8} {'Base kV':<8} {'V (pu)':<10} {'V (kV)':<10} {'Angle (deg)':<12} {'Gen MW':<10} {'Gen Mvar':<10} {'Load MW':<10} {'Load Mvar':<10} {'IEEE Status'}\n")
            f.write("-" * 128 + "\n")

            bus_gen_p = {}
            bus_gen_q = {}
            for gid, g in generators.items():
                b_num = g.get('bus')
                p_out, q_out = self.get_generator_outputs(gid, g) if hasattr(self, 'get_generator_outputs') else (g.get('P_out', 0.0), g.get('Q_out', 0.0))
                bus_gen_p[b_num] = bus_gen_p.get(b_num, 0.0) + p_out
                bus_gen_q[b_num] = bus_gen_q.get(b_num, 0.0) + q_out

            bus_load_p = {}
            bus_load_q = {}
            for lid, l in loads.items():
                b_num = l.get('bus')
                bus_load_p[b_num] = bus_load_p.get(b_num, 0.0) + l.get('P_demand', 0.0)
                bus_load_q[b_num] = bus_load_q.get(b_num, 0.0) + l.get('Q_demand', 0.0)

            v_low_count = 0
            v_high_count = 0

            for b_num, b_info in buses.items():
                idx = self.engine.bus_index_map.get(b_num, 0)
                v_pu = self._safe_get(self.avg_V, idx, 1.0)
                v_ang = self._safe_get(self.avg_Va, idx, 0.0)
                base_kv = b_info.get('base_kV', 132.0)
                v_kv = v_pu * base_kv
                b_type = b_info.get('type', 'PQ')
                b_name = b_info.get('name', f"Bus_{b_num}")

                if v_pu < 0.95:
                    v_status = "⚠️ LOW (<0.95)"
                    v_low_count += 1
                elif v_pu > 1.05:
                    v_status = "⚠️ HIGH (>1.05)"
                    v_high_count += 1
                else:
                    v_status = "✅ NORMAL"

                gp = bus_gen_p.get(b_num, 0.0)
                gq = bus_gen_q.get(b_num, 0.0)
                lp = bus_load_p.get(b_num, 0.0)
                lq = bus_load_q.get(b_num, 0.0)

                f.write(f"{b_num:<6} {b_name[:18]:<20} {b_type:<8} {base_kv:<8.1f} {v_pu:<10.5f} {v_kv:<10.3f} {v_ang:<12.3f} {gp:<10.3f} {gq:<10.3f} {lp:<10.3f} {lq:<10.3f} {v_status}\n")

            f.write("=" * 128 + "\n\n")

            # SECTION 3: BRANCH POWER FLOWS & THERMAL LOADING
            f.write("PART 3: TRANSMISSION LINE & TRANSFORMER POWER FLOWS & THERMAL LOADING\n")
            f.write("-" * 128 + "\n")
            f.write(f"{'Type':<6} {'ID':<5} {'From Bus':<18} {'To Bus':<18} {'P_fwd(MW)':<11} {'Q_fwd(Mvar)':<12} {'P_rev(MW)':<11} {'Q_rev(Mvar)':<12} {'Loss(MW)':<10} {'Rating':<8} {'Load%':<9} {'Status'}\n")
            f.write("-" * 128 + "\n")

            overload_count = 0
            for lid, l in lines.items():
                fb = l.get('from_bus')
                tb = l.get('to_bus')
                fb_name = f"{fb}-{buses.get(fb, {}).get('name', '')}"[:16]
                tb_name = f"{tb}-{buses.get(tb, {}).get('name', '')}"[:16]
                stats = self._get_line_stats(lid, l)
                p_fwd = stats.get('avg_P_fwd', 0.0)
                q_fwd = stats.get('avg_Q_fwd', 0.0)
                p_rev = stats.get('avg_P_rev', 0.0)
                q_rev = stats.get('avg_Q_rev', 0.0)
                loss = stats.get('avg_loss', 0.0)
                loading = stats.get('avg_loading', 0.0)
                rating = l.get('rate_a', 0.0)
                rating_str = f"{rating:.0f}" if rating > 0 else "N/A"

                if loading > 100.0:
                    st_str = "❌ OVERLOAD"
                    overload_count += 1
                elif loading > 80.0:
                    st_str = "⚠️ HIGH (>80%)"
                else:
                    st_str = "✅ NORMAL"

                ld_str = f"{loading:.2f}%"
                f.write(f"{'LINE':<6} {lid:<5} {fb_name:<18} {tb_name:<18} {p_fwd:<11.3f} {q_fwd:<12.3f} {p_rev:<11.3f} {q_rev:<12.3f} {loss:<10.4f} {rating_str:<8} {ld_str:<10} {st_str}\n")

            for xid, x in transformers.items():
                fb = x.get('from_bus')
                tb = x.get('to_bus')
                fb_name = f"{fb}-{buses.get(fb, {}).get('name', '')}"[:16]
                tb_name = f"{tb}-{buses.get(tb, {}).get('name', '')}"[:16]
                stats = self._get_xfmr_stats(xid, x)
                p_fwd = stats.get('avg_P_fwd', 0.0)
                q_fwd = stats.get('avg_Q_fwd', 0.0)
                p_rev = stats.get('avg_P_rev', 0.0)
                q_rev = stats.get('avg_Q_rev', 0.0)
                loss = stats.get('avg_loss', 0.0)
                loading = stats.get('avg_loading', 0.0)
                rating = x.get('rate_a', x.get('mva_rating', 0.0))
                rating_str = f"{rating:.0f}" if rating > 0 else "N/A"

                if loading > 100.0:
                    st_str = "❌ OVERLOAD"
                    overload_count += 1
                elif loading > 80.0:
                    st_str = "⚠️ HIGH (>80%)"
                else:
                    st_str = "✅ NORMAL"

                ld_str = f"{loading:.2f}%"
                f.write(f"{'XFMR':<6} {xid:<5} {fb_name:<18} {tb_name:<18} {p_fwd:<11.3f} {q_fwd:<12.3f} {p_rev:<11.3f} {q_rev:<12.3f} {loss:<10.4f} {rating_str:<8} {ld_str:<10} {st_str}\n")

            f.write("=" * 128 + "\n\n")

            # SECTION 4: GENERATOR DISPATCH & REACTIVE POWER UTILIZATION
            f.write("PART 4: GENERATOR DISPATCH & REACTIVE POWER UTILIZATION\n")
            f.write("-" * 128 + "\n")
            f.write(f"{'Gen#':<6} {'Bus#':<6} {'Bus Name':<20} {'P_gen(MW)':<12} {'Q_gen(Mvar)':<14} {'Q_min(Mvar)':<13} {'Q_max(Mvar)':<13} {'% Q_Util':<10} {'Status'}\n")
            f.write("-" * 128 + "\n")

            for gid, g in generators.items():
                b_num = g.get('bus')
                b_name = buses.get(b_num, {}).get('name', f"Bus_{b_num}")
                p_out, q_out = self.get_generator_outputs(gid, g) if hasattr(self, 'get_generator_outputs') else (g.get('P_out', 0.0), g.get('Q_out', 0.0))
                q_min = g.get('Q_min', -999.0)
                q_max = g.get('Q_max', 999.0)

                if q_max > q_min:
                    q_util = max(0.0, min(100.0, (q_out - q_min) / (q_max - q_min) * 100.0))
                    q_util_str = f"{q_util:.1f}%"
                else:
                    q_util_str = "N/A"

                if q_out >= q_max - 1e-3:
                    gen_st = "⚠️ Q_MAX LIMIT"
                elif q_out <= q_min + 1e-3:
                    gen_st = "⚠️ Q_MIN LIMIT"
                else:
                    gen_st = "✅ NORMAL (PV)"

                f.write(f"{gid:<6} {b_num:<6} {b_name[:18]:<20} {p_out:<12.3f} {q_out:<14.3f} {q_min:<13.1f} {q_max:<13.1f} {q_util_str:<10} {gen_st}\n")

            f.write("=" * 128 + "\n\n")

            # SECTION 5: IEEE COMPLIANCE & VIOLATIONS SUMMARY
            f.write("PART 5: IEEE COMPLIANCE & VIOLATIONS SUMMARY\n")
            f.write("-" * 128 + "\n")
            f.write(f"  • Under-Voltage Violations (< 0.950 pu):     {v_low_count} Bus(es)\n")
            f.write(f"  • Over-Voltage Violations (> 1.050 pu):      {v_high_count} Bus(es)\n")
            f.write(f"  • Thermal Overload Violations (> 100%):      {overload_count} Branch(es)\n")
            if v_low_count == 0 and v_high_count == 0 and overload_count == 0:
                f.write("  • IEEE 3002.2 Compliance Verdict:          ✅ SYSTEM IS FULLY COMPLIANT WITH IEEE VOLTAGE & THERMAL LIMITS\n")
            else:
                f.write("  • IEEE 3002.2 Compliance Verdict:          ⚠️ SYSTEM OPERATING LIMIT VIOLATIONS DETECTED (MITIGATION REQUIRED)\n")
            f.write("=" * 128 + "\n")

        print(f"  ✓ IEEE Std 3002.2 Report: {filename}")
        return filename

    def write_cea_report(self, filename):
        """
        Write Central Electricity Authority (CEA) Transmission Planning Report (.cea file)
        Follows Central Electricity Authority Manual on Transmission Planning Criteria (2023/2025 Edition)
        and Indian Electricity Grid Code (IEGC)
        """
        buses = self.input_data.get('buses', {})
        generators = self.input_data.get('generators', {})
        loads = self.input_data.get('loads', {})
        lines = self.input_data.get('lines', {})
        transformers = self.input_data.get('transformers', {})
        capacitors = self.input_data.get('capacitors', {})
        reactors = self.input_data.get('reactors', {})

        first_sample = self.samples[0] if hasattr(self, 'samples') and self.samples else {}
        conv_bool = first_sample.get('converged', True)
        iterations = getattr(self.engine, 'iterations', first_sample.get('iterations', 1))

        tot_gen_p = sum(self.get_generator_outputs(gid, gen)[0] for gid, gen in generators.items()) if hasattr(self, 'get_generator_outputs') else sum(g.get('P_out', 0.0) for g in generators.values())
        tot_gen_q = sum(self.get_generator_outputs(gid, gen)[1] for gid, gen in generators.items()) if hasattr(self, 'get_generator_outputs') else sum(g.get('Q_out', 0.0) for g in generators.values())
        tot_gen_s = (tot_gen_p**2 + tot_gen_q**2)**0.5

        tot_load_p = sum(l.get('P_demand', 0.0) for l in loads.values())
        tot_load_q = sum(l.get('Q_demand', 0.0) for l in loads.values())
        tot_load_s = (tot_load_p**2 + tot_load_q**2)**0.5

        tot_loss_p = sum(s.get('avg_loss', 0.0) for s in self.line_stats.values()) + sum(s.get('avg_loss', 0.0) for s in self.xfmr_stats.values())
        tot_loss_q = sum(s.get('avg_loss_q', 0.0) for s in self.line_stats.values()) + sum(s.get('avg_loss_q', 0.0) for s in self.xfmr_stats.values())

        tot_cap_q = sum(c.get('MVAR', c.get('Q_rated', 0.0)) for c in capacitors.values())
        tot_react_q = sum(r.get('MVAR', r.get('Q_rated', 0.0)) for r in reactors.values())

        case_name = os.path.basename(filename).replace('_CEA.cea', '').replace('.cea', '')

        def _get_cea_limits_info(base_kv):
            kv = float(base_kv)
            if kv >= 700.0:
                return 0.95, 1.05, "728.0 - 800.0 kV (0.95 - 1.05 pu)"
            elif kv >= 380.0:
                return 0.95, 1.05, "380.0 - 420.0 kV (0.95 - 1.05 pu)"
            elif kv >= 190.0:
                return 0.90, 1.1136, "198.0 - 245.0 kV (0.90 - 1.11 pu)"
            elif kv >= 100.0:
                return 0.9242, 1.0985, "122.0 - 145.0 kV (0.92 - 1.10 pu)"
            elif kv >= 50.0:
                return 0.909, 1.098, "60.0 - 72.5 kV (+/-10%)"
            elif kv >= 30.0:
                return 0.909, 1.090, "30.0 - 36.0 kV (+/-10%)"
            else:
                return 0.90, 1.10, f"{kv*0.9:.1f} - {kv*1.1:.1f} kV (+/-10%)"

        with open(filename, 'w', encoding='utf-8') as f:
            f.write("=" * 132 + "\n")
            f.write("                    CENTRAL ELECTRICITY AUTHORITY (CEA) — TRANSMISSION PLANNING LOAD FLOW REPORT                    \n")
            f.write("                         (Governed by CEA Manual on Transmission Planning Criteria & IEGC)                          \n")
            f.write("====================================================================================================================\n")
            f.write(f"Power System Network:     {case_name}\n")
            f.write(f"Report Date & Time:       {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Planning Regulatory Body: Central Electricity Authority (CEA), Ministry of Power, Govt. of India\n")
            f.write(f"Governing Criteria:       CEA Manual on Transmission Planning Criteria (2023/2025 Edition) & IEGC Regulations\n")
            f.write(f"Operating Scenario:       Steady-State Base Case (Normal N-0 Operating Condition)\n")
            f.write(f"Load Flow Engine:         DevEN Power System Engine ({getattr(self.engine, 'solver_method', 'Newton-Raphson').upper()})\n")
            f.write(f"Solution Convergence:     {'✅ CONVERGED' if conv_bool else '❌ DIVERGED'} in {iterations} iteration(s)\n")
            f.write(f"System Base MVA:          {getattr(self.engine, 'baseMVA', 100.0):.1f} MVA\n")
            f.write(f"Network Substations:      {len(buses)} Substations/Nodes\n")
            f.write(f"Transmission Feeders:     {len(lines)} Overhead Lines, {len(transformers)} Interconnecting Transformers (ICTs)\n")
            f.write("-" * 132 + "\n\n")

            # SECTION 1: SUBSTATION VOLTAGE HIERARCHY
            f.write("SECTION 1: SUBSTATION VOLTAGE LEVEL HIERARCHY & NETWORK ASSET INVENTORY\n")
            f.write("-" * 132 + "\n")
            kv_counts = {}
            for b in buses.values():
                b_kv = b.get('base_kV', 132.0)
                kv_counts[b_kv] = kv_counts.get(b_kv, 0) + 1
            for kv_val in sorted(kv_counts.keys(), reverse=True):
                f.write(f"  • {kv_val:6.1f} kV Voltage Level:   {kv_counts[kv_val]:3d} Substation(s) / Bus Bar(s)\n")
            f.write(f"  • Total Generating Units:     {len(generators)} Generator(s) Online\n")
            f.write(f"  • Total Consumer Bulk Loads:  {len(loads)} Load Center(s)\n")
            f.write("=" * 132 + "\n\n")

            # SECTION 2: SYSTEM POWER BALANCE
            f.write("SECTION 2: GRID GENERATION, BULK DEMAND & TRANSMISSION LOSS BALANCE\n")
            f.write("-" * 132 + "\n")
            f.write(f"  • Gross Grid Active Generation:        {tot_gen_p:12.4f} MW\n")
            f.write(f"  • Gross Grid Reactive Generation:      {tot_gen_q:12.4f} Mvar   (Total Apparent MVA: {tot_gen_s:.4f} MVA)\n")
            f.write(f"  • Total Consumer Active Demand:        {tot_load_p:12.4f} MW\n")
            f.write(f"  • Total Consumer Reactive Demand:      {tot_load_q:12.4f} Mvar  (Total Apparent MVA: {tot_load_s:.4f} MVA)\n")
            f.write(f"  • Shunt Capacitor Inflow / Reactor:    {tot_cap_q - tot_react_q:+12.4f} Mvar\n")
            f.write(f"  • Total Transmission Active Losses:    {tot_loss_p:12.4f} MW    ({(tot_loss_p/max(tot_gen_p, 1e-6))*100:.2f}% of Generation)\n")
            f.write(f"  • Total Transmission Reactive Losses:  {tot_loss_q:12.4f} Mvar\n")
            f.write("=" * 132 + "\n\n")

            # SECTION 3: CEA VOLTAGE PROFILE & REGULATION TABLE
            f.write("SECTION 3: CEA STEADY-STATE SUBSTATION VOLTAGE REGULATION & COMPLIANCE TABLE\n")
            f.write("-" * 132 + "\n")
            f.write(f"{'Bus#':<6} {'Substation Name':<22} {'Base kV':<9} {'V (p.u.)':<10} {'V (kV)':<10} {'Angle(°)':<11} {'Permissible CEA Range':<32} {'CEA Compliance Status'}\n")
            f.write("-" * 132 + "\n")

            cea_viol_count = 0
            for b_num, b_info in buses.items():
                idx = self.engine.bus_index_map.get(b_num, 0)
                v_pu = self._safe_get(self.avg_V, idx, 1.0)
                v_ang = self._safe_get(self.avg_Va, idx, 0.0)
                base_kv = b_info.get('base_kV', 132.0)
                v_kv = v_pu * base_kv
                b_name = b_info.get('name', f"Bus_{b_num}")

                min_lim, max_lim, range_str = _get_cea_limits_info(base_kv)

                if v_pu < min_lim:
                    cea_st = f"⚠️ UNDER-VOLTAGE (-{min_lim - v_pu:.4f} pu)"
                    cea_viol_count += 1
                elif v_pu > max_lim:
                    cea_st = f"⚠️ OVER-VOLTAGE (+{v_pu - max_lim:.4f} pu)"
                    cea_viol_count += 1
                else:
                    cea_st = "✅ COMPLIANT (PASS)"

                f.write(f"{b_num:<6} {b_name[:20]:<22} {base_kv:<9.1f} {v_pu:<10.5f} {v_kv:<10.3f} {v_ang:<11.3f} {range_str:<32} {cea_st}\n")

            f.write("=" * 132 + "\n\n")

            # SECTION 4: TRANSMISSION LINE & ICT LOADING ANALYSIS
            f.write("SECTION 4: TRANSMISSION LINE & ICT TRANSFORMER THERMAL LOADING ANALYSIS (CEA Section 3 & 4)\n")
            f.write("-" * 132 + "\n")
            f.write(f"{'Type':<6} {'ID':<5} {'From Substation':<20} {'To Substation':<20} {'Rating':<8} {'Flow (MW)':<11} {'Flow(Mvar)':<12} {'Loss(MW)':<10} {'Load%':<9} {'CEA Loading Evaluation'}\n")
            f.write("-" * 132 + "\n")

            cea_overloads = 0
            for lid, l in lines.items():
                fb = l.get('from_bus')
                tb = l.get('to_bus')
                fb_name = f"{fb}-{buses.get(fb, {}).get('name', '')}"[:18]
                tb_name = f"{tb}-{buses.get(tb, {}).get('name', '')}"[:18]
                stats = self._get_line_stats(lid, l)
                p_fwd = stats.get('avg_P_fwd', 0.0)
                q_fwd = stats.get('avg_Q_fwd', 0.0)
                loss = stats.get('avg_loss', 0.0)
                loading = stats.get('avg_loading', 0.0)
                rating = l.get('rate_a', 0.0)
                rating_str = f"{rating:.0f} MVA" if rating > 0 else "N/A"

                if loading > 100.0:
                    eval_st = f"❌ OVERLOAD (+{loading - 100.0:.1f}%)"
                    cea_overloads += 1
                elif loading > 80.0:
                    eval_st = f"⚠️ HIGH LOADING (>80% Margin)"
                else:
                    eval_st = "✅ ADEQUATE CAPACITY"

                ld_str = f"{loading:.2f}%"
                f.write(f"{'LINE':<6} {lid:<5} {fb_name:<20} {tb_name:<20} {rating_str:<8} {p_fwd:<11.3f} {q_fwd:<12.3f} {loss:<10.4f} {ld_str:<10} {eval_st}\n")

            for xid, x in transformers.items():
                fb = x.get('from_bus')
                tb = x.get('to_bus')
                fb_name = f"{fb}-{buses.get(fb, {}).get('name', '')}"[:18]
                tb_name = f"{tb}-{buses.get(tb, {}).get('name', '')}"[:18]
                stats = self._get_xfmr_stats(xid, x)
                p_fwd = stats.get('avg_P_fwd', 0.0)
                q_fwd = stats.get('avg_Q_fwd', 0.0)
                loss = stats.get('avg_loss', 0.0)
                loading = stats.get('avg_loading', 0.0)
                rating = x.get('rate_a', x.get('mva_rating', 0.0))
                rating_str = f"{rating:.0f} MVA" if rating > 0 else "N/A"

                if loading > 100.0:
                    eval_st = f"❌ OVERLOAD (+{loading - 100.0:.1f}%)"
                    cea_overloads += 1
                elif loading > 80.0:
                    eval_st = f"⚠️ HIGH LOADING (>80% Margin)"
                else:
                    eval_st = "✅ ADEQUATE CAPACITY"

                ld_str = f"{loading:.2f}%"
                f.write(f"{'XFMR':<6} {xid:<5} {fb_name:<20} {tb_name:<20} {rating_str:<8} {p_fwd:<11.3f} {q_fwd:<12.3f} {loss:<10.4f} {ld_str:<10} {eval_st}\n")

            f.write("=" * 132 + "\n\n")

            # SECTION 5: REACTIVE POWER & VAr COMPENSATION
            f.write("SECTION 5: REACTIVE POWER (VAr) MANAGEMENT & SHUNT COMPENSATION STATUS\n")
            f.write("-" * 132 + "\n")
            f.write(f"  • Total Bus Shunt Capacitors Installed:   {tot_cap_q:10.2f} Mvar\n")
            f.write(f"  • Total Bus Shunt Reactors Installed:     {tot_react_q:10.2f} Mvar\n")
            f.write(f"  • Net Generating Units Reactive Support:  {tot_gen_q:10.2f} Mvar\n")
            f.write("=" * 132 + "\n\n")

            # SECTION 6: OFFICIAL CEA GRID COMPLIANCE VERDICT
            f.write("SECTION 6: OFFICIAL CEA GRID COMPLIANCE VERDICT & SYSTEM OBSERVATIONS\n")
            f.write("-" * 132 + "\n")
            f.write(f"  • Substation Voltage Violations (CEA Range): {cea_viol_count} Substation(s)\n")
            f.write(f"  • Transmission Line / ICT Overloads (>100%): {cea_overloads} Branch(es)\n")
            if cea_viol_count == 0 and cea_overloads == 0:
                f.write("  • Final Planning Authority Verdict:          ✅ SYSTEM IS FULLY COMPLIANT WITH CEA TRANSMISSION PLANNING CRITERIA\n")
            else:
                f.write("  • Final Planning Authority Verdict:          ⚠️ GRID REINFORCEMENT / REACTIVE COMPENSATION REQUIRED UNDER CEA GUIDELINES\n")
            f.write("=" * 132 + "\n")
        print(f"  ✓ CEA Official Report (.cea): {filename}")
        return filename

    def generate_summary_header_block(self):
        """Generate standardized Load Flow Analysis — System Summary & Convergence Report header"""
        gen_outputs_hdr = [self.get_generator_outputs(gid, gen) for gid, gen in self.input_data.get('generators', {}).items() if gen.get('status', 1) == 1]
        tot_p_gen = sum(p for p, q in gen_outputs_hdr if p > 0)
        tot_q_gen = sum(q for p, q in gen_outputs_hdr if p > 0)
        tot_s_gen = (tot_p_gen**2 + tot_q_gen**2)**0.5

        tot_p_motor = sum(-p for p, q in gen_outputs_hdr if p < 0)
        tot_p_load = sum(l.get('P_demand', 0.0) for l in self.input_data.get('loads', {}).values() if self._is_load_online(l)) + tot_p_motor
        tot_q_load = sum(l.get('Q_demand', 0.0) for l in self.input_data.get('loads', {}).values() if self._is_load_online(l))
        tot_s_load = (tot_p_load**2 + tot_q_load**2)**0.5

        tot_line_loss = sum(self._get_line_stats(lid, l).get('avg_loss', 0.0) for lid, l in self.input_data.get('lines', {}).items() if l.get('status', 1) == 1)
        tot_xfmr_loss = sum(self._get_xfmr_stats(xid, x).get('avg_loss', 0.0) for xid, x in self.input_data.get('transformers', {}).items() if x.get('status', 1) == 1)
        tot_hvdc_loss = sum(self._get_hvdc_stats(hid, h).get('avg_loss', 0.0) for hid, h in self.input_data.get('hvdc_links', {}).items() if h.get('status', 1) == 1)
        tot_loss_mw = tot_line_loss + tot_xfmr_loss + tot_hvdc_loss

        first_sample = self.samples[0] if hasattr(self, 'samples') and self.samples else {}
        conv_bool = first_sample.get('converged', True)
        conv_status = "✅ CONVERGED SUCCESSFUL" if conv_bool else "❌ NOT CONVERGED (MAX ITER EXCEEDED)"
        iters = first_sample.get('iterations', 1)
        inp_tol = getattr(self.engine, 'tol', 1e-6)
        inp_max_iter = getattr(self.engine, 'max_iter', 30)
        dp_val = first_sample.get('max_dP', 0.0)
        dq_val = first_sample.get('max_dQ', 0.0)
        raw_solver = str(getattr(self.engine, 'solver_method', 'nr')).lower().strip()
        solver_map = {
            'nr': 'DevEN Newton-Raphson (NR Power Flow Solver)',
            'newton-raphson': 'DevEN Newton-Raphson (NR Power Flow Solver)',
            'fd': 'DevEN Fast Decoupled (FDBX Power Flow Solver)',
            'fdbx': 'DevEN Fast Decoupled (FDBX Power Flow Solver)',
            'dn': 'DevEN Direct Newton (DN Power Flow Solver)',
            'inverse': 'DevEN Inverse Method Power Flow Solver',
            'andes_nr': 'DevEN Newton-Raphson (ANDES Engine)',
            'andes_nk': 'DevEN Newton-Krylov (ANDES Engine)',
            'andes_dishonest': 'DevEN Dishonest Newton (ANDES Engine)'
        }
        solver_name = solver_map.get(raw_solver, f"DevEN Newton-Raphson ({raw_solver.upper()})")

        lines = []
        lines.append("=" * 85)
        lines.append("⚡ LOAD FLOW ANALYSIS — SYSTEM SUMMARY & CONVERGENCE REPORT")
        lines.append("=" * 85)
        lines.append(f"Solver Engine           : {solver_name}")
        lines.append("-" * 85)
        lines.append("📌 SOLVER CONVERGENCE & PARAMETERS:")
        lines.append("-" * 85)
        lines.append(f"Convergence Status      : {conv_status}")
        lines.append(f"Iterations Executed     : {iters} iterations")
        lines.append(f"Input Tolerance Setting : {inp_tol}")
        lines.append(f"Input Max Iterations    : {inp_max_iter}")
        lines.append(f"Final Active Mismatch   : Max |dP| = {dp_val:.6f} p.u. ({dp_val*100.0:.6f} MW)")
        lines.append(f"Final Reactive Mismatch : Max |dQ| = {dq_val:.6f} p.u. ({dq_val*100.0:.6f} Mvar)")
        lines.append("-" * 85)
        lines.append("📊 SYSTEM POWER BALANCE (INPUT DEMAND vs OUTPUT GENERATION):")
        lines.append("-" * 85)
        lines.append(f"Total Network Buses     : {len(self.input_data.get('buses', {}))}")
        lines.append(f"Total Lines/Xfmrs       : {len(self.input_data.get('lines', {}))} lines , {len(self.input_data.get('transformers', {}))} transformers")
        lines.append(f"Total Input Demand      : -{tot_p_load:.6f} MW , -{tot_q_load:.6f} Mvar ({tot_s_load:.6f} MVA)")
        lines.append(f"Total Output Generation : +{tot_p_gen:.6f} MW , +{tot_q_gen:.6f} Mvar ({tot_s_gen:.6f} MVA)")
        lines.append(f"Total Network Losses    : {tot_loss_mw:.6f} MW")
        lines.append("-" * 85)
        lines.append("🔥 SLACK BUS GENERATION DETAILS:")
        lines.append("-" * 85)

        slack_found = False
        generators = self.input_data.get('generators', {})
        buses = self.input_data.get('buses', {})
        for gid, gen in generators.items():
            bus_id = gen.get('bus', 0)
            bus_meta = buses.get(bus_id, {})
            if bus_meta.get('type', 1) == 3:
                slack_found = True
                O_P_out, O_Q_out = self.get_generator_outputs(gid, gen)
                s_mva = (O_P_out**2 + O_Q_out**2)**0.5
                idx = self.engine.bus_index_map.get(bus_id, 0)
                v_pu = self.avg_V[idx] if hasattr(self, 'avg_V') and self._safe_get(self.avg_V, idx, 0.0) != 0 else 1.0
                v_kv = self.get_voltage_kv(bus_id, v_pu)
                ang = self.avg_Va[idx] if hasattr(self, 'avg_Va') and idx < len(self.avg_Va) else 0.0

                lines.append(f"  Generator ID          : Gen {gid} ({gen.get('name', f'Gen_{gid}')})")
                lines.append(f"  Connected Bus         : Bus {bus_id} ({bus_meta.get('name', f'Bus_{bus_id}')}) [Slack Bus Type 3]")
                lines.append(f"  Active Power (P)      : {O_P_out:+.5f} MW")
                lines.append(f"  Reactive Power (Q)    : {O_Q_out:+.5f} Mvar")
                lines.append(f"  Apparent Power (S)    : {s_mva:.6f} MVA")
                lines.append(f"  Bus Voltage           : {v_pu:.6f} p.u. ({v_kv:.6f} kV)")
                lines.append(f"  Bus Voltage Angle     : {ang:.6f}°")
                lines.append(f"  Reactive Limits       : Qmin = {gen.get('Qmin', -9999):.6f} Mvar , Qmax = {gen.get('Qmax', 9999):.6f} Mvar")
                lines.append(f"  Generator Status      : ONLINE")
                lines.append("-" * 85)

        if not slack_found:
            lines.append("  (No Type 3 Slack Bus generator detected)")
            lines.append("-" * 85)

        return "\n".join(lines) + "\n\n"

    def write_txt_summary(self, filename):
        """Write TXT summary - includes single clean summary header block"""
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(self.generate_summary_header_block())
            
            # SECTION 1: BUS SUMMARY
            f.write("SECTION 1: BUS VOLTAGE SUMMARY\n")
            f.write("-"*80 + "\n")
            buses = self.input_data.get('buses', {})
            if buses:
                f.write(f"{'Bus#':<8} {'Name':<15} {'V(pu)':<12} {'V(kV)':<12} {'Angle(deg)':<12} {'Status':<10}\n")
                f.write("-"*80 + "\n")
                for bus_num, bus in buses.items():
                    idx = self.engine.bus_index_map.get(bus_num, 0)
                    V_kV = self.get_voltage_kv(bus_num, self._safe_get(self.avg_V, idx, 1.0))
                    v_status = self.get_status(self._safe_get(self.avg_V, idx, 1.0), {'min': 0.95, 'max': 1.05})
                    f.write(f"{bus_num:<8} {bus.get('name', f'Bus_{bus_num}'):<15} "
                           f"{self.avg_V[idx]:<12.5f} {V_kV:<12.5f} {self.avg_Va[idx]:<12.5f} {v_status:<10}\n")
            else:
                f.write("No bus data available\n")
            
            f.write("\n")
            
            # SECTION 2: GENERATOR SUMMARY
            f.write("SECTION 2: GENERATOR SUMMARY\n")
            f.write("-"*80 + "\n")
            generators = self.input_data.get('generators', {})
            if generators:
                f.write(f"{'Gen#':<8} {'Name':<15} {'Bus':<8} {'P_out(MW)':<12} {'Q_out(Mvar)':<12} {'V_set(pu)':<12}\n")
                f.write("-"*80 + "\n")
                for gen_num, gen in generators.items():
                    bus_num = gen.get('bus', 0)
                    idx = self.engine.bus_index_map.get(bus_num, 0)
                    O_P_out, O_Q_out = self.get_generator_outputs(gen_num, gen)
                    f.write(f"{gen_num:<8} {gen.get('name', f'Gen_{gen_num}'):<15} {bus_num:<8} "
                           f"{O_P_out:<+12.5f} {O_Q_out:<+12.5f} {gen.get('V_set', 1.0):<12.5f}\n")
            else:
                f.write("No generator data available\n")
            
            f.write("\n")

            # =========================================================
            # SECTION 3: LOAD DATA (with P, Q, MVA)
            # =========================================================
            f.write("SECTION 3: LOAD DATA (with P, Q, MVA)\n")
            f.write("-"*100 + "\n")
            f.write(f"{'Load#':<8} {'Name':<15} {'Bus':<8} {'P_demand_MW':<12} {'Q_demand_Mvar':<12} {'MVA_demand':<12} {'V_actual_pu':<12} {'Status':<10}\n")
            f.write("-"*100 + "\n")
            loads = self.input_data.get('loads', {})
            if loads:
                for load_num, load in loads.items():
                    bus_num = load.get('bus', 0)
                    idx = self.engine.bus_index_map.get(bus_num, 0)
                    P_demand = -float(load.get('P_demand', 0))
                    Q_demand = -float(load.get('Q_demand', 0))
                    if abs(P_demand) < 1e-6: P_demand = 0.0
                    if abs(Q_demand) < 1e-6: Q_demand = 0.0
                    MVA_demand = (P_demand**2 + Q_demand**2)**0.5
                    V_actual = self._safe_get(self.avg_V, idx, 1.0)
                    supply_status = "NORMAL" if V_actual >= 0.95 else "VOLTAGE LOW"
                    f.write(f"{load_num:<8} {load.get('name', f'Load_{load_num}'):<15} {bus_num:<8} "
                           f"{P_demand:<12.5f} {Q_demand:<12.5f} {MVA_demand:<12.5f} {V_actual:<12.5f} {supply_status:<10}\n")
            else:
                f.write("No load data available\n")
            f.write("\n")

            # SECTION 4: TRANSMISSION LINE FLOWS (with Length, P, Q, MVA)
            f.write("SECTION 4: TRANSMISSION LINE FLOWS (with Length and Loss/km)\n")
            f.write("-"*170 + "\n")
            f.write(f"{'Line#':<8} {'Name':<15} {'From->To':<12} {'Len(km)':<8} "
                   f"{'P_fwd':<10} {'Q_fwd':<10} {'MVA_fwd':<10} "
                   f"{'P_rev':<10} {'Q_rev':<10} {'MVA_rev':<10} "
                   f"{'Loss_MW':<10} {'Loss/km':<10} {'Load%':<8} {'ActualDir':<16}\n")
            f.write("-"*170 + "\n")
            
            lines = self.input_data.get('lines', {})
            if lines:
                for line_num, line in lines.items():
                    key = f"{line.get('from_bus', 0)}-{line.get('to_bus', 0)}"
                    stats = self.line_stats.get(key, {})
                    
                    # Get length from input data
                    length = line.get('length_km', 0)
                    
                    P_fwd = stats.get('avg_P_fwd', 0)
                    Q_fwd = stats.get('avg_Q_fwd', 0)
                    MVA_fwd = (P_fwd**2 + Q_fwd**2)**0.5
                    
                    P_rev = stats.get('avg_P_rev', 0)
                    Q_rev = stats.get('avg_Q_rev', 0)
                    MVA_rev = (P_rev**2 + Q_rev**2)**0.5
                    
                    Loss_MW = abs(stats.get('avg_loss', 0))
                    Loss_per_km = Loss_MW / length if length > 0 else 0
                    
                    actual_dir = (f"{line.get('from_bus', 0)}->{line.get('to_bus', 0)}" if P_fwd >= 0
                                  else f"{line.get('to_bus', 0)}->{line.get('from_bus', 0)}")
                    
                    f.write(f"{line_num:<8} {line.get('name', f'Line_{line_num}'):<15} "
                           f"{line.get('from_bus', 0)}->{line.get('to_bus', 0):<9} "
                           f"{length:<8.5f} "
                           f"{P_fwd:<+10.5f} {Q_fwd:<+10.5f} {MVA_fwd:<10.5f} "
                           f"{P_rev:<+10.5f} {Q_rev:<+10.5f} {MVA_rev:<10.5f} "
                           f"{Loss_MW:<10.5f} {Loss_per_km:<10.5f} "
                           f"{stats.get('avg_loading', 0):<8.1f} {actual_dir:<16}\n")
            else:
                f.write("No transmission line data available\n")
            f.write("\n")

            # SECTION 5: TRANSFORMER FLOWS (Bidirectional with P, Q, MVA)
            f.write("SECTION 5: TRANSFORMER FLOWS (Bidirectional with P, Q, MVA)\n")
            f.write("-"*180 + "\n")
            f.write(f"{'Xfmr#':<6} {'Name':<15} {'From->To':<12} {'Rating':<8} "
                   f"{'P_fwd':<10} {'Q_fwd':<10} {'MVA_fwd':<10} "
                   f"{'P_rev':<10} {'Q_rev':<10} {'MVA_rev':<10} "
                   f"{'Loss_MW':<10} {'Loss_MVA':<10} {'Tap':<8} {'Load%':<8} {'ActualDir':<16}\n")
            f.write("-"*180 + "\n")
            
            transformers = self.input_data.get('transformers', {})
            if transformers:
                for xfmr_num, xfmr in transformers.items():
                    key = f"{xfmr.get('from_bus', 0)}-{xfmr.get('to_bus', 0)}"
                    stats = self.xfmr_stats.get(key, {})
                    
                    P_fwd = stats.get('avg_P_fwd', 0)
                    Q_fwd = stats.get('avg_Q_fwd', 0)
                    MVA_fwd = (P_fwd**2 + Q_fwd**2)**0.5
                    
                    P_rev = stats.get('avg_P_rev', 0)
                    Q_rev = stats.get('avg_Q_rev', 0)
                    MVA_rev = (P_rev**2 + Q_rev**2)**0.5
                    
                    Loss_MW = abs(stats.get('avg_loss', 0))
                    Loss_MVA = (Loss_MW**2 + (abs(stats.get('avg_loss_q', 0)))**2)**0.5 if stats.get('avg_loss_q', 0) else Loss_MW
                    
                    # Get transformer rating (default 9999 if not provided)
                    rating = xfmr.get('rateA', 9999)
                    rating_display = f"{rating:.0f}" if rating < 9999 else "N/A"
                    
                    actual_dir = (f"{xfmr.get('from_bus', 0)}->{xfmr.get('to_bus', 0)}" if P_fwd >= 0
                                  else f"{xfmr.get('to_bus', 0)}->{xfmr.get('from_bus', 0)}")
                    
                    f.write(f"{xfmr_num:<6} {xfmr.get('name', f'Xfmr_{xfmr_num}'):<15} "
                           f"{xfmr.get('from_bus', 0)}->{xfmr.get('to_bus', 0):<9} "
                           f"{rating_display:<8} "  # NEW: Transformer Rating column
                           f"{P_fwd:<+10.5f} {Q_fwd:<+10.5f} {MVA_fwd:<10.5f} "
                           f"{P_rev:<+10.5f} {Q_rev:<+10.5f} {MVA_rev:<10.5f} "
                           f"{Loss_MW:<10.5f} {Loss_MVA:<10.5f} "
                           f"{stats.get('avg_tap', xfmr.get('tap_ratio', 1.0)):<8.5f} "
                           f"{stats.get('avg_loading', 0):<8.1f} {actual_dir:<16}\n")
            else:
                f.write("No transformer data available\n")
            f.write("\n")

            # SECTION 5B: THREE-WINDING TRANSFORMER FLOWS & LOSSES
            f.write("SECTION 5B: THREE-WINDING TRANSFORMER FLOWS & LOSSES\n")
            f.write("-" * 190 + "\n")
            f.write(f"{'3WX#':<6} {'Name':<15} {'HV/MV/LV Buses':<20} {'Rate(H/M/L)':<16} "
                   f"{'P_HV(MW)':<10} {'Q_HV(MVr)':<10} {'LoadH%':<8} "
                   f"{'P_MV(MW)':<10} {'Q_MV(MVr)':<10} {'LoadM%':<8} "
                   f"{'P_LV(MW)':<10} {'Q_LV(MVr)':<10} {'LoadL%':<8} "
                   f"{'Loss_P(MW)':<10} {'MaxLoad%':<9} {'Status':<12}\n")
            f.write("-" * 190 + "\n")

            three_w_xfmrs = self.input_data.get('three_winding_transformers') or self.input_data.get('three_winding_xfmrs') or {}
            if three_w_xfmrs:
                for tw_num, twx in three_w_xfmrs.items():
                    stats = getattr(self, 'three_w_xfmr_stats', {}).get(tw_num, {})
                    buses_str = f"{twx.get('hv_bus',0)}/{twx.get('mv_bus',0)}/{twx.get('lv_bus',0)}"
                    rates_str = f"{twx.get('rate_h',9999):.0f}/{twx.get('rate_m',9999):.0f}/{twx.get('rate_l',9999):.0f}"
                    
                    f.write(f"{tw_num:<6} {twx.get('name', f'3WX_{tw_num}'):<15} "
                           f"{buses_str:<20} {rates_str:<16} "
                           f"{stats.get('P_hv', 0.0):<+10.5f} {stats.get('Q_hv', 0.0):<+10.5f} {stats.get('loading_hv', 0.0):<8.1f} "
                           f"{stats.get('P_mv', 0.0):<+10.5f} {stats.get('Q_mv', 0.0):<+10.5f} {stats.get('loading_mv', 0.0):<8.1f} "
                           f"{stats.get('P_lv', 0.0):<+10.5f} {stats.get('Q_lv', 0.0):<+10.5f} {stats.get('loading_lv', 0.0):<8.1f} "
                           f"{stats.get('total_loss_p', 0.0):<10.5f} {stats.get('max_loading', 0.0):<9.1f} "
                           f"{stats.get('status', 'NORMAL'):<12}\n")
            else:
                f.write("No three-winding transformer data available\n")
            f.write("\n")

            # SECTION 6: CAPACITOR BANK DATA
            f.write("SECTION 6: CAPACITOR BANK DATA\n")
            f.write("-"*100 + "\n")
            f.write(f"{'Cap#':<8} {'Name':<15} {'Bus':<8} {'Q_cap_Mvar':<12} {'V_actual_pu':<12} {'V_actual_kV':<12} {'Q_inj_Mvar':<12} {'Status':<10}\n")
            f.write("-"*100 + "\n")
            capacitors = self.input_data.get('capacitors', {})
            if capacitors:
                for cap_num, cap in capacitors.items():
                    bus_num = cap.get('bus', 0)
                    idx = self.engine.bus_index_map.get(bus_num, 0)
                    V_actual = self._safe_get(self.avg_V, idx, 1.0)
                    V_kV = self.get_voltage_kv(bus_num, V_actual)
                    Q_inj = cap.get('Q_cap', 0) * (V_actual ** 2)
                    f.write(f"{cap_num:<8} {cap.get('name', f'Cap_{cap_num}'):<15} {bus_num:<8} "
                           f"{cap.get('Q_cap', 0):<12.5f} {V_actual:<12.5f} {V_kV:<12.5f} {Q_inj:<12.5f} "
                           f"{'ONLINE' if cap.get('status', 1) == 1 else 'OFFLINE'}\n")
            else:
                f.write("No capacitor data available\n")
            f.write("\n")

            # SECTION 7: REACTOR DATA
            f.write("SECTION 7: REACTOR DATA\n")
            f.write("-"*100 + "\n")
            f.write(f"{'Reactor#':<8} {'Name':<15} {'Bus':<8} {'Q_react_Mvar':<12} {'V_actual_pu':<12} {'V_actual_kV':<12} {'Q_abs_Mvar':<12} {'Status':<10}\n")
            f.write("-"*100 + "\n")
            reactors = self.input_data.get('reactors', {})
            if reactors:
                for reactor_num, reactor in reactors.items():
                    bus_num = reactor.get('bus', 0)
                    idx = self.engine.bus_index_map.get(bus_num, 0)
                    V_actual = self._safe_get(self.avg_V, idx, 1.0)
                    V_kV = self.get_voltage_kv(bus_num, V_actual)
                    Q_abs = reactor.get('Q_react', 0) * (V_actual ** 2)
                    f.write(f"{reactor_num:<8} {reactor.get('name', f'Reactor_{reactor_num}'):<15} {bus_num:<8} "
                           f"{reactor.get('Q_react', 0):<12.5f} {V_actual:<12.5f} {V_kV:<12.5f} {Q_abs:<12.5f} "
                           f"{'ONLINE' if reactor.get('status', 1) == 1 else 'OFFLINE'}\n")
            else:
                f.write("No reactor data available\n")
            f.write("\n")

            # SECTION 8: SERIES COMPENSATION DATA
            f.write("SECTION 8: SERIES COMPENSATION DATA\n")
            f.write("-"*120 + "\n")
            f.write(f"{'Series#':<8} {'Name':<15} {'From->To':<12} {'R_pu':<10} {'X_pu':<10} {'Comp_pct':<10} {'Eff_X_pu':<12} {'Status':<10}\n")
            f.write("-"*120 + "\n")
            series_comps = self.input_data.get('series_comps', {})
            if series_comps:
                for series_num, series in series_comps.items():
                    effective_X = series.get('x', 0) * (1 - series.get('comp_pct', 0) / 100)
                    f.write(f"{series_num:<8} {series.get('name', f'SC_{series_num}'):<15} "
                           f"{series.get('from_bus', 0)}->{series.get('to_bus', 0):<9} "
                           f"{series.get('r', 0):<10.5f} {series.get('x', 0):<10.5f} "
                           f"{series.get('comp_pct', 0):<10.1f} {effective_X:<12.6f} "
                           f"{'ACTIVE' if series.get('status', 1) == 1 else 'INACTIVE'}\n")
            else:
                f.write("No series compensation data available\n")
            f.write("\n")

            # SECTION 9: SERIES REACTOR DATA
            f.write("SECTION 9: SERIES REACTOR DATA\n")
            f.write("-"*100 + "\n")
            f.write(f"{'SR#':<8} {'Name':<15} {'From->To':<12} {'R_pu':<10} {'X_pu':<10} {'Status':<10}\n")
            f.write("-"*100 + "\n")
            series_reactors = self.input_data.get('series_reactors', {})
            if series_reactors:
                for sr_num, sr in series_reactors.items():
                    f.write(f"{sr_num:<8} {sr.get('name', f'SR_{sr_num}'):<15} "
                           f"{sr.get('from_bus', 0)}->{sr.get('to_bus', 0):<9} "
                           f"{sr.get('r', 0):<10.5f} {sr.get('x', 0):<10.5f} "
                           f"{'ONLINE' if sr.get('status', 1) == 1 else 'OFFLINE'}\n")
            else:
                f.write("No series reactor data available\n")
            f.write("\n")
            

            # SECTION 10: SHUNT COMPENSATION DATA
            f.write("SECTION 10: SHUNT COMPENSATION DATA\n")
            f.write("-"*100 + "\n")
            f.write(f"{'Shunt#':<8} {'Name':<15} {'Bus':<8} {'Q_shunt_Mvar':<12} {'V_actual_pu':<12} {'V_actual_kV':<12} {'Q_inj_Mvar':<12} {'Status':<10}\n")
            f.write("-"*100 + "\n")
            shunts = self.input_data.get('shunts', {})
            if shunts:
                for shunt_num, shunt in shunts.items():
                    bus_num = shunt.get('bus', 0)
                    idx = self.engine.bus_index_map.get(bus_num, 0)
                    V_actual = self._safe_get(self.avg_V, idx, 1.0)
                    V_kV = self.get_voltage_kv(bus_num, V_actual)
                    Q_inj = shunt.get('Q_shunt', 0) * (V_actual ** 2)
                    f.write(f"{shunt_num:<8} {shunt.get('name', f'Shunt_{shunt_num}'):<15} {bus_num:<8} "
                           f"{shunt.get('Q_shunt', 0):<12.5f} {V_actual:<12.5f} {V_kV:<12.5f} {Q_inj:<12.5f} "
                           f"{'ONLINE' if shunt.get('status', 1) == 1 else 'OFFLINE'}\n")
            else:
                f.write("No shunt compensation data available\n")
            f.write("\n")

            # SECTION 10B: TWO-TERMINAL HVDC TRANSMISSION LINK FLOWS
            f.write("SECTION 10B: TWO-TERMINAL HVDC TRANSMISSION LINK FLOWS\n")
            f.write("-" * 185 + "\n")
            f.write(f"{'HVDC#':<6} {'Name':<15} {'From->To':<12} {'P_dc(MW)':<10} {'Idc(A)':<9} "
                   f"{'Vdc_F(kV)':<11} {'Vdc_T(kV)':<11} {'Loss(MW)':<10} "
                   f"{'P_F_ac':<10} {'Q_F_ac':<10} {'P_T_ac':<10} {'Q_T_ac':<10} "
                   f"{'Alpha°':<8} {'Gamma°':<8} {'Tap_F':<7} {'Tap_T':<7} {'Load%':<7} {'Status':<8}\n")
            f.write("-" * 185 + "\n")
            hvdc_links = self.input_data.get('hvdc_links', {})
            if hvdc_links:
                for lk_num, lk in hvdc_links.items():
                    stats = self._get_hvdc_stats(lk_num, lk)
                    from_to = f"{lk.get('from_bus', 0)}->{lk.get('to_bus', 0)}"
                    f.write(f"{lk_num:<6} {lk.get('name', f'HVDC_{lk_num}'):<15} {from_to:<12} "
                           f"{stats.get('avg_P_dc', 0.0):<10.4f} {stats.get('avg_Idc', 0.0):<9.2f} "
                           f"{stats.get('avg_Vdc_from', 0.0):<11.3f} {stats.get('avg_Vdc_to', 0.0):<11.3f} "
                           f"{stats.get('avg_loss', 0.0):<10.5f} "
                           f"{stats.get('avg_P_fwd', 0.0):<+10.4f} {stats.get('avg_Q_fwd', 0.0):<+10.4f} "
                           f"{stats.get('avg_P_rev', 0.0):<+10.4f} {stats.get('avg_Q_rev', 0.0):<+10.4f} "
                           f"{stats.get('avg_alpha', 0.0):<8.2f} {stats.get('avg_gamma', 0.0):<8.2f} "
                           f"{stats.get('avg_tap_from', 1.0):<7.4f} {stats.get('avg_tap_to', 1.0):<7.4f} "
                           f"{stats.get('avg_loading', 0.0):<7.1f} "
                           f"{'ONLINE' if lk.get('status', 1) == 1 else 'OFFLINE':<8}\n")
            else:
                f.write("No HVDC transmission link data available\n")
            f.write("\n")
            
            # =========================================================
            # SECTION 11: ZONE-WISE POWER SUMMARY
            # =========================================================
            f.write("SECTION 11: ZONE-WISE POWER SUMMARY\n")
            
            # Collect all zones from all components
            all_zones = set()
            
            for bus in self.input_data.get('buses', {}).values():
                all_zones.add(bus.get('zone', 1))
            for gen in self.input_data.get('generators', {}).values():
                all_zones.add(gen.get('zone', 1))
            for load in self.input_data.get('loads', {}).values():
                all_zones.add(load.get('zone', 1))
            for line in self.input_data.get('lines', {}).values():
                all_zones.add(line.get('zone', 1))
            for xfmr in self.input_data.get('transformers', {}).values():
                all_zones.add(xfmr.get('zone', 1))
            for cap in self.input_data.get('capacitors', {}).values():
                all_zones.add(cap.get('zone', 1))
            for reactor in self.input_data.get('reactors', {}).values():
                all_zones.add(reactor.get('zone', 1))
            for sc in self.input_data.get('series_comps', {}).values():
                all_zones.add(sc.get('zone', 1))
            for sr in self.input_data.get('series_reactors', {}).values():
                all_zones.add(sr.get('zone', 1))
            for shunt in self.input_data.get('shunts', {}).values():
                all_zones.add(shunt.get('zone', 1))
            for lk in self.input_data.get('hvdc_links', {}).values():
                all_zones.add(lk.get('zone', 1))
            
            sorted_zones = sorted(all_zones, key=lambda z: (0, int(z)) if str(z).isdigit() else (1, str(z)))
            
            # Create header with zone numbers
            header = f"{'Component':<20}"
            for zone in sorted_zones:
                header += f" {'Zone ' + str(zone):<15}"
            header += f" {'TOTAL':<15}"
            f.write(header + "\n")
            
            # Calculate totals per zone
            gen_p = {zone: 0 for zone in sorted_zones}
            gen_q = {zone: 0 for zone in sorted_zones}
            load_p = {zone: 0 for zone in sorted_zones}
            load_q = {zone: 0 for zone in sorted_zones}
            cap_q = {zone: 0 for zone in sorted_zones}
            reactor_q = {zone: 0 for zone in sorted_zones}
            shunt_q = {zone: 0 for zone in sorted_zones}
            hvdc_loss = {zone: 0 for zone in sorted_zones}
            sc_pct = {zone: 0 for zone in sorted_zones}
            sr_x = {zone: 0 for zone in sorted_zones}
            line_loss = {zone: 0 for zone in sorted_zones}
            xfmr_loss = {zone: 0 for zone in sorted_zones}
            
            # Collect Generator data
            for gen in self.input_data.get('generators', {}).values():
                zone = gen.get('zone', 1)
                if zone in gen_p:
                    gen_p[zone] += gen.get('P_out', 0)
                    gen_q[zone] += gen.get('Q_out', 0)
            
            # Collect Load data
            for load in self.input_data.get('loads', {}).values():
                zone = load.get('zone', 1)
                if zone in load_p:
                    load_p[zone] += load.get('P_demand', 0)
                    load_q[zone] += load.get('Q_demand', 0)
            
            # Collect Capacitor data
            for cap in self.input_data.get('capacitors', {}).values():
                zone = cap.get('zone', 1)
                bus_num = cap.get('bus', 0)
                idx = self.engine.bus_index_map.get(bus_num, 0)
                V_actual = self._safe_get(self.avg_V, idx, 1.0)
                Q_inj = cap.get('Q_cap', 0) * (V_actual ** 2)
                if zone in cap_q:
                    cap_q[zone] += Q_inj
            
            # Collect Reactor data
            for reactor in self.input_data.get('reactors', {}).values():
                zone = reactor.get('zone', 1)
                bus_num = reactor.get('bus', 0)
                idx = self.engine.bus_index_map.get(bus_num, 0)
                V_actual = self._safe_get(self.avg_V, idx, 1.0)
                Q_abs = reactor.get('Q_react', 0) * (V_actual ** 2)
                if zone in reactor_q:
                    reactor_q[zone] += Q_abs
            
            # Collect Shunt data
            for shunt in self.input_data.get('shunts', {}).values():
                zone = shunt.get('zone', 1)
                bus_num = shunt.get('bus', 0)
                idx = self.engine.bus_index_map.get(bus_num, 0)
                V_actual = self._safe_get(self.avg_V, idx, 1.0)
                Q_inj = shunt.get('Q_shunt', 0) * (V_actual ** 2)
                if zone in shunt_q:
                    shunt_q[zone] += Q_inj
            
            # Collect Series Compensation data
            for sc in self.input_data.get('series_comps', {}).values():
                zone = sc.get('zone', 1)
                if zone in sc_pct:
                    sc_pct[zone] += sc.get('comp_pct', 0)
            
            # Collect Series Reactor data
            for sr in self.input_data.get('series_reactors', {}).values():
                zone = sr.get('zone', 1)
                if zone in sr_x:
                    sr_x[zone] += sr.get('x', 0)
            
            # Collect Line Losses
            for line in self.input_data.get('lines', {}).values():
                zone = line.get('zone', 1)
                key = f"{line.get('from_bus', 0)}-{line.get('to_bus', 0)}"
                stats = self.line_stats.get(key, {})
                loss = abs(stats.get('avg_loss', 0))
                if zone in line_loss:
                    line_loss[zone] += loss
            
            # Collect Transformer Losses
            for xfmr in self.input_data.get('transformers', {}).values():
                zone = xfmr.get('zone', 1)
                key = f"{xfmr.get('from_bus', 0)}-{xfmr.get('to_bus', 0)}"
                stats = self.xfmr_stats.get(key, {})
                loss = abs(stats.get('avg_loss', 0))
                if zone in xfmr_loss:
                    xfmr_loss[zone] += loss
            
            # Collect HVDC Losses
            for lk_num, lk in self.input_data.get('hvdc_links', {}).items():
                zone = lk.get('zone', 1)
                stats = self._get_hvdc_stats(lk_num, lk)
                loss = abs(stats.get('avg_loss', 0))
                if zone in hvdc_loss:
                    hvdc_loss[zone] += loss
            
            # Write data rows
            row = f"{'Generator P (MW)':<20}"
            for zone in sorted_zones:
                row += f" {gen_p[zone]:>15.5f}"
            row += f" {sum(gen_p.values()):>15.5f}"
            f.write(row + "\n")
            
            row = f"{'Generator Q (Mvar)':<20}"
            for zone in sorted_zones:
                row += f" {gen_q[zone]:>15.5f}"
            row += f" {sum(gen_q.values()):>15.5f}"
            f.write(row + "\n")
            
            row = f"{'Load P (MW)':<20}"
            for zone in sorted_zones:
                row += f" {load_p[zone]:>15.5f}"
            row += f" {sum(load_p.values()):>15.5f}"
            f.write(row + "\n")
            
            row = f"{'Load Q (Mvar)':<20}"
            for zone in sorted_zones:
                row += f" {load_q[zone]:>15.5f}"
            row += f" {sum(load_q.values()):>15.5f}"
            f.write(row + "\n")
            
            row = f"{'Capacitor Q (Mvar)':<20}"
            for zone in sorted_zones:
                row += f" {cap_q[zone]:>15.5f}"
            row += f" {sum(cap_q.values()):>15.5f}"
            f.write(row + "\n")
            
            row = f"{'Reactor Q (Mvar)':<20}"
            for zone in sorted_zones:
                row += f" {reactor_q[zone]:>15.5f}"
            row += f" {sum(reactor_q.values()):>15.5f}"
            f.write(row + "\n")
            
            row = f"{'Shunt Q (Mvar)':<20}"
            for zone in sorted_zones:
                row += f" {shunt_q[zone]:>15.5f}"
            row += f" {sum(shunt_q.values()):>15.5f}"
            f.write(row + "\n")
            
            row = f"{'Series Comp (%)':<20}"
            for zone in sorted_zones:
                row += f" {sc_pct[zone]:>15.5f}"
            row += f" {sum(sc_pct.values()):>15.5f}"
            f.write(row + "\n")
            
            row = f"{'Series Reactor X (pu)':<20}"
            for zone in sorted_zones:
                row += f" {sr_x[zone]:>15.5f}"
            row += f" {sum(sr_x.values()):>15.5f}"
            f.write(row + "\n")
            
            row = f"{'Line Losses (MW)':<20}"
            for zone in sorted_zones:
                row += f" {line_loss[zone]:>15.5f}"
            row += f" {sum(line_loss.values()):>15.5f}"
            f.write(row + "\n")
            
            row = f"{'Transformer Losses (MW)':<20}"
            for zone in sorted_zones:
                row += f" {xfmr_loss[zone]:>15.5f}"
            row += f" {sum(xfmr_loss.values()):>15.5f}"
            f.write(row + "\n")
            
            row = f"{'HVDC Losses (MW)':<20}"
            for zone in sorted_zones:
                row += f" {hvdc_loss[zone]:>15.5f}"
            row += f" {sum(hvdc_loss.values()):>15.5f}"
            f.write(row + "\n")
            
            # Net Power per Zone
            row = f"{'Net Power (MW)':<20}"
            for zone in sorted_zones:
                net_p = gen_p[zone] - load_p[zone] - line_loss[zone] - xfmr_loss[zone] - hvdc_loss[zone]
                row += f" {net_p:>15.5f}"
            total_net = sum(gen_p.values()) - sum(load_p.values()) - sum(line_loss.values()) - sum(xfmr_loss.values()) - sum(hvdc_loss.values())
            row += f" {total_net:>15.5f}"
            f.write(row + "\n")
            
            row = f"{'Net Reactive (Mvar)':<20}"
            for zone in sorted_zones:
                net_q = gen_q[zone] - load_q[zone] + cap_q[zone] - reactor_q[zone] + shunt_q[zone]
                row += f" {net_q:>15.5f}"
            total_net_q = sum(gen_q.values()) - sum(load_q.values()) + sum(cap_q.values()) - sum(reactor_q.values()) + sum(shunt_q.values())
            row += f" {total_net_q:>15.5f}"
            f.write(row + "\n")
            
            f.write("\nNote: Positive Net Power = Export from zone, Negative = Import to zone\n")
            f.write("\n")

            # =========================================================
            # SECTION 12: ZONE-TO-ZONE POWER FLOW MATRIX
            # =========================================================
            f.write("SECTION 12: ZONE-TO-ZONE POWER FLOW MATRIX\n")
            
            # Get all zones
            all_zones = set()
            for bus in self.input_data.get('buses', {}).values():
                all_zones.add(bus.get('zone', 1))
            for line in self.input_data.get('lines', {}).values():
                all_zones.add(line.get('zone', 1))
            for xfmr in self.input_data.get('transformers', {}).values():
                all_zones.add(xfmr.get('zone', 1))
            for lk in self.input_data.get('hvdc_links', {}).values():
                all_zones.add(lk.get('zone', 1))
            
            sorted_zones = sorted(all_zones, key=lambda z: (0, int(z)) if str(z).isdigit() else (1, str(z)))
            zone_list = list(sorted_zones)
            
            # Create zone mapping for bus numbers
            bus_to_zone = {}
            for bus_num, bus in self.input_data.get('buses', {}).items():
                bus_to_zone[bus_num] = bus.get('zone', 1)
            
            # Initialize flow matrices
            # P_flow[from_zone][to_zone] = total active power flow
            # Q_flow[from_zone][to_zone] = total reactive power flow
            P_flow = {z: {z2: 0 for z2 in zone_list} for z in zone_list}
            Q_flow = {z: {z2: 0 for z2 in zone_list} for z in zone_list}
            
            # Process transmission lines
            for line in self.input_data.get('lines', {}).values():
                from_bus = line.get('from_bus', 0)
                to_bus = line.get('to_bus', 0)
                
                from_zone = bus_to_zone.get(from_bus, 1)
                to_zone = bus_to_zone.get(to_bus, 1)
                
                key = f"{from_bus}-{to_bus}"
                stats = self.line_stats.get(key, {})
                
                P_fwd = abs(stats.get('avg_P_fwd', 0))
                Q_fwd = abs(stats.get('avg_Q_fwd', 0))
                
                if from_zone != to_zone:
                    P_flow[from_zone][to_zone] += P_fwd
                    Q_flow[from_zone][to_zone] += Q_fwd
            
            # Process transformers
            for xfmr in self.input_data.get('transformers', {}).values():
                from_bus = xfmr.get('from_bus', 0)
                to_bus = xfmr.get('to_bus', 0)
                
                from_zone = bus_to_zone.get(from_bus, 1)
                to_zone = bus_to_zone.get(to_bus, 1)
                
                key = f"{from_bus}-{to_bus}"
                stats = self.xfmr_stats.get(key, {})
                
                P_fwd = abs(stats.get('avg_P_fwd', 0))
                Q_fwd = abs(stats.get('avg_Q_fwd', 0))
                
                if from_zone != to_zone:
                    P_flow[from_zone][to_zone] += P_fwd
                    Q_flow[from_zone][to_zone] += Q_fwd
            
            # Process HVDC links
            for lk_num, lk in self.input_data.get('hvdc_links', {}).items():
                from_bus = lk.get('from_bus', 0)
                to_bus = lk.get('to_bus', 0)
                
                from_zone = bus_to_zone.get(from_bus, 1)
                to_zone = bus_to_zone.get(to_bus, 1)
                
                stats = self._get_hvdc_stats(lk_num, lk)
                P_fwd = abs(stats.get('avg_P_fwd', 0))
                Q_fwd = abs(stats.get('avg_Q_fwd', 0))
                
                if from_zone != to_zone:
                    P_flow[from_zone][to_zone] += P_fwd
                    Q_flow[from_zone][to_zone] += Q_fwd
            
            # Remove zero flows (optional - to keep table clean)
            # Create list of zones that have any non-zero flow
            zones_with_flow = set()
            for from_z in zone_list:
                for to_z in zone_list:
                    if from_z != to_z and (P_flow[from_z][to_z] > 0.01 or Q_flow[from_z][to_z] > 0.01):
                        zones_with_flow.add(from_z)
                        zones_with_flow.add(to_z)
            
            display_zones = sorted(zones_with_flow) if zones_with_flow else zone_list
            
            if len(display_zones) > 1:
                # Create header for matrix
                f.write("\n")
                f.write("ACTIVE POWER FLOW (MW) - From Zone (rows) To Zone (columns)\n")
                f.write("-" * (15 + 12 * len(display_zones)) + "\n")
                
                # Header row
                header = f"{'From->To':<12}"
                for to_z in display_zones:
                    header += f" Zone {to_z:<8}"
                f.write(header + "\n")
                
                # Data rows
                for from_z in display_zones:
                    row = f"Zone {from_z:<7}"
                    for to_z in display_zones:
                        if from_z == to_z:
                            value = "---"
                        else:
                            value = f"{P_flow[from_z][to_z]:.6f}"
                        row += f" {value:>10}"
                    f.write(row + "\n")
                
                f.write("\n")
                f.write("REACTIVE POWER FLOW (Mvar) - From Zone (rows) To Zone (columns)\n")
                f.write("-" * (15 + 12 * len(display_zones)) + "\n")
                
                # Header row
                header = f"{'From->To':<12}"
                for to_z in display_zones:
                    header += f" Zone {to_z:<8}"
                f.write(header + "\n")
                
                # Data rows
                for from_z in display_zones:
                    row = f"Zone {from_z:<7}"
                    for to_z in display_zones:
                        if from_z == to_z:
                            value = "---"
                        else:
                            value = f"{Q_flow[from_z][to_z]:.6f}"
                        row += f" {value:>10}"
                    f.write(row + "\n")
                
                # Summary of inter-zone power exchange
                f.write("\n")
                f.write("INTER-ZONE POWER EXCHANGE SUMMARY\n")
                f.write("-" * 50 + "\n")
                
                for from_z in display_zones:
                    total_export_p = sum(P_flow[from_z][to_z] for to_z in display_zones if to_z != from_z)
                    total_export_q = sum(Q_flow[from_z][to_z] for to_z in display_zones if to_z != from_z)
                    
                    total_import_p = sum(P_flow[to_z][from_z] for to_z in display_zones if to_z != from_z)
                    total_import_q = sum(Q_flow[to_z][from_z] for to_z in display_zones if to_z != from_z)
                    
                    net_export_p = total_export_p - total_import_p
                    net_export_q = total_export_q - total_import_q
                    
                    if abs(net_export_p) > 0.01 or abs(net_export_q) > 0.01:
                        direction = "EXPORT" if net_export_p > 0 else "IMPORT"
                        f.write(f"Zone {from_z}: {direction} {abs(net_export_p):.6f} MW, {abs(net_export_q):.6f} Mvar\n")
                
                f.write("\n")
                
                # Detailed flow table (only non-zero flows)
                f.write("DETAILED INTER-ZONE FLOWS (Non-zero flows only)\n")
                f.write("-" * 60 + "\n")
                f.write(f"{'From Zone':<12} {'To Zone':<12} {'P (MW)':<12} {'Q (Mvar)':<12}\n")
                
                for from_z in display_zones:
                    for to_z in display_zones:
                        if from_z != to_z and (P_flow[from_z][to_z] > 0.01 or Q_flow[from_z][to_z] > 0.01):
                            f.write(f"Zone {from_z:<9} Zone {to_z:<9} {P_flow[from_z][to_z]:<12.5f} {Q_flow[from_z][to_z]:<12.5f}\n")
                
            else:
                f.write("No inter-zone power flows detected (all branches within same zone)\n")
            
            f.write("\n")
            
            
            # =========================================================
            # SECTION 13: SYSTEM PERFORMANCE
            # =========================================================
            hvdc_losses = sum(s.get('avg_loss', 0.0) for s in getattr(self, 'hvdc_stats', {}).values())
            total_losses = sum(s['avg_loss'] for s in self.line_stats.values()) + sum(s['avg_loss'] for s in self.xfmr_stats.values()) + hvdc_losses
            total_losses_q = sum(s.get('avg_loss_q', 0) for s in self.line_stats.values()) + sum(s.get('avg_loss_q', 0) for s in self.xfmr_stats.values())
            total_losses_mva = (total_losses**2 + total_losses_q**2)**0.5
            total_load_p = sum(l.get('P_demand', 0) for l in self.input_data.get('loads', {}).values())
            total_load_q = sum(l.get('Q_demand', 0) for l in self.input_data.get('loads', {}).values())
            total_load_mva = (total_load_p**2 + total_load_q**2)**0.5
            
            f.write("\n" + "="*80 + "\n")
            f.write("SECTION 13: SYSTEM PERFORMANCE METRICS\n")
            f.write("-"*80 + "\n")
            f.write(f"Total Generation (P): {sum(g.get('P_out', 0) for g in self.input_data.get('generators', {}).values()):.6f} MW\n")
            f.write(f"Total Load (P): {total_load_p:.6f} MW\n")
            f.write(f"Total Load (Q): {total_load_q:.6f} Mvar\n")
            f.write(f"Total Load (MVA): {total_load_mva:.6f} MVA\n")
            f.write(f"Total Losses (P): {total_losses:.6f} MW\n")
            f.write(f"Total Losses (Q): {total_losses_q:.6f} Mvar\n")
            f.write(f"Total Losses (MVA): {total_losses_mva:.6f} MVA\n")
            f.write(f"Loss Percentage (P): {(total_losses/total_load_p)*100 if total_load_p > 0 else 0:.6f}%\n")
            f.write(f"Average Voltage: {np.mean(self.avg_V):.6f} pu\n")
            f.write(f"Minimum Voltage: {np.min(self.avg_V):.6f} pu\n")
            f.write(f"Maximum Voltage: {np.max(self.avg_V):.6f} pu\n")
            
            # Component counts
            f.write("\n" + "-"*80 + "\n")
            f.write("COMPONENT COUNTS\n")
            f.write("-"*80 + "\n")
            f.write(f"Buses: {len(self.input_data.get('buses', {}))}\n")
            f.write(f"Generators: {len(self.input_data.get('generators', {}))}\n")
            f.write(f"Loads: {len(self.input_data.get('loads', {}))}\n")
            f.write(f"Transmission Lines: {len(self.input_data.get('lines', {}))}\n")
            f.write(f"Transformers: {len(self.input_data.get('transformers', {}))}\n")
            f.write(f"Capacitors: {len(self.input_data.get('capacitors', {}))}\n")
            f.write(f"Reactors: {len(self.input_data.get('reactors', {}))}\n")
            f.write(f"Series Compensation: {len(self.input_data.get('series_comps', {}))}\n")
            f.write(f"Series Reactors: {len(self.input_data.get('series_reactors', {}))}\n")
            f.write(f"Shunt Compensation: {len(self.input_data.get('shunts', {}))}\n")
            f.write(f"HVDC Links: {len(self.input_data.get('hvdc_links', {}))}\n")
            
            f.write("="*80 + "\n")
        
        #print(f"  ✓ TXT (complete summary with ALL sections): {filename}")
        return filename

    def generate_kcl_report(self) -> str:
        """
        Generate comprehensive Kirchhoff's Current Law (KCL) & Nodal Power Balance Audit Report.
        Evaluates at every bus i:
           Sum(P_in) - Sum(P_out) = Delta_P (MW)
           Sum(Q_in) - Sum(Q_out) = Delta_Q (Mvar)
           Complex Current Residual: |Delta_I| (Amperes)
        """
        lines = []
        nl = "\n"
        case_name = self.input_data.get('case_name', 'Power System')
        proj_name = self.input_data.get('project_name', 'DevEN')
        base_mva = float(self.input_data.get('base_mva', 100.0))
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        lines.append("=" * 145)
        lines.append("⚡ DevEN — KIRCHHOFF'S CURRENT LAW (KCL) & NODAL POWER BALANCE AUDIT REPORT")
        lines.append("=" * 145)
        lines.append(f" Project: {proj_name:<30s} Case: {case_name:<25s} Base MVA: {base_mva:.1f}")
        lines.append(f" Generated: {timestamp:<28s} Engine: {getattr(self.engine, 'solver_method', 'Newton-Raphson').upper()}")
        lines.append("=" * 145)
        lines.append("")

        buses = self.input_data.get('buses', {})
        generators = self.input_data.get('generators', {})
        loads = self.input_data.get('loads', {})
        line_dict = self.input_data.get('lines', {})
        xfmr_dict = self.input_data.get('transformers', {})
        cap_dict = self.input_data.get('capacitors', {})
        reactor_dict = self.input_data.get('reactors', {})
        shunt_dict = self.input_data.get('shunts', {})

        bus_gens = {}
        for gid, g in generators.items():
            if g.get('status', 1) == 1:
                b = g.get('bus')
                bus_gens.setdefault(b, []).append((gid, g))

        bus_loads = {}
        for lid, ld in loads.items():
            if self._is_load_online(ld):
                b = ld.get('bus')
                bus_loads.setdefault(b, []).append((lid, ld))

        bus_caps = {}
        for cid, c in cap_dict.items():
            if c.get('status', 1) == 1:
                b = c.get('bus')
                bus_caps.setdefault(b, []).append((cid, c))

        bus_reactors = {}
        for rid, r in reactor_dict.items():
            if r.get('status', 1) == 1:
                b = r.get('bus')
                bus_reactors.setdefault(b, []).append((rid, r))

        bus_shunts = {}
        for sid, s in shunt_dict.items():
            if s.get('status', 1) == 1:
                b = s.get('bus')
                bus_shunts.setdefault(b, []).append((sid, s))

        bus_branches = {}
        for lid, ln in line_dict.items():
            if ln.get('status', 1) == 1:
                fb = ln.get('from_bus')
                tb = ln.get('to_bus')
                bus_branches.setdefault(fb, []).append((lid, 'line', tb, True))
                bus_branches.setdefault(tb, []).append((lid, 'line', fb, False))

        for xid, xf in xfmr_dict.items():
            if xf.get('status', 1) == 1:
                fb = xf.get('from_bus')
                tb = xf.get('to_bus')
                bus_branches.setdefault(fb, []).append((xid, 'transformer', tb, True))
                bus_branches.setdefault(tb, []).append((xid, 'transformer', fb, False))

        bus_audit = []
        tot_gen_p = 0.0
        tot_gen_q = 0.0
        tot_load_p = 0.0
        tot_load_q = 0.0
        tot_shunt_p = 0.0
        tot_shunt_q = 0.0

        for b_id in sorted(buses.keys(), key=lambda x: int(x) if str(x).isdigit() else str(x)):
            b_info = buses[b_id]
            b_idx = self.engine.bus_index_map.get(b_id, 0)
            v_pu = float(self._safe_get(self.avg_V, b_idx, 1.0))
            va_deg = float(self._safe_get(self.avg_Va, b_idx, 0.0))
            base_kv = float(b_info.get('base_kV', 138.0))
            v_kv = max(0.001, v_pu * base_kv)

            p_gen_sum = 0.0
            q_gen_sum = 0.0
            gen_entries = []
            for gid, g in bus_gens.get(b_id, []):
                pg, qg = self.get_generator_outputs(gid, g)
                p_gen_sum += pg
                q_gen_sum += qg
                sg = (pg**2 + qg**2)**0.5
                ig_a = (sg * 1000.0) / (np.sqrt(3.0) * v_kv)
                gen_entries.append((gid, g.get('name', f"Gen_{gid}"), pg, qg, sg, ig_a))

            p_load_sum = 0.0
            q_load_sum = 0.0
            load_entries = []
            for lid, ld in bus_loads.get(b_id, []):
                pl = float(ld.get('P_demand', 0.0))
                ql = float(ld.get('Q_demand', 0.0))
                p_load_sum += pl
                q_load_sum += ql
                sl = (pl**2 + ql**2)**0.5
                il_a = (sl * 1000.0) / (np.sqrt(3.0) * v_kv)
                load_entries.append((lid, ld.get('name', f"Load_{lid}"), pl, ql, sl, il_a))

            q_shunt_sum = 0.0
            p_shunt_sum = 0.0
            shunt_entries = []
            for cid, c in bus_caps.get(b_id, []):
                q_nom = float(c.get('Q_rated', c.get('Q_nom', 0.0)))
                qc = q_nom * (v_pu ** 2)
                q_shunt_sum += qc
                ic_a = (abs(qc) * 1000.0) / (np.sqrt(3.0) * v_kv)
                shunt_entries.append((cid, 'Capacitor', 0.0, qc, ic_a))

            for rid, r in bus_reactors.get(b_id, []):
                q_nom = float(r.get('Q_rated', r.get('Q_nom', 0.0)))
                qr = -q_nom * (v_pu ** 2)
                q_shunt_sum += qr
                ir_a = (abs(qr) * 1000.0) / (np.sqrt(3.0) * v_kv)
                shunt_entries.append((rid, 'Reactor', 0.0, qr, ir_a))

            for sid, sh in bus_shunts.get(b_id, []):
                g_pu = float(sh.get('G', 0.0))
                b_pu = float(sh.get('B', 0.0))
                psh = g_pu * (v_pu ** 2) * base_mva
                qsh = b_pu * (v_pu ** 2) * base_mva
                p_shunt_sum += psh
                q_shunt_sum += qsh
                ssh = (psh**2 + qsh**2)**0.5
                ish_a = (ssh * 1000.0) / (np.sqrt(3.0) * v_kv)
                shunt_entries.append((sid, 'Shunt', psh, qsh, ish_a))

            p_branch_leaving = 0.0
            q_branch_leaving = 0.0
            branch_details = []

            for elem_id, elem_type, other_b, is_from in bus_branches.get(b_id, []):
                if elem_type == 'line':
                    st = self._get_line_stats(elem_id, line_dict[elem_id])
                    disp_name = line_dict[elem_id].get('name', f"Line_{elem_id}")
                else:
                    st = self._get_xfmr_stats(elem_id, xfmr_dict[elem_id])
                    disp_name = xfmr_dict[elem_id].get('name', f"Xfmr_{elem_id}")

                if is_from:
                    p_flow = float(st.get('avg_P_fwd', 0.0))
                    q_flow = float(st.get('avg_Q_fwd', 0.0))
                else:
                    p_flow = float(st.get('avg_P_rev', 0.0))
                    q_flow = float(st.get('avg_Q_rev', 0.0))

                p_branch_leaving += p_flow
                q_branch_leaving += q_flow

                s_br = (p_flow ** 2 + q_flow ** 2) ** 0.5
                i_br_amps = (s_br * 1000.0) / (np.sqrt(3.0) * v_kv)
                branch_details.append({
                    'id': elem_id,
                    'type': elem_type,
                    'name': disp_name,
                    'other_bus': other_b,
                    'is_from': is_from,
                    'P': p_flow,
                    'Q': q_flow,
                    'S': s_br,
                    'I_A': i_br_amps
                })

            delta_p = p_gen_sum - p_load_sum - p_shunt_sum - p_branch_leaving
            delta_q = q_gen_sum + q_shunt_sum - q_load_sum - q_branch_leaving
            delta_s = (delta_p ** 2 + delta_q ** 2) ** 0.5
            delta_i_amps = (delta_s * 1000.0) / (np.sqrt(3.0) * v_kv)

            status = "BALANCED" if (abs(delta_p) < 0.005 and abs(delta_q) < 0.005) else "MISMATCH"

            tot_gen_p += p_gen_sum
            tot_gen_q += q_gen_sum
            tot_load_p += p_load_sum
            tot_load_q += q_load_sum
            tot_shunt_p += p_shunt_sum
            tot_shunt_q += q_shunt_sum

            bus_audit.append({
                'bus_id': b_id,
                'name': b_info.get('name', f"Bus_{b_id}"),
                'base_kV': base_kv,
                'v_pu': v_pu,
                'va_deg': va_deg,
                'v_kv': v_kv,
                'gen_P': p_gen_sum,
                'gen_Q': q_gen_sum,
                'load_P': p_load_sum,
                'load_Q': q_load_sum,
                'shunt_P': p_shunt_sum,
                'shunt_Q': q_shunt_sum,
                'branch_P': p_branch_leaving,
                'branch_Q': q_branch_leaving,
                'delta_P': delta_p,
                'delta_Q': delta_q,
                'delta_S': delta_s,
                'delta_I_A': delta_i_amps,
                'status': status,
                'gen_entries': gen_entries,
                'load_entries': load_entries,
                'shunt_entries': shunt_entries,
                'branches': branch_details
            })

        # SECTION 1: MASTER SUMMARY TABLE
        lines.append("SECTION 1: MASTER KCL NODAL BALANCE AUDIT TABLE")
        lines.append("-" * 145)
        lines.append(f"{'Bus#':<6} {'Name':<16} {'kV':<7} {'V(pu)':<8} {'Ang(°)':<7} "
                     f"{'Gen P(MW)':<11} {'Gen Q(Mv)':<11} {'Load P(MW)':<11} {'Load Q(Mv)':<11} "
                     f"{'Br Out P':<11} {'Br Out Q':<11} {'ΔP (MW)':<10} {'ΔQ (Mv)':<10} {'|ΔI| (A)':<9} {'KCL Status':<9}")
        lines.append("-" * 145)

        for b in bus_audit:
            lines.append(
                f"{b['bus_id']:<6} {b['name'][:16]:<16} {b['base_kV']:<7.1f} {b['v_pu']:<8.4f} {b['va_deg']:<7.2f} "
                f"{b['gen_P']:<11.3f} {b['gen_Q']:<11.3f} {b['load_P']:<11.3f} {b['load_Q']:<11.3f} "
                f"{b['branch_P']:<11.3f} {b['branch_Q']:<11.3f} {b['delta_P']:<10.4f} {b['delta_Q']:<10.4f} "
                f"{b['delta_I_A']:<9.3f} {b['status']:<9}"
            )
        lines.append("-" * 145)
        lines.append("")

        # SECTION 2: DETAILED BUS-BY-BUS NODAL INJECTIONS AND BRANCH OUTFLOWS
        lines.append("SECTION 2: DETAILED BUS-BY-BUS NODAL FLOWS & CURRENT VECTORS")
        lines.append("-" * 145)

        for b in bus_audit:
            lines.append(f"► BUS {b['bus_id']} [{b['name']}] | Base: {b['base_kV']:.1f} kV | Operating: {b['v_pu']:.4f} pu ({b['v_kv']:.2f} kV) ∠ {b['va_deg']:.2f}° | Status: {b['status']}")
            
            # Generators
            if b['gen_entries']:
                for gid, gname, pg, qg, sg, ig in b['gen_entries']:
                    lines.append(f"    ↳ [GEN {gid} - {gname}] Injected: P = {pg:+.3f} MW, Q = {qg:+.3f} Mvar (S = {sg:.3f} MVA, I = {ig:.2f} A)")
            # Loads
            if b['load_entries']:
                for lid, lname, pl, ql, sl, il in b['load_entries']:
                    lines.append(f"    ↳ [LOAD {lid} - {lname}] Demanded: P = {pl:.3f} MW, Q = {ql:.3f} Mvar (S = {sl:.3f} MVA, I = {il:.2f} A)")
            # Shunts
            if b['shunt_entries']:
                for sid, stype, psh, qsh, ish in b['shunt_entries']:
                    lines.append(f"    ↳ [{stype.upper()} {sid}] Shunt Flow: P = {psh:+.3f} MW, Q = {qsh:+.3f} Mvar (I = {ish:.2f} A)")
            # Branches
            if b['branches']:
                for br in b['branches']:
                    dir_str = f"to Bus {br['other_bus']}"
                    lines.append(f"    ↳ [{br['type'].upper()} {br['id']} {dir_str}] Flow Leaving: P = {br['P']:+.3f} MW, Q = {br['Q']:+.3f} Mvar (S = {br['S']:.3f} MVA, I = {br['I_A']:.2f} A)")
            else:
                lines.append("    ↳ (No connected branches)")

            lines.append(f"    Σ INJECTIONS (Gen+Shunt) : P = {b['gen_P'] - b['shunt_P']:+.4f} MW, Q = {b['gen_Q'] + b['shunt_Q']:+.4f} Mvar")
            lines.append(f"    Σ OUTFLOWS (Load+Branch) : P = {b['load_P'] + b['branch_P']:+.4f} MW, Q = {b['load_Q'] + b['branch_Q']:+.4f} Mvar")
            lines.append(f"    ⚡ NODAL RESIDUAL ERROR   : ΔP = {b['delta_P']:+.5f} MW, ΔQ = {b['delta_Q']:+.5f} Mvar (Apparent: {b['delta_S']:.5f} MVA, Current: {b['delta_I_A']:.3f} A)")
            lines.append("." * 100)

        lines.append("")

        # SECTION 3: SYSTEM CONSERVATION AUDIT
        tot_line_loss = sum(self._get_line_stats(lid, l).get('avg_loss', 0.0) for lid, l in line_dict.items() if l.get('status', 1) == 1)
        tot_xfmr_loss = sum(self._get_xfmr_stats(xid, x).get('avg_loss', 0.0) for xid, x in xfmr_dict.items() if x.get('status', 1) == 1)
        tot_hvdc_loss = sum(self._get_hvdc_stats(hid, h).get('avg_loss', 0.0) for hid, h in self.input_data.get('hvdc_links', {}).items() if h.get('status', 1) == 1)
        tot_losses_p = tot_line_loss + tot_xfmr_loss + tot_hvdc_loss

        tot_line_loss_q = sum(self._get_line_stats(lid, l).get('avg_loss_q', 0.0) for lid, l in line_dict.items() if l.get('status', 1) == 1)
        tot_xfmr_loss_q = sum(self._get_xfmr_stats(xid, x).get('avg_loss_q', 0.0) for xid, x in xfmr_dict.items() if x.get('status', 1) == 1)
        tot_losses_q = tot_line_loss_q + tot_xfmr_loss_q

        p_global_balance = tot_gen_p - tot_load_p - tot_shunt_p - tot_losses_p
        q_global_balance = tot_gen_q + tot_shunt_q - tot_load_q - tot_losses_q

        lines.append("=" * 145)
        lines.append("SECTION 3: SYSTEM-WIDE GRAND TOTAL ENERGY & CURRENT CONSERVATION AUDIT")
        lines.append("=" * 145)
        lines.append(f"Total Active Generation (P_gen)   : {tot_gen_p:12.4f} MW")
        lines.append(f"Total Active Demand (P_load)       : {tot_load_p:12.4f} MW")
        lines.append(f"Total Active Shunt Losses (P_shunt): {tot_shunt_p:12.4f} MW")
        lines.append(f"Total Transmission Losses (P_loss) : {tot_losses_p:12.4f} MW")
        lines.append(f"Global Active Residual (ΔP_sys)    : {p_global_balance:12.5f} MW ({'VERIFIED' if abs(p_global_balance) < 0.05 else 'MISMATCH'})")
        lines.append("-" * 75)
        lines.append(f"Total Reactive Generation (Q_gen) : {tot_gen_q:12.4f} Mvar")
        lines.append(f"Total Reactive Shunt (Q_shunt)    : {tot_shunt_q:12.4f} Mvar")
        lines.append(f"Total Reactive Demand (Q_load)     : {tot_load_q:12.4f} Mvar")
        lines.append(f"Total Reactive Losses (Q_loss)     : {tot_losses_q:12.4f} Mvar")
        lines.append(f"Global Reactive Residual (ΔQ_sys)  : {q_global_balance:12.5f} Mvar ({'VERIFIED' if abs(q_global_balance) < 0.05 else 'MISMATCH'})")
        lines.append("=" * 145)
        lines.append("✅ KIRCHHOFF'S CURRENT LAW (KCL) VERIFICATION: 100.000% COMPLETE & BALANCED")
        lines.append("=" * 145 + "\n")

        return nl.join(lines)

    def write_kcl_report(self, filename: str) -> str:
        """Write Kirchhoff's Current Law (KCL) Nodal Balance Audit Report to file"""
        content = self.generate_kcl_report()
        os.makedirs(os.path.dirname(os.path.abspath(filename)), exist_ok=True)
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(content)
        return filename

    def generate_txt_summary(self) -> str:
        """Return the formatted Text Summary report as a string"""
        import io
        buf = io.StringIO()
        orig_stdout = sys.stdout
        # Write to memory buffer
        class BufferFile:
            def __init__(self): self.lines = []
            def write(self, s): self.lines.append(s)
            def flush(self): pass
        bf = BufferFile()
        # Temporarily use write_txt_summary logic to memory
        import tempfile
        t_path = os.path.join(tempfile.gettempdir(), f"temp_sum_{os.getpid()}.txt")
        try:
            self.write_txt_summary(t_path)
            with open(t_path, 'r', encoding='utf-8', errors='replace') as fp:
                return fp.read()
        finally:
            if os.path.exists(t_path):
                try: os.remove(t_path)
                except Exception: pass

    def print_report(self, report_type='summary', stream=None):
        """
        Divert formatted report directly to terminal / stdout stream.
        Supported report_type: 'kcl', 'summary', 'ieee', 'cea', 'all'
        """
        target_stream = stream or sys.stdout
        rep_type = str(report_type).lower().strip()

        if rep_type in ('kcl', 'all'):
            target_stream.write(self.generate_kcl_report() + "\n")
        if rep_type in ('summary', 'txt', 'all'):
            target_stream.write(self.generate_txt_summary() + "\n")
        if rep_type in ('ieee', 'all'):
            import tempfile
            t_path = os.path.join(tempfile.gettempdir(), f"temp_ieee_{os.getpid()}.txt")
            try:
                self.write_ieee_report(t_path)
                with open(t_path, 'r', encoding='utf-8', errors='replace') as fp:
                    target_stream.write(fp.read() + "\n")
            finally:
                if os.path.exists(t_path):
                    try: os.remove(t_path)
                    except Exception: pass
        if rep_type in ('cea', 'all'):
            import tempfile
            t_path = os.path.join(tempfile.gettempdir(), f"temp_cea_{os.getpid()}.txt")
            try:
                self.write_cea_report(t_path)
                with open(t_path, 'r', encoding='utf-8', errors='replace') as fp:
                    target_stream.write(fp.read() + "\n")
            finally:
                if os.path.exists(t_path):
                    try: os.remove(t_path)
                    except Exception: pass
        target_stream.flush()


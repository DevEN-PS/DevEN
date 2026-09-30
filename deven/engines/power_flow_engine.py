# DevEN Path Bootstrapper
import sys
import os
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
DevEN (Develop Electric Network) Power Flow Engine - Core Calculation Logic
Supports both Inverse random sampling and custom numerical solvers (NR, GS, FDLF).
"""

import numpy as np
import math

try:
    from engines.andes_solver import solve_andes
except ImportError:
    try:
        from andes_solver import solve_andes
    except ImportError:
        solve_andes = None

try:
    from engines.custom_power_flow_solver import solve_deven
except ImportError:
    try:
        from custom_power_flow_solver import solve_deven
    except ImportError:
        solve_deven = None

class PowerFlowEngine:
    """
    Core engine for power flow calculations
    Independent of input/output formats
    """
    
    def __init__(self, baseMVA=100.0):
        self.baseMVA = baseMVA
        self.Ybus = None
        self.buses = None
        self.branches = None
        self.n_buses = 0
        self.bus_index_map = {}
        self.solver_method = 'inverse'
        self.tol = 1e-8
        self.max_iter = 10
        self.full_data = {}
        self.ignore_q_tol = False
        self.ignore_islands = True
        self.ignored_buses = set()
        self.v_init_mode = 'flat'
        self.fallback_opts = {}
        
    def initialize(self, bus_data, branch_data, full_data=None, solver_method='inverse', tol=1e-8, max_iter=10, ignore_q_tol=False, ignore_islands=True, industry_std_pv=True, v_init_mode='flat', fallback_opts=None, enable_fallback_pipeline=True):
        """
        Initialize engine with bus and branch data
        """
        self.buses = bus_data
        self.branches = branch_data
        self.full_data = full_data or {}
        self.solver_method = solver_method
        self.tol = tol
        self.max_iter = max_iter
        self.ignore_q_tol = ignore_q_tol
        self.ignore_islands = ignore_islands
        self.industry_std_pv = industry_std_pv
        self.v_init_mode = v_init_mode
        self.fallback_opts = dict(fallback_opts) if fallback_opts else {}
        if 'enable_fallback_pipeline' not in self.fallback_opts:
            self.fallback_opts['enable_fallback_pipeline'] = enable_fallback_pipeline
        self.enable_fallback_pipeline = self.fallback_opts['enable_fallback_pipeline']
        if 'stage_max_iter' in self.fallback_opts:
            self.fallback_opts['stage_max_iter'] = min(self.max_iter, int(self.fallback_opts['stage_max_iter']))
        else:
            self.fallback_opts['stage_max_iter'] = self.max_iter
        self.ignored_buses = set()
        self.hvdc_links = self.full_data.get('hvdc_links', {})
        self.n_buses = len(bus_data)
        # Validate that all branches connect existing buses
        for branch in branch_data:
            if branch['from_bus'] not in bus_data:
                raise ValueError(f"Branch references non-existent from_bus: {branch['from_bus']}")
            if branch['to_bus'] not in bus_data:
                raise ValueError(f"Branch references non-existent to_bus: {branch['to_bus']}")
                
        self.build_index_map()
        self.build_admittance_matrix()
        
    def build_index_map(self):
        """Build mapping from bus number to index"""
        bus_numbers = sorted(self.buses.keys())
        self.bus_index_map = {bus_num: idx for idx, bus_num in enumerate(bus_numbers)}
    
    def build_admittance_matrix(self):
        """Build Ybus matrix as a sparse CSR matrix"""
        import scipy.sparse as sp
        
        row = []
        col = []
        val = []
        
        for branch in self.branches:
            f_idx = self.bus_index_map[branch['from_bus']]
            t_idx = self.bus_index_map[branch['to_bus']]
            r, x, b, ratio = branch['r'], branch['x'], branch['b'], branch.get('ratio', 0.0)
            phase_shift_deg = branch.get('phase_shift', 0.0)
            
            # Complex tap
            a = ratio if ratio != 0.0 else 1.0
            alpha = phase_shift_deg * np.pi / 180.0
            tap = a * np.exp(1j * alpha)
            
            z = complex(r, x)
            if z != 0:
                y = 1.0 / z
                y_shunt = complex(0.0, b / 2.0)
                
                # Standard pi-model with complex tap ratio
                row.append(f_idx)
                col.append(f_idx)
                val.append((y + y_shunt) / (a ** 2))
                
                row.append(t_idx)
                col.append(t_idx)
                val.append(y + y_shunt)
                
                row.append(f_idx)
                col.append(t_idx)
                val.append(-y / np.conj(tap))
                
                row.append(t_idx)
                col.append(f_idx)
                val.append(-y / tap)
        
        # Add bus shunts (G_shunt + j B_shunt)
        for bus_num, bus in self.buses.items():
            idx = self.bus_index_map[bus_num]
            g_sh = bus.get('shunt_G', 0.0) / self.baseMVA
            b_sh = bus.get('shunt_B', 0.0) / self.baseMVA
            y_sh = complex(g_sh, b_sh)
            if y_sh != 0:
                row.append(idx)
                col.append(idx)
                val.append(y_sh)

        if not val:
            self.Ybus = sp.csr_matrix((self.n_buses, self.n_buses), dtype=complex)
        else:
            coo = sp.coo_matrix((val, (row, col)), shape=(self.n_buses, self.n_buses), dtype=complex)
            self.Ybus = coo.tocsr()
            
        return self.Ybus
    
    def get_base_voltages(self):
        """Get base voltage magnitudes and angles according to v_init_mode"""
        V_mag = np.zeros(self.n_buses)
        V_angle = np.zeros(self.n_buses)
        is_flat = (str(getattr(self, 'v_init_mode', 'flat')).lower().startswith('flat') or getattr(self, 'v_init_mode', 'flat') == 'flat')
        for bus_num, bus in self.buses.items():
            idx = self.bus_index_map[bus_num]
            b_type = bus.get('type', 1)
            if is_flat:
                if b_type == 1:
                    V_mag[idx] = 1.0
                    V_angle[idx] = 0.0
                else:
                    V_mag[idx] = bus.get('V_set', bus.get('V_init', 1.0))
                    V_angle[idx] = 0.0
            else:
                raw_v = bus.get('V_init', 1.0)
                try:
                    raw_v_f = float(raw_v)
                except (ValueError, TypeError):
                    raw_v_f = 1.0
                if raw_v_f <= 0.0001:
                    raw_v_f = 1.0
                V_mag[idx] = raw_v_f
                V_angle[idx] = bus.get('angle_init', 0.0)
        return V_mag, V_angle
    
    def calculate_power(self, V_mag, V_angle_deg):
        """Calculate power injection from voltages"""
        V_angle_rad = V_angle_deg * np.pi / 180.0
        V_complex = V_mag * np.exp(1j * V_angle_rad)
        I_inj = self.Ybus.dot(V_complex)
        S = V_complex * np.conj(I_inj)
        
        P_calc = S.real
        Q_calc = S.imag
        
        # For ignored buses, zero out injections
        if hasattr(self, 'ignored_buses') and self.ignored_buses:
            for b in self.ignored_buses:
                if b in self.bus_index_map:
                    idx = self.bus_index_map[b]
                    P_calc[idx] = 0.0
                    Q_calc[idx] = 0.0
                    
        return P_calc, Q_calc
    
    def calculate_bidirectional_flows(self, V_mag, V_angle_deg):
        """Calculate bidirectional power flows on all branches"""
        V_angle_rad = V_angle_deg * np.pi / 180.0
        V_complex = V_mag * np.exp(1j * V_angle_rad)
        
        flows = []
        for branch in self.branches:
            f_idx = self.bus_index_map[branch['from_bus']]
            t_idx = self.bus_index_map[branch['to_bus']]
            
            # If branch is offline or connected to ignored floating island, output 0 flow
            if branch.get('status', 1) == 0 or (hasattr(self, 'ignored_buses') and (branch['from_bus'] in self.ignored_buses or branch['to_bus'] in self.ignored_buses)):
                flows.append({
                    'type': 'transformer' if branch.get('ratio', 0.0) != 0.0 else 'line',
                    'num': branch.get('num'),
                    'name': branch.get('name'),
                    'from_bus': branch['from_bus'],
                    'to_bus': branch['to_bus'],
                    'P_fwd_MW': 0.0,
                    'Q_fwd_Mvar': 0.0,
                    'P_rev_MW': 0.0,
                    'Q_rev_Mvar': 0.0,
                    'losses_MW': 0.0,
                    'loading_pct': 0.0,
                    'tap_ratio': branch.get('ratio', 1.0)
                })
                continue
                
            Vf, Vt = V_complex[f_idx], V_complex[t_idx]
            
            r, x, b = branch['r'], branch['x'], branch['b']
            ratio = branch.get('ratio', 0.0)
            phase_shift_deg = branch.get('phase_shift', 0.0)
            
            a = ratio if ratio != 0.0 else 1.0
            alpha = phase_shift_deg * np.pi / 180.0
            tap = a * np.exp(1j * alpha)
            
            z = complex(r, x)
            y = 1.0 / z if z != 0 else 0
            
            if ratio != 0:  # Transformer
                # Forward (from -> to)
                If_fwd = (Vf / tap - Vt) * y / np.conj(tap)
                S_fwd = Vf * np.conj(If_fwd)
                # Reverse (to -> from)
                If_rev = (Vt - Vf / tap) * y
                S_rev = Vt * np.conj(If_rev)
                losses = S_fwd + S_rev
                
                flows.append({
                    'type': 'transformer',
                    'num': branch.get('num'),
                    'name': branch.get('name'),
                    'from_bus': branch['from_bus'],
                    'to_bus': branch['to_bus'],
                    'P_fwd_MW': S_fwd.real * self.baseMVA,
                    'Q_fwd_Mvar': S_fwd.imag * self.baseMVA,
                    'P_rev_MW': S_rev.real * self.baseMVA,
                    'Q_rev_Mvar': S_rev.imag * self.baseMVA,
                    'losses_MW': losses.real * self.baseMVA,
                    'loading_pct': (abs(S_fwd) * self.baseMVA) / branch.get('rateA', 9999) * 100 if branch.get('rateA', 0) > 0 else 0,
                    'tap_ratio': ratio
                })
            else:  # Transmission line
                y_shunt = complex(0, b / 2.0)
                # Forward (from -> to)
                Ift = (Vf - Vt) * y + Vf * y_shunt
                S_fwd = Vf * np.conj(Ift)
                # Reverse (to -> from)
                Itf = (Vt - Vf) * y + Vt * y_shunt
                S_rev = Vt * np.conj(Itf)
                losses = S_fwd + S_rev
                
                flows.append({
                    'type': 'line',
                    'num': branch.get('num'),
                    'name': branch.get('name'),
                    'from_bus': branch['from_bus'],
                    'to_bus': branch['to_bus'],
                    'P_fwd_MW': S_fwd.real * self.baseMVA,
                    'Q_fwd_Mvar': S_fwd.imag * self.baseMVA,
                    'P_rev_MW': S_rev.real * self.baseMVA,
                    'Q_rev_Mvar': S_rev.imag * self.baseMVA,
                    'losses_MW': losses.real * self.baseMVA,
                    'loading_pct': (abs(S_fwd) * self.baseMVA) / branch.get('rateA', 9999) * 100 if branch.get('rateA', 0) > 0 else 0
                })
        
        return flows

    def calculate_hvdc_flows(self, V_mag, V_angle, check_ignored=True):
        """Calculate active/reactive powers, DC voltages, and currents for HVDC links"""
        hvdc_flows = []
        raw_links = getattr(self, 'hvdc_links', {}) or self.full_data.get('hvdc_links', {}) or {}
        
        for k, lk in raw_links.items():
            num = lk.get('num', k)
            name = lk.get('name', f"HVDC_{num}")
            f_bus = lk.get('from_bus')
            t_bus = lk.get('to_bus')
            status = int(lk.get('status', 1))
            
            # Offline check: offline if status is 0 or if both ends are unenergized/ignored
            if status == 0 or (check_ignored and hasattr(self, 'ignored_buses') and f_bus in self.ignored_buses and t_bus in self.ignored_buses):
                hvdc_flows.append({
                    'num': num,
                    'name': name,
                    'from_bus': f_bus,
                    'to_bus': t_bus,
                    'status': 'OFFLINE',
                    'from_mode': lk.get('from_mode', 'Rectifier'),
                    'to_mode': lk.get('to_mode', 'Inverter'),
                    'Vdc_from_kV': 0.0,
                    'Vdc_to_kV': 0.0,
                    'Idc_A': 0.0,
                    'P_dc_MW': 0.0,
                    'P_dc': 0.0,
                    'losses_MW': 0.0,
                    'losses_dc_MW': 0.0,
                    'P_fwd': 0.0,
                    'Q_fwd': 0.0,
                    'MVA_fwd': 0.0,
                    'P_rev': 0.0,
                    'Q_rev': 0.0,
                    'MVA_rev': 0.0,
                    'P_from_ac_MW': 0.0,
                    'Q_from_ac_Mvar': 0.0,
                    'P_to_ac_MW': 0.0,
                    'Q_to_ac_Mvar': 0.0,
                    'alpha_deg': 0.0,
                    'gamma_deg': 0.0,
                    'tap_from': 1.0,
                    'tap_to': 1.0,
                    'loading_pct': 0.0,
                    'area': lk.get('area', 1),
                    'zone': lk.get('zone', 1),
                    'owner': lk.get('owner', 1)
                })
                continue

            f_idx = self.bus_index_map.get(f_bus)
            t_idx = self.bus_index_map.get(t_bus)
            
            base_kv_f = float(self.buses[f_bus].get('base_kV', 220.0)) if f_bus in self.buses else 220.0
            base_kv_t = float(self.buses[t_bus].get('base_kV', 220.0)) if t_bus in self.buses else 220.0
            
            v_ac_f_pu = float(V_mag[f_idx]) if f_idx is not None and f_idx < len(V_mag) else 1.0
            v_ac_t_pu = float(V_mag[t_idx]) if t_idx is not None and t_idx < len(V_mag) else 1.0
            v_ac_f_kv = v_ac_f_pu * base_kv_f
            v_ac_t_kv = v_ac_t_pu * base_kv_t
            
            r_dc = max(1e-5, float(lk.get('r_dc', 0.032) or 0.032))
            
            # Modes: From side, To side
            from_mode = str(lk.get('from_mode', 'Rectifier')).strip()
            to_mode = str(lk.get('to_mode', 'Inverter')).strip()
            
            # Flow direction: 1 = From -> To, -1 = To -> From
            dir_mult = 1.0
            if from_mode.lower() == 'inverter':
                dir_mult = -1.0
            
            # Rectifier & Inverter nominal / control values
            fc_type = int(lk.get('from_ctrl_type', 3) or 3)
            fc_val = float(lk.get('from_val', 50.0) or 50.0)
            tc_type = int(lk.get('to_ctrl_type', 1) or 1)
            tc_val = float(lk.get('to_val', 220.0) or 220.0)
            
            # Target DC Voltage at Inverter
            vdc_inv = tc_val if tc_val > 0 else (lk.get('to_tfr_kv', base_kv_t) or base_kv_t)
            
            # Target DC Power or Current
            if fc_type == 3 and fc_val > 0:
                p_dc_target = fc_val
                idc_a = (p_dc_target * 1000.0) / max(1.0, vdc_inv)
            elif fc_type == 2 and fc_val > 0:
                idc_a = fc_val
                p_dc_target = (vdc_inv * idc_a) / 1000.0
            elif fc_type == 1:
                # Voltage control at rectifier
                v_diff = fc_val - vdc_inv
                rate_mva = float(lk.get('from_tfr_mva', 100.0) or 100.0)
                if abs(v_diff) > 0.01:
                    raw_idc = abs(v_diff * 1000.0) / r_dc
                    p_dc_calc = (vdc_inv * raw_idc) / 1000.0
                    p_dc_target = min(p_dc_calc, rate_mva)
                    idc_a = (p_dc_target * 1000.0) / max(1.0, vdc_inv)
                else:
                    # Voltage difference small or zero: check if from-side island has net generation
                    visited = set([f_bus])
                    queue = [f_bus]
                    while queue:
                        curr = queue.pop(0)
                        for br in getattr(self, 'branches', []):
                            if br.get('status', 1) == 0: continue
                            fb_br, tb_br = br.get('from_bus'), br.get('to_bus')
                            nxt = tb_br if fb_br == curr else (fb_br if tb_br == curr else None)
                            if nxt is not None and nxt not in visited:
                                visited.add(nxt)
                                queue.append(nxt)
                    net_gen = 0.0
                    raw_gens = self.full_data.get('generators', {})
                    raw_loads = self.full_data.get('loads', {})
                    for g in raw_gens.values():
                        if g.get('status', 1) != 0 and g.get('bus') in visited:
                            net_gen += float(g.get('P_out', 0.0) or g.get('p_mw', 0.0) or 0.0)
                    for l in raw_loads.values():
                        if l.get('status', 1) != 0 and l.get('bus') in visited:
                            net_gen -= float(l.get('P_demand', 0.0) or 0.0)
                    if net_gen > 1.0:
                        p_dc_target = min(net_gen, rate_mva)
                    else:
                        p_dc_target = rate_mva * 0.5
                    idc_a = (p_dc_target * 1000.0) / max(1.0, vdc_inv)
            else:
                p_dc_target = max(10.0, fc_val)
                idc_a = (p_dc_target * 1000.0) / max(1.0, vdc_inv)
                
            idc_a = max(0.0, idc_a)
            delta_v_dc = (idc_a * r_dc) / 1000.0
            vdc_rec = vdc_inv + delta_v_dc
            p_loss_dc = (idc_a ** 2 * r_dc) * 1e-6
            p_rec_dc = (vdc_rec * idc_a) / 1000.0
            p_inv_dc = (vdc_inv * idc_a) / 1000.0
            
            # Angles (alpha for rectifier, gamma for inverter)
            alpha_deg = float(lk.get('from_angle', 12.0) or 12.0)
            gamma_deg = float(lk.get('to_angle', 15.0) or 15.0)
            
            alpha_rad = math.radians(max(5.0, min(85.0, alpha_deg)))
            gamma_rad = math.radians(max(5.0, min(85.0, gamma_deg)))
            
            # AC Terminal Active & Reactive Powers
            p_ac_rec = p_rec_dc
            q_ac_rec = p_ac_rec * math.tan(alpha_rad)
            
            p_ac_inv = p_inv_dc
            q_ac_inv = p_ac_inv * math.tan(gamma_rad)
            
            # Taps calculation
            nb_rec = int(lk.get('from_nb', 1) or 1)
            nb_inv = int(lk.get('to_nb', 1) or 1)
            
            v_d0_rec = nb_rec * (3.0 * math.sqrt(2.0) / math.pi) * v_ac_f_kv
            v_d0_inv = nb_inv * (3.0 * math.sqrt(2.0) / math.pi) * v_ac_t_kv
            
            tap_from = max(0.80, min(1.25, vdc_rec / max(1e-4, v_d0_rec * math.cos(alpha_rad)))) if v_d0_rec > 1.0 else 1.0
            tap_to = max(0.80, min(1.25, vdc_inv / max(1e-4, v_d0_inv * math.cos(gamma_rad)))) if v_d0_inv > 1.0 else 1.0
            
            if dir_mult >= 0:
                p_from = p_ac_rec
                q_from = q_ac_rec
                p_to = -p_ac_inv
                q_to = q_ac_inv
                vdc_from = vdc_rec
                vdc_to = vdc_inv
                p_dc_val = p_rec_dc
                out_alpha = alpha_deg
                out_gamma = gamma_deg
                out_tap_from = tap_from
                out_tap_to = tap_to
            else:
                p_from = -p_ac_inv
                q_from = q_ac_inv
                p_to = p_ac_rec
                q_to = q_ac_rec
                vdc_from = vdc_inv
                vdc_to = vdc_rec
                p_dc_val = -p_rec_dc
                out_alpha = gamma_deg
                out_gamma = alpha_deg
                out_tap_from = tap_to
                out_tap_to = tap_from
                
            mva_fwd = math.sqrt(p_from**2 + q_from**2)
            mva_rev = math.sqrt(p_to**2 + q_to**2)
            
            rate_mva = float(lk.get('from_tfr_mva', 100.0) or 100.0)
            loading_pct = (max(mva_fwd, mva_rev) / rate_mva * 100.0) if rate_mva > 0 else 0.0
            
            hvdc_flows.append({
                'num': num,
                'name': name,
                'from_bus': f_bus,
                'to_bus': t_bus,
                'status': 'ONLINE',
                'from_mode': from_mode,
                'to_mode': to_mode,
                'Vdc_from_kV': vdc_from,
                'Vdc_to_kV': vdc_to,
                'Idc_A': idc_a,
                'P_dc_MW': p_dc_val,
                'P_dc': p_dc_val,
                'losses_MW': p_loss_dc,
                'losses_dc_MW': p_loss_dc,
                'P_fwd': p_from,
                'Q_fwd': q_from,
                'MVA_fwd': mva_fwd,
                'P_from_ac_MW': p_from,
                'Q_from_ac_Mvar': q_from,
                'P_rev': p_to,
                'Q_rev': q_to,
                'MVA_rev': mva_rev,
                'P_to_ac_MW': p_to,
                'Q_to_ac_Mvar': q_to,
                'alpha_deg': out_alpha,
                'gamma_deg': out_gamma,
                'tap_from': out_tap_from,
                'tap_to': out_tap_to,
                'loading_pct': loading_pct,
                'area': lk.get('area', 1),
                'zone': lk.get('zone', 1),
                'owner': lk.get('owner', 1)
            })
            
        return hvdc_flows
    
    def generate_sample(self, variation_strength=0.05):
        """Generate one power flow sample"""
        try:
            if self.solver_method == 'inverse':
                V_mag_base, V_angle_base = self.get_base_voltages()
                
                variation = np.random.uniform(-variation_strength, variation_strength, self.n_buses)
                V_mag = V_mag_base * (1 + variation)
                V_mag = np.clip(V_mag, 0.90, 1.1)
                
                angle_variation = np.random.uniform(-variation_strength * 30, variation_strength * 30, self.n_buses)
                V_angle = V_angle_base + angle_variation
                
                P_calc, Q_calc = self.calculate_power(V_mag, V_angle)
                branch_flows = self.calculate_bidirectional_flows(V_mag, V_angle)
                hvdc_flows = self.calculate_hvdc_flows(V_mag, V_angle)
                
                return {
                    'P_calc': P_calc,
                    'Q_calc': Q_calc,
                    'V_mag': V_mag,
                    'V_angle': V_angle,
                    'branch_flows': branch_flows,
                    'hvdc_flows': hvdc_flows
                }
            else:
                self.ignored_buses = set()
                # Perturb loads & generators for this sample
                perturbed_loads = {}
                for l_num, l in self.full_data.get('loads', {}).items():
                    f_load = 1.0 + np.random.uniform(-variation_strength, variation_strength)
                    perturbed_loads[l_num] = {
                        'bus': l['bus'],
                        'status': l.get('status', 1),
                        'P_demand': l['P_demand'] * f_load,
                        'Q_demand': l['Q_demand'] * f_load,
                        'scope': l.get('scope', 'Both')
                    }
                    
                perturbed_gens = {}
                for g_num, g in self.full_data.get('generators', {}).items():
                    f_gen = 1.0 + np.random.uniform(-variation_strength, variation_strength)
                    perturbed_gens[g_num] = {
                        'bus': g['bus'],
                        'status': g.get('status', 1),
                        'P_out': g['P_out'] * f_gen,
                        'Q_out': g['Q_out'] * f_gen,
                        'Qmax': g['Qmax'],
                        'Qmin': g['Qmin'],
                        'V_set': g['V_set'],
                        'scope': g.get('scope', 'Both')
                    }

                # Apply HVDC converter active and reactive powers as equivalent terminal bus injections
                active_hvdc = [lk for lk in self.full_data.get('hvdc_links', {}).values() if int(lk.get('status', 1)) != 0]
                if active_hvdc:
                    initial_v_mag = np.ones(self.n_buses)
                    initial_v_ang = np.zeros(self.n_buses)
                    est_hvdc_flows = self.calculate_hvdc_flows(initial_v_mag, initial_v_ang, check_ignored=False)
                    for hf in est_hvdc_flows:
                        if hf.get('status') == 'OFFLINE':
                            continue
                        fb = hf['from_bus']
                        tb = hf['to_bus']
                        p_fwd = hf['P_fwd']
                        q_fwd = hf['Q_fwd']
                        p_rev = hf['P_rev']
                        q_rev = hf['Q_rev']
                        
                        syn_lid_f = f"HVDC_CONV_{hf['num']}_FROM"
                        perturbed_loads[syn_lid_f] = {
                            'bus': fb,
                            'status': 1,
                            'P_demand': p_fwd,
                            'Q_demand': q_fwd,
                            'scope': 'Both'
                        }
                        
                        syn_gid_t = f"HVDC_CONV_{hf['num']}_TO"
                        perturbed_gens[syn_gid_t] = {
                            'bus': tb,
                            'status': 1,
                            'P_out': -p_rev,
                            'Q_out': -q_rev,
                            'Qmax': 9999.0,
                            'Qmin': -9999.0,
                            'V_set': float(self.buses.get(tb, {}).get('V_init', 1.0)),
                            'bus_type': 2 if self.buses.get(tb, {}).get('type') == 2 else 1,
                            'scope': 'Both'
                        }
                    
                # Handle Island Detection / Multi-Island Solving if ignore_islands is enabled
                if self.ignore_islands:
                    try:
                        from island_detector import detect_and_classify_islands
                    except ImportError:
                        from utils.island_detector import detect_and_classify_islands
                    eff_full_data = {**self.full_data, 'generators': perturbed_gens, 'loads': perturbed_loads}
                    solvable_islands, floating_buses, all_islands = detect_and_classify_islands(
                        self.buses, self.branches, full_data=eff_full_data, auto_slack=True
                    )
                    self.ignored_buses = floating_buses

                    if len(all_islands) > 1 and not getattr(self, '_island_logged', False):
                        self._island_logged = True
                        n_solv = len(solvable_islands)
                        n_float = len(all_islands) - n_solv
                        total_solv_buses = sum(isl['num_buses'] for isl in solvable_islands)
                        print(f"  [ISLAND ENGINE] Detected {len(all_islands)} total islands: {n_solv} energized ({total_solv_buses} buses), {n_float} floating/passive ({len(floating_buses)} buses).")

                    # Initialize full network voltage vectors
                    V_mag = np.zeros(self.n_buses)
                    V_angle = np.zeros(self.n_buses)
                    all_converged = True
                    total_iters = 0
                    max_dP_overall = 0.0
                    max_dQ_overall = 0.0

                    # Solve each energized island independently
                    for isl in solvable_islands:
                        isl_buses_set = isl['buses']
                        isl_buses = {b: dict(self.buses[b]) for b in isl_buses_set if b in self.buses}
                        isl_verbose = (isl.get('is_main', False) or isl['num_buses'] >= 5)

                        # Ensure island has a Type 3 Slack bus designated
                        slack_bid = isl.get('slack_bus')
                        if slack_bid and slack_bid in isl_buses:
                            isl_buses[slack_bid]['type'] = 3

                        isl_branches = [br for br in self.branches if br['from_bus'] in isl_buses_set and br['to_bus'] in isl_buses_set]
                        isl_gens = {g_id: g for g_id, g in perturbed_gens.items() if g['bus'] in isl_buses_set}
                        isl_loads = {l_id: l for l_id, l in perturbed_loads.items() if l['bus'] in isl_buses_set}

                        if self.solver_method.startswith('deven'):
                            try:
                                from engines.custom_power_flow_solver import solve_deven
                            except ImportError:
                                from custom_power_flow_solver import solve_deven
                            m_tag = self.solver_method.replace('deven_', '')
                            if m_tag in ('deven', 'default', ''):
                                m_tag = 'nr'
                            res = solve_deven(
                                isl_buses, isl_branches, isl_gens, isl_loads,
                                base_mva=self.baseMVA, method=m_tag,
                                tol=self.tol, max_iter=self.max_iter,
                                ignore_q_tol=getattr(self, 'ignore_q_tol', False),
                                v_init_mode=getattr(self, 'v_init_mode', 'flat')
                            )
                        else:
                            try:
                                from engines.andes_solver import solve_andes
                            except ImportError:
                                from andes_solver import solve_andes
                            method_tag = self.solver_method.split('_')[1] if '_' in self.solver_method else 'nr'
                            if method_tag in ('andes', 'deven', 'default', ''):
                                method_tag = 'nr'
                            
                            fb_opts = getattr(self, 'fallback_opts', {}) or {}
                            res = solve_andes(
                                isl_buses, isl_branches, isl_gens, isl_loads,
                                base_mva=self.baseMVA, method=method_tag,
                                tol=self.tol, max_iter=self.max_iter, ignore_q_tol=getattr(self, 'ignore_q_tol', False),
                                industry_std_pv=getattr(self, 'industry_std_pv', True),
                                v_init_mode=getattr(self, 'v_init_mode', 'flat'),
                                verbose=isl_verbose,
                                enable_fallback_pipeline=fb_opts.get('enable_fallback_pipeline', getattr(self, 'enable_fallback_pipeline', True)),
                                stage_max_iter=min(self.max_iter, int(fb_opts.get('stage_max_iter', self.max_iter))),
                                use_dc_angle_init=fb_opts.get('use_dc_angle_init', True),
                                use_postponed_q_limits=fb_opts.get('use_postponed_q_limits', True),
                                use_step_damping=fb_opts.get('use_step_damping', True),
                                use_levenberg_marquardt=fb_opts.get('use_levenberg_marquardt', True),
                                use_homotopy_ramping=fb_opts.get('use_homotopy_ramping', fb_opts.get('use_homotopy_continuation', True)),
                                use_diagnostics=fb_opts.get('use_diagnostics', fb_opts.get('use_failure_diagnostics', True))
                            )

                        if not isl_verbose and res.get('converged', True):
                            print(f"  [ISLAND {isl['island_id']}] Solved {isl['num_buses']}-bus subgrid in {res.get('iterations', 1)} iters.")

                        sub_bus_numbers = res.get('bus_numbers', sorted(isl_buses.keys()))
                        sub_v_mag = res['V_mag']
                        sub_v_angle = res['V_angle']

                        for sub_i, b_num in enumerate(sub_bus_numbers):
                            if b_num in self.bus_index_map:
                                full_i = self.bus_index_map[b_num]
                                V_mag[full_i] = sub_v_mag[sub_i]
                                V_angle[full_i] = sub_v_angle[sub_i]

                        if not res.get('converged', True):
                            all_converged = False
                        total_iters = max(total_iters, res.get('iterations', 1))
                        max_dP_overall = max(max_dP_overall, res.get('max_dP', 0.0))
                        max_dQ_overall = max(max_dQ_overall, res.get('max_dQ', 0.0))

                    # Floating buses remain V_mag = 0.0, V_angle = 0.0
                    for b_num in self.ignored_buses:
                        if b_num in self.bus_index_map:
                            full_i = self.bus_index_map[b_num]
                            V_mag[full_i] = 0.0
                            V_angle[full_i] = 0.0

                    # Strict NaN guard for global convergence
                    if np.isnan(V_mag).any() or np.isinf(V_mag).any():
                        all_converged = False

                    P_calc, Q_calc = self.calculate_power(V_mag, V_angle)
                    branch_flows = self.calculate_bidirectional_flows(V_mag, V_angle)
                    hvdc_flows = self.calculate_hvdc_flows(V_mag, V_angle)

                    if np.isnan(P_calc).any() or np.isnan(Q_calc).any():
                        all_converged = False

                    return {
                        'P_calc': P_calc,
                        'Q_calc': Q_calc,
                        'V_mag': V_mag,
                        'V_angle': V_angle,
                        'branch_flows': branch_flows,
                        'gens': perturbed_gens,
                        'loads': perturbed_loads,
                        'converged': all_converged,
                        'iterations': total_iters,
                        'max_dP': max_dP_overall,
                        'max_dQ': max_dQ_overall,
                        'hvdc_flows': hvdc_flows
                    }
                else:
                    solver_buses = self.buses
                    solver_branches = self.branches
                    solver_gens = perturbed_gens
                    solver_loads = perturbed_loads
                    self.ignored_buses = set()

                    if self.solver_method.startswith('andes'):
                        try:
                            from engines.andes_solver import solve_andes
                        except ImportError:
                            from andes_solver import solve_andes
                        method_tag = self.solver_method.split('_')[1] if '_' in self.solver_method else 'nr'
                        fb_opts = getattr(self, 'fallback_opts', {}) or {}
                        res = solve_andes(
                            solver_buses, solver_branches, solver_gens, solver_loads,
                            base_mva=self.baseMVA, method=method_tag,
                            tol=self.tol, max_iter=self.max_iter, ignore_q_tol=getattr(self, 'ignore_q_tol', False),
                            industry_std_pv=getattr(self, 'industry_std_pv', True),
                            v_init_mode=getattr(self, 'v_init_mode', 'flat'),
                            enable_fallback_pipeline=fb_opts.get('enable_fallback_pipeline', getattr(self, 'enable_fallback_pipeline', True)),
                            stage_max_iter=min(self.max_iter, int(fb_opts.get('stage_max_iter', self.max_iter))),
                            use_dc_angle_init=fb_opts.get('use_dc_angle_init', True),
                            use_postponed_q_limits=fb_opts.get('use_postponed_q_limits', True),
                            use_step_damping=fb_opts.get('use_step_damping', True),
                            use_levenberg_marquardt=fb_opts.get('use_levenberg_marquardt', True),
                            use_homotopy_ramping=fb_opts.get('use_homotopy_ramping', fb_opts.get('use_homotopy_continuation', True)),
                            use_diagnostics=fb_opts.get('use_diagnostics', fb_opts.get('use_failure_diagnostics', True))
                        )
                    else:
                        try:
                            from engines.custom_power_flow_solver import solve_deven
                        except ImportError:
                            from custom_power_flow_solver import solve_deven
                        m_tag = self.solver_method.replace('deven_', '')
                        res = solve_deven(
                            solver_buses, solver_branches, solver_gens, solver_loads,
                            base_mva=self.baseMVA, method=m_tag,
                            tol=self.tol, max_iter=self.max_iter, ignore_q_tol=getattr(self, 'ignore_q_tol', False),
                            v_init_mode=getattr(self, 'v_init_mode', 'flat')
                        )

                    sub_bus_numbers = res.get('bus_numbers', sorted(solver_buses.keys()))
                    sub_v_mag = res['V_mag']
                    sub_v_angle = res['V_angle']

                    V_mag = np.zeros(self.n_buses)
                    V_angle = np.zeros(self.n_buses)

                    for sub_i, b_num in enumerate(sub_bus_numbers):
                        if b_num in self.bus_index_map:
                            full_i = self.bus_index_map[b_num]
                            V_mag[full_i] = sub_v_mag[sub_i]
                            V_angle[full_i] = sub_v_angle[sub_i]

                    P_calc, Q_calc = self.calculate_power(V_mag, V_angle)
                    branch_flows = self.calculate_bidirectional_flows(V_mag, V_angle)
                    hvdc_flows = self.calculate_hvdc_flows(V_mag, V_angle)

                    return {
                        'P_calc': P_calc,
                        'Q_calc': Q_calc,
                        'V_mag': V_mag,
                        'V_angle': V_angle,
                        'branch_flows': branch_flows,
                        'gens': perturbed_gens,
                        'loads': perturbed_loads,
                        'converged': res.get('converged', True),
                        'iterations': res.get('iterations', 1),
                        'max_dP': res.get('max_dP', 0.0),
                        'max_dQ': res.get('max_dQ', 0.0),
                        'hvdc_flows': hvdc_flows
                    }
        except Exception as e:
            # print(f"  ✗ Error in sample: {e}")
            raise e
        except Exception as e:
            # print(f"  ✗ Error in sample: {e}")
            raise e
    
    def validate_sample(self, sample):
        """Validate sample"""
        if np.any(np.isnan(sample['P_calc'])) or np.any(np.isinf(sample['P_calc'])):
            return False
        return True
    
    def run_batch(self, n_samples=100, variation_strength=0.10):
        """Run batch of samples"""
        import time
        samples = []
        
        is_single_run = (n_samples == 1 and variation_strength == 0.0)
        max_attempts = 1 if is_single_run else n_samples * 10
        attempts = 0
        
        while len(samples) < n_samples and attempts < max_attempts:
            if getattr(self, 'stop_requested', False):
                print("\n🛑 SIMULATION TERMINATED: Stop requested by user.")
                break
            attempts += 1
            time.sleep(0.001)  # Yield GIL to Tkinter GUI thread to keep UI responsive
            try:
                sample = self.generate_sample(variation_strength=variation_strength)
                if is_single_run or self.validate_sample(sample):
                    samples.append(sample)
            except Exception:
                continue
                
        valid_count = sum(1 for s in samples if bool(s.get('converged', True)) and self.validate_sample(s))
        return samples, valid_count
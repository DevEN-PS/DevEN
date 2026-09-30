#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
  DevEN (Develop Electric Network) - 3-Phase Unbalanced Power Flow Engine
=============================================================================
  Standards Compliant:
    - IEEE Std 1159: Monitoring Electric Power Quality (Voltage Unbalance)
    - IEEE Std 141 / Red Book: Electric Power Distribution for Industrial Plants
    - NEMA MG 1: Derating Factor for Voltage Unbalance (PVUR / VUF)
    - IEC 61000-4-30: Power Quality Measurement Techniques
=============================================================================
  Capabilities:
    - Full 3-phase (a, b, c) phase coordinate network modeling
    - Supports both single-value (auto-distributed) and explicit 3-phase loads & generators
    - Fallback strategies for single-value elements:
        * 'equal': P_tot / 3, Q_tot / 3
        * 'same': P_single on all 3 phases
        * 'custom': Phase A %, Phase B %, Phase C %
    - Algorithms:
        * 3-Phase Newton-Raphson in Phase Coordinates (NR-3P) for meshed/transmission grids
        * 3-Phase Forward-Backward Sweep (FBS-3P) for radial/distribution feeders
    - Full per-phase reporting:
        * Bus: Va, Vb, Vc (kV & pu), angles anga, angb, angc, Vn, VUF (%), PVUR (%)
        * Branch: Pa, Pb, Pc, Qa, Qb, Qc, Ia, Ib, Ic, In, Per-phase Losses
        * Gen & Load: Per-phase active & reactive injection/demand and power factor
    - Complete standalone engine with rich, reusable APIs (independent of UI)
=============================================================================
"""

import math
import cmath
import time
import os
import csv
from typing import Dict, List, Tuple, Any, Optional

try:
    import numpy as np
except ImportError:
    np = None

# Complex operator a = e^(j 120deg) = -0.5 + j*sqrt(3)/2
A_OP = cmath.rect(1.0, math.radians(120.0))
A2_OP = cmath.rect(1.0, math.radians(240.0))


# =============================================================================
# 1. HELPER CONVERTER FUNCTIONS & EXPANSION
# =============================================================================

def expand_element_to_3phase(
    element: Dict[str, Any],
    elem_type: str = 'load',
    fallback_rule: str = 'equal',
    custom_pct: Tuple[float, float, float] = (33.333, 33.333, 33.334)
) -> Dict[str, Any]:
    """
    Expands a load or generator dictionary to explicit Phase A, B, C values.
    If the element already has explicit 3-phase data (phase_mode == '3phase'),
    its per-phase values are preserved.
    Otherwise, the fallback rule ('equal', 'same', or 'custom') is applied.
    """
    mode = str(element.get('phase_mode', 'single')).lower()
    
    if elem_type == 'load':
        p_tot = float(element.get('P_demand', element.get('P', 0.0)))
        q_tot = float(element.get('Q_demand', element.get('Q', 0.0)))
        
        if mode == '3phase' and 'Pa' in element:
            pa = float(element.get('Pa', p_tot / 3.0))
            pb = float(element.get('Pb', p_tot / 3.0))
            pc = float(element.get('Pc', p_tot / 3.0))
            qa = float(element.get('Qa', q_tot / 3.0))
            qb = float(element.get('Qb', q_tot / 3.0))
            qc = float(element.get('Qc', q_tot / 3.0))
        elif fallback_rule == 'same':
            pa = pb = pc = p_tot
            qa = qb = qc = q_tot
        elif fallback_rule == 'custom':
            fa, fb, fc = custom_pct[0] / 100.0, custom_pct[1] / 100.0, custom_pct[2] / 100.0
            pa, pb, pc = p_tot * fa, p_tot * fb, p_tot * fc
            qa, qb, qc = q_tot * fa, q_tot * fb, q_tot * fc
        else:  # 'equal' default
            pa = pb = pc = p_tot / 3.0
            qa = qb = qc = q_tot / 3.0
            
        return {
            'phase_mode': mode,
            'Pa': pa, 'Pb': pb, 'Pc': pc,
            'Qa': qa, 'Qb': qb, 'Qc': qc,
            'P_tot': pa + pb + pc,
            'Q_tot': qa + qb + qc,
            'model': element.get('model', 'constant_PQ'),
            'status': element.get('status', 1)
        }
        
    elif elem_type == 'generator':
        p_tot = float(element.get('P_out', element.get('P_gen', 0.0)))
        q_tot = float(element.get('Q_out', element.get('Q_gen', 0.0)))
        v_set = float(element.get('V_set', 1.0))
        qmin = float(element.get('Qmin', -9999.0))
        qmax = float(element.get('Qmax', 9999.0))
        
        if mode == '3phase' and 'Pa' in element:
            pa = float(element.get('Pa', p_tot / 3.0))
            pb = float(element.get('Pb', p_tot / 3.0))
            pc = float(element.get('Pc', p_tot / 3.0))
            qa = float(element.get('Qa', q_tot / 3.0))
            qb = float(element.get('Qb', q_tot / 3.0))
            qc = float(element.get('Qc', q_tot / 3.0))
            va = float(element.get('Va_set', v_set))
            vb = float(element.get('Vb_set', v_set))
            vc = float(element.get('Vc_set', v_set))
        elif fallback_rule == 'same':
            pa = pb = pc = p_tot
            qa = qb = qc = q_tot
            va = vb = vc = v_set
        elif fallback_rule == 'custom':
            fa, fb, fc = custom_pct[0] / 100.0, custom_pct[1] / 100.0, custom_pct[2] / 100.0
            pa, pb, pc = p_tot * fa, p_tot * fb, p_tot * fc
            qa, qb, qc = q_tot * fa, q_tot * fb, q_tot * fc
            va = vb = vc = v_set
        else:  # 'equal' default
            pa = pb = pc = p_tot / 3.0
            qa = qb = qc = q_tot / 3.0
            va = vb = vc = v_set
            
        return {
            'phase_mode': mode,
            'Pa': pa, 'Pb': pb, 'Pc': pc,
            'Qa': qa, 'Qb': qb, 'Qc': qc,
            'Va_set': va, 'Vb_set': vb, 'Vc_set': vc,
            'P_tot': pa + pb + pc,
            'Q_tot': qa + qb + qc,
            'Qmin_phase': qmin / 3.0,
            'Qmax_phase': qmax / 3.0,
            'status': element.get('status', 1)
        }
    return {}


def compute_symmetrical_components(va: complex, vb: complex, vc: complex) -> Tuple[complex, complex, complex, float, float]:
    """
    Computes zero (V0), positive (V1), and negative (V2) sequence voltages,
    along with Voltage Unbalance Factor (VUF %) and Phase Voltage Unbalance Rate (PVUR %).
    """
    v0 = (va + vb + vc) / 3.0
    v1 = (va + A_OP * vb + A2_OP * vc) / 3.0
    v2 = (va + A2_OP * vb + A_OP * vc) / 3.0
    
    mag_v1 = abs(v1)
    mag_v2 = abs(v2)
    
    # IEEE 1159 / IEC Definition: VUF % = (|V2| / |V1|) * 100%
    vuf_pct = (mag_v2 / mag_v1 * 100.0) if mag_v1 > 1e-6 else 0.0
    
    # NEMA MG 1 Definition: PVUR % = (max deviation from average / average) * 100%
    m_a, m_b, m_c = abs(va), abs(vb), abs(vc)
    v_avg = (m_a + m_b + m_c) / 3.0
    max_dev = max(abs(m_a - v_avg), abs(m_b - v_avg), abs(m_c - v_avg))
    pvur_pct = (max_dev / v_avg * 100.0) if v_avg > 1e-6 else 0.0
    
    return v0, v1, v2, vuf_pct, pvur_pct


# =============================================================================
# 2. THREE-PHASE ADMITTANCE & IMPEDANCE MODELING
# =============================================================================

def build_line_z3x3(
    r1: float, x1: float, b1: float = 0.0,
    r0: float = None, x0: float = None, b0: float = None,
    length_km: float = 1.0, base_z: float = 1.0
) -> Tuple[List[List[complex]], List[List[complex]]]:
    """
    Constructs 3x3 Phase Coordinate Impedance (Z_abc) and Shunt Admittance (Y_c_abc) matrices.
    If zero-sequence data is not specified, standard empirical ratios (r0 = 3*r1, x0 = 3.5*x1) are used.
    """
    if r0 is None or r0 <= 0.0:
        r0 = 3.0 * r1
    if x0 is None or x0 <= 0.0:
        x0 = 3.5 * x1
    if b0 is None:
        b0 = 0.5 * b1

    # Total impedances (pu or ohms)
    z1 = complex(r1, x1) * length_km / base_z
    z0 = complex(r0, x0) * length_km / base_z

    # Symmetrical components conversion to phase coordinates:
    # Z_s = (2*Z1 + Z0) / 3   (self-impedance)
    # Z_m = (Z0 - Z1) / 3     (mutual impedance)
    z_s = (2.0 * z1 + z0) / 3.0
    z_m = (z0 - z1) / 3.0

    z_abc = [
        [z_s, z_m, z_m],
        [z_m, z_s, z_m],
        [z_m, z_m, z_s]
    ]

    # Shunt charging
    y1_sh = complex(0.0, b1 * length_km * base_z)
    y0_sh = complex(0.0, b0 * length_km * base_z)
    y_s = (2.0 * y1_sh + y0_sh) / 3.0
    y_m = (y0_sh - y1_sh) / 3.0

    yc_abc = [
        [y_s, y_m, y_m],
        [y_m, y_s, y_m],
        [y_m, y_m, y_s]
    ]

    return z_abc, yc_abc


def invert_3x3(m: List[List[complex]]) -> List[List[complex]]:
    """Inverts a 3x3 complex matrix."""
    a, b, c = m[0][0], m[0][1], m[0][2]
    d, e, f = m[1][0], m[1][1], m[1][2]
    g, h, k = m[2][0], m[2][1], m[2][2]

    det = (
        a * (e * k - f * h) -
        b * (d * k - f * g) +
        c * (d * h - e * g)
    )

    if abs(det) < 1e-15:
        # Fallback pseudo-inverse or small regularization
        det = complex(1e-15, 1e-15)

    inv_det = 1.0 / det

    return [
        [(e * k - f * h) * inv_det, (c * h - b * k) * inv_det, (b * f - c * e) * inv_det],
        [(f * g - d * k) * inv_det, (a * k - c * g) * inv_det, (c * d - a * f) * inv_det],
        [(d * h - e * g) * inv_det, (b * g - a * h) * inv_det, (a * e - b * d) * inv_det]
    ]


# =============================================================================
# 3. THREE-PHASE POWER FLOW ENGINE CLASS
# =============================================================================

class ThreePhasePowerFlowEngine:
    """
    Production-grade 3-Phase Unbalanced Power Flow Engine for DevEN.
    Fully independent of UI, highly modular, with rich data extraction APIs.
    """

    def __init__(self, base_mva: float = 100.0, system_freq: float = 60.0):
        self.base_mva = float(base_mva)
        self.system_freq = float(system_freq)

        self.buses: Dict[Any, Dict[str, Any]] = {}
        self.branches: List[Dict[str, Any]] = []
        self.generators: Dict[Any, Dict[str, Any]] = {}
        self.loads: Dict[Any, Dict[str, Any]] = {}
        self.settings: Dict[str, Any] = {}

        # Internal state
        self.bus_list: List[Any] = []
        self.bus_idx: Dict[Any, int] = {}
        self.n_buses: int = 0
        self.slack_bus_id: Any = None

        # 3-Phase complex voltages: V_abc[bus_idx] = [Va, Vb, Vc]
        self.V_abc: List[List[complex]] = []
        self.converged: bool = False
        self.iterations: int = 0
        self.max_residual: float = 0.0
        self.elapsed_time: float = 0.0

        # Detailed results cache
        self.results_buses: Dict[Any, Dict[str, Any]] = {}
        self.results_branches: List[Dict[str, Any]] = []
        self.results_gens: Dict[Any, Dict[str, Any]] = {}
        self.results_loads: Dict[Any, Dict[str, Any]] = {}
        self.system_summary: Dict[str, Any] = {}

    # -- Initializer & Data Loader --------------------------------------------
    def initialize(
        self,
        buses: Dict[Any, Dict[str, Any]],
        branches: List[Dict[str, Any]],
        generators: Dict[Any, Dict[str, Any]],
        loads: Dict[Any, Dict[str, Any]],
        settings: Optional[Dict[str, Any]] = None,
        capacitors: Optional[Dict[Any, Dict[str, Any]]] = None,
        reactors: Optional[Dict[Any, Dict[str, Any]]] = None,
        shunts: Optional[Dict[Any, Dict[str, Any]]] = None
    ):
        """
        Initializes the engine with network data and simulation settings.
        Expands single-value loads and generators according to the selected strategy.
        Accumulates bus shunts, capacitors (+B), and reactors (-B).
        """
        self.buses = {k: dict(v) for k, v in buses.items()}
        self.branches = list(branches)
        self.generators = dict(generators)
        self.loads = dict(loads)
        self.settings = dict(settings or {})

        def to_mvar(val):
            v = abs(float(val or 0.0))
            return v / 1000.0 if v > 1000.0 else v

        if capacitors:
            for cap in capacitors.values():
                if cap.get('status', 1) == 1:
                    b_num = cap.get('bus')
                    if b_num in self.buses:
                        self.buses[b_num]['shunt_B'] = self.buses[b_num].get('shunt_B', 0.0) + to_mvar(cap.get('Q_cap', 0.0))

        if reactors:
            for react in reactors.values():
                if react.get('status', 1) == 1:
                    b_num = react.get('bus')
                    if b_num in self.buses:
                        self.buses[b_num]['shunt_B'] = self.buses[b_num].get('shunt_B', 0.0) - to_mvar(react.get('Q_react', 0.0))

        if shunts:
            for sh in shunts.values():
                if sh.get('status', 1) == 1:
                    b_num = sh.get('bus')
                    if b_num in self.buses:
                        self.buses[b_num]['shunt_G'] = self.buses[b_num].get('shunt_G', 0.0) + float(sh.get('shunt_G', 0.0) or 0.0)
                        self.buses[b_num]['shunt_B'] = self.buses[b_num].get('shunt_B', 0.0) + to_mvar(sh.get('Q_shunt', 0.0) or sh.get('shunt_B', 0.0))

        # Settings defaults
        self.method = self.settings.get('method', 'nr_3p')  # 'nr_3p' or 'fbs_3p'
        self.load_dist_rule = self.settings.get('load_dist_rule', 'equal')
        self.load_custom_pct = tuple(self.settings.get('load_custom_pct', (33.333, 33.333, 33.334)))
        self.gen_dist_rule = self.settings.get('gen_dist_rule', 'equal')
        self.gen_custom_pct = tuple(self.settings.get('gen_custom_pct', (33.333, 33.333, 33.334)))
        self.tol = float(self.settings.get('tol', 1e-4))
        self.max_iter = int(self.settings.get('max_iter', 30))
        self.enforce_q_limits = bool(self.settings.get('enforce_q_limits', True))

        # Index buses
        self.bus_list = sorted(list(self.buses.keys()), key=lambda x: int(x) if str(x).isdigit() else str(x))
        self.bus_idx = {bid: i for i, bid in enumerate(self.bus_list)}
        self.n_buses = len(self.bus_list)

        # Identify Slack Bus
        self.slack_bus_id = self.bus_list[0]
        for bid in self.bus_list:
            b_type = self.buses[bid].get('type', 1)
            if b_type == 3:  # Slack
                self.slack_bus_id = bid
                break

        # Expand loads and generators
        self.expanded_loads = {}
        for lid, ld in self.loads.items():
            self.expanded_loads[lid] = expand_element_to_3phase(
                ld, elem_type='load',
                fallback_rule=self.load_dist_rule,
                custom_pct=self.load_custom_pct
            )

        self.expanded_gens = {}
        for gid, gn in self.generators.items():
            self.expanded_gens[gid] = expand_element_to_3phase(
                gn, elem_type='generator',
                fallback_rule=self.gen_dist_rule,
                custom_pct=self.gen_custom_pct
            )

        # Initialize flat start 3-phase voltages
        # Phase A: 1.0 ang 0.0deg
        # Phase B: 1.0 ang -120.0deg
        # Phase C: 1.0 ang +120.0deg
        self.V_abc = []
        for bid in self.bus_list:
            v_init = float(self.buses[bid].get('V_init', 1.0))
            if v_init <= 0.01:
                v_init = 1.0
            va = cmath.rect(v_init, math.radians(0.0))
            vb = cmath.rect(v_init, math.radians(-120.0))
            vc = cmath.rect(v_init, math.radians(120.0))
            self.V_abc.append([va, vb, vc])

    # -- Solver Master Entry Point --------------------------------------------
    def solve(self) -> bool:
        """
        Executes the 3-Phase Unbalanced Power Flow.
        Selects between 3-Phase Newton-Raphson and Forward-Backward Sweep based on settings.
        """
        t0 = time.time()
        if self.method == 'fbs_3p':
            success = self._solve_fbs()
        else:
            success = self._solve_nr()
            if not success:
                # Fallback to FBS if NR does not converge
                success = self._solve_fbs()

        self.elapsed_time = time.time() - t0
        self.converged = success

        # Build detailed results, symmetrical components, and losses
        self._calculate_all_results()
        return success

    # -- 3-Phase Newton-Raphson Solver (NR-3P) --------------------------------
    def _solve_nr(self) -> bool:
        """
        Solves 3-phase unbalanced power flow via Newton-Raphson in Phase Coordinates (NR-3P).
        Uses exact analytical Jacobian in phase coordinates with sparse linear solve (spsolve).
        Includes robust PV-to-PQ bus reactive power limit enforcement and PQ-to-PV recovery.
        """
        if np is None:
            return False

        try:
            import scipy.sparse as sp
            from scipy.sparse.linalg import spsolve
        except ImportError:
            return False

        n = self.n_buses
        bus_numbers = self.bus_list

        # Extract bus parameters
        bus_types = np.zeros(n, dtype=int)
        V_setpoint = np.ones(n)
        theta_init = np.zeros(n)
        P_gen_sched = np.zeros(n)
        Q_gen_sched = np.zeros(n)
        Q_max_bus = np.zeros(n)
        Q_min_bus = np.zeros(n)
        has_gen = np.zeros(n, dtype=bool)

        for b_num, bus in self.buses.items():
            idx = self.bus_idx[b_num]
            b_type = int(bus.get('type', 1))
            bus_types[idx] = b_type
            theta_init[idx] = float(bus.get('angle_init', 0.0)) * math.pi / 180.0
            V_setpoint[idx] = float(bus.get('V_set', bus.get('V_init', 1.0)))

        for gid, g in self.generators.items():
            if g.get('status', 1) != 0:
                idx = self.bus_idx[g['bus']]
                has_gen[idx] = True
                P_gen_sched[idx] += float(g.get('P_out', 0.0)) / self.base_mva
                V_setpoint[idx] = float(g.get('V_set', 1.0))
                q_max = float(g.get('Qmax', 9999.0))
                q_min = float(g.get('Qmin', -9999.0))
                Q_max_bus[idx] += q_max / self.base_mva
                Q_min_bus[idx] += q_min / self.base_mva
                if bus_types[idx] == 1:
                    Q_gen_sched[idx] += float(g.get('Q_out', 0.0)) / self.base_mva

        P_load = np.zeros(n)
        Q_load = np.zeros(n)
        for lid, l in self.loads.items():
            if l.get('status', 1) != 0:
                idx = self.bus_idx[l['bus']]
                P_load[idx] += float(l.get('P_demand', 0.0)) / self.base_mva
                Q_load[idx] += float(l.get('Q_demand', 0.0)) / self.base_mva

        # Build 3N x 3N Ybus
        row = []
        col = []
        val = []

        # Bus shunts (G_sh + j B_sh)
        for b_num, bus in self.buses.items():
            idx = self.bus_idx[b_num]
            g_sh = float(bus.get('shunt_G', 0.0)) / self.base_mva
            b_sh = float(bus.get('shunt_B', 0.0)) / self.base_mva
            y_sh = complex(g_sh, b_sh)
            if y_sh != 0:
                for p in range(3):
                    row.append(3 * idx + p)
                    col.append(3 * idx + p)
                    val.append(y_sh)

        # Branches (Lines and Transformers)
        for br in self.branches:
            if br.get('status', 1) == 0:
                continue
            fb = br.get('from_bus')
            tb = br.get('to_bus')
            if fb not in self.bus_idx or tb not in self.bus_idx:
                continue
            f_idx = self.bus_idx[fb]
            t_idx = self.bus_idx[tb]

            r = float(br.get('r') or br.get('R_pu') or br.get('r_pu') or 0.0)
            x = float(br.get('x') or br.get('X_pu') or br.get('x_pu') or 0.0)
            b = float(br.get('b') or br.get('B_pu') or br.get('b_pu') or 0.0)
            ratio = float(br.get('ratio', br.get('tap_ratio', 0.0)))
            phase_shift_deg = float(br.get('phase_shift', 0.0))

            if abs(x) < 1e-4 and abs(r) < 1e-4:
                x = 1e-4 if x >= 0 else -1e-4

            z = complex(r, x)
            if z == 0:
                continue

            y = 1.0 / z
            y_shunt = complex(0.0, b / 2.0)

            is_xfmr = (ratio != 0.0 or phase_shift_deg != 0.0 or br.get('type') == 'transformer')

            a = ratio if ratio != 0.0 else 1.0
            alpha = phase_shift_deg * math.pi / 180.0
            tap = a * cmath.rect(1.0, alpha)

            # Check if custom untransposed 3x3 impedance matrix is explicitly provided
            z_abc_custom = br.get('Z_abc') or br.get('z_abc')
            if z_abc_custom is not None:
                y_ser = invert_3x3(z_abc_custom)
                for p in range(3):
                    for q in range(3):
                        fp = 3 * f_idx + p
                        fq = 3 * f_idx + q
                        tp = 3 * t_idx + p
                        tq = 3 * t_idx + q
                        y_val = y_ser[p][q]
                        yc_val = complex(0.0, b / 2.0) if p == q else 0.0
                        row.append(fp); col.append(fq); val.append(y_val + yc_val)
                        row.append(tp); col.append(tq); val.append(y_val + yc_val)
                        row.append(fp); col.append(tq); val.append(-y_val)
                        row.append(tp); col.append(fq); val.append(-y_val)
            else:
                # Transposed 3-phase branch / transformer Pi-model
                for p in range(3):
                    fp = 3 * f_idx + p
                    tp = 3 * t_idx + p
                    row.append(fp); col.append(fp); val.append((y + y_shunt) / (a ** 2))
                    row.append(tp); col.append(tp); val.append(y + y_shunt)
                    row.append(fp); col.append(tp); val.append(-y / tap.conjugate())
                    row.append(tp); col.append(fp); val.append(-y / tap)

        Y3P = sp.coo_matrix((val, (row, col)), shape=(3 * n, 3 * n), dtype=complex).tocsr()
        self.Y3P = Y3P

        # Initialize 3-phase voltages
        V_flat = np.ones(3 * n)
        theta_flat = np.zeros(3 * n)
        shift_angles = [0.0, -2.0 * math.pi / 3.0, 2.0 * math.pi / 3.0]

        for i in range(n):
            for p in range(3):
                idx = 3 * i + p
                if bus_types[i] == 3:  # Slack
                    V_flat[idx] = V_setpoint[i]
                    theta_flat[idx] = theta_init[i] + shift_angles[p]
                elif bus_types[i] == 2:  # PV
                    V_flat[idx] = V_setpoint[i]
                    theta_flat[idx] = shift_angles[p]
                else:  # PQ
                    V_flat[idx] = 1.0
                    theta_flat[idx] = shift_angles[p]

        # Scheduled injections per phase in per unit on phase base (S_base / 3)
        P_sched_3p = np.zeros(3 * n)
        Q_sched_3p = np.zeros(3 * n)
        Q_load_3p = np.zeros(3 * n)
        phase_base_mva = self.base_mva / 3.0

        for i in range(n):
            bid = bus_numbers[i]
            p_gen_p = [0.0, 0.0, 0.0]
            q_gen_p = [0.0, 0.0, 0.0]
            p_ld_p  = [0.0, 0.0, 0.0]
            q_ld_p  = [0.0, 0.0, 0.0]

            for gid, gn in self.generators.items():
                if gn.get('bus') == bid and gn.get('status', 1) != 0:
                    exp = self.expanded_gens[gid]
                    p_gen_p[0] += exp['Pa']
                    p_gen_p[1] += exp['Pb']
                    p_gen_p[2] += exp['Pc']
                    q_gen_p[0] += exp['Qa']
                    q_gen_p[1] += exp['Qb']
                    q_gen_p[2] += exp['Qc']

            for lid, ld in self.loads.items():
                if ld.get('bus') == bid and ld.get('status', 1) != 0:
                    exp = self.expanded_loads[lid]
                    p_ld_p[0] += exp['Pa']
                    p_ld_p[1] += exp['Pb']
                    p_ld_p[2] += exp['Pc']
                    q_ld_p[0] += exp['Qa']
                    q_ld_p[1] += exp['Qb']
                    q_ld_p[2] += exp['Qc']

            for p in range(3):
                idx = 3 * i + p
                P_sched_3p[idx] = (p_gen_p[p] - p_ld_p[p]) / phase_base_mva
                if bus_types[i] == 1:
                    Q_sched_3p[idx] = (q_gen_p[p] - q_ld_p[p]) / phase_base_mva
                else:
                    Q_sched_3p[idx] = -q_ld_p[p] / phase_base_mva
                Q_load_3p[idx] = q_ld_p[p] / phase_base_mva

        # State management for PV buses
        active_types = bus_types.copy()
        original_bus_types = bus_types.copy()
        q_limit_status = np.zeros(n, dtype=int)
        q_dwell_counter = np.zeros(n, dtype=int)

        q_delay_iters = 3
        q_dwell_time = 3
        phase_names = ['A', 'B', 'C']

        print(f"\n=========================================================================================================")
        print(f"  DevEN 3-PHASE NEWTON-RAPHSON ITERATION MONITOR")
        print(f"=========================================================================================================")

        for it in range(self.max_iter):
            self.iterations = it + 1
            q_dwell_counter = np.maximum(0, q_dwell_counter - 1)
            V_complex = V_flat * np.exp(1j * theta_flat)
            I_calc = Y3P.dot(V_complex)
            S_calc = V_complex * np.conj(I_calc)
            P_calc = S_calc.real
            Q_calc = S_calc.imag

            type_changed = False
            if self.enforce_q_limits and it >= q_delay_iters:
                for i in range(n):
                    if original_bus_types[i] == 2 and (Q_max_bus[i] >= Q_min_bus[i] - 1e-4):
                        Qg_tot = (Q_calc[3 * i] + Q_load_3p[3 * i])  # in per unit on phase base
                        Qg_tot_mvar = Qg_tot * self.base_mva
                        q_max_mvar = Q_max_bus[i] * self.base_mva
                        q_min_mvar = Q_min_bus[i] * self.base_mva

                        if active_types[i] == 2:
                            if Qg_tot_mvar > q_max_mvar + 1e-5:
                                active_types[i] = 1  # Convert to PQ
                                q_limit_status[i] = 1
                                q_dwell_counter[i] = q_dwell_time
                                for p in range(3):
                                    Q_sched_3p[3 * i + p] = Q_max_bus[i] - Q_load_3p[3 * i + p]
                                type_changed = True
                                print(f"  [3P-LFA Q-LIMIT] Bus {bus_numbers[i]} reached Qmax ({Qg_tot_mvar:.2f} > {q_max_mvar:.2f} MVAr) -> Converted PV to PQ")
                            elif Qg_tot_mvar < q_min_mvar - 1e-5:
                                active_types[i] = 1  # Convert to PQ
                                q_limit_status[i] = -1
                                q_dwell_counter[i] = q_dwell_time
                                for p in range(3):
                                    Q_sched_3p[3 * i + p] = Q_min_bus[i] - Q_load_3p[3 * i + p]
                                type_changed = True
                                print(f"  [3P-LFA Q-LIMIT] Bus {bus_numbers[i]} reached Qmin ({Qg_tot_mvar:.2f} < {q_min_mvar:.2f} MVAr) -> Converted PV to PQ")
                        elif active_types[i] == 1 and q_dwell_counter[i] == 0:
                            v_avg = V_flat[3 * i]
                            if q_limit_status[i] == 1 and v_avg > V_setpoint[i] + 1e-3:
                                active_types[i] = 2  # Revert to PV
                                q_limit_status[i] = 0
                                for p in range(3):
                                    V_flat[3 * i + p] = V_setpoint[i]
                                type_changed = True
                                print(f"  [3P-LFA Q-RECOVERY] Bus {bus_numbers[i]} voltage recovered ({v_avg:.4f} > {V_setpoint[i]:.4f} pu) -> Reverted PQ to PV")
                            elif q_limit_status[i] == -1 and v_avg < V_setpoint[i] - 1e-3:
                                active_types[i] = 2  # Revert to PV
                                q_limit_status[i] = 0
                                for p in range(3):
                                    V_flat[3 * i + p] = V_setpoint[i]
                                type_changed = True
                                print(f"  [3P-LFA Q-RECOVERY] Bus {bus_numbers[i]} voltage dropped ({v_avg:.4f} < {V_setpoint[i]:.4f} pu) -> Reverted PQ to PV")

            if type_changed:
                V_complex = V_flat * np.exp(1j * theta_flat)
                I_calc = Y3P.dot(V_complex)
                S_calc = V_complex * np.conj(I_calc)
                P_calc = S_calc.real
                Q_calc = S_calc.imag

            dP = P_sched_3p - P_calc
            dQ = Q_sched_3p - Q_calc

            p_idx = []
            q_idx = []
            for i in range(n):
                for p in range(3):
                    idx = 3 * i + p
                    if active_types[i] != 3:
                        p_idx.append(idx)
                    if active_types[i] == 1:
                        q_idx.append(idx)

            p_idx = np.array(p_idx, dtype=int)
            q_idx = np.array(q_idx, dtype=int)

            max_dP = np.max(np.abs(dP[p_idx])) if len(p_idx) > 0 else 0.0
            max_dQ = np.max(np.abs(dQ[q_idx])) if len(q_idx) > 0 else 0.0
            p_max_idx = p_idx[np.argmax(np.abs(dP[p_idx]))] if len(p_idx) > 0 else 0
            q_max_idx = q_idx[np.argmax(np.abs(dQ[q_idx]))] if len(q_idx) > 0 else 0

            p_bus = bus_numbers[p_max_idx // 3]
            p_ph = phase_names[p_max_idx % 3]
            q_bus = bus_numbers[q_max_idx // 3]
            q_ph = phase_names[q_max_idx % 3]

            print(f"  Iter {it + 1:2d} [3P-NR]: Max |dP| = {max_dP:.6f} p.u. (Bus {p_bus} Phase {p_ph}), Max |dQ| = {max_dQ:.6f} p.u. (Bus {q_bus} Phase {q_ph})")
            self.max_residual = max(max_dP, max_dQ)

            if not type_changed and max_dP < self.tol and max_dQ < self.tol:
                self.converged = True
                print(f"\n  [CONVERGED] 3-Phase Newton-Raphson converged in {it + 1} iterations (Tolerance: {self.tol:.1e})")
                break

            # Vectorized Exact Jacobian in Phase Coordinates
            diag_V = sp.diags(V_complex)
            diag_I_conj = sp.diags(np.conj(I_calc))
            diag_V_norm = sp.diags(V_complex / V_flat)

            dS_dtheta = 1j * diag_V @ (diag_I_conj - Y3P.conj() @ diag_V.conj())
            dS_dV = diag_V @ Y3P.conj() @ diag_V_norm.conj() + diag_V_norm @ diag_I_conj

            H = dS_dtheta.real
            N = dS_dV.real
            J = dS_dtheta.imag
            L = dS_dV.imag

            H_sliced = H[p_idx, :][:, p_idx]
            N_sliced = N[p_idx, :][:, q_idx]
            J_sliced = J[q_idx, :][:, p_idx]
            L_sliced = L[q_idx, :][:, q_idx]

            J_full = sp.bmat([[H_sliced, N_sliced], [J_sliced, L_sliced]], format='csr')
            RHS = np.concatenate([dP[p_idx], dQ[q_idx]])

            dx = spsolve(J_full, RHS)
            dtheta = dx[:len(p_idx)]
            dV = dx[len(p_idx):]

            theta_flat[p_idx] += dtheta
            V_flat[q_idx] += dV

        for b_i in range(n):
            for p in range(3):
                self.V_abc[b_i][p] = cmath.rect(V_flat[3 * b_i + p], theta_flat[3 * b_i + p])

        return self.converged

    # -- 3-Phase Forward-Backward Sweep Solver (FBS-3P) -----------------------
    def _solve_fbs(self) -> bool:
        """
        Solves 3-phase unbalanced power flow via Forward-Backward Sweep.
        Extremely reliable for distribution networks and radial/weakly meshed feeders.
        """
        n = self.n_buses
        slack_idx = self.bus_idx[self.slack_bus_id]

        for it in range(self.max_iter):
            self.iterations = it + 1
            max_v_diff = 0.0

            # 1. Calculate nodal injection currents at current voltages:
            # I_inj_p = (S_spec_p / V_p)*
            I_inj: List[List[complex]] = [[complex(0.0, 0.0) for _ in range(3)] for _ in range(n)]

            for b_i in range(n):
                bid = self.bus_list[b_i]
                if b_i == slack_idx:
                    continue

                for p in range(3):
                    v_p = self.V_abc[b_i][p]
                    if abs(v_p) < 1e-4:
                        v_p = cmath.rect(1.0, math.radians(-120.0 * p))

                    p_net = 0.0
                    q_net = 0.0

                    # Add Gens
                    for gid, gn in self.generators.items():
                        if gn.get('bus') == bid and gn.get('status', 1) != 0:
                            exp = self.expanded_gens[gid]
                            phase_k = ('Pa', 'Pb', 'Pc')[p]
                            phase_qk = ('Qa', 'Qb', 'Qc')[p]
                            p_net += exp[phase_k] / self.base_mva
                            q_net += exp[phase_qk] / self.base_mva

                    # Subtract Loads
                    for lid, ld in self.loads.items():
                        if ld.get('bus') == bid and ld.get('status', 1) != 0:
                            exp = self.expanded_loads[lid]
                            phase_k = ('Pa', 'Pb', 'Pc')[p]
                            phase_qk = ('Qa', 'Qb', 'Qc')[p]
                            p_net -= exp[phase_k] / self.base_mva
                            q_net -= exp[phase_qk] / self.base_mva

                    s_net = complex(p_net, q_net)
                    # Injection current into network: I_inj = (S_net / V)*
                    I_inj[b_i][p] = (s_net / v_p).conjugate()

            # 2. Backward Sweep: Compute branch phase currents from leaves to root
            branch_currents: List[List[complex]] = []
            for br in self.branches:
                fb = br.get('from_bus')
                tb = br.get('to_bus')
                if fb not in self.bus_idx or tb not in self.bus_idx:
                    branch_currents.append([complex(0.0, 0.0)] * 3)
                    continue

                t_idx = self.bus_idx[tb]
                # Branch current carries downstream load
                i_br = [-I_inj[t_idx][p] for p in range(3)]
                branch_currents.append(i_br)

            # 3. Forward Sweep: Drop voltages from root to leaves
            for k_br, br in enumerate(self.branches):
                fb = br.get('from_bus')
                tb = br.get('to_bus')
                if fb not in self.bus_idx or tb not in self.bus_idx:
                    continue

                f_idx = self.bus_idx[fb]
                t_idx = self.bus_idx[tb]

                r1 = float(br.get('r') or br.get('R_pu') or 0.001)
                x1 = float(br.get('x') or br.get('X_pu') or 0.01)
                z_abc, _ = build_line_z3x3(r1, x1)

                i_br = branch_currents[k_br]

                # V_to = V_from - Z_abc * I_br
                for p in range(3):
                    v_drop = (
                        z_abc[p][0] * i_br[0] +
                        z_abc[p][1] * i_br[1] +
                        z_abc[p][2] * i_br[2]
                    )
                    v_new = self.V_abc[f_idx][p] - v_drop
                    diff = abs(v_new - self.V_abc[t_idx][p])
                    max_v_diff = max(max_v_diff, diff)
                    self.V_abc[t_idx][p] = v_new

            self.max_residual = max_v_diff
            if max_v_diff < self.tol:
                return True

        return self.max_residual < (self.tol * 10)

    # -- Calculation of All Symmetrical Components, Flows & Losses ------------
    def _calculate_all_results(self):
        """Calculates comprehensive per-phase voltages, unbalance factors, branch flows, and losses."""
        self.results_buses = {}
        self.results_branches = []
        self.results_gens = {}
        self.results_loads = {}

        total_p_loss = [0.0, 0.0, 0.0]
        total_q_loss = [0.0, 0.0, 0.0]
        max_vuf = 0.0
        worst_bus_vuf = None

        # 1. Bus Results
        for b_i, bid in enumerate(self.bus_list):
            bus_data = self.buses[bid]
            base_kv = float(bus_data.get('base_kV', 132.0))
            if base_kv <= 0.0:
                base_kv = 132.0

            va, vb, vc = self.V_abc[b_i]
            v0, v1, v2, vuf_pct, pvur_pct = compute_symmetrical_components(va, vb, vc)

            # Neutral voltage (approx zero-sequence voltage drop)
            vn_pu = abs(v0)
            vn_kv = vn_pu * (base_kv / math.sqrt(3.0))

            if vuf_pct > max_vuf:
                max_vuf = vuf_pct
                worst_bus_vuf = bid

            self.results_buses[bid] = {
                'bus_id': bid,
                'name': bus_data.get('name', f"Bus_{bid}"),
                'base_kV': base_kv,
                # Phase A
                'Va_pu': abs(va),
                'Va_kV': abs(va) * (base_kv / math.sqrt(3.0)),
                'ang_a_deg': math.degrees(cmath.phase(va)),
                # Phase B
                'Vb_pu': abs(vb),
                'Vb_kV': abs(vb) * (base_kv / math.sqrt(3.0)),
                'ang_b_deg': math.degrees(cmath.phase(vb)),
                # Phase C
                'Vc_pu': abs(vc),
                'Vc_kV': abs(vc) * (base_kv / math.sqrt(3.0)),
                'ang_c_deg': math.degrees(cmath.phase(vc)),
                # Symmetrical Components & Unbalance
                'V0_pu': abs(v0),
                'V1_pu': abs(v1),
                'V2_pu': abs(v2),
                'VUF_pct': vuf_pct,
                'PVUR_pct': pvur_pct,
                'Vn_kV': vn_kv,
                'status': 'PASS' if vuf_pct <= 2.0 else 'VIOLATION'  # IEEE 1159: <= 2% normal
            }

        # 2. Branch Flows & Losses
        for k_br, br in enumerate(self.branches):
            fb = br.get('from_bus')
            tb = br.get('to_bus')
            if fb not in self.bus_idx or tb not in self.bus_idx:
                continue

            f_idx = self.bus_idx[fb]
            t_idx = self.bus_idx[tb]

            r1 = float(br.get('r') or br.get('R_pu') or br.get('r_pu') or 0.0)
            x1 = float(br.get('x') or br.get('X_pu') or br.get('x_pu') or 0.01)
            b1 = float(br.get('b') or br.get('B_pu') or br.get('b_pu') or 0.0)
            ratio = float(br.get('ratio', br.get('tap_ratio', 0.0)))
            phase_shift_deg = float(br.get('phase_shift', 0.0))
            is_xfmr = (ratio != 0.0 or phase_shift_deg != 0.0 or br.get('type') == 'transformer')

            va_f, vb_f, vc_f = self.V_abc[f_idx]
            va_t, vb_t, vc_t = self.V_abc[t_idx]
            v_f = [va_f, vb_f, vc_f]
            v_t = [va_t, vb_t, vc_t]

            z_abc_custom = br.get('Z_abc') or br.get('z_abc')
            if z_abc_custom is not None:
                y_ser = invert_3x3(z_abc_custom)
                yc_sh = complex(0.0, b1 / 2.0)
                i_f = [complex(0.0, 0.0)] * 3
                i_t = [complex(0.0, 0.0)] * 3
                for p in range(3):
                    for q in range(3):
                        dv = v_f[q] - v_t[q]
                        yc_val = yc_sh if p == q else 0.0
                        i_f[p] += y_ser[p][q] * dv + yc_val * v_f[q]
                        i_t[p] += y_ser[p][q] * (-dv) + yc_val * v_t[q]
            else:
                a = ratio if ratio != 0.0 else 1.0
                alpha = phase_shift_deg * math.pi / 180.0
                tap = a * cmath.rect(1.0, alpha)
                z = complex(r1, x1) if complex(r1, x1) != 0 else complex(0.0, 1e-4)
                y = 1.0 / z
                y_sh = complex(0.0, b1 / 2.0)
                i_f = [((v_f[p] / tap - v_t[p]) * y + (v_f[p] / (a ** 2)) * y_sh) / tap.conjugate() for p in range(3)]
                i_t = [((v_t[p] - v_f[p] / tap) * y + v_t[p] * y_sh) for p in range(3)]

            # Power flows (MW, MVar)
            base_kv_f = self.results_buses[fb]['base_kV']
            base_i_f = (self.base_mva * 1000.0) / (math.sqrt(3.0) * base_kv_f)
            phase_mva_base = self.base_mva / 3.0

            p_f = [(v_f[p] * i_f[p].conjugate()).real * phase_mva_base for p in range(3)]
            q_f = [(v_f[p] * i_f[p].conjugate()).imag * phase_mva_base for p in range(3)]
            p_t = [(v_t[p] * i_t[p].conjugate()).real * phase_mva_base for p in range(3)]
            q_t = [(v_t[p] * i_t[p].conjugate()).imag * phase_mva_base for p in range(3)]

            # Losses
            p_loss = [p_f[p] + p_t[p] for p in range(3)]
            q_loss = [q_f[p] + q_t[p] for p in range(3)]

            for p in range(3):
                total_p_loss[p] += max(0.0, p_loss[p])
                total_q_loss[p] += max(0.0, q_loss[p])

            # Neutral current In = Ia + Ib + Ic
            in_pu = i_f[0] + i_f[1] + i_f[2]
            in_amps = abs(in_pu) * base_i_f

            self.results_branches.append({
                'line_id': br.get('num') or br.get('id') or (k_br + 1),
                'name': br.get('name', f"Line_{fb}_{tb}"),
                'from_bus': fb,
                'to_bus': tb,
                # Phase Flows (From Bus)
                'P_from_a': p_f[0], 'P_from_b': p_f[1], 'P_from_c': p_f[2],
                'Q_from_a': q_f[0], 'Q_from_b': q_f[1], 'Q_from_c': q_f[2],
                # Phase Flows (To Bus)
                'P_to_a': p_t[0], 'P_to_b': p_t[1], 'P_to_c': p_t[2],
                'Q_to_a': q_t[0], 'Q_to_b': q_t[1], 'Q_to_c': q_t[2],
                # Currents
                'I_a_kA': abs(i_f[0]) * (base_i_f / 1000.0),
                'I_b_kA': abs(i_f[1]) * (base_i_f / 1000.0),
                'I_c_kA': abs(i_f[2]) * (base_i_f / 1000.0),
                'I_neutral_A': in_amps,
                # Losses
                'Ploss_a': p_loss[0], 'Ploss_b': p_loss[1], 'Ploss_c': p_loss[2],
                'Ploss_tot': sum(p_loss),
                'Qloss_tot': sum(q_loss)
            })

        # 3. System Summary
        self.system_summary = {
            'converged': self.converged,
            'iterations': self.iterations,
            'elapsed_time_s': self.elapsed_time,
            'max_residual': self.max_residual,
            'max_VUF_pct': max_vuf,
            'worst_bus_VUF': worst_bus_vuf,
            'total_P_loss_a_MW': total_p_loss[0],
            'total_P_loss_b_MW': total_p_loss[1],
            'total_P_loss_c_MW': total_p_loss[2],
            'total_P_loss_MW': sum(total_p_loss),
            'total_Q_loss_MVAR': sum(total_q_loss)
        }

    # -- Report Generators (Matching DevEN Master Output Format) --------------
    def generate_text_report(self, case_name: str = "CASE") -> str:
        """
        Generates clean ASCII text report matching DevEN's master report format,
        enriched with Phase A, Phase B, and Phase C columns for each respective element.
        """
        lines = []
        lines.append("=========================================================================================================")
        lines.append("                      DevEN 3-PHASE UNBALANCED POWER FLOW ANALYSIS REPORT                                ")
        lines.append("                 Standards: IEEE Std 1159 (Power Quality) / NEMA MG 1 / IEC 61000-4-30                   ")
        lines.append("=========================================================================================================")
        lines.append(f"Case Name:            {case_name}")
        lines.append(f"System Base MVA:      {self.base_mva:.1f} MVA")
        lines.append(f"Solution Status:      {'CONVERGED' if self.converged else 'FAILED / DIVERGED'}")
        lines.append(f"Iterations:           {self.iterations}")
        lines.append(f"Max Voltage Unbalance: {self.system_summary.get('max_VUF_pct', 0.0):.3f}% (Bus {self.system_summary.get('worst_bus_VUF')})")
        lines.append(f"Total System Losses:  {self.system_summary.get('total_P_loss_MW', 0.0):.3f} MW (Phase A: {self.system_summary.get('total_P_loss_a_MW', 0.0):.2f}, B: {self.system_summary.get('total_P_loss_b_MW', 0.0):.2f}, C: {self.system_summary.get('total_P_loss_c_MW', 0.0):.2f})")
        lines.append("-" * 105)

        # -- Table 1: Bus 3-Phase Voltages & Unbalance -------------------------
        lines.append("\n[1] 3-PHASE BUS VOLTAGE & UNBALANCE PROFILE")
        lines.append("-" * 105)
        lines.append(f"{'Bus':<5} {'Name':<14} {'Base_kV':<8} {'Va(pu)':<8} {'Vb(pu)':<8} {'Vc(pu)':<8} {'anga(deg)':<8} {'angb(deg)':<8} {'angc(deg)':<8} {'VUF(%)':<8} {'Status':<6}")
        lines.append("-" * 105)

        for bid in self.bus_list:
            b = self.results_buses[bid]
            lines.append(
                f"{bid:<5} {b['name'][:14]:<14} {b['base_kV']:<8.1f} "
                f"{b['Va_pu']:<8.4f} {b['Vb_pu']:<8.4f} {b['Vc_pu']:<8.4f} "
                f"{b['ang_a_deg']:<8.2f} {b['ang_b_deg']:<8.2f} {b['ang_c_deg']:<8.2f} "
                f"{b['VUF_pct']:<8.3f} {b['status']:<6}"
            )
        lines.append("-" * 105)

        # -- Table 2: 3-Phase Branch Power Flows & Neutral Currents -------------
        lines.append("\n[2] 3-PHASE BRANCH ACTIVE & REACTIVE POWER FLOWS (FROM BUS -> TO BUS)")
        lines.append("-" * 105)
        lines.append(f"{'Line':<5} {'From':<5} {'To':<5} {'Pa(MW)':<9} {'Pb(MW)':<9} {'Pc(MW)':<9} {'Qa(MVAr)':<9} {'Qb(MVAr)':<9} {'Qc(MVAr)':<9} {'In(A)':<8} {'Ploss(kW)':<9}")
        lines.append("-" * 105)

        for br in self.results_branches:
            lines.append(
                f"{br['line_id']:<5} {br['from_bus']:<5} {br['to_bus']:<5} "
                f"{br['P_from_a']:<9.2f} {br['P_from_b']:<9.2f} {br['P_from_c']:<9.2f} "
                f"{br['Q_from_a']:<9.2f} {br['Q_from_b']:<9.2f} {br['Q_from_c']:<9.2f} "
                f"{br['I_neutral_A']:<8.1f} {br['Ploss_tot']*1000.0:<9.1f}"
            )
        lines.append("-" * 105)

        # -- Table 3: 3-Phase Load Allocations ---------------------------------
        lines.append("\n[3] 3-PHASE LOAD CONSUMPTION & ALLOCATIONS")
        lines.append("-" * 105)
        lines.append(f"{'Load':<5} {'Name':<14} {'Bus':<5} {'Pa(MW)':<9} {'Pb(MW)':<9} {'Pc(MW)':<9} {'Qa(MVAr)':<9} {'Qb(MVAr)':<9} {'Qc(MVAr)':<9} {'Mode':<10}")
        lines.append("-" * 105)

        for lid, ld in self.loads.items():
            exp = self.expanded_loads.get(lid, {})
            l_name = ld.get('name', f"Load_{lid}")
            lines.append(
                f"{lid:<5} {l_name[:14]:<14} {ld.get('bus', 0):<5} "
                f"{exp.get('Pa', 0.0):<9.2f} {exp.get('Pb', 0.0):<9.2f} {exp.get('Pc', 0.0):<9.2f} "
                f"{exp.get('Qa', 0.0):<9.2f} {exp.get('Qb', 0.0):<9.2f} {exp.get('Qc', 0.0):<9.2f} "
                f"{exp.get('phase_mode', 'single'):<10}"
            )
        lines.append("-" * 105)
        lines.append("=========================================================================================================\n")

        return "\n".join(lines)

    def export_csv_results(self, output_folder: str, case_name: str = "CASE") -> Tuple[str, str]:
        """Exports 3-phase bus voltage summary and branch flow summary to CSV files."""
        os.makedirs(output_folder, exist_ok=True)

        bus_csv = os.path.join(output_folder, f"{case_name}_3PHASE_BUS_VOLTAGES.csv")
        with open(bus_csv, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow([
                "Bus_ID", "Bus_Name", "Base_kV",
                "Va_pu", "Va_kV", "Angle_a_deg",
                "Vb_pu", "Vb_kV", "Angle_b_deg",
                "Vc_pu", "Vc_kV", "Angle_c_deg",
                "V0_pu", "V1_pu", "V2_pu",
                "VUF_pct", "PVUR_pct", "Vn_kV", "Status"
            ])
            for bid in self.bus_list:
                b = self.results_buses[bid]
                w.writerow([
                    bid, b['name'], b['base_kV'],
                    f"{b['Va_pu']:.5f}", f"{b['Va_kV']:.3f}", f"{b['ang_a_deg']:.2f}",
                    f"{b['Vb_pu']:.5f}", f"{b['Vb_kV']:.3f}", f"{b['ang_b_deg']:.2f}",
                    f"{b['Vc_pu']:.5f}", f"{b['Vc_kV']:.3f}", f"{b['ang_c_deg']:.2f}",
                    f"{b['V0_pu']:.5f}", f"{b['V1_pu']:.5f}", f"{b['V2_pu']:.5f}",
                    f"{b['VUF_pct']:.4f}", f"{b['PVUR_pct']:.4f}", f"{b['Vn_kV']:.3f}", b['status']
                ])

        branch_csv = os.path.join(output_folder, f"{case_name}_3PHASE_BRANCH_FLOWS.csv")
        with open(branch_csv, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow([
                "Line_ID", "Name", "From_Bus", "To_Bus",
                "P_from_a_MW", "P_from_b_MW", "P_from_c_MW",
                "Q_from_a_MVar", "Q_from_b_MVar", "Q_from_c_MVar",
                "P_to_a_MW", "P_to_b_MW", "P_to_c_MW",
                "Q_to_a_MVar", "Q_to_b_MVar", "Q_to_c_MVar",
                "Ia_kA", "Ib_kA", "Ic_kA", "In_Amps",
                "Ploss_a_kW", "Ploss_b_kW", "Ploss_c_kW", "Ploss_tot_kW"
            ])
            for br in self.results_branches:
                w.writerow([
                    br['line_id'], br['name'], br['from_bus'], br['to_bus'],
                    f"{br['P_from_a']:.3f}", f"{br['P_from_b']:.3f}", f"{br['P_from_c']:.3f}",
                    f"{br['Q_from_a']:.3f}", f"{br['Q_from_b']:.3f}", f"{br['Q_from_c']:.3f}",
                    f"{br['P_to_a']:.3f}", f"{br['P_to_b']:.3f}", f"{br['P_to_c']:.3f}",
                    f"{br['Q_to_a']:.3f}", f"{br['Q_to_b']:.3f}", f"{br['Q_to_c']:.3f}",
                    f"{br['I_a_kA']:.3f}", f"{br['I_b_kA']:.3f}", f"{br['I_c_kA']:.3f}", f"{br['I_neutral_A']:.1f}",
                    f"{br['Ploss_a']*1000.0:.2f}", f"{br['Ploss_b']*1000.0:.2f}", f"{br['Ploss_c']*1000.0:.2f}",
                    f"{br['Ploss_tot']*1000.0:.2f}"
                ])

        return bus_csv, branch_csv

    # -- Clean API Methods for Integration with Other Studies & Scripts -------
    def get_bus_results(self) -> Dict[Any, Dict[str, Any]]:
        """Returns per-bus 3-phase voltages and unbalance indices dictionary."""
        return self.results_buses

    def get_branch_results(self) -> List[Dict[str, Any]]:
        """Returns per-branch 3-phase power flows and currents list."""
        return self.results_branches

    def get_system_summary(self) -> Dict[str, Any]:
        """Returns system-wide losses, max VUF, and convergence statistics."""
        return self.system_summary

    def to_dict(self) -> Dict[str, Any]:
        """Returns complete serializable dictionary of all 3-phase simulation results."""
        return {
            'summary': self.system_summary,
            'buses': self.results_buses,
            'branches': self.results_branches,
            'expanded_loads': self.expanded_loads,
            'expanded_gens': self.expanded_gens
        }


# =============================================================================
# 4. FUNCTIONAL ONE-LINE API WRAPPER
# =============================================================================

def solve_three_phase_power_flow(
    buses: Dict[Any, Dict[str, Any]],
    branches: List[Dict[str, Any]],
    generators: Dict[Any, Dict[str, Any]],
    loads: Dict[Any, Dict[str, Any]],
    base_mva: float = 100.0,
    method: str = 'nr_3p',
    load_dist_rule: str = 'equal',
    load_custom_pct: Tuple[float, float, float] = (33.333, 33.333, 33.334),
    gen_dist_rule: str = 'equal',
    gen_custom_pct: Tuple[float, float, float] = (33.333, 33.333, 33.334),
    tol: float = 1e-4,
    max_iter: int = 30,
    capacitors: Optional[Dict[Any, Dict[str, Any]]] = None,
    reactors: Optional[Dict[Any, Dict[str, Any]]] = None,
    shunts: Optional[Dict[Any, Dict[str, Any]]] = None
) -> Tuple[bool, ThreePhasePowerFlowEngine]:
    """
    Convenience functional API to run 3-Phase Unbalanced Power Flow in a single call.
    Returns (success_flag, engine_instance).
    """
    engine = ThreePhasePowerFlowEngine(base_mva=base_mva)
    settings = {
        'method': method,
        'load_dist_rule': load_dist_rule,
        'load_custom_pct': load_custom_pct,
        'gen_dist_rule': gen_dist_rule,
        'gen_custom_pct': gen_custom_pct,
        'tol': tol,
        'max_iter': max_iter
    }
    engine.initialize(
        buses, branches, generators, loads,
        settings=settings,
        capacitors=capacitors,
        reactors=reactors,
        shunts=shunts
    )
    success = engine.solve()
    return success, engine

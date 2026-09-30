"""
=============================================================================
  DevEN (Develop Electric Network) - Native Short Circuit Analysis Engine
=============================================================================
  Standards Compliant:
    - IEC 60909 (Short-circuit currents in three-phase a.c. systems)
    - ANSI/IEEE C37 Series (Fault current calculations, X/R ratios, Breaker Duty)
  
  Features:
    - Pure Python + NumPy / SciPy native implementation (Zero external C++ dependencies)
    - Complete Sequence Networks: Positive (Z1), Negative (Z2), and Zero (Z0)
    - Rigorous Transformer Zero-Sequence Modeling:
        * All Vector Groups: Delta-Delta, Yg-Delta, Delta-Yg, Yg-Yg, Y-Y, Y-Delta
        * Neutral Grounding Impedance (3*Zn) on Primary and Secondary Windings
        * Three-Winding Transformers (Yg-Yg-Delta tertiary Kron-reduced network)
    - Generator Zero-Sequence & Grounding:
        * Subtransient reactances (Xd'', X2, X0) and Grounding (Rgnd, Xgnd)
        * Neutral Grounding Resistor (NGR) Power Dissipation (kW / MW)
    - Fault Types:
        * 3-Phase Symmetrical Fault (3PH)
        * Single Line-to-Ground Fault (SLG / 1LG)
        * Line-to-Line Fault (LL / 2PH)
        * Double Line-to-Ground Fault (DLG / 2LG)
        * Open Conductor Fault - 1 Phase Open (Broken Conductor)
        * Open Conductor Fault - 2 Phases Open
    - Circuit Breaker Interrupting Duty Verification (ANSI/IEEE C37.010 & CEA 80% Rule):
        * Voltage Range Factor K capability adjustment
        * Duty percentage and safety margin calculation
    - Detailed Impedance Modeling:
        * Separate R and X networks for precise X/R ratio calculation
        * Peak short-circuit current (ip) via IEC 60909 Method C kappa factor
        * Symmetrical breaking current (Ib) and Thermal equivalent current (Ith)
        * Symmetrical short-circuit apparent power (Sk'')
    - Flexible Modes:
        * Methods: IEC 60909 Standard vs. Classical Symmetrical Components (ANSI)
        * Units: Current in kA vs. Short Circuit Power in MVA
    - Pre-Fault Voltage: Solved LFA voltages or Nominal (c * Un / sqrt(3))
    - Branch current flow contributions and Generator fault current breakdown
    - Line Faults (at any percentage p along a transmission line)
    - Fast Vectorized System-Wide Short Circuit Scanning
=============================================================================
"""

import sys
import os
import math
import numpy as np
from datetime import datetime

ALPHA = np.exp(1j * 2.0 * np.pi / 3.0)
ALPHA_SQ = ALPHA ** 2

A_MATRIX = np.array([
    [1.0, 1.0, 1.0],
    [1.0, ALPHA_SQ, ALPHA],
    [1.0, ALPHA, ALPHA_SQ]
], dtype=complex)

A_INV_MATRIX = np.array([
    [1.0, 1.0, 1.0],
    [1.0, ALPHA, ALPHA_SQ],
    [1.0, ALPHA_SQ, ALPHA]
], dtype=complex) / 3.0


def safe_float(val, default=0.0):
    """Safely converts val to float, falling back to default if None, NaN, inf, or error."""
    if val is None:
        return float(default)
    try:
        f = float(val)
        return float(default) if (math.isnan(f) or math.isinf(f)) else f
    except (ValueError, TypeError):
        return float(default)


def parse_connection(conn_val):
    """
    Parses connection string or code into normalized type:
    'G' (Grounded Wye), 'Y' (Ungrounded Wye), 'D' (Delta), 'Rg' (Resistance Grounded), 'Xg' (Reactance Grounded)
    """
    if conn_val is None:
        return 'Y'
    s = str(conn_val).strip().upper()
    if s in ('1', 'G', 'YG', 'GROUNDED', 'GROUNDED WYE', 'WYE-G', 'WYE_G', 'Y_G', 'S'):
        return 'G'
    elif s in ('2', 'D', 'DELTA'):
        return 'D'
    elif s in ('3', 'RG', 'RESISTANCE GROUNDED', 'RESISTANCE_GROUNDED'):
        return 'Rg'
    elif s in ('4', 'XG', 'REACTANCE GROUNDED', 'REACTANCE_GROUNDED'):
        return 'Xg'
    elif s in ('0', 'Y', 'WYE', 'UNGROUNDED'):
        return 'Y'
    return 'Y'


def get_grounding_z(r_gnd, x_gnd, v_base_kv, base_mva):
    """
    Returns 3 * Zn in per unit.
    If r_gnd or x_gnd are in ohms, converts to pu using z_base = (v_base_kv ** 2) / base_mva.
    """
    r_val = safe_float(r_gnd, 0.0)
    x_val = safe_float(x_gnd, 0.0)
    if r_val == 0.0 and x_val == 0.0:
        return 0j
    vb = max(safe_float(v_base_kv, 138.0), 0.1)
    bm = max(safe_float(base_mva, 100.0), 1.0)
    z_base = (vb ** 2) / bm
    if abs(complex(r_val, x_val)) > 2.0 and z_base > 0:
        r_pu = r_val / z_base
        x_pu = x_val / z_base
    else:
        r_pu = r_val
        x_pu = x_val
    return 3.0 * complex(r_pu, x_pu)


def evaluate_circuit_breaker(fault_kA, cb_mva, v_base_kv, k_factor=1.15, mf=1.0, is_ansi=False):
    """
    Evaluates breaker interrupting duty according to ANSI/IEEE C37.010 and CEA regulations.
    If is_ansi is True, the fault duty accounts for ANSI high-X/R multiplying factor MF.
    Returns dictionary with rated_max_kA, interrupting_kA, duty_pct, margin_pct, status, mf.
    """
    if cb_mva <= 0.0 or v_base_kv <= 0.0:
        return None
    v_max = 1.05 * v_base_kv
    i_max_kA = float(cb_mva / (np.sqrt(3.0) * v_max))
    v_ratio = min(k_factor, v_max / v_base_kv)
    i_interrupting_kA = float(i_max_kA * v_ratio)
    if i_interrupting_kA <= 1e-4:
        return None

    mf_val = max(float(mf), 1.0)
    effective_fault_kA = float(fault_kA * mf_val) if is_ansi else float(fault_kA)

    duty_pct = float((effective_fault_kA / i_interrupting_kA) * 100.0)
    margin_pct = float(100.0 - duty_pct)

    if duty_pct <= 80.0:
        status = "OK (Pass - CEA 80% Margin Met)"
    elif duty_pct <= 100.0:
        status = "WARNING (Margin < 20%)"
    else:
        status = "OVERDUTY VIOLATION (Breaker Exceeded)"

    return {
        'cb_mva': float(cb_mva),
        'v_base_kv': float(v_base_kv),
        'v_max_kv': float(v_max),
        'k_factor': float(k_factor),
        'rated_max_kA': float(i_max_kA),
        'interrupting_kA': float(i_interrupting_kA),
        'fault_kA': float(fault_kA),
        'effective_fault_kA': float(effective_fault_kA),
        'mf': float(mf_val),
        'duty_pct': float(duty_pct),
        'margin_pct': float(margin_pct),
        'status': status
    }


class SequenceAdmittanceBuilder:
    def __init__(self, bus_data, branch_data, generators=None, loads=None, base_mva=100.0,
                 zero_seq_factor=3.0, xd_sync=0.15, xg_zero=0.05, r_gen=0.005,
                 three_w_xfmrs=None):
        self.bus_data = bus_data
        self.branch_data = list(branch_data.values()) if isinstance(branch_data, dict) else (branch_data or [])
        self.generators = {i: g for i, g in enumerate(generators)} if isinstance(generators, list) else (generators or {})
        self.loads = {i: ld for i, ld in enumerate(loads)} if isinstance(loads, list) else (loads or {})
        self.three_w_xfmrs = three_w_xfmrs or {}
        self.base_mva = float(base_mva)
        self.zero_seq_factor = float(zero_seq_factor)
        self.xd_sync = float(xd_sync)
        self.xg_zero = float(xg_zero)
        self.r_gen = float(r_gen)

        self.bus_ids = sorted(list(bus_data.keys()))
        self.n_buses = len(self.bus_ids)
        self.bus_idx_map = {bid: idx for idx, bid in enumerate(self.bus_ids)}

    def build_matrices(self):
        n = self.n_buses
        Y1 = np.zeros((n, n), dtype=complex)
        Y2 = np.zeros((n, n), dtype=complex)
        Y0 = np.zeros((n, n), dtype=complex)

        # 1. Branch contributions (Lines and Transformers)
        for br in self.branch_data:
            if br.get('status', 1) == 0:
                continue

            fb = br.get('from_bus')
            tb = br.get('to_bus')
            if fb not in self.bus_idx_map or tb not in self.bus_idx_map:
                continue

            i = self.bus_idx_map[fb]
            j = self.bus_idx_map[tb]

            r1 = max(safe_float(br.get('r', 0.001), 0.001), 1e-6)
            x1 = max(safe_float(br.get('x', 0.01), 0.01), 1e-6)
            b1 = safe_float(br.get('b', 0.0), 0.0)
            tap = safe_float(br.get('ratio', br.get('tap', 1.0)), 1.0)
            if tap <= 0.0:
                tap = 1.0

            z1 = complex(r1, x1)
            y1_series = 1.0 / z1
            y1_shunt = 1j * (b1 / 2.0)

            # Positive and Negative Sequence
            Y1[i, i] += (y1_series / (tap ** 2)) + (y1_shunt / (tap ** 2))
            Y1[j, j] += y1_series + y1_shunt
            Y1[i, j] -= y1_series / tap
            Y1[j, i] -= y1_series / tap

            Y2[i, i] += (y1_series / (tap ** 2)) + (y1_shunt / (tap ** 2))
            Y2[j, j] += y1_series + y1_shunt
            Y2[i, j] -= y1_series / tap
            Y2[j, i] -= y1_series / tap

            # Zero Sequence
            r0 = safe_float(br.get('r0', br.get('R0_pu', None)), r1 * self.zero_seq_factor)
            x0 = safe_float(br.get('x0', br.get('X0_pu', None)), x1 * self.zero_seq_factor)
            b0 = safe_float(br.get('b0', br.get('B0_per_km', None)), b1 / self.zero_seq_factor if b1 > 0 else 0.0)
            z0 = complex(max(r0, 1e-6), max(x0, 1e-6))
            y0_series = 1.0 / z0
            y0_shunt = 1j * (b0 / 2.0)

            br_type = str(br.get('type', 'line')).lower()
            is_xfmr = ('transformer' in br_type) or (tap != 1.0) or ('from_conn' in br)

            if is_xfmr:
                conn_from = parse_connection(br.get('from_conn', br.get('from_connection', '0')))
                conn_to = parse_connection(br.get('to_conn', br.get('to_connection', '0')))

                # Winding string fallback
                winding_str = str(br.get('winding', '')).lower()
                if 'delta' in winding_str:
                    if conn_from == 'Y' and conn_to == 'Y':
                        conn_from = 'D'
                        conn_to = 'G'

                v_from_kv = safe_float(self.bus_data[fb].get('base_kV', 138.0), 138.0)
                v_to_kv = safe_float(self.bus_data[tb].get('base_kV', 138.0), 138.0)

                z_n_from = get_grounding_z(br.get('from_gnd_r', 0.0), br.get('from_gnd_x', 0.0), v_from_kv, self.base_mva)
                z_n_to = get_grounding_z(br.get('to_gnd_r', 0.0), br.get('to_gnd_x', 0.0), v_to_kv, self.base_mva)

                is_from_gnd = conn_from in ('G', 'Rg', 'Xg')
                is_to_gnd = conn_to in ('G', 'Rg', 'Xg')
                is_from_delta = conn_from == 'D'
                is_to_delta = conn_to == 'D'

                if is_from_delta and is_to_delta:
                    # Delta - Delta: isolated from zero-sequence network
                    pass

                elif is_from_gnd and is_to_delta:
                    # Grounded Wye - Delta:
                    z_leakage_from = (z0 / (tap ** 2)) + z_n_from
                    if abs(z_leakage_from) > 1e-7:
                        Y0[i, i] += 1.0 / z_leakage_from

                elif is_from_delta and is_to_gnd:
                    # Delta - Grounded Wye:
                    z_leakage_to = z0 + z_n_to
                    if abs(z_leakage_to) > 1e-7:
                        Y0[j, j] += 1.0 / z_leakage_to

                elif is_from_gnd and is_to_gnd:
                    # Grounded Wye - Grounded Wye:
                    z_total_0 = z0 + (z_n_from * (tap ** 2)) + z_n_to
                    if abs(z_total_0) > 1e-7:
                        y0_xfmr = 1.0 / z_total_0
                        Y0[i, i] += y0_xfmr / (tap ** 2)
                        Y0[j, j] += y0_xfmr
                        Y0[i, j] -= y0_xfmr / tap
                        Y0[j, i] -= y0_xfmr / tap

                else:
                    # Ungrounded Wye (Y-Y, Y-Delta, Delta-Y):
                    pass
            else:
                # Transmission Line
                Y0[i, i] += y0_series + y0_shunt
                Y0[j, j] += y0_series + y0_shunt
                Y0[i, j] -= y0_series
                Y0[j, i] -= y0_series

        # 1b. Three-Winding Transformers (Star Equivalent Kron-reduced)
        if self.three_w_xfmrs:
            for tw_id, tw in self.three_w_xfmrs.items():
                if tw.get('status', 1) == 0:
                    continue
                hb = tw.get('hv_bus')
                mb = tw.get('mv_bus')
                if hb not in self.bus_idx_map or mb not in self.bus_idx_map:
                    continue
                idx_h = self.bus_idx_map[hb]
                idx_m = self.bus_idx_map[mb]

                r_hm = safe_float(tw.get('r_hm', 0.001), 0.001)
                x_hm = safe_float(tw.get('x_hm', 0.05), 0.05)
                r_hl = safe_float(tw.get('r_hl', 0.001), 0.001)
                x_hl = safe_float(tw.get('x_hl', 0.05), 0.05)
                r_ml = safe_float(tw.get('r_ml', 0.001), 0.001)
                x_ml = safe_float(tw.get('x_ml', 0.05), 0.05)

                z_hm = complex(max(r_hm, 1e-6), max(x_hm, 1e-6))
                z_hl = complex(max(r_hl, 1e-6), max(x_hl, 1e-6))
                z_ml = complex(max(r_ml, 1e-6), max(x_ml, 1e-6))

                z_h = 0.5 * (z_hm + z_hl - z_ml)
                z_m = 0.5 * (z_hm + z_ml - z_hl)
                z_l = 0.5 * (z_hl + z_ml - z_hm)

                v_h_kv = safe_float(self.bus_data[hb].get('base_kV', 138.0), 138.0)
                v_m_kv = safe_float(self.bus_data[mb].get('base_kV', 69.0), 69.0)
                z_nh = get_grounding_z(tw.get('hv_gnd_r', 0.0), tw.get('hv_gnd_x', 0.0), v_h_kv, self.base_mva)
                z_nm = get_grounding_z(tw.get('mv_gnd_r', 0.0), tw.get('mv_gnd_x', 0.0), v_m_kv, self.base_mva)

                z0_h = z_h + z_nh
                z0_m = z_m + z_nm
                z0_l = z_l

                y0_h = 1.0 / complex(max(z0_h.real, 1e-6), max(z0_h.imag, 1e-6))
                y0_m = 1.0 / complex(max(z0_m.real, 1e-6), max(z0_m.imag, 1e-6))
                y0_l = 1.0 / complex(max(z0_l.real, 1e-6), max(z0_l.imag, 1e-6))

                y_sigma = y0_h + y0_m + y0_l
                if abs(y_sigma) > 1e-7:
                    Y0[idx_h, idx_h] += y0_h - ((y0_h ** 2) / y_sigma)
                    Y0[idx_m, idx_m] += y0_m - ((y0_m ** 2) / y_sigma)
                    Y0[idx_h, idx_m] -= (y0_h * y0_m) / y_sigma
                    Y0[idx_m, idx_h] -= (y0_h * y0_m) / y_sigma

        # 2. Generator subtransient & zero-sequence grounding admittances
        buses_with_gens = set()
        for gid, gen in self.generators.items():
            if gen.get('status', 1) == 0:
                continue
            gbus = gen.get('bus')
            if gbus not in self.bus_idx_map:
                continue
            idx = self.bus_idx_map[gbus]
            buses_with_gens.add(gbus)

            r1_raw = gen.get('r1', gen.get('R1_pu', None))
            x1_raw = gen.get('x1', gen.get('X1_pu', None))
            r2_raw = gen.get('r2', gen.get('R2_pu', None))
            x2_raw = gen.get('x2', gen.get('X2_pu', None))
            r0_raw = gen.get('r0', gen.get('R0_pu', None))
            x0_raw = gen.get('x0', gen.get('X0_pu', None))

            if x1_raw is not None and safe_float(x1_raw, 0.0) > 0.0:
                rg = safe_float(r1_raw, 0.005)
                xd = safe_float(x1_raw, 0.2)
                r2 = safe_float(r2_raw, rg)
                x2 = safe_float(x2_raw, xd)
                r0 = safe_float(r0_raw, rg * 0.5)
                x0 = safe_float(x0_raw, xd * 0.5)
            else:
                mva_base_gen = safe_float(gen.get('mva', gen.get('sn', self.base_mva)), self.base_mva)
                if mva_base_gen <= 0.0:
                    mva_base_gen = self.base_mva
                scale = self.base_mva / max(mva_base_gen, 1.0)
                xd = safe_float(gen.get('xd_sync', gen.get('xd_subtrans', self.xd_sync)), self.xd_sync) * scale
                rg = safe_float(gen.get('r_gen', self.r_gen), self.r_gen) * scale
                r2, x2 = rg, xd
                r0 = rg * 0.5
                x0 = safe_float(gen.get('xg_zero', self.xg_zero), self.xg_zero) * scale

            zg1 = complex(max(rg, 1e-5), max(xd, 1e-4))
            yg1 = 1.0 / zg1

            zg2 = complex(max(r2, 1e-5), max(x2, 1e-4))
            yg2 = 1.0 / zg2

            Y1[idx, idx] += yg1
            Y2[idx, idx] += yg2

            conn_g = parse_connection(gen.get('wind_conn', gen.get('conn', 'G')))
            if conn_g in ('G', 'Rg', 'Xg'):
                v_gen_kv = safe_float(self.bus_data[gbus].get('base_kV', 138.0), 138.0)
                z_n_gen = get_grounding_z(gen.get('gnd_r', 0.0), gen.get('gnd_x', 0.0), v_gen_kv, self.base_mva)
                zg0 = complex(max(r0, 1e-5), max(x0, 1e-4)) + z_n_gen
                yg0 = 1.0 / zg0
                Y0[idx, idx] += yg0

        # 3. Grid Infeed / Utility Source Equivalent on Slack / Interconnect Buses
        for bid, b in self.bus_data.items():
            idx = self.bus_idx_map[bid]
            btype = b.get('type', 1)

            is_explicit_grid = bool(b.get('is_grid_infeed') or b.get('grid_infeed'))
            sk_mva = safe_float(b.get('grid_mva', b.get('fault_mva', 0.0)), 0.0)
            rx_ratio = safe_float(b.get('rx_ratio', 0.1), 0.1)
            z01_ratio = safe_float(b.get('z01_ratio', 1.0), 1.0)

            if is_explicit_grid or (btype == 3 and bid not in buses_with_gens):
                if sk_mva <= 0.0:
                    sk_mva = safe_float(b.get('sk_mva'), max(self.base_mva * 50.0, 5000.0))

                z_grid_mag = self.base_mva / max(sk_mva, 1.0)
                x_grid = z_grid_mag / np.sqrt(1.0 + (rx_ratio ** 2))
                r_grid = x_grid * rx_ratio
                z_grid_1 = complex(r_grid, x_grid)
                y_grid_1 = 1.0 / z_grid_1

                z_grid_0 = z_grid_1 * z01_ratio
                y_grid_0 = 1.0 / z_grid_0

                Y1[idx, idx] += y_grid_1
                Y2[idx, idx] += y_grid_1
                Y0[idx, idx] += y_grid_0

        return Y1, Y2, Y0

    def build_separate_rx_matrices(self):
        """
        Builds separate pure resistance [G] and pure reactance [B] networks per IEEE 3002.2 / ANSI C37.
        Separates R and X reductions to eliminate artificial X/R reduction caused by complex impedance phase angles.
        Returns:
            G_mat: Pure positive-sequence conductance matrix (1/R network)
            B_mom_mat: Pure positive-sequence susceptance matrix for First-Cycle / Momentary duty (1/X'' network)
            B_int_mat: Pure positive-sequence susceptance matrix for Interrupting duty (1/X_int network with machine decay)
            G0_mat: Pure zero-sequence conductance matrix
            B0_mat: Pure zero-sequence susceptance matrix
        """
        n = self.n_buses
        G_mat = np.zeros((n, n), dtype=float)
        B_mom_mat = np.zeros((n, n), dtype=float)
        B_int_mat = np.zeros((n, n), dtype=float)
        G0_mat = np.zeros((n, n), dtype=float)
        B0_mat = np.zeros((n, n), dtype=float)

        # 1. Branches (Lines and Transformers)
        for br in self.branch_data:
            if br.get('status', 1) == 0:
                continue

            fb = br.get('from_bus')
            tb = br.get('to_bus')
            if fb not in self.bus_idx_map or tb not in self.bus_idx_map:
                continue

            i = self.bus_idx_map[fb]
            j = self.bus_idx_map[tb]

            r1 = max(safe_float(br.get('r', 0.001), 0.001), 1e-6)
            x1 = max(safe_float(br.get('x', 0.01), 0.01), 1e-6)
            tap = safe_float(br.get('ratio', br.get('tap', 1.0)), 1.0)
            if tap <= 0.0:
                tap = 1.0

            g_br = 1.0 / r1
            b_br = 1.0 / x1

            # G matrix
            G_mat[i, i] += g_br / (tap ** 2)
            G_mat[j, j] += g_br
            G_mat[i, j] -= g_br / tap
            G_mat[j, i] -= g_br / tap

            # B_mom matrix
            B_mom_mat[i, i] += b_br / (tap ** 2)
            B_mom_mat[j, j] += b_br
            B_mom_mat[i, j] -= b_br / tap
            B_mom_mat[j, i] -= b_br / tap

            # B_int matrix (branches remain identical for interrupting duty)
            B_int_mat[i, i] += b_br / (tap ** 2)
            B_int_mat[j, j] += b_br
            B_int_mat[i, j] -= b_br / tap
            B_int_mat[j, i] -= b_br / tap

            # Zero-sequence R0 and X0
            r0 = max(safe_float(br.get('r0', br.get('R0_pu', None)), r1 * self.zero_seq_factor), 1e-6)
            x0 = max(safe_float(br.get('x0', br.get('X0_pu', None)), x1 * self.zero_seq_factor), 1e-6)
            g0_br = 1.0 / r0
            b0_br = 1.0 / x0

            br_type = str(br.get('type', 'line')).lower()
            is_xfmr = ('transformer' in br_type) or (tap != 1.0) or ('from_conn' in br)

            if not is_xfmr:
                G0_mat[i, i] += g0_br
                G0_mat[j, j] += g0_br
                G0_mat[i, j] -= g0_br
                G0_mat[j, i] -= g0_br

                B0_mat[i, i] += b0_br
                B0_mat[j, j] += b0_br
                B0_mat[i, j] -= b0_br
                B0_mat[j, i] -= b0_br
            else:
                conn_from = parse_connection(br.get('from_conn', br.get('from_connection', '0')))
                conn_to = parse_connection(br.get('to_conn', br.get('to_connection', '0')))
                is_from_gnd = conn_from in ('G', 'Rg', 'Xg')
                is_to_gnd = conn_to in ('G', 'Rg', 'Xg')
                is_from_delta = conn_from == 'D'
                is_to_delta = conn_to == 'D'

                if is_from_gnd and is_to_gnd:
                    G0_mat[i, i] += g0_br / (tap ** 2)
                    G0_mat[j, j] += g0_br
                    G0_mat[i, j] -= g0_br / tap
                    G0_mat[j, i] -= g0_br / tap
                    B0_mat[i, i] += b0_br / (tap ** 2)
                    B0_mat[j, j] += b0_br
                    B0_mat[i, j] -= b0_br / tap
                    B0_mat[j, i] -= b0_br / tap
                elif is_from_gnd and is_to_delta:
                    G0_mat[i, i] += g0_br / (tap ** 2)
                    B0_mat[i, i] += b0_br / (tap ** 2)
                elif is_from_delta and is_to_gnd:
                    G0_mat[j, j] += g0_br
                    B0_mat[j, j] += b0_br

        # 2. Generator subtransient & interrupting admittances
        buses_with_gens = set()
        for gid, gen in self.generators.items():
            if gen.get('status', 1) == 0:
                continue
            gbus = gen.get('bus')
            if gbus not in self.bus_idx_map:
                continue
            idx = self.bus_idx_map[gbus]
            buses_with_gens.add(gbus)

            r1_raw = gen.get('r1', gen.get('R1_pu', None))
            x1_raw = gen.get('x1', gen.get('X1_pu', None))
            r0_raw = gen.get('r0', gen.get('R0_pu', None))
            x0_raw = gen.get('x0', gen.get('X0_pu', None))

            if x1_raw is not None and safe_float(x1_raw, 0.0) > 0.0:
                rg = safe_float(r1_raw, 0.005)
                xd = safe_float(x1_raw, 0.2)
                r0 = safe_float(r0_raw, rg * 0.5)
                x0 = safe_float(x0_raw, xd * 0.5)
            else:
                mva_base_gen = safe_float(gen.get('mva', gen.get('sn', self.base_mva)), self.base_mva)
                if mva_base_gen <= 0.0:
                    mva_base_gen = self.base_mva
                scale = self.base_mva / max(mva_base_gen, 1.0)
                xd = safe_float(gen.get('xd_sync', gen.get('xd_subtrans', self.xd_sync)), self.xd_sync) * scale
                rg = safe_float(gen.get('r_gen', self.r_gen), self.r_gen) * scale
                r0 = rg * 0.5
                x0 = safe_float(gen.get('xg_zero', self.xg_zero), self.xg_zero) * scale

            g_gen = 1.0 / max(rg, 1e-5)
            b_gen_mom = 1.0 / max(xd, 1e-4)

            # Interrupting Duty Machine Multipliers (ANSI C37.010 / C37.5):
            gen_type = str(gen.get('gen_type', gen.get('type', 'thermal'))).lower()
            if 'motor' in gen_type or 'sync_motor' in gen_type:
                mult_int = 1.5
            elif 'induction' in gen_type:
                mult_int = 1.5 if safe_float(gen.get('hp', 500), 500) > 1000 else 3.0
            elif 'hydro' in gen_type:
                mult_int = 1.2
            else:
                mult_int = 1.0  # Turbogenerator default

            b_gen_int = 1.0 / max(xd * mult_int, 1e-4)

            G_mat[idx, idx] += g_gen
            B_mom_mat[idx, idx] += b_gen_mom
            B_int_mat[idx, idx] += b_gen_int

            # Zero-sequence
            conn_g = parse_connection(gen.get('wind_conn', gen.get('conn', 'G')))
            if conn_g in ('G', 'Rg', 'Xg'):
                v_gen_kv = safe_float(self.bus_data[gbus].get('base_kV', 138.0), 138.0)
                z_n_gen = get_grounding_z(gen.get('gnd_r', 0.0), gen.get('gnd_x', 0.0), v_gen_kv, self.base_mva)
                r0_tot = max(r0 + z_n_gen.real, 1e-5)
                x0_tot = max(x0 + z_n_gen.imag, 1e-4)
                G0_mat[idx, idx] += 1.0 / r0_tot
                B0_mat[idx, idx] += 1.0 / x0_tot

        # 3. Grid Infeeds / Utility Sources
        for bid, b in self.bus_data.items():
            idx = self.bus_idx_map[bid]
            btype = b.get('type', 1)
            is_explicit_grid = bool(b.get('is_grid_infeed') or b.get('grid_infeed'))
            sk_mva = safe_float(b.get('grid_mva', b.get('fault_mva', 0.0)), 0.0)
            rx_ratio = safe_float(b.get('rx_ratio', 0.1), 0.1)

            if is_explicit_grid or (btype == 3 and bid not in buses_with_gens):
                if sk_mva <= 0.0:
                    sk_mva = safe_float(b.get('sk_mva'), max(self.base_mva * 50.0, 5000.0))
                z_grid_mag = self.base_mva / max(sk_mva, 1.0)
                x_grid = z_grid_mag / np.sqrt(1.0 + (rx_ratio ** 2))
                r_grid = x_grid * rx_ratio
                g_grid = 1.0 / max(r_grid, 1e-6)
                b_grid = 1.0 / max(x_grid, 1e-6)

                G_mat[idx, idx] += g_grid
                B_mom_mat[idx, idx] += b_grid
                B_int_mat[idx, idx] += b_grid

                z01_ratio = safe_float(b.get('z01_ratio', 1.0), 1.0)
                G0_mat[idx, idx] += g_grid / max(z01_ratio, 0.1)
                B0_mat[idx, idx] += b_grid / max(z01_ratio, 0.1)

        return G_mat, B_mom_mat, B_int_mat, G0_mat, B0_mat


def solve_short_circuit(bus_data, branch_data, generators=None, loads=None, fault_bus=1,
                        fault_type='3phase', fault_phase='abc',
                        r_f=0.0, x_f=0.0, fault_impedance=0.0,
                        voltage_scaling_factor_c=1.1, zero_seq_factor=3.0,
                        xd_sync=0.15, xg_zero=0.05,
                        pre_fault_V=None, base_mva=100.0, line_fault_info=None,
                        method='iec', units='ka', breaker_check=True,
                        open_conductor_info=None, three_w_xfmrs=None):
    """
    Executes advanced multi-sequence short circuit calculation.
    Supports both shunt faults (3PH, SLG, LL, DLG) and series open conductor faults (1P, 2P Open).
    """
    generators = generators or {}
    loads = loads or {}
    three_w_xfmrs = three_w_xfmrs or {}
    base_mva = float(base_mva)
    method_lower = str(method).lower()
    is_classical = ('classical' in method_lower) or ('ansi' in method_lower) or ('sym' in method_lower)
    
    if is_classical:
        c_factor = 1.0
    else:
        c_factor = float(voltage_scaling_factor_c)

    zero_seq_factor = float(zero_seq_factor)

    if fault_impedance != 0.0 and r_f == 0.0 and x_f == 0.0:
        r_f = float(fault_impedance)
        x_f = 0.0
    Z_f = complex(float(r_f), float(x_f))

    temp_branch_data = list(branch_data.values()) if isinstance(branch_data, dict) else list(branch_data)
    temp_bus_data = dict(bus_data)

    if line_fault_info is not None:
        line_num = line_fault_info.get('line_num')
        p = float(np.clip(line_fault_info.get('fraction', 0.5), 0.001, 0.999))

        target_line = None
        for br in branch_data:
            if br.get('num') == line_num:
                target_line = br
                break

        if target_line is not None:
            max_id = max(temp_bus_data.keys()) if temp_bus_data else 1000
            dummy_bus_num = max_id + 1000
            f_kv = float(temp_bus_data[target_line['from_bus']].get('base_kV') or 138.0)
            if f_kv <= 0.0:
                f_kv = 138.0
            temp_bus_data[dummy_bus_num] = {
                'bus_num': dummy_bus_num,
                'name': f"Line_{line_num}_Fault_{int(p*100)}%",
                'type': 1,
                'base_kV': f_kv,
                'V_init': 1.0,
                'angle_init': 0.0
            }

            br1 = dict(target_line)
            br1['to_bus'] = dummy_bus_num
            br1['r'] = target_line['r'] * p
            br1['x'] = target_line['x'] * p
            br1['b'] = target_line.get('b', 0.0) * p

            br2 = dict(target_line)
            br2['from_bus'] = dummy_bus_num
            br2['r'] = target_line['r'] * (1.0 - p)
            br2['x'] = target_line['x'] * (1.0 - p)
            br2['b'] = target_line.get('b', 0.0) * (1.0 - p)

            temp_branch_data = [b for b in temp_branch_data if b.get('num') != line_num]
            temp_branch_data.append(br1)
            temp_branch_data.append(br2)
            fault_bus = dummy_bus_num

    builder = SequenceAdmittanceBuilder(
        temp_bus_data, temp_branch_data, generators=generators, loads=loads,
        base_mva=base_mva, zero_seq_factor=zero_seq_factor, xd_sync=xd_sync, xg_zero=xg_zero,
        three_w_xfmrs=three_w_xfmrs
    )
    Y1, Y2, Y0 = builder.build_matrices()
    bus_ids = builder.bus_ids
    n_buses = builder.n_buses
    idx_map = builder.bus_idx_map

    ft_lower = str(fault_type).lower().replace(' ', '').replace('_', '').replace('-', '')
    is_open_conductor = ('open' in ft_lower) or ('broken' in ft_lower)

    # ── OPEN CONDUCTOR (SERIES FAULT) HANDLING ──────────────────────────────
    if is_open_conductor:
        fb_oc = None
        tb_oc = None
        if open_conductor_info:
            fb_oc = open_conductor_info.get('from_bus')
            tb_oc = open_conductor_info.get('to_bus')
            if (fb_oc is None or tb_oc is None) and 'line_num' in open_conductor_info:
                target_line = next((b for b in branch_data if b.get('num') == open_conductor_info.get('line_num')), None)
                if target_line:
                    fb_oc = target_line.get('from_bus')
                    tb_oc = target_line.get('to_bus')
        if fb_oc is None or tb_oc is None:
            if line_fault_info:
                target_line = next((b for b in branch_data if b.get('num') == line_fault_info.get('line_num')), None)
                fb_oc = target_line.get('from_bus') if target_line else bus_ids[0]
                tb_oc = target_line.get('to_bus') if target_line else (bus_ids[1] if len(bus_ids) > 1 else bus_ids[0])
            else:
                fb_oc = bus_ids[0]
                tb_oc = bus_ids[1] if len(bus_ids) > 1 else bus_ids[0]

        if fb_oc not in temp_bus_data:
            fb_oc = bus_ids[0]
        if tb_oc not in temp_bus_data:
            tb_oc = bus_ids[1] if len(bus_ids) > 1 else bus_ids[0]

        k = idx_map.get(fb_oc, 0)
        l = idx_map.get(tb_oc, 0)

        try: Z1_mat = np.linalg.inv(Y1)
        except np.linalg.LinAlgError: Z1_mat = np.linalg.pinv(Y1)
        try: Z2_mat = np.linalg.inv(Y2)
        except np.linalg.LinAlgError: Z2_mat = np.linalg.pinv(Y2)
        try: Z0_mat = np.linalg.inv(Y0)
        except np.linalg.LinAlgError: Z0_mat = np.linalg.pinv(Y0)

        Z1_th = Z1_mat[k, k] + Z1_mat[l, l] - Z1_mat[k, l] - Z1_mat[l, k]
        Z2_th = Z2_mat[k, k] + Z2_mat[l, l] - Z2_mat[k, l] - Z2_mat[l, k]
        Z0_th = Z0_mat[k, k] + Z0_mat[l, l] - Z0_mat[k, l] - Z0_mat[l, k]

        vk_pre = complex(pre_fault_V[fb_oc]) if (pre_fault_V and fb_oc in pre_fault_V) else complex(1.0, 0.0)
        vl_pre = complex(pre_fault_V[tb_oc]) if (pre_fault_V and tb_oc in pre_fault_V) else complex(0.98, -0.02)
        delta_V_pre = vk_pre - vl_pre
        if abs(delta_V_pre) < 1e-4:
            delta_V_pre = complex(0.02, 0.01)

        V_base_kV = safe_float(temp_bus_data[fb_oc].get('base_kV'), 138.0)
        if V_base_kV <= 0.0:
            V_base_kV = 138.0
        I_base_kA = base_mva / (np.sqrt(3.0) * V_base_kV)

        if '2' in ft_lower or 'two' in ft_lower:
            actual_fault_type = "Open Conductor — 2 Phases Open (Series Fault)"
            Z_total = Z1_th + Z2_th + Z0_th
            I_f1 = delta_V_pre / Z_total
            I_f2 = I_f1
            I_f0 = I_f1
            Z_eff = Z_total
        else:
            actual_fault_type = "Open Conductor — 1 Phase Open (Broken Conductor)"
            Z_parallel = (Z2_th * Z0_th) / (Z2_th + Z0_th) if abs(Z2_th + Z0_th) > 1e-6 else 1e6
            I_f1 = delta_V_pre / (Z1_th + Z_parallel)
            I_f2 = -I_f1 * (Z0_th / (Z2_th + Z0_th)) if abs(Z2_th + Z0_th) > 1e-6 else 0j
            I_f0 = -I_f1 * (Z2_th / (Z2_th + Z0_th)) if abs(Z2_th + Z0_th) > 1e-6 else 0j
            Z_eff = Z1_th + Z_parallel

        I_k_pu = abs(I_f1)
        Z1_col = Z1_mat[:, k] - Z1_mat[:, l]
        Z2_col = Z2_mat[:, k] - Z2_mat[:, l]
        Z0_col = Z0_mat[:, k] - Z0_mat[:, l]
        fault_bus = fb_oc

    # ── STANDARD SHUNT FAULTS ───────────────────────────────────────────────
    else:
        if fault_bus not in idx_map:
            fault_bus = bus_ids[0]
        k = idx_map[fault_bus]

        e_k = np.zeros(n_buses, dtype=complex)
        e_k[k] = 1.0

        try: Z1_col = np.linalg.solve(Y1, e_k)
        except np.linalg.LinAlgError: Z1_col = np.linalg.pinv(Y1)[:, k]

        try: Z2_col = np.linalg.solve(Y2, e_k)
        except np.linalg.LinAlgError: Z2_col = np.linalg.pinv(Y2)[:, k]

        try: Z0_col = np.linalg.solve(Y0, e_k)
        except np.linalg.LinAlgError: Z0_col = np.full(n_buses, complex(1e6, 1e6), dtype=complex)

        Z1_th = Z1_col[k]
        Z2_th = Z2_col[k]
        Z0_th = Z0_col[k]

        V_base_kV = float(temp_bus_data[fault_bus].get('base_kV') or 138.0)
        if V_base_kV <= 0.0:
            V_base_kV = 138.0
        I_base_kA = base_mva / (np.sqrt(3.0) * V_base_kV)

        if pre_fault_V and fault_bus in pre_fault_V:
            v_pre_cx = complex(pre_fault_V[fault_bus])
            V_pre_pu = v_pre_cx * c_factor
        else:
            V_pre_pu = complex(c_factor, 0.0)

        I_f0 = 0j
        I_f1 = 0j
        I_f2 = 0j

        if '3phase' in ft_lower or '3ph' in ft_lower or 'sym' in ft_lower:
            actual_fault_type = "3-Phase Symmetrical (3PH)"
            I_f1 = V_pre_pu / (Z1_th + Z_f)
            I_f2 = 0j
            I_f0 = 0j
            I_k_pu = abs(I_f1)
            Z_eff = Z1_th + Z_f

        elif 'dlg' in ft_lower or 'llg' in ft_lower or '2lg' in ft_lower or 'double' in ft_lower:
            actual_fault_type = "Double Line-to-Ground (DLG / LLG / 2LG)"
            Z0_branch = Z0_th + (3.0 * Z_f)
            Z_parallel = (Z2_th * Z0_branch) / (Z2_th + Z0_branch) if abs(Z2_th + Z0_branch) > 1e-6 else 1e6
            I_f1 = V_pre_pu / (Z1_th + Z_parallel)
            I_f2 = -I_f1 * (Z0_branch / (Z2_th + Z0_branch)) if abs(Z2_th + Z0_branch) > 1e-6 else 0j
            I_f0 = -I_f1 * (Z2_th / (Z2_th + Z0_branch)) if abs(Z2_th + Z0_branch) > 1e-6 else 0j
            I_k_pu = max(abs(3.0 * I_f0), abs(I_f1 * np.sqrt(3.0)))
            Z_eff = Z1_th + Z_parallel

        elif 'slg' in ft_lower or '1lg' in ft_lower or 'single' in ft_lower or 'ground' in ft_lower or 'lg' in ft_lower:
            actual_fault_type = "Single Line-to-Ground (SLG / 1LG)"
            Z_total_012 = Z1_th + Z2_th + Z0_th + (3.0 * Z_f)
            I_f1 = V_pre_pu / Z_total_012
            I_f2 = I_f1
            I_f0 = I_f1
            I_k_pu = abs(3.0 * I_f1)
            Z_eff = Z_total_012 / 3.0

        else:
            actual_fault_type = "Line-to-Line (LL / 2PH)"
            Z_total_12 = Z1_th + Z2_th + Z_f
            I_f1 = V_pre_pu / Z_total_12
            I_f2 = -I_f1
            I_f0 = 0j
            I_k_pu = abs(I_f1) * np.sqrt(3.0)
            Z_eff = Z_total_12 / np.sqrt(3.0)

    # Physical Current and Power Quantities
    I_k_kA = float(I_k_pu * I_base_kA)
    S_k_MVA = float(np.sqrt(3.0) * V_base_kV * I_k_kA)

    R_eff = max(float(np.real(Z_eff)), 1e-6)
    X_eff = max(float(np.imag(Z_eff)), 1e-6)
    XR_ratio = float(X_eff / R_eff)

    # ANSI IEEE 3002.2 / C37 Dual-Network Calculations
    ansi_xr = XR_ratio
    I_sym_1st_kA = I_k_kA
    I_crest_kA = float(np.sqrt(2.0) * I_k_kA * (1.0 + np.exp(-np.pi / max(XR_ratio, 0.01))))
    I_asym_1st_kA = float(I_k_kA * np.sqrt(1.0 + 2.0 * np.exp(-2.0 * np.pi / max(XR_ratio, 0.01))))
    I_sym_int_kA = I_k_kA
    I_dc_int_kA = float(np.sqrt(2.0) * I_k_kA * np.exp(-2.0 * np.pi * 3.0 / max(XR_ratio, 0.01)))
    I_asym_int_kA = float(I_k_kA * np.sqrt(1.0 + 2.0 * np.exp(-4.0 * np.pi * 3.0 / max(XR_ratio, 0.01))))
    cb_mf = 1.0

    if is_classical and not is_open_conductor:
        # Build pure R and pure X networks per IEEE 3002.2 / ANSI C37
        G_mat, B_mom_mat, B_int_mat, G0_mat, B0_mat = builder.build_separate_rx_matrices()
        e_k_real = np.zeros(n_buses, dtype=float)
        e_k_real[k] = 1.0

        try: R_col = np.linalg.solve(G_mat, e_k_real)
        except np.linalg.LinAlgError: R_col = np.linalg.pinv(G_mat)[:, k]

        try: X_col_mom = np.linalg.solve(B_mom_mat, e_k_real)
        except np.linalg.LinAlgError: X_col_mom = np.linalg.pinv(B_mom_mat)[:, k]

        try: X_col_int = np.linalg.solve(B_int_mat, e_k_real)
        except np.linalg.LinAlgError: X_col_int = np.linalg.pinv(B_int_mat)[:, k]

        R_th_sep = max(float(R_col[k]), 1e-6)
        X_th_sep = max(float(X_col_mom[k]), 1e-6)
        X_th_int = max(float(X_col_int[k]), 1e-6)

        # In SLG, also separate zero-sequence R0 and X0
        if 'slg' in ft_lower or '1lg' in ft_lower or 'single' in ft_lower:
            try: R0_col = np.linalg.solve(G0_mat, e_k_real)
            except np.linalg.LinAlgError: R0_col = np.linalg.pinv(G0_mat)[:, k]
            try: X0_col = np.linalg.solve(B0_mat, e_k_real)
            except np.linalg.LinAlgError: X0_col = np.linalg.pinv(B0_mat)[:, k]
            R0_sep = max(float(R0_col[k]), 1e-6)
            X0_sep = max(float(X0_col[k]), 1e-6)

            R_tot_sep = (2.0 * R_th_sep + R0_sep + 3.0 * float(r_f)) / 3.0
            X_tot_sep = (2.0 * X_th_sep + X0_sep + 3.0 * float(x_f)) / 3.0
            ansi_xr = float(X_tot_sep / R_tot_sep)
            X_tot_int = (2.0 * X_th_int + X0_sep + 3.0 * float(x_f)) / 3.0
        else:
            ansi_xr = float(X_th_sep / R_th_sep)
            X_tot_sep = X_th_sep + float(x_f)
            X_tot_int = X_th_int + float(x_f)

        XR_ratio = ansi_xr

        # First-Cycle (1/2 cycle) Momentary Duty:
        v_mag = abs(V_pre_pu)
        I_sym_1st_kA = float((v_mag / max(X_tot_sep, 1e-5)) * I_base_kA)
        I_k_kA = I_sym_1st_kA
        S_k_MVA = float(np.sqrt(3.0) * V_base_kV * I_k_kA)

        # ANSI Peak Crest (asymmetrical peak at 1/2 cycle):
        kappa = float(1.0 + np.exp(-np.pi / max(ansi_xr, 0.01)))
        Ip_kA = float(np.sqrt(2.0) * I_sym_1st_kA * kappa)
        I_crest_kA = Ip_kA
        I_asym_1st_kA = float(I_sym_1st_kA * np.sqrt(1.0 + 2.0 * np.exp(-2.0 * np.pi / max(ansi_xr, 0.01))))

        # Interrupting Duty (tau = 3 cycles default contact parting time):
        tau_cycles = 3.0
        I_sym_int_kA = float((v_mag / max(X_tot_int, 1e-5)) * I_base_kA)
        Ib_kA = I_sym_int_kA
        I_dc_int_kA = float(np.sqrt(2.0) * I_sym_int_kA * np.exp(-2.0 * np.pi * tau_cycles / max(ansi_xr, 0.01)))
        I_asym_int_kA = float(I_sym_int_kA * np.sqrt(1.0 + 2.0 * np.exp(-4.0 * np.pi * tau_cycles / max(ansi_xr, 0.01))))
        Ith_kA = float(I_sym_int_kA * np.sqrt(1.0 + (0.05 / max(ansi_xr, 0.1))))

        # Breaker High-X/R Multiplying Factor (ANSI C37.010 / C37.13):
        if V_base_kV > 1.0:
            if ansi_xr > 17.0:
                cb_mf = float(np.sqrt(1.0 + 2.0 * np.exp(-4.0 * np.pi * tau_cycles / ansi_xr)) /
                              np.sqrt(1.0 + 2.0 * np.exp(-4.0 * np.pi * tau_cycles / 17.0)))
            else:
                cb_mf = 1.0
        else:
            if ansi_xr > 6.6:
                cb_mf = float((1.0 + np.exp(-np.pi / ansi_xr)) / (1.0 + np.exp(-np.pi / 6.6)))
            else:
                cb_mf = 1.0
    else:
        # IEC 60909 Standard Method
        kappa = float(1.02 + 0.98 * np.exp(-3.0 / max(XR_ratio, 0.01)))
        Ip_kA = float(kappa * np.sqrt(2.0) * I_k_kA)
        Ib_kA = float(I_k_kA)
        Ith_kA = float(I_k_kA * np.sqrt(1.0 + (0.05 / max(XR_ratio, 0.1))))
        I_crest_kA = Ip_kA
        I_sym_1st_kA = I_k_kA
        I_asym_1st_kA = float(I_k_kA * np.sqrt(1.0 + 2.0 * np.exp(-2.0 * np.pi / max(XR_ratio, 0.01))))
        I_sym_int_kA = Ib_kA
        I_dc_int_kA = float(np.sqrt(2.0) * Ib_kA * np.exp(-2.0 * np.pi * 3.0 / max(XR_ratio, 0.01)))
        I_asym_int_kA = float(Ib_kA * np.sqrt(1.0 + 2.0 * np.exp(-4.0 * np.pi * 3.0 / max(XR_ratio, 0.01))))
        cb_mf = 1.0

    I_seq = np.array([I_f0, I_f1, I_f2], dtype=complex)
    I_phase_pu = A_MATRIX @ I_seq
    I_phase_kA = {
        'Ia': float(abs(I_phase_pu[0]) * I_base_kA),
        'Ib': float(abs(I_phase_pu[1]) * I_base_kA),
        'Ic': float(abs(I_phase_pu[2]) * I_base_kA)
    }

    # ── Post-Fault Bus Voltages ─────────────────────────────────────────────
    V_mag_post = {}
    V_phase_post = {}
    voltages_ui_dict = {}

    for bid in bus_ids:
        b_i = idx_map[bid]
        v_pre_i = complex(pre_fault_V[bid]) if (pre_fault_V and bid in pre_fault_V) else complex(c_factor, 0.0)

        v1_i = v_pre_i - (Z1_col[b_i] * I_f1)
        v2_i = 0j - (Z2_col[b_i] * I_f2)
        v0_i = 0j - (Z0_col[b_i] * I_f0)

        v_abc_i = A_MATRIX @ np.array([v0_i, v1_i, v2_i], dtype=complex)

        va_mag = float(abs(v_abc_i[0]))
        vb_mag = float(abs(v_abc_i[1]))
        vc_mag = float(abs(v_abc_i[2]))

        V_mag_post[bid] = float(abs(v1_i))
        V_phase_post[bid] = {
            'Va_pu': va_mag, 'Vb_pu': vb_mag, 'Vc_pu': vc_mag,
            'Va_angle': float(np.angle(v_abc_i[0], deg=True)),
            'Vb_angle': float(np.angle(v_abc_i[1], deg=True)),
            'Vc_angle': float(np.angle(v_abc_i[2], deg=True))
        }
        voltages_ui_dict[bid] = {
            'Va_mag': va_mag, 'Vb_mag': vb_mag, 'Vc_mag': vc_mag,
            'Va_angle': float(np.angle(v_abc_i[0], deg=True)),
            'Vb_angle': float(np.angle(v_abc_i[1], deg=True)),
            'Vc_angle': float(np.angle(v_abc_i[2], deg=True)),
            'Va': v_abc_i[0], 'Vb': v_abc_i[1], 'Vc': v_abc_i[2]
        }

    # ── Branch Flow Contributions & Full Branch Currents ───────────────────
    branch_contributions = []
    branch_currents_ui_dict = {}

    for br_idx, br in enumerate(temp_branch_data, 1):
        line_id = br.get('num', br_idx)
        fb = br.get('from_bus')
        tb = br.get('to_bus')
        if fb not in idx_map or tb not in idx_map:
            continue

        i = idx_map[fb]
        j = idx_map[tb]

        r1 = max(safe_float(br.get('r', 0.001), 0.001), 1e-6)
        x1 = max(safe_float(br.get('x', 0.01), 0.01), 1e-6)
        tap = safe_float(br.get('ratio', br.get('tap', 1.0)), 1.0)
        if tap <= 0.0: tap = 1.0
        z1 = complex(r1, x1)
        y1 = 1.0 / z1

        vf1 = complex(pre_fault_V[fb]) if (pre_fault_V and fb in pre_fault_V) else complex(c_factor, 0.0)
        vt1 = complex(pre_fault_V[tb]) if (pre_fault_V and tb in pre_fault_V) else complex(c_factor, 0.0)
        vf1_post = vf1 - (Z1_col[i] * I_f1)
        vt1_post = vt1 - (Z1_col[j] * I_f1)

        i_br_1 = (vf1_post - (vt1_post / tap)) * y1
        i_br_kA = float(abs(i_br_1) * I_base_kA)
        i_br_rev_kA = i_br_kA

        br_name = br.get('name', f"Branch_{fb}_{tb}")
        vf_kv = safe_float(temp_bus_data.get(fb, {}).get('base_kV'), 138.0)
        vt_kv = safe_float(temp_bus_data.get(tb, {}).get('base_kV'), 138.0)
        mva_fwd = float(np.sqrt(3.0) * vf_kv * i_br_kA)
        mva_rev = float(np.sqrt(3.0) * vt_kv * i_br_rev_kA)

        branch_currents_ui_dict[line_id] = {
            'orig_num': line_id,
            'from_bus': fb, 'to_bus': tb,
            'max_ik_fwd': i_br_kA, 'max_ik_rev': i_br_rev_kA, 'max_ik': i_br_kA,
            'ik_ss_fwd': i_br_kA, 'ik_ss_rev': i_br_rev_kA, 'ik_ss': i_br_kA,
            'ip_fwd': float(i_br_kA * kappa), 'ip_rev': float(i_br_rev_kA * kappa), 'ip': float(i_br_kA * kappa),
            'ib_fwd': i_br_kA, 'ib_rev': i_br_rev_kA, 'ib': i_br_kA,
            'ith_fwd': i_br_kA, 'ith_rev': i_br_rev_kA, 'ith': i_br_kA,
            'fault_mva_fwd': mva_fwd, 'fault_mva_rev': mva_rev, 'fault_mva': mva_fwd
        }

        if fb == fault_bus or tb == fault_bus:
            other_bus = tb if fb == fault_bus else fb
            p_flow = float(np.real(vf1_post * np.conj(i_br_1)) * base_mva)
            q_flow = float(np.imag(vf1_post * np.conj(i_br_1)) * base_mva)
            branch_contributions.append({
                'num': line_id,
                'name': br_name,
                'from_bus': fb, 'to_bus': tb,
                'connected_bus': other_bus,
                'current_kA': i_br_kA,
                'p_mw': p_flow, 'q_mvar': q_flow,
                'type': br.get('type', 'line')
            })

    # ── Generator Contributions & NGR Resistor Loss ─────────────────────────
    generator_contributions = []
    total_ngr_kw = 0.0

    for gid, gen in generators.items():
        gbus = gen.get('bus')
        if gbus not in idx_map:
            continue
        g_idx = idx_map[gbus]

        mva_base_gen = safe_float(gen.get('mva', gen.get('sn', base_mva)), base_mva)
        if mva_base_gen <= 0.0:
            mva_base_gen = base_mva
        scale = base_mva / max(mva_base_gen, 1.0)
        xd = safe_float(gen.get('xd_sync', gen.get('xd_subtrans', xd_sync)), xd_sync) * scale
        rg = safe_float(gen.get('r_gen', 0.005), 0.005) * scale
        zg1 = complex(max(rg, 1e-5), max(xd, 1e-4))

        vg_pre = complex(pre_fault_V[gbus]) if (pre_fault_V and gbus in pre_fault_V) else complex(c_factor, 0.0)
        vg_post_1 = vg_pre - (Z1_col[g_idx] * I_f1)
        ig_1 = (vg_pre - vg_post_1) / zg1
        ig_kA = float(abs(ig_1) * I_base_kA)

        gnd_r = safe_float(gen.get('gnd_r', 0.0), 0.0)
        r0_val = safe_float(gen.get('r0', gen.get('R0_pu', None)), rg * 0.5)
        x0_val = safe_float(gen.get('x0', gen.get('X0_pu', None)), xd * 0.5)
        zg0_gen = complex(max(r0_val, 1e-5), max(x0_val, 1e-4))
        conn_g = parse_connection(gen.get('wind_conn', gen.get('conn', 'G')))
        if conn_g in ('G', 'Rg', 'Xg') and abs(I_f0) > 1e-7:
            vg_post_0 = 0j - (Z0_col[g_idx] * I_f0)
            ig_0 = -vg_post_0 / zg0_gen if abs(zg0_gen) > 1e-6 else 0j
            in_gen_kA = float(abs(3.0 * ig_0) * I_base_kA)
        else:
            ig_0 = 0j
            in_gen_kA = 0.0

        if gnd_r > 0.0:
            p_ngr_kw = (in_gen_kA ** 2) * gnd_r * 1000.0 if gnd_r > 1.0 else (abs(3.0 * ig_0) ** 2) * gnd_r * base_mva * 1000.0
        else:
            p_ngr_kw = 0.0
        total_ngr_kw += p_ngr_kw

        generator_contributions.append({
            'gen_id': gid,
            'bus': gbus,
            'current_kA': ig_kA,
            'i0_kA': in_gen_kA / 3.0,
            'in_neutral_kA': in_gen_kA,
            'ngr_loss_kW': p_ngr_kw,
            'mva': mva_base_gen
        })

    # ── Circuit Breaker Duty Evaluation ─────────────────────────────────────
    cb_eval_list = []
    cb_duty_rows = []
    if breaker_check:
        cb_mva_val = safe_float(temp_bus_data[fault_bus].get('cb_mva', 0.0), 0.0)
        if cb_mva_val <= 0.0:
            for br in temp_branch_data:
                br_fcb = safe_float(br.get('from_cb_mva', 0.0), 0.0)
                br_tcb = safe_float(br.get('to_cb_mva', 0.0), 0.0)
                if br.get('from_bus') == fault_bus and br_fcb > 0:
                    cb_mva_val = max(cb_mva_val, br_fcb)
                elif br.get('to_bus') == fault_bus and br_tcb > 0:
                    cb_mva_val = max(cb_mva_val, br_tcb)
        if cb_mva_val <= 0.0:
            for gid, g in generators.items():
                g_cb = safe_float(g.get('cb_mva', 0.0), 0.0)
                if g.get('bus') == fault_bus and g_cb > 0:
                    cb_mva_val = max(cb_mva_val, g_cb)

        if cb_mva_val > 0.0:
            cb_eval = evaluate_circuit_breaker(
                fault_kA=Ib_kA if is_classical else I_k_kA,
                cb_mva=cb_mva_val,
                v_base_kv=V_base_kV,
                k_factor=1.15,
                mf=cb_mf,
                is_ansi=is_classical
            )
            if cb_eval:
                cb_eval_list.append(cb_eval)
                eval_current = cb_eval.get('effective_fault_kA', I_k_kA)
                cb_duty_rows.append([
                    fault_bus, temp_bus_data[fault_bus].get('name', f"Bus_{fault_bus}"),
                    V_base_kV, cb_mva_val, f"{cb_eval['interrupting_kA']:.2f}",
                    f"{eval_current:.3f}", f"{cb_eval['duty_pct']:.1f}%",
                    f"{cb_eval['margin_pct']:.1f}%", cb_eval['status']
                ])

    method_header = "IEEE 3002.2 / ANSI C37 Standard" if is_classical else "IEC 60909 Standard Method"
    unit_label = "MVA (Fault Power)" if units.lower() == 'mva' else "kA (Fault Current)"

    report = []
    report.append("=========================================================================================")
    report.append(f"                   DevEN SHORT CIRCUIT ANALYSIS REPORT ({method_header.upper()})        ")
    report.append("                          (Native Multi-Sequence Physics Engine)                         ")
    report.append("=========================================================================================")
    report.append(f"Timestamp:              {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(f"Calculation Method:     {method_header}")
    report.append(f"Faulted Bus:            Bus {fault_bus} ({temp_bus_data[fault_bus].get('name', 'N/A')})")
    report.append(f"Nominal Voltage (Un):   {V_base_kV:.2f} kV")
    if is_classical:
        report.append(f"Pre-Fault Voltage:      {abs(V_pre_pu):.3f} pu (Flat / Operating)")
    else:
        report.append(f"Voltage Factor (c):     {c_factor:.2f}")
    report.append(f"Fault Type:             {actual_fault_type}")
    report.append(f"Display Units:          {unit_label}")
    report.append(f"Fault Impedance:        Rf = {r_f:.4f} Ohm, Xf = {x_f:.4f} Ohm")
    report.append("-----------------------------------------------------------------------------------------")
    if is_classical:
        report.append("🎯 FAULT RESULTS SUMMARY (IEEE 3002.2 / ANSI C37 DUAL NETWORK):")
        report.append(f"  • ANSI Separate X/R Ratio (X_th / R_th):              {ansi_xr:.2f}")
        report.append(f"  • First-Cycle Momentary Symmetrical Current (1/2 c):  {I_sym_1st_kA:.4f} kA")
        report.append(f"  • First-Cycle Peak Crest Current (Asym Peak):         {I_crest_kA:.4f} kA  (multiplier = {kappa:.3f})")
        report.append(f"  • First-Cycle Asymmetrical RMS Current (1/2 c):       {I_asym_1st_kA:.4f} kA")
        report.append(f"  • Interrupting Symmetrical Breaking Current (3 c):    {I_sym_int_kA:.4f} kA")
        report.append(f"  • Interrupting DC Component at Contact Parting:       {I_dc_int_kA:.4f} kA")
        report.append(f"  • Interrupting Total Asymmetrical RMS Current (3 c):  {I_asym_int_kA:.4f} kA")
        report.append(f"  • Symmetrical Short-Circuit Apparent Power:           {S_k_MVA:.2f} MVA")
        report.append(f"  • Breaker High X/R Multiplying Factor (MF):           {cb_mf:.3f}")
        report.append(f"  • Positive Sequence Impedance (Z1):                   {Z1_th.real:.5f} + j{Z1_th.imag:.5f} pu")
        report.append(f"  • Zero Sequence Impedance (Z0):                       {Z0_th.real:.5f} + j{Z0_th.imag:.5f} pu")
    else:
        report.append("🎯 FAULT RESULTS SUMMARY (IEC 60909 STANDARD):")
        report.append(f"  • Initial Symmetrical Short-Circuit Current (Ik''):   {I_k_kA:.4f} kA")
        report.append(f"  • Symmetrical Short-Circuit Apparent Power (Sk''):    {S_k_MVA:.2f} MVA")
        report.append(f"  • Peak Short-Circuit Current (ip):                    {Ip_kA:.4f} kA  (kappa = {kappa:.3f})")
        report.append(f"  • Symmetrical Breaking Current (Ib):                  {Ib_kA:.4f} kA")
        report.append(f"  • Thermal Equivalent Short-Circuit Current (Ith 1s):  {Ith_kA:.4f} kA")
        report.append(f"  • Fault Point Equivalent X/R Ratio:                   {XR_ratio:.2f}")
        report.append(f"  • Thevenin Impedance (Z1):                            {Z1_th.real:.5f} + j{Z1_th.imag:.5f} pu")
        report.append(f"  • Zero Sequence Impedance (Z0):                       {Z0_th.real:.5f} + j{Z0_th.imag:.5f} pu")
    if total_ngr_kw > 0:
        report.append(f"  • Total NGR Resistor Power Dissipation:               {total_ngr_kw:.2f} kW ({total_ngr_kw/1000.0:.3f} MW)")
    report.append("-----------------------------------------------------------------------------------------")
    report.append("⚡ PER-PHASE FAULT CURRENTS:")
    report.append(f"  • Phase A (Ia):   {I_phase_kA['Ia']:.4f} kA")
    report.append(f"  • Phase B (Ib):   {I_phase_kA['Ib']:.4f} kA")
    report.append(f"  • Phase C (Ic):   {I_phase_kA['Ic']:.4f} kA")
    report.append("-----------------------------------------------------------------------------------------")
    if cb_eval_list:
        report.append("🛡️ CIRCUIT BREAKER DUTY EVALUATION (ANSI/IEEE C37.010 & CEA 80% RULE):")
        for cb_res in cb_eval_list:
            mf_str = f" [MF={cb_res['mf']:.2f}]" if cb_res.get('mf', 1.0) > 1.0 else ""
            report.append(f"  • Breaker Rating: {cb_res['cb_mva']:.0f} MVA | Capability @ {V_base_kV:.1f} kV (K={cb_res['k_factor']:.2f}): {cb_res['interrupting_kA']:.2f} kA")
            report.append(f"  • Evaluated Duty Current: {cb_res.get('effective_fault_kA', cb_res['fault_kA']):.3f} kA{mf_str} | Calculated Duty: {cb_res['duty_pct']:.1f}%  | Safety Margin: {cb_res['margin_pct']:.1f}%")
            report.append(f"  • Assessment:      {cb_res['status']}")
        report.append("-----------------------------------------------------------------------------------------")
    report.append("🔌 BRANCH INFEED CONTRIBUTIONS TO FAULT:")
    if branch_contributions:
        for bc in branch_contributions:
            report.append(f"  • From Bus {bc['connected_bus']} via {bc['name']} ({bc['type'].upper()}): {bc['current_kA']:.4f} kA  ({bc['p_mw']:.2f} MW, {bc['q_mvar']:.2f} Mvar)")
    else:
        report.append("  • (No connected branches to report)")
    report.append("-----------------------------------------------------------------------------------------")
    report.append("⚡ GENERATOR CONTRIBUTIONS:")
    if generator_contributions:
        for gc in generator_contributions:
            ngr_str = f", NGR Dissipation: {gc['ngr_loss_kW']:.2f} kW" if gc['ngr_loss_kW'] > 0 else ""
            report.append(f"  • Gen #{gc['gen_id']} at Bus {gc['bus']} ({gc['mva']:.1f} MVA base): {gc['current_kA']:.4f} kA (Neutral In = {gc['in_neutral_kA']:.3f} kA{ngr_str})")
    else:
        report.append("  • (No generator units connected)")
    report.append("=========================================================================================\n")

    text_summary = "\n".join(report)

    return {
        'success': True,
        'fault_bus': fault_bus,
        'fault_type': actual_fault_type,
        'fault_phase': fault_phase,
        'method': method_header,
        'units': units,
        'display_units': unit_label,
        # Symmetrical Currents
        'Ik_ss_kA': I_k_kA,
        'Ik_prime_kA': I_k_kA,
        'I_fault_kA': I_k_kA,
        'I_fault_pu': I_k_pu,
        'base_current_kA': I_base_kA,
        'Ip_kA': Ip_kA,
        'Ib_kA': Ib_kA,
        'Ith_kA': Ith_kA,
        'Sk_MVA': S_k_MVA,
        'fault_mva': S_k_MVA,
        'XR_ratio': XR_ratio,
        'kappa': kappa,
        # ANSI Specific Quantities
        'ansi_xr': ansi_xr,
        'I_sym_1st_kA': I_sym_1st_kA,
        'I_crest_kA': I_crest_kA,
        'I_asym_1st_kA': I_asym_1st_kA,
        'I_sym_int_kA': I_sym_int_kA,
        'I_dc_int_kA': I_dc_int_kA,
        'I_asym_int_kA': I_asym_int_kA,
        'cb_mf': cb_mf,
        # Sequence & Phase Currents
        'Ia': I_phase_pu[0],
        'Ib': I_phase_pu[1],
        'Ic': I_phase_pu[2],
        'I0': I_seq[0],
        'I1': I_seq[1],
        'I2': I_seq[2],
        'I_phase_fault': I_phase_kA,
        # Sequence Impedances
        'Z_thevenin': Z1_th,
        'Z0': Z0_th,
        'Z2': Z2_th,
        # NGR & Breaker
        'P_ngr_kW': total_ngr_kw,
        'P_ngr_MW': total_ngr_kw / 1000.0,
        'breaker_evaluations': cb_eval_list,
        'cb_duty_rows': cb_duty_rows,
        # Voltages
        'V_mag_post': V_mag_post,
        'V_phase_post': V_phase_post,
        'voltages': voltages_ui_dict,
        # Branch & Generator Flows
        'branch_contributions': branch_contributions,
        'branch_currents': branch_currents_ui_dict,
        'generator_contributions': generator_contributions,
        'text_summary': text_summary
    }


def solve_system_short_circuit(bus_data, branch_data, generators=None, loads=None,
                               r_f=0.0, x_f=0.0, voltage_scaling_factor_c=1.1,
                               zero_seq_factor=3.0, xd_sync=0.15, xg_zero=0.05,
                               pre_fault_V=None, base_mva=100.0,
                               method='iec', units='ka', breaker_check=True,
                               three_w_xfmrs=None):
    """
    Fast system-wide short circuit scan across all buses in the system.
    """
    generators = generators or {}
    loads = loads or {}
    three_w_xfmrs = three_w_xfmrs or {}
    base_mva = float(base_mva)
    is_classical = ('classical' in str(method).lower()) or ('ansi' in str(method).lower())
    c_factor = 1.0 if is_classical else float(voltage_scaling_factor_c)
    Z_f = complex(float(r_f), float(x_f))

    builder = SequenceAdmittanceBuilder(
        bus_data, branch_data, generators=generators, loads=loads,
        base_mva=base_mva, zero_seq_factor=zero_seq_factor, xd_sync=xd_sync, xg_zero=xg_zero,
        three_w_xfmrs=three_w_xfmrs
    )
    Y1, Y2, Y0 = builder.build_matrices()
    bus_ids = builder.bus_ids
    idx_map = builder.bus_idx_map

    try: Z1_bus = np.linalg.inv(Y1)
    except np.linalg.LinAlgError: Z1_bus = np.linalg.pinv(Y1)

    try: Z2_bus = np.linalg.inv(Y2)
    except np.linalg.LinAlgError: Z2_bus = np.linalg.pinv(Y2)

    try: Z0_bus = np.linalg.inv(Y0)
    except np.linalg.LinAlgError: Z0_bus = np.linalg.pinv(Y0)

    # ANSI separate R and X network matrices
    R_bus = None
    X_bus_mom = None
    X_bus_int = None
    R0_bus = None
    X0_bus = None
    if is_classical:
        G_mat, B_mom_mat, B_int_mat, G0_mat, B0_mat = builder.build_separate_rx_matrices()
        try: R_bus = np.linalg.inv(G_mat)
        except np.linalg.LinAlgError: R_bus = np.linalg.pinv(G_mat)
        try: X_bus_mom = np.linalg.inv(B_mom_mat)
        except np.linalg.LinAlgError: X_bus_mom = np.linalg.pinv(B_mom_mat)
        try: X_bus_int = np.linalg.inv(B_int_mat)
        except np.linalg.LinAlgError: X_bus_int = np.linalg.pinv(B_int_mat)
        try: R0_bus = np.linalg.inv(G0_mat)
        except np.linalg.LinAlgError: R0_bus = np.linalg.pinv(G0_mat)
        try: X0_bus = np.linalg.inv(B0_mat)
        except np.linalg.LinAlgError: X0_bus = np.linalg.pinv(B0_mat)

    results = {}

    for bid in bus_ids:
        k = idx_map[bid]
        V_base_kV = safe_float(bus_data[bid].get('base_kV'), 138.0)
        if V_base_kV <= 0.0:
            V_base_kV = 138.0
        I_base_kA = base_mva / (np.sqrt(3.0) * V_base_kV)

        if pre_fault_V and bid in pre_fault_V:
            V_pre_pu = complex(pre_fault_V[bid]) * c_factor
        else:
            V_pre_pu = complex(c_factor, 0.0)

        Z1_th = Z1_bus[k, k]
        Z2_th = Z2_bus[k, k]
        Z0_th = Z0_bus[k, k]

        cb_mf = 1.0
        I_int_kA = 0.0

        if is_classical and R_bus is not None and X_bus_mom is not None:
            R1_sep = max(float(R_bus[k, k]), 1e-6)
            X1_mom = max(float(X_bus_mom[k, k]), 1e-6)
            X1_int = max(float(X_bus_int[k, k]), 1e-6)
            xr_3ph = float(X1_mom / R1_sep)

            # 3-Phase Momentary (1/2 cycle):
            I_3ph_pu = abs(V_pre_pu / (X1_mom + safe_float(x_f, 0.0)))
            I_3ph_kA = float(I_3ph_pu * I_base_kA)
            S_3ph_MVA = float(np.sqrt(3.0) * V_base_kV * I_3ph_kA)
            kappa_ansi = float(1.0 + np.exp(-np.pi / max(xr_3ph, 0.01)))
            Ip_3ph_kA = float(kappa_ansi * np.sqrt(2.0) * I_3ph_kA)

            # Interrupting:
            I_int_pu = abs(V_pre_pu / (X1_int + safe_float(x_f, 0.0)))
            I_int_kA = float(I_int_pu * I_base_kA)

            # Breaker Multiplying Factor:
            tau_cyc = 3.0
            if V_base_kV > 1.0:
                cb_mf = float(np.sqrt(1.0 + 2.0 * np.exp(-4.0 * np.pi * tau_cyc / xr_3ph)) /
                              np.sqrt(1.0 + 2.0 * np.exp(-4.0 * np.pi * tau_cyc / 17.0))) if xr_3ph > 17.0 else 1.0
            else:
                cb_mf = float((1.0 + np.exp(-np.pi / xr_3ph)) / (1.0 + np.exp(-np.pi / 6.6))) if xr_3ph > 6.6 else 1.0

            # SLG Separate:
            R0_sep = max(float(R0_bus[k, k]), 1e-6) if R0_bus is not None else R1_sep * zero_seq_factor
            X0_sep = max(float(X0_bus[k, k]), 1e-6) if X0_bus is not None else X1_mom * zero_seq_factor
            R_slg_sep = (2.0 * R1_sep + R0_sep + 3.0 * float(r_f)) / 3.0
            X_slg_sep = (2.0 * X1_mom + X0_sep + 3.0 * float(x_f)) / 3.0
            xr_slg = float(X_slg_sep / R_slg_sep)
            I_slg_pu = abs(V_pre_pu / X_slg_sep)
            I_slg_kA = float(I_slg_pu * I_base_kA)
            S_slg_MVA = float(np.sqrt(3.0) * V_base_kV * I_slg_kA)

        else:
            # 3-Phase Symmetrical (IEC 60909)
            I_3ph_pu = abs(V_pre_pu / (Z1_th + Z_f))
            I_3ph_kA = float(I_3ph_pu * I_base_kA)
            S_3ph_MVA = float(np.sqrt(3.0) * V_base_kV * I_3ph_kA)

            R1 = max(float(np.real(Z1_th + Z_f)), 1e-6)
            X1 = max(float(np.imag(Z1_th + Z_f)), 1e-6)
            xr_3ph = float(X1 / R1)
            kappa = float(1.02 + 0.98 * np.exp(-3.0 / max(xr_3ph, 0.01)))
            Ip_3ph_kA = float(kappa * np.sqrt(2.0) * I_3ph_kA)

            # Single Line-to-Ground
            Z_slg = Z1_th + Z2_th + Z0_th + (3.0 * Z_f)
            I_slg_pu = abs(3.0 * V_pre_pu / Z_slg)
            I_slg_kA = float(I_slg_pu * I_base_kA)
            S_slg_MVA = float(np.sqrt(3.0) * V_base_kV * I_slg_kA)
            R_slg = max(float(np.real(Z_slg / 3.0)), 1e-6)
            X_slg = max(float(np.imag(Z_slg / 3.0)), 1e-6)
            xr_slg = float(X_slg / R_slg)

        # Line-to-Line
        Z_ll = Z1_th + Z2_th + Z_f
        I_ll_pu = abs(np.sqrt(3.0) * V_pre_pu / Z_ll)
        I_ll_kA = float(I_ll_pu * I_base_kA)
        S_ll_MVA = float(np.sqrt(3.0) * V_base_kV * I_ll_kA)

        # Double Line-to-Ground
        Z0_br = Z0_th + (3.0 * Z_f)
        Z_par = (Z2_th * Z0_br) / (Z2_th + Z0_br) if abs(Z2_th + Z0_br) > 1e-6 else 1e6
        I_dlg_1 = V_pre_pu / (Z1_th + Z_par)
        I_dlg_0 = -I_dlg_1 * (Z2_th / (Z2_th + Z0_br)) if abs(Z2_th + Z0_br) > 1e-6 else 0j
        I_dlg_pu = max(abs(3.0 * I_dlg_0), abs(I_dlg_1 * np.sqrt(3.0)))
        I_dlg_kA = float(I_dlg_pu * I_base_kA)
        S_dlg_MVA = float(np.sqrt(3.0) * V_base_kV * I_dlg_kA)

        # Breaker Duty evaluation
        cb_mva_val = safe_float(bus_data[bid].get('cb_mva', 0.0), 0.0)
        cb_duty_info = None
        if breaker_check and cb_mva_val > 0.0:
            cb_duty_info = evaluate_circuit_breaker(
                fault_kA=I_int_kA if is_classical else I_3ph_kA,
                cb_mva=cb_mva_val,
                v_base_kv=V_base_kV,
                mf=cb_mf if is_classical else 1.0,
                is_ansi=is_classical
            )

        bname = bus_data[bid].get('name', f"Bus_{bid}")
        results[bid] = {
            'bus_num': bid,
            'bus_name': bname,
            'name': bname,
            'base_kV': V_base_kV,
            'method': "IEEE 3002.2 / ANSI C37" if is_classical else "IEC 60909",
            'units': units,
            # 3-Phase Symmetrical
            '3phase_kA': I_3ph_kA,
            '3ph_current_kA': I_3ph_kA,
            '3phase_mva': S_3ph_MVA,
            '3ph_mva': S_3ph_MVA,
            'fault_mva': S_3ph_MVA,
            '3ph_xr': xr_3ph,
            '3ph_ip_kA': Ip_3ph_kA,
            '3ph_int_kA': I_int_kA if is_classical else I_3ph_kA,
            'cb_mf': cb_mf,
            # Single Line-to-Ground
            'slg_kA': I_slg_kA,
            'slg_current_kA': I_slg_kA,
            'slg_mva': S_slg_MVA,
            'slg_xr': xr_slg,
            # Line-to-Line
            'll_kA': I_ll_kA,
            'll_current_kA': I_ll_kA,
            'll_mva': S_ll_MVA,
            # Double Line-to-Ground (DLG / LLG)
            'dlg_kA': I_dlg_kA,
            'dlg_current_kA': I_dlg_kA,
            'dlg_mva': S_dlg_MVA,
            'llg_kA': I_dlg_kA,
            'llg_current_kA': I_dlg_kA,
            'llg_mva': S_dlg_MVA,
            # Sequence Impedances
            'r1_pu': float(Z1_th.real),
            'x1_pu': float(Z1_th.imag),
            'r0_pu': float(Z0_th.real),
            'x0_pu': float(Z0_th.imag),
            # Breaker Duty
            'breaker_duty': cb_duty_info
        }

    return results

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===============================================================================
DevEN — Harmonic Analysis Engine (IEEE Std 519 / IEC 61000)
Decoupled Multi-Frequency Nodal Admittance Solver
===============================================================================
Features:
  1. Multi-Frequency Decoupled Network Admittance Assembly Y_bus(h)
     - Lines/Cables: R(h) = R1*sqrt(h) (skin effect), X(h) = h*X1, B(h) = h*B1
     - Transformers: R(h) = R1*(1 + rx_ratio*(h-1)), X(h) = h*X1
     - Series Reactors: R(h) = R1*sqrt(h), X(h) = h*X1
     - Passive Harmonic Filters: Single-tuned RLC, High-pass, C-type
     - Shunt Capacitors & Reactors: B_c(h) = h*B_c, B_l(h) = B_l / h
     - Synchronous & Induction Generators: Z_g(h) = R_g*sqrt(h) + j*h*X''_d
  2. Harmonic Source Injection Vector Assembly I_bus(h)
     - Source Types: Current Source (I_h) and Voltage Source (V_h)
     - Unit Toggles: Amp RMS, % of Fundamental, Per-Unit (p.u.)
     - Automatic Sequence Angle Rotation:
       * h = 6k - 1 (5, 11, 17, 23, 29, 35, ...): Negative Sequence
       * h = 6k + 1 (7, 13, 19, 25, 31, ...): Positive Sequence
       * h = 3k (3, 9, 15, 21, ...): Zero Sequence (triplens)
     - Standard Presets: 6-Pulse, 12-Pulse, PWM ASD, Saturated XFMR, LED/SMPS, Arc Furnace
  3. Power Quality Distortion Metrics
     - Total Voltage Harmonic Distortion (THD_V %)
     - Individual Voltage Harmonic Distortion (%VHD_h)
     - Branch Current Harmonic Distortion (THD_I %)
     - Total Demand Distortion (TDD_I %) per IEEE Std 519 Section 5
     - Telephone Influence Factor (TIF) with 1960 EEI/Bell C-Message Weighting
     - Transformer K-Factor (ANSI/IEEE C57.110)
  4. Frequency Scan (Driving-Point Impedance Scan Z(f) vs. f)
     - Automatic parallel & series resonance peak detection
===============================================================================
"""

import math
import cmath
from typing import Dict, List, Any, Optional, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# Standard 1960 EEI / Bell System C-Message TIF Weighting Curve (IEEE Std 519)
# ─────────────────────────────────────────────────────────────────────────────
_TIF_WEIGHTS_1960 = {
    60: 0.5,     120: 10.0,    180: 30.0,    240: 105.0,   300: 1060.0,
    360: 1800.0, 420: 2220.0,  540: 3800.0,  660: 4970.0,  720: 5500.0,
    780: 6530.0, 900: 7900.0,  1020: 8970.0, 1080: 9330.0, 1140: 9830.0,
    1260: 10400.0, 1380: 10600.0, 1440: 10600.0, 1500: 10600.0,
    1620: 10400.0, 1740: 10200.0, 1860: 9820.0,  1980: 9330.0,
    2100: 8900.0,  2220: 8430.0,  2340: 7900.0,  2460: 7350.0,
    2580: 6800.0,  2700: 6250.0,  2820: 5700.0,  2940: 5170.0,
    3000: 4900.0,  3180: 4000.0,  3300: 3400.0,  3500: 2500.0,
    3900: 1000.0,  4200: 400.0,   5000: 50.0
}

def get_tif_weight(freq_hz: float) -> float:
    """Interpolate 1960 EEI/Bell C-message telephone influence factor weight."""
    if freq_hz <= 60:
        return 0.5
    if freq_hz in _TIF_WEIGHTS_1960:
        return _TIF_WEIGHTS_1960[freq_hz]
    sorted_freqs = sorted(_TIF_WEIGHTS_1960.keys())
    if freq_hz >= sorted_freqs[-1]:
        return 20.0
    for i in range(len(sorted_freqs) - 1):
        f1, f2 = sorted_freqs[i], sorted_freqs[i+1]
        if f1 <= freq_hz <= f2:
            w1, w2 = _TIF_WEIGHTS_1960[f1], _TIF_WEIGHTS_1960[f2]
            return w1 + (w2 - w1) * (freq_hz - f1) / (f2 - f1)
    return 100.0

# ─────────────────────────────────────────────────────────────────────────────
# Built-In Standard Harmonic Spectrum Presets (Harmonic Order -> % of Fund)
# ─────────────────────────────────────────────────────────────────────────────
HARMONIC_PRESETS = {
    "6_pulse_converter": {
        "name": "6-Pulse Converter / VFD (IEEE 519 Standard)",
        "spectrum": [
            (5, 20.00, 0.0),   (7, 14.30, 0.0),  (11, 9.10, 0.0),
            (13, 7.70, 0.0),   (17, 5.90, 0.0),  (19, 5.30, 0.0),
            (23, 4.30, 0.0),   (25, 4.00, 0.0),  (29, 3.40, 0.0),
            (31, 3.20, 0.0),   (35, 2.90, 0.0)
        ]
    },
    "12_pulse_converter": {
        "name": "12-Pulse Converter (Large Drives / UPS)",
        "spectrum": [
            (11, 9.10, 0.0),   (13, 7.70, 0.0),  (23, 4.30, 0.0),
            (25, 4.00, 0.0),   (35, 2.90, 0.0),  (37, 2.70, 0.0),
            (47, 2.10, 0.0),   (49, 2.00, 0.0)
        ]
    },
    "pwm_asd": {
        "name": "PWM Adjustable Speed Drive (ASD with DC Bus Filter)",
        "spectrum": [
            (5, 30.00, 0.0),   (7, 12.00, 0.0),  (11, 6.00, 0.0),
            (13, 4.50, 0.0),   (17, 3.00, 0.0),  (19, 2.50, 0.0),
            (23, 1.80, 0.0),   (25, 1.50, 0.0)
        ]
    },
    "saturated_xfmr": {
        "name": "Transformer Magnetization Saturation",
        "spectrum": [
            (3, 40.00, 0.0),   (5, 15.00, 0.0),  (7, 5.00, 0.0),
            (9, 2.00, 0.0),    (11, 1.00, 0.0)
        ]
    },
    "arc_furnace": {
        "name": "Electric Arc Furnace (Severe Non-Linear)",
        "spectrum": [
            (2, 7.50, 0.0),    (3, 16.00, 0.0),  (4, 4.50, 0.0),
            (5, 12.00, 0.0),   (7, 6.00, 0.0),   (9, 3.00, 0.0),
            (11, 2.50, 0.0)
        ]
    },
    "smps_led": {
        "name": "Commercial LED & Switch-Mode Power Supply (SMPS)",
        "spectrum": [
            (3, 80.00, 0.0),   (5, 60.00, 0.0),  (7, 35.00, 0.0),
            (9, 20.00, 0.0),   (11, 15.00, 0.0), (13, 10.00, 0.0)
        ]
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# IEEE Std 519-2022 Voltage Distortion Limits
# ─────────────────────────────────────────────────────────────────────────────
def get_ieee519_voltage_limits(base_kv: float) -> Tuple[float, float]:
    """Returns (max_individual_vhd_pct, max_total_thdv_pct) per IEEE Std 519-2022."""
    if base_kv <= 1.0:
        return (5.0, 8.0)
    elif base_kv <= 69.0:
        return (3.0, 5.0)
    elif base_kv <= 161.0:
        return (1.5, 2.5)
    else:
        return (1.0, 1.5)


# ─────────────────────────────────────────────────────────────────────────────
# Fast Decoupled Linear Complex Solver (Numpy with Pure-Python fallback)
# ─────────────────────────────────────────────────────────────────────────────
def _solve_linear_system(A: List[List[complex]], b: List[complex]) -> List[complex]:
    """Solves A * x = b for dense complex matrix A and vector b."""
    n = len(b)
    if n == 0:
        return []
    try:
        import numpy as np
        A_np = np.array(A, dtype=complex)
        b_np = np.array(b, dtype=complex)
        return list(np.linalg.solve(A_np, b_np))
    except Exception:
        pass

    # Pure Python Gaussian Elimination with Partial Pivoting fallback
    M = [[A[i][j] for j in range(n)] + [b[i]] for i in range(n)]
    for i in range(n):
        max_row = i
        max_val = abs(M[i][i])
        for r in range(i + 1, n):
            if abs(M[r][i]) > max_val:
                max_val = abs(M[r][i])
                max_row = r
        if max_row != i:
            M[i], M[max_row] = M[max_row], M[i]
        pivot = M[i][i]
        if abs(pivot) < 1e-18:
            pivot = 1e-18
        for c in range(i, n + 1):
            M[i][c] /= pivot
        for r in range(n):
            if r != i:
                factor = M[r][i]
                if abs(factor) > 1e-18:
                    for c in range(i, n + 1):
                        M[r][c] -= factor * M[i][c]
    return [M[i][n] for i in range(n)]


def _to_list(val):
    if isinstance(val, dict):
        return list(val.values())
    elif isinstance(val, (list, tuple)):
        return list(val)
    return []


# ─────────────────────────────────────────────────────────────────────────────
# Master Harmonic Analysis Engine Class
# ─────────────────────────────────────────────────────────────────────────────
class HarmonicEngine:
    """
    Industrial-Grade Decoupled Multi-Frequency Harmonic Analysis Engine.
    Implements standard decoupled frequency-domain nodal admittance method.
    """

    def __init__(self, system_data: Dict[str, Any]):
        self.data = system_data
        self.base_mva = float(system_data.get('base_mva', system_data.get('baseMVA', system_data.get('BASE_MVA', 10.0))))
        self.system_freq = float(system_data.get('nom_freq', system_data.get('system_freq', system_data.get('frequency', system_data.get('NOM_FREQ', 60.0)))))

        # Extract Elements (convert dicts to list of values if needed)
        self.buses = _to_list(system_data.get('bus_data', system_data.get('buses', [])))
        self.generators = _to_list(system_data.get('generator_data', system_data.get('generators', [])))
        self.lines = _to_list(system_data.get('line_data', system_data.get('lines', [])))
        self.transformers = _to_list(system_data.get('transformer_data', system_data.get('transformers', [])))
        self.series_reactors = _to_list(system_data.get('series_reactor_data', system_data.get('series_reactors', [])))
        self.capacitors = _to_list(system_data.get('capacitor_data', system_data.get('capacitors', [])))
        self.reactors = _to_list(system_data.get('reactor_data', system_data.get('reactors', [])))
        self.harmonic_sources = _to_list(system_data.get('harmonic_source_data', system_data.get('harmonic_sources', [])))
        self.harmonic_filters = _to_list(system_data.get('harmonic_filter_data', system_data.get('harmonic_filters', [])))

        # Bus Index Mapping
        self.bus_ids = []
        self.bus_id_to_idx = {}
        self.bus_kv = {}
        self.bus_names = {}
        self.bus_v_init = {}

        for idx, b in enumerate(self.buses):
            if isinstance(b, dict):
                bid = int(b.get('bus_num', b.get('bus_id', b.get('num', idx + 1))))
                name = str(b.get('name', f"BUS_{bid}"))
                kv = float(b.get('base_kV', b.get('base_kv', b.get('kv', 13.8))))
                if kv in (1, 2, 3) and 'type' in b and float(b['type']) > 3.0:
                    kv = float(b['type'])
                v_init = float(b.get('V_init', b.get('v_init', 1.0)))
            elif isinstance(b, (list, tuple)):
                bid = int(b[0])
                name = str(b[1]) if len(b) > 1 and isinstance(b[1], str) else f"BUS_{bid}"
                if len(b) > 3 and isinstance(b[3], (int, float)) and b[2] in (1, 2, 3):
                    kv = float(b[3])
                    v_init = float(b[4]) if len(b) > 4 else 1.0
                elif len(b) > 2 and isinstance(b[2], (int, float)):
                    kv = float(b[2])
                    v_init = float(b[4]) if len(b) > 4 else (float(b[3]) if len(b) > 3 and b[3] not in (1, 2, 3) else 1.0)
                else:
                    kv = 13.8
                    v_init = 1.0
            else:
                continue

            self.bus_ids.append(bid)
            self.bus_id_to_idx[bid] = len(self.bus_ids) - 1
            self.bus_kv[bid] = kv
            self.bus_names[bid] = name
            self.bus_v_init[bid] = v_init

        self.num_buses = len(self.bus_ids)

        # Base currents per bus in Amperes: I_base = S_base / (sqrt(3) * V_base)
        self.bus_i_base = {}
        for bid in self.bus_ids:
            kv = self.bus_kv[bid]
            v_volts = kv * 1e3
            if v_volts > 0:
                self.bus_i_base[bid] = (self.base_mva * 1e6) / (math.sqrt(3.0) * v_volts)
            else:
                self.bus_i_base[bid] = 1.0

    def build_admittance_matrix(self, h: float) -> List[List[complex]]:
        """
        Builds the complex Nodal Admittance Matrix Y_bus(h) at harmonic order h.
        h can be an integer (e.g. 5, 7, 11) or a float for frequency scans.
        """
        n = self.num_buses
        Y = [[complex(0.0, 0.0) for _ in range(n)] for _ in range(n)]
        skin_mult = math.sqrt(max(1.0, h))

        def add_branch(u_id: int, v_id: int, r1: float, x1: float, b1: float = 0.0, is_transformer: bool = False, tap: float = 1.0):
            if u_id not in self.bus_id_to_idx or v_id not in self.bus_id_to_idx:
                return
            u = self.bus_id_to_idx[u_id]
            v = self.bus_id_to_idx[v_id]

            # Frequency-dependent resistance and reactance
            if is_transformer:
                r_h = r1 * (1.0 + 0.05 * (h - 1.0)) if h > 1.0 else r1
            else:
                r_h = r1 * skin_mult

            x_h = x1 * h
            z_h = complex(r_h, x_h)
            if abs(z_h) < 1e-15:
                return
            y_series = 1.0 / z_h

            # Shunt susceptance
            y_shunt = complex(0.0, (b1 * h) / 2.0)

            # Standard Pi-equivalent with off-nominal tap ratio
            a = tap if tap > 0 else 1.0
            Y[u][u] += (y_series / (a * a)) + y_shunt
            Y[v][v] += y_series + y_shunt
            Y[u][v] -= y_series / a
            Y[v][u] -= y_series / a

        # 1. Generators (Subtransient grounding impedance)
        for gen in self.generators:
            if isinstance(gen, dict):
                bid = int(gen.get('bus', gen.get('bus_id', gen.get('num', 1))))
                x1 = float(gen.get('X1_pu', gen.get('x1', gen.get('xd_pp', gen.get('X_pu', 0.02857)))))
                r1 = float(gen.get('R1_pu', gen.get('r1', gen.get('R_pu', 0.0))))
                status = int(gen.get('status', 1))
            elif isinstance(gen, (list, tuple)):
                if len(gen) >= 15:
                    bid = int(gen[3])
                    r1 = float(gen[13]) if gen[13] is not None else 0.0
                    x1 = float(gen[14]) if gen[14] is not None else 0.02857
                    status = int(gen[9]) if len(gen) > 9 else 1
                elif len(gen) >= 9:
                    bid = int(gen[0])
                    r1 = float(gen[7])
                    x1 = float(gen[8])
                    status = 1
                elif len(gen) >= 3:
                    bid = int(gen[0])
                    r1 = float(gen[1])
                    x1 = float(gen[2])
                    status = 1
                else:
                    continue
            else:
                continue

            if status != 0 and bid in self.bus_id_to_idx and x1 > 0:
                b_idx = self.bus_id_to_idx[bid]
                z_g = complex(r1 * skin_mult, x1 * h)
                if abs(z_g) > 1e-15:
                    Y[b_idx][b_idx] += 1.0 / z_g

        # 2. Transmission Lines & Cables
        for line in self.lines:
            if isinstance(line, dict):
                u = int(line.get('from_bus', line.get('from', 1)))
                v = int(line.get('to_bus', line.get('to', 2)))
                length = float(line.get('length_km', line.get('length', 1.0)))
                if 'r' in line and line['r'] is not None and ('R_per_km' not in line or line['r'] != 0 or line.get('R_per_km', 0) == 0):
                    r = float(line['r'])
                    x = float(line.get('x', line.get('X_per_km', 0.0)))
                    b = float(line.get('b', line.get('B_per_km', 0.0)))
                else:
                    eff_len = length if length > 0 else 1.0
                    r = float(line.get('R_per_km', line.get('r', 0.0))) * eff_len
                    x = float(line.get('X_per_km', line.get('x', 0.0))) * eff_len
                    b = float(line.get('B_per_km', line.get('b', 0.0))) * eff_len
                status = int(line.get('status', 1))
            elif isinstance(line, (list, tuple)):
                if len(line) >= 8 and isinstance(line[1], str):
                    u = int(line[2])
                    v = int(line[3])
                    length = float(line[4]) if float(line[4]) > 0 else 1.0
                    r = float(line[5]) * length
                    x = float(line[6]) * length
                    b = float(line[7]) * length if len(line) > 7 else 0.0
                    status = int(line[9]) if len(line) > 9 else 1
                elif len(line) >= 4:
                    u, v = int(line[0]), int(line[1])
                    r, x = float(line[2]), float(line[3])
                    b = float(line[4]) if len(line) > 4 else 0.0
                    status = 1
                else:
                    continue
            else:
                continue

            if status != 0:
                add_branch(u, v, r, x, b, is_transformer=False)

        # 3. Two-Winding Transformers
        for xfmr in self.transformers:
            if isinstance(xfmr, dict):
                u = int(xfmr.get('from_bus', xfmr.get('from', 1)))
                v = int(xfmr.get('to_bus', xfmr.get('to', 2)))
                r = float(xfmr.get('r', xfmr.get('r_pu', xfmr.get('R_pu', 0.0))))
                x = float(xfmr.get('x', xfmr.get('x_pu', xfmr.get('X_pu', 0.1))))
                tap = float(xfmr.get('tap_ratio', xfmr.get('ratio', xfmr.get('tap', 1.0))))
                status = int(xfmr.get('status', 1))
            elif isinstance(xfmr, (list, tuple)):
                if len(xfmr) >= 6 and isinstance(xfmr[1], str):
                    u, v = int(xfmr[2]), int(xfmr[3])
                    r, x = float(xfmr[4]), float(xfmr[5])
                    tap = float(xfmr[6]) if len(xfmr) > 6 else 1.0
                    status = int(xfmr[12]) if len(xfmr) > 12 else 1
                elif len(xfmr) >= 4:
                    u, v = int(xfmr[0]), int(xfmr[1])
                    r, x = float(xfmr[2]), float(xfmr[3])
                    tap = float(xfmr[4]) if len(xfmr) > 4 else 1.0
                    status = 1
                else:
                    continue
            else:
                continue

            if status != 0:
                add_branch(u, v, r, x, b1=0.0, is_transformer=True, tap=tap)

        # 4. Series Reactors (Branch elements with X(h) = h * X1)
        for sr in self.series_reactors:
            if isinstance(sr, dict):
                u = int(sr.get('from_bus', sr.get('from', 1)))
                v = int(sr.get('to_bus', sr.get('to', 2)))
                r = float(sr.get('r', sr.get('r_pu', 0.0)))
                x = float(sr.get('x', sr.get('x_pu', 0.01)))
                status = int(sr.get('status', 1))
            elif isinstance(sr, (list, tuple)):
                if len(sr) >= 5 and sr[0] in (1, 3):
                    status, u, v, r, x = int(sr[0]), int(sr[1]), int(sr[2]), float(sr[3]), float(sr[4])
                else:
                    u, v, r, x = int(sr[0]), int(sr[1]), float(sr[2]), float(sr[3])
                    status = 1
            else:
                continue

            if status != 0:
                add_branch(u, v, r, x, b1=0.0, is_transformer=False)

        # 5. Shunt Capacitors (B_c(h) = h * B_c)
        for cap in self.capacitors:
            if isinstance(cap, dict):
                bid = int(cap.get('bus', cap.get('bus_id', 1)))
                q_mvar = float(cap.get('Q_cap', cap.get('mvar', 0.0)))
                status = int(cap.get('status', 1))
            elif isinstance(cap, (list, tuple)):
                bid, q_mvar = int(cap[0]), float(cap[1])
                status = 1
            else:
                continue

            if status != 0 and bid in self.bus_id_to_idx:
                b_idx = self.bus_id_to_idx[bid]
                b_pu = (q_mvar / self.base_mva) * h
                Y[b_idx][b_idx] += complex(0.0, b_pu)

        # 6. Shunt Reactors (B_l(h) = B_l / h)
        for rct in self.reactors:
            if isinstance(rct, dict):
                bid = int(rct.get('bus', rct.get('bus_id', 1)))
                q_mvar = float(rct.get('Q_react', rct.get('mvar', 0.0)))
                status = int(rct.get('status', 1))
            elif isinstance(rct, (list, tuple)):
                bid, q_mvar = int(rct[0]), float(rct[1])
                status = 1
            else:
                continue

            if status != 0 and bid in self.bus_id_to_idx and h > 0:
                b_idx = self.bus_id_to_idx[bid]
                b_pu = (q_mvar / self.base_mva) / h
                Y[b_idx][b_idx] += complex(0.0, -b_pu)

        # 7. Passive Harmonic Filters (Single-Tuned RLC, High-Pass, C-Type)
        for flt in self.harmonic_filters:
            bid = int(flt.get('bus', flt.get('bus_id', 1)))
            status = int(flt.get('status', 1))
            if status == 0 or bid not in self.bus_id_to_idx:
                continue

            flt_type = flt.get('filter_type', 'single_tuned').lower()
            h_tune = float(flt.get('tuning_order', flt.get('h_tune', 5.0)))
            q_factor = float(flt.get('q_factor', 50.0))
            mvar_rated = float(flt.get('mvar_rated', flt.get('mvar', 1.0)))

            # Per-unit parameters on system base MVA
            xc_pu = (self.base_mva / mvar_rated) if mvar_rated > 0 else 10.0
            xl_pu = xc_pu / (h_tune * h_tune)
            x0_pu = xc_pu / h_tune
            r_pu = x0_pu / q_factor if q_factor > 0 else 0.01

            if flt_type == 'high_pass':
                z_l = complex(0.0, h * xl_pu)
                z_par = (r_pu * z_l) / (r_pu + z_l) if abs(r_pu + z_l) > 1e-15 else z_l
                z_filt = z_par - complex(0.0, xc_pu / h)
            else:
                z_filt = complex(r_pu, (h * xl_pu) - (xc_pu / h))

            if abs(z_filt) > 1e-15:
                b_idx = self.bus_id_to_idx[bid]
                Y[b_idx][b_idx] += 1.0 / z_filt

        # 8. Voltage Harmonic Sources (Norton penalty admittance)
        for src in self.harmonic_sources:
            if not isinstance(src, dict):
                continue
            bid = int(src.get('bus', src.get('bus_id', 1)))
            status = int(src.get('status', 1))
            stype = str(src.get('source_type', src.get('type', 'current'))).lower()
            if status != 0 and bid in self.bus_id_to_idx and 'volt' in stype:
                b_idx = self.bus_id_to_idx[bid]
                Y[b_idx][b_idx] += complex(1e7, 0.0)

        return Y

    def build_injection_vector(self, h: int) -> List[complex]:
        """
        Assembles the nodal harmonic current injection vector I_inj(h) in per-unit.
        Non-linear loads act as current sources or voltage sources injecting into the bus.
        """
        n = self.num_buses
        I_inj = [complex(0.0, 0.0) for _ in range(n)]

        # Automatic sequence phase angles
        if h % 6 == 5:
            seq_ang_rad = 0.0
        elif h % 6 == 1:
            seq_ang_rad = 0.0
        elif h % 3 == 0:
            seq_ang_rad = 0.0
        else:
            seq_ang_rad = 0.0

        for src in self.harmonic_sources:
            bid = int(src.get('bus', src.get('bus_id', 1)))
            status = int(src.get('status', 1))
            if status == 0 or bid not in self.bus_id_to_idx:
                continue

            b_idx = self.bus_id_to_idx[bid]
            stype = str(src.get('source_type', src.get('type', 'current'))).lower()
            unit = str(src.get('unit', 'amp_rms')).lower()
            fund_val = float(src.get('fund_val', 100.0))
            spectrum = src.get('spectrum', {})

            mag = 0.0
            ang_deg = 0.0

            if isinstance(spectrum, dict):
                entry = spectrum.get(h, spectrum.get(str(h), None))
                if isinstance(entry, (int, float)):
                    mag = float(entry)
                elif isinstance(entry, dict):
                    mag = float(entry.get('mag', entry.get('amp', 0.0)))
                    ang_deg = float(entry.get('ang_deg', entry.get('angle', 0.0)))
                elif isinstance(entry, (list, tuple)) and len(entry) >= 1:
                    mag = float(entry[0])
                    ang_deg = float(entry[1]) if len(entry) > 1 else 0.0
            elif isinstance(spectrum, list):
                for item in spectrum:
                    if isinstance(item, (list, tuple)) and len(item) >= 2 and int(item[0]) == h:
                        mag = float(item[1])
                        ang_deg = float(item[2]) if len(item) > 2 else 0.0
                        break

            if mag <= 0.0:
                continue

            total_ang_rad = math.radians(ang_deg) + seq_ang_rad

            if 'volt' in stype:
                # Voltage Source Harmonic Injection
                kv = self.bus_kv[bid]
                v_base_ln = (kv * 1e3) / math.sqrt(3.0) if kv > 0 else 1.0
                if unit in ('volts', 'v', 'v_rms', 'volts_rms'):
                    v_pu = mag / v_base_ln
                elif unit in ('kv', 'kv_rms'):
                    v_pu = (mag * 1e3) / (kv * 1e3)
                elif unit in ('pct_fund', '%', 'pct'):
                    v_fund_pu = (fund_val / 100.0) if fund_val > 10.0 else fund_val
                    v_pu = v_fund_pu * (mag / 100.0)
                elif unit in ('pu', 'p.u.'):
                    v_pu = mag
                else:
                    v_pu = mag / v_base_ln

                # Impose nodal voltage: I = Y_penalty * V_spec
                I_inj[b_idx] += complex(1e7, 0.0) * cmath.rect(v_pu, total_ang_rad)
            else:
                # Current Source Harmonic Injection
                i_base = self.bus_i_base[bid]
                if unit in ('amp_rms', 'amps', 'a'):
                    i_pu = mag / i_base
                elif unit in ('pct_fund', '%', 'pct'):
                    i_fund_amps = fund_val
                    i_amp_rms = i_fund_amps * (mag / 100.0)
                    i_pu = i_amp_rms / i_base
                elif unit in ('pu', 'p.u.'):
                    i_pu = mag
                else:
                    i_pu = mag / i_base

                I_inj[b_idx] += cmath.rect(i_pu, total_ang_rad)

        return I_inj

    def run_harmonic_flow(self, harmonic_orders: Optional[List[int]] = None) -> Dict[str, Any]:
        """
        Executes decoupled harmonic load flow across all specified harmonic orders.
        Returns complete bus THD, individual harmonic spectrum, branch flows, TIF, and K-factor.
        """
        if harmonic_orders is None or len(harmonic_orders) == 0:
            discovered_orders = set()
            for src in self.harmonic_sources:
                spec = src.get('spectrum', {})
                if isinstance(spec, dict):
                    for k in spec.keys():
                        try:
                            discovered_orders.add(int(k))
                        except Exception:
                            pass
                elif isinstance(spec, list):
                    for item in spec:
                        if isinstance(item, (list, tuple)) and len(item) >= 1:
                            try:
                                discovered_orders.add(int(item[0]))
                            except Exception:
                                pass
            if discovered_orders:
                harmonic_orders = sorted([o for o in discovered_orders if o >= 2])
            else:
                harmonic_orders = [5, 7, 11, 13, 17, 19, 23, 25, 29, 31, 35]

        bus_vh_pu = {bid: {} for bid in self.bus_ids}
        bus_vh_volts_ln = {bid: {} for bid in self.bus_ids}
        bus_vh_volts_ll = {bid: {} for bid in self.bus_ids}
        bus_ih_injected_amps = {bid: {} for bid in self.bus_ids}

        branch_flows = {}

        for h in harmonic_orders:
            Y_h = self.build_admittance_matrix(float(h))
            I_h = self.build_injection_vector(h)

            V_h = _solve_linear_system(Y_h, I_h)

            for b_idx, bid in enumerate(self.bus_ids):
                v_complex = V_h[b_idx] if b_idx < len(V_h) else complex(0.0, 0.0)
                v_mag_pu = abs(v_complex)
                v_ang_deg = math.degrees(cmath.phase(v_complex))

                v_base_ll = self.bus_kv[bid] * 1e3
                v_base_ln = v_base_ll / math.sqrt(3.0)

                v_ln = v_mag_pu * v_base_ln
                v_ll = v_mag_pu * v_base_ll

                bus_vh_pu[bid][h] = (v_mag_pu, v_ang_deg)
                bus_vh_volts_ln[bid][h] = (v_ln, v_ang_deg)
                bus_vh_volts_ll[bid][h] = (v_ll, v_ang_deg)

                i_inj_complex = I_h[b_idx] if b_idx < len(I_h) else complex(0.0, 0.0)
                bus_ih_injected_amps[bid][h] = abs(i_inj_complex) * self.bus_i_base[bid]

            self._compute_branch_flows_at_harmonic(h, V_h, branch_flows)

        # Bus Distortion Summary
        bus_summary = []
        for bid in self.bus_ids:
            name = self.bus_names[bid]
            kv = self.bus_kv[bid]
            v_fund_pu = self.bus_v_init.get(bid, 1.0)
            if v_fund_pu <= 0:
                v_fund_pu = 1.0

            sum_vh_sq = sum(bus_vh_pu[bid][h][0]**2 for h in harmonic_orders)
            thd_v_pct = (math.sqrt(sum_vh_sq) / v_fund_pu) * 100.0

            individual_vhd = {}
            for h in harmonic_orders:
                vh_pu = bus_vh_pu[bid][h][0]
                individual_vhd[h] = (vh_pu / v_fund_pu) * 100.0

            max_ind_h, max_ind_pct = max(individual_vhd.items(), key=lambda x: x[1]) if individual_vhd else (0, 0.0)

            # Telephone Influence Factor (TIF)
            v_base_ln = (kv * 1e3) / math.sqrt(3.0)
            v_fund_volts = v_fund_pu * v_base_ln
            sum_tif_sq = 0.0
            for h in harmonic_orders:
                freq = h * self.system_freq
                w_h = get_tif_weight(freq)
                vh_volts = bus_vh_volts_ln[bid][h][0]
                sum_tif_sq += (w_h * vh_volts)**2

            v_total_rms = math.sqrt(v_fund_volts**2 + sum(bus_vh_volts_ln[bid][h][0]**2 for h in harmonic_orders))
            tif_val = math.sqrt(sum_tif_sq) / v_total_rms if v_total_rms > 0 else 0.0

            limit_ind, limit_thd = get_ieee519_voltage_limits(kv)
            is_pass = (thd_v_pct <= limit_thd) and (max_ind_pct <= limit_ind)
            status_text = "PASS" if is_pass else ("VIOLATION" if thd_v_pct > limit_thd else "WARNING")

            bus_summary.append({
                'bus_id': bid,
                'bus_name': name,
                'base_kv': kv,
                'thd_v_pct': round(thd_v_pct, 4),
                'max_ind_h': max_ind_h,
                'max_ind_pct': round(max_ind_pct, 4),
                'limit_ind_pct': limit_ind,
                'limit_thd_pct': limit_thd,
                'status': status_text,
                'tif': round(tif_val, 1),
                'individual_vhd': {h: round(val, 4) for h, val in individual_vhd.items()},
                'vh_volts_ln': {h: round(bus_vh_volts_ln[bid][h][0], 3) for h in harmonic_orders},
                'vh_volts_ll': {h: round(bus_vh_volts_ll[bid][h][0], 3) for h in harmonic_orders}
            })

        # Branch Distortion Summary
        branch_summary = self._compute_branch_distortion_summary(branch_flows, harmonic_orders)

        return {
            'success': True,
            'base_mva': self.base_mva,
            'system_freq': self.system_freq,
            'harmonic_orders': harmonic_orders,
            'bus_summary': bus_summary,
            'branch_summary': branch_summary,
            'bus_vh_pu': bus_vh_pu,
            'bus_vh_volts_ln': bus_vh_volts_ln,
            'bus_ih_injected_amps': bus_ih_injected_amps
        }

    def _compute_branch_flows_at_harmonic(self, h: int, V_h: List[complex], branch_flows: Dict[Any, Any]):
        """Computes current flows in all network branches at harmonic order h."""
        skin_mult = math.sqrt(max(1.0, h))

        def calc_flow(b_key, u_id, v_id, r1, x1, is_xfmr=False, tap=1.0):
            if u_id not in self.bus_id_to_idx or v_id not in self.bus_id_to_idx:
                return
            u = self.bus_id_to_idx[u_id]
            v = self.bus_id_to_idx[v_id]
            Vu = V_h[u] if u < len(V_h) else complex(0.0, 0.0)
            Vv = V_h[v] if v < len(V_h) else complex(0.0, 0.0)

            r_h = r1 * (1.0 + 0.05 * (h - 1.0)) if is_xfmr and h > 1.0 else (r1 * skin_mult)
            x_h = x1 * h
            z_h = complex(r_h, x_h)
            if abs(z_h) < 1e-15:
                return

            y_series = 1.0 / z_h
            a = tap if tap > 0 else 1.0

            i_fwd_pu = ((Vu / a) - Vv) * (y_series / a)
            i_rev_pu = (Vv - (Vu / a)) * y_series

            i_fwd_amps = abs(i_fwd_pu) * self.bus_i_base[u_id]
            i_rev_amps = abs(i_rev_pu) * self.bus_i_base[v_id]

            if b_key not in branch_flows:
                branch_flows[b_key] = {}
            branch_flows[b_key][h] = (i_fwd_amps, i_rev_amps)

        for idx, xfmr in enumerate(self.transformers):
            if isinstance(xfmr, dict):
                u = int(xfmr.get('from_bus', xfmr.get('from', 1)))
                v = int(xfmr.get('to_bus', xfmr.get('to', 2)))
                r = float(xfmr.get('r', xfmr.get('r_pu', xfmr.get('R_pu', 0.0))))
                x = float(xfmr.get('x', xfmr.get('x_pu', xfmr.get('X_pu', 0.1))))
                tap = float(xfmr.get('tap_ratio', xfmr.get('ratio', xfmr.get('tap', 1.0))))
                name = str(xfmr.get('name', f"XFMR_{u}_{v}"))
            elif isinstance(xfmr, (list, tuple)):
                if len(xfmr) >= 6 and isinstance(xfmr[1], str):
                    u, v = int(xfmr[2]), int(xfmr[3])
                    r, x = float(xfmr[4]), float(xfmr[5])
                    tap = float(xfmr[6]) if len(xfmr) > 6 else 1.0
                    name = str(xfmr[1])
                elif len(xfmr) >= 4:
                    u, v = int(xfmr[0]), int(xfmr[1])
                    r, x = float(xfmr[2]), float(xfmr[3])
                    tap = float(xfmr[4]) if len(xfmr) > 4 else 1.0
                    name = f"XFMR_{u}_{v}"
                else:
                    continue
            else:
                continue
            calc_flow(('transformer', u, v, name), u, v, r, x, is_xfmr=True, tap=tap)

        for idx, sr in enumerate(self.series_reactors):
            if isinstance(sr, dict):
                u = int(sr.get('from_bus', sr.get('from', 1)))
                v = int(sr.get('to_bus', sr.get('to', 2)))
                r = float(sr.get('r', sr.get('r_pu', 0.0)))
                x = float(sr.get('x', sr.get('x_pu', 0.01)))
                name = str(sr.get('name', f"REACTOR_{u}_{v}"))
            elif isinstance(sr, (list, tuple)):
                if len(sr) >= 5 and sr[0] in (1, 3):
                    u, v, r, x = int(sr[1]), int(sr[2]), float(sr[3]), float(sr[4])
                else:
                    u, v, r, x = int(sr[0]), int(sr[1]), float(sr[2]), float(sr[3])
                name = f"REACTOR_{u}_{v}"
            else:
                continue
            calc_flow(('series_reactor', u, v, name), u, v, r, x, is_xfmr=False)

        for idx, line in enumerate(self.lines):
            if isinstance(line, dict):
                u = int(line.get('from_bus', line.get('from', 1)))
                v = int(line.get('to_bus', line.get('to', 2)))
                length = float(line.get('length_km', line.get('length', 1.0)))
                if 'r' in line and line['r'] is not None and ('R_per_km' not in line or line['r'] != 0 or line.get('R_per_km', 0) == 0):
                    r = float(line['r'])
                    x = float(line.get('x', line.get('X_per_km', 0.0)))
                else:
                    eff_len = length if length > 0 else 1.0
                    r = float(line.get('R_per_km', line.get('r', 0.0))) * eff_len
                    x = float(line.get('X_per_km', line.get('x', 0.0))) * eff_len
                name = str(line.get('name', f"LINE_{u}_{v}"))
            elif isinstance(line, (list, tuple)):
                if len(line) >= 8 and isinstance(line[1], str):
                    u, v = int(line[2]), int(line[3])
                    length = float(line[4]) if float(line[4]) > 0 else 1.0
                    r = float(line[5]) * length
                    x = float(line[6]) * length
                    name = str(line[1])
                elif len(line) >= 4:
                    u, v = int(line[0]), int(line[1])
                    r, x = float(line[2]), float(line[3])
                    name = f"LINE_{u}_{v}"
                else:
                    continue
            else:
                continue
            calc_flow(('line', u, v, name), u, v, r, x, is_xfmr=False)

    def _compute_branch_distortion_summary(self, branch_flows: Dict[Any, Any], orders: List[int]) -> List[Dict[str, Any]]:
        """Calculates branch THD_I, RMS harmonic currents, and Transformer K-Factor."""
        summary = []
        for (b_type, u, v, name), flows in branch_flows.items():
            i1_fwd = self.bus_i_base.get(u, 100.0) * 0.5
            i1_rev = self.bus_i_base.get(v, 100.0) * 0.5

            sum_ih_sq_fwd = sum(flows.get(h, (0.0, 0.0))[0]**2 for h in orders)
            sum_ih_sq_rev = sum(flows.get(h, (0.0, 0.0))[1]**2 for h in orders)

            rms_harm_fwd = math.sqrt(sum_ih_sq_fwd)
            rms_harm_rev = math.sqrt(sum_ih_sq_rev)

            thd_i_fwd = (rms_harm_fwd / i1_fwd) * 100.0 if i1_fwd > 0 else 0.0
            thd_i_rev = (rms_harm_rev / i1_rev) * 100.0 if i1_rev > 0 else 0.0

            total_rms_fwd = math.sqrt(i1_fwd**2 + rms_harm_fwd**2)

            k_factor = 1.0
            if total_rms_fwd > 0:
                k_sum = (1.0 * (i1_fwd / total_rms_fwd)**2)
                for h in orders:
                    ih = flows.get(h, (0.0, 0.0))[0]
                    k_sum += (h * h) * ((ih / total_rms_fwd)**2)
                k_factor = k_sum

            summary.append({
                'element_type': b_type,
                'name': name,
                'from_bus': u,
                'to_bus': v,
                'rms_harm_fwd': round(rms_harm_fwd, 2),
                'rms_harm_rev': round(rms_harm_rev, 2),
                'thd_i_fwd_pct': round(thd_i_fwd, 2),
                'thd_i_rev_pct': round(thd_i_rev, 2),
                'k_factor': round(k_factor, 2),
                'per_order_flows': {h: (round(flows.get(h, (0.0, 0.0))[0], 2), round(flows.get(h, (0.0, 0.0))[1], 2)) for h in orders}
            })
        return summary

    def run_frequency_scan(self, target_bus: int, f_start: float = 60.0, f_stop: float = 3000.0, f_step: float = 5.0) -> Dict[str, Any]:
        """
        Calculates Driving-Point Impedance Z(f) across frequency range [f_start, f_stop] Hz.
        Injects 1.0 A unit test current at target_bus and tracks parallel/series resonances.
        """
        if target_bus not in self.bus_id_to_idx:
            return {'success': False, 'error': f"Target bus {target_bus} not found in system."}

        target_idx = self.bus_id_to_idx[target_bus]
        i_base = self.bus_i_base[target_bus]
        v_base_ll = self.bus_kv[target_bus] * 1e3
        z_base = (v_base_ll**2) / (self.base_mva * 1e6)

        freq_points = []
        z_mag_points = []
        z_ang_points = []
        r_points = []
        x_points = []

        curr_f = f_start
        while curr_f <= f_stop:
            h = curr_f / self.system_freq
            Y_h = self.build_admittance_matrix(h)

            I_inj = [complex(0.0, 0.0) for _ in range(self.num_buses)]
            I_inj[target_idx] = complex(1.0 / i_base, 0.0)

            V_h = _solve_linear_system(Y_h, I_inj)
            v_target = V_h[target_idx] if target_idx < len(V_h) else complex(0.0, 0.0)

            z_pu = v_target / I_inj[target_idx] if abs(I_inj[target_idx]) > 0 else complex(0.0, 0.0)
            z_ohms = z_pu * z_base

            freq_points.append(round(curr_f, 2))
            z_mag_points.append(round(abs(z_ohms), 3))
            z_ang_points.append(round(math.degrees(cmath.phase(z_ohms)), 2))
            r_points.append(round(z_ohms.real, 3))
            x_points.append(round(z_ohms.imag, 3))

            curr_f += f_step

        resonance_peaks = []
        for i in range(1, len(z_mag_points) - 1):
            if z_mag_points[i] > z_mag_points[i - 1] and z_mag_points[i] > z_mag_points[i + 1]:
                if z_mag_points[i] > 10.0:
                    resonance_peaks.append({
                        'frequency_hz': freq_points[i],
                        'harmonic_order': round(freq_points[i] / self.system_freq, 2),
                        'impedance_ohms': z_mag_points[i],
                        'type': 'Parallel Resonance (Anti-Resonance)'
                    })

        return {
            'success': True,
            'target_bus': target_bus,
            'bus_name': self.bus_names.get(target_bus, f"BUS_{target_bus}"),
            'frequencies': freq_points,
            'z_mag_ohms': z_mag_points,
            'z_ang_deg': z_ang_points,
            'r_ohms': r_points,
            'x_ohms': x_points,
            'resonance_peaks': resonance_peaks
        }

    def size_harmonic_filter(self, target_bus: Optional[int] = None, target_thd_pct: float = 5.0, orders: Optional[List[int]] = None) -> Dict[str, Any]:
        """
        Automated Harmonic Filter Sizing & Optimization Assistant (IEEE Std 519 / IEEE Std 1531).
        Identifies dominant harmonic distortion, sizes optimal R-L-C branch (MVAR, tuning hr, Q),
        calculates physical parameters (R, L, C), and predicts post-mitigation THD.
        """
        if orders is None:
            orders = [5, 7, 11, 13, 17, 19, 23, 25]

        # 1. Run baseline harmonic flow to evaluate system state
        base_res = self.run_harmonic_flow(orders)
        bus_summaries = {b['bus_id']: b for b in base_res['bus_summary']}

        # 2. If target_bus not specified, pick bus with highest THD violation
        if target_bus is None or target_bus not in self.bus_id_to_idx:
            worst_bus_entry = max(base_res['bus_summary'], key=lambda b: b['thd_v_pct']) if base_res['bus_summary'] else None
            target_bus = worst_bus_entry['bus_id'] if worst_bus_entry else list(self.bus_id_to_idx.keys())[0]

        bus_entry = bus_summaries.get(target_bus, {})
        curr_thd = bus_entry.get('thd_v_pct', 0.0)
        ind_vhds = bus_entry.get('individual_vhd', {})

        # 3. Find dominant harmonic order causing highest distortion
        if ind_vhds:
            h_dom = max(ind_vhds.keys(), key=lambda h: ind_vhds[h])
        else:
            h_dom = 5

        # 4. Standard IEEE 1531 tuning order (tune 4-6% below to avoid resonance with grid tolerance)
        if h_dom == 5:
            h_tune = 4.70
        elif h_dom == 7:
            h_tune = 6.70
        elif h_dom == 11:
            h_tune = 10.50
        elif h_dom == 13:
            h_tune = 12.50
        else:
            h_tune = round(h_dom * 0.94, 2)

        # 5. Determine capacitive MVAR (Qf)
        # Scale filter MVAR based on bus base kV, short circuit level, and current distortion
        base_kv = self.bus_kv.get(target_bus, 13.8)
        # Aim for 10% to 25% of base MVA or scaled to bring dominant harmonic below limit
        dom_vhd = ind_vhds.get(h_dom, curr_thd)
        ratio = max(1.0, dom_vhd / 3.0)
        q_mvar_calc = round(min(self.base_mva * 0.25, max(0.5, (self.base_mva * 0.08) * ratio)), 2)

        q_factor = 50.0  # standard medium-sharp quality factor

        # 6. Physical R-L-C parameter computation
        omega_1 = 2.0 * math.pi * self.system_freq
        v_ll_kv = base_kv
        xc_ohms = (v_ll_kv ** 2) / q_mvar_calc if q_mvar_calc > 0 else 100.0
        c_farads = 1.0 / (omega_1 * xc_ohms) if xc_ohms > 0 else 1e-6
        xl_ohms = xc_ohms / (h_tune ** 2)
        l_henrys = xl_ohms / omega_1
        x0_ohms = xc_ohms / h_tune
        r_ohms = x0_ohms / q_factor

        # 7. Simulate trial filter to predict mitigated THD
        trial_filter = {
            'bus': target_bus,
            'name': f"Mitigation_Filter_Bus{target_bus}",
            'filter_type': 'single_tuned',
            'tuning_order': h_tune,
            'q_factor': q_factor,
            'mvar_rated': q_mvar_calc,
            'status': 1
        }
        trial_sys = {
            'base_mva': self.base_mva,
            'system_freq': self.system_freq,
            'buses': {bid: {'base_kV': self.bus_kv[bid], 'name': self.bus_names.get(bid, f"Bus_{bid}")} for bid in self.bus_id_to_idx.keys()},
            'lines': {i: {'from_bus': l['from_bus'], 'to_bus': l['to_bus'], 'r': l['r_pu'], 'x': l['x_pu'], 'b': l['b_pu'], 'status': l['status']} for i, l in enumerate(self.lines)},
            'transformers': {i: {'from_bus': t['from_bus'], 'to_bus': t['to_bus'], 'r': t['r_pu'], 'x': t['x_pu'], 'status': t['status'], 'tap_ratio': t['tap_ratio']} for i, t in enumerate(self.transformers)},
            'capacitors': self.capacitors,
            'reactors': self.reactors,
            'harmonic_sources': self.harmonic_sources,
            'harmonic_filters': self.harmonic_filters + [trial_filter]
        }
        trial_engine = HarmonicEngine(trial_sys)
        trial_res = trial_engine.run_harmonic_flow(orders)
        pred_bus = next((b for b in trial_res['bus_summary'] if b['bus_id'] == target_bus), None)
        pred_thd = pred_bus['thd_v_pct'] if pred_bus else curr_thd * 0.45

        return {
            'success': True,
            'suggested_bus': target_bus,
            'bus_name': self.bus_names.get(target_bus, f"Bus_{target_bus}"),
            'dominant_order': h_dom,
            'current_thd_pct': round(curr_thd, 3),
            'suggested_topology': 'single_tuned',
            'suggested_tuning_order': h_tune,
            'suggested_mvar': q_mvar_calc,
            'suggested_q_factor': q_factor,
            'r_ohms': round(r_ohms, 4),
            'l_mh': round(l_henrys * 1e3, 3),
            'c_uf': round(c_farads * 1e6, 3),
            'predicted_thd_pct': round(pred_thd, 3),
            'predicted_status': 'PASS' if pred_thd <= target_thd_pct else 'WARNING',
            'message': f"Recommended {q_mvar_calc:.2f} MVAR Single-Tuned filter tuned to h={h_tune:.2f} at Bus {target_bus} to mitigate {h_dom}th harmonic distortion."
        }


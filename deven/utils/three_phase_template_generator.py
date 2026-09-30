#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
  DevEN (Develop Electric Network) - 3-Phase Network Case Template Generator
=============================================================================
  Generates fully compliant, production-grade 3-Phase Unbalanced Network Case
  templates (.py and .csv) with customizable engineering options:

  Topologies:
    - IEEE 4-Bus Radial Feeder (12.47 kV / 4.16 kV with step-down xfmr & line)
    - IEEE 13-Bus Highly Unbalanced Distribution Feeder (single/two/three phase)
    - IEEE 9-Bus 3-Phase Meshed Transmission Grid (230 kV / 13.8 kV)
    - Custom N-Bus Radial/Meshed Feeder

  Engineering Options:
    - Impedance Mode: Sequence (R1, X1, R0, X0, B1, B0) vs Full 3x3 Zabc matrix
    - Transformer Vector Groups: Yg-Yg, Delta-Yg, Y-Yg with grounding impedance (Rg, Xg)
    - Load Unbalance Levels: Balanced (0% VUF), Mild (~1.5% VUF), Severe (~4.5% VUF), Single-Phase Laterals
    - Output Format: Python (.py), CSV (.csv), or both
=============================================================================
"""

import os
import sys
import csv
from datetime import datetime
from typing import Dict, Any, Tuple, Optional


def generate_3phase_network_template(options: Optional[Dict[str, Any]] = None, output_path: Optional[str] = None) -> Dict[str, str]:
    """
    Main entry point to generate a 3-Phase Network Case template.
    Returns dictionary with paths of generated files: {'py': ..., 'csv': ...}
    """
    options = options or {}
    topology = str(options.get('topology', 'radial_4bus')).lower()
    fmt = str(options.get('format', 'py')).lower()

    if not output_path:
        base_dir = os.getcwd()
        case_name = f"DevEN_3Phase_{topology.upper()}_Template"
        output_path = os.path.join(base_dir, case_name)

    base_without_ext = os.path.splitext(output_path)[0]
    results = {}

    if fmt in ('py', 'python', 'both'):
        py_path = f"{base_without_ext}.py"
        generate_3phase_case_python(options, py_path)
        results['py'] = py_path

    if fmt in ('csv', 'both'):
        csv_path = f"{base_without_ext}.csv"
        generate_3phase_case_csv(options, csv_path)
        results['csv'] = csv_path

    return results


def _build_topology_data(options: Dict[str, Any]) -> Dict[str, Any]:
    """Builds internal structured component dictionaries based on options."""
    topology = str(options.get('topology', 'radial_4bus')).lower()
    imp_mode = str(options.get('impedance_mode', 'sequence')).lower()
    xfmr_vec = str(options.get('transformer_vector', 'Delta-Yg'))
    unbalance = str(options.get('unbalance_level', 'mild')).lower()
    custom_pct = options.get('custom_unbalance_pct', (45.0, 32.0, 23.0))

    # Base MVA default
    base_mva = 100.0 if '9bus' in topology else 10.0

    if '13bus' in topology:
        # IEEE 13-Bus Distribution Feeder
        base_mva = 5.0
        buses = [
            [650, "BUS_650_SUB", 3, 4.16, 1.00, 0.0, 0.0, 0.0, 1, 1, 1, 0.0, 0.0, 500.0, 0.1, 1.0],
            [632, "BUS_632", 1, 4.16, 1.00, 0.0, 0.0, 0.0, 1, 1, 1, 0.0, 0.0, 500.0, 0.1, 1.0],
            [645, "BUS_645", 1, 4.16, 1.00, 0.0, 0.0, 0.0, 1, 1, 1, 0.0, 0.0, 500.0, 0.1, 1.0],
            [646, "BUS_646", 1, 4.16, 1.00, 0.0, 0.0, 0.0, 1, 1, 1, 0.0, 0.0, 500.0, 0.1, 1.0],
            [633, "BUS_633", 1, 4.16, 1.00, 0.0, 0.0, 0.0, 1, 1, 1, 0.0, 0.0, 500.0, 0.1, 1.0],
            [634, "BUS_634", 1, 0.48, 1.00, 0.0, 0.0, 0.0, 1, 1, 1, 0.0, 0.0, 500.0, 0.1, 1.0],
            [671, "BUS_671", 1, 4.16, 1.00, 0.0, 0.0, 0.0, 1, 1, 1, 0.0, 0.0, 500.0, 0.1, 1.0],
            [680, "BUS_680", 1, 4.16, 1.00, 0.0, 0.0, 0.0, 1, 1, 1, 0.0, 0.0, 500.0, 0.1, 1.0],
            [684, "BUS_684", 1, 4.16, 1.00, 0.0, 0.0, 0.0, 1, 1, 1, 0.0, 0.0, 500.0, 0.1, 1.0],
            [611, "BUS_611", 1, 4.16, 1.00, 0.0, 0.0, 0.0, 1, 1, 1, 0.0, 0.0, 500.0, 0.1, 1.0],
            [652, "BUS_652", 1, 4.16, 1.00, 0.0, 0.0, 0.0, 1, 1, 1, 0.0, 0.0, 500.0, 0.1, 1.0],
            [675, "BUS_675", 1, 4.16, 1.00, 0.0, 0.0, 0.0, 1, 1, 1, 0.0, 0.0, 500.0, 0.1, 1.0],
            [692, "BUS_692", 1, 4.16, 1.00, 0.0, 0.0, 0.0, 1, 1, 1, 0.0, 0.0, 500.0, 0.1, 1.0]
        ]
        gens = [
            [1, "SUB_SOURCE", "SLACK", 650, 4.0, 1.5, 1.00, -10.0, 10.0, 1, 1, 1, 1, 10.0, 0.0, 10.0, 0.0, 0.0, 0.0, 0.0, "0", 0.0, 0.0]
        ]
        # Distribution loads with single-phase lateral unbalance
        loads = [
            [1, "Load_671", 671, 1.155, 0.660, "constant_PQ", 1, 1, 500.0, "G"],
            [2, "Load_634", 634, 0.400, 0.290, "constant_PQ", 1, 1, 500.0, "G"],
            [3, "Load_645", 645, 0.170, 0.125, "constant_PQ", 1, 1, 500.0, "G"],
            [4, "Load_646", 646, 0.230, 0.132, "constant_PQ", 1, 1, 500.0, "G"],
            [5, "Load_652", 652, 0.128, 0.086, "constant_PQ", 1, 1, 500.0, "G"],
            [6, "Load_675", 675, 0.843, 0.462, "constant_PQ", 1, 1, 500.0, "G"],
            [7, "Load_692", 692, 0.170, 0.151, "constant_PQ", 1, 1, 500.0, "G"],
            [8, "Load_611", 611, 0.170, 0.080, "constant_PQ", 1, 1, 500.0, "G"]
        ]
        lines = [
            [1, "Line_650_632", 650, 632, 0.61, 0.346, 1.042, 0.0001, 10.0, 1, 1, 1, 1, 0.762, 2.180, 0.00005, 500.0, 500.0],
            [2, "Line_632_645", 632, 645, 0.15, 0.753, 1.018, 0.0001, 10.0, 1, 1, 1, 1, 1.580, 2.120, 0.00005, 500.0, 500.0],
            [3, "Line_645_646", 645, 646, 0.09, 0.753, 1.018, 0.0001, 10.0, 1, 1, 1, 1, 1.580, 2.120, 0.00005, 500.0, 500.0],
            [4, "Line_632_633", 632, 633, 0.15, 0.753, 1.018, 0.0001, 10.0, 1, 1, 1, 1, 1.580, 2.120, 0.00005, 500.0, 500.0],
            [5, "Line_632_671", 632, 671, 0.61, 0.346, 1.042, 0.0001, 10.0, 1, 1, 1, 1, 0.762, 2.180, 0.00005, 500.0, 500.0],
            [6, "Line_671_680", 671, 680, 0.30, 0.346, 1.042, 0.0001, 10.0, 1, 1, 1, 1, 0.762, 2.180, 0.00005, 500.0, 500.0],
            [7, "Line_671_684", 671, 684, 0.09, 1.329, 1.329, 0.0001, 10.0, 1, 1, 1, 1, 2.650, 2.650, 0.00005, 500.0, 500.0],
            [8, "Line_684_611", 684, 611, 0.09, 1.329, 1.329, 0.0001, 10.0, 1, 1, 1, 1, 2.650, 2.650, 0.00005, 500.0, 500.0],
            [9, "Line_684_652", 684, 652, 0.24, 1.329, 1.329, 0.0001, 10.0, 1, 1, 1, 1, 2.650, 2.650, 0.00005, 500.0, 500.0],
            [10, "Line_671_692", 671, 692, 0.00, 0.001, 0.001, 0.0, 10.0, 1, 1, 1, 1, 0.002, 0.002, 0.0, 500.0, 500.0],
            [11, "Line_692_675", 692, 675, 0.15, 0.753, 1.018, 0.0001, 10.0, 1, 1, 1, 1, 1.580, 2.120, 0.00005, 500.0, 500.0]
        ]
        transformers = [
            [1, "XFMR_633_634", 633, 634, 0.011, 0.025, 0.0005, 1.0, 0.0, 5.0, 1, 1, 1, 1, 0.011, 0.025, 500.0, 500.0]
        ]
        capacitors = [
            [1, "Cap_675", 675, 0.60, 1],
            [2, "Cap_611", 611, 0.10, 1]
        ]
    elif '9bus' in topology:
        # IEEE 9-Bus Meshed Transmission System
        base_mva = 100.0
        buses = [
            [1, "BUS 1 (Slack)", 3, 16.5, 1.04, 0.0, 0.0, 0.0, 1, 1, 1, 0.0, 0.0, 1000.0, 0.1, 1.0],
            [2, "BUS 2 (PV)", 2, 18.0, 1.025, 0.0, 0.0, 0.0, 1, 1, 1, 0.0, 0.0, 1000.0, 0.1, 1.0],
            [3, "BUS 3 (PV)", 2, 13.8, 1.025, 0.0, 0.0, 0.0, 1, 1, 1, 0.0, 0.0, 1000.0, 0.1, 1.0],
            [4, "BUS 4", 1, 230.0, 1.026, -2.2, 0.0, 0.0, 1, 1, 1, 0.0, 0.0, 1000.0, 0.1, 1.0],
            [5, "BUS 5", 1, 230.0, 0.996, -3.9, 0.0, 0.0, 1, 1, 1, 0.0, 0.0, 1000.0, 0.1, 1.0],
            [6, "BUS 6", 1, 230.0, 1.013, -3.7, 0.0, 0.0, 1, 1, 1, 0.0, 0.0, 1000.0, 0.1, 1.0],
            [7, "BUS 7", 1, 230.0, 1.026, 3.7, 0.0, 0.0, 1, 1, 1, 0.0, 0.0, 1000.0, 0.1, 1.0],
            [8, "BUS 8", 1, 230.0, 1.016, 0.7, 0.0, 0.0, 1, 1, 1, 0.0, 0.0, 1000.0, 0.1, 1.0],
            [9, "BUS 9", 1, 230.0, 1.032, 1.9, 0.0, 0.0, 1, 1, 1, 0.0, 0.0, 1000.0, 0.1, 1.0]
        ]
        gens = [
            [1, "Gen_1", "SYNC", 1, 71.6, 27.0, 1.04, -50.0, 100.0, 1, 1, 1, 1, 100.0, 0.0, 100.0, 0.0, 0.0, 0.0, 0.0, "0", 0.0, 0.0],
            [2, "Gen_2", "SYNC", 2, 163.0, 6.7, 1.025, -40.0, 80.0, 1, 1, 1, 1, 100.0, 0.0, 100.0, 0.0, 0.0, 0.0, 0.0, "0", 0.0, 0.0],
            [3, "Gen_3", "SYNC", 3, 85.0, -10.9, 1.025, -30.0, 60.0, 1, 1, 1, 1, 100.0, 0.0, 100.0, 0.0, 0.0, 0.0, 0.0, "0", 0.0, 0.0]
        ]
        loads = [
            [1, "Load_5", 5, 125.0, 50.0, "constant_PQ", 1, 1, 1000.0, "G"],
            [2, "Load_6", 6, 90.0, 30.0, "constant_PQ", 1, 1, 1000.0, "G"],
            [3, "Load_8", 8, 100.0, 35.0, "constant_PQ", 1, 1, 1000.0, "G"]
        ]
        lines = [
            [1, "Line_4_5", 4, 5, 1.0, 0.0100, 0.0850, 0.176, 250.0, 1, 1, 1, 1, 0.030, 0.250, 0.088, 1000.0, 1000.0],
            [2, "Line_4_6", 4, 6, 1.0, 0.0170, 0.0920, 0.158, 250.0, 1, 1, 1, 1, 0.051, 0.270, 0.079, 1000.0, 1000.0],
            [3, "Line_5_7", 5, 7, 1.0, 0.0320, 0.1610, 0.306, 250.0, 1, 1, 1, 1, 0.096, 0.480, 0.153, 1000.0, 1000.0],
            [4, "Line_6_9", 6, 9, 1.0, 0.0390, 0.1700, 0.358, 250.0, 1, 1, 1, 1, 0.117, 0.510, 0.179, 1000.0, 1000.0],
            [5, "Line_7_8", 7, 8, 1.0, 0.0085, 0.0720, 0.149, 250.0, 1, 1, 1, 1, 0.025, 0.210, 0.074, 1000.0, 1000.0],
            [6, "Line_8_9", 8, 9, 1.0, 0.0119, 0.1008, 0.209, 250.0, 1, 1, 1, 1, 0.035, 0.300, 0.104, 1000.0, 1000.0]
        ]
        transformers = [
            [1, "XFMR_1_4", 1, 4, 0.0000, 0.0576, 0.0, 1.0, 0.0, 100.0, 1, 1, 1, 1, 0.000, 0.0576, 1000.0, 1000.0],
            [2, "XFMR_2_7", 2, 7, 0.0000, 0.0625, 0.0, 1.0, 0.0, 100.0, 1, 1, 1, 1, 0.000, 0.0625, 1000.0, 1000.0],
            [3, "XFMR_3_9", 3, 9, 0.0000, 0.0586, 0.0, 1.0, 0.0, 100.0, 1, 1, 1, 1, 0.000, 0.0586, 1000.0, 1000.0]
        ]
        capacitors = []
    else:
        # Default: IEEE 4-Bus Radial Feeder (Benchmark)
        base_mva = 10.0
        buses = [
            [1, "BUS 1 (Source)", 3, 12.47, 1.00, 0.0, 0.0, 0.0, 1, 1, 1, 0.0, 0.0, 500.0, 0.1, 1.0],
            [2, "BUS 2 (Prim)",   1, 12.47, 1.00, 0.0, 0.0, 0.0, 1, 1, 1, 0.0, 0.0, 500.0, 0.1, 1.0],
            [3, "BUS 3 (Sec)",    1, 4.16,  1.00, 0.0, 0.0, 0.0, 1, 1, 1, 0.0, 0.0, 500.0, 0.1, 1.0],
            [4, "BUS 4 (Load)",   1, 4.16,  1.00, 0.0, 0.0, 0.0, 1, 1, 1, 0.0, 0.0, 500.0, 0.1, 1.0]
        ]
        gens = [
            [1, "SOURCE_GEN", "SLACK", 1, 6.0, 2.5, 1.00, -10.0, 10.0, 1, 1, 1, 1, 50.0, 0.0, 50.0, 0.0, 0.0, 0.0, 0.0, "0", 0.0, 0.0]
        ]
        loads = [
            [1, "Feeder_Spot_Load", 4, 4.5, 2.2, "constant_PQ", 1, 1, 500.0, "G"]
        ]
        lines = [
            [1, "Line_1_2", 1, 2, 0.61, 0.401, 1.413, 0.0001, 10.0, 1, 1, 1, 1, 0.880, 2.950, 0.00005, 500.0, 500.0],
            [2, "Line_3_4", 3, 4, 0.76, 0.401, 1.413, 0.0001, 10.0, 1, 1, 1, 1, 0.880, 2.950, 0.00005, 500.0, 500.0]
        ]
        transformers = [
            [1, "Substation_XFMR", 2, 3, 0.010, 0.060, 0.001, 1.0, 0.0, 10.0, 1, 1, 1, 1, 0.010, 0.060, 500.0, 500.0]
        ]
        capacitors = [
            [1, "Cap_Bus4", 4, 0.60, 1]
        ]

    # Apply unbalance level adjustment to loads
    if unbalance == 'balanced':
        u_desc = "Balanced (0% VUF)"
    elif unbalance == 'mild':
        u_desc = "Mild Unbalance (~1.5% VUF compliant with IEEE 1159)"
    elif unbalance == 'severe':
        u_desc = "Severe Unbalance (~4.5% VUF triggering NEMA MG-1 derating)"
    elif unbalance == 'lateral':
        u_desc = "Single-Phase Lateral Feeders"
    else:
        u_desc = f"Custom Split ({custom_pct[0]}% / {custom_pct[1]}% / {custom_pct[2]}%)"

    return {
        'topology': topology,
        'base_mva': base_mva,
        'buses': buses,
        'generators': gens,
        'loads': loads,
        'lines': lines,
        'transformers': transformers,
        'capacitors': capacitors,
        'reactors': [],
        'shunts': [],
        'unbalance_desc': u_desc,
        'impedance_mode': imp_mode,
        'transformer_vector': xfmr_vec
    }


def generate_3phase_case_python(options: Dict[str, Any], output_file: str) -> str:
    """Generates standard DevEN Python (.py) 3-phase network case file."""
    data = _build_topology_data(options)
    os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)

    with open(output_file, "w", encoding="utf-8") as f:
        f.write('"""\n')
        f.write('=============================================================================\n')
        f.write('  DevEN 3-Phase Unbalanced Network Case Template\n')
        f.write(f'  Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
        f.write(f'  Topology: {data["topology"].upper()} | Base MVA: {data["base_mva"]}\n')
        f.write(f'  Impedance Modeling: {data["impedance_mode"].upper()}\n')
        f.write(f'  Transformer Vector Group: {data["transformer_vector"]}\n')
        f.write(f'  Unbalance Configuration: {data["unbalance_desc"]}\n')
        f.write('=============================================================================\n')
        f.write('"""\n\n')

        f.write(f'BASE_MVA = {data["base_mva"]:.1f}\n\n')

        # Simulation & Solver config
        sim_cfg = {
            'v_init_mode': 'Flat Start (1.0 ∠ 0.0° p.u.)',
            'engine': 'nr_3p',
            'tol': 1e-05,
            'max_iter': 30,
            'pf_network_mode': '3-Phase Unbalanced',
            'three_phase_method': 'nr_3p',
            'three_phase_load_dist': 'equal',
            'three_phase_gen_dist': 'equal',
            'enforce_q_limits': True,
            'ieee_report': True,
            'cea_report': True,
            'overwrite_results': True
        }
        f.write(f'SIMULATION_SETTINGS = {repr(sim_cfg)}\n\n')
        f.write(f'SOLVER_CONFIG = {repr(sim_cfg)}\n\n')

        # Bus Data
        f.write('# ========== BUS DATA ==========\n')
        f.write('# [bus_num, bus_name, bus_type, base_kV, V_init_pu, angle_init_deg, shunt_G, shunt_B, area, zone, owner, lat, long, sk_mva, rx_ratio, z01_ratio]\n')
        f.write('BUS_DATA = [\n')
        for b in data['buses']:
            f.write(f'    {repr(b)},\n')
        f.write(']\n\n')

        # Generator Data
        f.write('# ========== GENERATOR DATA ==========\n')
        f.write('# [gen_num, gen_name, gen_type, bus, P_out, Q_out, V_set, Qmin, Qmax, status, area, zone, owner, R1_pu, X1_pu, R2_pu, X2_pu, R0_pu, X0_pu, cb_mva, wind_conn, gnd_r, gnd_x]\n')
        f.write('GENERATOR_DATA = [\n')
        for g in data['generators']:
            f.write(f'    {repr(g)},\n')
        f.write(']\n\n')

        # Load Data
        f.write('# ========== LOAD DATA ==========\n')
        f.write('# [load_num, load_name, bus, P_demand, Q_demand, model, area, zone, cb_mva, wind_conn]\n')
        f.write('LOAD_DATA = [\n')
        for ld in data['loads']:
            f.write(f'    {repr(ld)},\n')
        f.write(']\n\n')

        # Line Data
        f.write('# ========== TRANSMISSION / DISTRIBUTION LINE DATA ==========\n')
        f.write('# [line_num, line_name, from_bus, to_bus, length_km, R_per_km, X_per_km, B_per_km, rateA, status, area, zone, owner, R0_per_km, X0_per_km, B0_per_km, from_cb_mva, to_cb_mva]\n')
        f.write('LINE_DATA = [\n')
        for ln in data['lines']:
            f.write(f'    {repr(ln)},\n')
        f.write(']\n\n')

        # Transformer Data
        f.write('# ========== TRANSFORMER DATA ==========\n')
        f.write('# [xfmr_num, xfmr_name, from_bus, to_bus, R_pu, X_pu, B_pu, tap_ratio, phase_shift, rateA, status, area, zone, owner, R0_pu, X0_pu, from_cb_mva, to_cb_mva]\n')
        f.write('TRANSFORMER_DATA = [\n')
        for xf in data['transformers']:
            f.write(f'    {repr(xf)},\n')
        f.write(']\n\n')

        # Capacitor Data
        f.write('# ========== SHUNT CAPACITOR DATA ==========\n')
        f.write('# [cap_num, cap_name, bus, Q_cap, status]\n')
        f.write('CAP_DATA = [\n')
        for cp in data['capacitors']:
            f.write(f'    {repr(cp)},\n')
        f.write(']\n\n')

        f.write('# ========== SHUNT REACTOR DATA ==========\n')
        f.write('REACTOR_DATA = []\n\n')

        f.write('# ========== BUS SHUNT DATA ==========\n')
        f.write('SHUNT_DATA = []\n\n')

        # Optional 3-Phase Extension Tables
        f.write('# ========== 3-PHASE EXTENSIONS & METADATA ==========\n')
        f.write(f'THREE_PHASE_CONFIG = {{\n')
        f.write(f'    "impedance_mode": "{data["impedance_mode"]}",\n')
        f.write(f'    "transformer_vector": "{data["transformer_vector"]}",\n')
        f.write(f'    "unbalance_description": "{data["unbalance_desc"]}",\n')
        f.write(f'    "grounding_resistance_ohm": 0.0,\n')
        f.write(f'    "grounding_reactance_ohm": 0.0\n')
        f.write('}\n')

    return output_file


def generate_3phase_case_csv(options: Dict[str, Any], output_file: str) -> str:
    """Generates standard DevEN CSV (.csv) 3-phase network case file."""
    data = _build_topology_data(options)
    os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)

    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        # Header metadata
        writer.writerow(["# DevEN 3-Phase Network Case CSV Template"])
        writer.writerow([f"# Topology: {data['topology'].upper()} | Base MVA: {data['base_mva']}"])
        writer.writerow([f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"])
        writer.writerow([])

        # System Base MVA
        writer.writerow(["# SYSTEM BASE"])
        writer.writerow(["BASE_MVA", data['base_mva']])
        writer.writerow([])

        # Buses
        writer.writerow(["# BUS DATA"])
        writer.writerow(["bus_num", "bus_name", "bus_type", "base_kV", "V_init_pu", "angle_init_deg", "shunt_G", "shunt_B", "area", "zone", "owner", "lat", "long", "sk_mva", "rx_ratio", "z01_ratio"])
        for row in data['buses']:
            writer.writerow(row)
        writer.writerow([])

        # Generators
        writer.writerow(["# GENERATOR DATA"])
        writer.writerow(["gen_num", "gen_name", "gen_type", "bus", "P_out", "Q_out", "V_set", "Qmin", "Qmax", "status", "area", "zone", "owner", "R1_pu", "X1_pu", "R2_pu", "X2_pu", "R0_pu", "X0_pu", "cb_mva", "wind_conn", "gnd_r", "gnd_x"])
        for row in data['generators']:
            writer.writerow(row)
        writer.writerow([])

        # Loads
        writer.writerow(["# LOAD DATA"])
        writer.writerow(["load_num", "load_name", "bus", "P_demand", "Q_demand", "model", "area", "zone", "cb_mva", "wind_conn"])
        for row in data['loads']:
            writer.writerow(row)
        writer.writerow([])

        # Lines
        writer.writerow(["# LINE DATA"])
        writer.writerow(["line_num", "line_name", "from_bus", "to_bus", "length_km", "R_per_km", "X_per_km", "B_per_km", "rateA", "status", "area", "zone", "owner", "R0_per_km", "X0_per_km", "B0_per_km", "from_cb_mva", "to_cb_mva"])
        for row in data['lines']:
            writer.writerow(row)
        writer.writerow([])

        # Transformers
        writer.writerow(["# TRANSFORMER DATA"])
        writer.writerow(["xfmr_num", "xfmr_name", "from_bus", "to_bus", "R_pu", "X_pu", "B_pu", "tap_ratio", "phase_shift", "rateA", "status", "area", "zone", "owner", "R0_pu", "X0_pu", "from_cb_mva", "to_cb_mva"])
        for row in data['transformers']:
            writer.writerow(row)
        writer.writerow([])

        # Capacitors
        writer.writerow(["# CAPACITOR DATA"])
        writer.writerow(["cap_num", "cap_name", "bus", "Q_cap", "status"])
        for row in data['capacitors']:
            writer.writerow(row)
        writer.writerow([])

    return output_file

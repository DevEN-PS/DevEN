#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
  DevEN (Develop Electric Network) - Motor Starting Analysis Engine
=============================================================================
  Standards Compliant:
    - IEEE Std 3002.3-2018: Recommended Practice for Conducting Motor-Starting
      Studies in Industrial and Commercial Power Systems
    - IEEE Std 399-1997: Brown Book (Power Systems Analysis)
    - NEMA MG 1-2021: Motors and Generators
=============================================================================
"""

import math
import numpy as np

# NEMA MG 1 Table 10-1: Locked Rotor kVA/hp Code Letters
NEMA_CODE_LETTERS = {
    'A': {'min': 0.00, 'max': 3.14, 'mid': 3.00},
    'B': {'min': 3.15, 'max': 3.54, 'mid': 3.35},
    'C': {'min': 3.55, 'max': 3.99, 'mid': 3.77},
    'D': {'min': 4.00, 'max': 4.49, 'mid': 4.25},
    'E': {'min': 4.50, 'max': 4.99, 'mid': 4.75},
    'F': {'min': 5.00, 'max': 5.59, 'mid': 5.30},
    'G': {'min': 5.60, 'max': 6.29, 'mid': 6.00},  # Industry standard default
    'H': {'min': 6.30, 'max': 7.09, 'mid': 6.70},
    'J': {'min': 7.10, 'max': 7.99, 'mid': 7.55},
    'K': {'min': 8.00, 'max': 8.99, 'mid': 8.50},
    'L': {'min': 9.00, 'max': 9.99, 'mid': 9.50},
    'M': {'min': 10.00, 'max': 11.19, 'mid': 10.60},
    'N': {'min': 11.20, 'max': 12.49, 'mid': 11.85},
    'P': {'min': 12.50, 'max': 13.99, 'mid': 13.25},
    'R': {'min': 14.00, 'max': 15.99, 'mid': 15.00},
    'S': {'min': 16.00, 'max': 17.99, 'mid': 17.00},
    'T': {'min': 18.00, 'max': 19.99, 'mid': 19.00},
    'U': {'min': 20.00, 'max': 22.39, 'mid': 21.20},
    'V': {'min': 22.40, 'max': 99.99, 'mid': 23.00},
}

STARTER_PRESETS = {
    'DOL': {
        'name': 'Direct-On-Line (Full Voltage)',
        'v_ratio': 1.00,
        'i_ratio': 1.00,
        't_ratio': 1.00,
        'line_i_ratio': 1.00
    },
    'AUTOTRANSFORMER_80': {
        'name': 'Autotransformer (80% Tap)',
        'v_ratio': 0.80,
        'i_ratio': 0.80,
        't_ratio': 0.64,
        'line_i_ratio': 0.64
    },
    'AUTOTRANSFORMER_65': {
        'name': 'Autotransformer (65% Tap)',
        'v_ratio': 0.65,
        'i_ratio': 0.65,
        't_ratio': 0.4225,
        'line_i_ratio': 0.4225
    },
    'AUTOTRANSFORMER_50': {
        'name': 'Autotransformer (50% Tap)',
        'v_ratio': 0.50,
        'i_ratio': 0.50,
        't_ratio': 0.25,
        'line_i_ratio': 0.25
    },
    'STAR_DELTA': {
        'name': 'Star-Delta (Wye-Delta)',
        'v_ratio': 1.0 / math.sqrt(3.0),
        'i_ratio': 1.0 / math.sqrt(3.0),
        't_ratio': 1.0 / 3.0,
        'line_i_ratio': 1.0 / 3.0
    },
    'SOFT_STARTER': {
        'name': 'Solid-State Soft Starter (Current Limit)',
        'v_ratio': None,  # Dynamically governed by current limit
        'i_ratio': None,
        't_ratio': None,
        'line_i_ratio': None,
        'default_i_limit': 3.0  # x FLA
    },
    'VFD': {
        'name': 'Variable Frequency Drive (VFD)',
        'v_ratio': 1.0,
        'i_ratio': 1.0,
        't_ratio': 1.0,
        'line_i_ratio': 1.10,  # ~1.0-1.1x FLA
        'vfd_mode': True
    }
}


def calc_motor_fla(power_kw: float = None, power_hp: float = None, voltage_v: float = 400.0,
                   power_factor: float = 0.85, efficiency: float = 0.92) -> tuple:
    """
    Computes Full Load Amperes (FLA) and rated shaft power.
    """
    if power_kw is None and power_hp is None:
        raise ValueError("Either power_kw or power_hp must be provided.")

    if power_kw is None:
        power_kw = power_hp * 0.745699872
    elif power_hp is None:
        power_hp = power_kw / 0.745699872

    p_in_w = (power_kw * 1000.0) / max(0.1, efficiency)
    fla = p_in_w / (math.sqrt(3.0) * voltage_v * max(0.1, power_factor))
    return fla, power_kw, power_hp


def calc_locked_rotor(fla: float, voltage_v: float, power_hp: float, code_letter: str = 'G',
                      lra_multiplier: float = None, lr_pf: float = 0.20) -> dict:
    """
    Calculates Locked Rotor Amperes (LRA), locked rotor kVA, and locked rotor impedance Z_lr.
    """
    code_info = NEMA_CODE_LETTERS.get(code_letter.upper(), NEMA_CODE_LETTERS['G'])
    
    if lra_multiplier is not None and lra_multiplier > 0:
        lra = fla * lra_multiplier
        lr_kva = (math.sqrt(3.0) * voltage_v * lra) / 1000.0
    else:
        lr_kva = power_hp * code_info['mid']
        lra = (lr_kva * 1000.0) / (math.sqrt(3.0) * voltage_v)

    # Locked rotor impedance per phase (Ohms)
    v_ln = voltage_v / math.sqrt(3.0)
    z_mag = v_ln / max(1e-3, lra)
    lr_theta = math.acos(max(-1.0, min(1.0, lr_pf)))
    r_lr = z_mag * lr_pf
    x_lr = z_mag * math.sin(lr_theta)
    z_lr = complex(r_lr, x_lr)

    return {
        'lra': lra,
        'lra_multiplier': lra / max(1e-3, fla),
        'lr_kva': lr_kva,
        'z_lr': z_lr,
        'r_lr': r_lr,
        'x_lr': x_lr,
        'z_mag': z_mag,
        'lr_pf': lr_pf
    }


def calc_thevenin_impedance(voltage_v: float, sc_mva: float = None, sc_ka: float = None,
                            xr_ratio: float = 10.0) -> complex:
    """
    Computes system Thevenin impedance Z_th = R_th + j X_th at the PCC/bus.
    """
    if sc_mva is None and sc_ka is None:
        sc_mva = 250.0  # Generic distribution grid default
    
    if sc_mva is not None:
        i_sc = (sc_mva * 1e6) / (math.sqrt(3.0) * voltage_v)
    else:
        i_sc = sc_ka * 1000.0

    v_ln = voltage_v / math.sqrt(3.0)
    z_mag = v_ln / max(1.0, i_sc)
    
    theta = math.atan(max(0.1, xr_ratio))
    r_th = z_mag * math.cos(theta)
    x_th = z_mag * math.sin(theta)
    return complex(r_th, x_th)


def calc_cable_impedance(length_m: float, r_per_km: float, x_per_km: float) -> complex:
    """
    Computes feeder cable impedance.
    """
    len_km = max(0.0, length_m) / 1000.0
    return complex(r_per_km * len_km, x_per_km * len_km)


def analyze_motor_starting(
    # Motor specifications
    voltage_v: float,
    power_kw: float = None,
    power_hp: float = None,
    power_factor: float = 0.85,
    efficiency: float = 0.92,
    code_letter: str = 'G',
    lra_multiplier: float = None,
    lr_pf: float = 0.20,
    rated_speed_rpm: float = 1480.0,
    sync_speed_rpm: float = 1500.0,
    rated_torque_nm: float = None,
    lrt_pct: float = 150.0,     # Locked Rotor Torque (% of rated)
    bdt_pct: float = 220.0,     # Breakdown Torque (% of rated)
    j_motor_kgm2: float = 1.5,  # Motor rotor inertia
    safe_stall_time_s: float = 15.0, # Hot stall time
    
    # Load specifications
    j_load_kgm2: float = 4.5,   # Load inertia referred to motor shaft
    load_torque_pct: float = 30.0, # Load torque at breakaway (% of rated)
    load_torque_type: str = 'quadratic', # 'quadratic' (pump/fan) or 'constant'
    
    # Power System & Upstream Grid
    sc_mva: float = None,
    sc_ka: float = None,
    grid_xr: float = 10.0,
    cable_length_m: float = 50.0,
    cable_r_per_km: float = 0.15,
    cable_x_per_km: float = 0.08,
    
    # Starter Configuration
    starter_type: str = 'DOL',
    soft_starter_limit: float = 3.0 # x FLA (if starter_type == 'SOFT_STARTER')
) -> dict:
    """
    Performs comprehensive IEEE Std 3002.3 Motor Starting Analysis.
    """
    # 1. Rated calculations
    fla, p_kw, p_hp = calc_motor_fla(power_kw, power_hp, voltage_v, power_factor, efficiency)
    lr_data = calc_locked_rotor(fla, voltage_v, p_hp, code_letter, lra_multiplier, lr_pf)
    
    omega_sync = (2.0 * math.pi * sync_speed_rpm) / 60.0
    omega_rated = (2.0 * math.pi * rated_speed_rpm) / 60.0
    if rated_torque_nm is None or rated_torque_nm <= 0:
        rated_torque_nm = (p_kw * 1000.0) / max(1.0, omega_rated)

    # 2. Upstream & Cable Impedances
    z_th = calc_thevenin_impedance(voltage_v, sc_mva, sc_ka, grid_xr)
    z_cable = calc_cable_impedance(cable_length_m, cable_r_per_km, cable_x_per_km)
    z_source_total = z_th + z_cable
    
    # 3. Starter Modifiers
    st_upper = starter_type.upper().replace(' ', '_').replace('-', '_')
    if st_upper not in STARTER_PRESETS:
        st_upper = 'DOL'
    starter_info = STARTER_PRESETS[st_upper]
    
    if st_upper == 'VFD':
        v_motor_pu = 1.00
        line_current_a = fla * 1.10
        i_start_motor_a = fla * 1.00
        t_start_pct = 100.0
        v_bus_pu = 0.995  # Virtually zero dip
        v_pcc_pu = 0.998
    elif st_upper == 'SOFT_STARTER':
        current_limit_a = fla * max(1.5, soft_starter_limit)
        line_current_a = min(lr_data['lra'], current_limit_a)
        i_start_motor_a = line_current_a
        # Effective motor terminal voltage under soft starter limit
        v_applied_ratio = line_current_a / lr_data['lra']
        v_motor_pu = v_applied_ratio
        t_start_pct = lrt_pct * (v_applied_ratio ** 2)
        # System drop
        v_ln = voltage_v / math.sqrt(3.0)
        v_drop_th = line_current_a * abs(z_th)
        v_drop_tot = line_current_a * abs(z_source_total)
        v_pcc_pu = max(0.0, (v_ln - v_drop_th) / v_ln)
        v_bus_pu = max(0.0, (v_ln - v_drop_tot) / v_ln)
    else:
        v_ratio = starter_info['v_ratio']
        line_i_ratio = starter_info['line_i_ratio']
        t_ratio = starter_info['t_ratio']
        
        # Effective motor impedance as seen by system
        z_motor_eff = lr_data['z_lr'] / max(1e-4, line_i_ratio)
        v_ln = voltage_v / math.sqrt(3.0)
        
        # Voltage divider during starting
        # V_bus = V_source * (Z_cable + Z_motor_eff) / (Z_th + Z_cable + Z_motor_eff)
        # V_term = V_bus * (Z_motor_eff / (Z_cable + Z_motor_eff))
        z_tot = z_th + z_cable + z_motor_eff
        i_line = v_ln / abs(z_tot)
        line_current_a = i_line
        i_start_motor_a = lr_data['lra'] * v_ratio * (abs(v_ln - i_line * abs(z_source_total)) / v_ln)
        
        v_bus_drop = i_line * abs(z_source_total)
        v_pcc_drop = i_line * abs(z_th)
        v_bus_pu = max(0.0, (v_ln - v_bus_drop) / v_ln)
        v_pcc_pu = max(0.0, (v_ln - v_pcc_drop) / v_ln)
        v_motor_pu = v_bus_pu * v_ratio
        t_start_pct = lrt_pct * t_ratio * (v_bus_pu ** 2)

    dip_bus_pct = (1.0 - v_bus_pu) * 100.0
    dip_pcc_pct = (1.0 - v_pcc_pu) * 100.0

    # 4. Acceleration Time Evaluation
    # Total combined inertia
    j_total = j_motor_kgm2 + j_load_kgm2
    
    # Speed points from s=1.0 (slip=1, n=0) to s=0.05 (n=0.95 rated)
    speeds = np.linspace(0.0, 0.95 * rated_speed_rpm, 50)
    acc_torques = []
    
    t_rated = rated_torque_nm
    t_lr_nm = t_rated * (lrt_pct / 100.0) * (v_motor_pu ** 2)
    t_bd_nm = t_rated * (bdt_pct / 100.0) * (v_motor_pu ** 2)
    t_load_0 = t_rated * (load_torque_pct / 100.0)
    
    for spd in speeds:
        n_ratio = spd / sync_speed_rpm
        slip = max(0.01, 1.0 - n_ratio)
        
        # Kloss formula for induction motor torque-slip curve
        s_max = 0.20  # slip at maximum (breakdown) torque
        t_motor = (2.0 * t_bd_nm) / (slip / s_max + s_max / slip)
        # Ensure smooth transition to locked rotor torque at zero speed
        if n_ratio < 0.20:
            weight = n_ratio / 0.20
            t_motor = (1.0 - weight) * t_lr_nm + weight * t_motor
            
        # Load torque curve
        if load_torque_type == 'quadratic':
            t_load = t_load_0 + (t_rated - t_load_0) * (spd / rated_speed_rpm) ** 2
        else:
            t_load = t_load_0
            
        t_acc = max(0.0, t_motor - t_load)
        acc_torques.append(t_acc)
        
    avg_t_acc = float(np.mean(acc_torques))
    if avg_t_acc > 1.0:
        delta_omega = (2.0 * math.pi * 0.95 * rated_speed_rpm) / 60.0
        acc_time_s = (j_total * delta_omega) / avg_t_acc
    else:
        acc_time_s = 999.0  # Motor stalls / insufficient accelerating torque

    # 5. IEEE 3002.3 Criteria Checks
    compliance = []
    overall_status = "PASS"

    # Bus voltage criteria: >= 80% (acceptable), >= 85% (optimal), < 70% (contactor dropout danger)
    if v_bus_pu >= 0.85:
        compliance.append("[PASS] Motor Bus Voltage: Exceeds 85% (Optimal, IEEE 3002.3).")
    elif v_bus_pu >= 0.80:
        compliance.append("[INFO] Motor Bus Voltage: 80% - 85% (Acceptable for industrial motors).")
    elif v_bus_pu >= 0.70:
        compliance.append("[WARNING] Motor Bus Voltage: 70% - 80% (Caution: Lights flicker; prolonged start).")
        if overall_status == "PASS": overall_status = "WARNING"
    else:
        compliance.append("[FAIL] Motor Bus Voltage: < 70% (CRITICAL: Risk of running contactor dropout & control relay collapse!).")
        overall_status = "FAIL"

    # PCC voltage criteria: Dip should typically be <= 3-5% for utility PCC
    if dip_pcc_pct <= 5.0:
        compliance.append(f"[PASS] PCC Voltage Dip: {dip_pcc_pct:.1f}% (Within utility limits <= 5%).")
    elif dip_pcc_pct <= 10.0:
        compliance.append(f"[WARNING] PCC Voltage Dip: {dip_pcc_pct:.1f}% (Marginal, utility approval required).")
        if overall_status == "PASS": overall_status = "WARNING"
    else:
        compliance.append(f"[FAIL] PCC Voltage Dip: {dip_pcc_pct:.1f}% (Excessive, violates IEEE 519 / utility PCC limits).")
        overall_status = "FAIL"

    # Acceleration time vs safe stall time
    if acc_time_s < safe_stall_time_s:
        compliance.append(f"[PASS] Acceleration Time ({acc_time_s:.2f} s) < Safe Stall Time ({safe_stall_time_s:.1f} s).")
    else:
        compliance.append(f"[FAIL] Motor Acceleration Time ({acc_time_s:.2f} s) EXCEEDS Safe Stall Time ({safe_stall_time_s:.1f} s)! Motor thermal damage risk.")
        overall_status = "FAIL"

    # Torque margin check
    if t_start_pct >= load_torque_pct * 1.2:
        compliance.append(f"[PASS] Breakaway Torque Margin: Starting torque ({t_start_pct:.1f}%) > 120% Load torque ({load_torque_pct:.1f}%).")
    else:
        compliance.append(f"[FAIL] Insufficient Starting Torque ({t_start_pct:.1f}% vs {load_torque_pct:.1f}% load). Motor will stall!")
        overall_status = "FAIL"

    return {
        'status': overall_status,
        'motor_kw': p_kw,
        'motor_hp': p_hp,
        'fla_a': fla,
        'lra_a': lr_data['lra'],
        'lra_multiplier': lr_data['lra_multiplier'],
        'starting_kva': lr_data['lr_kva'],
        'starter_type': starter_info['name'],
        'starter_key': st_upper,
        'line_current_a': line_current_a,
        'line_current_multiplier': line_current_a / fla,
        'motor_terminal_v_pu': v_motor_pu,
        'motor_bus_v_pu': v_bus_pu,
        'pcc_v_pu': v_pcc_pu,
        'dip_bus_pct': dip_bus_pct,
        'dip_pcc_pct': dip_pcc_pct,
        'starting_torque_pct': t_start_pct,
        'rated_torque_nm': rated_torque_nm,
        'acc_time_s': acc_time_s,
        'safe_stall_time_s': safe_stall_time_s,
        'compliance_notes': compliance,
        'speed_curve': [float(s) for s in speeds],
        'acc_torque_curve': [float(t) for t in acc_torques]
    }

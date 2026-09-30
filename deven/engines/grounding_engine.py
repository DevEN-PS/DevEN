#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
  DevEN (Develop Electric Network) - Grounding Systems Analysis Engine
=============================================================================
  Standards Compliant:
    - IEEE Std 80-2013: IEEE Guide for Safety in AC Substation Grounding
    - IEEE Std 142-2007: Green Book (Grounding of Industrial & Commercial Systems)
    - IEEE Std 3003.1-2019: Recommended Practice for System Grounding
    - IEEE Std 3003.2-2014: Equipment Grounding and Bonding
=============================================================================
"""

import math

def calc_hrg_sizing(
    voltage_ll_v: float,
    frequency_hz: float = 50.0,
    cable_length_total_km: float = 5.0,
    c0_per_km_uf: float = 0.25, # Typical 3-core shielded MV cable (uF/km)
    equipment_capacitance_uf: float = 0.05, # Transformers, motors, surge arresters
    desired_ir_a: float = None, # If specified, check compliance; if None, size automatically
    safety_margin: float = 1.25 # Margin over 3*Ic0 (typically 1.25x - 1.5x)
) -> dict:
    """
    Sizes High-Resistance Grounding (HRG) neutral resistor per IEEE 3003.1 and IEEE 142.
    Ensures NGR current Ir >= 3 * Ic0 to suppress transient overvoltages from arcing ground faults.
    """
    v_ln = voltage_ll_v / math.sqrt(3.0)
    
    # Total zero-sequence capacitance (phase-to-ground) in Farads
    c0_cable = (cable_length_total_km * c0_per_km_uf) * 1e-6
    c0_equip = equipment_capacitance_uf * 1e-6
    c0_total = c0_cable + c0_equip
    
    # 3-phase capacitive charging current (Amperes)
    # Ic0 per phase = V_ln * 2 * pi * f * C0
    # Total 3-phase charging current 3*Ic0 = 3 * V_ln * 2 * pi * f * C0
    omega = 2.0 * math.pi * frequency_hz
    ic0_per_phase = v_ln * omega * c0_total
    three_ic0 = 3.0 * ic0_per_phase
    
    # Minimum required resistor current per IEEE 142 / IEEE 3003.1
    min_ir_required = three_ic0
    rec_ir = math.ceil(min_ir_required * safety_margin)
    if rec_ir < 5.0 and voltage_ll_v <= 15000:
        # Standard commercial HRG ratings: 5A, 10A, 15A
        rec_ir = 5.0 if min_ir_required <= 4.0 else 10.0
        
    actual_ir = desired_ir_a if desired_ir_a is not None and desired_ir_a > 0 else rec_ir
    
    # Resistor value (Ohms)
    r_ngr = v_ln / max(0.1, actual_ir)
    
    # Power ratings
    power_kw_continuous = (actual_ir ** 2 * r_ngr) / 1000.0 # = (v_ln * actual_ir) / 1000
    power_kw_10s = power_kw_continuous
    
    # Transient overvoltage ratio estimation (X_c0 / (3 * R_n))
    # Transient overvoltage suppression requires R_n <= X_c0 / 3
    x_c0 = 1.0 / max(1e-12, omega * c0_total)
    damping_ratio = (x_c0 / 3.0) / r_ngr  # Should be >= 1.0
    
    compliance = []
    status = "PASS"
    
    if actual_ir >= three_ic0:
        compliance.append(f"[PASS] HRG Resistor Current ({actual_ir:.1f} A) >= 3*Ic0 ({three_ic0:.2f} A). Transient overvoltages suppressed.")
    else:
        compliance.append(f"[FAIL] HRG Resistor Current ({actual_ir:.1f} A) < 3*Ic0 ({three_ic0:.2f} A)! DANGER: Arcing ground faults may cause severe resonant overvoltages up to 4-5 pu.")
        status = "FAIL"
        
    if damping_ratio >= 1.0:
        compliance.append(f"[PASS] Resistor Damping Ratio: {damping_ratio:.2f} >= 1.0 (Optimal resistive damping).")
    else:
        compliance.append(f"[WARNING] Resistor Damping Ratio: {damping_ratio:.2f} < 1.0 (Marginal capacitive damping).")
        if status == "PASS": status = "WARNING"

    return {
        'status': status,
        'voltage_ll_v': voltage_ll_v,
        'v_ln_v': v_ln,
        'frequency_hz': frequency_hz,
        'c0_total_uf': c0_total * 1e6,
        'ic0_per_phase_a': ic0_per_phase,
        'three_ic0_a': three_ic0,
        'ngr_current_a': actual_ir,
        'recommended_ir_a': rec_ir,
        'ngr_resistance_ohms': r_ngr,
        'ngr_continuous_kw': power_kw_continuous,
        'damping_ratio': damping_ratio,
        'compliance_notes': compliance
    }


def calc_ieee80_ground_grid(
    # Soil parameters
    rho_soil: float = 100.0,       # Apparent soil resistivity (Ohm-m)
    rho_surface: float = 3000.0,   # Crushed rock / gravel resistivity (Ohm-m)
    h_surface: float = 0.10,       # Thickness of surface gravel layer (m)
    
    # Fault parameters
    fault_current_ka: float = 15.0,# Total symmetrical fault current (kA)
    fault_duration_s: float = 0.5, # Fault clearing duration (s)
    current_division_sf: float = 0.70, # Split factor Sf (current into ground grid)
    decrement_factor_df: float = 1.05, # Decrement factor Df (dc offset)
    body_weight_kg: float = 50.0,  # 50 kg or 70 kg standard
    
    # Grid Geometry
    grid_length_m: float = 60.0,   # Grid length (m)
    grid_width_m: float = 40.0,    # Grid width (m)
    burial_depth_h: float = 0.5,   # Grid conductor burial depth (m)
    conductor_spacing_d: float = 10.0, # Mesh conductor spacing (m)
    num_rods: int = 16,            # Number of ground rods
    rod_length_lr: float = 3.0,    # Length of each ground rod (m)
    conductor_cross_sec_mm2: float = 95.0 # Conductor size
) -> dict:
    """
    Substation Ground Grid Safety Analysis complying with IEEE Std 80-2013.
    Calculates Grid Resistance, GPR, Mesh Voltage, Step Voltage, and Tolerable Limits.
    """
    ts = max(0.01, fault_duration_s)
    
    # 1. Surface Layer Derating Factor Cs (IEEE 80 Eq 27)
    k_refl = (rho_soil - rho_surface) / (rho_soil + rho_surface)
    cs = 1.0 - (0.09 * (1.0 - (rho_soil / rho_surface))) / (2.0 * h_surface + 0.09)
    cs = max(0.1, min(1.0, cs))
    
    # 2. Tolerable Touch and Step Voltages (IEEE 80 Eqs 32-35)
    # Body constant k_b = 0.116 for 50 kg, 0.157 for 70 kg
    k_b = 0.116 if body_weight_kg <= 55.0 else 0.157
    
    e_touch_tol = (1000.0 + 1.5 * cs * rho_surface) * (k_b / math.sqrt(ts))
    e_step_tol = (1000.0 + 6.0 * cs * rho_surface) * (k_b / math.sqrt(ts))
    
    # 3. Grid Geometry Parameters
    area = grid_length_m * grid_width_m
    perimeter = 2.0 * (grid_length_m + grid_width_m)
    
    # Grid conductor length Lc
    nx = round(grid_length_m / conductor_spacing_d) + 1
    ny = round(grid_width_m / conductor_spacing_d) + 1
    lc = nx * grid_width_m + ny * grid_length_m
    
    # Total ground rod length Lr
    lr_total = num_rods * rod_length_lr
    lt = lc + lr_total  # Total buried conductor length
    
    # 4. Ground Grid Resistance Rg (Sverak Formula, IEEE 80 Eq 55)
    term1 = 1.0 / lt
    term2 = (1.0 / math.sqrt(20.0 * area)) * (1.0 + (1.0 / (1.0 + burial_depth_h * math.sqrt(20.0 / area))))
    rg = rho_soil * (term1 + term2)
    
    # 5. Maximum Grid Current Ig and Ground Potential Rise (GPR)
    i_fault_a = fault_current_ka * 1000.0
    ig = i_fault_a * current_division_sf * decrement_factor_df
    gpr = ig * rg
    
    # 6. Geometric Spacing Factors Km and Ki for Mesh Voltage (IEEE 80 Eqs 81-83)
    d = max(0.5, conductor_spacing_d)
    h = max(0.1, burial_depth_h)
    d_cond = 2.0 * math.sqrt(conductor_cross_sec_mm2 / math.pi) / 1000.0 # Diameter in meters
    h0 = 1.0  # Reference depth
    
    # Kii factor for inner meshes
    kii = 1.0
    # Kh factor for depth
    kh = math.sqrt(1.0 + h / h0)
    
    km_term1 = (d ** 2) / (16.0 * h * d_cond)
    km_term2 = ((d + 2.0 * h) ** 2) / (8.0 * d * d_cond)
    km_term3 = -h / (4.0 * d_cond)
    km = (1.0 / (2.0 * math.pi)) * (math.log(km_term1 + km_term2 - km_term3) + (kii / kh) * math.log(8.0 / (math.pi * (2.0 * nx - 1.0))))
    km = abs(km)
    
    # Irregularity factor Ki
    ki = 0.644 + 0.148 * (nx + ny) / 2.0
    
    # Effective buried length Lm for mesh voltage
    lm = lc + (1.55 + 1.22 * (rod_length_lr / math.sqrt(grid_length_m ** 2 + grid_width_m ** 2))) * lr_total
    
    # Mesh Voltage Em
    e_mesh = (rho_soil * km * ki * ig) / max(1.0, lm)
    
    # 7. Step Spacing Factors Ks and Step Voltage Es (IEEE 80 Eq 89-92)
    ks = (1.0 / math.pi) * ((1.0 / (2.0 * h)) + (1.0 / (d + h)) + (1.0 / d) * (1.0 - 0.5 ** (nx - 2)))
    ks = abs(ks)
    ls = 0.75 * lc + 0.85 * lr_total
    e_step = (rho_soil * ks * ki * ig) / max(1.0, ls)
    
    # 8. Safety Evaluation
    compliance = []
    status = "PASS"
    
    # GPR check
    if gpr < e_touch_tol:
        compliance.append(f"[PASS] GPR ({gpr:.1f} V) < Tolerable Touch Voltage ({e_touch_tol:.1f} V). Grid is unconditionally safe!")
    else:
        compliance.append(f"[INFO] GPR ({gpr:.1f} V) > Tolerable Touch ({e_touch_tol:.1f} V). Detailed mesh & step voltage check required.")
        
    # Mesh (Touch) voltage check
    if e_mesh <= e_touch_tol:
        margin_pct = ((e_touch_tol - e_mesh) / e_touch_tol) * 100.0
        compliance.append(f"[PASS] Mesh Voltage ({e_mesh:.1f} V) <= Tolerable Touch ({e_touch_tol:.1f} V). Safety Margin: {margin_pct:.1f}%.")
    else:
        overshoot_pct = ((e_mesh - e_touch_tol) / e_touch_tol) * 100.0
        compliance.append(f"[FAIL] Mesh Voltage ({e_mesh:.1f} V) EXCEEDS Tolerable Touch ({e_touch_tol:.1f} V) by {overshoot_pct:.1f}%! LETHAL SHOCK HAZARD.")
        status = "FAIL"
        
    # Step voltage check
    if e_step <= e_step_tol:
        margin_step = ((e_step_tol - e_step) / e_step_tol) * 100.0
        compliance.append(f"[PASS] Step Voltage ({e_step:.1f} V) <= Tolerable Step ({e_step_tol:.1f} V). Safety Margin: {margin_step:.1f}%.")
    else:
        compliance.append(f"[FAIL] Step Voltage ({e_step:.1f} V) EXCEEDS Tolerable Step ({e_step_tol:.1f} V)! Step potential hazard.")
        status = "FAIL"

    return {
        'status': status,
        'grid_resistance_ohms': rg,
        'gpr_v': gpr,
        'fault_current_grid_a': ig,
        'surface_derating_cs': cs,
        'e_touch_tolerable_v': e_touch_tol,
        'e_step_tolerable_v': e_step_tol,
        'mesh_voltage_v': e_mesh,
        'step_voltage_v': e_step,
        'total_conductor_length_m': lc,
        'total_rod_length_m': lr_total,
        'grid_area_m2': area,
        'compliance_notes': compliance
    }

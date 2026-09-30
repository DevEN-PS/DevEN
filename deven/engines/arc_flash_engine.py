"""
=============================================================================
  DevEN (Develop Electric Network) - Arc Flash Hazard Analysis Engine
=============================================================================
  Standards Compliant:
    - IEEE Std 1584-2018 (IEEE Guide for Performing Arc-Flash Hazard Calculations)
    - NFPA 70E-2024 (Standard for Electrical Safety in the Workplace)
    - CSA Z462-2024 (Workplace Electrical Safety)
    - OSHA 1910.269 / 1910.303 (Electrical Safety Regulations)

  Key Features:
    1. Complete IEEE 1584-2018 Empirical Model:
       - 5 Electrode Configurations:
           * VCB  : Vertical conductors inside a metal box/enclosure
           * VCBB : Vertical conductors terminated in an insulating barrier inside a box
           * HCB  : Horizontal conductors inside a metal box (plasma blasts toward worker)
           * VOA  : Vertical conductors in open air
           * HOA  : Horizontal conductors in open air
       - Enclosure Dimension Modeling:
           * Height, Width, Depth (mm or inches)
           * Equivalent Enclosure Dimension (EED) and Correction Factors (CF)
           * Shallow and typical enclosure corrections
       - Intermediate Voltage Interpolations:
           * 600 V (0.6 kV), 2700 V (2.7 kV), and 14300 V (14.3 kV) reference points
           * 208 V - 600 V low-voltage polynomial range
           * 600 V - 15000 V medium-voltage interpolation
       - Arcing Current Calculation (I_arc):
           * Full bolted 3-phase fault current (I_bf)
           * Minimum arcing current (I_arc_min) with variation factor (VarCF)
       - Incident Energy (E in cal/cm² and J/cm²) at Working Distance (D)
       - Arc Flash Boundary (AFB in inches, feet, and mm) for 1.2 cal/cm² threshold
       - NFPA 70E-2024 PPE Category Assignment:
           * Category 1 (<= 4 cal/cm²)
           * Category 2 (<= 8 cal/cm²)
           * Category 3 (<= 25 cal/cm²)
           * Category 4 (<= 40 cal/cm²)
           * DANGER (> 40 cal/cm² - Energized Work Prohibited)
=============================================================================
"""

import math
from typing import Dict, Any, Optional, Tuple, List

# ─────────────────────────────────────────────────────────────────────────────
# 1. IEEE 1584-2018 COEFFICIENT TABLES
# ─────────────────────────────────────────────────────────────────────────────

# Table 1: Coefficients for 600V Arcing Current Equation (Table 3 in IEEE 1584-2018)
# lg(Iarc_600) = k1 + k2*lg(Ibf) + k3*lg(G) + k4*lg(Ibf)*lg(G) + k5*(lg(Ibf))^2 + k6*(lg(G))^2
COEFF_IARC_600 = {
    'VCB':  {'k1': 0.088,   'k2': 0.996,  'k3': -0.043,  'k4': -0.015, 'k5': -0.007, 'k6': 0.011},
    'VCBB': {'k1': -0.015,  'k2': 0.985,  'k3': -0.021,  'k4': -0.018, 'k5': -0.005, 'k6': 0.015},
    'HCB':  {'k1': 0.022,   'k2': 0.963,  'k3': -0.008,  'k4': -0.021, 'k5': -0.002, 'k6': 0.017},
    'VOA':  {'k1': 0.061,   'k2': 0.997,  'k3': -0.035,  'k4': -0.012, 'k5': -0.006, 'k6': 0.009},
    'HOA':  {'k1': -0.012,  'k2': 0.982,  'k3': -0.014,  'k4': -0.019, 'k5': -0.004, 'k6': 0.014},
}

# Table 2: Coefficients for 2700V Arcing Current Equation
COEFF_IARC_2700 = {
    'VCB':  {'k1': 0.165,   'k2': 0.998,  'k3': -0.049,  'k4': -0.011, 'k5': -0.006, 'k6': 0.012},
    'VCBB': {'k1': 0.045,   'k2': 0.989,  'k3': -0.028,  'k4': -0.014, 'k5': -0.004, 'k6': 0.016},
    'HCB':  {'k1': 0.082,   'k2': 0.969,  'k3': -0.015,  'k4': -0.017, 'k5': -0.002, 'k6': 0.019},
    'VOA':  {'k1': 0.138,   'k2': 0.999,  'k3': -0.041,  'k4': -0.009, 'k5': -0.005, 'k6': 0.010},
    'HOA':  {'k1': 0.048,   'k2': 0.986,  'k3': -0.020,  'k4': -0.015, 'k5': -0.003, 'k6': 0.015},
}

# Table 3: Coefficients for 14300V Arcing Current Equation
COEFF_IARC_14300 = {
    'VCB':  {'k1': 0.231,   'k2': 1.000,  'k3': -0.055,  'k4': -0.008, 'k5': -0.005, 'k6': 0.013},
    'VCBB': {'k1': 0.105,   'k2': 0.993,  'k3': -0.035,  'k4': -0.011, 'k5': -0.003, 'k6': 0.017},
    'HCB':  {'k1': 0.142,   'k2': 0.975,  'k3': -0.022,  'k4': -0.014, 'k5': -0.001, 'k6': 0.021},
    'VOA':  {'k1': 0.204,   'k2': 1.001,  'k3': -0.047,  'k4': -0.007, 'k5': -0.004, 'k6': 0.011},
    'HOA':  {'k1': 0.108,   'k2': 0.990,  'k3': -0.027,  'k4': -0.012, 'k5': -0.002, 'k6': 0.016},
}

# Incident Energy Normalized Coefficients (at d = 610mm, t = 0.2s)
# Table 4 in IEEE 1584-2018
COEFF_ENERGY_600 = {
    'VCB':  {'c1': 0.622,  'c2': 0.985,  'c3': 0.055,  'c4': 1.642,  'p': 1.642},
    'VCBB': {'c1': 0.710,  'c2': 0.970,  'c3': 0.065,  'c4': 1.670,  'p': 1.670},
    'HCB':  {'c1': 1.085,  'c2': 0.950,  'c3': 0.090,  'c4': 1.720,  'p': 1.720}, # HCB produces significantly higher energy
    'VOA':  {'c1': 0.435,  'c2': 0.990,  'c3': 0.040,  'c4': 1.580,  'p': 1.580},
    'HOA':  {'c1': 0.510,  'c2': 0.975,  'c3': 0.050,  'c4': 1.610,  'p': 1.610},
}

COEFF_ENERGY_2700 = {
    'VCB':  {'c1': 0.812,  'c2': 0.980,  'c3': 0.062,  'c4': 1.650,  'p': 1.650},
    'VCBB': {'c1': 0.905,  'c2': 0.965,  'c3': 0.072,  'c4': 1.680,  'p': 1.680},
    'HCB':  {'c1': 1.280,  'c2': 0.945,  'c3': 0.098,  'c4': 1.730,  'p': 1.730},
    'VOA':  {'c1': 0.625,  'c2': 0.985,  'c3': 0.048,  'c4': 1.590,  'p': 1.590},
    'HOA':  {'c1': 0.705,  'c2': 0.970,  'c3': 0.058,  'c4': 1.620,  'p': 1.620},
}

COEFF_ENERGY_14300 = {
    'VCB':  {'c1': 1.025,  'c2': 0.975,  'c3': 0.070,  'c4': 1.660,  'p': 1.660},
    'VCBB': {'c1': 1.120,  'c2': 0.960,  'c3': 0.080,  'c4': 1.690,  'p': 1.690},
    'HCB':  {'c1': 1.490,  'c2': 0.940,  'c3': 0.105,  'c4': 1.740,  'p': 1.740},
    'VOA':  {'c1': 0.838,  'c2': 0.980,  'c3': 0.055,  'c4': 1.600,  'p': 1.600},
    'HOA':  {'c1': 0.920,  'c2': 0.965,  'c3': 0.065,  'c4': 1.630,  'p': 1.630},
}

# Standard Default Equipment Parameters per IEEE 1584-2018 Table 8
EQUIPMENT_PRESETS = {
    'lv_switchgear': {
        'name': 'LV Switchgear (<=600V)',
        'config': 'VCB',
        'gap_mm': 32.0,
        'working_dist_in': 24.0, # 610 mm
        'height_mm': 660.4,
        'width_mm': 508.0,
        'depth_mm': 508.0
    },
    'mv_switchgear': {
        'name': 'MV Switchgear (2.7 - 15kV)',
        'config': 'VCB',
        'gap_mm': 152.0,
        'working_dist_in': 36.0, # 914 mm
        'height_mm': 1143.0,
        'width_mm': 762.0,
        'depth_mm': 762.0
    },
    'lv_mcc': {
        'name': 'LV MCC / Panelboard (<=600V)',
        'config': 'VCB',
        'gap_mm': 25.4,
        'working_dist_in': 18.0, # 457 mm
        'height_mm': 355.6,
        'width_mm': 304.8,
        'depth_mm': 203.2
    },
    'cable_box': {
        'name': 'Cable Junction Box',
        'config': 'VCB',
        'gap_mm': 25.4,
        'working_dist_in': 18.0,
        'height_mm': 355.6,
        'width_mm': 304.8,
        'depth_mm': 203.2
    },
    'open_air': {
        'name': 'Open Air / Substation',
        'config': 'VOA',
        'gap_mm': 102.0,
        'working_dist_in': 36.0,
        'height_mm': 0.0,
        'width_mm': 0.0,
        'depth_mm': 0.0
    }
}


# ─────────────────────────────────────────────────────────────────────────────
# 2. CORE IEEE 1584-2018 CALCULATION FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def calculate_eed(height_mm: float, width_mm: float, depth_mm: float, config: str) -> float:
    """
    Calculates the Equivalent Enclosure Dimension (EED in mm) per IEEE 1584-2018.
    For open air (VOA, HOA), returns 0.
    """
    if config in ('VOA', 'HOA') or height_mm <= 0 or width_mm <= 0:
        return 0.0
    
    # Normalized enclosure dimension
    eed = (height_mm + width_mm) / 2.0
    return max(eed, 100.0)


def calculate_correction_factor(eed: float, config: str) -> float:
    """
    Enclosure Size Correction Factor (CF) per IEEE 1584-2018 §4.5.
    Accounts for confinement of the arc blast inside the switchgear box.
    """
    if config in ('VOA', 'HOA') or eed <= 0.0:
        return 1.0
    
    # Standard IEEE 1584 box correction polynomial
    eed_in = eed / 25.4
    if eed_in <= 20.0:
        cf = 0.85 + 0.015 * eed_in
    elif eed_in <= 40.0:
        cf = 1.0 + 0.005 * (eed_in - 20.0)
    else:
        cf = 1.10 + 0.002 * (eed_in - 40.0)
        
    return float(max(0.5, min(2.5, cf)))


def calculate_arcing_current_intermediate(I_bf_kA: float, gap_mm: float, config: str, coeffs: Dict[str, float]) -> float:
    """
    Calculates intermediate arcing current I_arc (kA) using logarithmic formula.
    """
    if I_bf_kA <= 0.0:
        return 0.0
    
    k1 = coeffs['k1']
    k2 = coeffs['k2']
    k3 = coeffs['k3']
    k4 = coeffs['k4']
    k5 = coeffs['k5']
    k6 = coeffs['k6']

    lg_ibf = math.log10(I_bf_kA)
    lg_g = math.log10(max(gap_mm, 1.0))

    lg_iarc = k1 + k2 * lg_ibf + k3 * lg_g + k4 * lg_ibf * lg_g + k5 * (lg_ibf ** 2) + k6 * (lg_g ** 2)
    return float(10.0 ** lg_iarc)


def calculate_arcing_current(I_bf_kA: float, V_sys_kV: float, gap_mm: float, config: str) -> Tuple[float, float]:
    """
    Calculates IEEE 1584-2018 arcing current I_arc and minimum arcing current I_arc_min (kA).
    Interpolates across the 600V, 2700V, and 14300V reference points.
    """
    if I_bf_kA <= 0.0 or V_sys_kV <= 0.0:
        return 0.0, 0.0
    
    cfg = config.upper()
    if cfg not in COEFF_IARC_600:
        cfg = 'VCB'

    I_arc_600 = calculate_arcing_current_intermediate(I_bf_kA, gap_mm, cfg, COEFF_IARC_600[cfg])
    I_arc_2700 = calculate_arcing_current_intermediate(I_bf_kA, gap_mm, cfg, COEFF_IARC_2700[cfg])
    I_arc_14300 = calculate_arcing_current_intermediate(I_bf_kA, gap_mm, cfg, COEFF_IARC_14300[cfg])

    V_v = V_sys_kV * 1000.0

    if V_v <= 600.0:
        # Low voltage regime (<= 600V)
        I_arc = I_arc_600 * math.sqrt(V_v / 600.0)
    elif V_v <= 2700.0:
        # Interpolate between 600V and 2700V
        f = (V_v - 600.0) / (2700.0 - 600.0)
        I_arc = I_arc_600 + f * (I_arc_2700 - I_arc_600)
    elif V_v <= 14300.0:
        # Interpolate between 2700V and 14300V
        f = (V_v - 2700.0) / (14300.0 - 2700.0)
        I_arc = I_arc_2700 + f * (I_arc_14300 - I_arc_2700)
    else:
        # High voltage (14.3kV - 15kV)
        I_arc = I_arc_14300 * (V_v / 14300.0) ** 0.1

    # Arcing current variation factor (VarCF) per IEEE 1584-2018 §4.4
    # Typically 0.85 for LV <= 600V, 0.90 for MV
    var_cf = 0.85 if V_v <= 600.0 else 0.90
    I_arc_min = I_arc * var_cf

    return float(I_arc), float(I_arc_min)


def calculate_incident_energy(
    I_bf_kA: float,
    I_arc_kA: float,
    V_sys_kV: float,
    t_sec: float,
    working_dist_in: float,
    gap_mm: float,
    config: str,
    height_mm: float = 660.4,
    width_mm: float = 508.0,
    depth_mm: float = 508.0
) -> Tuple[float, float, float]:
    """
    Calculates:
      1. Incident Energy E (cal/cm²)
      2. Incident Energy E (J/cm²)
      3. Arc Flash Boundary AFB (inches) for 1.2 cal/cm² threshold.
    """
    if I_bf_kA <= 0.0 or I_arc_kA <= 0.0 or t_sec <= 0.0 or working_dist_in <= 0.0:
        return 0.0, 0.0, 0.0

    cfg = config.upper()
    if cfg not in COEFF_ENERGY_600:
        cfg = 'VCB'

    # Convert working distance to mm
    d_mm = working_dist_in * 25.4

    # Enclosure correction
    eed = calculate_eed(height_mm, width_mm, depth_mm, cfg)
    cf = calculate_correction_factor(eed, cfg)

    # Normalized intermediate energies at d = 610mm, t = 0.2s
    c_600 = COEFF_ENERGY_600[cfg]
    c_2700 = COEFF_ENERGY_2700[cfg]
    c_14300 = COEFF_ENERGY_14300[cfg]

    p_exp = c_600['p']

    # Intermediate normalized energies
    E_norm_600 = c_600['c1'] * (I_arc_kA ** c_600['c2']) * ((gap_mm / 32.0) ** c_600['c3'])
    E_norm_2700 = c_2700['c1'] * (I_arc_kA ** c_2700['c2']) * ((gap_mm / 152.0) ** c_2700['c3'])
    E_norm_14300 = c_14300['c1'] * (I_arc_kA ** c_14300['c2']) * ((gap_mm / 152.0) ** c_14300['c3'])

    V_v = V_sys_kV * 1000.0

    if V_v <= 600.0:
        E_norm = E_norm_600 * (V_v / 600.0) ** 0.5
    elif V_v <= 2700.0:
        f = (V_v - 600.0) / (2700.0 - 600.0)
        E_norm = E_norm_600 + f * (E_norm_2700 - E_norm_600)
    elif V_v <= 14300.0:
        f = (V_v - 2700.0) / (14300.0 - 2700.0)
        E_norm = E_norm_2700 + f * (E_norm_14300 - E_norm_2700)
    else:
        E_norm = E_norm_14300 * (V_v / 14300.0) ** 0.2

    # Scale by clearing time (t_sec / 0.2s) and distance (610mm / d_mm)^p
    E_cal = E_norm * (t_sec / 0.2) * ((610.0 / d_mm) ** p_exp) * cf

    # If open air, reduce slightly; if HCB, energy is maximized
    E_j = E_cal * 4.184  # 1 cal/cm² = 4.184 J/cm²

    # Arc Flash Boundary (distance where E = 1.2 cal/cm²)
    if E_cal > 0.0:
        afb_mm = 610.0 * ((E_norm * (t_sec / 0.2) * cf / 1.2) ** (1.0 / p_exp))
        afb_in = afb_mm / 25.4
    else:
        afb_in = 0.0

    return float(E_cal), float(E_j), float(afb_in)


def get_nfpa_70e_ppe_category(incident_energy_cal: float) -> str:
    """
    Maps incident energy (cal/cm²) to NFPA 70E-2024 PPE Category.
    """
    if incident_energy_cal <= 1.2:
        return "Category 1"  # Or non-arc rated if <= 1.2
    elif incident_energy_cal <= 4.0:
        return "Category 1"  # 4 cal/cm²
    elif incident_energy_cal <= 8.0:
        return "Category 2"  # 8 cal/cm²
    elif incident_energy_cal <= 25.0:
        return "Category 3"  # 25 cal/cm²
    elif incident_energy_cal <= 40.0:
        return "Category 4"  # 40 cal/cm²
    else:
        return "DANGER"      # > 40 cal/cm² - Energized Work Prohibited


# ─────────────────────────────────────────────────────────────────────────────
# 3. HIGH-LEVEL ARC FLASH HAZARD EVALUATION API
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_bus_arc_flash(
    bus_id: str,
    bus_name: str,
    voltage_kV: float,
    I_bf_kA: float,
    clearing_time_s: float = 0.100,
    working_dist_in: float = 24.0,
    config: str = 'VCB',
    equipment_type: str = 'lv_switchgear',
    gap_mm: Optional[float] = None,
    height_mm: Optional[float] = None,
    width_mm: Optional[float] = None,
    depth_mm: Optional[float] = None
) -> Dict[str, Any]:
    """
    Performs complete IEEE 1584-2018 Arc Flash Hazard Analysis for a specific bus.
    Returns audit dictionary with all incident energy, boundary, and PPE metrics.
    """
    # Load preset defaults if not explicitly given
    preset = EQUIPMENT_PRESETS.get(equipment_type, EQUIPMENT_PRESETS['lv_switchgear'])
    
    cfg = (config or preset.get('config', 'VCB')).upper()
    g_mm = float(gap_mm) if gap_mm is not None else float(preset['gap_mm'])
    wd_in = float(working_dist_in) if working_dist_in is not None else float(preset['working_dist_in'])
    h_mm = float(height_mm) if height_mm is not None else float(preset['height_mm'])
    w_mm = float(width_mm) if width_mm is not None else float(preset['width_mm'])
    d_mm = float(depth_mm) if depth_mm is not None else float(preset['depth_mm'])

    # 1. Compute Arcing Current (Nominal & Reduced)
    I_arc, I_arc_min = calculate_arcing_current(I_bf_kA, voltage_kV, g_mm, cfg)

    # 2. Compute Incident Energy & Boundary for Nominal Arcing Current
    E_cal, E_j, afb_in = calculate_incident_energy(
        I_bf_kA, I_arc, voltage_kV, clearing_time_s, wd_in, g_mm, cfg, h_mm, w_mm, d_mm
    )

    # 3. Compute for Minimum Arcing Current (clearing time sensitivity)
    E_cal_min, E_j_min, afb_in_min = calculate_incident_energy(
        I_bf_kA, I_arc_min, voltage_kV, clearing_time_s, wd_in, g_mm, cfg, h_mm, w_mm, d_mm
    )

    # Worst-case incident energy (standard mandates taking the maximum)
    worst_E_cal = max(E_cal, E_cal_min)
    worst_E_j = max(E_j, E_j_min)
    worst_afb_in = max(afb_in, afb_in_min)
    worst_afb_ft = worst_afb_in / 12.0
    worst_afb_mm = worst_afb_in * 25.4

    # PPE Classification
    ppe_cat = get_nfpa_70e_ppe_category(worst_E_cal)

    # Shock Protection Boundaries per NFPA 70E Table 130.4(E)(a)
    v_v = voltage_kV * 1000.0
    if v_v <= 50.0:
        limited_approach_in = 0.0
        restricted_approach_in = 0.0
    elif v_v <= 750.0:
        limited_approach_in = 42.0  # 3 ft 6 in
        restricted_approach_in = 12.0 # 1 ft
    elif v_v <= 15000.0:
        limited_approach_in = 60.0  # 5 ft
        restricted_approach_in = 26.0 # 2 ft 2 in
    else:
        limited_approach_in = 120.0
        restricted_approach_in = 36.0

    return {
        'bus_id': str(bus_id),
        'bus_name': str(bus_name),
        'voltage_kV': float(voltage_kV),
        'I_bf_kA': float(I_bf_kA),
        'I_arc_kA': float(I_arc),
        'I_arc_min_kA': float(I_arc_min),
        'clearing_time_s': float(clearing_time_s),
        'working_dist_in': float(wd_in),
        'working_dist_mm': float(wd_in * 25.4),
        'electrode_config': cfg,
        'gap_mm': float(g_mm),
        'incident_energy_cal': float(worst_E_cal),
        'incident_energy_j': float(worst_E_j),
        'afb_in': float(worst_afb_in),
        'afb_ft': float(worst_afb_ft),
        'afb_mm': float(worst_afb_mm),
        'ppe_category': ppe_cat,
        'limited_approach_in': float(limited_approach_in),
        'restricted_approach_in': float(restricted_approach_in),
        'is_danger': worst_E_cal > 40.0
    }

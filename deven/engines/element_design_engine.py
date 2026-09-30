"""
=============================================================================
  DevEN (Develop Electric Network) - Element Design & Conductor Sizing Engine
=============================================================================
  Standards Compliant:
    - ANSI / NEC (NFPA 70, National Electrical Code Table 310.16 & 310.15)
    - IEEE 3001.11 (Recommended Practice for Application of Power Cables)
    - IEEE 399 (Brown Book - Industrial and Commercial Power Systems Analysis)
    - IEC 60364-5-52 (Low-voltage electrical installations - Wiring systems)
    - IEC 60287 (Electric cables - Calculation of the current rating)
    - IEC 60949 & IEC 60364-5-54 (Calculation of thermally permissible short-circuit currents)

  Core Design Capabilities:
    1. Continuous Ampacity & Derating Calculus:
       - Ambient temperature correction (k_temp)
       - Bundling / conduit fill / grouping derating (k_group)
       - Continuous load 125% safety factor (NEC 215.2 / 210.19)
    2. Steady-State Voltage Drop Analysis:
       - Precise AC resistance (skin & proximity effect) and reactance
       - Phase-to-phase and phase-to-neutral drop with power factor cos(phi)
       - Standard limits: <= 3% branch/feeder, <= 5% total system
    3. Short-Circuit Thermal Withstand (Fault Adiabatic Withstand):
       - IEC Adiabatic Equation: S_min = (I_sc * sqrt(t)) / k
       - ANSI / Onderdonk / ICEA Equation for Copper and Aluminum
       - Prevents conductor annealing and insulation melting during fault clearing time
    4. Auto-Sizing Engine:
       - Determines governing criterion (Ampacity vs. Voltage Drop vs. Short Circuit)
       - Selects optimal standard AWG/kcmil or mm² size with full engineering audit sheet
=============================================================================
"""

import math
import numpy as np

# ─────────────────────────────────────────────────────────────────────────────
# 1. CONDUCTOR SPECIFICATION TABLES (NEC / AWG / kcmil)
# ─────────────────────────────────────────────────────────────────────────────

# NEC Table 310.16 Base Ampacities (Copper & Aluminum in raceway/cable at 30°C ambient)
# Keys: AWG/kcmil string -> dict with:
#   area_cmil: Circular Mils
#   area_mm2: Cross-sectional area in mm²
#   cu_60, cu_75, cu_90: Copper ampacity (Amps) for 60°C, 75°C, 90°C insulation
#   al_60, al_75, al_90: Aluminum ampacity (Amps) for 60°C, 75°C, 90°C insulation
#   r_ac_cu: AC resistance in Ohm/km (at 75°C in steel/PVC conduit, 60Hz)
#   x_ac: 60Hz reactance in Ohm/km (conduit)
NEC_CONDUCTOR_TABLE = {
    '14 AWG':   {'cmil': 4110,    'mm2': 2.08,  'cu_60': 15,  'cu_75': 20,  'cu_90': 25,  'al_60': 0,   'al_75': 0,   'al_90': 0,   'r_cu': 10.17, 'x': 0.190},
    '12 AWG':   {'cmil': 6530,    'mm2': 3.31,  'cu_60': 20,  'cu_75': 25,  'cu_90': 30,  'al_60': 15,  'al_75': 20,  'al_90': 25,  'r_cu': 6.56,  'x': 0.177},
    '10 AWG':   {'cmil': 10380,   'mm2': 5.26,  'cu_60': 30,  'cu_75': 35,  'cu_90': 40,  'al_60': 25,  'al_75': 30,  'al_90': 35,  'r_cu': 3.94,  'x': 0.164},
    '8 AWG':    {'cmil': 16510,   'mm2': 8.37,  'cu_60': 40,  'cu_75': 50,  'cu_90': 55,  'al_60': 35,  'al_75': 40,  'al_90': 45,  'r_cu': 2.56,  'x': 0.171},
    '6 AWG':    {'cmil': 26240,   'mm2': 13.30, 'cu_60': 55,  'cu_75': 65,  'cu_90': 75,  'al_60': 40,  'al_75': 50,  'al_90': 60,  'r_cu': 1.61,  'x': 0.167},
    '4 AWG':    {'cmil': 41740,   'mm2': 21.15, 'cu_60': 70,  'cu_75': 85,  'cu_90': 95,  'al_60': 55,  'al_75': 65,  'al_90': 75,  'r_cu': 1.02,  'x': 0.157},
    '3 AWG':    {'cmil': 52620,   'mm2': 26.66, 'cu_60': 85,  'cu_75': 100, 'cu_90': 115, 'al_60': 65,  'al_75': 75,  'al_90': 85,  'r_cu': 0.82,  'x': 0.154},
    '2 AWG':    {'cmil': 66360,   'mm2': 33.62, 'cu_60': 95,  'cu_75': 115, 'cu_90': 130, 'al_60': 75,  'al_75': 90,  'al_90': 100, 'r_cu': 0.62,  'x': 0.148},
    '1 AWG':    {'cmil': 83690,   'mm2': 42.41, 'cu_60': 110, 'cu_75': 130, 'cu_90': 145, 'al_60': 85,  'al_75': 100, 'al_90': 115, 'r_cu': 0.49,  'x': 0.151},
    '1/0 AWG':  {'cmil': 105600,  'mm2': 53.49, 'cu_60': 125, 'cu_75': 150, 'cu_90': 170, 'al_60': 100, 'al_75': 120, 'al_90': 135, 'r_cu': 0.39,  'x': 0.144},
    '2/0 AWG':  {'cmil': 133100,  'mm2': 67.43, 'cu_60': 145, 'cu_75': 175, 'cu_90': 195, 'al_60': 115, 'al_75': 135, 'al_90': 150, 'r_cu': 0.33,  'x': 0.141},
    '3/0 AWG':  {'cmil': 167800,  'mm2': 85.01, 'cu_60': 165, 'cu_75': 200, 'cu_90': 225, 'al_60': 130, 'al_75': 155, 'al_90': 175, 'r_cu': 0.25,  'x': 0.138},
    '4/0 AWG':  {'cmil': 211600,  'mm2': 107.2, 'cu_60': 195, 'cu_75': 230, 'cu_90': 260, 'al_60': 150, 'al_75': 180, 'al_90': 205, 'r_cu': 0.20,  'x': 0.135},
    '250 kcmil':{'cmil': 250000,  'mm2': 126.7, 'cu_60': 215, 'cu_75': 255, 'cu_90': 290, 'al_60': 170, 'al_75': 205, 'al_90': 230, 'r_cu': 0.17,  'x': 0.135},
    '300 kcmil':{'cmil': 300000,  'mm2': 152.0, 'cu_60': 240, 'cu_75': 285, 'cu_90': 320, 'al_60': 195, 'al_75': 230, 'al_90': 260, 'r_cu': 0.14,  'x': 0.135},
    '350 kcmil':{'cmil': 350000,  'mm2': 177.3, 'cu_60': 260, 'cu_75': 310, 'cu_90': 350, 'al_60': 210, 'al_75': 250, 'al_90': 280, 'r_cu': 0.12,  'x': 0.131},
    '400 kcmil':{'cmil': 400000,  'mm2': 202.7, 'cu_60': 280, 'cu_75': 335, 'cu_90': 380, 'al_60': 225, 'al_75': 270, 'al_90': 305, 'r_cu': 0.11,  'x': 0.131},
    '500 kcmil':{'cmil': 500000,  'mm2': 253.4, 'cu_60': 320, 'cu_75': 380, 'cu_90': 430, 'al_60': 260, 'al_75': 310, 'al_90': 350, 'r_cu': 0.089, 'x': 0.128},
    '600 kcmil':{'cmil': 600000,  'mm2': 304.0, 'cu_60': 350, 'cu_75': 420, 'cu_90': 475, 'al_60': 285, 'al_75': 340, 'al_90': 385, 'r_cu': 0.075, 'x': 0.128},
    '750 kcmil':{'cmil': 750000,  'mm2': 380.0, 'cu_60': 400, 'cu_75': 475, 'cu_90': 535, 'al_60': 320, 'al_75': 385, 'al_90': 435, 'r_cu': 0.062, 'x': 0.125},
    '1000 kcmil':{'cmil': 1000000,'mm2': 506.7, 'cu_60': 455, 'cu_75': 545, 'cu_90': 615, 'al_60': 375, 'al_75': 445, 'al_90': 500, 'r_cu': 0.049, 'x': 0.121},
}

# ─────────────────────────────────────────────────────────────────────────────
# 2. CONDUCTOR SPECIFICATION TABLES (IEC 60364-5-52 / Metric)
# ─────────────────────────────────────────────────────────────────────────────

# IEC 60364-5-52 Table B.52.4 & B.52.5 (Three loaded conductors, Ambient 30°C in air)
# Keys: mm² string -> dict with:
#   area_mm2: Area in mm²
#   cu_pvc_70: Copper PVC 70°C ampacity (Method C - on tray / wall)
#   cu_xlpe_90: Copper XLPE 90°C ampacity (Method C - on tray / wall)
#   al_pvc_70: Aluminum PVC 70°C ampacity
#   al_xlpe_90: Aluminum XLPE 90°C ampacity
#   r_cu: AC resistance in Ohm/km at 70°C / 90°C
#   x_ac: 50Hz reactance in Ohm/km
IEC_CONDUCTOR_TABLE = {
    '1.5 mm²':  {'mm2': 1.5,  'cu_pvc': 19.5, 'cu_xlpe': 26,   'al_pvc': 0,    'al_xlpe': 0,    'r_cu': 14.8,  'x': 0.115},
    '2.5 mm²':  {'mm2': 2.5,  'cu_pvc': 27,   'cu_xlpe': 36,   'al_pvc': 0,    'al_xlpe': 0,    'r_cu': 8.87,  'x': 0.109},
    '4 mm²':    {'mm2': 4.0,  'cu_pvc': 36,   'cu_xlpe': 49,   'al_pvc': 28,   'al_xlpe': 38,   'r_cu': 5.52,  'x': 0.107},
    '6 mm²':    {'mm2': 6.0,  'cu_pvc': 46,   'cu_xlpe': 63,   'al_pvc': 36,   'al_xlpe': 49,   'r_cu': 3.69,  'x': 0.100},
    '10 mm²':   {'mm2': 10.0, 'cu_pvc': 63,   'cu_xlpe': 86,   'al_pvc': 49,   'al_xlpe': 67,   'r_cu': 2.19,  'x': 0.094},
    '16 mm²':   {'mm2': 16.0, 'cu_pvc': 85,   'cu_xlpe': 115,  'al_pvc': 66,   'al_xlpe': 89,   'r_cu': 1.38,  'x': 0.090},
    '25 mm²':   {'mm2': 25.0, 'cu_pvc': 112,  'cu_xlpe': 149,  'al_pvc': 83,   'al_xlpe': 115,  'r_cu': 0.87,  'x': 0.086},
    '35 mm²':   {'mm2': 35.0, 'cu_pvc': 138,  'cu_xlpe': 185,  'al_pvc': 103,  'al_xlpe': 143,  'r_cu': 0.627, 'x': 0.084},
    '50 mm²':   {'mm2': 50.0, 'cu_pvc': 168,  'cu_xlpe': 225,  'al_pvc': 125,  'al_xlpe': 174,  'r_cu': 0.493, 'x': 0.083},
    '70 mm²':   {'mm2': 70.0, 'cu_pvc': 213,  'cu_xlpe': 289,  'al_pvc': 160,  'al_xlpe': 225,  'r_cu': 0.342, 'x': 0.082},
    '95 mm²':   {'mm2': 95.0, 'cu_pvc': 258,  'cu_xlpe': 352,  'al_pvc': 195,  'al_xlpe': 275,  'r_cu': 0.247, 'x': 0.081},
    '120 mm²':  {'mm2': 120.0,'cu_pvc': 299,  'cu_xlpe': 410,  'al_pvc': 226,  'al_xlpe': 321,  'r_cu': 0.196, 'x': 0.080},
    '150 mm²':  {'mm2': 150.0,'cu_pvc': 344,  'cu_xlpe': 473,  'al_pvc': 261,  'al_xlpe': 372,  'r_cu': 0.159, 'x': 0.080},
    '185 mm²':  {'mm2': 185.0,'cu_pvc': 392,  'cu_xlpe': 542,  'al_pvc': 298,  'al_xlpe': 427,  'r_cu': 0.128, 'x': 0.080},
    '240 mm²':  {'mm2': 240.0,'cu_pvc': 461,  'cu_xlpe': 641,  'al_pvc': 352,  'al_xlpe': 507,  'r_cu': 0.098, 'x': 0.079},
    '300 mm²':  {'mm2': 300.0,'cu_pvc': 530,  'cu_xlpe': 741,  'al_pvc': 406,  'al_xlpe': 587,  'r_cu': 0.080, 'x': 0.079},
    '400 mm²':  {'mm2': 400.0,'cu_pvc': 610,  'cu_xlpe': 860,  'al_pvc': 470,  'al_xlpe': 685,  'r_cu': 0.063, 'x': 0.078},
    '500 mm²':  {'mm2': 500.0,'cu_pvc': 690,  'cu_xlpe': 980,  'al_pvc': 535,  'al_xlpe': 785,  'r_cu': 0.051, 'x': 0.078},
    '630 mm²':  {'mm2': 630.0,'cu_pvc': 780,  'cu_xlpe': 1110, 'al_pvc': 610,  'al_xlpe': 895,  'r_cu': 0.041, 'x': 0.077},
}

# ─────────────────────────────────────────────────────────────────────────────
# 3. DERATING FACTOR COMPUTATION FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def get_nec_temperature_correction(ambient_temp_c, insulation_rating_c=90):
    """
    NEC Table 310.15(B)(1) Ambient Temperature Correction Factors (Based on 30°C).
    Formula: sqrt((T_rating - T_amb) / (T_rating - 30))
    """
    t_amb = float(ambient_temp_c)
    t_rat = float(insulation_rating_c)
    if t_amb >= t_rat:
        return 0.0
    return max(0.0, math.sqrt((t_rat - t_amb) / max(t_rat - 30.0, 1.0)))


def get_nec_bundling_adjustment(num_current_carrying_conductors):
    """
    NEC Table 310.15(C)(1) Adjustment Factors for More Than Three Current-Carrying Conductors.
    """
    n = int(num_current_carrying_conductors)
    if n <= 3:
        return 1.00
    elif 4 <= n <= 6:
        return 0.80
    elif 7 <= n <= 9:
        return 0.70
    elif 10 <= n <= 20:
        return 0.50
    elif 21 <= n <= 30:
        return 0.45
    elif 31 <= n <= 40:
        return 0.40
    else:
        return 0.35


def get_iec_temperature_correction(ambient_temp_c, insulation_type='XLPE'):
    """
    IEC 60364-5-52 Table B.52.14 Ambient Temperature Derating Factors (Base 30°C in air).
    """
    t_amb = float(ambient_temp_c)
    is_xlpe = 'xlpe' in str(insulation_type).lower() or 'epr' in str(insulation_type).lower()
    t_rat = 90.0 if is_xlpe else 70.0
    if t_amb >= t_rat:
        return 0.0
    return max(0.0, math.sqrt((t_rat - t_amb) / (t_rat - 30.0)))


def get_iec_grouping_factor(num_circuits, installation_type='tray'):
    """
    IEC 60364-5-52 Table B.52.17 Grouping Derating Factors.
    """
    n = max(int(num_circuits), 1)
    if n == 1:
        return 1.00
    elif n == 2:
        return 0.80
    elif n == 3:
        return 0.70
    elif n == 4:
        return 0.65
    elif n == 5:
        return 0.60
    elif n == 6:
        return 0.57
    elif 7 <= n <= 8:
        return 0.52
    elif 9 <= n <= 11:
        return 0.48
    elif 12 <= n <= 15:
        return 0.45
    elif 16 <= n <= 19:
        return 0.41
    else:
        return 0.38


# ─────────────────────────────────────────────────────────────────────────────
# 4. VOLTAGE DROP CALCULATIONS
# ─────────────────────────────────────────────────────────────────────────────

def calculate_voltage_drop(current_a, length_m, r_ohm_per_km, x_ohm_per_km,
                           voltage_v, power_factor=0.85, phases=3):
    """
    Calculates steady-state voltage drop (Volts and %).
    Formula for 3-Phase: Delta_V = sqrt(3) * I * L * (R*cos(phi) + X*sin(phi))
    Formula for 1-Phase: Delta_V = 2 * I * L * (R*cos(phi) + X*sin(phi))
    """
    i = float(current_a)
    l_km = float(length_m) / 1000.0
    v = float(voltage_v)
    pf = float(power_factor)
    sin_phi = math.sqrt(max(0.0, 1.0 - (pf ** 2)))

    r_total = float(r_ohm_per_km) * l_km
    x_total = float(x_ohm_per_km) * l_km
    z_eff = (r_total * pf) + (x_total * sin_phi)

    mult = math.sqrt(3.0) if phases == 3 else 2.0
    delta_v = mult * i * z_eff
    v_drop_pct = (delta_v / max(v, 1.0)) * 100.0

    return {
        'delta_v_volts': float(delta_v),
        'v_drop_pct': float(v_drop_pct),
        'v_receiving': float(v - delta_v),
        'r_line_ohms': float(r_total),
        'x_line_ohms': float(x_total),
        'z_eff_ohms': float(z_eff)
    }


# ─────────────────────────────────────────────────────────────────────────────
# 5. SHORT-CIRCUIT THERMAL WITHSTAND (ADIABATIC WITHSTAND)
# ─────────────────────────────────────────────────────────────────────────────

def calculate_short_circuit_withstand(fault_kA, clearing_time_s, material='copper',
                                      insulation='XLPE', standard='IEC'):
    """
    Calculates the minimum required cross-sectional area (mm² and kcmil)
    to withstand the short-circuit current without insulation damage.

    IEC Formula (IEC 60364-5-54 / IEC 60949):
        S_min = (I_sc * sqrt(t)) / k
        where k:
          - Copper/XLPE (90°C -> 250°C): k = 143
          - Copper/PVC  (70°C -> 160°C): k = 115
          - Al/XLPE     (90°C -> 250°C): k = 95
          - Al/PVC      (70°C -> 160°C): k = 76

    ANSI / ICEA / Onderdonk Formula:
        A_cmil = I_sc * sqrt(t) / sqrt(K * log10((T2 + 234.5)/(T1 + 234.5)))
    """
    i_sc_amps = float(fault_kA) * 1000.0
    t_sec = max(float(clearing_time_s), 0.01)
    is_cu = 'cu' in str(material).lower() or 'copper' in str(material).lower()
    is_xlpe = 'xlpe' in str(insulation).lower() or 'epr' in str(insulation).lower() or '90' in str(insulation)

    if str(standard).upper() == 'ANSI':
        # ANSI / Onderdonk constants
        k_factor = 0.0297 if is_cu else 0.0125
        t1 = 90.0 if is_xlpe else 75.0
        t2 = 250.0 if is_xlpe else 160.0
        c_val = 234.5 if is_cu else 228.1
        log_term = math.log10((t2 + c_val) / (t1 + c_val))
        denom = math.sqrt(k_factor * log_term)
        req_cmil = (i_sc_amps * math.sqrt(t_sec)) / max(denom, 1e-4)
        req_mm2 = req_cmil / 1973.525
        k_used = denom * 1973.525
    else:
        # IEC 60364-5-54 k factor
        if is_cu and is_xlpe:
            k_used = 143.0
        elif is_cu and not is_xlpe:
            k_used = 115.0
        elif not is_cu and is_xlpe:
            k_used = 95.0
        else:
            k_used = 76.0

        req_mm2 = (i_sc_amps * math.sqrt(t_sec)) / k_used
        req_cmil = req_mm2 * 1973.525

    return {
        'req_mm2': float(req_mm2),
        'req_cmil': float(req_cmil),
        'k_factor': float(k_used),
        'i_sc_kA': float(fault_kA),
        'clearing_time_s': float(t_sec)
    }


# ─────────────────────────────────────────────────────────────────────────────
# 6. UNIVERSAL CONDUCTOR AUTO-SIZING & AUDIT ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def size_conductor(load_current_a, voltage_v, length_m, fault_kA=10.0,
                   clearing_time_s=0.1, power_factor=0.85, phases=3,
                   material='copper', insulation='XLPE_90C',
                   standard='ANSI', ambient_temp_c=30.0,
                   num_conductors=3, max_vdrop_pct=3.0,
                   is_continuous=True):
    """
    Performs complete 3-criterion conductor sizing satisfying:
      1. Continuous Ampacity (with thermal & grouping derating)
      2. Steady-State Voltage Drop (<= max_vdrop_pct)
      3. Short-Circuit Thermal Withstand (adiabatic limit)
    Returns complete engineering report, sizing breakdown, and governing criterion.
    """
    std = str(standard).upper()
    is_ansi = ('ANSI' in std) or ('NEC' in std)
    is_cu = ('cu' in str(material).lower()) or ('copper' in str(material).lower())
    mat_label = "Copper (Cu)" if is_cu else "Aluminum (Al)"

    is_90c = ('90' in str(insulation)) or ('xlpe' in str(insulation).lower())
    ins_label = "XLPE / THHN (90°C)" if is_90c else "PVC / THWN (75°C)"

    # 1. Determine Derating Factors
    if is_ansi:
        k_temp = get_nec_temperature_correction(ambient_temp_c, 90 if is_90c else 75)
        k_adj = get_nec_bundling_adjustment(num_conductors)
        cont_factor = 1.25 if is_continuous else 1.00
        design_load_a = float(load_current_a) * cont_factor
        table = NEC_CONDUCTOR_TABLE
    else:
        k_temp = get_iec_temperature_correction(ambient_temp_c, 'XLPE' if is_90c else 'PVC')
        k_adj = get_iec_grouping_factor(num_conductors)
        cont_factor = 1.00
        design_load_a = float(load_current_a)
        table = IEC_CONDUCTOR_TABLE

    total_derate = max(k_temp * k_adj, 0.05)
    req_table_ampacity = design_load_a / total_derate

    # 2. Short Circuit Thermal Withstand Area Requirement
    sc_res = calculate_short_circuit_withstand(
        fault_kA=fault_kA, clearing_time_s=clearing_time_s,
        material='copper' if is_cu else 'aluminum',
        insulation='XLPE' if is_90c else 'PVC',
        standard='ANSI' if is_ansi else 'IEC'
    )
    req_sc_mm2 = sc_res['req_mm2']

    # 3. Iterate through standard conductor sizes
    best_candidate = None
    pass_candidates = []

    for name, cinfo in table.items():
        # Get base ampacity from table
        if is_ansi:
            col_key = f"{'cu' if is_cu else 'al'}_{'90' if is_90c else '75'}"
            base_amp = float(cinfo.get(col_key, 0.0))
        else:
            col_key = f"{'cu' if is_cu else 'al'}_{'xlpe' if is_90c else 'pvc'}"
            base_amp = float(cinfo.get(col_key, 0.0))

        if base_amp <= 0.0:
            continue

        derated_amp = base_amp * total_derate
        amp_pass = derated_amp >= float(load_current_a) * cont_factor

        # Resistance and reactance
        r_ac = float(cinfo.get('r_cu', 1.0)) * (1.0 if is_cu else 1.64)
        x_ac = float(cinfo.get('x', 0.1))

        # Voltage drop
        vd_res = calculate_voltage_drop(
            current_a=load_current_a, length_m=length_m,
            r_ohm_per_km=r_ac, x_ohm_per_km=x_ac,
            voltage_v=voltage_v, power_factor=power_factor, phases=phases
        )
        vd_pass = vd_res['v_drop_pct'] <= float(max_vdrop_pct)

        # Short circuit withstand
        area_mm2 = float(cinfo['mm2'])
        sc_pass = area_mm2 >= req_sc_mm2

        status_all = amp_pass and vd_pass and sc_pass
        cand = {
            'name': name,
            'area_mm2': area_mm2,
            'base_amp': base_amp,
            'derated_amp': derated_amp,
            'amp_pass': amp_pass,
            'amp_margin_pct': float((derated_amp - load_current_a) / max(derated_amp, 1.0) * 100.0),
            'vdrop_pct': vd_res['v_drop_pct'],
            'vdrop_volts': vd_res['delta_v_volts'],
            'vdrop_pass': vd_pass,
            'sc_req_mm2': req_sc_mm2,
            'sc_pass': sc_pass,
            'sc_margin_pct': float((area_mm2 - req_sc_mm2) / max(area_mm2, 1e-4) * 100.0),
            'all_pass': status_all,
            'r_ohm_per_km': r_ac,
            'x_ohm_per_km': x_ac
        }
        if status_all:
            pass_candidates.append(cand)
            if best_candidate is None:
                best_candidate = cand

    if best_candidate is None:
        # Fallback to largest available
        best_candidate = list(table.keys())[-1]
        best_cand_name = best_candidate
        best_candidate = {
            'name': best_cand_name,
            'area_mm2': float(table[best_cand_name]['mm2']),
            'derated_amp': 0.0,
            'amp_pass': False,
            'vdrop_pct': 99.0,
            'vdrop_volts': 0.0,
            'vdrop_pass': False,
            'sc_pass': False,
            'all_pass': False,
            'amp_margin_pct': -100.0,
            'sc_margin_pct': -100.0,
            'sc_req_mm2': req_sc_mm2,
            'base_amp': 0.0,
            'r_ohm_per_km': 1.0,
            'x_ohm_per_km': 0.1
        }

    # Determine Governing Design Criterion
    # Find minimum size for each criterion individually
    min_amp_cand = next((c for c in table.items() if (c[1].get(f"{'cu' if is_cu else 'al'}_{'90' if is_90c else '75' if is_ansi else 'xlpe' if is_90c else 'pvc'}", 0) * total_derate) >= float(load_current_a) * cont_factor), None)
    min_sc_cand = next((c for c in table.items() if float(c[1]['mm2']) >= req_sc_mm2), None)

    gov_reasons = []
    if min_amp_cand and min_amp_cand[0] == best_candidate['name']:
        gov_reasons.append("Continuous Thermal Ampacity (Load Current + Derating)")
    if min_sc_cand and min_sc_cand[0] == best_candidate['name']:
        gov_reasons.append("Short-Circuit Thermal Withstand (Fault Energy)")
    if best_candidate['vdrop_pct'] >= max_vdrop_pct * 0.85:
        gov_reasons.append(f"Voltage Drop Constraint (<= {max_vdrop_pct:.1f}%)")
    if not gov_reasons:
        gov_reasons.append("Combined Thermal and Voltage Drop Optimum")

    gov_criterion = " & ".join(gov_reasons)

    # 4. Generate Comprehensive Audit Sheet Report
    report = []
    report.append("=========================================================================================")
    report.append(f"          DevEN CONDUCTOR SIZING & ELEMENT DESIGN REPORT ({std})                         ")
    report.append("=========================================================================================")
    report.append(f"Standard Used:          {('ANSI / NEC (NFPA 70 & IEEE 3001.11)' if is_ansi else 'IEC 60364-5-52 & IEC 60949')}")
    report.append(f"Conductor Material:     {mat_label}")
    report.append(f"Insulation Rating:      {ins_label}")
    report.append(f"System Voltage:         {voltage_v:.1f} V ({phases}-Phase, 60 Hz)" if is_ansi else f"System Voltage:         {voltage_v:.1f} V ({phases}-Phase, 50 Hz)")
    report.append(f"Circuit Route Length:   {length_m:.1f} m ({length_m * 3.28084:.1f} ft)")
    report.append(f"Continuous Load Current:{load_current_a:.2f} A (Power Factor = {power_factor:.2f})")
    if is_ansi and is_continuous:
        report.append(f"NEC Continuous Factor:  125% -> Design Current = {design_load_a:.2f} A")
    report.append(f"Ambient Temperature:    {ambient_temp_c:.1f}°C (k_temp = {k_temp:.3f})")
    report.append(f"Conductor Grouping:     {num_conductors} current-carrying conductors (k_group = {k_adj:.3f})")
    report.append(f"Total Derating Factor:  {total_derate:.3f} ({total_derate*100.0:.1f}% capacity retained)")
    report.append(f"Fault Level at Bus:     {fault_kA:.2f} kA rms  (Clearing Time: {clearing_time_s:.3f} s)")
    report.append(f"Max Voltage Drop Limit: {max_vdrop_pct:.1f}%")
    report.append("-----------------------------------------------------------------------------------------")
    report.append(f"🎯 OPTIMAL SIZED CONDUCTOR:   {best_candidate['name']} ({best_candidate['area_mm2']:.1f} mm²)")
    report.append(f"   Governing Criterion:       {gov_criterion}")
    report.append("-----------------------------------------------------------------------------------------")
    report.append("📋 THREE CRITERIA AUDIT VERIFICATION:")
    report.append(f"  1. CONTINUOUS AMPACITY:")
    report.append(f"     • Base Ampacity (Table):          {best_candidate['base_amp']:.1f} A")
    report.append(f"     • Derated Allowable Ampacity:     {best_candidate['derated_amp']:.1f} A")
    report.append(f"     • Required Design Current:        {design_load_a:.1f} A")
    report.append(f"     • Ampacity Thermal Margin:        {best_candidate['amp_margin_pct']:+.1f}% [{'PASS' if best_candidate['amp_pass'] else 'FAIL'}]")
    report.append("")
    report.append(f"  2. STEADY-STATE VOLTAGE DROP:")
    report.append(f"     • Calculated Voltage Drop:        {best_candidate['vdrop_volts']:.2f} V ({best_candidate['vdrop_pct']:.2f}%)")
    report.append(f"     • Allowable Threshold:            <= {max_vdrop_pct:.1f}% ({voltage_v * max_vdrop_pct / 100.0:.2f} V)")
    report.append(f"     • Voltage Margin Remaining:       {max_vdrop_pct - best_candidate['vdrop_pct']:+.2f}% [{'PASS' if best_candidate['vdrop_pass'] else 'FAIL'}]")
    report.append("")
    report.append(f"  3. SHORT-CIRCUIT THERMAL WITHSTAND (ADIABATIC WITHSTAND):")
    report.append(f"     • Minimum Required Area (S_min):  {req_sc_mm2:.2f} mm² ({req_sc_mm2 * 1973.525:.0f} cmil)")
    report.append(f"     • Selected Conductor Area:        {best_candidate['area_mm2']:.2f} mm² ({best_candidate['area_mm2'] * 1973.525:.0f} cmil)")
    report.append(f"     • Thermal Withstand Margin:       {best_candidate['sc_margin_pct']:+.1f}% [{'PASS' if best_candidate['sc_pass'] else 'FAIL'}]")
    report.append("-----------------------------------------------------------------------------------------")
    report.append("💡 ENGINEERING SIZING RECOMMENDATION:")
    if best_candidate['all_pass']:
        report.append(f"  ✓ Standard conductor {best_candidate['name']} safely meets all NEC/IEC thermal, voltage drop,")
        report.append(f"    and short-circuit adiabatic withstand requirements under rated operating conditions.")
    else:
        report.append("  ⚠️ Selected conductor does NOT fully meet all requirements! Consider parallel conductors (runs)")
        report.append("     or stepping up to a larger feeder specification.")
    report.append("=========================================================================================\n")

    return {
        'success': True,
        'standard': std,
        'selected_conductor': best_candidate['name'],
        'area_mm2': best_candidate['area_mm2'],
        'area_cmil': best_candidate['area_mm2'] * 1973.525,
        'base_ampacity_a': best_candidate['base_amp'],
        'derated_ampacity_a': best_candidate['derated_amp'],
        'derating_factor': total_derate,
        'k_temp': k_temp,
        'k_group': k_adj,
        'design_current_a': design_load_a,
        'voltage_drop_pct': best_candidate['vdrop_pct'],
        'voltage_drop_volts': best_candidate['vdrop_volts'],
        'req_sc_mm2': req_sc_mm2,
        'governing_criterion': gov_criterion,
        'all_pass': best_candidate['all_pass'],
        'audit_report': "\n".join(report)
    }

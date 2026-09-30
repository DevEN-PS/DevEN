"""
Standard DAT to DevEN Python (.py) Converter Module
=====================================================
Parses standard DAT0 load flow files and generates native DevEN Python database (.py) files.

Features:
  - Slack bus identification from DAT0 control parameters (Type 3).
  - PV bus identification for buses connected to voltage-controlled generators, wind, solar (Type 2).
  - PQ bus identification for load/passive buses (Type 1).
  - Accurate line and transformer parameters mapping.
  - Wind Generator parsing (mapped as GENERATOR type "WIND").
  - Solar PV parsing (mapped as GENERATOR type "INV").
  - Shunt Reactor parsing (bus-connected → REACTOR_DATA).
  - Shunt Capacitor parsing (bus-connected → CAPACITOR_DATA).
  - FACTS device parsing (SVC/STATCOM → SHUNT_DATA).
  - Automatic saving to same path with .py extension.
"""

import os
import re
import math
from datetime import datetime

def sanitize_and_ensure_unique_names(element_list, category_name):
    """
    Ensures every element in element_list has a non-empty, clean, and 100% unique 'name'.
    Handles buses, generators, loads, lines, transformers, capacitors, reactors, etc.
    """
    used_names = set()
    for idx, item in enumerate(element_list, 1):
        raw_name = item.get('name')
        if not raw_name or not str(raw_name).strip() or str(raw_name).strip().lower() in ('none', 'null', 'nan', '""', "''"):
            # Generate default fallback name based on element type and connections
            if category_name == 'bus':
                bnum = item.get('num') or item.get('bus') or idx
                base_name = f"Bus_{bnum}"
            elif category_name == 'load':
                bnum = item.get('bus', 0)
                lid = item.get('id', idx)
                base_name = f"Load_{bnum}_{lid}"
            elif category_name == 'gen':
                bnum = item.get('bus', 0)
                gid = item.get('id', idx)
                base_name = f"Gen_{bnum}_{gid}"
            elif category_name == 'line':
                fbus = item.get('from_bus', 0)
                tbus = item.get('to_bus', 0)
                base_name = f"Line_{fbus}_{tbus}"
            elif category_name == 'xfmr':
                fbus = item.get('from_bus', 0)
                tbus = item.get('to_bus', 0)
                base_name = f"Xfmr_{fbus}_{tbus}"
            elif category_name == '3wxfmr':
                hbus = item.get('hv_bus', 0)
                mbus = item.get('mv_bus', 0)
                lbus = item.get('lv_bus', 0)
                base_name = f"TW_Xfmr_{hbus}_{mbus}_{lbus}"
            elif category_name == 'cap':
                bnum = item.get('bus', 0)
                base_name = f"Cap_{bnum}_{idx}"
            elif category_name == 'reactor':
                bnum = item.get('bus', 0)
                base_name = f"Reactor_{bnum}_{idx}"
            elif category_name == 'shunt':
                bnum = item.get('bus', 0)
                base_name = f"Shunt_{bnum}_{idx}"
            elif category_name == 'hvdc':
                fbus = item.get('from_bus', 0)
                tbus = item.get('to_bus', 0)
                base_name = f"HVDC_{fbus}_{tbus}_{idx}"
            else:
                base_name = f"{category_name.capitalize()}_{idx}"
        else:
            base_name = str(raw_name).strip().replace('"', '').replace("'", "")

        # Enforce 100% Uniqueness
        unique_name = base_name
        counter = 2
        while unique_name in used_names:
            unique_name = f"{base_name}_{counter}"
            counter += 1

        used_names.add(unique_name)
        item['name'] = unique_name


def parse_dat0(file_path):
    """Parses a standard .dat0 / .dat input file into raw dictionary components."""

    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
        
    section = None
    base_mva = 100.0
    slack_bus_id = None
    
    buses = {}
    generators = []
    loads = []
    lines_data = []
    transformers = []
    shunt_reactors = []
    shunt_capacitors = []
    shunt_facts = []
    converters_raw = {}
    dc_links_raw = []
    pending_conv = None

    # Solar PV count line tracking
    solar_count_expected = 0
    
    i = 0
    while i < len(lines):
        raw_line = lines[i]
        i += 1
        line = raw_line.strip()
        if not line:
            continue
            
        if line.startswith('%'):
            l_lower = line.lower()
            # --- Major data sections ---
            if 'bus data' in l_lower and 'frequency' not in l_lower:
                section = 'BUS'
            elif 'two winding' in l_lower:
                section = 'XFMR'
            elif 'transmission line' in l_lower:
                section = 'LINE'
            elif 'generator data' in l_lower and 'frequency' not in l_lower and 'wind' not in l_lower:
                section = 'GEN'
            elif 'wind generator data' in l_lower:
                section = 'WIND_GEN'
            elif 'solar pv simple model data' in l_lower:
                section = 'SOLAR'
            elif 'no of solar pv simple' in l_lower:
                section = 'SOLAR_COUNT'
            elif 'load data' in l_lower and 'characteristic' not in l_lower:
                section = 'LOAD'
            elif 'synchronous motor' in l_lower:
                section = 'SYNC_MOTOR'
            elif 'motor' in l_lower:
                section = 'MOTOR'
            elif 'shunt reactor' in l_lower:
                section = 'SHUNT_REACTOR'
            elif 'shunt capacitor' in l_lower:
                section = 'SHUNT_CAP'
            elif 'shunt fact' in l_lower:
                section = 'SHUNT_FACTS'
            elif 'common control' in l_lower:
                section = 'CTRL_OPT'
            elif 'converter data' in l_lower:
                section = 'CONVERTER'
                pending_conv = None
            elif 'dc link' in l_lower:
                section = 'DC_LINK'
            # --- Sections to skip ---
            elif 'frequency characteristics' in l_lower:
                section = None
            elif 'slack bus angle' in l_lower:
                section = None
            elif 'load characteristic' in l_lower:
                section = None
            elif 'no of solar pv detailed' in l_lower:
                section = None
            continue
            
        tokens = line.split()

        # ---- CONTROL OPTIONS ----
        if section == 'CTRL_OPT':
            try:
                if len(tokens) >= 10:
                    base_mva = float(tokens[5])
                    slack_bus_id = int(tokens[9])
                    section = None
                    continue
            except Exception:
                pass
                
        # ---- BUS DATA ----
        elif section == 'BUS':
            if len(tokens) >= 8:
                try:
                    bid = int(tokens[0])
                    area_no = int(tokens[1])
                    zone_no = int(tokens[2])
                    base_kv = float(tokens[4])
                    min_v = float(tokens[5]) if len(tokens) > 5 else 0.95
                    max_v = float(tokens[6]) if len(tokens) > 6 else 1.05
                    name = tokens[7] if len(tokens) > 7 else f"Bus_{bid}"
                    buses[bid] = {
                        'num': bid, 'name': name, 'type': 1, 'base_kV': base_kv,
                        'V_init': 1.0, 'angle_init': 0.0, 'min_v': min_v, 'max_v': max_v,
                        'area': area_no, 'zone': zone_no
                    }
                except ValueError:
                    pass
                    
        # ---- TRANSFORMER DATA (2-line format) ----
        elif section == 'XFMR':
            if len(tokens) >= 8:
                try:
                    status = 1 if int(tokens[0]) in (1, 3) else 0
                    f_bus = int(tokens[2])
                    t_bus = int(tokens[3])
                    r_pu = float(tokens[4])
                    x_pu = float(tokens[5])
                    nom_tap = float(tokens[6])
                    mva = float(tokens[7])
                    
                    min_tap, max_tap, tap_step, phase_shift = 0.9, 1.1, 0.025, 0.0
                    if i < len(lines):
                        next_line = lines[i].strip()
                        if next_line and not next_line.startswith('%'):
                            nt_tokens = next_line.split()
                            if len(nt_tokens) >= 4:
                                min_tap = float(nt_tokens[1])
                                max_tap = float(nt_tokens[2])
                                tap_step = float(nt_tokens[3])
                                if len(nt_tokens) >= 5:
                                    phase_shift = float(nt_tokens[4])
                                i += 1
                                
                    transformers.append({
                        'from_bus': f_bus, 'to_bus': t_bus, 'R_pu': r_pu, 'X_pu': x_pu,
                        'tap_ratio': nom_tap, 'rateA': mva, 'phase_shift': phase_shift,
                        'min_tap': min_tap, 'max_tap': max_tap, 'step_size': tap_step,
                        'status': status
                    })
                except ValueError:
                    pass
                    
        # ---- TRANSMISSION LINE DATA ----
        elif section == 'LINE':
            if len(tokens) >= 8:
                try:
                    status = 1 if int(tokens[0]) in (1, 3) else 0
                    f_bus = int(tokens[2])
                    t_bus = int(tokens[3])
                    r_pu = float(tokens[4])
                    x_pu = float(tokens[5])
                    b_half = float(tokens[6])
                    mva = float(tokens[7])
                    kms = float(tokens[8]) if len(tokens) > 8 else 1.0
                    
                    lines_data.append({
                        'from_bus': f_bus, 'to_bus': t_bus, 'length_km': kms,
                        'R_per_km': r_pu / max(kms, 1e-6),
                        'X_per_km': x_pu / max(kms, 1e-6),
                        'B_per_km': (2.0 * b_half) / max(kms, 1e-6),
                        'rateA': mva, 'status': status
                    })
                except ValueError:
                    pass
                    
        # ---- GENERATOR DATA ----
        # Format: Bus SchMW MinMvar MaxMvar SpecVoltage CapCurveNo MVA Status Type
        elif section == 'GEN':
            if len(tokens) >= 5:
                try:
                    gbus = int(tokens[0])
                    if gbus in buses and gbus > 0:
                        p_out = float(tokens[1])
                        q_min = float(tokens[2])
                        q_max = float(tokens[3])
                        v_spec = float(tokens[4])
                        status = 1 if (len(tokens) > 7 and int(tokens[7]) in (1, 3)) else 0
                        bus_type = int(tokens[8]) if len(tokens) > 8 else 1
                        q_out = 0.0
                        
                        generators.append({
                            'bus': gbus, 'P_out': p_out, 'Q_out': q_out, 'V_set': v_spec,
                            'Qmin': q_min, 'Qmax': q_max, 'status': status,
                            'gen_type': 'SYNC', 'bus_type': bus_type
                        })
                except ValueError:
                    pass
                    
        # ---- WIND GENERATOR DATA ----
        # Format same as Generator Data: Bus SchMW MinMvar MaxMvar SpecVoltage CapCurveNo MVA Status Type
        elif section == 'WIND_GEN':
            if len(tokens) >= 5:
                try:
                    gbus = int(tokens[0])
                    if gbus in buses and gbus > 0:
                        p_out = float(tokens[1])
                        q_min = float(tokens[2])
                        q_max = float(tokens[3])
                        v_spec = float(tokens[4])
                        status = 1 if (len(tokens) > 7 and int(tokens[7]) in (1, 3)) else 0
                        bus_type = int(tokens[8]) if len(tokens) > 8 else 1
                        q_out = 0.0
                        
                        generators.append({
                            'bus': gbus, 'P_out': p_out, 'Q_out': q_out, 'V_set': v_spec,
                            'Qmin': q_min, 'Qmax': q_max, 'status': status,
                            'gen_type': 'WIND', 'bus_type': bus_type
                        })
                except ValueError:
                    pass

        # ---- SOLAR PV COUNT (just a number line) ----
        elif section == 'SOLAR_COUNT':
            try:
                solar_count_expected = int(tokens[0])
                section = None  # Done, next section header will set correctly
            except ValueError:
                pass

        # ---- SOLAR PV SIMPLE MODEL DATA ----
        # Format: Status BusNo PlantMVA PSpecified ModeOfOperation PowerFactor pfFlag VSpecified QMin QMax
        elif section == 'SOLAR':
            if len(tokens) >= 4:
                try:
                    status = 1 if int(tokens[0]) in (1, 3) else 0
                    gbus = int(tokens[1])
                    plant_mva = float(tokens[2])
                    p_spec = float(tokens[3])
                    v_spec = float(tokens[7]) if len(tokens) > 7 else 1.0
                    q_min = float(tokens[8]) if len(tokens) > 8 else 0.0
                    q_max = float(tokens[9]) if len(tokens) > 9 else 0.0
                    
                    if gbus in buses and gbus > 0:
                        generators.append({
                            'bus': gbus, 'P_out': p_spec, 'Q_out': 0.0, 'V_set': v_spec,
                            'Qmin': q_min, 'Qmax': q_max, 'status': status,
                            'gen_type': 'INV'
                        })
                except ValueError:
                    pass

        # ---- LOAD DATA ----
        elif section == 'LOAD':
            if len(tokens) >= 3:
                try:
                    lbus = int(tokens[0])
                    p_load = float(tokens[1])
                    q_load = float(tokens[2])
                    
                    loads.append({
                        'bus': lbus, 'P_demand': p_load, 'Q_demand': q_load, 'model': 'constant_PQ'
                    })
                except ValueError:
                    pass

        # ---- SYNCHRONOUS MOTOR DATA ----
        # Format: Bus.No  RealPower  MinMvar  MaxMvar  SpecVoltage(pu)  CapCurveNo  MVA  Status  Type
        elif section == 'SYNC_MOTOR':
            if len(tokens) >= 2:
                try:
                    mbus = int(tokens[0])
                    real_power = float(tokens[1])
                    q_min = float(tokens[2]) if len(tokens) > 2 else 0.0
                    q_max = float(tokens[3]) if len(tokens) > 3 else 75.0
                    v_spec = float(tokens[4]) if len(tokens) > 4 else 1.0
                    cap_curve = int(tokens[5]) if len(tokens) > 5 else 0
                    mva = float(tokens[6]) if len(tokens) > 6 else (abs(real_power) or 100.0)
                    status = 1 if (len(tokens) > 7 and int(tokens[7]) in (1, 3)) else 1
                    sm_type = int(tokens[8]) if len(tokens) > 8 else 4
                    
                    if mbus in buses and mbus > 0:
                        generators.append({
                            'bus': mbus,
                            'name': f"SM_{mbus}",
                            'P_out': -abs(real_power),  # Negative P represents motor consumption
                            'Q_out': 0.0,
                            'V_set': v_spec,
                            'Qmin': q_min,
                            'Qmax': q_max,
                            'status': status,
                            'gen_type': 'SYNC_MOTOR',
                            'bus_type': 1,  # Regulates voltage (PV)
                            'mva': mva
                        })
                except ValueError:
                    pass

        # ---- MOTOR (INDUCTION MOTOR) DATA ----
        # Format: FromBus  R  X  Status
        elif section == 'MOTOR':
            if len(tokens) >= 3:
                try:
                    mbus = int(tokens[0])
                    r_val = float(tokens[1])
                    x_val = float(tokens[2])
                    status = 1 if (len(tokens) > 3 and int(tokens[3]) in (1, 3)) else 1
                    z_sq = r_val*r_val + x_val*x_val
                    if z_sq > 1e-10 and mbus in buses and status == 1:
                        p_mw = (r_val / z_sq) * base_mva
                        q_mvar = (x_val / z_sq) * base_mva
                        loads.append({
                            'bus': mbus, 'P_demand': p_mw, 'Q_demand': q_mvar, 'model': 'constant_PQ'
                        })
                except ValueError:
                    pass

        # ---- SHUNT REACTOR DATA ----
        # Format: Bus/LineNo  R  X  Status  Location(0=Bus, 1=FromLine, 2=ToLine)
        elif section == 'SHUNT_REACTOR':
            if len(tokens) >= 4:
                try:
                    bus_or_line = int(tokens[0])
                    r_val = float(tokens[1])
                    x_val = float(tokens[2])
                    status = 1 if int(tokens[3]) in (1, 3) else 0
                    location = int(tokens[4]) if len(tokens) > 4 else 0
                    
                    if location == 0 and bus_or_line in buses:
                        # Bus-connected reactor: Q_reactor = BASE_MVA / |X| MVAr (absorbed)
                        q_react = base_mva / abs(x_val) if abs(x_val) > 1e-12 else 0.0
                        shunt_reactors.append({
                            'bus': bus_or_line, 'R': r_val, 'X': x_val,
                            'Q_react': q_react, 'status': status, 'location': location
                        })
                except ValueError:
                    pass

        # ---- SHUNT CAPACITOR DATA ----
        # Format: Bus/LineNo  G  B  Status  Location(0=Bus, 1=Line, 2=Line)
        elif section == 'SHUNT_CAP':
            if len(tokens) >= 4:
                try:
                    bus_or_line = int(tokens[0])
                    g_val = float(tokens[1])
                    b_val = float(tokens[2])
                    status = 1 if int(tokens[3]) in (1, 3) else 0
                    location = int(tokens[4]) if len(tokens) > 4 else 0
                    
                    if location == 0 and bus_or_line in buses:
                        # Bus-connected capacitor: Q_cap = BASE_MVA * B MVAr (generated)
                        q_cap = base_mva * abs(b_val)
                        shunt_capacitors.append({
                            'bus': bus_or_line, 'G': g_val, 'B': b_val,
                            'Q_cap': q_cap, 'status': status, 'location': location
                        })
                except ValueError:
                    pass

        # ---- SHUNT FACTS DEVICE DATA ----
        # Format: BusNo  DeviceType  VoltageRef  Slope  InductiveMax  CapacitiveMax  Tolerance  Status
        elif section == 'SHUNT_FACTS':
            if len(tokens) >= 7:
                try:
                    fbus = int(tokens[0])
                    dev_type = int(tokens[1])
                    v_ref = float(tokens[2])
                    slope = float(tokens[3])
                    q_ind_max = float(tokens[4])
                    q_cap_max = float(tokens[5])
                    tolerance = float(tokens[6])
                    status = 1 if (len(tokens) > 7 and int(tokens[7]) in (1, 3)) else 1
                    
                    if fbus in buses:
                        shunt_facts.append({
                            'bus': fbus, 'device_type': dev_type, 'V_ref': v_ref,
                            'slope': slope, 'Q_ind_max': q_ind_max, 'Q_cap_max': q_cap_max,
                            'tolerance': tolerance, 'status': status
                        })
                except ValueError:
                    pass

        # ---- CONVERTER DATA ----
        # Line 1: AC.NUM  CONV_BUS  XC_PU  CTRL_TYPE  CTRL_VAL  CTRL_ANGLE
        # Line 2: TAP_MIN  TAP_MAX  TAP_STEP  Nb  Np  Tfr_kV  Tfr_MVA
        elif section == 'CONVERTER':
            try:
                if pending_conv is None:
                    if len(tokens) >= 6:
                        c_num = int(tokens[0])
                        c_bus = int(tokens[1])
                        xc_pu = float(tokens[2])
                        c_type = int(tokens[3])
                        c_val = float(tokens[4])
                        c_ang = float(tokens[5])
                        pending_conv = {
                            'conv_num': c_num,
                            'bus': c_bus,
                            'xc_pu': xc_pu,
                            'ctrl_type': c_type,
                            'ctrl_val': c_val,
                            'ctrl_angle': c_ang
                        }
                else:
                    t_min = float(tokens[0]) if len(tokens) > 0 else 0.85
                    t_max = float(tokens[1]) if len(tokens) > 1 else 1.20
                    t_step = float(tokens[2]) if len(tokens) > 2 else 0.0125
                    nb = int(tokens[3]) if len(tokens) > 3 else 1
                    np_val = int(tokens[4]) if len(tokens) > 4 else 1
                    tfr_kv = float(tokens[5]) if len(tokens) > 5 else buses.get(pending_conv['bus'], {}).get('base_kV', 220.0)
                    tfr_mva = float(tokens[6]) if len(tokens) > 6 else 100.0
                    pending_conv.update({
                        'tap_min': t_min,
                        'tap_max': t_max,
                        'tap_step': t_step,
                        'nb': nb,
                        'np': np_val,
                        'tfr_kv': tfr_kv,
                        'tfr_mva': tfr_mva
                    })
                    converters_raw[pending_conv['conv_num']] = pending_conv
                    pending_conv = None
            except (ValueError, IndexError):
                pending_conv = None

        # ---- DC LINK DATA ----
        # Format: FromConvNo  ToConvNo  R-DC(Ohms)
        elif section == 'DC_LINK':
            if len(tokens) >= 3:
                try:
                    fc_no = int(tokens[0])
                    tc_no = int(tokens[1])
                    r_dc_val = float(tokens[2])
                    dc_links_raw.append({
                        'from_conv': fc_no,
                        'to_conv': tc_no,
                        'r_dc': r_dc_val
                    })
                except ValueError:
                    pass

    # ---- Validate PQ generator reactive limits ----
    invalid_pq_buses = sorted({
        g['bus'] for g in generators
        if g.get('bus_type') == 2 and not math.isclose(
            g['Qmin'], g['Qmax'], rel_tol=1e-9, abs_tol=1e-9
        )
    })
    if invalid_pq_buses:
        bus_list = ', '.join(str(bus) for bus in invalid_pq_buses)
        raise ValueError(
            f"Type 2 (PQ) generators have different MinMvar and MaxMvar "
            f"values at bus(es): {bus_list}"
        )

    for generator in generators:
        if generator.get('bus_type') == 2:
            generator['Qmin'] = generator['Qmax']
            generator['Q_out'] = generator['Qmax']

    # ---- Infer Slack, PV, and PQ bus types ----
    if slack_bus_id is None and len(buses) > 0:
        slack_bus_id = sorted(list(buses.keys()))[-1]  # fallback
        
    for bid, binfo in buses.items():
        if slack_bus_id is not None and bid == slack_bus_id:
            binfo['type'] = 3  # Slack Bus
        else:
            has_active_pv_gen = any(
                g['bus'] == bid and g['status'] == 1 and (g.get('bus_type', 1) == 1 or g.get('gen_type') == 'SYNC_MOTOR')
                for g in generators
            )
            if has_active_pv_gen:
                binfo['type'] = 2  # PV Bus
                for g in generators:
                    if g['bus'] == bid and g['status'] == 1 and (g.get('bus_type', 1) == 1 or g.get('gen_type') == 'SYNC_MOTOR'):
                        binfo['V_init'] = float(g.get('V_set', 1.0))
                        break
            else:
                binfo['type'] = 1  # PQ Bus

    # Sanitize and guarantee 100% unique names for all element types
    bus_list = list(buses.values())
    sanitize_and_ensure_unique_names(bus_list, 'bus')
    for b in bus_list:
        buses[b['num']] = b

    sanitize_and_ensure_unique_names(generators, 'gen')
    sanitize_and_ensure_unique_names(loads, 'load')
    sanitize_and_ensure_unique_names(lines_data, 'line')
    sanitize_and_ensure_unique_names(transformers, 'xfmr')
    sanitize_and_ensure_unique_names(shunt_reactors, 'reactor')
    sanitize_and_ensure_unique_names(shunt_capacitors, 'cap')
    sanitize_and_ensure_unique_names(shunt_facts, 'shunt')

    # Pair DC Links with Converters into Two-Terminal HVDC Links
    hvdc_links = []
    for idx, dl in enumerate(dc_links_raw, 1):
        fc_id = dl['from_conv']
        tc_id = dl['to_conv']
        fc = converters_raw.get(fc_id, {})
        tc = converters_raw.get(tc_id, {})
        fbus = fc.get('bus', 0)
        tbus = tc.get('bus', 0)
        hvdc_links.append({
            'num': idx,
            'name': f"HVDC_{fbus}_{tbus}_{idx}",
            'from_bus': fbus,
            'to_bus': tbus,
            'r_dc': dl['r_dc'],
            'status': 1,
            # From Side
            'from_mode': 'Rectifier',
            'from_ctrl_type': fc.get('ctrl_type', 3),
            'from_val': fc.get('ctrl_val', 50.0),
            'from_angle': fc.get('ctrl_angle', 12.0),
            'from_xc': fc.get('xc_pu', 0.0),
            'from_tfr_kv': fc.get('tfr_kv', buses.get(fbus, {}).get('base_kV', 220.0)),
            'from_tfr_mva': fc.get('tfr_mva', 100.0),
            'from_tap_min': fc.get('tap_min', 0.85),
            'from_tap_max': fc.get('tap_max', 1.20),
            'from_tap_step': fc.get('tap_step', 0.0125),
            'from_nb': fc.get('nb', 1),
            'from_np': fc.get('np', 1),
            # To Side
            'to_mode': 'Inverter',
            'to_ctrl_type': tc.get('ctrl_type', 1),
            'to_val': tc.get('ctrl_val', 220.0),
            'to_angle': tc.get('ctrl_angle', 15.0),
            'to_xc': tc.get('xc_pu', 0.0),
            'to_tfr_kv': tc.get('tfr_kv', buses.get(tbus, {}).get('base_kV', 220.0)),
            'to_tfr_mva': tc.get('tfr_mva', 100.0),
            'to_tap_min': tc.get('tap_min', 0.85),
            'to_tap_max': tc.get('tap_max', 1.20),
            'to_tap_step': tc.get('tap_step', 0.0125),
            'to_nb': tc.get('nb', 1),
            'to_np': tc.get('np', 1),
            'area': 1, 'zone': 1, 'owner': 1
        })
    sanitize_and_ensure_unique_names(hvdc_links, 'hvdc')

    return {
        'base_mva': base_mva,
        'slack_bus_id': slack_bus_id,
        'buses': buses,
        'generators': generators,
        'loads': loads,
        'lines': lines_data,
        'transformers': transformers,
        'shunt_reactors': shunt_reactors,
        'shunt_capacitors': shunt_capacitors,
        'shunt_facts': shunt_facts,
        'hvdc_links': hvdc_links,
    }

# Backward compatibility alias
parse_mipower_dat0 = parse_dat0


def parse_sc_dat0(sc_path):
    """
    Parses a Short Circuit .dat0 input file ($ schema).
    Extracts both the base Load Flow network model and the full Sequence / Short Circuit parameters.
    """
    with open(sc_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.read().splitlines()
        
    sec = None
    buses = {}
    lf_gens = []
    lf_loads = []
    lf_lines = []
    lf_xfmrs = []
    lf_reactors = []
    base_mva = 100.0
    
    sc_lines = []
    sc_xfmrs = []
    sc_gens = []
    sc_motors = []
    sc_reactors = []
    fault_cases = []
    all_bus_fault_spec = None
    line_voltage_factors = []
    global_factors = {
        'xfmr_zero_seq_rx': 0.05,
        'xfmr_zero_seq_factor': 0.90,
        'gen_neg_seq_r_mult': 0.175,
        'gen_neg_seq_x_mult': 0.175,
        'gen_zero_seq_r_mult': 0.0375,
        'gen_zero_seq_x_mult': 0.0375,
        'load_neg_seq_imp_mult': 0.81,
        'load_zero_seq_imp_mult': 1.60,
        'series_reactor_zero_seq_mult': 1.0,
        'shunt_reactor_zero_seq_mult': 0.625,
    }
    
    subsec = None
    for l in lines:
        s = l.strip()
        if not s:
            continue
        if s.startswith('$'):
            sec = s.upper().strip()
            subsec = None
            continue
        if s.startswith('%'):
            su = s.upper()
            if 'TRANSFORMER ZERO SEQUENCE R / X' in su:
                subsec = 'XFMR_RX'
            elif 'TRANSFORMER ZERO SEQUENCE IMPEDANCE' in su:
                subsec = 'XFMR_FACTOR'
            elif 'TRANSMISSION LINE FACTORS' in su or 'NUMBER OF TRANSMISSION LINE' in su:
                subsec = 'LINE'
            elif 'GENERATOR FACTORS' in su or 'GENERATOR NEGATIVE' in su:
                subsec = 'GEN'
            elif 'LOAD FACTORS' in su or 'LOAD NEGATIVE' in su:
                subsec = 'LOAD'
            elif 'SERIES REACTOR' in su:
                subsec = 'SERIES_REACTOR'
            elif 'SHUNT REACTOR' in su:
                subsec = 'SHUNT_REACTOR'
            continue
            
        toks = s.split()
        
        if sec == '$PROPERTY' and len(toks) >= 6:
            try:
                base_mva = float(toks[5])
            except Exception: pass
            
        elif sec == '$DATA_CORRECTION_FACTORS':
            try:
                if subsec == 'XFMR_RX' and len(toks) >= 1:
                    global_factors['xfmr_zero_seq_rx'] = float(toks[0])
                elif subsec == 'XFMR_FACTOR' and len(toks) >= 1:
                    global_factors['xfmr_zero_seq_factor'] = float(toks[0])
                elif subsec == 'LINE' and len(toks) == 4:
                    v_kv = float(toks[0]); r_mult = float(toks[1]); x_mult = float(toks[2]); b_mult = float(toks[3])
                    line_voltage_factors.append([v_kv, r_mult, x_mult, b_mult])
                elif subsec == 'GEN' and len(toks) >= 4:
                    global_factors['gen_neg_seq_r_mult'] = float(toks[0])
                    global_factors['gen_neg_seq_x_mult'] = float(toks[1])
                    global_factors['gen_zero_seq_r_mult'] = float(toks[2])
                    global_factors['gen_zero_seq_x_mult'] = float(toks[3])
                elif subsec == 'LOAD' and len(toks) >= 2:
                    global_factors['load_neg_seq_imp_mult'] = float(toks[0])
                    global_factors['load_zero_seq_imp_mult'] = float(toks[1])
                elif subsec == 'SERIES_REACTOR' and len(toks) >= 1:
                    global_factors['series_reactor_zero_seq_mult'] = float(toks[0])
                elif subsec == 'SHUNT_REACTOR' and len(toks) >= 1:
                    global_factors['shunt_reactor_zero_seq_mult'] = float(toks[0])
            except Exception: pass
            
        elif sec == '$BUS' and len(toks) >= 8:
            try:
                bnum = int(re.sub(r'[^\d]', '', toks[0]))
                bname = toks[5] if len(toks) > 5 else f'Bus_{bnum}'
                bkv = float(toks[4])
                vmag = float(toks[6])
                vang = float(toks[7])
                pgen = float(toks[8]) if len(toks) > 8 else 0.0
                qgen = float(toks[9]) if len(toks) > 9 else 0.0
                pload = float(toks[10]) if len(toks) > 10 else 0.0
                qload = float(toks[11]) if len(toks) > 11 else 0.0
                
                buses[bnum] = {
                    'num': bnum, 'name': bname, 'type': 1,
                    'base_kV': bkv, 'V_init': vmag, 'angle_init': vang,
                    'pgen': pgen, 'qgen': qgen, 'pload': pload, 'qload': qload
                }
                if pload > 0 or qload > 0:
                    lf_loads.append({
                        'bus': bnum, 'P_demand': pload, 'Q_demand': qload,
                        'cb_mva': 1500.0, 'wind_conn': 'G'
                    })
            except Exception: pass
            
        elif sec == '$TRANSMISSION_LINE' and len(toks) >= 13:
            try:
                fbus = int(re.sub(r'[^\d]', '', toks[1]))
                tbus = int(re.sub(r'[^\d]', '', toks[2]))
                st = 1 if int(toks[3]) in (1, 3) else 0
                r1 = float(toks[5])
                x1 = float(toks[6])
                b1 = float(toks[7]) * 2.0
                r0 = float(toks[8])
                x0 = float(toks[9])
                b0 = float(toks[10]) * 2.0
                fcb = float(toks[11])
                tcb = float(toks[12])
                
                sc_lines.append({
                    'uid': toks[0], 'from_bus': fbus, 'to_bus': tbus, 'status': st,
                    'ckts': int(toks[4]), 'r1': r1, 'x1': x1, 'b1': b1,
                    'r0': r0, 'x0': x0, 'b0': b0,
                    'from_cb_mva': fcb, 'to_cb_mva': tcb
                })
                lf_lines.append({
                    'from_bus': fbus, 'to_bus': tbus, 'length_km': 1.0,
                    'R_per_km': r1, 'X_per_km': x1, 'B_per_km': b1,
                    'rateA': max(fcb, tcb), 'status': st,
                    'R0_per_km': r0, 'X0_per_km': x0, 'B0_per_km': b0,
                    'from_cb_mva': fcb, 'to_cb_mva': tcb
                })
            except Exception: pass
            
        elif sec == '$TWO_WINDING_TRANSFORMER' and len(toks) >= 19:
            try:
                fbus = int(re.sub(r'[^\d]', '', toks[1]))
                tbus = int(re.sub(r'[^\d]', '', toks[2]))
                st = 1 if int(toks[3]) in (1, 3) else 0
                r1 = float(toks[5])
                x1 = float(toks[6])
                r0 = float(toks[7])
                x0 = float(toks[8])
                f_gr = float(toks[9])
                f_gx = float(toks[10])
                t_gr = float(toks[11])
                t_gx = float(toks[12])
                tap = float(toks[13])
                ps = float(toks[14])
                fcb = float(toks[15])
                tcb = float(toks[16])
                fconn = toks[17]
                tconn = toks[18]
                
                sc_xfmrs.append({
                    'uid': toks[0], 'from_bus': fbus, 'to_bus': tbus, 'status': st,
                    'r1': r1, 'x1': x1, 'r0': r0, 'x0': x0,
                    'from_gnd_r': f_gr, 'from_gnd_x': f_gx,
                    'to_gnd_r': t_gr, 'to_gnd_x': t_gx,
                    'tap_ratio': tap, 'phase_shift': ps,
                    'from_cb_mva': fcb, 'to_cb_mva': tcb,
                    'from_conn': fconn, 'to_conn': tconn
                })
                lf_xfmrs.append({
                    'from_bus': fbus, 'to_bus': tbus, 'R_pu': r1, 'X_pu': x1,
                    'tap_ratio': tap, 'rateA': max(fcb, tcb), 'phase_shift': ps,
                    'min_tap': 0.9, 'max_tap': 1.1, 'step_size': 0.0125, 'status': st,
                    'R0_pu': r0, 'X0_pu': x0, 'from_conn': fconn, 'to_conn': tconn,
                    'from_gnd_r': f_gr, 'from_gnd_x': f_gx, 'to_gnd_r': t_gr, 'to_gnd_x': t_gx,
                    'from_cb_mva': fcb, 'to_cb_mva': tcb
                })
            except Exception: pass
            
        elif sec == '$GENERATOR' and len(toks) >= 12:
            try:
                gbus = int(re.sub(r'[^\d]', '', toks[1]))
                st = 1 if int(toks[2]) in (1, 3) else 0
                p_out = buses.get(gbus, {}).get('pgen', 0.0)
                q_out = buses.get(gbus, {}).get('qgen', 0.0)
                v_set = buses.get(gbus, {}).get('V_init', 1.0)
                r1 = float(toks[4])
                x1 = float(toks[5])
                r2 = float(toks[6])
                x2 = float(toks[7])
                r0 = float(toks[8])
                x0 = float(toks[9])
                cb_mva = float(toks[10])
                wind_conn = toks[11]
                
                sc_gens.append({
                    'uid': toks[0], 'bus': gbus, 'status': st, 'gen_type': 'SYNC',
                    'r1': r1, 'x1': x1, 'r2': r2, 'x2': x2, 'r0': r0, 'x0': x0,
                    'cb_mva': cb_mva, 'wind_conn': wind_conn
                })
                lf_gens.append({
                    'bus': gbus, 'P_out': p_out, 'Q_out': q_out, 'V_set': v_set,
                    'Qmin': -999.0, 'Qmax': 999.0, 'status': st, 'gen_type': 'SYNC',
                    'R1_pu': r1, 'X1_pu': x1, 'R2_pu': r2, 'X2_pu': x2,
                    'R0_pu': r0, 'X0_pu': x0, 'cb_mva': cb_mva, 'wind_conn': wind_conn
                })
            except Exception: pass
            
        elif sec in ('$WIND_GENERATOR_TYPE_SIMPLE', '$SOLAR_SIMPLE') and len(toks) >= 12:
            try:
                gbus = int(re.sub(r'[^\d]', '', toks[1]))
                st = 1 if int(toks[2]) in (1, 3) else 0
                gtype = 'WIND' if 'WIND' in sec else 'SOLAR'
                p_out = buses.get(gbus, {}).get('pgen', 0.0)
                q_out = buses.get(gbus, {}).get('qgen', 0.0)
                v_set = buses.get(gbus, {}).get('V_init', 1.0)
                r1 = float(toks[4])
                x1 = float(toks[5])
                r2 = float(toks[6])
                x2 = float(toks[7])
                r0 = float(toks[8])
                x0 = float(toks[9])
                cb_mva = float(toks[10])
                wind_conn = toks[11]
                
                sc_gens.append({
                    'uid': toks[0], 'bus': gbus, 'status': st, 'gen_type': gtype,
                    'r1': r1, 'x1': x1, 'r2': r2, 'x2': x2, 'r0': r0, 'x0': x0,
                    'cb_mva': cb_mva, 'wind_conn': wind_conn
                })
                lf_gens.append({
                    'bus': gbus, 'P_out': p_out, 'Q_out': q_out, 'V_set': v_set,
                    'Qmin': -999.0, 'Qmax': 999.0, 'status': st, 'gen_type': gtype,
                    'R1_pu': r1, 'X1_pu': x1, 'R2_pu': r2, 'X2_pu': x2,
                    'R0_pu': r0, 'X0_pu': x0, 'cb_mva': cb_mva, 'wind_conn': wind_conn
                })
            except Exception: pass
            
        elif sec in ('$MOTOR', '$SYNCHRONOUS_MOTOR') and len(toks) >= 13:
            try:
                mbus = int(re.sub(r'[^\d]', '', toks[1]))
                st = 1 if int(toks[2]) in (1, 3) else 0
                mtype = 'SYNC_MOTOR' if 'SYNC' in sec else 'INDUCTION_MOTOR'
                r1 = float(toks[5])
                x1 = float(toks[6])
                r2 = float(toks[7])
                x2 = float(toks[8])
                r0 = float(toks[9])
                x0 = float(toks[10])
                cb_mva = float(toks[11])
                wind_conn = toks[12]
                
                sc_motors.append({
                    'uid': toks[0], 'bus': mbus, 'status': st, 'motor_type': mtype,
                    'r1': r1, 'x1': x1, 'r2': r2, 'x2': x2, 'r0': r0, 'x0': x0,
                    'cb_mva': cb_mva, 'wind_conn': wind_conn
                })
            except Exception: pass
            
        elif sec == '$LOAD' and len(toks) >= 5:
            try:
                lbus = int(re.sub(r'[^\d]', '', toks[1]))
                st = 1 if int(toks[2]) in (1, 3) else 0
                cb_mva = float(toks[3])
                wind_conn = toks[4]
                # Update load CB MVA and connection if exists
                for ld in lf_loads:
                    if ld['bus'] == lbus:
                        ld['cb_mva'] = cb_mva
                        ld['wind_conn'] = wind_conn
            except Exception: pass

        elif sec == '$SHUNT_REACTOR' and len(toks) >= 9:
            try:
                rbus = int(re.sub(r'[^\d]', '', toks[1]))
                st = 1 if int(toks[2]) in (1, 3) else 0
                g1 = float(toks[4])
                b1 = float(toks[5])
                g0 = float(toks[6])
                b0 = float(toks[7])
                cb_mva = float(toks[8])
                q_react = abs(b1) * base_mva
                
                sc_reactors.append({
                    'uid': toks[0], 'bus': rbus, 'status': st,
                    'g1': g1, 'b1': b1, 'g0': g0, 'b0': b0, 'cb_mva': cb_mva
                })
                lf_reactors.append({
                    'bus': rbus, 'Q_react': q_react, 'status': st,
                    'G1_pu': g1, 'B1_pu': b1, 'G0_pu': g0, 'B0_pu': b0, 'cb_mva': cb_mva
                })
            except Exception: pass
            
        elif sec == '$FAULT_ON_ALL_BUSES' and len(toks) == 5:
            try:
                ftype = int(toks[0])
                rf = float(toks[1])
                xf = float(toks[2])
                rg = float(toks[3])
                xg = float(toks[4])
                all_bus_fault_spec = (ftype, rf, xf, rg, xg)
            except Exception: pass

        elif sec == '$FAULT_ON_SELECTED_BUSES' and len(toks) >= 7 and 'BUS' in toks[1].upper():
            try:
                fault_cases.append([
                    int(toks[0]),
                    int(re.sub(r'[^\d]', '', toks[1])),
                    int(toks[2]),
                    float(toks[3]),
                    float(toks[4]),
                    float(toks[5]),
                    float(toks[6])
                ])
            except Exception: pass

    # If no selected buses specified but fault on all buses was enabled, populate fault cases for all buses
    if not fault_cases and all_bus_fault_spec and buses:
        ftype, rf, xf, rg, xg = all_bus_fault_spec
        for idx, bid in enumerate(sorted(buses.keys())):
            fault_cases.append([idx + 1, bid, ftype, rf, xf, rg, xg])

    # Infer Bus Types (Slack, PV, PQ)
    if buses:
        slack_id = sorted(list(buses.keys()))[-1]
        for bid, binfo in buses.items():
            if bid == slack_id:
                binfo['type'] = 3
            else:
                has_gen = any(g['bus'] == bid and g['status'] == 1 for g in lf_gens)
                binfo['type'] = 2 if has_gen else 1

    return {
        'base_mva': base_mva,
        'buses': buses,
        'generators': lf_gens,
        'loads': lf_loads,
        'lines': lf_lines,
        'transformers': lf_xfmrs,
        'shunt_reactors': lf_reactors,
        'shunt_capacitors': [],
        'shunt_facts': [],
        'lines_data': lf_lines,
        'sc_lines': sc_lines,
        'sc_transformers': sc_xfmrs,
        'sc_generators': sc_gens,
        'sc_motors': sc_motors,
        'sc_reactors': sc_reactors,
        'fault_cases': fault_cases,
        'line_voltage_factors': line_voltage_factors,
        'global_factors': global_factors
    }

# Backward compatibility alias
parse_mipower_sc_dat0 = parse_sc_dat0


def convert_dat0_to_py(dat0_path, out_py_path=None, secondary_dat0_path=None):
    """
    Converts a standard .dat0 file to a DevEN .py database file in the same directory.
    Automatically detects whether the file is Load Flow (*L.dat0) or Short Circuit (*S.dat0),
    and sets up extended columns. Allows passing an explicit secondary_dat0_path (LFA or SCS)
    to combine both files into a complete, unified database.
    """
    if not os.path.exists(dat0_path):
        raise FileNotFoundError(f"Input file not found: {dat0_path}")
        
    if out_py_path is None:
        out_py_path = os.path.splitext(dat0_path)[0] + ".py"
        
    dir_name = os.path.dirname(dat0_path)
    base_name = os.path.basename(dat0_path)

    # Check file content to detect if it is an SCS format file ($ schema) or LFA format (% schema)
    is_scs_format = False
    try:
        with open(dat0_path, 'r', encoding='utf-8', errors='ignore') as f_chk:
            header_sample = f_chk.read(500)
            if '$MIP_TITLE' in header_sample or '$BUS' in header_sample or '$ELEMENT_COUNT' in header_sample:
                is_scs_format = True
    except Exception:
        pass

    has_sc_data = False
    fault_cases = []
    line_voltage_factors = []
    global_factors = {
        "xfmr_zero_seq_rx": 0.0,
        "xfmr_zero_seq_factor": 0.0,
        "gen_neg_seq_r_mult": 0.0,
        "gen_neg_seq_x_mult": 0.0,
        "gen_zero_seq_r_mult": 0.0,
        "gen_zero_seq_x_mult": 0.0,
        "load_neg_seq_imp_mult": 0.0,
        "load_zero_seq_imp_mult": 0.0,
        "series_reactor_zero_seq_mult": 0.0,
        "shunt_reactor_zero_seq_mult": 0.0,
    }

    companion_path = None
    dir_name = os.path.dirname(os.path.abspath(dat0_path))
    base_name = os.path.basename(dat0_path)
    base_upper = base_name.upper()

    is_scs_input = ('0S' in base_upper or base_upper.endswith('S.DAT0') or base_upper.endswith('S.DAT') or 'SCS' in base_upper or is_scs_format)

    # Search for companion file in same directory
    cand_files = []
    if is_scs_input:
        # Input is SCS -> Search for companion LFA
        if '0S' in base_name: cand_files.append(os.path.join(dir_name, base_name.replace('0S', '0L')))
        if '0s' in base_name: cand_files.append(os.path.join(dir_name, base_name.replace('0s', '0l')))
        if 'SCS' in base_upper: cand_files.append(os.path.join(dir_name, re.sub('SCS', 'LFA', base_name, flags=re.IGNORECASE)))
        for f in os.listdir(dir_name):
            fu = f.upper()
            if (fu.endswith('L.DAT0') or fu.endswith('L.DAT') or '0L' in fu or 'LFA' in fu) and f != base_name:
                cand_files.append(os.path.join(dir_name, f))
    else:
        # Input is LFA -> Search for companion SCS
        if '0L' in base_name: cand_files.append(os.path.join(dir_name, base_name.replace('0L', '0S')))
        if '0l' in base_name: cand_files.append(os.path.join(dir_name, base_name.replace('0l', '0s')))
        if 'LFA' in base_upper: cand_files.append(os.path.join(dir_name, re.sub('LFA', 'SCS', base_name, flags=re.IGNORECASE)))
        for f in os.listdir(dir_name):
            fu = f.upper()
            if (fu.endswith('S.DAT0') or fu.endswith('S.DAT') or '0S' in fu or 'SCS' in fu) and f != base_name:
                cand_files.append(os.path.join(dir_name, f))

    if secondary_dat0_path and os.path.exists(secondary_dat0_path):
        companion_path = secondary_dat0_path
    else:
        for cf in cand_files:
            if os.path.exists(cf):
                companion_path = cf
                break


    if is_scs_input:
        sc_parsed = parse_sc_dat0(dat0_path)
        has_sc_data = True
        fault_cases = sc_parsed.get('fault_cases', [])
        line_voltage_factors = sc_parsed.get('line_voltage_factors', [])
        global_factors = sc_parsed.get('global_factors', global_factors)

        if companion_path:
            # Companion LFA exists: parse LFA baseline and overlay SCS sequence parameters
            lfa_data = parse_dat0(companion_path)
            data = lfa_data

            for l in data['lines']:
                match_sc = next((s for s in sc_parsed['sc_lines'] if (s['from_bus'] == l['from_bus'] and s['to_bus'] == l['to_bus']) or (s['from_bus'] == l['to_bus'] and s['to_bus'] == l['from_bus'])), None)
                if match_sc:
                    l['R0_per_km'] = match_sc.get('r0', 0.0)
                    l['X0_per_km'] = match_sc.get('x0', 0.0)
                    l['B0_per_km'] = match_sc.get('b0', 0.0)
                    l['from_cb_mva'] = match_sc.get('from_cb_mva', 0.0)
                    l['to_cb_mva'] = match_sc.get('to_cb_mva', 0.0)
                else:
                    l['R0_per_km'] = 0.0; l['X0_per_km'] = 0.0; l['B0_per_km'] = 0.0; l['from_cb_mva'] = 0.0; l['to_cb_mva'] = 0.0

            for x in data['transformers']:
                match_scx = next((s for s in sc_parsed['sc_transformers'] if (s['from_bus'] == x['from_bus'] and s['to_bus'] == x['to_bus']) or (s['from_bus'] == x['to_bus'] and s['to_bus'] == x['from_bus'])), None)
                if match_scx:
                    x['R0_pu'] = match_scx.get('r0', 0.0)
                    x['X0_pu'] = match_scx.get('x0', 0.0)
                    x['from_conn'] = match_scx.get('from_conn', "0")
                    x['to_conn'] = match_scx.get('to_conn', "0")
                    x['from_gnd_r'] = match_scx.get('from_gnd_r', 0.0)
                    x['from_gnd_x'] = match_scx.get('from_gnd_x', 0.0)
                    x['to_gnd_r'] = match_scx.get('to_gnd_r', 0.0)
                    x['to_gnd_x'] = match_scx.get('to_gnd_x', 0.0)
                    x['from_cb_mva'] = match_scx.get('from_cb_mva', 0.0)
                    x['to_cb_mva'] = match_scx.get('to_cb_mva', 0.0)
                else:
                    x['R0_pu'] = 0.0; x['X0_pu'] = 0.0; x['from_conn'] = "0"; x['to_conn'] = "0"
                    x['from_gnd_r'] = 0.0; x['from_gnd_x'] = 0.0; x['to_gnd_r'] = 0.0; x['to_gnd_x'] = 0.0
                    x['from_cb_mva'] = 0.0; x['to_cb_mva'] = 0.0

            for g in data['generators']:
                match_scg = next((s for s in sc_parsed['sc_generators'] if s['bus'] == g['bus']), None)
                if match_scg:
                    g['R1_pu'] = match_scg.get('r1', 0.0); g['X1_pu'] = match_scg.get('x1', 0.0)
                    g['R2_pu'] = match_scg.get('r2', 0.0); g['X2_pu'] = match_scg.get('x2', 0.0)
                    g['R0_pu'] = match_scg.get('r0', 0.0); g['X0_pu'] = match_scg.get('x0', 0.0)
                    g['cb_mva'] = match_scg.get('cb_mva', 0.0); g['wind_conn'] = match_scg.get('wind_conn', "0")
                else:
                    g['R1_pu'] = 0.0; g['X1_pu'] = 0.0; g['R2_pu'] = 0.0; g['X2_pu'] = 0.0
                    g['R0_pu'] = 0.0; g['X0_pu'] = 0.0; g['cb_mva'] = 0.0; g['wind_conn'] = "0"

            for ld in data['loads']:
                match_scld = next((s for s in sc_parsed.get('loads', []) if s['bus'] == ld['bus']), None)
                ld['cb_mva'] = match_scld.get('cb_mva', 1500.0) if match_scld else 1500.0
                ld['wind_conn'] = match_scld.get('wind_conn', "G") if match_scld else "G"

            for r in data['shunt_reactors']:
                match_scr = next((s for s in sc_parsed['sc_reactors'] if s['bus'] == r['bus']), None)
                if match_scr:
                    r['G1_pu'] = match_scr.get('g1', 0.0); r['B1_pu'] = match_scr.get('b1', 0.0)
                    r['G0_pu'] = match_scr.get('g0', 0.0); r['B0_pu'] = match_scr.get('b0', 0.0)
                    r['cb_mva'] = match_scr.get('cb_mva', 0.0)
                else:
                    r['G1_pu'] = 0.0; r['B1_pu'] = 0.0; r['G0_pu'] = 0.0; r['B0_pu'] = 0.0; r['cb_mva'] = 0.0
        else:
            # SCS alone: set sensible rateA for lines based on base voltage if rateA is missing or breaker capacity
            data = sc_parsed
            for l in data.get('lines', []):
                if l.get('rateA', 0.0) == 0.0 or l.get('rateA', 0.0) >= 1500.0:
                    fb_kv = data['buses'].get(l['from_bus'], {}).get('base_kV', 132.0)
                    l['rateA'] = 100.0 if fb_kv <= 132.0 else (250.0 if fb_kv <= 220.0 else 500.0)

    else:
        # Input is LFA file: parse LFA and merge companion SCS sequence parameters if present
        data = parse_dat0(dat0_path)
        fault_cases = []
        line_voltage_factors = []
        global_factors = {
            "xfmr_zero_seq_rx": 0.0,
            "xfmr_zero_seq_factor": 0.0,
            "gen_neg_seq_r_mult": 0.0,
            "gen_neg_seq_x_mult": 0.0,
            "gen_zero_seq_r_mult": 0.0,
            "gen_zero_seq_x_mult": 0.0,
            "load_neg_seq_imp_mult": 0.0,
            "load_zero_seq_imp_mult": 0.0,
            "series_reactor_zero_seq_mult": 0.0,
            "shunt_reactor_zero_seq_mult": 0.0,
        }

        if companion_path:
            sc_parsed = parse_sc_dat0(companion_path)
            has_sc_data = True
            fault_cases = sc_parsed.get('fault_cases', [])
            line_voltage_factors = sc_parsed.get('line_voltage_factors', [])
            global_factors = sc_parsed.get('global_factors', global_factors)

            for l in data['lines']:
                match_sc = next((s for s in sc_parsed['sc_lines'] if (s['from_bus'] == l['from_bus'] and s['to_bus'] == l['to_bus']) or (s['from_bus'] == l['to_bus'] and s['to_bus'] == l['from_bus'])), None)
                if match_sc:
                    l['R0_per_km'] = match_sc.get('r0', 0.0)
                    l['X0_per_km'] = match_sc.get('x0', 0.0)
                    l['B0_per_km'] = match_sc.get('b0', 0.0)
                    l['from_cb_mva'] = match_sc.get('from_cb_mva', 0.0)
                    l['to_cb_mva'] = match_sc.get('to_cb_mva', 0.0)
                else:
                    l['R0_per_km'] = 0.0; l['X0_per_km'] = 0.0; l['B0_per_km'] = 0.0; l['from_cb_mva'] = 0.0; l['to_cb_mva'] = 0.0

            for x in data['transformers']:
                match_scx = next((s for s in sc_parsed['sc_transformers'] if (s['from_bus'] == x['from_bus'] and s['to_bus'] == x['to_bus']) or (s['from_bus'] == x['to_bus'] and s['to_bus'] == x['from_bus'])), None)
                if match_scx:
                    x['R0_pu'] = match_scx.get('r0', 0.0)
                    x['X0_pu'] = match_scx.get('x0', 0.0)
                    x['from_conn'] = match_scx.get('from_conn', "0")
                    x['to_conn'] = match_scx.get('to_conn', "0")
                    x['from_gnd_r'] = match_scx.get('from_gnd_r', 0.0)
                    x['from_gnd_x'] = match_scx.get('from_gnd_x', 0.0)
                    x['to_gnd_r'] = match_scx.get('to_gnd_r', 0.0)
                    x['to_gnd_x'] = match_scx.get('to_gnd_x', 0.0)
                    x['from_cb_mva'] = match_scx.get('from_cb_mva', 0.0)
                    x['to_cb_mva'] = match_scx.get('to_cb_mva', 0.0)
                else:
                    x['R0_pu'] = 0.0; x['X0_pu'] = 0.0; x['from_conn'] = "0"; x['to_conn'] = "0"
                    x['from_gnd_r'] = 0.0; x['from_gnd_x'] = 0.0; x['to_gnd_r'] = 0.0; x['to_gnd_x'] = 0.0
                    x['from_cb_mva'] = 0.0; x['to_cb_mva'] = 0.0

            for g in data['generators']:
                match_scg = next((s for s in sc_parsed['sc_generators'] if s['bus'] == g['bus']), None)
                if not match_scg and g.get('gen_type') == 'SYNC_MOTOR':
                    match_scg = next((s for s in sc_parsed.get('sc_motors', []) if s['bus'] == g['bus']), None)
                if match_scg:
                    g['R1_pu'] = match_scg.get('r1', 0.0); g['X1_pu'] = match_scg.get('x1', 0.0)
                    g['R2_pu'] = match_scg.get('r2', 0.0); g['X2_pu'] = match_scg.get('x2', 0.0)
                    g['R0_pu'] = match_scg.get('r0', 0.0); g['X0_pu'] = match_scg.get('x0', 0.0)
                    g['cb_mva'] = match_scg.get('cb_mva', 0.0); g['wind_conn'] = match_scg.get('wind_conn', "0")
                else:
                    g['R1_pu'] = 0.0; g['X1_pu'] = 0.0; g['R2_pu'] = 0.0; g['X2_pu'] = 0.0
                    g['R0_pu'] = 0.0; g['X0_pu'] = 0.0; g['cb_mva'] = 0.0; g['wind_conn'] = "0"

            for ld in data['loads']:
                match_scld = next((s for s in sc_parsed.get('loads', []) if s['bus'] == ld['bus']), None)
                ld['cb_mva'] = match_scld.get('cb_mva', 1500.0) if match_scld else 1500.0
                ld['wind_conn'] = match_scld.get('wind_conn', "G") if match_scld else "G"

            for r in data['shunt_reactors']:
                match_scr = next((s for s in sc_parsed['sc_reactors'] if s['bus'] == r['bus']), None)
                if match_scr:
                    r['G1_pu'] = match_scr.get('g1', 0.0); r['B1_pu'] = match_scr.get('b1', 0.0)
                    r['G0_pu'] = match_scr.get('g0', 0.0); r['B0_pu'] = match_scr.get('b0', 0.0)
                    r['cb_mva'] = match_scr.get('cb_mva', 0.0)
                else:
                    r['G1_pu'] = 0.0; r['B1_pu'] = 0.0; r['G0_pu'] = 0.0; r['B0_pu'] = 0.0; r['cb_mva'] = 0.0
        else:
            for l in data['lines']:
                l['R0_per_km'] = 0.0; l['X0_per_km'] = 0.0; l['B0_per_km'] = 0.0; l['from_cb_mva'] = 0.0; l['to_cb_mva'] = 0.0
            for x in data['transformers']:
                x['R0_pu'] = 0.0; x['X0_pu'] = 0.0; x['from_conn'] = "0"; x['to_conn'] = "0"
                x['from_gnd_r'] = 0.0; x['from_gnd_x'] = 0.0; x['to_gnd_r'] = 0.0; x['to_gnd_x'] = 0.0
                x['from_cb_mva'] = 0.0; x['to_cb_mva'] = 0.0
            for g in data['generators']:
                g['R1_pu'] = 0.0; g['X1_pu'] = 0.0; g['R2_pu'] = 0.0; g['X2_pu'] = 0.0
                g['R0_pu'] = 0.0; g['X0_pu'] = 0.0; g['cb_mva'] = 0.0; g['wind_conn'] = "0"
            for ld in data['loads']:
                ld['cb_mva'] = 0.0; ld['wind_conn'] = "0"
            for r in data['shunt_reactors']:
                r['G1_pu'] = 0.0; r['B1_pu'] = 0.0; r['G0_pu'] = 0.0; r['B0_pu'] = 0.0; r['cb_mva'] = 0.0



    base_mva = data['base_mva']
    buses = data['buses']
    gens = data['generators']
    loads = data['loads']
    lines_data = data['lines'] if 'lines' in data else data.get('lines_data', [])
    xfmrs = data['transformers']
    sh_reactors = data.get('shunt_reactors', [])
    sh_capacitors = data.get('shunt_capacitors', [])
    sh_facts = data.get('shunt_facts', [])
    hvdc_links = data.get('hvdc_links', [])

    py_lines = []
    py_lines.append('"""')
    py_lines.append(f'Power System Database - Converted from Standard DAT File')
    py_lines.append(f'Original File: {base_name}')
    py_lines.append(f'Generated On: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    py_lines.append('"""')
    py_lines.append('')
    py_lines.append(f'BASE_MVA = {base_mva:.1f}')
    py_lines.append('')
    
    # ---- BUS DATA ----
    py_lines.append('# ========== BUS DATA ==========')
    py_lines.append('# [bus_num, bus_name, bus_type, base_kV, V_init_pu, angle_init_deg, shunt_G, shunt_B, area, zone, owner, lat, long, sk_mva, rx_ratio, z01_ratio]')
    py_lines.append('BUS_DATA = [')
    for bid in sorted(buses.keys()):
        b = buses[bid]
        area = b.get('area', 1)
        zone = b.get('zone', 1)
        sk = b.get('sk_mva', 1000.0)
        rx = b.get('rx_ratio', 0.1)
        z01 = b.get('z01_ratio', 1.0)
        lat = b.get('lat', 0.0)
        lon = b.get('long', 0.0)
        py_lines.append(f"    [{b['num']}, \"{b['name']}\", {b['type']}, {b['base_kV']:.3f}, {b['V_init']:.4f}, {b['angle_init']:.4f}, 0, 0, {area}, {zone}, 1, {lat}, {lon}, {sk}, {rx}, {z01}],")
    py_lines.append(']')
    py_lines.append('')
    
    # ---- GENERATOR DATA ----
    py_lines.append('# ========== GENERATOR DATA ==========')
    py_lines.append('# [gen_num, gen_name, gen_type, bus, P_out, Q_out, V_set, Qmin, Qmax, status, area, zone, owner, R1_pu, X1_pu, R2_pu, X2_pu, R0_pu, X0_pu, cb_mva, wind_conn]')
    py_lines.append('GENERATOR_DATA = [')
    for idx, g in enumerate(gens):
        gtype = g.get('gen_type', 'SYNC')
        if gtype == 'SYNC_MOTOR':
            gname = g.get('name') or f"SM_{g['bus']}_{idx+1}"
        else:
            gname = g.get('name') or f"Gen_{g['bus']}_{idx+1}"
        r1 = g.get('R1_pu', 0.0); x1 = g.get('X1_pu', 0.0)
        r2 = g.get('R2_pu', 0.0); x2 = g.get('X2_pu', 0.0)
        r0 = g.get('R0_pu', 0.0); x0 = g.get('X0_pu', 0.0)
        cbm = g.get('cb_mva', 0.0); wconn = g.get('wind_conn', '0')
        py_lines.append(f"    [{idx+1}, \"{gname}\", \"{gtype}\", {g['bus']}, {g['P_out']:.3f}, {g['Q_out']:.3f}, {g['V_set']:.4f}, {g['Qmin']:.3f}, {g['Qmax']:.3f}, {g['status']}, 1, 1, 1, {r1:.6e}, {x1:.6e}, {r2:.6e}, {x2:.6e}, {r0:.6e}, {x0:.6e}, {cbm:.1f}, \"{wconn}\"],")
    py_lines.append(']')
    py_lines.append('')

    # ---- LOAD DATA ----
    py_lines.append('# ========== LOAD DATA ==========')
    py_lines.append('# [load_num, load_name, bus, P_demand, Q_demand, model, area, zone, cb_mva, wind_conn]')
    py_lines.append('LOAD_DATA = [')
    for idx, ld in enumerate(loads):
        lname = f"Load_{ld['bus']}_{idx+1}"
        cbm = ld.get('cb_mva', 0.0); wconn = ld.get('wind_conn', '0')
        py_lines.append(f"    [{idx+1}, \"{lname}\", {ld['bus']}, {ld['P_demand']:.4f}, {ld['Q_demand']:.4f}, \"constant_PQ\", 1, 1, {cbm:.1f}, \"{wconn}\"],")
    py_lines.append(']')
    py_lines.append('')

    # ---- LINE DATA ----
    py_lines.append('# ========== TRANSMISSION LINE DATA ==========')
    py_lines.append('# [line_num, line_name, from_bus, to_bus, length_km, R_per_km, X_per_km, B_per_km, rateA, status, area, zone, owner, R0_per_km, X0_per_km, B0_per_km, from_cb_mva, to_cb_mva]')
    py_lines.append('LINE_DATA = [')
    for idx, l in enumerate(lines_data):
        lname = f"Line_{l['from_bus']}_{l['to_bus']}"
        r0 = l.get('R0_per_km', 0.0); x0 = l.get('X0_per_km', 0.0); b0 = l.get('B0_per_km', 0.0)
        fcb = l.get('from_cb_mva', 0.0); tcb = l.get('to_cb_mva', 0.0)
        py_lines.append(f"    [{idx+1}, \"{lname}\", {l['from_bus']}, {l['to_bus']}, {l['length_km']:.4f}, {l['R_per_km']:.6e}, {l['X_per_km']:.6e}, {l['B_per_km']:.6e}, {l['rateA']:.2f}, {l['status']}, 1, 1, 1, {r0:.6e}, {x0:.6e}, {b0:.6e}, {fcb:.1f}, {tcb:.1f}],")
    py_lines.append(']')
    py_lines.append('')

    # ---- TRANSFORMER DATA ----
    py_lines.append('# ========== TRANSFORMER DATA ==========')
    py_lines.append('# [xfmr_num, xfmr_name, from_bus, to_bus, R_pu, X_pu, tap_ratio, rateA, phase_shift, min_tap, max_tap, step_size, status, area, zone, owner, R0_pu, X0_pu, from_conn, to_conn, from_gnd_r, from_gnd_x, to_gnd_r, to_gnd_x, from_cb_mva, to_cb_mva]')
    py_lines.append('TRANSFORMER_DATA = [')
    for idx, x in enumerate(xfmrs):
        xname = f"Xfmr_{x['from_bus']}_{x['to_bus']}"
        r0 = x.get('R0_pu', 0.0); x0 = x.get('X0_pu', 0.0)
        fconn = x.get('from_conn', '0'); tconn = x.get('to_conn', '0')
        fgr = x.get('from_gnd_r', 0.0); fgx = x.get('from_gnd_x', 0.0)
        tgr = x.get('to_gnd_r', 0.0); tgx = x.get('to_gnd_x', 0.0)
        fcb = x.get('from_cb_mva', 0.0); tcb = x.get('to_cb_mva', 0.0)
        py_lines.append(f"    [{idx+1}, \"{xname}\", {x['from_bus']}, {x['to_bus']}, {x['R_pu']:.6e}, {x['X_pu']:.6e}, {x['tap_ratio']:.4f}, {x['rateA']:.2f}, {x['phase_shift']:.2f}, {x['min_tap']:.4f}, {x['max_tap']:.4f}, {x['step_size']:.4f}, {x['status']}, 1, 1, 1, {r0:.6e}, {x0:.6e}, \"{fconn}\", \"{tconn}\", {fgr:.6e}, {fgx:.6e}, {tgr:.6e}, {tgx:.6e}, {fcb:.1f}, {tcb:.1f}],")
    py_lines.append(']')
    py_lines.append('')

    # ---- THREE-WINDING TRANSFORMER DATA ----
    py_lines.append('# ========== THREE-WINDING TRANSFORMER DATA ==========')
    py_lines.append('# [tw_num, tw_name, hv_bus, mv_bus, lv_bus, r_hm, x_hm, r_hl, x_hl, r_ml, x_ml, rate_h, rate_m, rate_l, tap_h, tap_m, tap_l, status, area, zone, owner]')
    py_lines.append('THREE_WINDING_TRANSFORMER_DATA = [')
    py_lines.append(']')
    py_lines.append('')

    # ---- CAPACITOR DATA ----
    py_lines.append('# ========== CAPACITOR DATA ==========')
    py_lines.append('# [cap_num, cap_name, bus, Q_cap, status, area, zone]')
    py_lines.append('CAPACITOR_DATA = [')
    for idx, c in enumerate(sh_capacitors):
        cname = f"Cap_{c['bus']}_{idx+1}"
        py_lines.append(f"    [{idx+1}, \"{cname}\", {c['bus']}, {c['Q_cap']:.4f}, {c['status']}, 1, 1],")
    py_lines.append(']')
    py_lines.append('')

    # ---- REACTOR DATA ----
    py_lines.append('# ========== REACTOR DATA ==========')
    py_lines.append('# [reactor_num, reactor_name, bus, Q_react, status, area, zone, G1_pu, B1_pu, G0_pu, B0_pu, cb_mva]')
    py_lines.append('REACTOR_DATA = [')
    for idx, r in enumerate(sh_reactors):
        rname = f"Reactor_{r['bus']}_{idx+1}"
        g1 = r.get('G1_pu', 0.0); b1 = r.get('B1_pu', 0.0)
        g0 = r.get('G0_pu', 0.0); b0 = r.get('B0_pu', 0.0)
        cbm = r.get('cb_mva', 0.0)
        py_lines.append(f"    [{idx+1}, \"{rname}\", {r['bus']}, {r['Q_react']:.4f}, {r['status']}, 1, 1, {g1:.6e}, {b1:.6e}, {g0:.6e}, {b0:.6e}, {cbm:.1f}],")
    py_lines.append(']')
    py_lines.append('')

    # ---- SERIES COMPENSATION DATA ----
    py_lines.append('# ========== SERIES COMPENSATION DATA ==========')
    py_lines.append('# [series_num, series_name, from_bus, to_bus, r, x, comp_pct, status, area, zone, owner]')
    py_lines.append('SERIES_COMP_DATA = [')
    py_lines.append(']')
    py_lines.append('')

    # ---- SERIES REACTOR DATA ----
    py_lines.append('# ========== SERIES REACTOR DATA ==========')
    py_lines.append('# [sr_num, sr_name, from_bus, to_bus, r, x, status, area, zone, owner]')
    py_lines.append('SERIES_REACTOR_DATA = [')
    py_lines.append(']')
    py_lines.append('')

    # ---- SHUNT DATA (FACTS devices) ----
    py_lines.append('# ========== SHUNT / FACTS DATA ==========')
    py_lines.append('# [shunt_num, shunt_name, bus, Q_shunt, status, area, zone]')
    py_lines.append('SHUNT_DATA = [')
    for idx, sf in enumerate(sh_facts):
        sname = f"FACTS_{sf['bus']}_{idx+1}"
        q_shunt = sf.get('Q_cap_max', 0.0)
        py_lines.append(f"    [{idx+1}, \"{sname}\", {sf['bus']}, {q_shunt:.4f}, {sf['status']}, 1, 1],")
    py_lines.append(']')
    py_lines.append('')

    # ---- TWO-TERMINAL HVDC LINK DATA ----
    py_lines.append('# ========== TWO-TERMINAL HVDC LINK DATA ==========')
    py_lines.append('# [link_num, link_name, from_bus, to_bus, r_dc, status, from_mode, from_ctrl_type, from_val, from_angle, from_xc, from_tfr_kv, from_tfr_mva, from_tap_min, from_tap_max, from_tap_step, from_nb, from_np, to_mode, to_ctrl_type, to_val, to_angle, to_xc, to_tfr_kv, to_tfr_mva, to_tap_min, to_tap_max, to_tap_step, to_nb, to_np, area, zone, owner]')
    py_lines.append('HVDC_LINK_DATA = [')
    for idx, lk in enumerate(hvdc_links):
        lname = lk.get('name', f"HVDC_{lk.get('from_bus', 0)}_{lk.get('to_bus', 0)}_{idx+1}")
        py_lines.append(
            f"    [{idx+1}, \"{lname}\", {lk['from_bus']}, {lk['to_bus']}, {lk['r_dc']:.6f}, {lk['status']}, "
            f"\"{lk.get('from_mode', 'Rectifier')}\", {lk.get('from_ctrl_type', 3)}, {lk.get('from_val', 50.0):.4f}, "
            f"{lk.get('from_angle', 12.0):.4f}, {lk.get('from_xc', 0.0):.6e}, {lk.get('from_tfr_kv', 220.0):.4f}, "
            f"{lk.get('from_tfr_mva', 100.0):.4f}, {lk.get('from_tap_min', 0.85):.4f}, {lk.get('from_tap_max', 1.20):.4f}, "
            f"{lk.get('from_tap_step', 0.0125):.4f}, {lk.get('from_nb', 1)}, {lk.get('from_np', 1)}, "
            f"\"{lk.get('to_mode', 'Inverter')}\", {lk.get('to_ctrl_type', 1)}, {lk.get('to_val', 220.0):.4f}, "
            f"{lk.get('to_angle', 15.0):.4f}, {lk.get('to_xc', 0.0):.6e}, {lk.get('to_tfr_kv', 220.0):.4f}, "
            f"{lk.get('to_tfr_mva', 100.0):.4f}, {lk.get('to_tap_min', 0.85):.4f}, {lk.get('to_tap_max', 1.20):.4f}, "
            f"{lk.get('to_tap_step', 0.0125):.4f}, {lk.get('to_nb', 1)}, {lk.get('to_np', 1)}, "
            f"{lk.get('area', 1)}, {lk.get('zone', 1)}, {lk.get('owner', 1)}],"
        )
    py_lines.append(']')
    py_lines.append('')

    # ---- FAULT ON SELECTED BUSES ----
    py_lines.append('# ========== FAULT ON SELECTED BUSES ==========')
    py_lines.append('# [case_num, fault_bus, fault_type, phase_fault_r, phase_fault_x, gnd_fault_r, gnd_fault_x]')
    py_lines.append('FAULT_ON_SELECTED_BUSES = [')
    for fc in fault_cases:
        py_lines.append(f"    [{fc[0]}, {fc[1]}, {fc[2]}, {fc[3]:.6e}, {fc[4]:.6e}, {fc[5]:.6e}, {fc[6]:.6e}],")
    py_lines.append(']')
    py_lines.append('')

    # ---- TRANSMISSION LINE ZERO SEQUENCE FACTORS ----
    py_lines.append('# ========== TRANSMISSION LINE ZERO SEQUENCE MULTIPLICATION FACTORS ==========')
    py_lines.append('# [voltage_kV, zero_seq_res_mult, zero_seq_react_mult, zero_seq_adm_mult]')
    py_lines.append('TRANSMISSION_LINE_ZERO_SEQ_FACTORS = [')
    for lf in line_voltage_factors:
        py_lines.append(f"    [{lf[0]:.3f}, {lf[1]:.4f}, {lf[2]:.4f}, {lf[3]:.4f}],")
    py_lines.append(']')
    py_lines.append('')

    # ---- GLOBAL SEQUENCE CORRECTION FACTORS ----
    py_lines.append('# ========== GLOBAL SEQUENCE CORRECTION FACTORS ==========')
    py_lines.append('GLOBAL_SEQUENCE_CORRECTION_FACTORS = {')
    for k, v in global_factors.items():
        py_lines.append(f"    \"{k}\": {v},")
    py_lines.append('}')
    py_lines.append('')

    py_lines.append('if __name__ == "__main__":')
    py_lines.append('    print(f"Buses: {len(BUS_DATA)}")')
    py_lines.append('    print(f"Generators: {len(GENERATOR_DATA)}")')
    py_lines.append('    print(f"Loads: {len(LOAD_DATA)}")')
    py_lines.append('    print(f"Lines: {len(LINE_DATA)}")')
    py_lines.append('    print(f"Transformers: {len(TRANSFORMER_DATA)}")')
    py_lines.append('    print(f"Three Winding Transformers: {len(THREE_WINDING_TRANSFORMER_DATA)}")')
    py_lines.append('    print(f"Capacitors: {len(CAPACITOR_DATA)}")')
    py_lines.append('    print(f"Reactors: {len(REACTOR_DATA)}")')
    py_lines.append('    print(f"Series Comps: {len(SERIES_COMP_DATA)}")')
    py_lines.append('    print(f"Series Reactors: {len(SERIES_REACTOR_DATA)}")')
    py_lines.append('    print(f"Shunts: {len(SHUNT_DATA)}")')
    py_lines.append('    print(f"HVDC Links: {len(HVDC_LINK_DATA)}")')
    py_lines.append('    print(f"Fault Cases: {len(FAULT_ON_SELECTED_BUSES)}")')
    py_lines.append('')

    with open(out_py_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(py_lines))

    return out_py_path


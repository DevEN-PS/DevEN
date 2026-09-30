"""
Standard RAW File to DevEN Python (.py) Converter Module
=========================================================
Parses standard RAW format files (v30, v33, v34, v36) and generates native DevEN Python database (.py) files.

Features:
  - System Base MVA extraction from header (SBASE).
  - Bus data parsing (PQ, PV, Slack, Isolated).
  - Load data parsing (constant MVA, constant current, constant impedance).
  - Generator data parsing (SYNC & WIND).
  - Branch data parsing (Transmission Lines & Reactors).
  - 2-Winding and 3-Winding Transformer data parsing.
  - Fixed Shunt data parsing (Capacitors & Reactors).
  - Switched Shunt data parsing (FACTS & STATCOMs).
"""

import os
import re

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


def parse_raw(raw_path):
    """Parses a standard RAW network file into raw dictionary components."""

    with open(raw_path, 'r', encoding='utf-8', errors='ignore') as f:
        raw_lines = f.readlines()

    base_mva = 100.0
    if len(raw_lines) >= 2:
        header_parts = raw_lines[1].split(',')
        if len(header_parts) >= 2:
            try:
                base_mva = float(header_parts[1].strip())
            except Exception: pass

    buses = {}
    generators = []
    loads = []
    lines_data = []
    transformers = []
    three_winding_transformers = []
    capacitors = []
    reactors = []
    shunts = []

    section = "HEADER"
    i = 0

    while i < len(raw_lines):
        raw_line = raw_lines[i]
        i += 1
        line = raw_line.strip()

        if not line:
            continue

        # Section transition detection
        if 'BEGIN' in line.upper():
            bp = line.upper().split('BEGIN')[-1]
            if 'BUS DATA' in bp: section = 'BUS'
            elif 'LOAD DATA' in bp: section = 'LOAD'
            elif 'FIXED SHUNT DATA' in bp: section = 'FIX_SHUNT'
            elif 'GENERATOR DATA' in bp: section = 'GEN'
            elif 'BRANCH DATA' in bp: section = 'BRANCH'
            elif 'TRANSFORMER DATA' in bp: section = 'XFMR'
            elif 'SWITCHED SHUNT DATA' in bp: section = 'SW_SHUNT'
            elif 'HEADER' in bp or 'SYSTEM-WIDE DATA' in bp: section = 'HEADER'
            else: section = 'OTHER'
            continue


        if line.startswith('@!') or line.startswith('Q') or line.startswith('0 /') or line.startswith('0/') or line == '0':
            continue

        # Split line by comma, handling quotes correctly
        tokens = [t.strip() for t in re.split(r',(?=(?:[^\']*\'[^\']*\')*[^\']*$)', line)]
        if not tokens or not tokens[0]:
            continue

        if section == 'BUS':
            try:
                bnum = int(tokens[0])
                bname = tokens[1].replace("'", "").strip() if len(tokens) > 1 else f"Bus_{bnum}"
                bkv = float(tokens[2]) if len(tokens) > 2 else 132.0
                ide = int(tokens[3]) if len(tokens) > 3 else 1
                area = int(tokens[4]) if len(tokens) > 4 else 1
                zone = int(tokens[5]) if len(tokens) > 5 else 1
                owner = int(tokens[6]) if len(tokens) > 6 else 1
                vm = float(tokens[7]) if len(tokens) > 7 else 1.0
                va = float(tokens[8]) if len(tokens) > 8 else 0.0

                buses[bnum] = {
                    'num': bnum, 'name': bname, 'type': ide, 'base_kV': bkv,
                    'V_init': vm, 'angle_init': va, 'area': area, 'zone': zone, 'owner': owner
                }
            except Exception: pass

        elif section == 'LOAD':
            try:
                bnum = int(tokens[0])
                lid = tokens[1].replace("'", "").strip() if len(tokens) > 1 else "1"
                stat = int(tokens[2]) if len(tokens) > 2 else 1
                area = int(tokens[3]) if len(tokens) > 3 else 1
                zone = int(tokens[4]) if len(tokens) > 4 else 1
                pl = float(tokens[5]) if len(tokens) > 5 else 0.0
                ql = float(tokens[6]) if len(tokens) > 6 else 0.0
                ip = float(tokens[7]) if len(tokens) > 7 else 0.0
                iq = float(tokens[8]) if len(tokens) > 8 else 0.0
                yp = float(tokens[9]) if len(tokens) > 9 else 0.0
                yq = float(tokens[10]) if len(tokens) > 10 else 0.0

                lname = tokens[-1].replace("'", "").strip() if len(tokens) >= 18 and tokens[-1].strip() else f"Load_{bnum}_{lid}"

                p_demand = pl + ip + yp
                q_demand = ql + iq + yq

                loads.append({
                    'bus': bnum, 'id': lid, 'P_demand': p_demand, 'Q_demand': q_demand,
                    'status': stat, 'area': area, 'zone': zone, 'name': lname,
                    'cb_mva': 1500.0, 'wind_conn': 'G'
                })
            except Exception: pass

        elif section == 'FIX_SHUNT':
            try:
                bnum = int(tokens[0])
                sid = tokens[1].replace("'", "").strip() if len(tokens) > 1 else "1"
                stat = int(tokens[2]) if len(tokens) > 2 else 1
                gl = float(tokens[3]) if len(tokens) > 3 else 0.0
                bl = float(tokens[4]) if len(tokens) > 4 else 0.0

                if bl > 0:
                    capacitors.append({'bus': bnum, 'Q_cap': bl, 'status': stat})
                elif bl < 0:
                    reactors.append({
                        'bus': bnum, 'Q_react': abs(bl), 'status': stat,
                        'G1_pu': gl, 'B1_pu': bl, 'G0_pu': 0.0, 'B0_pu': 0.0, 'cb_mva': 1500.0
                    })
            except Exception: pass

        elif section == 'GEN':
            try:
                bnum = int(tokens[0])
                gid = tokens[1].replace("'", "").strip() if len(tokens) > 1 else "1"
                pg = float(tokens[2]) if len(tokens) > 2 else 0.0
                qg = float(tokens[3]) if len(tokens) > 3 else 0.0
                qt = float(tokens[4]) if len(tokens) > 4 else 9999.0
                qb = float(tokens[5]) if len(tokens) > 5 else -9999.0
                vs = float(tokens[6]) if len(tokens) > 6 else 1.0
                mbase = float(tokens[8]) if len(tokens) > 8 else 100.0
                zr = float(tokens[9]) if len(tokens) > 9 else 0.0
                zx = float(tokens[10]) if len(tokens) > 10 else 0.0
                stat = int(tokens[15]) if len(tokens) > 15 else 1

                gname = tokens[-1].replace("'", "").strip() if len(tokens) >= 29 and tokens[-1].strip() else f"Gen_{bnum}_{gid}"
                gtype = "WIND" if "WTG" in gname.upper() else "SYNC"

                generators.append({
                    'bus': bnum, 'id': gid, 'P_out': pg, 'Q_out': qg,
                    'Qmax': qt, 'Qmin': qb, 'V_set': vs, 'cb_mva': mbase,
                    'status': stat, 'name': gname, 'gen_type': gtype,
                    'R1_pu': zr, 'X1_pu': zx, 'R2_pu': zr, 'X2_pu': zx, 'R0_pu': 0.0, 'X0_pu': 0.0
                })
            except Exception: pass

        elif section == 'BRANCH':
            try:
                fbus = int(tokens[0])
                tbus = int(tokens[1])
                ckt = tokens[2].replace("'", "").strip() if len(tokens) > 2 else "1"
                r = float(tokens[3]) if len(tokens) > 3 else 0.0
                x = float(tokens[4]) if len(tokens) > 4 else 0.01
                b = float(tokens[5]) if len(tokens) > 5 else 0.0
                ratea = float(tokens[7]) if len(tokens) > 7 else 0.0
                
                stat = 1
                if len(tokens) >= 24:
                    try: stat = int(tokens[23])
                    except Exception: pass
                    
                length = 1.0
                if len(tokens) >= 26:
                    try: length = float(tokens[25])
                    except Exception: pass
                if length <= 0: length = 1.0

                lines_data.append({
                    'from_bus': fbus, 'to_bus': tbus, 'ckt': ckt,
                    'length_km': length, 'R_per_km': r / length, 'X_per_km': x / length, 'B_per_km': b / length,
                    'rateA': ratea, 'status': stat,
                    'R0_per_km': 0.0, 'X0_per_km': 0.0, 'B0_per_km': 0.0, 'from_cb_mva': 1500.0, 'to_cb_mva': 1500.0
                })
            except Exception: pass

        elif section == 'XFMR':
            try:
                fbus = int(tokens[0])
                tbus = int(tokens[1])
                kbus = int(tokens[2]) if len(tokens) > 2 else 0
                ckt = tokens[3].replace("'", "").strip() if len(tokens) > 3 else "1"
                xname = tokens[10].replace("'", "").strip() if len(tokens) > 10 and tokens[10].replace("'", "").strip() else f"Xfmr_{fbus}_{tbus}"
                stat = int(tokens[11]) if len(tokens) > 11 else 1

                if kbus == 0:
                    # 2-winding transformer (read next 3 lines)
                    l2 = [t.strip() for t in re.split(r',(?=(?:[^\']*\'[^\']*\')*[^\']*$)', raw_lines[i].strip())]; i += 1
                    l3 = [t.strip() for t in re.split(r',(?=(?:[^\']*\'[^\']*\')*[^\']*$)', raw_lines[i].strip())]; i += 1
                    l4 = [t.strip() for t in re.split(r',(?=(?:[^\']*\'[^\']*\')*[^\']*$)', raw_lines[i].strip())]; i += 1

                    r12 = float(l2[0]) if len(l2) > 0 else 0.0
                    x12 = float(l2[1]) if len(l2) > 1 else 0.05

                    windv1 = float(l3[0]) if len(l3) > 0 else 1.0
                    ang1 = float(l3[2]) if len(l3) > 2 else 0.0
                    rate1 = float(l3[3]) if len(l3) > 3 else 0.0

                    rma1 = float(l3[18]) if len(l3) > 18 else 1.1
                    rmi1 = float(l3[19]) if len(l3) > 19 else 0.9
                    ntp1 = int(l3[22]) if len(l3) > 22 else 33

                    windv2 = float(l4[0]) if len(l4) > 0 else 1.0

                    tap_ratio = windv1 / windv2 if windv2 > 0 else windv1
                    step_size = (rma1 - rmi1) / ntp1 if ntp1 > 0 else 0.00625

                    transformers.append({
                        'from_bus': fbus, 'to_bus': tbus, 'ckt': ckt,
                        'R_pu': r12, 'X_pu': x12, 'tap_ratio': tap_ratio,
                        'rateA': rate1, 'phase_shift': ang1, 'min_tap': rmi1, 'max_tap': rma1,
                        'step_size': step_size, 'status': stat, 'name': xname,
                        'R0_pu': 0.0, 'X0_pu': 0.0, 'from_conn': '0', 'to_conn': '0',
                        'from_gnd_r': 0.0, 'from_gnd_x': 0.0, 'to_gnd_r': 0.0, 'to_gnd_x': 0.0,
                        'from_cb_mva': 1500.0, 'to_cb_mva': 1500.0
                    })
                else:
                    # 3-winding transformer (read next 4 lines)
                    l2 = [t.strip() for t in re.split(r',(?=(?:[^\']*\'[^\']*\')*[^\']*$)', raw_lines[i].strip())]; i += 1
                    l3 = [t.strip() for t in re.split(r',(?=(?:[^\']*\'[^\']*\')*[^\']*$)', raw_lines[i].strip())]; i += 1
                    l4 = [t.strip() for t in re.split(r',(?=(?:[^\']*\'[^\']*\')*[^\']*$)', raw_lines[i].strip())]; i += 1
                    l5 = [t.strip() for t in re.split(r',(?=(?:[^\']*\'[^\']*\')*[^\']*$)', raw_lines[i].strip())]; i += 1

                    r12 = float(l2[0]); x12 = float(l2[1])
                    r23 = float(l2[3]); x23 = float(l2[4])
                    r31 = float(l2[6]); x31 = float(l2[7])

                    rate1 = float(l3[3]) if len(l3) > 3 else 0.0
                    rate2 = float(l4[3]) if len(l4) > 3 else 0.0
                    rate3 = float(l5[3]) if len(l5) > 3 else 0.0

                    tap1 = float(l3[0]) if len(l3) > 0 else 1.0
                    tap2 = float(l4[0]) if len(l4) > 0 else 1.0
                    tap3 = float(l5[0]) if len(l5) > 0 else 1.0

                    three_winding_transformers.append({
                        'hv_bus': fbus, 'mv_bus': tbus, 'lv_bus': kbus,
                        'r_hm': r12, 'x_hm': x12, 'r_hl': r31, 'x_hl': x31, 'r_ml': r23, 'x_ml': x23,
                        'rate_h': rate1, 'rate_m': rate2, 'rate_l': rate3,
                        'tap_h': tap1, 'tap_m': tap2, 'tap_l': tap3, 'status': stat, 'name': xname
                    })
            except Exception: pass

        elif section == 'SW_SHUNT':
            try:
                bnum = int(tokens[0])
                sid = tokens[1].replace("'", "").strip() if len(tokens) > 1 else "1"
                stat = int(tokens[4]) if len(tokens) > 4 else 1
                binit = float(tokens[11]) if len(tokens) > 11 else 0.0

                shunts.append({
                    'bus': bnum, 'Q_shunt': binit, 'status': stat
                })
            except Exception: pass

    # Sanitize and guarantee 100% unique names for all element types
    bus_list = list(buses.values())
    sanitize_and_ensure_unique_names(bus_list, 'bus')
    for b in bus_list:
        buses[b['num']] = b

    sanitize_and_ensure_unique_names(generators, 'gen')
    sanitize_and_ensure_unique_names(loads, 'load')
    sanitize_and_ensure_unique_names(lines_data, 'line')
    sanitize_and_ensure_unique_names(transformers, 'xfmr')
    sanitize_and_ensure_unique_names(three_winding_transformers, '3wxfmr')
    sanitize_and_ensure_unique_names(capacitors, 'cap')
    sanitize_and_ensure_unique_names(reactors, 'reactor')
    sanitize_and_ensure_unique_names(shunts, 'shunt')

    return {
        'base_mva': base_mva,
        'buses': buses,
        'generators': generators,
        'loads': loads,
        'lines': lines_data,
        'transformers': transformers,
        'three_winding_transformers': three_winding_transformers,
        'capacitors': capacitors,
        'reactors': reactors,
        'shunts': shunts
    }

# Backward compatibility alias
parse_psse_raw = parse_raw


def convert_psse_raw_to_py(raw_path, out_py_path=None):
    """
    Converts a standard RAW file to a DevEN .py database file.
    """
    if not os.path.exists(raw_path):
        raise FileNotFoundError(f"Input file not found: {raw_path}")

    if out_py_path is None:
        out_py_path = os.path.splitext(raw_path)[0] + ".py"

    base_name = os.path.basename(raw_path)
    data = parse_raw(raw_path)

    base_mva = data['base_mva']
    buses = data['buses']
    gens = data['generators']
    loads = data['loads']
    lines_data = data['lines']
    xfmrs = data['transformers']
    tw_xfmrs = data['three_winding_transformers']
    sh_capacitors = data['capacitors']
    sh_reactors = data['reactors']
    sh_facts = data['shunts']

    py_lines = []
    py_lines.append('"""')
    py_lines.append(f'Power System Database - Converted from PSS/E RAW File')
    py_lines.append(f'Original File: {base_name}')
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
        py_lines.append(f"    [{b['num']}, \"{b['name']}\", {b['type']}, {b['base_kV']:.3f}, {b['V_init']:.4f}, {b['angle_init']:.4f}, 0, 0, {b['area']}, {b['zone']}, {b['owner']}, 0.0, 0.0, 1000.0, 0.1, 1.0],")
    py_lines.append(']')
    py_lines.append('')

    # ---- GENERATOR DATA ----
    py_lines.append('# ========== GENERATOR DATA ==========')
    py_lines.append('# [gen_num, gen_name, gen_type, bus, P_out, Q_out, V_set, Qmin, Qmax, status, area, zone, owner, R1_pu, X1_pu, R2_pu, X2_pu, R0_pu, X0_pu, cb_mva, wind_conn]')
    py_lines.append('GENERATOR_DATA = [')
    for idx, g in enumerate(gens):
        gtype = g.get('gen_type', 'SYNC')
        gname = g.get('name', f"Gen_{g['bus']}_{idx+1}")
        r1 = g.get('R1_pu', 0.0); x1 = g.get('X1_pu', 0.0)
        r2 = g.get('R2_pu', 0.0); x2 = g.get('X2_pu', 0.0)
        r0 = g.get('R0_pu', 0.0); x0 = g.get('X0_pu', 0.0)
        cbm = g.get('cb_mva', 100.0); wconn = '0'
        py_lines.append(f"    [{idx+1}, \"{gname}\", \"{gtype}\", {g['bus']}, {g['P_out']:.3f}, {g['Q_out']:.3f}, {g['V_set']:.4f}, {g['Qmin']:.3f}, {g['Qmax']:.3f}, {g['status']}, 1, 1, 1, {r1:.6e}, {x1:.6e}, {r2:.6e}, {x2:.6e}, {r0:.6e}, {x0:.6e}, {cbm:.1f}, \"{wconn}\"],")
    py_lines.append(']')
    py_lines.append('')

    # ---- LOAD DATA ----
    py_lines.append('# ========== LOAD DATA ==========')
    py_lines.append('# [load_num, load_name, bus, P_demand, Q_demand, model, area, zone, cb_mva, wind_conn]')
    py_lines.append('LOAD_DATA = [')
    for idx, ld in enumerate(loads):
        lname = ld.get('name', f"Load_{ld['bus']}_{idx+1}")
        cbm = ld.get('cb_mva', 1500.0); wconn = ld.get('wind_conn', 'G')
        py_lines.append(f"    [{idx+1}, \"{lname}\", {ld['bus']}, {ld['P_demand']:.4f}, {ld['Q_demand']:.4f}, \"constant_PQ\", {ld.get('area', 1)}, {ld.get('zone', 1)}, {cbm:.1f}, \"{wconn}\"],")
    py_lines.append(']')
    py_lines.append('')

    # ---- LINE DATA ----
    py_lines.append('# ========== TRANSMISSION LINE DATA ==========')
    py_lines.append('# [line_num, line_name, from_bus, to_bus, length_km, R_per_km, X_per_km, B_per_km, rateA, status, area, zone, owner, R0_per_km, X0_per_km, B0_per_km, from_cb_mva, to_cb_mva]')
    py_lines.append('LINE_DATA = [')
    for idx, l in enumerate(lines_data):
        lname = f"Line_{l['from_bus']}_{l['to_bus']}"
        r0 = l.get('R0_per_km', 0.0); x0 = l.get('X0_per_km', 0.0); b0 = l.get('B0_per_km', 0.0)
        fcb = l.get('from_cb_mva', 1500.0); tcb = l.get('to_cb_mva', 1500.0)
        ratea = l['rateA']
        if ratea <= 0:
            fb_kv = buses.get(l['from_bus'], {}).get('base_kV', 132.0)
            ratea = 100.0 if fb_kv <= 132.0 else (250.0 if fb_kv <= 220.0 else 500.0)
        py_lines.append(f"    [{idx+1}, \"{lname}\", {l['from_bus']}, {l['to_bus']}, {l['length_km']:.4f}, {l['R_per_km']:.6e}, {l['X_per_km']:.6e}, {l['B_per_km']:.6e}, {ratea:.2f}, {l['status']}, 1, 1, 1, {r0:.6e}, {x0:.6e}, {b0:.6e}, {fcb:.1f}, {tcb:.1f}],")
    py_lines.append(']')
    py_lines.append('')

    # ---- TRANSFORMER DATA ----
    py_lines.append('# ========== TRANSFORMER DATA ==========')
    py_lines.append('# [xfmr_num, xfmr_name, from_bus, to_bus, R_pu, X_pu, tap_ratio, rateA, phase_shift, min_tap, max_tap, step_size, status, area, zone, owner, R0_pu, X0_pu, from_conn, to_conn, from_gnd_r, from_gnd_x, to_gnd_r, to_gnd_x, from_cb_mva, to_cb_mva]')
    py_lines.append('TRANSFORMER_DATA = [')
    for idx, x in enumerate(xfmrs):
        xname = x.get('name', f"Xfmr_{x['from_bus']}_{x['to_bus']}")
        r0 = x.get('R0_pu', 0.0); x0 = x.get('X0_pu', 0.0)
        fconn = x.get('from_conn', '0'); tconn = x.get('to_conn', '0')
        fgr = x.get('from_gnd_r', 0.0); fgx = x.get('from_gnd_x', 0.0)
        tgr = x.get('to_gnd_r', 0.0); tgx = x.get('to_gnd_x', 0.0)
        fcb = x.get('from_cb_mva', 1500.0); tcb = x.get('to_cb_mva', 1500.0)
        ratea = x['rateA']
        if ratea <= 0: ratea = 100.0
        py_lines.append(f"    [{idx+1}, \"{xname}\", {x['from_bus']}, {x['to_bus']}, {x['R_pu']:.6e}, {x['X_pu']:.6e}, {x['tap_ratio']:.4f}, {ratea:.2f}, {x['phase_shift']:.2f}, {x.get('min_tap', 0.9):.4f}, {x.get('max_tap', 1.1):.4f}, {x.get('step_size', 0.00625):.4f}, {x['status']}, 1, 1, 1, {r0:.6e}, {x0:.6e}, \"{fconn}\", \"{tconn}\", {fgr:.6e}, {fgx:.6e}, {tgr:.6e}, {tgx:.6e}, {fcb:.1f}, {tcb:.1f}],")
    py_lines.append(']')
    py_lines.append('')

    # ---- THREE-WINDING TRANSFORMER DATA ----
    py_lines.append('# ========== THREE-WINDING TRANSFORMER DATA ==========')
    py_lines.append('# [tw_num, tw_name, hv_bus, mv_bus, lv_bus, r_hm, x_hm, r_hl, x_hl, r_ml, x_ml, rate_h, rate_m, rate_l, tap_h, tap_m, tap_l, status, area, zone, owner]')
    py_lines.append('THREE_WINDING_TRANSFORMER_DATA = [')
    for idx, tw in enumerate(tw_xfmrs):
        twname = tw.get('name', f"TW_Xfmr_{tw['hv_bus']}_{tw['mv_bus']}_{tw['lv_bus']}")
        py_lines.append(f"    [{idx+1}, \"{twname}\", {tw['hv_bus']}, {tw['mv_bus']}, {tw['lv_bus']}, {tw['r_hm']:.6e}, {tw['x_hm']:.6e}, {tw['r_hl']:.6e}, {tw['x_hl']:.6e}, {tw['r_ml']:.6e}, {tw['x_ml']:.6e}, {tw['rate_h']:.2f}, {tw['rate_m']:.2f}, {tw['rate_l']:.2f}, {tw['tap_h']:.4f}, {tw['tap_m']:.4f}, {tw['tap_l']:.4f}, {tw['status']}, 1, 1, 1],")
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
        cbm = r.get('cb_mva', 1500.0)
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

    # ---- SHUNT DATA (FACTS / Switched Shunts) ----
    py_lines.append('# ========== SHUNT / FACTS DATA ==========')
    py_lines.append('# [shunt_num, shunt_name, bus, Q_shunt, status, area, zone]')
    py_lines.append('SHUNT_DATA = [')
    for idx, sf in enumerate(sh_facts):
        sname = f"FACTS_{sf['bus']}_{idx+1}"
        q_shunt = sf.get('Q_shunt', 0.0)
        py_lines.append(f"    [{idx+1}, \"{sname}\", {sf['bus']}, {q_shunt:.4f}, {sf['status']}, 1, 1],")
    py_lines.append(']')
    py_lines.append('')

    # ---- FAULT ON SELECTED BUSES ----
    py_lines.append('# ========== FAULT ON SELECTED BUSES ==========')
    py_lines.append('# [case_num, fault_bus, fault_type, phase_fault_r, phase_fault_x, gnd_fault_r, gnd_fault_x]')
    py_lines.append('FAULT_ON_SELECTED_BUSES = [')
    py_lines.append(']')
    py_lines.append('')

    # ---- TRANSMISSION LINE ZERO SEQUENCE FACTORS ----
    py_lines.append('# ========== TRANSMISSION LINE ZERO SEQUENCE MULTIPLICATION FACTORS ==========')
    py_lines.append('# [voltage_kV, zero_seq_res_mult, zero_seq_react_mult, zero_seq_adm_mult]')
    py_lines.append('TRANSMISSION_LINE_ZERO_SEQ_FACTORS = [')
    py_lines.append(']')
    py_lines.append('')

    # ---- GLOBAL SEQUENCE CORRECTION FACTORS ----
    py_lines.append('# ========== GLOBAL SEQUENCE CORRECTION FACTORS ==========')
    py_lines.append('GLOBAL_SEQUENCE_CORRECTION_FACTORS = {')
    py_lines.append('    "xfmr_zero_seq_rx": 0.0,')
    py_lines.append('    "xfmr_zero_seq_factor": 0.0,')
    py_lines.append('    "gen_neg_seq_r_mult": 0.0,')
    py_lines.append('    "gen_neg_seq_x_mult": 0.0,')
    py_lines.append('    "gen_zero_seq_r_mult": 0.0,')
    py_lines.append('    "gen_zero_seq_x_mult": 0.0,')
    py_lines.append('    "load_neg_seq_imp_mult": 0.0,')
    py_lines.append('    "load_zero_seq_imp_mult": 0.0,')
    py_lines.append('    "series_reactor_zero_seq_mult": 0.0,')
    py_lines.append('    "shunt_reactor_zero_seq_mult": 0.0,')
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
    py_lines.append('    print(f"Shunts: {len(SHUNT_DATA)}")')
    py_lines.append('')

    with open(out_py_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(py_lines))

    return out_py_path

# Backward compatibility alias
convert_raw_to_py = convert_psse_raw_to_py


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        out_file = convert_raw_to_py(sys.argv[1])
        print(f"Successfully converted RAW to: {out_file}")

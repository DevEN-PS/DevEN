# DevEN Path Bootstrapper
import sys
import os
import csv
import copy

try:
    from utils.time_series_imputer import generate_time_points, TimeSeriesImputer
except ImportError:
    from time_series_imputer import generate_time_points, TimeSeriesImputer

"""
DevEN Universal Time Series CSV Manager
Handles full multi-component universal CSV templates and batch profile imports with smart ID/Name matching.
"""

UNIVERSAL_CSV_HEADERS = [
    "Element_Type",
    "Element_ID",
    "Element_Name",
    "Connected_Bus",
    "Time_Step",
    "Timestamp",
    "Time_Label",
    "P_MW",
    "Q_MVar",
    "V_set_pu",
    "Qmin_MVar",
    "Qmax_MVar",
    "Status"
]

UNIVERSAL_3PHASE_CSV_HEADERS = [
    "Element_Type",
    "Element_ID",
    "Element_Name",
    "Connected_Bus",
    "Time_Step",
    "Timestamp",
    "Time_Label",
    "Pa_MW",
    "Pb_MW",
    "Pc_MW",
    "Qa_MVar",
    "Qb_MVar",
    "Qc_MVar",
    "Va_set_pu",
    "Vb_set_pu",
    "Vc_set_pu",
    "Qmin_MVar",
    "Qmax_MVar",
    "Status"
]


def generate_universal_csv_template(data_dict_or_app, time_settings=None, output_path=None):
    """
    Generates a full master universal CSV template containing all network components
    (Generators, Loads, Capacitors, Reactors, Shunts) mapped across the configured time horizon.
    Guarantees exact matching of all Element IDs and Names present in the active database.
    """
    time_settings = time_settings or {}
    duration = float(time_settings.get('duration', 24.0))
    dur_unit = time_settings.get('duration_unit', 'Hours')
    step_size = float(time_settings.get('step_size', 1.0))
    step_unit = time_settings.get('step_unit', 'Hours')
    start_time = time_settings.get('start_time', '2026-01-01 00:00:00')

    time_points = generate_time_points(
        duration=duration,
        duration_unit=dur_unit,
        step_size=step_size,
        step_unit=step_unit,
        start_time=start_time
    )

    # Extract component collections from loaded database
    if hasattr(data_dict_or_app, 'generators'):
        gens = data_dict_or_app.generators
        loads = data_dict_or_app.loads
        caps = getattr(data_dict_or_app, 'capacitors', {})
        reacts = getattr(data_dict_or_app, 'reactors', {})
        shunts = getattr(data_dict_or_app, 'shunts', {})
    elif isinstance(data_dict_or_app, dict):
        gens = data_dict_or_app.get('generators', {})
        loads = data_dict_or_app.get('loads', {})
        caps = data_dict_or_app.get('capacitors', {})
        reacts = data_dict_or_app.get('reactors', {})
        shunts = data_dict_or_app.get('shunts', {})
    else:
        gens, loads, caps, reacts, shunts = {}, {}, {}, {}, {}

    rows = []

    # 1. Generators (uses exact ID and exact Name in DB)
    for gid, gen in sorted(gens.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
        g_name = gen.get('name', f'Gen_{gid}')
        g_bus = gen.get('bus', '')
        base_p = float(gen.get('P_out', 0.0))
        base_q = float(gen.get('Q_out', 0.0))
        base_v = float(gen.get('V_set', 1.0))
        base_qmin = float(gen.get('Qmin', -999.0))
        base_qmax = float(gen.get('Qmax', 999.0))
        st = int(gen.get('status', 1))

        for pt in time_points:
            rows.append([
                "GEN",
                gid,
                g_name,
                g_bus,
                pt['index'],
                pt['timestamp'],
                pt['label'],
                f"{base_p:.2f}",
                f"{base_q:.2f}",
                f"{base_v:.4f}",
                f"{base_qmin:.2f}",
                f"{base_qmax:.2f}",
                st
            ])

    # 2. Loads
    for lid, load in sorted(loads.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
        l_name = load.get('name', f'Load_{lid}')
        l_bus = load.get('bus', '')
        base_p = float(load.get('P_demand', 0.0))
        base_q = float(load.get('Q_demand', 0.0))
        st = int(load.get('status', 1))

        for pt in time_points:
            rows.append([
                "LOAD",
                lid,
                l_name,
                l_bus,
                pt['index'],
                pt['timestamp'],
                pt['label'],
                f"{base_p:.2f}",
                f"{base_q:.2f}",
                "", # V_set
                "", # Qmin
                "", # Qmax
                st
            ])

    # 3. Capacitors
    for cid, cap in sorted(caps.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
        c_name = cap.get('name', f'Cap_{cid}')
        c_bus = cap.get('bus', '')
        base_q = float(cap.get('Q_cap', 0.0))
        st = int(cap.get('status', 1))

        for pt in time_points:
            rows.append([
                "CAPACITOR",
                cid,
                c_name,
                c_bus,
                pt['index'],
                pt['timestamp'],
                pt['label'],
                "", # P not applicable
                f"{base_q:.2f}",
                "",
                "",
                "",
                st
            ])

    # 4. Reactors
    for rid, rct in sorted(reacts.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
        r_name = rct.get('name', f'Reactor_{rid}')
        r_bus = rct.get('bus', '')
        base_q = float(rct.get('Q_react', 0.0))
        st = int(rct.get('status', 1))

        for pt in time_points:
            rows.append([
                "REACTOR",
                rid,
                r_name,
                r_bus,
                pt['index'],
                pt['timestamp'],
                pt['label'],
                "", # P not applicable
                f"{base_q:.2f}",
                "",
                "",
                "",
                st
            ])

    # 5. Shunts
    for sid, sh in sorted(shunts.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
        s_name = sh.get('name', f'Shunt_{sid}')
        s_bus = sh.get('bus', '')
        base_q = float(sh.get('Q_shunt', 0.0))
        st = int(sh.get('status', 1))

        for pt in time_points:
            rows.append([
                "SHUNT",
                sid,
                s_name,
                s_bus,
                pt['index'],
                pt['timestamp'],
                pt['label'],
                "", # P not applicable
                f"{base_q:.2f}",
                "",
                "",
                "",
                st
            ])

    if output_path:
        with open(output_path, "w", newline="", encoding="utf-8") as fp:
            writer = csv.writer(fp)
            writer.writerow(UNIVERSAL_CSV_HEADERS)
            writer.writerows(rows)

    return rows


def generate_3phase_universal_csv_template(data_dict_or_app, time_settings=None, options=None, output_path=None):
    """
    Generates a master 3-Phase Universal Time Series CSV template with per-phase
    parameters (Pa, Pb, Pc, Qa, Qb, Qc, Va_set, Vb_set, Vc_set) mapped across the time horizon.

    Options dictionary supports:
      - 'unbalance_mode': 'balanced', 'unbalanced_pct', 'single_phase_lateral'
      - 'load_phase_pct': (Pa%, Pb%, Pc%), default (40.0, 35.0, 25.0)
      - 'gen_phase_pct': (Pa%, Pb%, Pc%), default (33.333, 33.333, 33.334)
      - 'profile_pattern': 'flat', 'diurnal_solar', 'diurnal_commercial', 'diurnal_residential', 'random_walk'
    """
    import math

    time_settings = time_settings or {}
    options = options or {}

    duration = float(time_settings.get('duration', 24.0))
    dur_unit = time_settings.get('duration_unit', 'Hours')
    step_size = float(time_settings.get('step_size', 1.0))
    step_unit = time_settings.get('step_unit', 'Hours')
    start_time = time_settings.get('start_time', '2026-01-01 00:00:00')

    unbalance_mode = str(options.get('unbalance_mode', 'balanced')).lower()
    load_pct = options.get('load_phase_pct', (40.0, 35.0, 25.0))
    gen_pct = options.get('gen_phase_pct', (33.333, 33.333, 33.334))
    pattern = str(options.get('profile_pattern', 'diurnal_commercial')).lower()

    time_points = generate_time_points(
        duration=duration,
        duration_unit=dur_unit,
        step_size=step_size,
        step_unit=step_unit,
        start_time=start_time
    )

    # Extract component collections from loaded database
    if hasattr(data_dict_or_app, 'generators'):
        gens = data_dict_or_app.generators
        loads = data_dict_or_app.loads
        caps = getattr(data_dict_or_app, 'capacitors', {})
        reacts = getattr(data_dict_or_app, 'reactors', {})
        shunts = getattr(data_dict_or_app, 'shunts', {})
    elif isinstance(data_dict_or_app, dict):
        gens = data_dict_or_app.get('generators', {})
        loads = data_dict_or_app.get('loads', {})
        caps = data_dict_or_app.get('capacitors', {})
        reacts = data_dict_or_app.get('reactors', {})
        shunts = data_dict_or_app.get('shunts', {})
    else:
        gens, loads, caps, reacts, shunts = {}, {}, {}, {}, {}

    def get_time_multiplier(pt, pat):
        """Calculates shape multiplier (0.0 to 1.3) based on time-of-day"""
        hr = float(pt.get('time_hr', 0.0)) % 24.0
        if pat == 'diurnal_solar':
            # Solar PV curve: 0 at night, peaks at 12:00-13:00
            if 6.0 <= hr <= 18.0:
                rad = (hr - 6.0) / 12.0 * math.pi
                return max(0.0, math.sin(rad))
            return 0.0
        elif pat == 'diurnal_residential':
            # Morning peak (7-9), midday dip, evening peak (18-22)
            if 6.0 <= hr < 10.0:
                return 0.6 + 0.4 * math.sin((hr - 6.0) / 4.0 * math.pi)
            elif 10.0 <= hr < 17.0:
                return 0.5 + 0.1 * math.sin((hr - 10.0) / 7.0 * math.pi)
            elif 17.0 <= hr < 23.0:
                return 0.7 + 0.5 * math.sin((hr - 17.0) / 6.0 * math.pi)
            else:
                return 0.35
        elif pat == 'diurnal_commercial':
            # Commercial: 8:00 to 18:00 business peak, 0.35 baseline
            if 7.0 <= hr <= 19.0:
                return 0.4 + 0.65 * math.sin((hr - 7.0) / 12.0 * math.pi)
            return 0.35
        elif pat == 'random_walk':
            # Pseudo-random reproducible variation
            return 0.95 + 0.1 * math.sin(hr * 1.5)
        return 1.0  # 'flat'

    rows = []

    # 1. Generators
    for gid, gen in sorted(gens.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
        g_name = gen.get('name', f'Gen_{gid}')
        g_bus = gen.get('bus', '')
        base_p = float(gen.get('P_out', 0.0))
        base_q = float(gen.get('Q_out', 0.0))
        base_v = float(gen.get('V_set', 1.0))
        base_qmin = float(gen.get('Qmin', -999.0))
        base_qmax = float(gen.get('Qmax', 999.0))
        st = int(gen.get('status', 1))

        # Generator phase split
        if unbalance_mode == 'unbalanced_pct':
            fa, fb, fc = gen_pct[0] / 100.0, gen_pct[1] / 100.0, gen_pct[2] / 100.0
        else:
            fa = fb = fc = 1.0 / 3.0

        for pt in time_points:
            # If generator is solar/renewable, apply solar diurnal, else commercial/flat
            is_solar = any(k in g_name.lower() for k in ('solar', 'pv', 'sun', 'dg'))
            mult = get_time_multiplier(pt, 'diurnal_solar' if is_solar else pattern)

            p_now = base_p * mult
            q_now = base_q * mult

            pa, pb, pc = p_now * fa, p_now * fb, p_now * fc
            qa, qb, qc = q_now * fa, q_now * fb, q_now * fc

            rows.append([
                "GEN",
                gid,
                g_name,
                g_bus,
                pt['index'],
                pt['timestamp'],
                pt['label'],
                f"{pa:.3f}",
                f"{pb:.3f}",
                f"{pc:.3f}",
                f"{qa:.3f}",
                f"{qb:.3f}",
                f"{qc:.3f}",
                f"{base_v:.4f}",
                f"{base_v:.4f}",
                f"{base_v:.4f}",
                f"{base_qmin:.2f}",
                f"{base_qmax:.2f}",
                st
            ])

    # 2. Loads
    load_items = sorted(loads.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0]))
    for l_idx, (lid, load) in enumerate(load_items):
        l_name = load.get('name', f'Load_{lid}')
        l_bus = load.get('bus', '')
        base_p = float(load.get('P_demand', 0.0))
        base_q = float(load.get('Q_demand', 0.0))
        st = int(load.get('status', 1))

        # Determine phase assignment
        if unbalance_mode == 'single_phase_lateral':
            # Assign load cyclic to Phase A (mod 0), Phase B (mod 1), Phase C (mod 2)
            ph_sel = l_idx % 3
            if ph_sel == 0: fa, fb, fc = 1.0, 0.0, 0.0
            elif ph_sel == 1: fa, fb, fc = 0.0, 1.0, 0.0
            else: fa, fb, fc = 0.0, 0.0, 1.0
        elif unbalance_mode == 'unbalanced_pct':
            fa, fb, fc = load_pct[0] / 100.0, load_pct[1] / 100.0, load_pct[2] / 100.0
        else:  # balanced
            fa = fb = fc = 1.0 / 3.0

        for pt in time_points:
            mult = get_time_multiplier(pt, pattern)
            p_now = base_p * mult
            q_now = base_q * mult

            pa, pb, pc = p_now * fa, p_now * fb, p_now * fc
            qa, qb, qc = q_now * fa, q_now * fb, q_now * fc

            rows.append([
                "LOAD",
                lid,
                l_name,
                l_bus,
                pt['index'],
                pt['timestamp'],
                pt['label'],
                f"{pa:.3f}",
                f"{pb:.3f}",
                f"{pc:.3f}",
                f"{qa:.3f}",
                f"{qb:.3f}",
                f"{qc:.3f}",
                "", "", "",  # V_set
                "", "",      # Qmin/Qmax
                st
            ])

    # 3. Capacitors
    for cid, cap in sorted(caps.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
        c_name = cap.get('name', f'Cap_{cid}')
        c_bus = cap.get('bus', '')
        base_q = float(cap.get('Q_cap', 0.0))
        st = int(cap.get('status', 1))
        q_ph = base_q / 3.0

        for pt in time_points:
            rows.append([
                "CAPACITOR",
                cid,
                c_name,
                c_bus,
                pt['index'],
                pt['timestamp'],
                pt['label'],
                "", "", "",  # P
                f"{q_ph:.3f}", f"{q_ph:.3f}", f"{q_ph:.3f}",
                "", "", "",  # V_set
                "", "",      # Qmin/Qmax
                st
            ])

    # 4. Reactors
    for rid, rct in sorted(reacts.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
        r_name = rct.get('name', f'Reactor_{rid}')
        r_bus = rct.get('bus', '')
        base_q = float(rct.get('Q_react', 0.0))
        st = int(rct.get('status', 1))
        q_ph = base_q / 3.0

        for pt in time_points:
            rows.append([
                "REACTOR",
                rid,
                r_name,
                r_bus,
                pt['index'],
                pt['timestamp'],
                pt['label'],
                "", "", "",  # P
                f"{q_ph:.3f}", f"{q_ph:.3f}", f"{q_ph:.3f}",
                "", "", "",  # V_set
                "", "",      # Qmin/Qmax
                st
            ])

    # 5. Shunts
    for sid, sh in sorted(shunts.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
        s_name = sh.get('name', f'Shunt_{sid}')
        s_bus = sh.get('bus', '')
        base_q = float(sh.get('Q_shunt', 0.0))
        st = int(sh.get('status', 1))
        q_ph = base_q / 3.0

        for pt in time_points:
            rows.append([
                "SHUNT",
                sid,
                s_name,
                s_bus,
                pt['index'],
                pt['timestamp'],
                pt['label'],
                "", "", "",  # P
                f"{q_ph:.3f}", f"{q_ph:.3f}", f"{q_ph:.3f}",
                "", "", "",  # V_set
                "", "",      # Qmin/Qmax
                st
            ])

    if output_path:
        with open(output_path, "w", newline="", encoding="utf-8") as fp:
            writer = csv.writer(fp)
            writer.writerow(UNIVERSAL_3PHASE_CSV_HEADERS)
            writer.writerows(rows)

    return rows


def parse_universal_csv(csv_file_path, total_steps=24, imputation_method="linear", known_elements=None):
    """
    Parses a Universal Time Series CSV file (both 1-Phase and 3-Phase formats)
    and structures profiles by component.
    Performs smart matching against known database elements (by ID or by Name).
    Returns: (profiles_dict, stats_dict)
    """
    if not os.path.exists(csv_file_path):
        raise FileNotFoundError(f"Universal CSV file not found: {csv_file_path}")

    profiles = {
        'generators': {},
        'loads': {},
        'capacitors': {},
        'reactors': {},
        'shunts': {}
    }

    stats = {
        'matched_elements': set(),
        'skipped_unmatched': set(),
        'missing_database_elements': set()
    }

    # Build lookup table for known database elements if provided
    name_lookup = {'generators': {}, 'loads': {}, 'capacitors': {}, 'reactors': {}, 'shunts': {}}
    id_set = {'generators': set(), 'loads': set(), 'capacitors': set(), 'reactors': set(), 'shunts': set()}

    if known_elements and isinstance(known_elements, dict):
        for grp in ('generators', 'loads', 'capacitors', 'reactors', 'shunts'):
            e_dict = known_elements.get(grp, {})
            for eid, e_obj in e_dict.items():
                id_set[grp].add(str(eid))
                try: id_set[grp].add(int(eid))
                except (ValueError, TypeError): pass

                e_name = str(e_obj.get('name', '')).strip().lower()
                if e_name:
                    name_lookup[grp][e_name] = eid

    with open(csv_file_path, "r", encoding="utf-8", errors="ignore") as fp:
        reader = csv.reader(fp)
        raw_rows = [r for r in reader if r and len(r) >= 5]

    if not raw_rows:
        return (profiles, stats) if known_elements is not None else profiles

    # Header parsing
    header = [c.strip().lower() for c in raw_rows[0]]

    def get_col(name_candidates):
        for c in name_candidates:
            if c.lower() in header:
                return header.index(c.lower())
        return None

    c_type = get_col(['element_type', 'type', 'category'])
    c_id = get_col(['element_id', 'id', 'num', 'number'])
    c_name = get_col(['element_name', 'name', 'label'])
    c_step = get_col(['time_step', 'step', 'step_index'])

    # Single-Phase columns
    c_p = get_col(['p_mw', 'p', 'p_out', 'p_demand', 'mw'])
    c_q = get_col(['q_mvar', 'q', 'q_out', 'q_demand', 'q_cap', 'q_react', 'q_shunt', 'mvar'])
    c_v = get_col(['v_set_pu', 'v_set', 'v_pu', 'v'])
    c_qmin = get_col(['qmin_mvar', 'qmin'])
    c_qmax = get_col(['qmax_mvar', 'qmax'])

    # 3-Phase Columns
    c_pa = get_col(['pa_mw', 'pa', 'p_a', 'p_phase_a'])
    c_pb = get_col(['pb_mw', 'pb', 'p_b', 'p_phase_b'])
    c_pc = get_col(['pc_mw', 'pc', 'p_c', 'p_phase_c'])
    c_qa = get_col(['qa_mvar', 'qa', 'q_a', 'q_phase_a'])
    c_qb = get_col(['qb_mvar', 'qb', 'q_b', 'q_phase_b'])
    c_qc = get_col(['qc_mvar', 'qc', 'q_c', 'q_phase_c'])
    c_va = get_col(['va_set_pu', 'va_set', 'va_pu', 'va'])
    c_vb = get_col(['vb_set_pu', 'vb_set', 'vb_pu', 'vb'])
    c_vc = get_col(['vc_set_pu', 'vc_set', 'vc_pu', 'vc'])

    has_3phase_cols = (c_pa is not None or c_pb is not None or c_pc is not None)

    # Temporary storage: (type, resolved_id) -> {'P': {step: val}, 'Q': {step: val}, ...}
    grouped = {}

    for row in raw_rows[1:]:
        t_val = row[c_type].strip().upper() if c_type is not None and c_type < len(row) else "GEN"
        id_raw = row[c_id].strip() if c_id is not None and c_id < len(row) else "1"
        name_raw = row[c_name].strip() if c_name is not None and c_name < len(row) else ""

        # Determine target group key
        if "GEN" in t_val: grp = "generators"
        elif "LOAD" in t_val: grp = "loads"
        elif "CAP" in t_val: grp = "capacitors"
        elif "REAC" in t_val: grp = "reactors"
        elif "SHUNT" in t_val: grp = "shunts"
        else: grp = "generators"

        # Resolve element ID against loaded database if known_elements was passed
        resolved_id = id_raw
        try:
            int_id = int(id_raw)
        except ValueError:
            int_id = None

        if known_elements and isinstance(known_elements, dict) and id_set[grp]:
            if int_id is not None and int_id in id_set[grp]:
                resolved_id = int_id
            elif str(id_raw) in id_set[grp]:
                resolved_id = id_raw
            elif name_raw.lower() in name_lookup[grp]:
                resolved_id = name_lookup[grp][name_raw.lower()]
            else:
                # Element not present in loaded database
                stats['skipped_unmatched'].add(f"{grp.upper()[:-1]} ID={id_raw} ('{name_raw}')")
                continue
        else:
            resolved_id = int_id if int_id is not None else id_raw

        stats['matched_elements'].add((grp, resolved_id))

        step_idx = None
        if c_step is not None and c_step < len(row) and row[c_step].strip().isdigit():
            step_idx = int(row[c_step].strip())

        key = (grp, resolved_id)
        if key not in grouped:
            grouped[key] = {
                'P': {}, 'Q': {}, 'V_set': {}, 'Qmin': {}, 'Qmax': {},
                'Pa': {}, 'Pb': {}, 'Pc': {},
                'Qa': {}, 'Qb': {}, 'Qc': {},
                'Va_set': {}, 'Vb_set': {}, 'Vc_set': {}
            }

        if step_idx is not None and 0 <= step_idx < total_steps:
            # 1-Phase parsing
            if c_p is not None and c_p < len(row) and row[c_p].strip():
                try: grouped[key]['P'][step_idx] = float(row[c_p].strip())
                except ValueError: pass

            if c_q is not None and c_q < len(row) and row[c_q].strip():
                try: grouped[key]['Q'][step_idx] = float(row[c_q].strip())
                except ValueError: pass

            if c_v is not None and c_v < len(row) and row[c_v].strip():
                try: grouped[key]['V_set'][step_idx] = float(row[c_v].strip())
                except ValueError: pass

            if c_qmin is not None and c_qmin < len(row) and row[c_qmin].strip():
                try: grouped[key]['Qmin'][step_idx] = float(row[c_qmin].strip())
                except ValueError: pass

            if c_qmax is not None and c_qmax < len(row) and row[c_qmax].strip():
                try: grouped[key]['Qmax'][step_idx] = float(row[c_qmax].strip())
                except ValueError: pass

            # 3-Phase parsing
            if c_pa is not None and c_pa < len(row) and row[c_pa].strip():
                try: grouped[key]['Pa'][step_idx] = float(row[c_pa].strip())
                except ValueError: pass
            if c_pb is not None and c_pb < len(row) and row[c_pb].strip():
                try: grouped[key]['Pb'][step_idx] = float(row[c_pb].strip())
                except ValueError: pass
            if c_pc is not None and c_pc < len(row) and row[c_pc].strip():
                try: grouped[key]['Pc'][step_idx] = float(row[c_pc].strip())
                except ValueError: pass

            if c_qa is not None and c_qa < len(row) and row[c_qa].strip():
                try: grouped[key]['Qa'][step_idx] = float(row[c_qa].strip())
                except ValueError: pass
            if c_qb is not None and c_qb < len(row) and row[c_qb].strip():
                try: grouped[key]['Qb'][step_idx] = float(row[c_qb].strip())
                except ValueError: pass
            if c_qc is not None and c_qc < len(row) and row[c_qc].strip():
                try: grouped[key]['Qc'][step_idx] = float(row[c_qc].strip())
                except ValueError: pass

            if c_va is not None and c_va < len(row) and row[c_va].strip():
                try: grouped[key]['Va_set'][step_idx] = float(row[c_va].strip())
                except ValueError: pass
            if c_vb is not None and c_vb < len(row) and row[c_vb].strip():
                try: grouped[key]['Vb_set'][step_idx] = float(row[c_vb].strip())
                except ValueError: pass
            if c_vc is not None and c_vc < len(row) and row[c_vc].strip():
                try: grouped[key]['Vc_set'][step_idx] = float(row[c_vc].strip())
                except ValueError: pass

            # Cross-populate P / Q if only 3-phase columns were given
            if step_idx not in grouped[key]['P'] and step_idx in grouped[key]['Pa']:
                pa = grouped[key]['Pa'].get(step_idx, 0.0)
                pb = grouped[key]['Pb'].get(step_idx, 0.0)
                pc = grouped[key]['Pc'].get(step_idx, 0.0)
                grouped[key]['P'][step_idx] = pa + pb + pc

            if step_idx not in grouped[key]['Q'] and step_idx in grouped[key]['Qa']:
                qa = grouped[key]['Qa'].get(step_idx, 0.0)
                qb = grouped[key]['Qb'].get(step_idx, 0.0)
                qc = grouped[key]['Qc'].get(step_idx, 0.0)
                grouped[key]['Q'][step_idx] = qa + qb + qc

    # Apply imputation & build full arrays
    for (grp, elem_id), p_map in grouped.items():
        elem_profile = {}
        for param, s_dict in p_map.items():
            if not s_dict:
                elem_profile[param] = None
            else:
                k_idx = sorted(s_dict.keys())
                k_val = [s_dict[i] for i in k_idx]
                def_v = k_val[0] if k_val else (1.0 if 'v' in param.lower() else 0.0)
                full_curve = TimeSeriesImputer.impute_series(
                    k_idx, k_val, total_steps, method=imputation_method, default_base_val=def_v
                )
                elem_profile[param] = full_curve

        profiles[grp][elem_id] = elem_profile

    # Calculate missing elements from DB that were not in CSV
    if known_elements and isinstance(known_elements, dict):
        for grp in ('generators', 'loads', 'capacitors', 'reactors', 'shunts'):
            for db_id in known_elements.get(grp, {}).keys():
                if (grp, db_id) not in stats['matched_elements'] and (grp, str(db_id)) not in stats['matched_elements']:
                    stats['missing_database_elements'].add((grp, db_id))

    if known_elements is not None:
        return profiles, stats
    return profiles

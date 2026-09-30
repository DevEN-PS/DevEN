"""
Core Conversion Engine for DevEN Power System Databases:
- .py -> SQLite (single unified database container)
- SQLite -> .py (export / extraction)
- Batch folder / multi-file conversion
- Direct Dictionary Loading for DevEN App UI
"""

import sys
import os
import sqlite3
import json
import importlib.util
import datetime

cur_dir = os.path.dirname(os.path.abspath(__file__))
if cur_dir not in sys.path:
    sys.path.insert(0, cur_dir)

try:
    from .schema import create_tables
except ImportError:
    from schema import create_tables


def _to_float(val, default=0.0):
    """Safely converts val to float without raising ValueError/TypeError."""
    try:
        if val is None or isinstance(val, (dict, list, tuple)):
            return default
        return float(val)
    except (ValueError, TypeError):
        return default


def _to_int(val, default=1):
    """Safely converts val to int without raising ValueError/TypeError."""
    try:
        if val is None or isinstance(val, (dict, list, tuple)):
            return default
        return int(float(val))
    except (ValueError, TypeError):
        return default


def load_py_db_file(file_path):
    """Dynamically loads and parses a .py database file into standard data structures."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Python database file not found: {file_path}")

    # Use a unique module name per file
    mod_name = f"dynamic_db_{abs(hash(file_path))}"
    spec = importlib.util.spec_from_file_location(mod_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load python module from {file_path}")
    
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    sim_cfg = getattr(mod, 'SIMULATION_SETTINGS', getattr(mod, 'SOLVER_CONFIG', {}))
    data = {
        'base_mva': getattr(mod, 'BASE_MVA', 100.0),
        'map_settings': getattr(mod, 'MAP_SETTINGS', {}),
        'solver_config': sim_cfg,
        'simulation_settings': sim_cfg,
        'bus_data': getattr(mod, 'BUS_DATA', []),
        'generator_data': getattr(mod, 'GENERATOR_DATA', []),
        'load_data': getattr(mod, 'LOAD_DATA', []),
        'line_data': getattr(mod, 'LINE_DATA', []),
        'transformer_data': getattr(mod, 'TRANSFORMER_DATA', []),
        'three_w_xfmr_data': getattr(mod, 'THREE_WINDING_TRANSFORMER_DATA', getattr(mod, 'THREE_WINDING_XFMR_DATA', [])),
        'capacitor_data': getattr(mod, 'CAPACITOR_DATA', []),
        'reactor_data': getattr(mod, 'REACTOR_DATA', []),
        'series_comp_data': getattr(mod, 'SERIES_COMP_DATA', []),
        'series_reactor_data': getattr(mod, 'SERIES_REACTOR_DATA', []),
        'shunt_data': getattr(mod, 'SHUNT_DATA', []),
        'harmonic_sources': getattr(mod, 'HARMONIC_SOURCE_DATA', getattr(mod, 'HARMONIC_SOURCES', [])),
        'harmonic_filters': getattr(mod, 'HARMONIC_FILTER_DATA', getattr(mod, 'HARMONIC_FILTERS', [])),
        'fault_cases': getattr(mod, 'FAULT_ON_SELECTED_BUSES', getattr(mod, 'FAULT_CASES_DATA', [])),
        'line_voltage_factors': getattr(mod, 'TRANSMISSION_LINE_ZERO_SEQ_FACTORS', []),
        'global_factors': getattr(mod, 'GLOBAL_SEQUENCE_CORRECTION_FACTORS', {}),
        'sld_json': None
    }

    # Check for accompanying .sld file
    sld_path = os.path.splitext(file_path)[0] + ".sld"
    if os.path.exists(sld_path):
        try:
            with open(sld_path, 'r', encoding='utf-8') as sf:
                data['sld_json'] = sf.read()
        except Exception:
            pass

    return data


def generate_next_project_id(conn):
    """Finds the next integer project_id or creates an initial ID."""
    cur = conn.cursor()
    try:
        cur.execute("SELECT project_id FROM projects")
        rows = cur.fetchall()
        max_id = 0
        for (pid,) in rows:
            try:
                numeric_val = int(pid)
                if numeric_val > max_id:
                    max_id = numeric_val
            except ValueError:
                pass
        return str(max_id + 1)
    except Exception:
        return "1"


def py_to_sqlite(source_data_or_path, sqlite_db_path, project_name=None, project_id=None, description="", replace_existing=True):
    """
    Converts a .py database file or in-memory dict data into SQLite database.
    """
    if isinstance(source_data_or_path, str):
        data = load_py_db_file(source_data_or_path)
        if not project_name:
            project_name = os.path.splitext(os.path.basename(source_data_or_path))[0]
    elif isinstance(source_data_or_path, dict):
        data = source_data_or_path
        if not project_name:
            project_name = data.get('project_name', 'Power_System_Project')
    else:
        raise ValueError("source_data_or_path must be a file path string or data dictionary.")

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    os.makedirs(os.path.dirname(os.path.abspath(sqlite_db_path)), exist_ok=True)
    conn = sqlite3.connect(sqlite_db_path)
    try:
        create_tables(conn)
        cur = conn.cursor()

        if not project_id:
            project_id = generate_next_project_id(conn)
        else:
            project_id = str(project_id).strip()

        # Check if project_id exists
        cur.execute("SELECT project_id FROM projects WHERE project_id = ?", (project_id,))
        exists = cur.fetchone() is not None

        if exists:
            if replace_existing:
                delete_project_records(conn, project_id)
            else:
                raise ValueError(f"Project ID '{project_id}' already exists in SQLite DB. Set replace_existing=True or use a different ID.")

        # 1. Insert Project Master Record
        cur.execute("""
            INSERT OR REPLACE INTO projects (
                project_id, project_name, description, base_mva, created_at, updated_at,
                solver_config_json, map_settings_json, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            project_id,
            project_name,
            description or "",
            float(data.get('base_mva', 100.0)),
            now_str,
            now_str,
            json.dumps(data.get('solver_config', {})),
            json.dumps(data.get('map_settings', {})),
            json.dumps(data.get('metadata', {}))
        ))

        # 2. Insert Buses
        bus_rows = data.get('bus_data') if data.get('bus_data') is not None else data.get('buses', [])
        bus_insert_data = []
        if isinstance(bus_rows, dict):
            for b_id, b in bus_rows.items():
                bus_insert_data.append((
                    project_id, _to_int(b_id, 1), str(b.get('name', f'Bus_{b_id}')), _to_int(b.get('type', 3), 3),
                    _to_float(b.get('base_kV', 132.0), 132.0), _to_float(b.get('V_init', 1.0), 1.0), _to_float(b.get('angle_init', 0.0), 0.0),
                    _to_float(b.get('shunt_G', 0.0), 0.0), _to_float(b.get('shunt_B', 0.0), 0.0),
                    _to_int(b.get('area', 1), 1), _to_int(b.get('zone', 1), 1), _to_int(b.get('owner', 1), 1),
                    _to_float(b.get('lat', 0.0), 0.0), _to_float(b.get('long', 0.0), 0.0),
                    _to_float(b.get('sk_mva', 1000.0), 1000.0), _to_float(b.get('rx_ratio', 0.1), 0.1), _to_float(b.get('z01_ratio', 1.0), 1.0)
                ))
        else:
            for r in bus_rows:
                if len(r) >= 6:
                    bus_insert_data.append((
                        project_id, _to_int(r[0]), str(r[1]), _to_int(r[2], 3), _to_float(r[3], 132.0), _to_float(r[4], 1.0), _to_float(r[5], 0.0),
                        _to_float(r[6], 0.0) if len(r) > 6 else 0.0,
                        _to_float(r[7], 0.0) if len(r) > 7 else 0.0,
                        _to_int(r[8], 1) if len(r) > 8 else 1,
                        _to_int(r[9], 1) if len(r) > 9 else 1,
                        _to_int(r[10], 1) if len(r) > 10 else 1,
                        _to_float(r[11], 0.0) if len(r) > 11 else 0.0,
                        _to_float(r[12], 0.0) if len(r) > 12 else 0.0,
                        _to_float(r[13], 1000.0) if len(r) > 13 else 1000.0,
                        _to_float(r[14], 0.1) if len(r) > 14 else 0.1,
                        _to_float(r[15], 1.0) if len(r) > 15 else 1.0
                    ))

        if bus_insert_data:
            cur.executemany("""
                INSERT OR REPLACE INTO buses (
                    project_id, bus_id, name, type, base_kV, V_init, angle_init,
                    shunt_G, shunt_B, area, zone, owner, lat, long, sk_mva, rx_ratio, z01_ratio
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, bus_insert_data)

        # 3. Insert Generators
        gen_rows = data.get('generator_data') if data.get('generator_data') is not None else data.get('generators', [])
        gen_insert_data = []
        if isinstance(gen_rows, dict):
            for g_id, g in gen_rows.items():
                gen_insert_data.append((
                    project_id, _to_int(g_id, 1), str(g.get('name', f'Gen_{g_id}')), str(g.get('type', 'Thermal')),
                    _to_int(g.get('bus', 1), 1), _to_float(g.get('P_out', g.get('P_gen', g.get('P', 0.0)))), _to_float(g.get('Q_out', g.get('Q_gen', g.get('Q', 0.0)))),
                    _to_float(g.get('V_set', g.get('V', 1.0)), 1.0), _to_float(g.get('Qmin', -9999.0), -9999.0), _to_float(g.get('Qmax', 9999.0), 9999.0),
                    _to_int(g.get('status', 1), 1), _to_int(g.get('area', 1), 1), _to_int(g.get('zone', 1), 1), _to_int(g.get('owner', 1), 1),
                    _to_float(g.get('R1_pu', 0.0)), _to_float(g.get('X1_pu', 0.0)), _to_float(g.get('R2_pu', 0.0)), _to_float(g.get('X2_pu', 0.0)),
                    _to_float(g.get('R0_pu', 0.0)), _to_float(g.get('X0_pu', 0.0)), _to_float(g.get('cb_mva', 0.0)), str(g.get('wind_conn', '0')),
                    _to_float(g.get('gnd_r', 0.0)), _to_float(g.get('gnd_x', 0.0))
                ))
        else:
            for r in gen_rows:
                if len(r) >= 10:
                    gen_insert_data.append((
                        project_id, _to_int(r[0]), str(r[1]), str(r[2]), _to_int(r[3], 1), _to_float(r[4]), _to_float(r[5]),
                        _to_float(r[6], 1.0), _to_float(r[7], -9999.0), _to_float(r[8], 9999.0), _to_int(r[9], 1),
                        _to_int(r[10], 1) if len(r) > 10 else 1,
                        _to_int(r[11], 1) if len(r) > 11 else 1,
                        _to_int(r[12], 1) if len(r) > 12 else 1,
                        _to_float(r[13], 0.0) if len(r) > 13 else 0.0,
                        _to_float(r[14], 0.0) if len(r) > 14 else 0.0,
                        _to_float(r[15], 0.0) if len(r) > 15 else 0.0,
                        _to_float(r[16], 0.0) if len(r) > 16 else 0.0,
                        _to_float(r[17], 0.0) if len(r) > 17 else 0.0,
                        _to_float(r[18], 0.0) if len(r) > 18 else 0.0,
                        _to_float(r[19], 0.0) if len(r) > 19 else 0.0,
                        str(r[20]) if len(r) > 20 else '0',
                        _to_float(r[21], 0.0) if len(r) > 21 else 0.0,
                        _to_float(r[22], 0.0) if len(r) > 22 else 0.0
                    ))

        if gen_insert_data:
            cur.executemany("""
                INSERT OR REPLACE INTO generators (
                    project_id, gen_id, name, type, bus, P_out, Q_out, V_set, Qmin, Qmax,
                    status, area, zone, owner, R1_pu, X1_pu, R2_pu, X2_pu, R0_pu, X0_pu, cb_mva, wind_conn,
                    gnd_r, gnd_x
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, gen_insert_data)

        # 4. Insert Loads
        load_rows = data.get('load_data') if data.get('load_data') is not None else data.get('loads', [])
        load_insert_data = []
        if isinstance(load_rows, dict):
            for l_id, l in load_rows.items():
                load_insert_data.append((
                    project_id, _to_int(l_id, 1), str(l.get('name', f'Load_{l_id}')), _to_int(l.get('bus', 1), 1),
                    _to_float(l.get('P_demand', l.get('P_load', l.get('P', 0.0)))), _to_float(l.get('Q_demand', l.get('Q_load', l.get('Q', 0.0)))), str(l.get('model', 'Constant Power')),
                    _to_int(l.get('area', 1), 1), _to_int(l.get('zone', 1), 1), _to_float(l.get('cb_mva', 0.0)), str(l.get('wind_conn', '0'))
                ))
        else:
            for r in load_rows:
                if len(r) >= 6:
                    load_insert_data.append((
                        project_id, _to_int(r[0]), str(r[1]), _to_int(r[2], 1), _to_float(r[3]), _to_float(r[4]), str(r[5]),
                        _to_int(r[6], 1) if len(r) > 6 else 1,
                        _to_int(r[7], 1) if len(r) > 7 else 1,
                        _to_float(r[8], 0.0) if len(r) > 8 else 0.0,
                        str(r[9]) if len(r) > 9 else '0'
                    ))

        if load_insert_data:
            cur.executemany("""
                INSERT OR REPLACE INTO loads (
                    project_id, load_id, name, bus, P_demand, Q_demand, model, area, zone, cb_mva, wind_conn
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, load_insert_data)

        # 5. Insert Transmission Lines
        line_rows = data.get('line_data') if data.get('line_data') is not None else data.get('lines', [])
        line_insert_data = []
        if isinstance(line_rows, dict):
            for ln_id, ln in line_rows.items():
                line_insert_data.append((
                    project_id, _to_int(ln_id, 1), str(ln.get('name', f'Line_{ln_id}')), _to_int(ln.get('from_bus', 1), 1), _to_int(ln.get('to_bus', 2), 2),
                    _to_float(ln.get('length_km', 0.0)), _to_float(ln.get('R_per_km', ln.get('r', 0.0))), _to_float(ln.get('X_per_km', ln.get('x', 0.0))), _to_float(ln.get('B_per_km', ln.get('b', 0.0))),
                    _to_float(ln.get('rateA', 0.0)), _to_int(ln.get('status', 1), 1), _to_int(ln.get('area', 1), 1), _to_int(ln.get('zone', 1), 1), _to_int(ln.get('owner', 1), 1),
                    _to_float(ln.get('R0_per_km', 0.0)), _to_float(ln.get('X0_per_km', 0.0)), _to_float(ln.get('B0_per_km', 0.0)),
                    _to_float(ln.get('from_cb_mva', 0.0)), _to_float(ln.get('to_cb_mva', 0.0)),
                    json.dumps(ln.get('bends', []))
                ))
        else:
            for r in line_rows:
                if len(r) >= 8:
                    line_insert_data.append((
                        project_id, _to_int(r[0]), str(r[1]), _to_int(r[2], 1), _to_int(r[3], 2), _to_float(r[4]), _to_float(r[5]), _to_float(r[6]), _to_float(r[7]),
                        _to_float(r[8], 0.0) if len(r) > 8 else 0.0,
                        _to_int(r[9], 1) if len(r) > 9 else 1,
                        _to_int(r[10], 1) if len(r) > 10 else 1,
                        _to_int(r[11], 1) if len(r) > 11 else 1,
                        _to_int(r[12], 1) if len(r) > 12 else 1,
                        _to_float(r[13], 0.0) if len(r) > 13 else 0.0,
                        _to_float(r[14], 0.0) if len(r) > 14 else 0.0,
                        _to_float(r[15], 0.0) if len(r) > 15 else 0.0,
                        _to_float(r[16], 0.0) if len(r) > 16 else 0.0,
                        _to_float(r[17], 0.0) if len(r) > 17 else 0.0,
                        json.dumps([])
                    ))

        if line_insert_data:
            cur.executemany("""
                INSERT OR REPLACE INTO lines (
                    project_id, line_id, name, from_bus, to_bus, length_km, R_per_km, X_per_km, B_per_km,
                    rateA, status, area, zone, owner, R0_per_km, X0_per_km, B0_per_km, from_cb_mva, to_cb_mva, bends_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, line_insert_data)

        # 6. Insert Transformers
        xfmr_rows = data.get('transformer_data') if data.get('transformer_data') is not None else data.get('transformers', [])
        xfmr_insert_data = []
        if isinstance(xfmr_rows, dict):
            for x_id, xf in xfmr_rows.items():
                xfmr_insert_data.append((
                    project_id, _to_int(x_id, 1), str(xf.get('name', f'Xfmr_{x_id}')), _to_int(xf.get('from_bus', 1), 1), _to_int(xf.get('to_bus', 2), 2),
                    _to_float(xf.get('r', xf.get('R_pu', 0.0))), _to_float(xf.get('x', xf.get('X_pu', 0.05)), 0.05), _to_float(xf.get('tap_ratio', xf.get('ratio', xf.get('tap', 1.0))), 1.0), _to_float(xf.get('rateA', 9999.0), 9999.0),
                    _to_float(xf.get('phase_shift', 0.0)), _to_float(xf.get('min_tap', 0.9), 0.9), _to_float(xf.get('max_tap', 1.1), 1.1), _to_float(xf.get('step_size', 0.01), 0.01),
                    _to_int(xf.get('status', 1), 1), _to_int(xf.get('area', 1), 1), _to_int(xf.get('zone', 1), 1), _to_int(xf.get('owner', 1), 1),
                    _to_float(xf.get('R0_pu', 0.0)), _to_float(xf.get('X0_pu', 0.0)), str(xf.get('from_conn', '0')), str(xf.get('to_conn', '0')),
                    _to_float(xf.get('from_gnd_r', 0.0)), _to_float(xf.get('from_gnd_x', 0.0)), _to_float(xf.get('to_gnd_r', 0.0)), _to_float(xf.get('to_gnd_x', 0.0)),
                    _to_float(xf.get('from_cb_mva', 0.0)), _to_float(xf.get('to_cb_mva', 0.0))
                ))
        else:
            for r in xfmr_rows:
                if len(r) >= 6:
                    xfmr_insert_data.append((
                        project_id, _to_int(r[0]), str(r[1]), _to_int(r[2], 1), _to_int(r[3], 2), _to_float(r[4]), _to_float(r[5], 0.05),
                        _to_float(r[6], 1.0) if len(r) > 6 else 1.0,
                        _to_float(r[7], 9999.0) if len(r) > 7 else 9999.0,
                        _to_float(r[8], 0.0) if len(r) > 8 else 0.0,
                        _to_float(r[9], 0.9) if len(r) > 9 else 0.9,
                        _to_float(r[10], 1.1) if len(r) > 10 else 1.1,
                        _to_float(r[11], 0.01) if len(r) > 11 else 0.01,
                        _to_int(r[12], 1) if len(r) > 12 else 1,
                        _to_int(r[13], 1) if len(r) > 13 else 1,
                        _to_int(r[14], 1) if len(r) > 14 else 1,
                        _to_int(r[15], 1) if len(r) > 15 else 1,
                        _to_float(r[16], 0.0) if len(r) > 16 else 0.0,
                        _to_float(r[17], 0.0) if len(r) > 17 else 0.0,
                        str(r[18]) if len(r) > 18 else '0',
                        str(r[19]) if len(r) > 19 else '0',
                        _to_float(r[20], 0.0) if len(r) > 20 else 0.0,
                        _to_float(r[21], 0.0) if len(r) > 21 else 0.0,
                        _to_float(r[22], 0.0) if len(r) > 22 else 0.0,
                        _to_float(r[23], 0.0) if len(r) > 23 else 0.0,
                        _to_float(r[24], 0.0) if len(r) > 24 else 0.0,
                        _to_float(r[25], 0.0) if len(r) > 25 else 0.0
                    ))

        if xfmr_insert_data:
            cur.executemany("""
                INSERT OR REPLACE INTO transformers (
                    project_id, xfmr_id, name, from_bus, to_bus, r, x, tap_ratio, rateA, phase_shift,
                    min_tap, max_tap, step_size, status, area, zone, owner, R0_pu, X0_pu,
                    from_conn, to_conn, from_gnd_r, from_gnd_x, to_gnd_r, to_gnd_x, from_cb_mva, to_cb_mva
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, xfmr_insert_data)

        # 7. Insert Three-Winding Transformers
        tw_rows = data.get('three_w_xfmr_data') if data.get('three_w_xfmr_data') is not None else (data.get('three_winding_transformers') or data.get('three_winding_xfmrs', []))
        tw_insert_data = []
        if isinstance(tw_rows, dict):
            for t_id, tw in tw_rows.items():
                tw_insert_data.append((
                    project_id, _to_int(t_id, 1), str(tw.get('name', f'3WXfmr_{t_id}')), _to_int(tw.get('hv_bus', 1), 1), _to_int(tw.get('mv_bus', 2), 2), _to_int(tw.get('lv_bus', 3), 3),
                    _to_float(tw.get('r_hm', 0.0)), _to_float(tw.get('x_hm', 0.05), 0.05), _to_float(tw.get('r_hl', 0.0)), _to_float(tw.get('x_hl', 0.05), 0.05),
                    _to_float(tw.get('r_ml', 0.0)), _to_float(tw.get('x_ml', 0.05), 0.05),
                    _to_float(tw.get('rate_h', 9999.0), 9999.0), _to_float(tw.get('rate_m', 9999.0), 9999.0), _to_float(tw.get('rate_l', 9999.0), 9999.0),
                    _to_float(tw.get('tap_h', 1.0), 1.0), _to_float(tw.get('tap_m', 1.0), 1.0), _to_float(tw.get('tap_l', 1.0), 1.0),
                    _to_int(tw.get('status', 1), 1), _to_int(tw.get('area', 1), 1), _to_int(tw.get('zone', 1), 1), _to_int(tw.get('owner', 1), 1)
                ))
        else:
            for r in tw_rows:
                if len(r) >= 5:
                    tw_insert_data.append((
                        project_id, _to_int(r[0]), str(r[1]), _to_int(r[2], 1), _to_int(r[3], 2), _to_int(r[4], 3),
                        _to_float(r[5], 0.0) if len(r) > 5 else 0.0,
                        _to_float(r[6], 0.05) if len(r) > 6 else 0.05,
                        _to_float(r[7], 0.0) if len(r) > 7 else 0.0,
                        _to_float(r[8], 0.05) if len(r) > 8 else 0.05,
                        _to_float(r[9], 0.0) if len(r) > 9 else 0.0,
                        _to_float(r[10], 0.05) if len(r) > 10 else 0.05,
                        _to_float(r[11], 9999.0) if len(r) > 11 else 9999.0,
                        _to_float(r[12], 9999.0) if len(r) > 12 else 9999.0,
                        _to_float(r[13], 9999.0) if len(r) > 13 else 9999.0,
                        _to_float(r[14], 1.0) if len(r) > 14 else 1.0,
                        _to_float(r[15], 1.0) if len(r) > 15 else 1.0,
                        _to_float(r[16], 1.0) if len(r) > 16 else 1.0,
                        _to_int(r[17], 1) if len(r) > 17 else 1,
                        _to_int(r[18], 1) if len(r) > 18 else 1,
                        _to_int(r[19], 1) if len(r) > 19 else 1,
                        _to_int(r[20], 1) if len(r) > 20 else 1
                    ))

        if tw_insert_data:
            cur.executemany("""
                INSERT OR REPLACE INTO three_winding_transformers (
                    project_id, tw_id, name, hv_bus, mv_bus, lv_bus,
                    r_hm, x_hm, r_hl, x_hl, r_ml, x_ml,
                    rate_h, rate_m, rate_l, tap_h, tap_m, tap_l,
                    status, area, zone, owner
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, tw_insert_data)

        # 8. Capacitors
        cap_rows = data.get('capacitor_data') if data.get('capacitor_data') is not None else data.get('capacitors', [])
        cap_insert_data = []
        if isinstance(cap_rows, dict):
            for c_id, c in cap_rows.items():
                cap_insert_data.append((
                    project_id, _to_int(c_id, 1), str(c.get('name', f'Cap_{c_id}')), _to_int(c.get('bus', 1), 1),
                    _to_float(c.get('Q_cap', 0.0)), _to_int(c.get('status', 1), 1), _to_int(c.get('area', 1), 1), _to_int(c.get('zone', 1), 1)
                ))
        else:
            for r in cap_rows:
                if len(r) >= 4:
                    cap_insert_data.append((
                        project_id, _to_int(r[0]), str(r[1]), _to_int(r[2], 1), _to_float(r[3]),
                        _to_int(r[4], 1) if len(r) > 4 else 1,
                        _to_int(r[5], 1) if len(r) > 5 else 1,
                        _to_int(r[6], 1) if len(r) > 6 else 1
                    ))
        if cap_insert_data:
            cur.executemany("INSERT OR REPLACE INTO capacitors (project_id, cap_id, name, bus, Q_cap, status, area, zone) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", cap_insert_data)

        # 9. Reactors
        react_rows = data.get('reactor_data') if data.get('reactor_data') is not None else data.get('reactors', [])
        react_insert_data = []
        if isinstance(react_rows, dict):
            for r_id, rc in react_rows.items():
                react_insert_data.append((
                    project_id, _to_int(r_id, 1), str(rc.get('name', f'Reactor_{r_id}')), _to_int(rc.get('bus', 1), 1),
                    _to_float(rc.get('Q_react', 0.0)), _to_int(rc.get('status', 1), 1), _to_int(rc.get('area', 1), 1), _to_int(rc.get('zone', 1), 1),
                    _to_float(rc.get('G1_pu', 0.0)), _to_float(rc.get('B1_pu', 0.0)), _to_float(rc.get('G0_pu', 0.0)), _to_float(rc.get('B0_pu', 0.0)),
                    _to_float(rc.get('cb_mva', 0.0))
                ))
        else:
            for r in react_rows:
                if len(r) >= 4:
                    react_insert_data.append((
                        project_id, _to_int(r[0]), str(r[1]), _to_int(r[2], 1), _to_float(r[3]),
                        _to_int(r[4], 1) if len(r) > 4 else 1,
                        _to_int(r[5], 1) if len(r) > 5 else 1,
                        _to_int(r[6], 1) if len(r) > 6 else 1,
                        _to_float(r[7], 0.0) if len(r) > 7 else 0.0,
                        _to_float(r[8], 0.0) if len(r) > 8 else 0.0,
                        _to_float(r[9], 0.0) if len(r) > 9 else 0.0,
                        _to_float(r[10], 0.0) if len(r) > 10 else 0.0,
                        _to_float(r[11], 0.0) if len(r) > 11 else 0.0
                    ))
        if react_insert_data:
            cur.executemany("""
                INSERT OR REPLACE INTO reactors (
                    project_id, reactor_id, name, bus, Q_react, status, area, zone, G1_pu, B1_pu, G0_pu, B0_pu, cb_mva
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, react_insert_data)

        # 10. Series Comps
        sc_rows = data.get('series_comp_data') if data.get('series_comp_data') is not None else data.get('series_comps', [])
        sc_insert_data = []
        if isinstance(sc_rows, dict):
            for s_id, sc in sc_rows.items():
                sc_insert_data.append((
                    project_id, _to_int(s_id, 1), str(sc.get('name', f'SC_{s_id}')), _to_int(sc.get('from_bus', 1), 1), _to_int(sc.get('to_bus', 2), 2),
                    _to_float(sc.get('r', 0.0)), _to_float(sc.get('x', 0.0)), _to_float(sc.get('comp_pct', 0.0)),
                    _to_int(sc.get('status', 1), 1), _to_int(sc.get('area', 1), 1), _to_int(sc.get('zone', 1), 1), _to_int(sc.get('owner', 1), 1)
                ))
        else:
            for r in sc_rows:
                if len(r) >= 7:
                    sc_insert_data.append((
                        project_id, _to_int(r[0]), str(r[1]), _to_int(r[2], 1), _to_int(r[3], 2), _to_float(r[4]), _to_float(r[5]), _to_float(r[6]),
                        _to_int(r[7], 1) if len(r) > 7 else 1,
                        _to_int(r[8], 1) if len(r) > 8 else 1,
                        _to_int(r[9], 1) if len(r) > 9 else 1,
                        _to_int(r[10], 1) if len(r) > 10 else 1
                    ))
        if sc_insert_data:
            cur.executemany("INSERT OR REPLACE INTO series_comps (project_id, sc_id, name, from_bus, to_bus, r, x, comp_pct, status, area, zone, owner) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", sc_insert_data)

        # 11. Series Reactors
        sr_rows = data.get('series_reactor_data') if data.get('series_reactor_data') is not None else data.get('series_reactors', [])
        sr_insert_data = []
        if isinstance(sr_rows, dict):
            for s_id, sr in sr_rows.items():
                sr_insert_data.append((
                    project_id, _to_int(s_id, 1), str(sr.get('name', f'SR_{s_id}')), _to_int(sr.get('from_bus', 1), 1), _to_int(sr.get('to_bus', 2), 2),
                    _to_float(sr.get('r', 0.0)), _to_float(sr.get('x', 0.0)),
                    _to_int(sr.get('status', 1), 1), _to_int(sr.get('area', 1), 1), _to_int(sr.get('zone', 1), 1), _to_int(sr.get('owner', 1), 1)
                ))
        else:
            for r in sr_rows:
                if len(r) >= 6:
                    sr_insert_data.append((
                        project_id, _to_int(r[0]), str(r[1]), _to_int(r[2], 1), _to_int(r[3], 2), _to_float(r[4]), _to_float(r[5]),
                        _to_int(r[6], 1) if len(r) > 6 else 1,
                        _to_int(r[7], 1) if len(r) > 7 else 1,
                        _to_int(r[8], 1) if len(r) > 8 else 1,
                        _to_int(r[9], 1) if len(r) > 9 else 1
                    ))
        if sr_insert_data:
            cur.executemany("INSERT OR REPLACE INTO series_reactors (project_id, sr_id, name, from_bus, to_bus, r, x, status, area, zone, owner) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", sr_insert_data)

        # 12. Shunts
        shunt_rows = data.get('shunt_data') if data.get('shunt_data') is not None else data.get('shunts', [])
        shunt_insert_data = []
        if isinstance(shunt_rows, dict):
            for sh_id, sh in shunt_rows.items():
                shunt_insert_data.append((
                    project_id, _to_int(sh_id, 1), str(sh.get('name', f'Shunt_{sh_id}')), _to_int(sh.get('bus', 1), 1),
                    _to_float(sh.get('Q_shunt', 0.0)), _to_int(sh.get('status', 1), 1), _to_int(sh.get('area', 1), 1), _to_int(sh.get('zone', 1), 1)
                ))
        else:
            for r in shunt_rows:
                if len(r) >= 4:
                    shunt_insert_data.append((
                        project_id, _to_int(r[0]), str(r[1]), _to_int(r[2], 1), _to_float(r[3]),
                        _to_int(r[4], 1) if len(r) > 4 else 1,
                        _to_int(r[5], 1) if len(r) > 5 else 1,
                        _to_int(r[6], 1) if len(r) > 6 else 1
                    ))
        if shunt_insert_data:
            cur.executemany("INSERT OR REPLACE INTO shunts (project_id, shunt_id, name, bus, Q_shunt, status, area, zone) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", shunt_insert_data)

        # 12.5. Battery Energy Storage Systems (BESS)
        bess_rows = data.get('bess_data') if data.get('bess_data') is not None else data.get('bess', [])
        bess_insert_data = []
        if isinstance(bess_rows, dict):
            for b_id, b in bess_rows.items():
                bess_insert_data.append((
                    project_id, _to_int(b_id, 1), str(b.get('name', f'BESS_{b_id}')), _to_int(b.get('bus', 1), 1),
                    _to_float(b.get('rated_mw', 10.0)), _to_float(b.get('rated_mwh', 40.0)),
                    _to_float(b.get('soc_init', 0.5)), _to_float(b.get('soc_min', 0.1)), _to_float(b.get('soc_max', 0.9)),
                    _to_float(b.get('eff_ch', 0.95)), _to_float(b.get('eff_dis', 0.95)),
                    str(b.get('strategy', 'peak_shaving')), _to_float(b.get('target_mw', 0.0)),
                    _to_int(b.get('status', 1), 1), _to_int(b.get('area', 1), 1), _to_int(b.get('zone', 1), 1), _to_int(b.get('owner', 1), 1)
                ))
        else:
            for r in bess_rows:
                if len(r) >= 5:
                    bess_insert_data.append((
                        project_id, _to_int(r[0]), str(r[1]), _to_int(r[2], 1),
                        _to_float(r[3]), _to_float(r[4]),
                        _to_float(r[5]) if len(r) > 5 else 0.5,
                        _to_float(r[6]) if len(r) > 6 else 0.1,
                        _to_float(r[7]) if len(r) > 7 else 0.9,
                        _to_float(r[8]) if len(r) > 8 else 0.95,
                        _to_float(r[9]) if len(r) > 9 else 0.95,
                        str(r[10]) if len(r) > 10 else 'peak_shaving',
                        _to_float(r[11]) if len(r) > 11 else 0.0,
                        _to_int(r[12], 1) if len(r) > 12 else 1,
                        _to_int(r[13], 1) if len(r) > 13 else 1,
                        _to_int(r[14], 1) if len(r) > 14 else 1,
                        _to_int(r[15], 1) if len(r) > 15 else 1,
                    ))
        if bess_insert_data:
            cur.executemany("INSERT OR REPLACE INTO bess (project_id, bess_id, name, bus, rated_mw, rated_mwh, soc_init, soc_min, soc_max, eff_ch, eff_dis, strategy, target_mw, status, area, zone, owner) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", bess_insert_data)

        # 12.6. Harmonic Sources (IEEE 519 / IEC 61000)
        harm_src_rows = data.get('harmonic_source_data') if data.get('harmonic_source_data') is not None else data.get('harmonic_sources', [])
        harm_src_insert = []
        if isinstance(harm_src_rows, dict):
            for s_id, s in harm_src_rows.items():
                spec = s.get('spectrum', {})
                spec_json = json.dumps(spec) if isinstance(spec, (dict, list)) else str(spec)
                harm_src_insert.append((
                    project_id, _to_int(s_id, 1), str(s.get('name', f'HarmSrc_{s_id}')), _to_int(s.get('bus', 1), 1),
                    str(s.get('source_type', 'current')), str(s.get('unit', 'amp_rms')), _to_float(s.get('fund_val', 100.0)),
                    spec_json, _to_int(s.get('status', 1), 1), _to_int(s.get('area', 1), 1), _to_int(s.get('zone', 1), 1)
                ))
        elif isinstance(harm_src_rows, list):
            for idx, s in enumerate(harm_src_rows):
                if isinstance(s, dict):
                    spec = s.get('spectrum', {})
                    spec_json = json.dumps(spec) if isinstance(spec, (dict, list)) else str(spec)
                    harm_src_insert.append((
                        project_id, _to_int(s.get('source_id', idx + 1), idx + 1), str(s.get('name', f'HarmSrc_{idx+1}')),
                        _to_int(s.get('bus', s.get('bus_id', 1)), 1), str(s.get('source_type', 'current')),
                        str(s.get('unit', 'amp_rms')), _to_float(s.get('fund_val', 100.0)),
                        spec_json, _to_int(s.get('status', 1), 1), _to_int(s.get('area', 1), 1), _to_int(s.get('zone', 1), 1)
                    ))
        if harm_src_insert:
            cur.executemany("INSERT OR REPLACE INTO harmonic_sources (project_id, source_id, name, bus, source_type, unit, fund_val, spectrum_json, status, area, zone) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", harm_src_insert)

        # 12.7. Passive Harmonic Filters
        harm_flt_rows = data.get('harmonic_filter_data') if data.get('harmonic_filter_data') is not None else data.get('harmonic_filters', [])
        harm_flt_insert = []
        if isinstance(harm_flt_rows, dict):
            for f_id, flt in harm_flt_rows.items():
                harm_flt_insert.append((
                    project_id, _to_int(f_id, 1), str(flt.get('name', f'Filter_{f_id}')), _to_int(flt.get('bus', 1), 1),
                    str(flt.get('filter_type', 'single_tuned')), _to_float(flt.get('tuning_order', 5.0)),
                    _to_float(flt.get('q_factor', 50.0)), _to_float(flt.get('mvar_rated', 1.0)),
                    _to_float(flt.get('r_ohm', 0.0)), _to_float(flt.get('l_mh', 0.0)), _to_float(flt.get('c_uf', 0.0)),
                    _to_int(flt.get('status', 1), 1), _to_int(flt.get('area', 1), 1), _to_int(flt.get('zone', 1), 1)
                ))
        elif isinstance(harm_flt_rows, list):
            for idx, flt in enumerate(harm_flt_rows):
                if isinstance(flt, dict):
                    harm_flt_insert.append((
                        project_id, _to_int(flt.get('filter_id', idx + 1), idx + 1), str(flt.get('name', f'Filter_{idx+1}')),
                        _to_int(flt.get('bus', 1), 1), str(flt.get('filter_type', 'single_tuned')),
                        _to_float(flt.get('tuning_order', 5.0)), _to_float(flt.get('q_factor', 50.0)),
                        _to_float(flt.get('mvar_rated', 1.0)), _to_float(flt.get('r_ohm', 0.0)),
                        _to_float(flt.get('l_mh', 0.0)), _to_float(flt.get('c_uf', 0.0)),
                        _to_int(flt.get('status', 1), 1), _to_int(flt.get('area', 1), 1), _to_int(flt.get('zone', 1), 1)
                    ))
        if harm_flt_insert:
            cur.executemany("INSERT OR REPLACE INTO harmonic_filters (project_id, filter_id, name, bus, filter_type, tuning_order, q_factor, mvar_rated, r_ohm, l_mh, c_uf, status, area, zone) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", harm_flt_insert)

        # 13. Short Circuit Faults
        fault_rows = data.get('fault_cases', [])
        if fault_rows:
            f_insert = []
            for f in fault_rows:
                if len(f) >= 3:
                    f_insert.append((
                        project_id, int(f[0]), int(f[1]), str(f[2]),
                        float(f[3]) if len(f) > 3 else 0.0,
                        float(f[4]) if len(f) > 4 else 0.0,
                        float(f[5]) if len(f) > 5 else 0.0,
                        float(f[6]) if len(f) > 6 else 0.0
                    ))
            if f_insert:
                cur.executemany("INSERT INTO short_circuit_faults (project_id, case_num, fault_bus, fault_type, r_phase, x_phase, r_gnd, x_gnd) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", f_insert)

        # 14. Zero Sequence Voltage Factors
        line_factors = data.get('line_voltage_factors', [])
        if line_factors:
            lf_insert = []
            for lf in line_factors:
                if len(lf) >= 1:
                    lf_insert.append((
                        project_id, float(lf[0]),
                        float(lf[1]) if len(lf) > 1 else 3.0,
                        float(lf[2]) if len(lf) > 2 else 3.0,
                        float(lf[3]) if len(lf) > 3 else 0.6
                    ))
            if lf_insert:
                cur.executemany("INSERT INTO zero_seq_factors (project_id, voltage_kV, zero_seq_res_mult, zero_seq_rea_mult, zero_seq_adm_mult) VALUES (?, ?, ?, ?, ?)", lf_insert)

        # 15. Global Sequence Factors
        g_factors = data.get('global_factors', {})
        if g_factors:
            gf_insert = [(project_id, str(k), json.dumps(v)) for k, v in g_factors.items()]
            cur.executemany("INSERT OR REPLACE INTO global_factors (project_id, key_name, val_data) VALUES (?, ?, ?)", gf_insert)

        # 16. SLD Diagrams (supports dict of multiple diagrams or single sld_json string)
        sld_diagrams = data.get('sld_diagrams')
        sld_json = data.get('sld_json')
        cur.execute("PRAGMA table_info(sld_diagrams)")
        cols = [col[1] for col in cur.fetchall()]
        has_dname = 'diagram_name' in cols

        if sld_diagrams and isinstance(sld_diagrams, dict) and len(sld_diagrams) > 0:
            if has_dname and replace_existing:
                cur.execute("DELETE FROM sld_diagrams WHERE project_id = ?", (project_id,))
            for idx, (d_name, d_json) in enumerate(sld_diagrams.items()):
                d_json_str = json.dumps(d_json) if isinstance(d_json, dict) else str(d_json)
                is_prim = 1 if idx == 0 else 0
                if has_dname:
                    cur.execute("""
                        INSERT OR REPLACE INTO sld_diagrams (project_id, diagram_name, sld_json, is_primary, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (project_id, str(d_name), d_json_str, is_prim, now_str, now_str))
                else:
                    cur.execute("INSERT OR REPLACE INTO sld_diagrams (project_id, sld_json) VALUES (?, ?)", (project_id, d_json_str))
        elif sld_json:
            d_json_str = json.dumps(sld_json) if isinstance(sld_json, dict) else str(sld_json)
            if has_dname:
                cur.execute("""
                    INSERT OR REPLACE INTO sld_diagrams (project_id, diagram_name, sld_json, is_primary, created_at, updated_at)
                    VALUES (?, 'Diagram 1', ?, 1, ?, ?)
                """, (project_id, d_json_str, now_str, now_str))
            else:
                cur.execute("INSERT OR REPLACE INTO sld_diagrams (project_id, sld_json) VALUES (?, ?)", (project_id, d_json_str))

        conn.commit()
        return project_id

    finally:
        conn.close()


def batch_py_to_sqlite(file_paths, sqlite_db_path, replace_existing=True):
    """
    Batch converts a list of .py file paths into a single SQLite database container.
    """
    results = []
    for fp in file_paths:
        if not fp.endswith('.py') or not os.path.exists(fp):
            continue
        pname = os.path.splitext(os.path.basename(fp))[0]
        try:
            pid = py_to_sqlite(fp, sqlite_db_path, project_name=pname, replace_existing=replace_existing)
            results.append({'file': fp, 'name': pname, 'id': pid, 'status': 'success'})
        except Exception as e:
            results.append({'file': fp, 'name': pname, 'id': None, 'status': f'error: {str(e)}'})
    return results


def delete_project_records(conn, project_id):
    """Deletes all records for a project in a transaction."""
    cur = conn.cursor()
    tables = [
        'sld_diagrams', 'global_factors', 'zero_seq_factors', 'short_circuit_faults',
        'bess', 'shunts', 'series_reactors', 'series_comps', 'reactors', 'capacitors',
        'three_winding_transformers', 'transformers', 'lines', 'loads', 'generators', 'buses', 'projects'
    ]
    for tbl in tables:
        cur.execute(f"DELETE FROM {tbl} WHERE project_id = ?", (str(project_id),))


def delete_project(sqlite_db_path, project_id):
    """Public method to delete a project from an SQLite DB file."""
    if not os.path.exists(sqlite_db_path):
        raise FileNotFoundError(f"Database file not found: {sqlite_db_path}")
    conn = sqlite3.connect(sqlite_db_path)
    try:
        delete_project_records(conn, project_id)
        conn.commit()
    finally:
        conn.close()


def list_projects(sqlite_db_path):
    """
    Returns a list of project summaries stored in the SQLite database.
    """
    if not os.path.exists(sqlite_db_path):
        return []

    conn = sqlite3.connect(sqlite_db_path)
    try:
        create_tables(conn)
        cur = conn.cursor()
        cur.execute("""
            SELECT p.project_id, p.project_name, p.description, p.base_mva, p.created_at, p.updated_at,
                   (SELECT COUNT(*) FROM buses b WHERE b.project_id = p.project_id) as bus_cnt,
                   (SELECT COUNT(*) FROM generators g WHERE g.project_id = p.project_id) as gen_cnt,
                   (SELECT COUNT(*) FROM loads l WHERE l.project_id = p.project_id) as load_cnt,
                   (SELECT COUNT(*) FROM lines ln WHERE ln.project_id = p.project_id) as line_cnt,
                   (SELECT COUNT(*) FROM transformers x WHERE x.project_id = p.project_id) as xfmr_cnt,
                   (SELECT COUNT(*) FROM three_winding_transformers tw WHERE tw.project_id = p.project_id) as tw_cnt
            FROM projects p
            ORDER BY CAST(p.project_id AS INTEGER) ASC, p.project_id ASC
        """)
        rows = cur.fetchall()
        if not rows:
            try:
                cur.execute("SELECT COUNT(*) FROM buses")
                bc_row = cur.fetchone()
                if bc_row and bc_row[0] > 0:
                    cur.execute("""
                        INSERT OR IGNORE INTO projects (project_id, project_name, description, base_mva, created_at, updated_at)
                        VALUES ('1', 'Imported Grid System', 'Auto-detected grid project container', 100.0, datetime('now'), datetime('now'))
                    """)
                    for tbl in ['buses', 'generators', 'loads', 'lines', 'transformers', 'three_winding_transformers', 'capacitors', 'reactors', 'series_comps', 'series_reactors', 'shunts', 'bess']:
                        try:
                            cur.execute(f"UPDATE {tbl} SET project_id = '1' WHERE project_id IS NULL OR project_id = ''")
                        except Exception:
                            pass
                    conn.commit()
                    cur.execute("""
                        SELECT p.project_id, p.project_name, p.description, p.base_mva, p.created_at, p.updated_at,
                               (SELECT COUNT(*) FROM buses b WHERE b.project_id = p.project_id) as bus_cnt,
                               (SELECT COUNT(*) FROM generators g WHERE g.project_id = p.project_id) as gen_cnt,
                               (SELECT COUNT(*) FROM loads l WHERE l.project_id = p.project_id) as load_cnt,
                               (SELECT COUNT(*) FROM lines ln WHERE ln.project_id = p.project_id) as line_cnt,
                               (SELECT COUNT(*) FROM transformers x WHERE x.project_id = p.project_id) as xfmr_cnt,
                               (SELECT COUNT(*) FROM three_winding_transformers tw WHERE tw.project_id = p.project_id) as tw_cnt
                        FROM projects p
                        ORDER BY CAST(p.project_id AS INTEGER) ASC, p.project_id ASC
                    """)
                    rows = cur.fetchall()
            except Exception:
                pass
        projects = []
        for r in rows:
            projects.append({
                'project_id': r[0],
                'project_name': r[1],
                'description': r[2],
                'base_mva': r[3],
                'created_at': r[4],
                'updated_at': r[5],
                'bus_count': r[6],
                'gen_count': r[7],
                'load_count': r[8],
                'line_count': r[9],
                'xfmr_count': r[10] + r[11]
            })
        return projects
    finally:
        conn.close()


def load_project_dict_from_sqlite(sqlite_db_path, project_id):
    """
    Retrieves full data dictionary for a project from SQLite DB.
    """
    if not os.path.exists(sqlite_db_path):
        raise FileNotFoundError(f"Database file not found: {sqlite_db_path}")

    conn = sqlite3.connect(sqlite_db_path)
    try:
        cur = conn.cursor()
        pid_str = str(project_id).strip()

        # 1. Project Master
        cur.execute("SELECT project_id, project_name, description, base_mva, solver_config_json, map_settings_json, metadata_json FROM projects WHERE project_id = ?", (pid_str,))
        p_row = cur.fetchone()
        if not p_row:
            raise ValueError(f"Project ID '{project_id}' not found in {sqlite_db_path}")

        meta_dict = json.loads(p_row[6] or '{}') if len(p_row) > 6 and p_row[6] else {}
        ts_settings = meta_dict.get('time_series_settings', {})
        ts_profiles = meta_dict.get('time_series_profiles', {})

        project_info = {
            'project_id': p_row[0],
            'project_name': p_row[1],
            'description': p_row[2],
            'base_mva': p_row[3],
            'solver_config': json.loads(p_row[4] or '{}'),
            'map_settings': json.loads(p_row[5] or '{}'),
            'time_series_settings': ts_settings,
            'time_series_profiles': ts_profiles,
            'buses': {},
            'generators': {},
            'loads': {},
            'lines': {},
            'transformers': {},
            'three_winding_transformers': {},
            'capacitors': {},
            'reactors': {},
            'series_comps': {},
            'series_reactors': {},
            'shunts': {},
            'bess': {},
            'harmonic_sources': {},
            'harmonic_filters': {},
            'fault_cases': [],
            'line_voltage_factors': [],
            'global_factors': {},
            'sld_json': None
        }

        # 2. Buses
        cur.execute("SELECT bus_id, name, type, base_kV, V_init, angle_init, shunt_G, shunt_B, area, zone, owner, lat, long, sk_mva, rx_ratio, z01_ratio FROM buses WHERE project_id = ? ORDER BY bus_id ASC", (pid_str,))
        for r in cur.fetchall():
            project_info['buses'][r[0]] = {
                'name': r[1], 'type': r[2], 'base_kV': r[3], 'V_init': r[4], 'angle_init': r[5],
                'shunt_G': r[6], 'shunt_B': r[7], 'area': r[8], 'zone': r[9], 'owner': r[10],
                'lat': r[11], 'long': r[12], 'sk_mva': r[13], 'rx_ratio': r[14], 'z01_ratio': r[15]
            }

        # 3. Generators
        try:
            cur.execute("SELECT gen_id, name, type, bus, P_out, Q_out, V_set, Qmin, Qmax, status, area, zone, owner, R1_pu, X1_pu, R2_pu, X2_pu, R0_pu, X0_pu, cb_mva, wind_conn, gnd_r, gnd_x FROM generators WHERE project_id = ? ORDER BY gen_id ASC", (pid_str,))
            for r in cur.fetchall():
                project_info['generators'][r[0]] = {
                    'name': r[1], 'type': r[2], 'bus': r[3], 'P_out': r[4], 'Q_out': r[5],
                    'V_set': r[6], 'Qmin': r[7], 'Qmax': r[8], 'status': r[9],
                    'area': r[10], 'zone': r[11], 'owner': r[12],
                    'R1_pu': r[13], 'X1_pu': r[14], 'R2_pu': r[15], 'X2_pu': r[16],
                    'R0_pu': r[17], 'X0_pu': r[18], 'cb_mva': r[19], 'wind_conn': r[20],
                    'gnd_r': r[21] if len(r) > 21 else 0.0, 'gnd_x': r[22] if len(r) > 22 else 0.0
                }
        except Exception:
            cur.execute("SELECT gen_id, name, type, bus, P_out, Q_out, V_set, Qmin, Qmax, status, area, zone, owner, R1_pu, X1_pu, R2_pu, X2_pu, R0_pu, X0_pu, cb_mva, wind_conn FROM generators WHERE project_id = ? ORDER BY gen_id ASC", (pid_str,))
            for r in cur.fetchall():
                project_info['generators'][r[0]] = {
                    'name': r[1], 'type': r[2], 'bus': r[3], 'P_out': r[4], 'Q_out': r[5],
                    'V_set': r[6], 'Qmin': r[7], 'Qmax': r[8], 'status': r[9],
                    'area': r[10], 'zone': r[11], 'owner': r[12],
                    'R1_pu': r[13], 'X1_pu': r[14], 'R2_pu': r[15], 'X2_pu': r[16],
                    'R0_pu': r[17], 'X0_pu': r[18], 'cb_mva': r[19], 'wind_conn': r[20],
                    'gnd_r': 0.0, 'gnd_x': 0.0
                }

        # 4. Loads
        cur.execute("SELECT load_id, name, bus, P_demand, Q_demand, model, area, zone, cb_mva, wind_conn FROM loads WHERE project_id = ? ORDER BY load_id ASC", (pid_str,))
        for r in cur.fetchall():
            project_info['loads'][r[0]] = {
                'name': r[1], 'bus': r[2], 'P_demand': r[3], 'Q_demand': r[4],
                'model': r[5], 'area': r[6], 'zone': r[7], 'cb_mva': r[8], 'wind_conn': r[9]
            }

        # 5. Lines
        cur.execute("SELECT line_id, name, from_bus, to_bus, length_km, R_per_km, X_per_km, B_per_km, rateA, status, area, zone, owner, R0_per_km, X0_per_km, B0_per_km, from_cb_mva, to_cb_mva, bends_json FROM lines WHERE project_id = ? ORDER BY line_id ASC", (pid_str,))
        for r in cur.fetchall():
            l_km = float(r[4] or 0.0)
            r_km = float(r[5] or 0.0)
            x_km = float(r[6] or 0.0)
            b_km = float(r[7] or 0.0)
            project_info['lines'][r[0]] = {
                'name': r[1], 'from_bus': r[2], 'to_bus': r[3],
                'length_km': l_km, 'length': l_km,
                'R_per_km': r_km, 'X_per_km': x_km, 'B_per_km': b_km,
                'r': r_km * l_km if (l_km > 0 and r_km > 0) else r_km,
                'x': x_km * l_km if (l_km > 0 and x_km > 0) else x_km,
                'b': b_km * l_km if (l_km > 0 and b_km > 0) else b_km,
                'rateA': r[8], 'status': r[9], 'area': r[10], 'zone': r[11], 'owner': r[12],
                'R0_per_km': r[13], 'X0_per_km': r[14], 'B0_per_km': r[15],
                'from_cb_mva': r[16], 'to_cb_mva': r[17],
                'bends': json.loads(r[18] or '[]')
            }

        # 6. Transformers
        cur.execute("SELECT xfmr_id, name, from_bus, to_bus, r, x, tap_ratio, rateA, phase_shift, min_tap, max_tap, step_size, status, area, zone, owner, R0_pu, X0_pu, from_conn, to_conn, from_gnd_r, from_gnd_x, to_gnd_r, to_gnd_x, from_cb_mva, to_cb_mva FROM transformers WHERE project_id = ? ORDER BY xfmr_id ASC", (pid_str,))
        for r in cur.fetchall():
            project_info['transformers'][r[0]] = {
                'name': r[1], 'from_bus': r[2], 'to_bus': r[3], 'r': r[4], 'x': r[5],
                'tap_ratio': r[6], 'rateA': r[7], 'phase_shift': r[8], 'min_tap': r[9],
                'max_tap': r[10], 'step_size': r[11], 'status': r[12], 'area': r[13],
                'zone': r[14], 'owner': r[15], 'R0_pu': r[16], 'X0_pu': r[17],
                'from_conn': r[18], 'to_conn': r[19], 'from_gnd_r': r[20], 'from_gnd_x': r[21],
                'to_gnd_r': r[22], 'to_gnd_x': r[23], 'from_cb_mva': r[24], 'to_cb_mva': r[25]
            }

        # 7. Three-Winding Transformers
        cur.execute("SELECT tw_id, name, hv_bus, mv_bus, lv_bus, r_hm, x_hm, r_hl, x_hl, r_ml, x_ml, rate_h, rate_m, rate_l, tap_h, tap_m, tap_l, status, area, zone, owner FROM three_winding_transformers WHERE project_id = ? ORDER BY tw_id ASC", (pid_str,))
        for r in cur.fetchall():
            project_info['three_winding_transformers'][r[0]] = {
                'name': r[1], 'hv_bus': r[2], 'mv_bus': r[3], 'lv_bus': r[4],
                'r_hm': r[5], 'x_hm': r[6], 'r_hl': r[7], 'x_hl': r[8],
                'r_ml': r[9], 'x_ml': r[10], 'rate_h': r[11], 'rate_m': r[12], 'rate_l': r[13],
                'tap_h': r[14], 'tap_m': r[15], 'tap_l': r[16],
                'status': r[17], 'area': r[18], 'zone': r[19], 'owner': r[20]
            }

        # 8. Capacitors
        cur.execute("SELECT cap_id, name, bus, Q_cap, status, area, zone FROM capacitors WHERE project_id = ? ORDER BY cap_id ASC", (pid_str,))
        for r in cur.fetchall():
            project_info['capacitors'][r[0]] = {
                'name': r[1], 'bus': r[2], 'Q_cap': r[3], 'status': r[4], 'area': r[5], 'zone': r[6]
            }

        # 9. Reactors
        cur.execute("SELECT reactor_id, name, bus, Q_react, status, area, zone, G1_pu, B1_pu, G0_pu, B0_pu, cb_mva FROM reactors WHERE project_id = ? ORDER BY reactor_id ASC", (pid_str,))
        for r in cur.fetchall():
            project_info['reactors'][r[0]] = {
                'name': r[1], 'bus': r[2], 'Q_react': r[3], 'status': r[4], 'area': r[5], 'zone': r[6],
                'G1_pu': r[7], 'B1_pu': r[8], 'G0_pu': r[9], 'B0_pu': r[10], 'cb_mva': r[11]
            }

        # 10. Series Comps
        cur.execute("SELECT sc_id, name, from_bus, to_bus, r, x, comp_pct, status, area, zone, owner FROM series_comps WHERE project_id = ? ORDER BY sc_id ASC", (pid_str,))
        for r in cur.fetchall():
            project_info['series_comps'][r[0]] = {
                'name': r[1], 'from_bus': r[2], 'to_bus': r[3], 'r': r[4], 'x': r[5],
                'comp_pct': r[6], 'status': r[7], 'area': r[8], 'zone': r[9], 'owner': r[10]
            }

        # 11. Series Reactors
        cur.execute("SELECT sr_id, name, from_bus, to_bus, r, x, status, area, zone, owner FROM series_reactors WHERE project_id = ? ORDER BY sr_id ASC", (pid_str,))
        for r in cur.fetchall():
            project_info['series_reactors'][r[0]] = {
                'name': r[1], 'from_bus': r[2], 'to_bus': r[3], 'r': r[4], 'x': r[5],
                'status': r[6], 'area': r[7], 'zone': r[8], 'owner': r[9]
            }

        # 12. Shunts
        cur.execute("SELECT shunt_id, name, bus, Q_shunt, status, area, zone FROM shunts WHERE project_id = ? ORDER BY shunt_id ASC", (pid_str,))
        for r in cur.fetchall():
            project_info['shunts'][r[0]] = {
                'name': r[1], 'bus': r[2], 'Q_shunt': r[3], 'status': r[4], 'area': r[5], 'zone': r[6]
            }

        # 12.5. Battery Energy Storage Systems (BESS)
        cur.execute("SELECT bess_id, name, bus, rated_mw, rated_mwh, soc_init, soc_min, soc_max, eff_ch, eff_dis, strategy, target_mw, status, area, zone, owner FROM bess WHERE project_id = ? ORDER BY bess_id ASC", (pid_str,))
        for r in cur.fetchall():
            project_info['bess'][r[0]] = {
                'name': r[1], 'bus': r[2], 'rated_mw': r[3], 'rated_mwh': r[4],
                'soc_init': r[5], 'soc_min': r[6], 'soc_max': r[7],
                'eff_ch': r[8], 'eff_dis': r[9], 'strategy': r[10], 'target_mw': r[11],
                'status': r[12], 'area': r[13], 'zone': r[14], 'owner': r[15]
            }

        # 12.6. Harmonic Sources
        try:
            cur.execute("SELECT source_id, name, bus, source_type, unit, fund_val, spectrum_json, status, area, zone FROM harmonic_sources WHERE project_id = ? ORDER BY source_id ASC", (pid_str,))
            for r in cur.fetchall():
                spec = {}
                try: spec = json.loads(r[6] or '{}')
                except Exception: spec = {}
                project_info['harmonic_sources'][r[0]] = {
                    'name': r[1], 'bus': r[2], 'source_type': r[3], 'unit': r[4],
                    'fund_val': r[5], 'spectrum': spec, 'status': r[7], 'area': r[8], 'zone': r[9]
                }
        except Exception:
            pass

        # 12.7. Passive Harmonic Filters
        try:
            cur.execute("SELECT filter_id, name, bus, filter_type, tuning_order, q_factor, mvar_rated, r_ohm, l_mh, c_uf, status, area, zone FROM harmonic_filters WHERE project_id = ? ORDER BY filter_id ASC", (pid_str,))
            for r in cur.fetchall():
                project_info['harmonic_filters'][r[0]] = {
                    'name': r[1], 'bus': r[2], 'filter_type': r[3], 'tuning_order': r[4],
                    'q_factor': r[5], 'mvar_rated': r[6], 'r_ohm': r[7], 'l_mh': r[8],
                    'c_uf': r[9], 'status': r[10], 'area': r[11], 'zone': r[12]
                }
        except Exception:
            pass

        # 13. Short Circuit Faults
        cur.execute("SELECT case_num, fault_bus, fault_type, r_phase, x_phase, r_gnd, x_gnd FROM short_circuit_faults WHERE project_id = ? ORDER BY case_num ASC", (pid_str,))
        project_info['fault_cases'] = [list(r) for r in cur.fetchall()]

        # 14. Zero Seq Factors
        cur.execute("SELECT voltage_kV, zero_seq_res_mult, zero_seq_rea_mult, zero_seq_adm_mult FROM zero_seq_factors WHERE project_id = ? ORDER BY voltage_kV ASC", (pid_str,))
        project_info['line_voltage_factors'] = [list(r) for r in cur.fetchall()]

        # 15. Global Factors
        cur.execute("SELECT key_name, val_data FROM global_factors WHERE project_id = ?", (pid_str,))
        for k, v in cur.fetchall():
            try: project_info['global_factors'][k] = json.loads(v)
            except: project_info['global_factors'][k] = v

        # 16. SLD Diagrams
        project_info['sld_diagrams'] = {}
        cur.execute("PRAGMA table_info(sld_diagrams)")
        cols = [col[1] for col in cur.fetchall()]
        if 'diagram_name' in cols:
            cur.execute("SELECT diagram_name, sld_json FROM sld_diagrams WHERE project_id = ? ORDER BY is_primary DESC, diagram_name ASC", (pid_str,))
            for d_name, d_json in cur.fetchall():
                project_info['sld_diagrams'][d_name] = d_json
                if not project_info.get('sld_json'):
                    project_info['sld_json'] = d_json
        else:
            cur.execute("SELECT sld_json FROM sld_diagrams WHERE project_id = ?", (pid_str,))
            sld_r = cur.fetchone()
            if sld_r and sld_r[0]:
                project_info['sld_json'] = sld_r[0]
                project_info['sld_diagrams']['Diagram 1'] = sld_r[0]

        # Attach time series profiles to individual components
        if ts_profiles and isinstance(ts_profiles, dict):
            for gid, prof in ts_profiles.get('generators', {}).items():
                if gid in project_info['generators'] and prof:
                    project_info['generators'][gid]['time_series'] = prof
            for lid, prof in ts_profiles.get('loads', {}).items():
                if lid in project_info['loads'] and prof:
                    project_info['loads'][lid]['time_series'] = prof
            for cid, prof in ts_profiles.get('capacitors', {}).items():
                if cid in project_info['capacitors'] and prof:
                    project_info['capacitors'][cid]['time_series'] = prof
            for rid, prof in ts_profiles.get('reactors', {}).items():
                if rid in project_info['reactors'] and prof:
                    project_info['reactors'][rid]['time_series'] = prof
            for sid, prof in ts_profiles.get('shunts', {}).items():
                if sid in project_info['shunts'] and prof:
                    project_info['shunts'][sid]['time_series'] = prof

        return project_info
    finally:
        conn.close()


def sqlite_to_py(sqlite_db_path, project_id, output_py_path=None):
    """
    Extracts a project from SQLite DB into a standard .py database file format.
    """
    import pprint
    proj = load_project_dict_from_sqlite(sqlite_db_path, project_id)

    lines = []
    lines.append('"""\n')
    lines.append(f'Power System Database - Exported from SQLite DB\n')
    lines.append(f'Project ID: {proj["project_id"]} | Project Name: {proj["project_name"]}\n')
    lines.append(f'Generated: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
    lines.append('Contains: Buses, Generators, Loads, Lines, Transformers, Capacitors, Reactors, Series Comps, Series Reactors, Shunts\n')
    lines.append('"""\n\n')

    sim_cfg = proj.get('simulation_settings') or proj.get('solver_config') or {}
    lines.append(f"MAP_SETTINGS = {repr(proj.get('map_settings', {}))}\n\n")
    lines.append(f"SIMULATION_SETTINGS = {repr(sim_cfg)}\n\n")
    lines.append(f"SOLVER_CONFIG = {repr(sim_cfg)}\n\n")
    lines.append(f"BASE_MVA = {proj.get('base_mva', 100.0)}\n\n")

    # BUS_DATA
    lines.append('# ========== BUS DATA ==========\n')
    lines.append('# [bus_num, bus_name, bus_type, base_kV, V_init_pu, angle_init_deg, shunt_G, shunt_B, area, zone, owner, lat, long, sk_mva, rx_ratio, z01_ratio]\n')
    lines.append('BUS_DATA = [\n')
    for b_id in sorted(proj['buses'].keys()):
        b = proj['buses'][b_id]
        lines.append(f'    [{b_id}, "{b["name"]}", {b["type"]}, {b["base_kV"]}, {b["V_init"]}, {b["angle_init"]}, '
                     f'{b["shunt_G"]}, {b["shunt_B"]}, {b["area"]}, {b["zone"]}, {b["owner"]}, '
                     f'{b.get("lat", 0.0)}, {b.get("long", 0.0)}, {b.get("sk_mva", 1000.0)}, {b.get("rx_ratio", 0.1)}, {b.get("z01_ratio", 1.0)}],\n')
    lines.append(']\n\n')

    # GENERATOR_DATA
    lines.append('# ========== GENERATOR DATA ==========\n')
    lines.append('# [gen_num, gen_name, gen_type, bus, P_out, Q_out, V_set, Qmin, Qmax, status, area, zone, owner, R1_pu, X1_pu, R2_pu, X2_pu, R0_pu, X0_pu, cb_mva, wind_conn, gnd_r, gnd_x]\n')
    lines.append('GENERATOR_DATA = [\n')
    for g_id in sorted(proj['generators'].keys()):
        g = proj['generators'][g_id]
        lines.append(f'    [{g_id}, "{g["name"]}", "{g["type"]}", {g["bus"]}, {g["P_out"]}, {g["Q_out"]}, '
                     f'{g["V_set"]}, {g["Qmin"]}, {g["Qmax"]}, {g["status"]}, {g["area"]}, {g["zone"]}, {g["owner"]}, '
                     f'{g.get("R1_pu", 0.0)}, {g.get("X1_pu", 0.0)}, {g.get("R2_pu", 0.0)}, {g.get("X2_pu", 0.0)}, '
                     f'{g.get("R0_pu", 0.0)}, {g.get("X0_pu", 0.0)}, {g.get("cb_mva", 0.0)}, "{g.get("wind_conn", "0")}", '
                     f'{g.get("gnd_r", 0.0)}, {g.get("gnd_x", 0.0)}],\n')
    lines.append(']\n\n')

    # LOAD_DATA
    lines.append('# ========== LOAD DATA ==========\n')
    lines.append('# [load_num, load_name, bus, P_demand, Q_demand, model, area, zone, cb_mva, wind_conn]\n')
    lines.append('LOAD_DATA = [\n')
    for l_id in sorted(proj['loads'].keys()):
        l = proj['loads'][l_id]
        lines.append(f'    [{l_id}, "{l["name"]}", {l["bus"]}, {l["P_demand"]}, {l["Q_demand"]}, '
                     f'"{l["model"]}", {l["area"]}, {l["zone"]}, {l.get("cb_mva", 0.0)}, "{l.get("wind_conn", "0")}"],\n')
    lines.append(']\n\n')

    # LINE_DATA
    lines.append('# ========== TRANSMISSION LINE DATA ==========\n')
    lines.append('# [line_num, line_name, from_bus, to_bus, length_km, R_per_km, X_per_km, B_per_km, rateA, status, area, zone, owner, R0_per_km, X0_per_km, B0_per_km, from_cb_mva, to_cb_mva]\n')
    lines.append('LINE_DATA = [\n')
    for ln_id in sorted(proj['lines'].keys()):
        ln = proj['lines'][ln_id]
        lines.append(f'    [{ln_id}, "{ln["name"]}", {ln["from_bus"]}, {ln["to_bus"]}, '
                     f'{ln.get("length_km", 0.0)}, {ln.get("R_per_km", 0.0)}, {ln.get("X_per_km", 0.0)}, {ln.get("B_per_km", 0.0)}, '
                     f'{ln.get("rateA", 0.0)}, {ln.get("status", 1)}, {ln.get("area", 1)}, {ln.get("zone", 1)}, {ln.get("owner", 1)}, '
                     f'{ln.get("R0_per_km", 0.0)}, {ln.get("X0_per_km", 0.0)}, {ln.get("B0_per_km", 0.0)}, '
                     f'{ln.get("from_cb_mva", 0.0)}, {ln.get("to_cb_mva", 0.0)}],\n')
    lines.append(']\n\n')

    # TRANSFORMER_DATA
    lines.append('# ========== TRANSFORMER DATA ==========\n')
    lines.append('# [xfmr_num, xfmr_name, from_bus, to_bus, R_pu, X_pu, tap_ratio, rateA, phase_shift, min_tap, max_tap, step_size, status, area, zone, owner, R0_pu, X0_pu, from_conn, to_conn, from_gnd_r, from_gnd_x, to_gnd_r, to_gnd_x, from_cb_mva, to_cb_mva]\n')
    lines.append('TRANSFORMER_DATA = [\n')
    for x_id in sorted(proj['transformers'].keys()):
        xf = proj['transformers'][x_id]
        lines.append(f'    [{x_id}, "{xf["name"]}", {xf["from_bus"]}, {xf["to_bus"]}, '
                     f'{xf["r"]}, {xf["x"]}, {xf["tap_ratio"]}, {xf.get("rateA", 9999)}, '
                     f'{xf.get("phase_shift", 0)}, {xf.get("min_tap", 0.9)}, {xf.get("max_tap", 1.1)}, '
                     f'{xf.get("step_size", 0.01)}, {xf.get("status", 1)}, {xf.get("area", 1)}, '
                     f'{xf.get("zone", 1)}, {xf.get("owner", 1)}, {xf.get("R0_pu", 0.0)}, {xf.get("X0_pu", 0.0)}, '
                     f'"{xf.get("from_conn", "0")}", "{xf.get("to_conn", "0")}", {xf.get("from_gnd_r", 0.0)}, '
                     f'{xf.get("from_gnd_x", 0.0)}, {xf.get("to_gnd_r", 0.0)}, {xf.get("to_gnd_x", 0.0)}, '
                     f'{xf.get("from_cb_mva", 0.0)}, {xf.get("to_cb_mva", 0.0)}],\n')
    lines.append(']\n\n')

    # THREE_WINDING_TRANSFORMER_DATA
    lines.append('# ========== THREE-WINDING TRANSFORMER DATA ==========\n')
    lines.append('THREE_WINDING_TRANSFORMER_DATA = [\n')
    for t_id in sorted(proj['three_winding_transformers'].keys()):
        tw = proj['three_winding_transformers'][t_id]
        lines.append(f'    [{t_id}, "{tw["name"]}", {tw["hv_bus"]}, {tw["mv_bus"]}, {tw["lv_bus"]}, '
                     f'{tw.get("r_hm", 0.0)}, {tw.get("x_hm", 0.05)}, {tw.get("r_hl", 0.0)}, {tw.get("x_hl", 0.05)}, '
                     f'{tw.get("r_ml", 0.0)}, {tw.get("x_ml", 0.05)}, {tw.get("rate_h", 9999)}, {tw.get("rate_m", 9999)}, '
                     f'{tw.get("rate_l", 9999)}, {tw.get("tap_h", 1.0)}, {tw.get("tap_m", 1.0)}, {tw.get("tap_l", 1.0)}, '
                     f'{tw.get("status", 1)}, {tw.get("area", 1)}, {tw.get("zone", 1)}, {tw.get("owner", 1)}],\n')
    lines.append(']\n\n')

    # CAPACITOR_DATA
    lines.append('# ========== CAPACITOR DATA ==========\n')
    lines.append('CAPACITOR_DATA = [\n')
    for c_id in sorted(proj['capacitors'].keys()):
        c = proj['capacitors'][c_id]
        lines.append(f'    [{c_id}, "{c["name"]}", {c["bus"]}, {c["Q_cap"]}, {c["status"]}, {c["area"]}, {c["zone"]}],\n')
    lines.append(']\n\n')

    # REACTOR_DATA
    lines.append('# ========== REACTOR DATA ==========\n')
    lines.append('REACTOR_DATA = [\n')
    for r_id in sorted(proj['reactors'].keys()):
        rc = proj['reactors'][r_id]
        lines.append(f'    [{r_id}, "{rc["name"]}", {rc["bus"]}, {rc["Q_react"]}, {rc["status"]}, '
                     f'{rc["area"]}, {rc["zone"]}, {rc.get("G1_pu", 0.0)}, {rc.get("B1_pu", 0.0)}, '
                     f'{rc.get("G0_pu", 0.0)}, {rc.get("B0_pu", 0.0)}, {rc.get("cb_mva", 0.0)}],\n')
    lines.append(']\n\n')

    # SERIES_COMP_DATA
    lines.append('# ========== SERIES COMPENSATION DATA ==========\n')
    lines.append('SERIES_COMP_DATA = [\n')
    for s_id in sorted(proj['series_comps'].keys()):
        sc = proj['series_comps'][s_id]
        lines.append(f'    [{s_id}, "{sc["name"]}", {sc["from_bus"]}, {sc["to_bus"]}, '
                     f'{sc["r"]}, {sc["x"]}, {sc["comp_pct"]}, {sc["status"]}, {sc["area"]}, {sc["zone"]}, {sc["owner"]}],\n')
    lines.append(']\n\n')

    # SERIES_REACTOR_DATA
    lines.append('# ========== SERIES REACTOR DATA ==========\n')
    lines.append('SERIES_REACTOR_DATA = [\n')
    for s_id in sorted(proj['series_reactors'].keys()):
        sr = proj['series_reactors'][s_id]
        lines.append(f'    [{s_id}, "{sr["name"]}", {sr["from_bus"]}, {sr["to_bus"]}, '
                     f'{sr["r"]}, {sr["x"]}, {sr["status"]}, {sr["area"]}, {sr["zone"]}, {sr["owner"]}],\n')
    lines.append(']\n\n')

    # SHUNT_DATA
    lines.append('# ========== SHUNT COMPENSATION DATA ==========\n')
    lines.append('SHUNT_DATA = [\n')
    for s_id in sorted(proj['shunts'].keys()):
        sh = proj['shunts'][s_id]
        lines.append(f'    [{s_id}, "{sh["name"]}", {sh["bus"]}, {sh["Q_shunt"]}, {sh["status"]}, {sh["area"]}, {sh["zone"]}],\n')
    lines.append(']\n\n')

    # BESS_DATA
    if 'bess' in proj and proj['bess']:
        lines.append('# ========== BATTERY ENERGY STORAGE SYSTEM (BESS) DATA ==========\n')
        lines.append('# [bess_id, name, bus, rated_mw, rated_mwh, soc_init, soc_min, soc_max, eff_ch, eff_dis, strategy, target_mw, status, area, zone, owner]\n')
        lines.append('BESS_DATA = [\n')
        for b_id in sorted(proj['bess'].keys()):
            b = proj['bess'][b_id]
            lines.append(f'    [{b_id}, "{b["name"]}", {b["bus"]}, {b["rated_mw"]}, {b["rated_mwh"]}, '
                         f'{b.get("soc_init", 0.5)}, {b.get("soc_min", 0.1)}, {b.get("soc_max", 0.9)}, '
                         f'{b.get("eff_ch", 0.95)}, {b.get("eff_dis", 0.95)}, "{b.get("strategy", "peak_shaving")}", '
                         f'{b.get("target_mw", 0.0)}, {b.get("status", 1)}, {b.get("area", 1)}, {b.get("zone", 1)}, {b.get("owner", 1)}],\n')
        lines.append(']\n\n')

    # Faults and Factors
    lines.append(f"FAULT_ON_SELECTED_BUSES = {repr(proj.get('fault_cases', []))}\n\n")
    lines.append(f"TRANSMISSION_LINE_ZERO_SEQ_FACTORS = {repr(proj.get('line_voltage_factors', []))}\n\n")
    lines.append(f"GLOBAL_SEQUENCE_CORRECTION_FACTORS = {repr(proj.get('global_factors', {}))}\n\n")

    # Harmonic Sources and Filters
    harm_srcs = proj.get('harmonic_sources', {})
    if isinstance(harm_srcs, dict):
        harm_src_list = list(harm_srcs.values())
    elif isinstance(harm_srcs, list):
        harm_src_list = harm_srcs
    else:
        harm_src_list = []
    lines.append(f"HARMONIC_SOURCES = {repr(harm_src_list)}\n\n")

    harm_flts = proj.get('harmonic_filters', {})
    if isinstance(harm_flts, dict):
        harm_flt_list = list(harm_flts.values())
    elif isinstance(harm_flts, list):
        harm_flt_list = harm_flts
    else:
        harm_flt_list = []
    lines.append(f"HARMONIC_FILTERS = {repr(harm_flt_list)}\n\n")

    # Time Series Settings & Profiles
    lines.append('# ========== TIME SERIES LOAD FLOW SETTINGS & PROFILES ==========\n')
    lines.append(f"TIME_SERIES_SETTINGS = {repr(proj.get('time_series_settings', {}))}\n\n")
    ts_prof = {
        'generators': {gid: g.get('time_series') for gid, g in proj.get('generators', {}).items() if g.get('time_series')},
        'loads': {lid: l.get('time_series') for lid, l in proj.get('loads', {}).items() if l.get('time_series')},
        'capacitors': {cid: c.get('time_series') for cid, c in proj.get('capacitors', {}).items() if c.get('time_series')},
        'reactors': {rid: r.get('time_series') for rid, r in proj.get('reactors', {}).items() if r.get('time_series')},
        'shunts': {sid: s.get('time_series') for sid, s in proj.get('shunts', {}).items() if s.get('time_series')},
    }
    lines.append(f"TIME_SERIES_PROFILES = {repr(ts_prof)}\n\n")

    code_content = "".join(lines)

    if output_py_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_py_path)), exist_ok=True)
        with open(output_py_path, 'w', encoding='utf-8') as f:
            f.write(code_content)

        # Also write .sld file if diagram data exists
        if proj.get('sld_json'):
            sld_path = os.path.splitext(output_py_path)[0] + ".sld"
            with open(sld_path, 'w', encoding='utf-8') as sf:
                sf.write(proj['sld_json'])

    return code_content


def export_all_projects(sqlite_db_path, output_dir):
    """
    Exports all projects from an SQLite container to individual .py files in output_dir.
    """
    projects = list_projects(sqlite_db_path)
    os.makedirs(output_dir, exist_ok=True)
    exported = []
    for p in projects:
        safe_name = "".join(c for c in p['project_name'] if c.isalnum() or c in (' ', '_', '-')).rstrip()
        filename = f"{p['project_id']}_{safe_name}.py" if safe_name else f"Project_{p['project_id']}.py"
        out_path = os.path.join(output_dir, filename)
        sqlite_to_py(sqlite_db_path, p['project_id'], out_path)
        exported.append(out_path)
    return exported


def save_sld_to_sqlite(sqlite_db_path, project_id, diagram_name, sld_json, is_primary=1):
    """
    Saves an SLD diagram JSON string under project_id and diagram_name in the SQLite DB.
    """
    if not os.path.exists(sqlite_db_path):
        raise FileNotFoundError(f"Database file not found: {sqlite_db_path}")
    conn = sqlite3.connect(sqlite_db_path)
    try:
        create_tables(conn)
        cur = conn.cursor()
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        pid_str = str(project_id).strip()
        d_name = str(diagram_name).strip() if diagram_name else "Diagram 1"

        # Check existing table columns for migration
        cur.execute("PRAGMA table_info(sld_diagrams)")
        cols = [col[1] for col in cur.fetchall()]
        if 'diagram_name' not in cols:
            cur.execute("ALTER TABLE sld_diagrams RENAME TO sld_diagrams_old")
            create_tables(conn)
            cur.execute("INSERT INTO sld_diagrams (project_id, diagram_name, sld_json, is_primary, created_at, updated_at) SELECT project_id, 'Diagram 1', sld_json, 1, ?, ? FROM sld_diagrams_old", (now_str, now_str))
            cur.execute("DROP TABLE sld_diagrams_old")

        cur.execute("""
            INSERT OR REPLACE INTO sld_diagrams (
                project_id, diagram_name, sld_json, is_primary, created_at, updated_at
            ) VALUES (?, ?, ?, ?, COALESCE((SELECT created_at FROM sld_diagrams WHERE project_id=? AND diagram_name=?), ?), ?)
        """, (pid_str, d_name, sld_json, int(is_primary), pid_str, d_name, now_str, now_str))
        conn.commit()
    finally:
        conn.close()


def list_slds_from_sqlite(sqlite_db_path, project_id):
    """
    Returns a list of SLD diagram dictionaries for the given project_id:
    [{'diagram_name': '...', 'is_primary': 1, 'updated_at': '...'}]
    """
    if not os.path.exists(sqlite_db_path):
        return []
    conn = sqlite3.connect(sqlite_db_path)
    try:
        create_tables(conn)
        cur = conn.cursor()
        pid_str = str(project_id).strip()

        cur.execute("PRAGMA table_info(sld_diagrams)")
        cols = [col[1] for col in cur.fetchall()]

        if 'diagram_name' in cols:
            cur.execute("""
                SELECT diagram_name, is_primary, updated_at
                FROM sld_diagrams
                WHERE project_id = ?
                ORDER BY is_primary DESC, diagram_name ASC
            """, (pid_str,))
            rows = cur.fetchall()
            return [{'diagram_name': r[0], 'is_primary': r[1], 'updated_at': r[2] or ''} for r in rows]
        else:
            cur.execute("SELECT sld_json FROM sld_diagrams WHERE project_id = ?", (pid_str,))
            r = cur.fetchone()
            if r and r[0]:
                return [{'diagram_name': 'Diagram 1', 'is_primary': 1, 'updated_at': ''}]
            return []
    finally:
        conn.close()


def load_sld_from_sqlite(sqlite_db_path, project_id, diagram_name=None):
    """
    Loads and returns (diagram_name, sld_json) for the specified project and diagram name.
    If diagram_name is None, loads the primary diagram or the first available diagram.
    """
    if not os.path.exists(sqlite_db_path):
        return None, None
    conn = sqlite3.connect(sqlite_db_path)
    try:
        create_tables(conn)
        cur = conn.cursor()
        pid_str = str(project_id).strip()

        cur.execute("PRAGMA table_info(sld_diagrams)")
        cols = [col[1] for col in cur.fetchall()]

        if 'diagram_name' in cols:
            if diagram_name:
                cur.execute("""
                    SELECT diagram_name, sld_json
                    FROM sld_diagrams
                    WHERE project_id = ? AND diagram_name = ?
                """, (pid_str, str(diagram_name).strip()))
            else:
                cur.execute("""
                    SELECT diagram_name, sld_json
                    FROM sld_diagrams
                    WHERE project_id = ?
                    ORDER BY is_primary DESC, diagram_name ASC
                    LIMIT 1
                """, (pid_str,))
            r = cur.fetchone()
            if r:
                return r[0], r[1]
            return None, None
        else:
            cur.execute("SELECT sld_json FROM sld_diagrams WHERE project_id = ?", (pid_str,))
            r = cur.fetchone()
            if r and r[0]:
                return "Diagram 1", r[0]
            return None, None
    finally:
        conn.close()


def delete_sld_from_sqlite(sqlite_db_path, project_id, diagram_name):
    """
    Deletes a specific SLD diagram from an SQLite project.
    """
    if not os.path.exists(sqlite_db_path):
        return
    conn = sqlite3.connect(sqlite_db_path)
    try:
        cur = conn.cursor()
        pid_str = str(project_id).strip()
        cur.execute("PRAGMA table_info(sld_diagrams)")
        cols = [col[1] for col in cur.fetchall()]
        if 'diagram_name' in cols:
            cur.execute("DELETE FROM sld_diagrams WHERE project_id = ? AND diagram_name = ?", (pid_str, str(diagram_name).strip()))
        else:
            cur.execute("DELETE FROM sld_diagrams WHERE project_id = ?", (pid_str,))
        conn.commit()
    finally:
        conn.close()


def rename_sld_in_sqlite(sqlite_db_path, project_id, old_name, new_name):
    """
    Renames an SLD diagram in an SQLite project.
    """
    if not os.path.exists(sqlite_db_path):
        return
    conn = sqlite3.connect(sqlite_db_path)
    try:
        cur = conn.cursor()
        pid_str = str(project_id).strip()
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("PRAGMA table_info(sld_diagrams)")
        cols = [col[1] for col in cur.fetchall()]
        if 'diagram_name' in cols:
            cur.execute("""
                UPDATE sld_diagrams
                SET diagram_name = ?, updated_at = ?
                WHERE project_id = ? AND diagram_name = ?
            """, (str(new_name).strip(), now_str, pid_str, str(old_name).strip()))
            conn.commit()
    finally:
        conn.close()

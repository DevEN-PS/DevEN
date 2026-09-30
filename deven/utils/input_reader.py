# DevEN Path Bootstrapper
import sys
import os
_root_dir = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(_root_dir) in ('engines', 'utils', 'cli'):
    _root_dir = os.path.dirname(_root_dir)
if _root_dir not in sys.path:
    sys.path.insert(0, _root_dir)
for _sub in ('engines', 'utils', 'cli'):
    _p = os.path.join(_root_dir, _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)

"""
Input Reader - Handles various input formats
Can be modified to support different input file types without changing engine
"""

import importlib.util
import os

class InputReader:
    """
    Reads power system data from various formats
    Currently supports: Python file with data lists
    """
    
    @staticmethod
    def is_sqlite_file(file_path):
        """Checks if a file is a valid SQLite3 binary database."""
        if not file_path or not os.path.exists(file_path):
            return False
        try:
            with open(file_path, 'rb') as f:
                header = f.read(16)
                return header.startswith(b'SQLite format 3\x00')
        except Exception:
            return False

    @staticmethod
    def read_from_python(file_path, project_id=None):
        """
        Read data from Python format or SQLite format input file
        Format includes: BUS_DATA, GENERATOR_DATA, LOAD_DATA, LINE_DATA, 
                         TRANSFORMER_DATA, CAPACITOR_DATA, REACTOR_DATA,
                         SERIES_COMP_DATA, SERIES_REACTOR_DATA, SHUNT_DATA
        
        Extended with: AREA, ZONE, OWNER fields
        """
        # Direct SQLite database support (.db / .sqlite / .sql binary)
        if InputReader.is_sqlite_file(file_path):
            return InputReader.read_from_sqlite(file_path, project_id=project_id)

        # Direct SQL script dump support (.sql text)
        if file_path and str(file_path).lower().endswith('.sql'):
            try:
                import sqlite3
                cached_db = os.path.splitext(file_path)[0] + ".db"
                if not os.path.exists(cached_db) or os.path.getmtime(cached_db) < os.path.getmtime(file_path):
                    if os.path.exists(cached_db):
                        try:
                            os.remove(cached_db)
                        except Exception:
                            pass
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as sf:
                        sql_content = sf.read()
                    conn = sqlite3.connect(cached_db)
                    conn.executescript(sql_content)
                    conn.commit()
                    conn.close()
                if InputReader.is_sqlite_file(cached_db):
                    return InputReader.read_from_sqlite(cached_db, project_id=project_id)
            except Exception as e_sql:
                print(f"  [X] Failed to parse SQL script file '{file_path}': {e_sql}")

        try:
            import types
            case_name = os.path.splitext(os.path.basename(file_path))[0]
            
            # Try standard importlib spec
            module = None
            try:
                spec = importlib.util.spec_from_file_location(case_name, file_path)
                if spec is not None and spec.loader is not None:
                    module = importlib.util.module_from_spec(spec)
                    try:
                        import numpy as _np
                        module.__dict__['np'] = _np
                        module.__dict__['numpy'] = _np
                    except ImportError:
                        pass
                    spec.loader.exec_module(module)
            except Exception:
                module = None

            # Fallback: exec python code directly (handles .db / .dat files that contain Python code)
            if module is None:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    code_text = f.read()
                module = types.ModuleType(case_name)
                try:
                    import numpy as _np
                    module.__dict__['np'] = _np
                    module.__dict__['numpy'] = _np
                except ImportError:
                    pass
                exec(code_text, module.__dict__)
            
            # Extract data
            bus_data = {}
            bus_attr = getattr(module, 'BUS_DATA', getattr(module, 'bus_data', []))
            if bus_attr:
                for row in bus_attr:
                    bus_num = row[0]
                    bus_data[bus_num] = {
                        'bus_num': bus_num,
                        'name': row[1] if len(row) > 1 else f"Bus_{bus_num}",
                        'type': row[2] if len(row) > 2 else 1,
                        'base_kV': row[3] if len(row) > 3 else 132.0,
                        'V_init': row[4] if len(row) > 4 else 1.0,
                        'angle_init': row[5] if len(row) > 5 else 0.0,
                        'area': row[8] if len(row) > 8 else 1,  # AREA field
                        'zone': row[9] if len(row) > 9 else 1,  # ZONE field
                        'owner': row[10] if len(row) > 10 else 1,  # OWNER field
                        'shunt_G': row[6] if len(row) > 6 else 0,
                        'shunt_B': row[7] if len(row) > 7 else 0
                    }
            
            # Generator data
            generator_data = {}
            gen_attr = getattr(module, 'GENERATOR_DATA', getattr(module, 'generator_data', []))
            if gen_attr:
                for row in gen_attr:
                    generator_data[row[0]] = {
                        'num': row[0],
                        'name': row[1] if len(row) > 1 else f"Gen_{row[0]}",
                        'type': row[2] if len(row) > 2 else 1,
                        'bus': row[3] if len(row) > 3 else row[0],
                        'area': row[10] if len(row) > 10 else 1,
                        'zone': row[11] if len(row) > 11 else 1,
                        'owner': row[12] if len(row) > 12 else 1,
                        'P_out': row[4] if len(row) > 4 else 0.0,
                        'Q_out': row[5] if len(row) > 5 else 0.0,
                        'V_set': row[6] if len(row) > 6 else 1.0,
                        'Qmin': row[7] if len(row) > 7 else -9999.0,
                        'Qmax': row[8] if len(row) > 8 else 9999.0,
                        'status': row[9] if len(row) > 9 else 1,
                        'r1': float(row[13]) if len(row) > 13 and isinstance(row[13], (int, float)) else None,
                        'x1': float(row[14]) if len(row) > 14 and isinstance(row[14], (int, float)) else None,
                        'r2': float(row[15]) if len(row) > 15 and isinstance(row[15], (int, float)) else None,
                        'x2': float(row[16]) if len(row) > 16 and isinstance(row[16], (int, float)) else None,
                        'r0': float(row[17]) if len(row) > 17 and isinstance(row[17], (int, float)) else None,
                        'x0': float(row[18]) if len(row) > 18 and isinstance(row[18], (int, float)) else None,
                        'cb_mva': float(row[19]) if len(row) > 19 and isinstance(row[19], (int, float)) else None,
                        'wind_conn': str(row[20]) if len(row) > 20 else '0',
                        'gnd_r': float(row[21]) if len(row) > 21 and isinstance(row[21], (int, float)) else 0.0,
                        'gnd_x': float(row[22]) if len(row) > 22 and isinstance(row[22], (int, float)) else 0.0,
                    }
            
            # Load data
            load_data = {}
            load_attr = getattr(module, 'LOAD_DATA', getattr(module, 'load_data', []))
            if load_attr:
                for row in load_attr:
                    load_status = 1
                    if len(row) > 9 and isinstance(row[9], (int, float)):
                        load_status = int(row[9])
                    load_data[row[0]] = {
                        'num': row[0], 'name': row[1], 'bus': row[2],
                        'area': row[6] if len(row) > 6 else 1,
                        'zone': row[7] if len(row) > 7 else 1,
                        'P_demand': row[3], 'Q_demand': row[4], 'model': row[5],
                        'scope': 'Both',
                        'status': load_status
                    }


            # Line data with length calculation
            line_data = {}
            line_attr = getattr(module, 'LINE_DATA', getattr(module, 'line_data', []))
            if line_attr:
                for row in line_attr:
                    length_km = row[4] if len(row) > 4 else 0
                    R_per_km = row[5] if len(row) > 5 else 0
                    X_per_km = row[6] if len(row) > 6 else 0
                    B_per_km = row[7] if len(row) > 7 else 0
                    
                    # Calculate total values from per-km and length
                    R_total = R_per_km * length_km
                    X_total = X_per_km * length_km
                    B_total = B_per_km * length_km

                    r0_km = float(row[13]) if len(row) > 13 and isinstance(row[13], (int, float)) else 0.0
                    x0_km = float(row[14]) if len(row) > 14 and isinstance(row[14], (int, float)) else 0.0
                    b0_km = float(row[15]) if len(row) > 15 and isinstance(row[15], (int, float)) else 0.0
                    from_cb = float(row[16]) if len(row) > 16 and isinstance(row[16], (int, float)) else 0.0
                    to_cb = float(row[17]) if len(row) > 17 and isinstance(row[17], (int, float)) else 0.0
                    r0_tot = r0_km * length_km if (length_km > 0 and r0_km > 0) else r0_km
                    x0_tot = x0_km * length_km if (length_km > 0 and x0_km > 0) else x0_km
                    b0_tot = b0_km * length_km if (length_km > 0 and b0_km > 0) else b0_km
                    
                    line_data[row[0]] = {
                        'num': row[0], 'name': row[1],
                        'from_bus': row[2], 'to_bus': row[3],
                        'length_km': length_km, 'length': length_km,
                        'R_per_km': R_per_km, 'X_per_km': X_per_km, 'B_per_km': B_per_km,
                        'r': R_total, 'x': X_total, 'b': B_total,  # These go to engine
                        'rateA': row[8] if len(row) > 8 else 0,
                        'status': row[9] if len(row) > 9 else 1,
                        'area': row[10] if len(row) > 10 else 1,
                        'zone': row[11] if len(row) > 11 else 1,
                        'owner': row[12] if len(row) > 12 else 1,
                        'R0_per_km': r0_km, 'X0_per_km': x0_km, 'B0_per_km': b0_km,
                        'r0': r0_tot, 'x0': x0_tot, 'b0': b0_tot,
                        'from_cb_mva': from_cb, 'to_cb_mva': to_cb
                    }

            # Transformer data (NO length - direct R, X)
            transformer_data = {}
            xfmr_attr = getattr(module, 'TRANSFORMER_DATA', getattr(module, 'transformer_data', []))
            if xfmr_attr:
                for row in xfmr_attr:
                    tap_ratio = float(row[6]) if len(row) > 6 and row[6] is not None else 1.0
                    r0_val = float(row[16]) if len(row) > 16 and isinstance(row[16], (int, float)) else 0.0
                    x0_val = float(row[17]) if len(row) > 17 and isinstance(row[17], (int, float)) else 0.0
                    transformer_data[row[0]] = {
                        'num': row[0], 'name': row[1],
                        'from_bus': row[2], 'to_bus': row[3],
                        'r': row[4] if len(row) > 4 else 0,
                        'x': row[5] if len(row) > 5 else 0,
                        'tap_ratio': tap_ratio,
                        'ratio': tap_ratio,
                        'rateA': row[7] if len(row) > 7 else 9999,
                        'phase_shift': row[8] if len(row) > 8 else 0,
                        'min_tap': row[9] if len(row) > 9 else 0.9,
                        'max_tap': row[10] if len(row) > 10 else 1.1,
                        'step_size': row[11] if len(row) > 11 else 0.01,
                        'status': row[12] if len(row) > 12 else 1,
                        'area': row[13] if len(row) > 13 else 1,
                        'zone': row[14] if len(row) > 14 else 1,
                        'owner': row[15] if len(row) > 15 else 1,
                        'R0_pu': r0_val, 'X0_pu': x0_val,
                        'r0': r0_val, 'x0': x0_val,
                        'from_conn': str(row[18]) if len(row) > 18 else '0',
                        'to_conn': str(row[19]) if len(row) > 19 else '0',
                        'from_gnd_r': float(row[20]) if len(row) > 20 and isinstance(row[20], (int, float)) else 0.0,
                        'from_gnd_x': float(row[21]) if len(row) > 21 and isinstance(row[21], (int, float)) else 0.0,
                        'to_gnd_r': float(row[22]) if len(row) > 22 and isinstance(row[22], (int, float)) else 0.0,
                        'to_gnd_x': float(row[23]) if len(row) > 23 and isinstance(row[23], (int, float)) else 0.0,
                        'from_cb_mva': float(row[24]) if len(row) > 24 and isinstance(row[24], (int, float)) else 0.0,
                        'to_cb_mva': float(row[25]) if len(row) > 25 and isinstance(row[25], (int, float)) else 0.0
                    }


            # Capacitor data
            capacitor_data = {}
            if hasattr(module, 'CAPACITOR_DATA'):
                for row in module.CAPACITOR_DATA:
                    capacitor_data[row[0]] = {
                        'num': row[0], 'name': row[1], 'bus': row[2],
                        'area': row[5] if len(row) > 5 else 1,
                        'zone': row[6] if len(row) > 6 else 1,
                        'Q_cap': row[3], 'status': row[4]
                    }
            
            # Reactor data
            reactor_data = {}
            if hasattr(module, 'REACTOR_DATA'):
                for row in module.REACTOR_DATA:
                    reactor_data[row[0]] = {
                        'num': row[0], 'name': row[1], 'bus': row[2],
                        'area': row[5] if len(row) > 5 else 1,
                        'zone': row[6] if len(row) > 6 else 1,
                        'Q_react': row[3], 'status': row[4]
                    }
            
            # Series Compensation data
            series_comp_data = {}
            if hasattr(module, 'SERIES_COMP_DATA'):
                for row in module.SERIES_COMP_DATA:
                    series_comp_data[row[0]] = {
                        'num': row[0], 'name': row[1],
                        'from_bus': row[2], 'to_bus': row[3],
                        'area': row[8] if len(row) > 8 else 1,
                        'zone': row[9] if len(row) > 9 else 1,
                        'owner': row[10] if len(row) > 10 else 1,
                        'r': row[4], 'x': row[5], 'comp_pct': row[6], 'status': row[7]
                    }
            
            # Series Reactor data
            series_reactor_data = {}
            if hasattr(module, 'SERIES_REACTOR_DATA'):
                for row in module.SERIES_REACTOR_DATA:
                    series_reactor_data[row[0]] = {
                        'num': row[0], 'name': row[1],
                        'from_bus': row[2], 'to_bus': row[3],
                        'area': row[7] if len(row) > 7 else 1,
                        'zone': row[8] if len(row) > 8 else 1,
                        'owner': row[9] if len(row) > 9 else 1,
                        'r': row[4], 'x': row[5], 'status': row[6]
                    }
            
            # Shunt data
            shunt_data = {}
            if hasattr(module, 'SHUNT_DATA'):
                for row in module.SHUNT_DATA:
                    shunt_data[row[0]] = {
                        'num': row[0], 'name': row[1], 'bus': row[2],
                        'area': row[5] if len(row) > 5 else 1,
                        'zone': row[6] if len(row) > 6 else 1,
                        'Q_shunt': row[3], 'status': row[4]
                    }

            # BESS (Battery Energy Storage System) data
            bess_data = {}
            if hasattr(module, 'BESS_DATA') or hasattr(module, 'STORAGE_DATA'):
                bess_attr = getattr(module, 'BESS_DATA', getattr(module, 'STORAGE_DATA', []))
                for row in bess_attr:
                    bess_data[row[0]] = {
                        'num': row[0],
                        'name': row[1] if len(row) > 1 else f"BESS_{row[0]}",
                        'bus': row[2] if len(row) > 2 else 1,
                        'p_rated_mw': float(row[3]) if len(row) > 3 else 5.0,
                        'energy_mwh': float(row[4]) if len(row) > 4 else 20.0,
                        'soc_init': float(row[5]) if len(row) > 5 else 0.5,
                        'soc_min': float(row[6]) if len(row) > 6 else 0.1,
                        'soc_max': float(row[7]) if len(row) > 7 else 0.9,
                        'eff_ch': float(row[8]) if len(row) > 8 else 0.95,
                        'eff_dis': float(row[9]) if len(row) > 9 else 0.95,
                        'self_disch_rate': float(row[10]) if len(row) > 10 else 0.0001,
                        'q_mode': str(row[11]) if len(row) > 11 else "pf",
                        'power_factor': float(row[12]) if len(row) > 12 else 1.0,
                        'strategy': str(row[13]) if len(row) > 13 else "peak_shaving",
                        'target_mw': float(row[14]) if len(row) > 14 else 0.0,
                        'status': int(row[15]) if len(row) > 15 else 1,
                        'area': row[16] if len(row) > 16 else 1,
                        'zone': row[17] if len(row) > 17 else 1,
                        'owner': row[18] if len(row) > 18 else 1
                    }
            
            # 3-Winding Transformer data
            three_winding_transformer_data = {}
            three_w_attr = getattr(module, 'THREE_WINDING_TRANSFORMER_DATA', None) or getattr(module, 'THREE_WINDING_XFMR_DATA', None)
            if three_w_attr:
                for row in three_w_attr:
                    three_winding_transformer_data[row[0]] = {
                        'num': row[0], 'name': row[1],
                        'hv_bus': row[2], 'mv_bus': row[3], 'lv_bus': row[4],
                        'r_hm': row[5] if len(row) > 5 else 0.0,
                        'x_hm': row[6] if len(row) > 6 else 0.05,
                        'r_hl': row[7] if len(row) > 7 else 0.0,
                        'x_hl': row[8] if len(row) > 8 else 0.05,
                        'r_ml': row[9] if len(row) > 9 else 0.0,
                        'x_ml': row[10] if len(row) > 10 else 0.05,
                        'rate_h': row[11] if len(row) > 11 else 9999,
                        'rate_m': row[12] if len(row) > 12 else 9999,
                        'rate_l': row[13] if len(row) > 13 else 9999,
                        'tap_h': row[14] if len(row) > 14 else 1.0,
                        'tap_m': row[15] if len(row) > 15 else 1.0,
                        'tap_l': row[16] if len(row) > 16 else 1.0,
                        'status': row[17] if len(row) > 17 else 1,
                        'area': row[18] if len(row) > 18 else 1,
                        'zone': row[19] if len(row) > 19 else 1,
                        'owner': row[20] if len(row) > 20 else 1
                    }

            # HVDC Link data
            hvdc_link_data = {}
            if hasattr(module, 'HVDC_LINK_DATA'):
                for row in module.HVDC_LINK_DATA:
                    hvdc_link_data[row[0]] = {
                        'num': row[0],
                        'name': row[1],
                        'from_bus': row[2],
                        'to_bus': row[3],
                        'r_dc': float(row[4]) if len(row) > 4 else 0.0,
                        'status': int(row[5]) if len(row) > 5 else 1,
                        # From Side (Rectifier)
                        'from_mode': str(row[6]) if len(row) > 6 else "Rectifier",
                        'from_ctrl_type': int(row[7]) if len(row) > 7 else 3,
                        'from_val': float(row[8]) if len(row) > 8 else 50.0,
                        'from_angle': float(row[9]) if len(row) > 9 else 12.0,
                        'from_xc': float(row[10]) if len(row) > 10 else 0.0,
                        'from_tfr_kv': float(row[11]) if len(row) > 11 else 220.0,
                        'from_tfr_mva': float(row[12]) if len(row) > 12 else 100.0,
                        'from_tap_min': float(row[13]) if len(row) > 13 else 0.85,
                        'from_tap_max': float(row[14]) if len(row) > 14 else 1.20,
                        'from_tap_step': float(row[15]) if len(row) > 15 else 0.0125,
                        'from_nb': int(row[16]) if len(row) > 16 else 1,
                        'from_np': int(row[17]) if len(row) > 17 else 1,
                        # To Side (Inverter)
                        'to_mode': str(row[18]) if len(row) > 18 else "Inverter",
                        'to_ctrl_type': int(row[19]) if len(row) > 19 else 1,
                        'to_val': float(row[20]) if len(row) > 20 else 220.0,
                        'to_angle': float(row[21]) if len(row) > 21 else 15.0,
                        'to_xc': float(row[22]) if len(row) > 22 else 0.0,
                        'to_tfr_kv': float(row[23]) if len(row) > 23 else 220.0,
                        'to_tfr_mva': float(row[24]) if len(row) > 24 else 100.0,
                        'to_tap_min': float(row[25]) if len(row) > 25 else 0.85,
                        'to_tap_max': float(row[26]) if len(row) > 26 else 1.20,
                        'to_tap_step': float(row[27]) if len(row) > 27 else 0.0125,
                        'to_nb': int(row[28]) if len(row) > 28 else 1,
                        'to_np': int(row[29]) if len(row) > 29 else 1,
                        'area': row[30] if len(row) > 30 else 1,
                        'zone': row[31] if len(row) > 31 else 1,
                        'owner': row[32] if len(row) > 32 else 1,
                    }

            baseMVA = getattr(module, 'BASE_MVA', 100.0)
            solver_config = getattr(module, 'SIMULATION_SETTINGS', getattr(module, 'SOLVER_CONFIG', {}))
            
            # SLD Diagrams
            sld_diagrams = {}
            if hasattr(module, 'SLD_DIAGRAMS') and isinstance(module.SLD_DIAGRAMS, dict):
                sld_diagrams = module.SLD_DIAGRAMS
            elif hasattr(module, 'SLD_DATA'):
                sld_diagrams = {'Diagram 1': module.SLD_DATA}

            # Guarantee 100% clean and unique names for all element dictionaries
            InputReader._ensure_unique_element_names(bus_data, 'bus')
            InputReader._ensure_unique_element_names(generator_data, 'gen')
            InputReader._ensure_unique_element_names(load_data, 'load')
            InputReader._ensure_unique_element_names(line_data, 'line')
            InputReader._ensure_unique_element_names(transformer_data, 'xfmr')
            InputReader._ensure_unique_element_names(three_winding_transformer_data, '3wxfmr')
            InputReader._ensure_unique_element_names(capacitor_data, 'cap')
            InputReader._ensure_unique_element_names(reactor_data, 'reactor')
            InputReader._ensure_unique_element_names(shunt_data, 'shunt')
            InputReader._ensure_unique_element_names(hvdc_link_data, 'hvdc')
            InputReader._ensure_unique_element_names(bess_data, 'bess')

            # Time Series Settings & Profiles
            time_series_settings = getattr(module, 'TIME_SERIES_SETTINGS', {})
            time_series_profiles = getattr(module, 'TIME_SERIES_PROFILES', {})
            if isinstance(time_series_profiles, dict):
                for gid, prof in time_series_profiles.get('generators', {}).items():
                    if gid in generator_data and prof:
                        generator_data[gid]['time_series'] = prof
                for lid, prof in time_series_profiles.get('loads', {}).items():
                    if lid in load_data and prof:
                        load_data[lid]['time_series'] = prof
                for cid, prof in time_series_profiles.get('capacitors', {}).items():
                    if cid in capacitor_data and prof:
                        capacitor_data[cid]['time_series'] = prof
                for rid, prof in time_series_profiles.get('reactors', {}).items():
                    if rid in reactor_data and prof:
                        reactor_data[rid]['time_series'] = prof
                for sid, prof in time_series_profiles.get('shunts', {}).items():
                    if sid in shunt_data and prof:
                        shunt_data[sid]['time_series'] = prof

            print(
                f" Read {len(bus_data)} buses, "
                f" Read {len(generator_data)} generators, "
                f" Read {len(load_data)} loads, "
                f" Read {len(line_data)} lines, "
                f" Read {len(transformer_data)} transformers, "
                f" Read {len(bess_data)} BESS"
            )            
            harmonic_sources = getattr(module, 'HARMONIC_SOURCES', getattr(module, 'harmonic_sources', []))
            harmonic_filters = getattr(module, 'HARMONIC_FILTERS', getattr(module, 'harmonic_filters', []))

            return {
                'baseMVA': baseMVA,
                'solver_config': solver_config,
                'simulation_settings': solver_config,
                'time_series_settings': time_series_settings,
                'time_series_profiles': time_series_profiles,
                'buses': bus_data,
                'generators': generator_data,
                'loads': load_data,
                'lines': line_data,
                'transformers': transformer_data,
                'capacitors': capacitor_data,
                'reactors': reactor_data,
                'series_comps': series_comp_data,
                'series_reactors': series_reactor_data,
                'shunts': shunt_data,
                'bess': bess_data,
                'hvdc_links': hvdc_link_data,
                'three_winding_transformers': three_winding_transformer_data,
                'harmonic_sources': harmonic_sources,
                'harmonic_filters': harmonic_filters,
                'sld_diagrams': sld_diagrams,
                'sld_data': sld_diagrams.get('Diagram 1') if sld_diagrams else None
            }
        except Exception as e:
            print(f"  [X] Error reading python file: {e}")
            return None

    @staticmethod
    def read_from_sqlite(file_path, project_id=None):
        """
        Read power system data directly from an SQLite database container (.db / .sqlite).
        """
        try:
            from tools.sqldb.converter import load_project_dict_from_sqlite, list_projects
            
            if not project_id:
                project_id = os.environ.get('DEVEN_PROJECT_ID', None)

            if not project_id:
                projects = list_projects(file_path)
                if not projects:
                    raise ValueError(f"SQLite database {file_path} contains no projects.")
                project_id = projects[0]['project_id']

            proj = load_project_dict_from_sqlite(file_path, project_id)

            # Bus data
            bus_data = {}
            for b_id, b in proj.get('buses', {}).items():
                bus_data[int(b_id)] = {
                    'bus_num': int(b_id),
                    'name': b.get('name', f"Bus_{b_id}"),
                    'type': int(b.get('type', 1)),
                    'base_kV': float(b.get('base_kV', 132.0)),
                    'V_init': float(b.get('V_init', 1.0)),
                    'angle_init': float(b.get('angle_init', 0.0)),
                    'area': int(b.get('area', 1)),
                    'zone': int(b.get('zone', 1)),
                    'owner': int(b.get('owner', 1)),
                    'shunt_G': float(b.get('shunt_G', 0.0)),
                    'shunt_B': float(b.get('shunt_B', 0.0))
                }

            # Generator data
            generator_data = {}
            for g_id, g in proj.get('generators', {}).items():
                r1_val = float(g.get('R1_pu', 0.0)) if g.get('R1_pu') is not None else None
                x1_val = float(g.get('X1_pu', 0.0)) if g.get('X1_pu') is not None else None
                r2_val = float(g.get('R2_pu', 0.0)) if g.get('R2_pu') is not None else None
                x2_val = float(g.get('X2_pu', 0.0)) if g.get('X2_pu') is not None else None
                r0_val = float(g.get('R0_pu', 0.0)) if g.get('R0_pu') is not None else None
                x0_val = float(g.get('X0_pu', 0.0)) if g.get('X0_pu') is not None else None
                generator_data[int(g_id)] = {
                    'num': int(g_id),
                    'name': g.get('name', f"Gen_{g_id}"),
                    'type': g.get('type', 'Thermal'),
                    'bus': int(g.get('bus', 1)),
                    'area': int(g.get('area', 1)),
                    'zone': int(g.get('zone', 1)),
                    'owner': int(g.get('owner', 1)),
                    'P_out': float(g.get('P_out', 0.0)),
                    'Q_out': float(g.get('Q_out', 0.0)),
                    'V_set': float(g.get('V_set', 1.0)),
                    'Qmin': float(g.get('Qmin', -9999.0)),
                    'Qmax': float(g.get('Qmax', 9999.0)),
                    'status': int(g.get('status', 1)),
                    'scope': 'Both',
                    'r1': r1_val, 'x1': x1_val,
                    'r2': r2_val, 'x2': x2_val,
                    'r0': r0_val, 'x0': x0_val,
                    'R1_pu': r1_val or 0.0, 'X1_pu': x1_val or 0.0,
                    'R2_pu': r2_val or 0.0, 'X2_pu': x2_val or 0.0,
                    'R0_pu': r0_val or 0.0, 'X0_pu': x0_val or 0.0,
                    'cb_mva': float(g.get('cb_mva', 0.0)),
                    'wind_conn': str(g.get('wind_conn', '0')),
                    'gnd_r': float(g.get('gnd_r', 0.0)),
                    'gnd_x': float(g.get('gnd_x', 0.0))
                }

            # Load data
            load_data = {}
            for l_id, l in proj.get('loads', {}).items():
                load_data[int(l_id)] = {
                    'num': int(l_id),
                    'name': l.get('name', f"Load_{l_id}"),
                    'bus': int(l.get('bus', 1)),
                    'area': int(l.get('area', 1)),
                    'zone': int(l.get('zone', 1)),
                    'P_demand': float(l.get('P_demand', 0.0)),
                    'Q_demand': float(l.get('Q_demand', 0.0)),
                    'model': l.get('model', 'Constant Power'),
                    'scope': 'Both',
                    'status': int(l.get('status', 1))
                }

            # Line data
            line_data = {}
            for ln_id, ln in proj.get('lines', {}).items():
                l_km = float(ln.get('length_km', ln.get('length', 0.0)))
                r_val = float(ln.get('r', ln.get('R_per_km', 0.0) * l_km if l_km > 0 else ln.get('R_per_km', 0.0)))
                x_val = float(ln.get('x', ln.get('X_per_km', 0.0) * l_km if l_km > 0 else ln.get('X_per_km', 0.0)))
                b_val = float(ln.get('b', ln.get('B_per_km', 0.0) * l_km if l_km > 0 else ln.get('B_per_km', 0.0)))
                r0_km = float(ln.get('R0_per_km', 0.0))
                x0_km = float(ln.get('X0_per_km', 0.0))
                b0_km = float(ln.get('B0_per_km', 0.0))
                line_data[int(ln_id)] = {
                    'num': int(ln_id),
                    'name': ln.get('name', f"Line_{ln_id}"),
                    'from_bus': int(ln.get('from_bus', 1)),
                    'to_bus': int(ln.get('to_bus', 2)),
                    'area': int(ln.get('area', 1)),
                    'zone': int(ln.get('zone', 1)),
                    'owner': int(ln.get('owner', 1)),
                    'length': l_km,
                    'length_km': l_km,
                    'R_per_km': float(ln.get('R_per_km', 0.0)),
                    'X_per_km': float(ln.get('X_per_km', 0.0)),
                    'B_per_km': float(ln.get('B_per_km', 0.0)),
                    'r': r_val, 'x': x_val, 'b': b_val,
                    'rateA': float(ln.get('rateA', 0.0)),
                    'status': int(ln.get('status', 1)),
                    'R0_per_km': r0_km, 'X0_per_km': x0_km, 'B0_per_km': b0_km,
                    'r0': r0_km * l_km if (l_km > 0 and r0_km > 0) else r0_km,
                    'x0': x0_km * l_km if (l_km > 0 and x0_km > 0) else x0_km,
                    'b0': b0_km * l_km if (l_km > 0 and b0_km > 0) else b0_km,
                    'from_cb_mva': float(ln.get('from_cb_mva', 0.0)),
                    'to_cb_mva': float(ln.get('to_cb_mva', 0.0))
                }

            # Transformer data
            transformer_data = {}
            for x_id, xf in proj.get('transformers', {}).items():
                tap_val = float(xf.get('tap_ratio', xf.get('ratio', 1.0)))
                r0_val = float(xf.get('R0_pu', xf.get('r0', 0.0)))
                x0_val = float(xf.get('X0_pu', xf.get('x0', 0.0)))
                transformer_data[int(x_id)] = {
                    'num': int(x_id),
                    'name': xf.get('name', f"Xfmr_{x_id}"),
                    'from_bus': int(xf.get('from_bus', 1)),
                    'to_bus': int(xf.get('to_bus', 2)),
                    'area': int(xf.get('area', 1)),
                    'zone': int(xf.get('zone', 1)),
                    'owner': int(xf.get('owner', 1)),
                    'r': float(xf.get('r', 0.0)),
                    'x': float(xf.get('x', 0.05)),
                    'tap_ratio': tap_val,
                    'ratio': tap_val,
                    'rateA': float(xf.get('rateA', 9999.0)),
                    'phase_shift': float(xf.get('phase_shift', 0.0)),
                    'min_tap': float(xf.get('min_tap', 0.9)),
                    'max_tap': float(xf.get('max_tap', 1.1)),
                    'step_size': float(xf.get('step_size', 0.01)),
                    'status': int(xf.get('status', 1)),
                    'R0_pu': r0_val, 'X0_pu': x0_val,
                    'r0': r0_val, 'x0': x0_val,
                    'from_conn': str(xf.get('from_conn', '0')),
                    'to_conn': str(xf.get('to_conn', '0')),
                    'from_gnd_r': float(xf.get('from_gnd_r', 0.0)),
                    'from_gnd_x': float(xf.get('from_gnd_x', 0.0)),
                    'to_gnd_r': float(xf.get('to_gnd_r', 0.0)),
                    'to_gnd_x': float(xf.get('to_gnd_x', 0.0)),
                    'from_cb_mva': float(xf.get('from_cb_mva', 0.0)),
                    'to_cb_mva': float(xf.get('to_cb_mva', 0.0))
                }

            # Capacitor data
            capacitor_data = {}
            for c_id, c in proj.get('capacitors', {}).items():
                capacitor_data[int(c_id)] = {
                    'num': int(c_id),
                    'name': c.get('name', f"Cap_{c_id}"),
                    'bus': int(c.get('bus', 1)),
                    'area': int(c.get('area', 1)),
                    'zone': int(c.get('zone', 1)),
                    'Q_cap': float(c.get('Q_cap', 0.0)),
                    'status': int(c.get('status', 1))
                }

            # Reactor data
            reactor_data = {}
            for r_id, r in proj.get('reactors', {}).items():
                reactor_data[int(r_id)] = {
                    'num': int(r_id),
                    'name': r.get('name', f"Reactor_{r_id}"),
                    'bus': int(r.get('bus', 1)),
                    'area': int(r.get('area', 1)),
                    'zone': int(r.get('zone', 1)),
                    'Q_react': float(r.get('Q_react', 0.0)),
                    'status': int(r.get('status', 1))
                }

            # Series Comp data
            series_comp_data = {}
            for sc_id, sc in proj.get('series_comps', {}).items():
                series_comp_data[int(sc_id)] = {
                    'num': int(sc_id),
                    'name': sc.get('name', f"SC_{sc_id}"),
                    'from_bus': int(sc.get('from_bus', 1)),
                    'to_bus': int(sc.get('to_bus', 2)),
                    'area': int(sc.get('area', 1)),
                    'zone': int(sc.get('zone', 1)),
                    'owner': int(sc.get('owner', 1)),
                    'r': float(sc.get('r', 0.0)),
                    'x': float(sc.get('x', 0.0)),
                    'comp_pct': float(sc.get('comp_pct', 0.0)),
                    'status': int(sc.get('status', 1))
                }

            # Series Reactor data
            series_reactor_data = {}
            for sr_id, sr in proj.get('series_reactors', {}).items():
                series_reactor_data[int(sr_id)] = {
                    'num': int(sr_id),
                    'name': sr.get('name', f"SR_{sr_id}"),
                    'from_bus': int(sr.get('from_bus', 1)),
                    'to_bus': int(sr.get('to_bus', 2)),
                    'area': int(sr.get('area', 1)),
                    'zone': int(sr.get('zone', 1)),
                    'owner': int(sr.get('owner', 1)),
                    'r': float(sr.get('r', 0.0)),
                    'x': float(sr.get('x', 0.0)),
                    'status': int(sr.get('status', 1))
                }

            # Shunt data
            shunt_data = {}
            for sh_id, sh in proj.get('shunts', {}).items():
                shunt_data[int(sh_id)] = {
                    'num': int(sh_id),
                    'name': sh.get('name', f"Shunt_{sh_id}"),
                    'bus': int(sh.get('bus', 1)),
                    'area': int(sh.get('area', 1)),
                    'zone': int(sh.get('zone', 1)),
                    'Q_shunt': float(sh.get('Q_shunt', 0.0)),
                    'status': int(sh.get('status', 1))
                }

            # 3-Winding Transformer data
            three_winding_transformer_data = {}
            for tw_id, tw in proj.get('three_winding_transformers', {}).items():
                three_winding_transformer_data[int(tw_id)] = {
                    'num': int(tw_id),
                    'name': tw.get('name', f"3WXfmr_{tw_id}"),
                    'hv_bus': int(tw.get('hv_bus', 1)),
                    'mv_bus': int(tw.get('mv_bus', 2)),
                    'lv_bus': int(tw.get('lv_bus', 3)),
                    'r_hm': float(tw.get('r_hm', 0.0)),
                    'x_hm': float(tw.get('x_hm', 0.05)),
                    'r_hl': float(tw.get('r_hl', 0.0)),
                    'x_hl': float(tw.get('x_hl', 0.05)),
                    'r_ml': float(tw.get('r_ml', 0.0)),
                    'x_ml': float(tw.get('x_ml', 0.05)),
                    'rate_h': float(tw.get('rate_h', 9999.0)),
                    'rate_m': float(tw.get('rate_m', 9999.0)),
                    'rate_l': float(tw.get('rate_l', 9999.0)),
                    'tap_h': float(tw.get('tap_h', 1.0)),
                    'tap_m': float(tw.get('tap_m', 1.0)),
                    'tap_l': float(tw.get('tap_l', 1.0)),
                    'status': int(tw.get('status', 1)),
                    'area': int(tw.get('area', 1)),
                    'zone': int(tw.get('zone', 1)),
                    'owner': int(tw.get('owner', 1))
                }

            # BESS data
            bess_data = {}
            for b_id, b in proj.get('bess', {}).items():
                bess_data[int(b_id) if str(b_id).isdigit() else b_id] = {
                    'num': int(b_id) if str(b_id).isdigit() else b_id,
                    'name': b.get('name', f"BESS_{b_id}"),
                    'bus': int(b.get('bus', 1)),
                    'p_rated_mw': float(b.get('p_rated_mw', 5.0)),
                    'energy_mwh': float(b.get('energy_mwh', 20.0)),
                    'soc_init': float(b.get('soc_init', 0.5)),
                    'soc_min': float(b.get('soc_min', 0.1)),
                    'soc_max': float(b.get('soc_max', 0.9)),
                    'eff_ch': float(b.get('eff_ch', 0.95)),
                    'eff_dis': float(b.get('eff_dis', 0.95)),
                    'self_disch_rate': float(b.get('self_disch_rate', 0.0001)),
                    'q_mode': str(b.get('q_mode', 'pf')),
                    'power_factor': float(b.get('power_factor', 1.0)),
                    'strategy': str(b.get('strategy', 'peak_shaving')),
                    'target_mw': float(b.get('target_mw', 0.0)),
                    'status': int(b.get('status', 1)),
                    'area': int(b.get('area', 1)),
                    'zone': int(b.get('zone', 1)),
                    'owner': int(b.get('owner', 1))
                }

            baseMVA = float(proj.get('base_mva', 100.0))
            solver_config = dict(proj.get('simulation_settings') or proj.get('solver_config', {}))

            InputReader._ensure_unique_element_names(bus_data, 'bus')
            InputReader._ensure_unique_element_names(generator_data, 'gen')
            InputReader._ensure_unique_element_names(load_data, 'load')
            InputReader._ensure_unique_element_names(line_data, 'line')
            InputReader._ensure_unique_element_names(transformer_data, 'xfmr')
            InputReader._ensure_unique_element_names(three_winding_transformer_data, '3wxfmr')
            InputReader._ensure_unique_element_names(capacitor_data, 'cap')
            InputReader._ensure_unique_element_names(reactor_data, 'reactor')
            InputReader._ensure_unique_element_names(shunt_data, 'shunt')
            InputReader._ensure_unique_element_names(bess_data, 'bess')

            return {
                'project_id': str(proj.get('project_id', project_id or '1')),
                'project_name': str(proj.get('project_name', f"Project_{project_id or '1'}")),
                'baseMVA': baseMVA,
                'buses': bus_data,
                'generators': generator_data,
                'loads': load_data,
                'lines': line_data,
                'transformers': transformer_data,
                'capacitors': capacitor_data,
                'reactors': reactor_data,
                'series_comps': series_comp_data,
                'series_reactors': series_reactor_data,
                'shunts': shunt_data,
                'bess': bess_data,
                'three_winding_transformers': three_winding_transformer_data,
                'harmonic_sources': proj.get('harmonic_sources', []),
                'harmonic_filters': proj.get('harmonic_filters', []),
                'solver_config': solver_config,
                'simulation_settings': solver_config,
                'sld_diagrams': proj.get('sld_diagrams', {}),
                'sld_data': proj.get('sld_json')
            }
        except Exception as e:
            print(f"  [X] Error reading SQLite file: {e}")
            return None

    @staticmethod
    def _ensure_unique_element_names(element_dict, category_name):
        """
        Guarantees that every element in element_dict has a non-empty, clean, and 100% unique 'name'.
        """
        used_names = set()
        for key, item in element_dict.items():
            raw_name = item.get('name')
            if not raw_name or not str(raw_name).strip() or str(raw_name).strip().lower() in ('none', 'null', 'nan', '""', "''"):
                if category_name == 'bus':
                    bnum = item.get('bus_num', key)
                    base_name = f"Bus_{bnum}"
                elif category_name == 'load':
                    bnum = item.get('bus', 0)
                    base_name = f"Load_{bnum}_{key}"
                elif category_name == 'gen':
                    bnum = item.get('bus', 0)
                    base_name = f"Gen_{bnum}_{key}"
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
                    base_name = f"Cap_{bnum}_{key}"
                elif category_name == 'reactor':
                    bnum = item.get('bus', 0)
                    base_name = f"Reactor_{bnum}_{key}"
                elif category_name == 'shunt':
                    bnum = item.get('bus', 0)
                    base_name = f"Shunt_{bnum}_{key}"
                elif category_name == 'hvdc':
                    fbus = item.get('from_bus', 0)
                    tbus = item.get('to_bus', 0)
                    base_name = f"HVDC_{fbus}_{tbus}_{key}"
                elif category_name == 'bess':
                    bnum = item.get('bus', 0)
                    base_name = f"BESS_{bnum}_{key}"
                else:
                    base_name = f"{category_name.capitalize()}_{key}"
            else:
                base_name = str(raw_name).strip().replace('"', '').replace("'", "")

            unique_name = base_name
            counter = 2
            while unique_name in used_names:
                unique_name = f"{base_name}_{counter}"
                counter += 1

            used_names.add(unique_name)
            item['name'] = unique_name


    @staticmethod
    def convert_to_engine_format(input_data):
        """
        Convert input data to engine format
        Extracts bus and branch data needed for power flow
        """
        bus_data = {}
        for bus_num, bus in input_data['buses'].items():
            bus_data[bus_num] = {
                'V_init': bus['V_init'],
                'angle_init': bus['angle_init'],
                'base_kV': bus['base_kV'],
                'type': bus['type'],
                'name': bus['name'],
                'shunt_G': bus.get('shunt_G', 0.0),
                'shunt_B': bus.get('shunt_B', 0.0),
                'area': bus.get('area', 1),
                'zone': bus.get('zone', 1),
                'owner': bus.get('owner', 1)
            }
        
        def to_mvar(val):
            v = abs(float(val or 0.0))
            return v / 1000.0 if v > 1000.0 else v

        # Accumulate shunts from SHUNT_DATA
        for shunt in input_data.get('shunts', {}).values():
            if shunt.get('status', 1) == 1:
                b_num = shunt.get('bus')
                if b_num in bus_data:
                    bus_data[b_num]['shunt_G'] += float(shunt.get('shunt_G', 0.0) or 0.0)
                    q_val = float(shunt.get('Q_shunt', 0.0) or shunt.get('shunt_B', 0.0) or 0.0)
                    bus_data[b_num]['shunt_B'] += to_mvar(q_val)

        # Accumulate capacitors (+B_shunt)
        for cap in input_data.get('capacitors', {}).values():
            if cap.get('status', 1) == 1:
                b_num = cap.get('bus')
                if b_num in bus_data:
                    bus_data[b_num]['shunt_B'] += to_mvar(cap.get('Q_cap', 0.0))

        # Accumulate reactors (-B_shunt)
        for react in input_data.get('reactors', {}).values():
            if react.get('status', 1) == 1:
                b_num = react.get('bus')
                if b_num in bus_data:
                    bus_data[b_num]['shunt_B'] -= to_mvar(react.get('Q_react', 0.0))

        branch_data = []

        # Add lines
        for k, line in input_data.get('lines', {}).items():
            if line.get('status', 1) == 1:
                l_num = line.get('num', line.get('line_num', k))
                branch_data.append({
                    'type': 'line',
                    'num': l_num,
                    'name': line.get('name', f"Line_{l_num}"),
                    'from_bus': line.get('from_bus', 1),
                    'to_bus': line.get('to_bus', 2),
                    'r': float(line.get('r', 0.0)),
                    'x': float(line.get('x', 0.05)),
                    'b': float(line.get('b', 0.0)),
                    'ratio': 0,
                    'rateA': float(line.get('rateA', 0)),
                    'area': line.get('area', 1),
                    'zone': line.get('zone', 1),
                    'owner': line.get('owner', 1)
                })
        
        # Add transformers
        for k, xfmr in input_data.get('transformers', {}).items():
            if xfmr.get('status', 1) == 1:
                x_num = xfmr.get('num', xfmr.get('xfmr_num', k))
                tap = xfmr.get('tap_ratio', xfmr.get('ratio', 1.0))
                branch_data.append({
                    'type': 'transformer',
                    'num': x_num,
                    'name': xfmr.get('name', f"Xfmr_{x_num}"),
                    'from_bus': xfmr.get('from_bus', 1),
                    'to_bus': xfmr.get('to_bus', 2),
                    'r': float(xfmr.get('r', 0.0)),
                    'x': float(xfmr.get('x', 0.05)),
                    'b': 0,
                    'ratio': float(tap),
                    'tap_ratio': float(tap),
                    'phase_shift': float(xfmr.get('phase_shift', 0.0) or 0.0),
                    'rateA': float(xfmr.get('rateA', 9999)),
                    'min_tap': float(xfmr.get('min_tap', 0.9)),
                    'max_tap': float(xfmr.get('max_tap', 1.1)),
                    'step_size': float(xfmr.get('step_size', 0.01)),
                    'area': xfmr.get('area', 1),
                    'zone': xfmr.get('zone', 1),
                    'owner': xfmr.get('owner', 1)
                })

        # Add series compensators (series capacitors)
        for k, scomp in input_data.get('series_comps', {}).items():
            if scomp.get('status', 1) == 1:
                sc_num = scomp.get('num', scomp.get('sc_num', k))
                r_val = float(scomp.get('r', 0.0))
                x_val = float(scomp.get('x', 0.0))
                comp_pct = float(scomp.get('comp_pct', 0.0))
                eff_x = x_val * (1.0 - comp_pct / 100.0)
                branch_data.append({
                    'type': 'line',
                    'num': sc_num,
                    'name': scomp.get('name', f"SC_{sc_num}"),
                    'from_bus': scomp.get('from_bus', 1),
                    'to_bus': scomp.get('to_bus', 2),
                    'r': r_val,
                    'x': eff_x,
                    'b': 0.0,
                    'ratio': 0,
                    'rateA': 9999,
                    'area': scomp.get('area', 1),
                    'zone': scomp.get('zone', 1),
                    'owner': scomp.get('owner', 1)
                })

        # Add series reactors
        for k, sreact in input_data.get('series_reactors', {}).items():
            if sreact.get('status', 1) == 1:
                sr_num = sreact.get('num', sreact.get('sr_num', k))
                branch_data.append({
                    'type': 'line',
                    'num': sr_num,
                    'name': sreact.get('name', f"SR_{sr_num}"),
                    'from_bus': sreact.get('from_bus', 1),
                    'to_bus': sreact.get('to_bus', 2),
                    'r': float(sreact.get('r', 0.0)),
                    'x': float(sreact.get('x', 0.0)),
                    'b': 0.0,
                    'ratio': 0,
                    'rateA': 9999,
                    'area': sreact.get('area', 1),
                    'zone': sreact.get('zone', 1),
                    'owner': sreact.get('owner', 1)
                })
        
        # Add 3-Winding Transformers (Star Equivalent Model connected to Internal Dummy Bus starting at 100000000)
        three_w_xfmrs = input_data.get('three_winding_transformers') or input_data.get('three_winding_xfmrs') or {}
        for tw_num, twx in three_w_xfmrs.items():
            if twx.get('status', 1) == 1:
                # Internal dummy bus number starting from 100000000
                dummy_bus_num = 100000000 + int(tw_num)
                
                # Base kV for dummy bus from HV bus
                hv_bus_id = twx.get('hv_bus')
                hv_base_kV = 132.0
                if hv_bus_id in bus_data:
                    hv_base_kV = bus_data[hv_bus_id].get('base_kV', 132.0)
                
                # Add internal dummy bus to bus_data (Type 1 PQ)
                bus_data[dummy_bus_num] = {
                    'V_init': 1.0,
                    'angle_init': 0.0,
                    'base_kV': hv_base_kV,
                    'type': 1,
                    'name': f"Dummy_Bus_{dummy_bus_num}",
                    'shunt_G': 0.0,
                    'shunt_B': 0.0,
                    'area': twx.get('area', 1),
                    'zone': twx.get('zone', 1),
                    'owner': twx.get('owner', 1)
                }

                # Star equivalent impedances Z_H, Z_M, Z_L
                r_hm, x_hm = twx.get('r_hm', 0.0), twx.get('x_hm', 0.05)
                r_hl, x_hl = twx.get('r_hl', 0.0), twx.get('x_hl', 0.05)
                r_ml, x_ml = twx.get('r_ml', 0.0), twx.get('x_ml', 0.05)

                r_h = 0.5 * (r_hm + r_hl - r_ml)
                x_h = 0.5 * (x_hm + x_hl - x_ml)

                r_m = 0.5 * (r_hm + r_ml - r_hl)
                x_m = 0.5 * (x_hm + x_ml - x_hl)

                r_l = 0.5 * (r_hl + r_ml - r_hm)
                x_l = 0.5 * (x_hl + x_ml - x_hm)

                # Add 3 virtual 2-winding transformer branches connecting to dummy_bus_num
                branch_data.append({
                    'type': 'transformer',
                    'num': f"3WX_{tw_num}_HV",
                    'name': f"{twx.get('name', f'3WX_{tw_num}')}_HV",
                    'from_bus': twx['hv_bus'],
                    'to_bus': dummy_bus_num,
                    'r': r_h,
                    'x': x_h,
                    'b': 0,
                    'ratio': twx.get('tap_h', 1.0),
                    'rateA': twx.get('rate_h', 9999),
                    'min_tap': 0.9, 'max_tap': 1.1, 'step_size': 0.01,
                    'area': twx.get('area', 1), 'zone': twx.get('zone', 1), 'owner': twx.get('owner', 1)
                })

                branch_data.append({
                    'type': 'transformer',
                    'num': f"3WX_{tw_num}_MV",
                    'name': f"{twx.get('name', f'3WX_{tw_num}')}_MV",
                    'from_bus': twx['mv_bus'],
                    'to_bus': dummy_bus_num,
                    'r': r_m,
                    'x': x_m,
                    'b': 0,
                    'ratio': twx.get('tap_m', 1.0),
                    'rateA': twx.get('rate_m', 9999),
                    'min_tap': 0.9, 'max_tap': 1.1, 'step_size': 0.01,
                    'area': twx.get('area', 1), 'zone': twx.get('zone', 1), 'owner': twx.get('owner', 1)
                })

                branch_data.append({
                    'type': 'transformer',
                    'num': f"3WX_{tw_num}_LV",
                    'name': f"{twx.get('name', f'3WX_{tw_num}')}_LV",
                    'from_bus': twx['lv_bus'],
                    'to_bus': dummy_bus_num,
                    'r': r_l,
                    'x': x_l,
                    'b': 0,
                    'ratio': twx.get('tap_l', 1.0),
                    'rateA': twx.get('rate_l', 9999),
                    'min_tap': 0.9, 'max_tap': 1.1, 'step_size': 0.01,
                    'area': twx.get('area', 1), 'zone': twx.get('zone', 1), 'owner': twx.get('owner', 1)
                })

        return bus_data, branch_data, input_data

        
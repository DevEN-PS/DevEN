# DevEN Path Bootstrapper
import sys
import os

try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

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
DevEN Chronological Time Series Power Flow Engine
Solves quasi-dynamic time-series power flow across arbitrary timelines (seconds to years),
with sequential warm-starting, 13 imputation methods, selective time steps, and divergence resilience.
"""

import math
import copy
import csv
import json
import argparse
import numpy as np
from datetime import datetime

try:
    from input_reader import InputReader
except ImportError:
    from utils.input_reader import InputReader

try:
    from power_flow_engine import PowerFlowEngine
except ImportError:
    from engines.power_flow_engine import PowerFlowEngine

try:
    from report_writer import ReportWriter
except ImportError:
    from utils.report_writer import ReportWriter

try:
    from time_series_imputer import TimeSeriesImputer, generate_time_points, get_preset_profile
except ImportError:
    from utils.time_series_imputer import TimeSeriesImputer, generate_time_points, get_preset_profile

try:
    from time_series_universal_csv import parse_universal_csv
except ImportError:
    from utils.time_series_universal_csv import parse_universal_csv

try:
    from three_phase_pf_engine import ThreePhasePowerFlowEngine
except ImportError:
    from engines.three_phase_pf_engine import ThreePhasePowerFlowEngine


class TimeSeriesEngine:
    def __init__(self, input_file, time_settings=None, solver_settings=None):
        self.input_file = os.path.abspath(input_file)
        self.case_name = os.path.splitext(os.path.basename(self.input_file))[0]
        
        self.time_settings = time_settings or {}
        self.solver_settings = solver_settings or {}
        self.output_folder = self.solver_settings.get('output_folder', '')
        self.csv_file = self.time_settings.get('csv_file', '')
        
        if not self.output_folder:
            self.output_folder = os.path.join(os.path.dirname(self.input_file), f"{self.case_name}_TIMESERIES")
        os.makedirs(self.output_folder, exist_ok=True)

        self.full_data = None
        self.baseMVA = 100.0

        # Time settings
        self.duration = float(self.time_settings.get('duration', 24.0))
        self.dur_unit = self.time_settings.get('duration_unit', 'Hours')
        self.step_size = float(self.time_settings.get('step_size', 1.0))
        self.step_unit = self.time_settings.get('step_unit', 'Hours')
        self.start_time = self.time_settings.get('start_time', '2026-01-01 00:00:00')
        self.imputation_method = self.time_settings.get('imputation_method', 'linear')
        self.selected_steps = self.time_settings.get('selected_steps', None) # None = all steps
        self.continue_on_divergence = bool(self.time_settings.get('continue_on_divergence', True))
        self.auto_retry_flat_start = bool(self.time_settings.get('auto_retry_flat_start', True))

        # Solver options
        self.engine_choice = self.solver_settings.get('engine', 'andes_nr')
        self.tol = float(self.solver_settings.get('tol', 0.000001))
        self.max_iter = int(self.solver_settings.get('max_iter', 20))
        self.v_init_base = self.solver_settings.get('v_init_base', 'flat') # 'flat' or 'initial'
        self.v_init_step = self.solver_settings.get('v_init_step', 'warm') # 'warm', 'flat', 'initial'
        self.ignore_q_tol = bool(self.solver_settings.get('ignore_q_tol', False))
        self.industry_std_pv = bool(self.solver_settings.get('industry_std_pv', True))
        self.ignore_islands = bool(self.solver_settings.get('ignore_islands', True))
        fb_in = self.solver_settings.get('fallback_opts', {}) or {}
        self.fallback_opts = {
            'enable_fallback_pipeline': bool(fb_in.get('enable_fallback_pipeline', True)),
            'stage_max_iter': min(self.max_iter, int(fb_in.get('stage_max_iter', self.max_iter))),
            'use_dc_angle_init': bool(fb_in.get('use_dc_angle_init', True)),
            'use_postponed_q_limits': bool(fb_in.get('use_postponed_q_limits', True)),
            'use_step_damping': bool(fb_in.get('use_step_damping', True)),
            'use_levenberg_marquardt': bool(fb_in.get('use_levenberg_marquardt', True)),
            'use_homotopy_ramping': bool(fb_in.get('use_homotopy_ramping', True)),
            'use_diagnostics': bool(fb_in.get('use_diagnostics', True))
        }

        # 3-Phase Unbalanced Engine specific options
        eng_low = str(self.engine_choice).lower().strip()
        self.is_3phase = (
            eng_low in ('3p_nr', '3p_fbs', 'deven_3p_nr', 'deven_3p_fbs', 'nr_3p', 'fbs_3p')
            or '3p' in eng_low
            or '3-phase' in eng_low
            or 'three_phase' in eng_low
        )
        self.three_phase_method = 'fbs_3p' if ('fbs' in eng_low) else 'nr_3p'
        self.load_dist_rule = self.solver_settings.get('load_dist', self.solver_settings.get('load_dist_rule', 'equal'))
        raw_lp = self.solver_settings.get('load_pct', self.solver_settings.get('load_custom_pct', (33.333, 33.333, 33.334)))
        if isinstance(raw_lp, str):
            try: raw_lp = tuple(float(x.strip()) for x in raw_lp.split(','))
            except Exception: raw_lp = (33.333, 33.333, 33.334)
        self.load_custom_pct = tuple(raw_lp)

        self.gen_dist_rule = self.solver_settings.get('gen_dist', self.solver_settings.get('gen_dist_rule', 'equal'))
        raw_gp = self.solver_settings.get('gen_pct', self.solver_settings.get('gen_custom_pct', (33.333, 33.333, 33.334)))
        if isinstance(raw_gp, str):
            try: raw_gp = tuple(float(x.strip()) for x in raw_gp.split(','))
            except Exception: raw_gp = (33.333, 33.333, 33.334)
        self.gen_custom_pct = tuple(raw_gp)

        self.enforce_q_limits = bool(self.solver_settings.get('enforce_q_limits', self.solver_settings.get('enforce_q', True)))

        # Report generation controls (Default: False unless requested)
        self.generate_reports = bool(self.solver_settings.get('generate_reports', False))
        self.csv_report = bool(self.solver_settings.get('csv_report', False))
        self.py_report = bool(self.solver_settings.get('py_report', False))
        self.txt_report = bool(self.solver_settings.get('txt_report', False))
        rep_spec = self.solver_settings.get('reports')
        if rep_spec:
            if isinstance(rep_spec, str):
                rep_list = [r.strip().lower() for r in rep_spec.split(',')]
            else:
                rep_list = [str(r).strip().lower() for r in rep_spec]
            if 'all' in rep_list:
                self.csv_report = self.py_report = self.txt_report = True
            elif 'none' in rep_list:
                self.csv_report = self.py_report = self.txt_report = False
            else:
                if 'csv' in rep_list: self.csv_report = True
                if any(x in rep_list for x in ('py', 'python')): self.py_report = True
                if any(x in rep_list for x in ('txt', 'invout', 'summary')): self.txt_report = True
        elif self.generate_reports and not (self.csv_report or self.py_report or self.txt_report):
            self.csv_report = self.py_report = self.txt_report = True

        self.to_terminal = bool(self.solver_settings.get('to_terminal', False))
        self.print_report = self.solver_settings.get('print_report', None)

        # Timeline
        self.time_points = generate_time_points(
            duration=self.duration,
            duration_unit=self.dur_unit,
            step_size=self.step_size,
            step_unit=self.step_unit,
            start_time=self.start_time
        )
        self.total_steps = len(self.time_points)

    def load_system(self):
        """Read system case database"""
        self.full_data = InputReader.read_from_python(self.input_file)
        if not self.full_data:
            return False
        self.baseMVA = self.full_data.get('base_mva', 100.0)
        return True

    def build_time_series_profiles(self):
        """
        Extract or impute full chronological arrays of length total_steps for all dynamic components.
        Returns: dict of profiles keyed by element type and ID.
        """
        # If external universal CSV was linked, parse it first
        csv_profiles = {}
        if self.csv_file and os.path.exists(self.csv_file):
            print(f"📥 Loading Universal Time Series CSV: {self.csv_file}")
            try:
                csv_profiles, stats = parse_universal_csv(
                    self.csv_file,
                    total_steps=self.total_steps,
                    imputation_method=self.imputation_method,
                    known_elements=self.full_data
                )
                if stats.get('skipped_unmatched'):
                    print(f"⚠️ Warning: Skipped {len(stats['skipped_unmatched'])} CSV rows not present in case database:")
                    for sk in sorted(list(stats['skipped_unmatched']))[:5]:
                        print(f"   • {sk}")
                if stats.get('missing_database_elements'):
                    print(f"ℹ️ Note: {len(stats['missing_database_elements'])} database components not found in CSV (retaining static case defaults).")
            except Exception as e:
                print(f"⚠️ Warning: Could not parse CSV ({e}). Falling back to database case data.")

        profiles = {
            'loads': {},
            'generators': {},
            'capacitors': {},
            'reactors': {},
            'shunts': {}
        }

        # 1. Loads
        loads_dict = self.full_data.get('loads', {})
        for lid, load in loads_dict.items():
            base_p = float(load.get('P_demand', 0.0))
            base_q = float(load.get('Q_demand', 0.0))
            ts = load.get('time_series', {})
            
            p_curve = None
            q_curve = None
            if ts and isinstance(ts, dict):
                p_raw = ts.get('P')
                q_raw = ts.get('Q')
                mult_raw = ts.get('mult')
                if p_raw:
                    k_idx = [i for i, v in enumerate(p_raw) if v is not None and i < self.total_steps]
                    k_val = [p_raw[i] for i in k_idx]
                    p_curve = TimeSeriesImputer.impute_series(k_idx, k_val, self.total_steps, method=self.imputation_method, default_base_val=base_p)
                elif mult_raw:
                    k_idx = [i for i, v in enumerate(mult_raw) if v is not None and i < self.total_steps]
                    k_val = [mult_raw[i] for i in k_idx]
                    m_curve = TimeSeriesImputer.impute_series(k_idx, k_val, self.total_steps, method=self.imputation_method, default_base_val=100.0)
                    p_curve = [base_p * (m / 100.0) for m in m_curve]

                if q_raw:
                    k_idx = [i for i, v in enumerate(q_raw) if v is not None and i < self.total_steps]
                    k_val = [q_raw[i] for i in k_idx]
                    q_curve = TimeSeriesImputer.impute_series(k_idx, k_val, self.total_steps, method=self.imputation_method, default_base_val=base_q)

            if p_curve is None: p_curve = [base_p] * self.total_steps
            if q_curve is None: q_curve = [base_q] * self.total_steps
            profiles['loads'][lid] = {'P': p_curve, 'Q': q_curve}

        # 2. Generators
        gens_dict = self.full_data.get('generators', {})
        for gid, gen in gens_dict.items():
            base_p = float(gen.get('P_out', 0.0))
            base_q = float(gen.get('Q_out', 0.0))
            base_v = float(gen.get('V_set', 1.0))
            base_qmin = float(gen.get('Qmin', -999.0))
            base_qmax = float(gen.get('Qmax', 999.0))
            ts = gen.get('time_series', {})

            p_curve = None
            q_curve = None
            v_curve = None
            qmin_curve = None
            qmax_curve = None

            if ts and isinstance(ts, dict):
                for p_k, p_base, attr in (('P', base_p, 'p_curve'), ('Q', base_q, 'q_curve'),
                                          ('V_set', base_v, 'v_curve'), ('Qmin', base_qmin, 'qmin_curve'),
                                          ('Qmax', base_qmax, 'qmax_curve')):
                    raw = ts.get(p_k)
                    if raw:
                        k_idx = [i for i, v in enumerate(raw) if v is not None and i < self.total_steps]
                        k_val = [raw[i] for i in k_idx]
                        curve_res = TimeSeriesImputer.impute_series(k_idx, k_val, self.total_steps, method=self.imputation_method, default_base_val=p_base)
                        if attr == 'p_curve': p_curve = curve_res
                        elif attr == 'q_curve': q_curve = curve_res
                        elif attr == 'v_curve': v_curve = curve_res
                        elif attr == 'qmin_curve': qmin_curve = curve_res
                        elif attr == 'qmax_curve': qmax_curve = curve_res

            if p_curve is None: p_curve = [base_p] * self.total_steps
            if q_curve is None: q_curve = [base_q] * self.total_steps
            if v_curve is None: v_curve = [base_v] * self.total_steps
            if qmin_curve is None: qmin_curve = [base_qmin] * self.total_steps
            if qmax_curve is None: qmax_curve = [base_qmax] * self.total_steps

            profiles['generators'][gid] = {
                'P': p_curve, 'Q': q_curve, 'V_set': v_curve,
                'Qmin': qmin_curve, 'Qmax': qmax_curve
            }

        # 3. Shunts / Capacitors / Reactors
        for grp_name, f_key in (('capacitors', 'Q_cap'), ('reactors', 'Q_react'), ('shunts', 'Q_shunt')):
            el_dict = self.full_data.get(grp_name, {})
            for eid, el in el_dict.items():
                base_q = float(el.get(f_key, 0.0))
                ts = el.get('time_series', {})
                q_curve = None
                if ts and isinstance(ts, dict) and ts.get('Q'):
                    raw = ts['Q']
                    k_idx = [i for i, v in enumerate(raw) if v is not None and i < self.total_steps]
                    k_val = [raw[i] for i in k_idx]
                    q_curve = TimeSeriesImputer.impute_series(k_idx, k_val, self.total_steps, method=self.imputation_method, default_base_val=base_q)
                if q_curve is None: q_curve = [base_q] * self.total_steps
                profiles[grp_name][eid] = {'Q': q_curve}

        # Overlay external CSV profiles if provided
        if csv_profiles:
            for grp in ('loads', 'generators', 'capacitors', 'reactors', 'shunts'):
                for eid, p_map in csv_profiles.get(grp, {}).items():
                    if eid in profiles[grp]:
                        for param_k, c_vals in p_map.items():
                            if c_vals is not None:
                                profiles[grp][eid][param_k] = c_vals

        return profiles

    def run(self, progress_callback=None):
        """
        Execute chronological time-series simulation loop.
        """
        if not self.load_system():
            print("❌ Failed to load system database.")
            return None

        profiles = self.build_time_series_profiles()

        # Determine steps to execute
        if self.selected_steps and isinstance(self.selected_steps, (list, tuple, set)):
            steps_to_run = [i for i in self.selected_steps if 0 <= i < self.total_steps]
        else:
            steps_to_run = list(range(self.total_steps))

        print("\n" + "=" * 80)
        print("⚡ DevEN CHRONOLOGICAL TIME SERIES POWER FLOW ENGINE")
        print("=" * 80)
        print(f"📁 Case: {self.case_name}")
        print(f"⏱️ Timeline: {len(steps_to_run)}/{self.total_steps} Steps ({self.duration} {self.dur_unit} @ {self.step_size} {self.step_unit})")
        print(f"🧩 Imputation Method: {self.imputation_method.upper()}")
        print(f"⚙️ Engine: {self.engine_choice.upper()} | Tolerance: {self.tol} | Max Iter: {self.max_iter}")
        print(f"⚡ Warm-Starting: {'ENABLED' if self.v_init_step == 'warm' else 'DISABLED'}")
        print(f"🛡️ Divergence Recovery: {'CONTINUE (Seed with last converged)' if self.continue_on_divergence else 'STOP ON ERROR'}")
        print("=" * 80 + "\n")

        # Results structures
        chronological_results = []
        last_converged_v_mag = None
        last_converged_v_ang = None
        last_converged_v_abc = None

        total_gen_mwh = 0.0
        total_load_mwh = 0.0
        total_loss_mwh = 0.0
        step_hours = self.time_points[1]['time_hr'] - self.time_points[0]['time_hr'] if len(self.time_points) > 1 else 1.0

        for step_order, t_idx in enumerate(steps_to_run, 1):
            pt = self.time_points[t_idx]
            timestamp_str = pt['timestamp']
            time_lbl = pt['label']

            # Build case copy for this step
            step_full_data = copy.deepcopy(self.full_data)

            # Apply profile injections
            for lid, p_dict in profiles['loads'].items():
                if lid in step_full_data.get('loads', {}):
                    if p_dict.get('P') is not None:
                        step_full_data['loads'][lid]['P_demand'] = p_dict['P'][t_idx]
                    if p_dict.get('Q') is not None:
                        step_full_data['loads'][lid]['Q_demand'] = p_dict['Q'][t_idx]
                    if p_dict.get('Pa') is not None:
                        step_full_data['loads'][lid]['phase_mode'] = '3phase'
                        step_full_data['loads'][lid]['Pa'] = p_dict['Pa'][t_idx]
                        step_full_data['loads'][lid]['Pb'] = p_dict['Pb'][t_idx]
                        step_full_data['loads'][lid]['Pc'] = p_dict['Pc'][t_idx]
                        step_full_data['loads'][lid]['Qa'] = p_dict['Qa'][t_idx]
                        step_full_data['loads'][lid]['Qb'] = p_dict['Qb'][t_idx]
                        step_full_data['loads'][lid]['Qc'] = p_dict['Qc'][t_idx]

            for gid, p_dict in profiles['generators'].items():
                if gid in step_full_data.get('generators', {}):
                    if p_dict.get('P') is not None:
                        step_full_data['generators'][gid]['P_out'] = p_dict['P'][t_idx]
                    if p_dict.get('Q') is not None:
                        step_full_data['generators'][gid]['Q_out'] = p_dict['Q'][t_idx]
                    if p_dict.get('V_set') is not None:
                        step_full_data['generators'][gid]['V_set'] = p_dict['V_set'][t_idx]
                    if p_dict.get('Qmin') is not None:
                        step_full_data['generators'][gid]['Qmin'] = p_dict['Qmin'][t_idx]
                    if p_dict.get('Qmax') is not None:
                        step_full_data['generators'][gid]['Qmax'] = p_dict['Qmax'][t_idx]
                    if p_dict.get('Pa') is not None:
                        step_full_data['generators'][gid]['phase_mode'] = '3phase'
                        step_full_data['generators'][gid]['Pa'] = p_dict['Pa'][t_idx]
                        step_full_data['generators'][gid]['Pb'] = p_dict['Pb'][t_idx]
                        step_full_data['generators'][gid]['Pc'] = p_dict['Pc'][t_idx]
                        step_full_data['generators'][gid]['Qa'] = p_dict['Qa'][t_idx]
                        step_full_data['generators'][gid]['Qb'] = p_dict['Qb'][t_idx]
                        step_full_data['generators'][gid]['Qc'] = p_dict['Qc'][t_idx]
                    if p_dict.get('Va_set') is not None:
                        step_full_data['generators'][gid]['Va_set'] = p_dict['Va_set'][t_idx]
                        step_full_data['generators'][gid]['Vb_set'] = p_dict['Vb_set'][t_idx]
                        step_full_data['generators'][gid]['Vc_set'] = p_dict['Vc_set'][t_idx]

            for grp_name, f_key in (('capacitors', 'Q_cap'), ('reactors', 'Q_react'), ('shunts', 'Q_shunt')):
                for eid, p_dict in profiles[grp_name].items():
                    if eid in step_full_data.get(grp_name, {}):
                        if p_dict.get('Q') is not None:
                            step_full_data[grp_name][eid][f_key] = p_dict['Q'][t_idx]

            # ── BRANCH A: 3-PHASE UNBALANCED ENGINE ──
            if self.is_3phase:
                buses_in = step_full_data.get('buses', {})
                lines_in = step_full_data.get('lines', {})
                xfmrs_in = step_full_data.get('transformers', {})
                branches_in = list(lines_in.values()) + list(xfmrs_in.values())
                gens_in = step_full_data.get('generators', {})
                loads_in = step_full_data.get('loads', {})
                caps_in = step_full_data.get('capacitors', {})
                reacts_in = step_full_data.get('reactors', {})
                shunts_in = step_full_data.get('shunts', {})

                tp_settings = {
                    'method': self.three_phase_method,
                    'load_dist_rule': self.load_dist_rule,
                    'load_custom_pct': self.load_custom_pct,
                    'gen_dist_rule': self.gen_dist_rule,
                    'gen_custom_pct': self.gen_custom_pct,
                    'tol': self.tol,
                    'max_iter': self.max_iter,
                    'enforce_q_limits': self.enforce_q_limits
                }

                engine_3p = ThreePhasePowerFlowEngine(base_mva=self.baseMVA)
                engine_3p.initialize(
                    buses_in, branches_in, gens_in, loads_in,
                    settings=tp_settings,
                    capacitors=caps_in,
                    reactors=reacts_in,
                    shunts=shunts_in
                )

                # Warm start V_abc
                if self.v_init_step == 'warm' and last_converged_v_abc is not None:
                    for bid, idx in engine_3p.bus_idx.items():
                        if bid in last_converged_v_abc:
                            engine_3p.V_abc[idx] = list(last_converged_v_abc[bid])

                converged = engine_3p.solve()

                if not converged and self.auto_retry_flat_start and self.v_init_step == 'warm':
                    print(f"  ⚠️ Step {t_idx} diverged with warm start. Retrying with balanced flat start...")
                    engine_3p = ThreePhasePowerFlowEngine(base_mva=self.baseMVA)
                    engine_3p.initialize(
                        buses_in, branches_in, gens_in, loads_in,
                        settings=tp_settings,
                        capacitors=caps_in,
                        reactors=reacts_in,
                        shunts=shunts_in
                    )
                    converged = engine_3p.solve()

                step_iters = engine_3p.iterations

                step_summary = {
                    'step_index': t_idx,
                    'timestamp': timestamp_str,
                    'time_label': time_lbl,
                    'converged': converged,
                    'iterations': step_iters,
                    'is_3phase': True,
                    'total_p_gen_mw': 0.0,
                    'total_q_gen_mvar': 0.0,
                    'total_p_load_mw': 0.0,
                    'total_q_load_mvar': 0.0,
                    'total_p_loss_mw': 0.0,
                    'total_q_loss_mvar': 0.0,
                    'v_min_pu': 1.0,
                    'v_min_bus': 0,
                    'v_max_pu': 1.0,
                    'v_max_bus': 0,
                    'max_vuf_pct': 0.0,
                    'max_vuf_bus': 0,
                    'max_branch_loading_pct': 0.0,
                    'max_loading_branch': 'N/A',
                    'bus_results': {},
                    'branch_results': {},
                    'gen_results': {},
                    'load_results': {}
                }

                if converged:
                    last_converged_v_abc = {
                        bid: list(engine_3p.V_abc[engine_3p.bus_idx[bid]])
                        for bid in engine_3p.bus_idx
                    }

                    min_v = 999.0; min_v_b = 0
                    max_v = -999.0; max_v_b = 0
                    max_vuf = 0.0; max_vuf_b = 0

                    for bid, b_res in engine_3p.results_buses.items():
                        vm = float(b_res.get('V1_mag', 1.0))
                        va = float(b_res.get('anga', 0.0))
                        vuf = float(b_res.get('VUF', 0.0))
                        step_summary['bus_results'][bid] = {
                            'V_mag': vm,
                            'V_ang_deg': va,
                            'Va': float(b_res.get('Va_mag', 1.0)),
                            'Vb': float(b_res.get('Vb_mag', 1.0)),
                            'Vc': float(b_res.get('Vc_mag', 1.0)),
                            'anga': float(b_res.get('anga', 0.0)),
                            'angb': float(b_res.get('angb', -120.0)),
                            'angc': float(b_res.get('angc', 120.0)),
                            'V0': float(b_res.get('V0_mag', 0.0)),
                            'V1': vm,
                            'V2': float(b_res.get('V2_mag', 0.0)),
                            'VUF': vuf,
                            'PVUR': float(b_res.get('PVUR', 0.0))
                        }
                        if vm < min_v: min_v = vm; min_v_b = bid
                        if vm > max_v: max_v = vm; max_v_b = bid
                        if vuf > max_vuf: max_vuf = vuf; max_vuf_b = bid

                    step_summary['v_min_pu'] = min_v if min_v != 999.0 else 1.0
                    step_summary['v_min_bus'] = min_v_b
                    step_summary['v_max_pu'] = max_v if max_v != -999.0 else 1.0
                    step_summary['v_max_bus'] = max_v_b
                    step_summary['max_vuf_pct'] = max_vuf
                    step_summary['max_vuf_bus'] = max_vuf_b

                    tot_p_gen = 0.0; tot_q_gen = 0.0
                    for gid, g_dict in engine_3p.results_gens.items():
                        pa = float(g_dict.get('Pa', 0.0))
                        pb = float(g_dict.get('Pb', 0.0))
                        pc = float(g_dict.get('Pc', 0.0))
                        qa = float(g_dict.get('Qa', 0.0))
                        qb = float(g_dict.get('Qb', 0.0))
                        qc = float(g_dict.get('Qc', 0.0))
                        ptot = float(g_dict.get('P_tot', pa + pb + pc))
                        qtot = float(g_dict.get('Q_tot', qa + qb + qc))
                        step_summary['gen_results'][gid] = {
                            'P_out_MW': ptot, 'Q_out_Mvar': qtot,
                            'Pa': pa, 'Pb': pb, 'Pc': pc,
                            'Qa': qa, 'Qb': qb, 'Qc': qc
                        }
                        tot_p_gen += ptot
                        tot_q_gen += qtot

                    tot_p_load = 0.0; tot_q_load = 0.0
                    for lid, l_dict in engine_3p.results_loads.items():
                        pa = float(l_dict.get('Pa', 0.0))
                        pb = float(l_dict.get('Pb', 0.0))
                        pc = float(l_dict.get('Pc', 0.0))
                        qa = float(l_dict.get('Qa', 0.0))
                        qb = float(l_dict.get('Qb', 0.0))
                        qc = float(l_dict.get('Qc', 0.0))
                        ptot = float(l_dict.get('P_tot', pa + pb + pc))
                        qtot = float(l_dict.get('Q_tot', qa + qb + qc))
                        step_summary['load_results'][lid] = {
                            'P_supplied_MW': ptot, 'Q_supplied_Mvar': qtot,
                            'Pa': pa, 'Pb': pb, 'Pc': pc,
                            'Qa': qa, 'Qb': qb, 'Qc': qc
                        }
                        tot_p_load += ptot
                        tot_q_load += qtot

                    tot_p_loss = 0.0; tot_q_loss = 0.0
                    max_loading = 0.0; max_br_name = 'N/A'
                    for br_res in engine_3p.results_branches:
                        b_type = br_res.get('type', 'line')
                        bid = br_res.get('id', '')
                        key_prefix = "Line" if b_type == 'line' else "Xfmr"
                        key = f"{key_prefix}_{bid}"

                        pa = float(br_res.get('Pa_fwd', 0.0))
                        pb = float(br_res.get('Pb_fwd', 0.0))
                        pc = float(br_res.get('Pc_fwd', 0.0))
                        qa = float(br_res.get('Qa_fwd', 0.0))
                        qb = float(br_res.get('Qb_fwd', 0.0))
                        qc = float(br_res.get('Qc_fwd', 0.0))
                        pf = pa + pb + pc
                        qf = qa + qb + qc
                        sf = math.sqrt(pf**2 + qf**2)
                        loss = float(br_res.get('loss_P_total', 0.0))
                        loading = float(br_res.get('loading_pct', 0.0))
                        in_a = float(br_res.get('In_mag', 0.0))

                        tot_p_loss += loss
                        if loading > max_loading:
                            max_loading = loading
                            max_br_name = f"{key_prefix} {bid}"

                        step_summary['branch_results'][key] = {
                            'P_MW': pf, 'Q_MVar': qf, 'S_MVA': sf,
                            'Pa': pa, 'Pb': pb, 'Pc': pc,
                            'Qa': qa, 'Qb': qb, 'Qc': qc,
                            'In': in_a, 'Loss_MW': loss, 'Loading_Pct': loading
                        }

                    step_summary.update({
                        'total_p_gen_mw': tot_p_gen,
                        'total_q_gen_mvar': tot_q_gen,
                        'total_p_load_mw': tot_p_load,
                        'total_q_load_mvar': tot_q_load,
                        'total_p_loss_mw': tot_p_loss,
                        'total_q_loss_mvar': tot_q_loss,
                        'max_branch_loading_pct': max_loading,
                        'max_loading_branch': max_br_name
                    })

                    total_gen_mwh += tot_p_gen * step_hours
                    total_load_mwh += tot_p_load * step_hours
                    total_loss_mwh += tot_p_loss * step_hours

                    status_icon = "✅"
                    stat_str = f"P_Load: {tot_p_load:>7.1f} MW | Losses: {tot_p_loss:>6.2f} MW | V_min: {min_v:>5.3f} (Bus {min_v_b}) | Max VUF: {max_vuf:>5.2f}% (Bus {max_vuf_b}) | Max Load: {max_loading:>5.1f}%"
                else:
                    status_icon = "❌"
                    stat_str = "DIVERGED"

            else:
                # ── BRANCH B: SINGLE-PHASE ENGINE (ANDES / DevEN Sparse NR) ──
                bus_data_engine, branch_data_engine, full_data_engine = InputReader.convert_to_engine_format(step_full_data)

                # Determine voltage init mode for this step
                if step_order == 1 or last_converged_v_mag is None:
                    v_init_mode = 'initial' if 'initial' in str(self.v_init_base).lower() else 'flat'
                else:
                    v_init_mode = 'warm' if self.v_init_step == 'warm' else ('initial' if 'initial' in str(self.v_init_step).lower() else 'flat')

                engine = PowerFlowEngine(baseMVA=self.baseMVA)
                engine.initialize(
                    bus_data_engine, branch_data_engine, full_data=full_data_engine,
                    solver_method=self.engine_choice, tol=self.tol, max_iter=self.max_iter,
                    ignore_q_tol=self.ignore_q_tol, ignore_islands=self.ignore_islands,
                    industry_std_pv=self.industry_std_pv, v_init_mode=v_init_mode,
                    fallback_opts=self.fallback_opts
                )

                # Apply warm start if available
                if v_init_mode == 'warm' and last_converged_v_mag is not None:
                    engine.V_mag = np.array(last_converged_v_mag, copy=True)
                    engine.V_angle = np.array(last_converged_v_ang, copy=True)

                # Solve step
                samples, valid_count = engine.run_batch(n_samples=1, variation_strength=0.0)
                converged = (valid_count > 0 and len(samples) > 0 and bool(samples[0].get('converged', False)))

                # Auto-retry on divergence with flat start if requested
                if not converged and self.auto_retry_flat_start and v_init_mode == 'warm':
                    print(f"  ⚠️ Step {t_idx} diverged with warm start. Retrying with Flat Start + Recovery Pipeline...")
                    engine.initialize(
                        bus_data_engine, branch_data_engine, full_data=full_data_engine,
                        solver_method=self.engine_choice, tol=self.tol, max_iter=self.max_iter,
                        ignore_q_tol=self.ignore_q_tol, ignore_islands=self.ignore_islands,
                        industry_std_pv=self.industry_std_pv, v_init_mode='flat',
                        fallback_opts=self.fallback_opts
                    )
                    samples, valid_count = engine.run_batch(n_samples=1, variation_strength=0.0)
                    converged = (valid_count > 0 and len(samples) > 0 and bool(samples[0].get('converged', False)))

                sol = samples[0] if (converged and samples) else {}
                step_iters = sol.get('iterations', getattr(engine, 'iterations_count', 0))

                step_summary = {
                    'step_index': t_idx,
                    'timestamp': timestamp_str,
                    'time_label': time_lbl,
                    'converged': converged,
                    'iterations': step_iters,
                    'is_3phase': False,
                    'total_p_gen_mw': 0.0,
                    'total_q_gen_mvar': 0.0,
                    'total_p_load_mw': 0.0,
                    'total_q_load_mvar': 0.0,
                    'total_p_loss_mw': 0.0,
                    'total_q_loss_mvar': 0.0,
                    'v_min_pu': 1.0,
                    'v_min_bus': 0,
                    'v_max_pu': 1.0,
                    'v_max_bus': 0,
                    'max_branch_loading_pct': 0.0,
                    'max_loading_branch': 'N/A',
                    'bus_results': {},
                    'branch_results': {}
                }

                if converged:
                    sol = samples[0]
                    last_converged_v_mag = sol.get('V_mag')
                    last_converged_v_ang = sol.get('V_angle')

                # Use ReportWriter for 100% precision matching standard LFA calculations
                try:
                    from utils.report_writer import ReportWriter
                except ImportError:
                    from report_writer import ReportWriter

                rw = ReportWriter(engine, step_full_data, samples, 0.0)

                # 1. Bus voltages & angles
                bus_ids_sorted = sorted(step_full_data.get('buses', {}).keys(), key=lambda x: int(x) if str(x).isdigit() else str(x))
                min_v = 999.0; min_v_b = 0
                max_v = -999.0; max_v_b = 0
                for b_num in bus_ids_sorted:
                    idx = engine.bus_index_map.get(b_num, 0)
                    vm = rw._safe_get_v(idx) if hasattr(rw, '_safe_get_v') else float(rw.avg_V[idx])
                    va = rw._safe_get_va(idx) if hasattr(rw, '_safe_get_va') else float(rw.avg_Va[idx])
                    step_summary['bus_results'][b_num] = {'V_mag': vm, 'V_ang_deg': va}
                    if vm < min_v: min_v = vm; min_v_b = b_num
                    if vm > max_v: max_v = vm; max_v_b = b_num

                step_summary['v_min_pu'] = min_v if min_v != 999.0 else 1.0
                step_summary['v_min_bus'] = min_v_b
                step_summary['v_max_pu'] = max_v if max_v != -999.0 else 1.0
                step_summary['v_max_bus'] = max_v_b

                # 2. Generator outputs
                gen_res = {}
                tot_p_gen = 0.0
                tot_q_gen = 0.0
                for gid, gen in step_full_data.get('generators', {}).items():
                    op, oq = rw.get_generator_outputs(gid, gen)
                    gen_res[gid] = {'P_out_MW': op, 'Q_out_Mvar': oq}
                    if gen.get('status', 1) == 1:
                        tot_p_gen += op
                        tot_q_gen += oq
                step_summary['gen_results'] = gen_res

                # 3. Load outputs
                load_res = {}
                tot_p_load = 0.0
                tot_q_load = 0.0
                for lid, load in step_full_data.get('loads', {}).items():
                    st_ld = load.get('status', 1)
                    pd = float(load.get('P_demand', 0.0))
                    qd = float(load.get('Q_demand', 0.0))
                    load_res[lid] = {
                        'P_supplied_MW': pd if st_ld == 1 else 0.0,
                        'Q_supplied_Mvar': qd if st_ld == 1 else 0.0
                    }
                    if st_ld == 1:
                        tot_p_load += pd
                        tot_q_load += qd
                step_summary['load_results'] = load_res

                # 4. Branch flows (Lines & Transformers)
                tot_p_loss = 0.0
                tot_q_loss = 0.0
                max_loading = 0.0
                max_br_name = 'N/A'

                lines_dict = step_full_data.get('lines', {})
                for lid, line in lines_dict.items():
                    br_st = rw._get_line_stats(lid, line)
                    pf = float(br_st.get('avg_P_fwd', 0.0))
                    qf = float(br_st.get('avg_Q_fwd', 0.0))
                    pr = float(br_st.get('avg_P_rev', 0.0))
                    qr = float(br_st.get('avg_Q_rev', 0.0))
                    sf = math.sqrt(pf**2 + qf**2)
                    sr = math.sqrt(pr**2 + qr**2)
                    loss = float(br_st.get('avg_loss', 0.0))
                    loading = float(br_st.get('avg_loading', 0.0))

                    tot_p_loss += loss
                    if loading > max_loading:
                        max_loading = loading
                        max_br_name = f"Line {lid} ({line.get('name', '')})"

                    step_summary['branch_results'][f"Line_{lid}"] = {
                        'P_MW': pf, 'Q_MVar': qf, 'S_MVA': sf,
                        'P_rev_MW': pr, 'Q_rev_Mvar': qr, 'S_rev_MVA': sr,
                        'Loss_MW': loss, 'Loading_Pct': loading
                    }

                xfmrs_dict = step_full_data.get('transformers', {})
                for xid, xfmr in xfmrs_dict.items():
                    xf_st = rw._get_xfmr_stats(xid, xfmr)
                    pf = float(xf_st.get('avg_P_fwd', 0.0))
                    qf = float(xf_st.get('avg_Q_fwd', 0.0))
                    pr = float(xf_st.get('avg_P_rev', 0.0))
                    qr = float(xf_st.get('avg_Q_rev', 0.0))
                    sf = math.sqrt(pf**2 + qf**2)
                    sr = math.sqrt(pr**2 + qr**2)
                    loss = float(xf_st.get('avg_loss', 0.0))
                    loading = float(xf_st.get('avg_loading', 0.0))
                    tap = float(xf_st.get('avg_tap', 1.0))

                    tot_p_loss += loss
                    if loading > max_loading:
                        max_loading = loading
                        max_br_name = f"Xfmr {xid} ({xfmr.get('name', '')})"

                    step_summary['branch_results'][f"Xfmr_{xid}"] = {
                        'P_MW': pf, 'Q_MVar': qf, 'S_MVA': sf,
                        'P_rev_MW': pr, 'Q_rev_Mvar': qr, 'S_rev_MVA': sr,
                        'Loss_MW': loss, 'Loading_Pct': loading, 'tap_ratio': tap
                    }

                step_summary.update({
                    'total_p_gen_mw': tot_p_gen,
                    'total_q_gen_mvar': tot_q_gen,
                    'total_p_load_mw': tot_p_load,
                    'total_q_load_mvar': tot_q_load,
                    'total_p_loss_mw': tot_p_loss,
                    'total_q_loss_mvar': tot_q_loss,
                    'max_branch_loading_pct': max_loading,
                    'max_loading_branch': max_br_name
                })

                if converged:
                    total_gen_mwh += tot_p_gen * step_hours
                    total_load_mwh += tot_p_load * step_hours
                    total_loss_mwh += tot_p_loss * step_hours
                    status_icon = "✅"
                    stat_str = f"P_Load: {tot_p_load:>7.1f} MW | Losses: {tot_p_loss:>6.2f} MW | V_min: {min_v:>5.3f} (Bus {min_v_b}) | Max Load: {max_loading:>5.1f}%"
                else:
                    status_icon = "❌"
                    stat_str = "DIVERGED"

            chronological_results.append(step_summary)

            print(f"[{step_order:>3}/{len(steps_to_run)}] {timestamp_str} ({time_lbl}): {status_icon} {stat_str}")

            if progress_callback:
                progress_callback(step_order, len(steps_to_run), step_summary)

            if not converged and not self.continue_on_divergence:
                print("\n🛑 Time Series Simulation halted due to divergence at step " + str(t_idx))
                break

        # Generate Consolidated Time-Series Reports
        generated_reports = self._export_reports(chronological_results, total_gen_mwh, total_load_mwh, total_loss_mwh)

        print("\n" + "=" * 80)
        print(" TIME SERIES POWER FLOW ANALYSIS COMPLETE!")
        print("=" * 80)
        if generated_reports:
            print(f"📁 Reports saved in: {self.output_folder}")
            for rk, rp in generated_reports.items():
                print(f"   • {rk:<28s}: {os.path.basename(rp)}")
        else:
            print("   • (No report files selected for disk generation)")
        print("=" * 80 + "\n")

        # Terminal report diversion if requested
        if self.to_terminal or self.print_report:
            print("\n" + "=" * 90)
            print("📺 TIME SERIES TERMINAL SUMMARY:")
            print("=" * 90)
            print(f"  Simulation Steps Solved : {len(chronological_results)}/{len(self.time_points)}")
            print(f"  Total Energy Generation : {total_gen_mwh:.4f} MWh")
            print(f"  Total Energy Demand     : {total_load_mwh:.4f} MWh")
            print(f"  Total Energy Losses     : {total_loss_mwh:.4f} MWh")
            print("-" * 90)
            print(f"{'Step':<5} | {'Timestamp':<19} | {'Gen (MW)':<11} | {'Load (MW)':<11} | {'Loss (MW)':<11} | {'Max Load %':<11} | {'Status'}")
            print("-" * 90)
            for r in chronological_results[:24]:
                conv_str = "CONV" if r.get('converged', True) else "DIV"
                p_gen = r.get('P_gen_total', 0.0)
                p_load = r.get('P_load_total', 0.0)
                p_loss = r.get('P_loss_total', 0.0)
                m_load = r.get('max_line_loading_pct', 0.0)
                print(f"{r['step_index']:<5} | {str(r['timestamp'])[:19]:<19} | {p_gen:<11.3f} | {p_load:<11.3f} | {p_loss:<11.3f} | {m_load:<11.2f} | {conv_str}")
            if len(chronological_results) > 24:
                print(f"  ... and {len(chronological_results) - 24} more chronological steps.")
            print("=" * 90 + "\n")

        return {
            'results': chronological_results,
            'output_folder': self.output_folder,
            'reports': generated_reports,
            'total_gen_mwh': total_gen_mwh,
            'total_load_mwh': total_load_mwh,
            'total_loss_mwh': total_loss_mwh,
        }

    def _export_reports(self, results, total_gen_mwh, total_load_mwh, total_loss_mwh):
        if not results:
            return {}

        generated = {}
        if not (self.csv_report or self.py_report or self.txt_report):
            return generated

        os.makedirs(self.output_folder, exist_ok=True)

        if self.csv_report:
            # 1. Bus Voltages Matrix CSV (Positive Sequence / Single Phase)
            bus_csv_path = os.path.join(self.output_folder, f"{self.case_name}_TIMESERIES_BUS_VOLTAGES.csv")
            bus_ids = sorted(self.full_data.get('buses', {}).keys(), key=lambda x: int(x) if str(x).isdigit() else str(x))
            with open(bus_csv_path, "w", newline="", encoding="utf-8") as fp:
                writer = csv.writer(fp)
                hdr = ["Step", "Timestamp", "Time_Label"]
                for bid in bus_ids:
                    hdr.extend([f"Bus_{bid}_V_pu", f"Bus_{bid}_Ang_deg"])
                writer.writerow(hdr)

                for r in results:
                    row = [r['step_index'], r['timestamp'], r['time_label']]
                    for bid in bus_ids:
                        b_res = r['bus_results'].get(bid, {})
                        row.extend([f"{b_res.get('V_mag', 1.0):.4f}", f"{b_res.get('V_ang_deg', 0.0):.2f}"])
                    writer.writerow(row)
            generated['bus_voltages_csv'] = bus_csv_path

            # 2. Branch Flows Matrix CSV (Lines and Transformers Total P, Q, Loss, Loading)
            branch_csv_path = os.path.join(self.output_folder, f"{self.case_name}_TIMESERIES_BRANCH_FLOWS.csv")
            line_ids = sorted(self.full_data.get('lines', {}).keys(), key=lambda x: int(x) if str(x).isdigit() else str(x))
            xfmr_ids = sorted(self.full_data.get('transformers', {}).keys(), key=lambda x: int(x) if str(x).isdigit() else str(x))
            with open(branch_csv_path, "w", newline="", encoding="utf-8") as fp:
                writer = csv.writer(fp)
                hdr = ["Step", "Timestamp", "Time_Label"]
                for lid in line_ids:
                    hdr.extend([f"Line_{lid}_P_MW", f"Line_{lid}_Q_MVar", f"Line_{lid}_Loss_MW", f"Line_{lid}_Loading_Pct"])
                for xid in xfmr_ids:
                    hdr.extend([f"Xfmr_{xid}_P_MW", f"Xfmr_{xid}_Q_MVar", f"Xfmr_{xid}_Loss_MW", f"Xfmr_{xid}_Loading_Pct"])
                writer.writerow(hdr)

                for r in results:
                    row = [r['step_index'], r['timestamp'], r['time_label']]
                    for lid in line_ids:
                        br_res = r['branch_results'].get(f"Line_{lid}", {})
                        row.extend([
                            f"{br_res.get('P_MW', 0.0):.3f}",
                            f"{br_res.get('Q_MVar', 0.0):.3f}",
                            f"{br_res.get('Loss_MW', 0.0):.4f}",
                            f"{br_res.get('Loading_Pct', 0.0):.2f}"
                        ])
                    for xid in xfmr_ids:
                        br_res = r['branch_results'].get(f"Xfmr_{xid}", {})
                        row.extend([
                            f"{br_res.get('P_MW', 0.0):.3f}",
                            f"{br_res.get('Q_MVar', 0.0):.3f}",
                            f"{br_res.get('Loss_MW', 0.0):.4f}",
                            f"{br_res.get('Loading_Pct', 0.0):.2f}"
                        ])
                    writer.writerow(row)
            generated['branch_flows_csv'] = branch_csv_path

            # 3. If 3-Phase Engine was run, Export Dedicated 3-Phase Trajectory CSVs
            if self.is_3phase:
                tp_bus_csv = os.path.join(self.output_folder, f"{self.case_name}_TIMESERIES_3PHASE_BUS_VOLTAGES.csv")
                with open(tp_bus_csv, "w", newline="", encoding="utf-8") as fp:
                    writer = csv.writer(fp)
                    hdr = ["Step", "Timestamp", "Time_Label"]
                    for bid in bus_ids:
                        hdr.extend([
                            f"Bus_{bid}_Va_pu", f"Bus_{bid}_Vb_pu", f"Bus_{bid}_Vc_pu",
                            f"Bus_{bid}_AngA_deg", f"Bus_{bid}_AngB_deg", f"Bus_{bid}_AngC_deg",
                            f"Bus_{bid}_V0_pu", f"Bus_{bid}_V1_pu", f"Bus_{bid}_V2_pu",
                            f"Bus_{bid}_VUF_pct"
                        ])
                    writer.writerow(hdr)
                    for r in results:
                        row = [r['step_index'], r['timestamp'], r['time_label']]
                        for bid in bus_ids:
                            b = r['bus_results'].get(bid, {})
                            row.extend([
                                f"{b.get('Va', 1.0):.4f}", f"{b.get('Vb', 1.0):.4f}", f"{b.get('Vc', 1.0):.4f}",
                                f"{b.get('anga', 0.0):.2f}", f"{b.get('angb', -120.0):.2f}", f"{b.get('angc', 120.0):.2f}",
                                f"{b.get('V0', 0.0):.4f}", f"{b.get('V1', 1.0):.4f}", f"{b.get('V2', 0.0):.4f}",
                                f"{b.get('VUF', 0.0):.3f}"
                            ])
                        writer.writerow(row)
                generated['3phase_bus_csv'] = tp_bus_csv

                tp_branch_csv = os.path.join(self.output_folder, f"{self.case_name}_TIMESERIES_3PHASE_BRANCH_FLOWS.csv")
                with open(tp_branch_csv, "w", newline="", encoding="utf-8") as fp:
                    writer = csv.writer(fp)
                    hdr = ["Step", "Timestamp", "Time_Label"]
                    for lid in line_ids:
                        hdr.extend([
                            f"Line_{lid}_Pa_MW", f"Line_{lid}_Pb_MW", f"Line_{lid}_Pc_MW",
                            f"Line_{lid}_Qa_MVar", f"Line_{lid}_Qb_MVar", f"Line_{lid}_Qc_MVar",
                            f"Line_{lid}_In_A", f"Line_{lid}_Loss_MW", f"Line_{lid}_Loading_Pct"
                        ])
                    for xid in xfmr_ids:
                        hdr.extend([
                            f"Xfmr_{xid}_Pa_MW", f"Xfmr_{xid}_Pb_MW", f"Xfmr_{xid}_Pc_MW",
                            f"Xfmr_{xid}_Qa_MVar", f"Xfmr_{xid}_Qb_MVar", f"Xfmr_{xid}_Qc_MVar",
                            f"Xfmr_{xid}_In_A", f"Xfmr_{xid}_Loss_MW", f"Xfmr_{xid}_Loading_Pct"
                        ])
                    writer.writerow(hdr)
                    for r in results:
                        row = [r['step_index'], r['timestamp'], r['time_label']]
                        for lid in line_ids:
                            br = r['branch_results'].get(f"Line_{lid}", {})
                            row.extend([
                                f"{br.get('Pa', 0.0):.3f}", f"{br.get('Pb', 0.0):.3f}", f"{br.get('Pc', 0.0):.3f}",
                                f"{br.get('Qa', 0.0):.3f}", f"{br.get('Qb', 0.0):.3f}", f"{br.get('Qc', 0.0):.3f}",
                                f"{br.get('In', 0.0):.2f}", f"{br.get('Loss_MW', 0.0):.4f}", f"{br.get('Loading_Pct', 0.0):.2f}"
                            ])
                        for xid in xfmr_ids:
                            br = r['branch_results'].get(f"Xfmr_{xid}", {})
                            row.extend([
                                f"{br.get('Pa', 0.0):.3f}", f"{br.get('Pb', 0.0):.3f}", f"{br.get('Pc', 0.0):.3f}",
                                f"{br.get('Qa', 0.0):.3f}", f"{br.get('Qb', 0.0):.3f}", f"{br.get('Qc', 0.0):.3f}",
                                f"{br.get('In', 0.0):.2f}", f"{br.get('Loss_MW', 0.0):.4f}", f"{br.get('Loading_Pct', 0.0):.2f}"
                            ])
                        writer.writerow(row)
                generated['3phase_branch_csv'] = tp_branch_csv

                tp_vuf_csv = os.path.join(self.output_folder, f"{self.case_name}_TIMESERIES_3PHASE_UNBALANCE_VUF.csv")
                with open(tp_vuf_csv, "w", newline="", encoding="utf-8") as fp:
                    writer = csv.writer(fp)
                    hdr = ["Step", "Timestamp", "Time_Label", "Max_VUF_pct", "Critical_Bus", "IEEE_1159_Compliant"]
                    for bid in bus_ids:
                        hdr.append(f"Bus_{bid}_VUF_pct")
                    writer.writerow(hdr)
                    for r in results:
                        mvuf = r.get('max_vuf_pct', 0.0)
                        c_bus = r.get('max_vuf_bus', 0)
                        compl = "PASS (<= 2.0%)" if mvuf <= 2.0 else "EXCEEDED (> 2.0%)"
                        row = [r['step_index'], r['timestamp'], r['time_label'], f"{mvuf:.3f}", c_bus, compl]
                        for bid in bus_ids:
                            b = r['bus_results'].get(bid, {})
                            row.append(f"{b.get('VUF', 0.0):.3f}")
                        writer.writerow(row)
                generated['3phase_vuf_csv'] = tp_vuf_csv

        # 3. Master Consolidated Reports (.csv, .py, .invout)
        try:
            try:
                from time_series_report_writer import (
                    write_timeseries_all_data_csv,
                    write_timeseries_all_data_py,
                    write_timeseries_invout_report
                )
            except ImportError:
                from utils.time_series_report_writer import (
                    write_timeseries_all_data_csv,
                    write_timeseries_all_data_py,
                    write_timeseries_invout_report
                )

            if self.csv_report:
                all_csv = os.path.join(self.output_folder, f"{self.case_name}_TIMESERIES_ALL_DATA.csv")
                write_timeseries_all_data_csv(all_csv, self.case_name, self.full_data, results, total_gen_mwh, total_load_mwh, total_loss_mwh)
                generated['master_csv'] = all_csv

            if self.py_report:
                all_py = os.path.join(self.output_folder, f"{self.case_name}_TIMESERIES_ALL_DATA.py")
                write_timeseries_all_data_py(all_py, self.case_name, self.full_data, results, total_gen_mwh, total_load_mwh, total_loss_mwh)
                generated['master_py'] = all_py

            if self.txt_report:
                all_invout = os.path.join(self.output_folder, f"{self.case_name}_TIMESERIES_ALL_DATA.invout")
                write_timeseries_invout_report(all_invout, self.case_name, self.full_data, results, total_gen_mwh, total_load_mwh, total_loss_mwh)
                generated['master_txt'] = all_invout

        except Exception as e:
            print(f"⚠️ Warning: Could not generate master reports ({e})")

        return generated


def main():
    parser = argparse.ArgumentParser(description="DevEN Chronological Time Series Power Flow Engine")
    parser.add_argument("-i", "--input", type=str, required=True, help="Input python case file")
    parser.add_argument("-d", "--duration", type=float, default=24.0, help="Duration value")
    parser.add_argument("--dur-unit", type=str, default="Hours", help="Duration unit (Seconds, Minutes, Hours, Days, Weeks, Months, Years)")
    parser.add_argument("-s", "--step-size", type=float, default=1.0, help="Step size value")
    parser.add_argument("--step-unit", type=str, default="Hours", help="Step unit")
    parser.add_argument("--start-time", type=str, default="2026-01-01 00:00:00", help="Start timestamp")
    parser.add_argument("--imputation", type=str, default="linear", help="Missing data imputation method")
    parser.add_argument("-e", "--engine", type=str, default="andes_nr", help="Solver engine")
    parser.add_argument("-t", "--tol", type=float, default=0.000001, help="Tolerance")
    parser.add_argument("--max-iter", type=int, default=20, help="Max iterations")
    parser.add_argument("--v-init-base", type=str, default="flat", help="Base/1st step init (flat or initial)")
    parser.add_argument("--v-init-step", type=str, default="warm", help="Step init (warm, flat, initial)")
    parser.add_argument("-o", "--output", type=str, default="", help="Output directory")

    args = parser.parse_args()

    time_settings = {
        'duration': args.duration,
        'duration_unit': args.dur_unit,
        'step_size': args.step_size,
        'step_unit': args.step_unit,
        'start_time': args.start_time,
        'imputation_method': args.imputation,
    }

    solver_settings = {
        'engine': args.engine,
        'tol': args.tol,
        'max_iter': args.max_iter,
        'v_init_base': args.v_init_base,
        'v_init_step': args.v_init_step,
        'output_folder': args.output,
    }

    engine = TimeSeriesEngine(args.input, time_settings=time_settings, solver_settings=solver_settings)
    engine.run()


if __name__ == "__main__":
    main()

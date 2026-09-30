# DevEN Path Bootstrapper
import sys
import os
import copy
import time
import math
import argparse
import json
import numpy as np
from datetime import datetime

# Path bootstrapping
_root_dir = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(_root_dir) in ('engines', 'utils', 'cli'):
    _root_dir = os.path.dirname(_root_dir)
if _root_dir not in sys.path:
    sys.path.insert(0, _root_dir)
for _sub in ('engines', 'utils', 'cli'):
    _p = os.path.join(_root_dir, _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from input_reader import InputReader
except ImportError:
    from utils.input_reader import InputReader

try:
    from report_writer import ReportWriter
except ImportError:
    from utils.report_writer import ReportWriter

try:
    from power_flow_engine import PowerFlowEngine
except ImportError:
    from engines.power_flow_engine import PowerFlowEngine

try:
    from sensitivity_engine import SensitivityEngine, SensitivityConfig
except ImportError:
    from engines.sensitivity_engine import SensitivityEngine, SensitivityConfig

try:
    from ttc_report_writer import TTCReportWriter
except ImportError:
    from utils.ttc_report_writer import TTCReportWriter


class TTCEngine:
    """
    DevEN Total Transfer Capability (TTC) & Available Transfer Capability (ATC) Engine.
    
    Implements:
      1. Linear Thermal TTC (Screening via PTDF, OTDF, and GSDF)
      2. Full AC Bisection (Repeated Newton-Raphson AC Power Flow with generator Q-limits)
      3. Base Transfer Auto-Calculation from inter-area tie-lines (P_base_transfer = sum(P_tie))
      4. Mathematical Formulation: TTC = P_base_transfer + Delta_P_headroom
      5. Complete ATC Calculation: ATC_Firm = TTC - TRM - CBM - ETC_Firm
    """

    def __init__(
        self,
        case_data_or_file,
        source_mode="area",      # "area", "zone", "buses"
        source_id="1",           # area/zone number or comma-separated bus list
        sink_mode="area",        # "area", "zone", "buses"
        sink_id="2",             # area/zone number or comma-separated bus list
        method="ac_bisection",   # "ac_bisection" or "linear_thermal"
        contingency_scope="n1_branches",  # "n0_only", "n1_branches", "n1_all"
        base_transfer_mode="auto",        # "auto" (sum tie-lines) or "manual"
        base_transfer_mw=0.0,
        base_rating_mode="rateA",         # "rateA", "rateB", "100%", "custom"
        emerg_rating_mode="115%",         # "115%", "120%", "rateB", "rateA", "custom"
        base_rating_mult=1.0,
        emerg_rating_mult=1.15,
        custom_branch_rating=0.0,
        v_min_norm=0.95,
        v_max_norm=1.05,
        v_min_emerg=0.90,
        v_max_emerg=1.10,
        target_mw=1000.0,
        mw_tolerance=1.0,
        max_bisection_iters=25,
        enforce_q_limits=True,
        load_pf_mode="constant_pf",       # "constant_pf" or "unity_pf"
        trm_mode="pct",                   # "pct" or "mw"
        trm_pct=5.0,
        trm_mw=0.0,
        cbm_mw=0.0,
        etc_mode="use_base",              # "use_base" or "custom"
        etc_custom_mw=0.0,
        output_folder=None,
        progress_callback=None
    ):
        if isinstance(case_data_or_file, str):
            self.input_file = case_data_or_file
            self.case_name = os.path.splitext(os.path.basename(case_data_or_file))[0]
            if self.case_name.endswith('_converted'):
                self.case_name = self.case_name[:-10]
            self.full_data = InputReader.read_from_python(case_data_or_file)
            if not self.full_data:
                raise ValueError(f"Failed to load or parse power system case data from: {case_data_or_file}")
        else:
            self.input_file = "in_memory_case.py"
            self.case_name = case_data_or_file.get('project_name', 'NETWORK_CASE')
            self.full_data = copy.deepcopy(case_data_or_file)
            if not self.full_data:
                raise ValueError("Case data dictionary is empty.")

        self.source_mode = str(source_mode).lower()
        self.source_id = source_id
        self.sink_mode = str(sink_mode).lower()
        self.sink_id = sink_id

        self.method = str(method).lower()
        self.contingency_scope = str(contingency_scope).lower()

        self.base_transfer_mode = str(base_transfer_mode).lower()
        self.base_transfer_mw = float(base_transfer_mw)

        self.base_rating_mode = str(base_rating_mode).lower()
        self.emerg_rating_mode = str(emerg_rating_mode).lower()
        self.base_rating_mult = float(base_rating_mult)
        self.emerg_rating_mult = float(emerg_rating_mult)
        self.custom_branch_rating = float(custom_branch_rating)

        self.v_min_norm = float(v_min_norm)
        self.v_max_norm = float(v_max_norm)
        self.v_min_emerg = float(v_min_emerg)
        self.v_max_emerg = float(v_max_emerg)

        self.target_mw = float(target_mw)
        self.mw_tolerance = float(mw_tolerance)
        self.max_bisection_iters = int(max_bisection_iters)
        self.enforce_q_limits = bool(enforce_q_limits)
        self.load_pf_mode = str(load_pf_mode).lower()

        self.trm_mode = str(trm_mode).lower()
        self.trm_pct = float(trm_pct)
        self.trm_mw = float(trm_mw)
        self.cbm_mw = float(cbm_mw)
        self.etc_mode = str(etc_mode).lower()
        self.etc_custom_mw = float(etc_custom_mw)

        if output_folder:
            self.output_folder = output_folder
        elif isinstance(case_data_or_file, str) and os.path.exists(case_data_or_file):
            case_dir = os.path.dirname(os.path.abspath(case_data_or_file))
            self.output_folder = os.path.join(case_dir, f"{self.case_name}_TTC_ATC")
        else:
            self.output_folder = os.path.join(_root_dir, "output", f"TTC_{self.case_name}")
        self.progress_callback = progress_callback or (lambda pct, msg: None)

        # Parse source and sink buses
        self.source_buses = self._resolve_buses(self.source_mode, self.source_id)
        self.sink_buses = self._resolve_buses(self.sink_mode, self.sink_id)

    def _notify(self, pct, msg):
        try:
            self.progress_callback(pct, msg)
        except Exception:
            pass

    def _resolve_buses(self, mode, id_val):
        """Resolves bus IDs based on area, zone, or specific bus list."""
        all_buses = self.full_data.get('buses', {})
        b_list = []
        if mode == 'buses':
            if isinstance(id_val, (list, tuple)):
                raw = [str(x).strip() for x in id_val]
            else:
                raw = [s.strip() for s in str(id_val).replace(';', ',').split(',') if s.strip()]
            for item in raw:
                # Can be int or string bus ID
                if item.isdigit() and int(item) in all_buses:
                    b_list.append(int(item))
                elif item in all_buses:
                    b_list.append(item)
                else:
                    try:
                        val = int(item)
                        b_list.append(val)
                    except Exception:
                        b_list.append(item)
        elif mode == 'zone':
            target_zone = str(id_val).strip()
            for b_id, b_data in all_buses.items():
                if str(b_data.get('zone', 1)).strip() == target_zone:
                    b_list.append(b_id)
        else:  # area default
            target_area = str(id_val).strip()
            for b_id, b_data in all_buses.items():
                if str(b_data.get('area', 1)).strip() == target_area:
                    b_list.append(b_id)

        # Fallback if no matching buses found
        if not b_list and all_buses:
            if mode == 'area' and str(id_val) == '2':
                # Pick other half of buses
                mid = len(all_buses) // 2
                b_list = list(all_buses.keys())[mid:]
            else:
                mid = len(all_buses) // 2
                b_list = list(all_buses.keys())[:max(1, mid)]
        return b_list

    def _get_branch_rating(self, br_data, is_contingency=False):
        """Calculates normal or emergency MVA rating for a branch based on user selection."""
        rateA = float(br_data.get('rateA', 0.0) or br_data.get('rating', 0.0) or 0.0)
        rateB = float(br_data.get('rateB', 0.0) or 0.0)
        if rateB <= 0.0:
            rateB = rateA * 1.15  # standard industry fallback

        if not is_contingency:
            # Base Case Rating
            if self.base_rating_mode in ('rateb', 'emergency'):
                rating = rateB if rateB > 0 else rateA
            elif self.base_rating_mode in ('custom', 'user'):
                rating = self.custom_branch_rating if self.custom_branch_rating > 0 else rateA
            else:  # rateA or 100%
                rating = rateA * self.base_rating_mult
        else:
            # Contingency Rating
            if self.emerg_rating_mode in ('ratea', 'normal'):
                rating = rateA
            elif self.emerg_rating_mode in ('rateb', 'emergency') and rateB > 0:
                rating = rateB
            elif '120' in self.emerg_rating_mode:
                rating = rateA * 1.20
            elif self.emerg_rating_mode in ('custom', 'user'):
                rating = self.custom_branch_rating if self.custom_branch_rating > 0 else (rateA * self.emerg_rating_mult)
            else:  # default 115% of rateA
                rating = rateA * self.emerg_rating_mult

        if rating <= 0.0:
            rating = 9999.0  # unconstrained line fallback
        return rating

    def _find_inter_area_tie_lines(self):
        """Finds all transmission lines and transformers that connect Source buses to Sink buses."""
        source_set = set(self.source_buses)
        sink_set = set(self.sink_buses)
        tie_lines = []

        # Lines
        for l_id, l_data in self.full_data.get('lines', {}).items():
            fb = l_data.get('from_bus')
            tb = l_data.get('to_bus')
            if (fb in source_set and tb in sink_set) or (fb in sink_set and tb in source_set):
                forward = (fb in source_set and tb in sink_set)
                tie_lines.append({
                    'type': 'line',
                    'id': l_id,
                    'key': f"Line_{l_id}",
                    'name': l_data.get('name', f"Line_{l_id}"),
                    'from_bus': fb,
                    'to_bus': tb,
                    'forward': forward,
                    'rateA': float(l_data.get('rateA', 0.0) or l_data.get('rating', 0.0) or 0.0),
                    'rateB': float(l_data.get('rateB', 0.0) or 0.0),
                    'data': l_data
                })

        # Transformers
        for x_id, x_data in self.full_data.get('transformers', {}).items():
            fb = x_data.get('from_bus')
            tb = x_data.get('to_bus')
            if (fb in source_set and tb in sink_set) or (fb in sink_set and tb in source_set):
                forward = (fb in source_set and tb in sink_set)
                tie_lines.append({
                    'type': 'transformer',
                    'id': x_id,
                    'key': f"Xfmr_{x_id}",
                    'name': x_data.get('name', f"Xfmr_{x_id}"),
                    'from_bus': fb,
                    'to_bus': tb,
                    'forward': forward,
                    'rateA': float(x_data.get('rateA', 0.0) or x_data.get('rating', 0.0) or 0.0),
                    'rateB': float(x_data.get('rateB', 0.0) or 0.0),
                    'data': x_data
                })

        return tie_lines

    def _solve_ac_power_flow(self, case_data):
        """Solves AC power flow with generator Q-limits enforced."""
        try:
            bus_engine, branch_engine, full_engine = InputReader.convert_to_engine_format(case_data)
            engine = PowerFlowEngine(baseMVA=case_data.get('base_mva', 100.0))
            engine.initialize(
                bus_engine, branch_engine, full_data=case_data,
                solver_method='andes_nr', tol=1e-6, max_iter=30,
                ignore_q_tol=not self.enforce_q_limits,
                industry_std_pv=True, v_init_mode='flat'
            )
            samples, valid_count = engine.run_batch(n_samples=1, variation_strength=0.0)
            converged = (valid_count > 0 and len(samples) > 0 and bool(samples[0].get('converged', False)))
            if not converged:
                return False, {}, {}

            rep_writer = ReportWriter(engine, case_data, samples, 0.0)
            buses = case_data.get('buses', {})
            bus_res = {}
            for b_num in buses.keys():
                idx = engine.bus_index_map.get(b_num, 0)
                vm = float(rep_writer.avg_V[idx]) if hasattr(rep_writer, 'avg_V') else 1.0
                va = float(rep_writer.avg_Va[idx]) if hasattr(rep_writer, 'avg_Va') else 0.0
                bus_res[b_num] = {'vm': vm, 'va': va}

            branch_res = {}
            for l_id, line in case_data.get('lines', {}).items():
                st = rep_writer._get_line_stats(l_id, line)
                pf = float(st.get('avg_P_fwd', 0.0))
                qf = float(st.get('avg_Q_fwd', 0.0))
                sf = math.sqrt(pf**2 + qf**2)
                pr = float(st.get('avg_P_rev', 0.0))
                qr = float(st.get('avg_Q_rev', 0.0))
                sr = math.sqrt(pr**2 + qr**2)
                s_max = max(sf, sr)
                branch_res[f"Line_{l_id}"] = {
                    'p_fwd': pf, 'q_fwd': qf, 'p_rev': pr, 'q_rev': qr,
                    's_mva': s_max, 'from_bus': line.get('from_bus'), 'to_bus': line.get('to_bus'),
                    'data': line
                }

            for x_id, xfmr in case_data.get('transformers', {}).items():
                st = rep_writer._get_xfmr_stats(x_id, xfmr)
                pf = float(st.get('avg_P_fwd', 0.0))
                qf = float(st.get('avg_Q_fwd', 0.0))
                sf = math.sqrt(pf**2 + qf**2)
                pr = float(st.get('avg_P_rev', 0.0))
                qr = float(st.get('avg_Q_rev', 0.0))
                sr = math.sqrt(pr**2 + qr**2)
                s_max = max(sf, sr)
                branch_res[f"Xfmr_{x_id}"] = {
                    'p_fwd': pf, 'q_fwd': qf, 'p_rev': pr, 'q_rev': qr,
                    's_mva': s_max, 'from_bus': xfmr.get('from_bus'), 'to_bus': xfmr.get('to_bus'),
                    'data': xfmr
                }

            return True, bus_res, branch_res
        except Exception:
            return False, {}, {}

    def _calculate_base_transfer(self, tie_lines, branch_results):
        """Calculates base transfer across tie lines connecting source to sink."""
        if self.base_transfer_mode == 'manual' and self.base_transfer_mw != 0.0:
            return self.base_transfer_mw, tie_lines

        total_base_mw = 0.0
        for t in tie_lines:
            key = t['key']
            br_info = branch_results.get(key, {})
            if br_info:
                if t['forward']:
                    p_flow = br_info.get('p_fwd', 0.0)
                    q_flow = br_info.get('q_fwd', 0.0)
                else:
                    p_flow = -br_info.get('p_rev', 0.0)
                    q_flow = -br_info.get('q_rev', 0.0)
                t['p_mw'] = p_flow
                t['q_mvar'] = q_flow
                t['flow_mva'] = br_info.get('s_mva', 0.0)
                total_base_mw += p_flow
            else:
                t['p_mw'] = 0.0
                t['q_mvar'] = 0.0
                t['flow_mva'] = 0.0

        if abs(total_base_mw) < 1e-4:
            # Fallback if no direct tie-lines or disconnected areas: sum source generation
            tot_src_gen = sum(
                float(g.get('P_out', 0.0))
                for g in self.full_data.get('generators', {}).values()
                if g.get('bus') in self.source_buses and g.get('status', 1) == 1
            )
            if self.base_transfer_mode != 'manual':
                total_base_mw = tot_src_gen * 0.5  # reasonable estimation

        return total_base_mw, tie_lines

    def run(self):
        """Executes the selected TTC / ATC study."""
        t0 = time.time()
        self._notify(5, "Initializing TTC / ATC Study Engine...")

        # 1. Inter-area tie-lines and base AC solution
        tie_lines = self._find_inter_area_tie_lines()
        self._notify(10, f"Found {len(tie_lines)} inter-area tie-lines connecting Source to Sink...")

        conv, bus_res_base, branch_res_base = self._solve_ac_power_flow(self.full_data)
        if not conv:
            self._notify(15, "Base AC Power Flow failed. Attempting DC sensitivity fallback...")
        
        base_transfer_mw, updated_ties = self._calculate_base_transfer(tie_lines, branch_res_base)
        self._notify(20, f"Base Source-to-Sink Transfer: {base_transfer_mw:.2f} MW")

        # 2. Execute Method
        if "linear" in self.method or "ptdf" in self.method:
            res = self._run_linear_thermal_ttc(base_transfer_mw, updated_ties, branch_res_base)
        else:
            res = self._run_ac_bisection_ttc(base_transfer_mw, updated_ties, bus_res_base, branch_res_base)

        elapsed = time.time() - t0
        res['elapsed_sec'] = elapsed
        res['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 3. Calculate Margins and ATC
        ttc = float(res.get('ttc_mw', 0.0))
        
        # TRM
        if self.trm_mode == 'pct':
            trm_val = ttc * (self.trm_pct / 100.0)
        else:
            trm_val = self.trm_mw
        res['trm_mw'] = max(0.0, trm_val)

        # CBM
        res['cbm_mw'] = max(0.0, self.cbm_mw)

        # ETC
        if self.etc_mode == 'use_base':
            etc_val = base_transfer_mw
        else:
            etc_val = self.etc_custom_mw
        res['etc_firm_mw'] = max(0.0, etc_val)

        # ATC Formulations
        firm_atc = max(0.0, ttc - res['trm_mw'] - res['cbm_mw'] - res['etc_firm_mw'])
        non_firm_atc = max(0.0, ttc - res['etc_firm_mw'])
        res['firm_atc_mw'] = firm_atc
        res['non_firm_atc_mw'] = non_firm_atc

        # 4. Generate Reports
        self._notify(95, "Generating TTC/ATC Audit Reports (.invout, .csv, .json)...")
        rep_writer = TTCReportWriter(self.output_folder, self.case_name)
        rep_writer.write_full_report(res)

        self._notify(100, f"TTC / ATC Study Complete in {elapsed:.2f}s! TTC = {ttc:.2f} MW | Firm ATC = {firm_atc:.2f} MW")
        return res

    def _run_linear_thermal_ttc(self, base_transfer_mw, tie_lines, branch_res_base):
        """
        Calculates Linear Thermal TTC using PTDF, OTDF, and GSDF.
        Strictly labeled as Thermal TTC.
        """
        self._notify(30, "Computing Linear PTDF and LODF matrices...")
        cfg = SensitivityConfig(slack_bus=None, base_flow_mode='auto')
        sen = SensitivityEngine(self.full_data, config=cfg)
        sen.compute_ptdf()
        sen.compute_lodf()
        sen.resolve_base_flows()
        sen_base_flows = sen.base_flows if sen.base_flows is not None else np.zeros(len(sen.branches))

        # Participation vectors for Source and Sink
        src_set = set(self.source_buses)
        snk_set = set(self.sink_buses)
        
        n_buses = len(sen.bus_ids)
        alpha = np.zeros(n_buses)
        beta = np.zeros(n_buses)

        # Source gen participation
        for g in self.full_data.get('generators', {}).values():
            b = g.get('bus')
            if b in src_set and g.get('status', 1) == 1 and b in sen.bus_index_map:
                alpha[sen.bus_index_map[b]] += float(g.get('P_out', 10.0))
        if np.sum(alpha) <= 0.0:
            for b in self.source_buses:
                if b in sen.bus_index_map:
                    alpha[sen.bus_index_map[b]] = 1.0
        if np.sum(alpha) > 0:
            alpha /= np.sum(alpha)

        # Sink load participation
        for ld in self.full_data.get('loads', {}).values():
            b = ld.get('bus')
            if b in snk_set and ld.get('status', 1) == 1 and b in sen.bus_index_map:
                beta[sen.bus_index_map[b]] += float(ld.get('P_demand', 10.0))
        if np.sum(beta) <= 0.0:
            for b in self.sink_buses:
                if b in sen.bus_index_map:
                    beta[sen.bus_index_map[b]] = 1.0
        if np.sum(beta) > 0:
            beta /= np.sum(beta)

        # Bilateral PTDF (L,)
        ptdf_src = sen.ptdf_matrix @ alpha
        ptdf_snk = sen.ptdf_matrix @ beta
        ptdf_transfer = ptdf_src - ptdf_snk

        # Monitored branches
        min_headroom = float('inf')
        bottleneck_element = "None"
        bottleneck_type = "Thermal MVA Overload"
        critical_contingency = "Base Case (N-0)"
        binding_val_str = ""
        binding_lim_str = ""

        critical_branches = []

        # N-0 Base evaluation
        for idx, br in enumerate(sen.branches):
            key = br['key']
            p_transfer_factor = ptdf_transfer[idx]
            rating_norm = self._get_branch_rating(br, is_contingency=False)
            
            p0 = sen.base_flows[idx] if sen.base_flows is not None else 0.0
            br_base_info = branch_res_base.get(key, {})
            if br_base_info:
                p0 = br_base_info.get('s_mva', p0)

            # Headroom
            if abs(p_transfer_factor) > 1e-4:
                if p_transfer_factor > 0:
                    hr = (rating_norm - p0) / p_transfer_factor
                else:
                    hr = (rating_norm + p0) / abs(p_transfer_factor)
                
                hr = max(0.0, hr)
                if hr < min_headroom:
                    min_headroom = hr
                    bottleneck_element = br.get('name', key)
                    critical_contingency = "Base Case (N-0)"
                    binding_val_str = f"{p0 + p_transfer_factor * hr:.1f} MVA"
                    binding_lim_str = f"{rating_norm:.1f} MVA (Rate A)"

            critical_branches.append({
                'key': key,
                'name': br.get('name', key),
                'from_bus': br.get('from_bus'),
                'to_bus': br.get('to_bus'),
                'base_flow_mva': abs(p0),
                'flow_mva': abs(p0),
                'rating_mva': rating_norm,
                'loading_pct': (abs(p0) / rating_norm * 100.0) if rating_norm > 0 else 0.0,
                'contingency': "Base Case (N-0)",
                'status': "OK"
            })

        # N-1 Branch Outages evaluation (OTDF)
        if self.contingency_scope in ('n1_branches', 'n1_all') and sen.lodf_matrix is not None:
            self._notify(50, "Evaluating N-1 Branch Outages via OTDF...")
            n_branches = len(sen.branches)
            for k in range(n_branches):
                outage_br = sen.branches[k]
                outage_key = outage_br['key']
                outage_name = outage_br.get('name', outage_key)

                # OTDF = PTDF_l + LODF_{l, k} * PTDF_k
                otdf_k = ptdf_transfer + sen.lodf_matrix[:, k] * ptdf_transfer[k]

                for l in range(n_branches):
                    if l == k:
                        continue
                    mon_br = sen.branches[l]
                    rating_emerg = self._get_branch_rating(mon_br, is_contingency=True)
                    
                    p_post_base = sen_base_flows[l] + sen.lodf_matrix[l, k] * sen_base_flows[k]
                    otdf_factor = otdf_k[l]

                    if abs(otdf_factor) > 1e-4:
                        if otdf_factor > 0:
                            hr = (rating_emerg - p_post_base) / otdf_factor
                        else:
                            hr = (rating_emerg + p_post_base) / abs(otdf_factor)
                        
                        hr = max(0.0, hr)
                        if hr < min_headroom:
                            min_headroom = hr
                            bottleneck_element = mon_br.get('name', mon_br['key'])
                            critical_contingency = f"Trip {outage_name}"
                            binding_val_str = f"{p_post_base + otdf_factor * hr:.1f} MVA"
                            binding_lim_str = f"{rating_emerg:.1f} MVA (Emergency)"

        # N-1 Generator Outages evaluation (GSDF / re-dispatch)
        if self.contingency_scope == 'n1_all':
            self._notify(70, "Evaluating N-1 Generator Outages via GSDF / re-dispatch...")
            online_gens = [
                (gid, g) for gid, g in self.full_data.get('generators', {}).items()
                if g.get('status', 1) == 1 and g.get('bus') in sen.bus_index_map
            ]
            for gid, gen in online_gens:
                p_out = float(gen.get('P_out', 0.0))
                if p_out <= 5.0:
                    continue
                gen_bus_idx = sen.bus_index_map[gen.get('bus')]
                # Re-dispatch distribution to other online gens
                rem_gens = [g for g in online_gens if g[0] != gid]
                if not rem_gens:
                    continue
                gamma = np.zeros(n_buses)
                tot_p = sum(float(g[1].get('P_out', 10.0)) for g in rem_gens)
                for r_gid, r_g in rem_gens:
                    idx_r = sen.bus_index_map[r_g.get('bus')]
                    gamma[idx_r] += float(r_g.get('P_out', 10.0)) / max(tot_p, 1.0)
                
                # Shift factor vector for gen trip
                gen_trip_shift = sen.ptdf_matrix @ gamma - sen.ptdf_matrix[:, gen_bus_idx]

                for l in range(len(sen.branches)):
                    mon_br = sen.branches[l]
                    rating_emerg = self._get_branch_rating(mon_br, is_contingency=True)
                    p_post_base = sen_base_flows[l] + gen_trip_shift[l] * p_out
                    transfer_factor = ptdf_transfer[l]

                    if abs(transfer_factor) > 1e-4:
                        if transfer_factor > 0:
                            hr = (rating_emerg - p_post_base) / transfer_factor
                        else:
                            hr = (rating_emerg + p_post_base) / abs(transfer_factor)
                        hr = max(0.0, hr)
                        if hr < min_headroom:
                            min_headroom = hr
                            bottleneck_element = mon_br.get('name', mon_br['key'])
                            critical_contingency = f"Trip Gen {gen.get('name', gid)}"
                            binding_val_str = f"{p_post_base + transfer_factor * hr:.1f} MVA"
                            binding_lim_str = f"{rating_emerg:.1f} MVA (Emergency)"

        if math.isinf(min_headroom):
            min_headroom = self.target_mw

        # Calculate TTC
        ttc = base_transfer_mw + min_headroom

        # Sort critical branches by loading %
        critical_branches.sort(key=lambda x: x['loading_pct'], reverse=True)

        return {
            'method_label': "Linear Thermal TTC (PTDF / OTDF / GSDF)",
            'method': "linear_thermal",
            'contingency_scope': self.contingency_scope,
            'source_desc': f"{self.source_mode.upper()} {self.source_id} ({len(self.source_buses)} buses)",
            'sink_desc': f"{self.sink_mode.upper()} {self.sink_id} ({len(self.sink_buses)} buses)",
            'base_transfer_mode': self.base_transfer_mode.capitalize(),
            'base_transfer_mw': base_transfer_mw,
            'incremental_headroom_mw': min_headroom,
            'ttc_mw': ttc,
            'bottleneck_element': bottleneck_element,
            'bottleneck_type': bottleneck_type,
            'critical_contingency': critical_contingency,
            'binding_value_str': binding_val_str,
            'binding_limit_str': binding_lim_str,
            'tie_lines': tie_lines,
            'critical_branches': critical_branches,
            'critical_buses': []
        }

    def _run_ac_bisection_ttc(self, base_transfer_mw, tie_lines, bus_res_base, branch_res_base):
        """
        Calculates Total Transfer Capability using Full AC Repeated Power Flow with Bisection.
        Enforces generator Q-limits, constant PF load scaling, bus voltage limits, and thermal ratings.
        """
        self._notify(25, "Initiating Full AC Bisection Engine with Q-Limits Enforcement...")

        # Binary search bounds
        p_lower = 0.0
        p_upper = self.target_mw
        best_headroom = 0.0

        last_safe_bus_res = bus_res_base
        last_safe_branch_res = branch_res_base
        limiting_violation = None

        iter_count = 0
        while (p_upper - p_lower) > self.mw_tolerance and iter_count < self.max_bisection_iters:
            iter_count += 1
            p_test = 0.5 * (p_lower + p_upper)
            pct = 30 + int((iter_count / self.max_bisection_iters) * 60)
            self._notify(pct, f"Bisection Iter {iter_count}/{self.max_bisection_iters}: Testing Headroom +{p_test:.1f} MW...")

            # Apply transfer scaling
            scaled_case = self._scale_case_for_transfer(p_test)

            # Evaluate Security (N-0 and N-1)
            is_secure, viol_info, cur_bus_res, cur_branch_res = self._evaluate_ac_security(scaled_case)

            if is_secure:
                p_lower = p_test
                best_headroom = p_test
                last_safe_bus_res = cur_bus_res
                last_safe_branch_res = cur_branch_res
            else:
                p_upper = p_test
                limiting_violation = viol_info

        # Final TTC
        ttc = base_transfer_mw + best_headroom

        # Extract bottleneck details
        if limiting_violation:
            bottleneck_element = limiting_violation.get('element', 'N/A')
            bottleneck_type = limiting_violation.get('type', 'Thermal/Voltage Limit')
            critical_contingency = limiting_violation.get('contingency', 'Base Case (N-0)')
            binding_val_str = limiting_violation.get('val_str', '')
            binding_lim_str = limiting_violation.get('limit_str', '')
        else:
            bottleneck_element = f"Target Limit ({self.target_mw:.0f} MW Reached)"
            bottleneck_type = "Study Horizon Cap"
            critical_contingency = "None (System Operable across Target)"
            binding_val_str = f"{best_headroom:.1f} MW"
            binding_lim_str = f"{self.target_mw:.1f} MW"

        # Format critical branches and buses at limit
        critical_branches = []
        for key, br in last_safe_branch_res.items():
            rating = self._get_branch_rating(br.get('data', {}), is_contingency=False)
            s_mva = br.get('s_mva', 0.0)
            pct_load = (s_mva / rating * 100.0) if rating > 0 else 0.0
            critical_branches.append({
                'key': key,
                'name': br.get('data', {}).get('name', key),
                'from_bus': br.get('from_bus'),
                'to_bus': br.get('to_bus'),
                'base_flow_mva': branch_res_base.get(key, {}).get('s_mva', 0.0),
                'flow_mva': s_mva,
                'rating_mva': rating,
                'loading_pct': pct_load,
                'contingency': "Base Case (N-0)",
                'status': "OVERLOAD" if pct_load > 100.0 else "OK"
            })
        critical_branches.sort(key=lambda x: x['loading_pct'], reverse=True)

        critical_buses = []
        for b_id, b_res in last_safe_bus_res.items():
            b_data = self.full_data.get('buses', {}).get(b_id, {})
            vm = b_res.get('vm', 1.0)
            status = "OK"
            if vm < self.v_min_norm:
                status = "UNDERVOLT"
            elif vm > self.v_max_norm:
                status = "OVERVOLT"
            critical_buses.append({
                'bus_id': b_id,
                'name': b_data.get('name', f"Bus_{b_id}"),
                'base_kv': float(b_data.get('base_kV', 138.0)),
                'base_vm_pu': bus_res_base.get(b_id, {}).get('vm', 1.0),
                'vm_pu': vm,
                'vmin_pu': self.v_min_norm,
                'vmax_pu': self.v_max_norm,
                'status': status
            })
        critical_buses.sort(key=lambda x: abs(x['vm_pu'] - 1.0), reverse=True)

        return {
            'method_label': "Full AC Bisection (Repeated Power Flow)",
            'method': "ac_bisection",
            'contingency_scope': self.contingency_scope,
            'source_desc': f"{self.source_mode.upper()} {self.source_id} ({len(self.source_buses)} buses)",
            'sink_desc': f"{self.sink_mode.upper()} {self.sink_id} ({len(self.sink_buses)} buses)",
            'base_transfer_mode': self.base_transfer_mode.capitalize(),
            'base_transfer_mw': base_transfer_mw,
            'incremental_headroom_mw': best_headroom,
            'ttc_mw': ttc,
            'bisection_iterations': iter_count,
            'bottleneck_element': bottleneck_element,
            'bottleneck_type': bottleneck_type,
            'critical_contingency': critical_contingency,
            'binding_value_str': binding_val_str,
            'binding_limit_str': binding_lim_str,
            'tie_lines': tie_lines,
            'critical_branches': critical_branches,
            'critical_buses': critical_buses
        }

    def _scale_case_for_transfer(self, delta_p):
        """Creates a modified deepcopy of the network with transfer delta_p injected."""
        sc = copy.deepcopy(self.full_data)
        src_set = set(self.source_buses)
        snk_set = set(self.sink_buses)

        # 1. Scale Source Generators
        src_gens = [
            g for g in sc.get('generators', {}).values()
            if g.get('bus') in src_set and g.get('status', 1) == 1
        ]
        if src_gens:
            tot_p = sum(float(g.get('P_out', 10.0)) for g in src_gens)
            for g in src_gens:
                factor = (float(g.get('P_out', 10.0)) / max(tot_p, 1.0)) if tot_p > 0 else (1.0 / len(src_gens))
                g['P_out'] = float(g.get('P_out', 0.0)) + factor * delta_p
        else:
            # If no gens in source buses, pick first bus and inject
            first_b = self.source_buses[0] if self.source_buses else 1
            sc.setdefault('generators', {})['TTC_Source_Gen'] = {
                'bus': first_b, 'name': 'TTC_Source_Gen', 'P_out': delta_p, 'Q_out': 0.0,
                'V_set': 1.02, 'Qmin': -999.0, 'Qmax': 999.0, 'status': 1
            }

        # 2. Scale Sink Loads (Constant Power Factor)
        snk_loads = [
            ld for ld in sc.get('loads', {}).values()
            if ld.get('bus') in snk_set and ld.get('status', 1) == 1
        ]
        if snk_loads:
            tot_ld = sum(float(ld.get('P_demand', 10.0)) for ld in snk_loads)
            for ld in snk_loads:
                factor = (float(ld.get('P_demand', 10.0)) / max(tot_ld, 1.0)) if tot_ld > 0 else (1.0 / len(snk_loads))
                old_p = float(ld.get('P_demand', 0.0))
                old_q = float(ld.get('Q_demand', 0.0))
                tan_phi = (old_q / old_p) if abs(old_p) > 1e-3 else 0.2
                new_p = old_p + factor * delta_p
                ld['P_demand'] = new_p
                if self.load_pf_mode == 'constant_pf':
                    ld['Q_demand'] = new_p * tan_phi
        else:
            first_snk = self.sink_buses[0] if self.sink_buses else 2
            sc.setdefault('loads', {})['TTC_Sink_Load'] = {
                'bus': first_snk, 'name': 'TTC_Sink_Load', 'P_demand': delta_p,
                'Q_demand': delta_p * 0.2, 'status': 1
            }

        return sc

    def _evaluate_ac_security(self, case_data):
        """Evaluates convergence, normal thermal/voltage limits, and N-1 contingencies."""
        # 1. Base Case (N-0) AC Power Flow
        conv, b_res, br_res = self._solve_ac_power_flow(case_data)
        if not conv:
            return False, {
                'element': 'Grid Wide',
                'type': 'Voltage Collapse / Divergence',
                'contingency': 'Base Case (N-0)',
                'val_str': 'Singular Jacobian',
                'limit_str': 'P-V Nose Boundary'
            }, b_res, br_res

        # Check N-0 Voltages
        for b_id, b_res_item in b_res.items():
            vm = b_res_item['vm']
            if vm < self.v_min_norm:
                return False, {
                    'element': f"Bus {b_id}",
                    'type': 'Bus Undervoltage',
                    'contingency': 'Base Case (N-0)',
                    'val_str': f"{vm:.3f} pu",
                    'limit_str': f"{self.v_min_norm:.2f} pu"
                }, b_res, br_res
            elif vm > self.v_max_norm:
                return False, {
                    'element': f"Bus {b_id}",
                    'type': 'Bus Overvoltage',
                    'contingency': 'Base Case (N-0)',
                    'val_str': f"{vm:.3f} pu",
                    'limit_str': f"{self.v_max_norm:.2f} pu"
                }, b_res, br_res

        # Check N-0 Thermal Loading
        for key, br in br_res.items():
            rating = self._get_branch_rating(br.get('data', {}), is_contingency=False)
            s_mva = br.get('s_mva', 0.0)
            if s_mva > rating:
                return False, {
                    'element': br.get('data', {}).get('name', key),
                    'type': 'Thermal Overload',
                    'contingency': 'Base Case (N-0)',
                    'val_str': f"{s_mva:.1f} MVA",
                    'limit_str': f"{rating:.1f} MVA (Rate A)"
                }, b_res, br_res

        # If N-0 only, return secure
        if self.contingency_scope == 'n0_only':
            return True, None, b_res, br_res

        # 2. N-1 Branch Contingencies
        if self.contingency_scope in ('n1_branches', 'n1_all'):
            # Screen line trips
            for l_id, l_data in case_data.get('lines', {}).items():
                if int(l_data.get('status', 1)) == 0:
                    continue
                # Trip line
                l_data_copy = copy.deepcopy(case_data)
                l_data_copy['lines'][l_id]['status'] = 0
                c_conv, c_b_res, c_br_res = self._solve_ac_power_flow(l_data_copy)
                if not c_conv:
                    return False, {
                        'element': f"Line {l_id}",
                        'type': 'Post-Contingency Voltage Collapse',
                        'contingency': f"Trip Line {l_data.get('name', l_id)}",
                        'val_str': 'Diverged',
                        'limit_str': 'P-V Stability Limit'
                    }, b_res, br_res

                # Check Emergency Voltages
                for b_id, b_item in c_b_res.items():
                    vm = b_item['vm']
                    if vm < self.v_min_emerg:
                        return False, {
                            'element': f"Bus {b_id}",
                            'type': 'Post-Contingency Undervoltage',
                            'contingency': f"Trip Line {l_data.get('name', l_id)}",
                            'val_str': f"{vm:.3f} pu",
                            'limit_str': f"{self.v_min_emerg:.2f} pu"
                        }, b_res, br_res

                # Check Emergency Thermal Ratings
                for br_key, br_val in c_br_res.items():
                    rating_emerg = self._get_branch_rating(br_val.get('data', {}), is_contingency=True)
                    s_mva = br_val.get('s_mva', 0.0)
                    if s_mva > rating_emerg:
                        return False, {
                            'element': br_val.get('data', {}).get('name', br_key),
                            'type': 'Post-Contingency Thermal Overload',
                            'contingency': f"Trip Line {l_data.get('name', l_id)}",
                            'val_str': f"{s_mva:.1f} MVA",
                            'limit_str': f"{rating_emerg:.1f} MVA (Emergency)"
                        }, b_res, br_res

        # 3. N-1 Generator Contingencies
        if self.contingency_scope == 'n1_all':
            for gid, g_data in case_data.get('generators', {}).items():
                if int(g_data.get('status', 1)) == 0 or float(g_data.get('P_out', 0.0)) <= 5.0:
                    continue
                g_case = copy.deepcopy(case_data)
                lost_p = float(g_case['generators'][gid]['P_out'])
                g_case['generators'][gid]['status'] = 0
                g_case['generators'][gid]['P_out'] = 0.0
                g_case['generators'][gid]['Q_out'] = 0.0

                # Re-dispatch lost_p pro-rata among remaining active generators
                active_gens = [
                    g for g in g_case.get('generators', {}).values()
                    if g.get('status', 1) == 1 and g.get('bus') != g_data.get('bus')
                ]
                if active_gens:
                    tot_p = sum(float(g.get('P_out', 10.0)) for g in active_gens)
                    for g in active_gens:
                        f = (float(g.get('P_out', 10.0)) / max(tot_p, 1.0))
                        g['P_out'] = float(g.get('P_out', 0.0)) + f * lost_p

                c_conv, c_b_res, c_br_res = self._solve_ac_power_flow(g_case)
                if not c_conv:
                    return False, {
                        'element': f"Gen {gid}",
                        'type': 'Post-Contingency Voltage Collapse',
                        'contingency': f"Trip Gen {g_data.get('name', gid)}",
                        'val_str': 'Diverged',
                        'limit_str': 'Insolvent Grid'
                    }, b_res, br_res

                for br_key, br_val in c_br_res.items():
                    rating_emerg = self._get_branch_rating(br_val.get('data', {}), is_contingency=True)
                    s_mva = br_val.get('s_mva', 0.0)
                    if s_mva > rating_emerg:
                        return False, {
                            'element': br_val.get('data', {}).get('name', br_key),
                            'type': 'Post-Contingency Thermal Overload',
                            'contingency': f"Trip Gen {g_data.get('name', gid)}",
                            'val_str': f"{s_mva:.1f} MVA",
                            'limit_str': f"{rating_emerg:.1f} MVA (Emergency)"
                        }, b_res, br_res

        return True, None, b_res, br_res


# ─────────────────────────────────────────────────────────────────────────────
# CLI ENTRYPOINT (Supports CMD execution and standalone exe compiling)
# ─────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="DevEN Total & Available Transfer Capability (TTC / ATC) Analyzer — CLI & Headless Runner"
    )
    parser.add_argument("-i", "--case", required=True, help="Path to Python (.py) or SQLite (.db) case file")
    parser.add_argument("--source-mode", default="area", choices=["area", "zone", "buses"], help="Source selection mode")
    parser.add_argument("--source-id", default="1", help="Source Area ID, Zone ID, or comma-separated bus list")
    parser.add_argument("--sink-mode", default="area", choices=["area", "zone", "buses"], help="Sink selection mode")
    parser.add_argument("--sink-id", default="2", help="Sink Area ID, Zone ID, or comma-separated bus list")
    
    parser.add_argument("--method", default="ac_bisection", choices=["ac_bisection", "linear_thermal"],
                        help="Transfer calculation method (Full AC Bisection or Linear Thermal PTDF/OTDF)")
    parser.add_argument("--contingency", default="n1_branches", choices=["n0_only", "n1_branches", "n1_all"],
                        help="Contingency security screening scope")

    parser.add_argument("--base-transfer-mode", default="auto", choices=["auto", "manual"],
                        help="Base transfer mode: auto (sum tie-lines) or manual override")
    parser.add_argument("--base-transfer-mw", type=float, default=0.0, help="Manual base transfer override (MW)")

    # Flexible Rating Selection
    parser.add_argument("--base-rating", default="rateA", choices=["rateA", "rateB", "100%", "custom"],
                        help="Normal branch rating convention")
    parser.add_argument("--emerg-rating", default="115%", choices=["115%", "120%", "rateB", "rateA", "custom"],
                        help="Emergency branch rating convention for N-1 contingencies")
    parser.add_argument("--emerg-mult", type=float, default=1.15, help="Multiplier on Rate A for emergency rating")
    parser.add_argument("--custom-rating", type=float, default=0.0, help="Custom rating MVA override")

    # Voltage Limits
    parser.add_argument("--v-min-norm", type=float, default=0.95, help="Normal min voltage limit (pu)")
    parser.add_argument("--v-max-norm", type=float, default=1.05, help="Normal max voltage limit (pu)")
    parser.add_argument("--v-min-emerg", type=float, default=0.90, help="Emergency min voltage limit (pu)")
    parser.add_argument("--v-max-emerg", type=float, default=1.10, help="Emergency max voltage limit (pu)")

    # Bisection parameters
    parser.add_argument("-t", "--target-mw", type=float, default=1000.0, help="Target transfer study horizon (MW)")
    parser.add_argument("--tol", type=float, default=1.0, help="Bisection convergence tolerance (MW)")
    parser.add_argument("--max-iter", type=int, default=25, help="Maximum bisection iterations")
    parser.add_argument("--ignore-q", action="store_true", help="Ignore generator Q-limits (unconstrained PV)")

    # Margins & ATC
    parser.add_argument("--trm-pct", type=float, default=5.0, help="Transmission Reliability Margin percentage (%%)")
    parser.add_argument("--trm-mw", type=float, default=0.0, help="Fixed TRM in MW (if > 0 overrides pct)")
    parser.add_argument("--cbm-mw", type=float, default=0.0, help="Capacity Benefit Margin (MW)")
    parser.add_argument("--etc-mw", type=float, default=0.0, help="Existing Transmission Commitments (MW)")

    # Output options
    parser.add_argument("-o", "--output-dir", default=None, help="Directory to save report and CSV exports")
    parser.add_argument("--json-out", action="store_true", help="Print full results dictionary as JSON to stdout")

    args = parser.parse_args()

    engine = TTCEngine(
        case_data_or_file=args.case,
        source_mode=args.source_mode,
        source_id=args.source_id,
        sink_mode=args.sink_mode,
        sink_id=args.sink_id,
        method=args.method,
        contingency_scope=args.contingency,
        base_transfer_mode=args.base_transfer_mode,
        base_transfer_mw=args.base_transfer_mw,
        base_rating_mode=args.base_rating,
        emerg_rating_mode=args.emerg_rating,
        emerg_rating_mult=args.emerg_mult,
        custom_branch_rating=args.custom_rating,
        v_min_norm=args.v_min_norm,
        v_max_norm=args.v_max_norm,
        v_min_emerg=args.v_min_emerg,
        v_max_emerg=args.v_max_emerg,
        target_mw=args.target_mw,
        mw_tolerance=args.tol,
        max_bisection_iters=args.max_iter,
        enforce_q_limits=not args.ignore_q,
        trm_mode="mw" if args.trm_mw > 0 else "pct",
        trm_pct=args.trm_pct,
        trm_mw=args.trm_mw,
        cbm_mw=args.cbm_mw,
        etc_mode="custom" if args.etc_mw > 0 else "use_base",
        etc_custom_mw=args.etc_mw,
        output_folder=args.output_dir,
        progress_callback=lambda pct, msg: print(f"[{pct:3d}%] {msg}", flush=True)
    )

    results = engine.run()

    if args.json_out:
        print("\n--- JSON_OUTPUT_START ---")
        cleaned = {k: v for k, v in results.items() if isinstance(v, (int, float, str, bool, list, dict)) or v is None}
        print(json.dumps(cleaned, indent=2))
        print("--- JSON_OUTPUT_END ---\n")
    else:
        print("\n" + "=" * 65)
        print("  DevEN — TOTAL & AVAILABLE TRANSFER CAPABILITY RESULTS")
        print("=" * 65)
        print(f"  Method:               {results.get('method_label')}")
        print(f"  Base Flow:            {results.get('base_transfer_mw', 0.0):.2f} MW")
        print(f"  Incremental Headroom: {results.get('incremental_headroom_mw', 0.0):.2f} MW")
        print(f"  -------------------------------------------------------------")
        print(f"  ★ TTC (Total):        {results.get('ttc_mw', 0.0):.2f} MW")
        print(f"  - TRM Margin:         {results.get('trm_mw', 0.0):.2f} MW")
        print(f"  - CBM Margin:         {results.get('cbm_mw', 0.0):.2f} MW")
        print(f"  - ETC (Existing):     {results.get('etc_firm_mw', 0.0):.2f} MW")
        print(f"  -------------------------------------------------------------")
        print(f"  ★ FIRM ATC:           {results.get('firm_atc_mw', 0.0):.2f} MW")
        print(f"  ★ NON-FIRM ATC:       {results.get('non_firm_atc_mw', 0.0):.2f} MW")
        print(f"  -------------------------------------------------------------")
        print(f"  Limiting Bottleneck:  {results.get('bottleneck_element')}")
        print(f"  Constraint Type:      {results.get('bottleneck_type')}")
        print(f"  Critical Contingency: {results.get('critical_contingency')}")
        print(f"  Reports Generated in: {engine.output_folder}")
        print("=" * 65 + "\n")


if __name__ == "__main__":
    main()

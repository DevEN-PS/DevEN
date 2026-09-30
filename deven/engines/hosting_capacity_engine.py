# DevEN Path Bootstrapper
import sys
import os
import copy
import time
import math
import argparse
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
    from hosting_capacity_report_writer import HostingCapacityReportWriter
except ImportError:
    from utils.hosting_capacity_report_writer import HostingCapacityReportWriter

class HostingCapacityEngine:
    """
    DevEN N-1 Security-Constrained Hosting Capacity & Substation Injection Limit Analyzer.
    Uses Binary Search (Bisection) with 2-Tier Security Screening (N-0 Base + N-1 Contingencies).
    Supports multiple candidate buses, parallel-branch optimization, and incremental streaming audit reports.
    """

    def __init__(
        self,
        case_data_or_file,
        candidate_buses,
        target_mw=300.0,
        min_mw=0.0,
        mw_tolerance=1.0,
        max_bisection_iters=20,
        power_factor=1.0,
        q_mode="pf",  # "pf" or "v_set"
        v_set=1.0,
        sink_mode="slack",  # "slack", "pro_rata_gen", "pro_rata_load"
        v_min_limit=0.95,
        v_max_limit=1.05,
        branch_loading_limit=100.0,
        monitored_contingency_branches="substation",
        k_hops=4,
        monitor_scope="substation",
        monitor_hops=4,
        parallel_ckt_optimization=True,
        ignore_q_limits=False,
        industry_std_pv=True,
        lfa_tol=1e-6,
        lfa_max_iter=25,
        check_base_n1=True,
        output_folder=None,
        progress_callback=None
    ):
        if isinstance(case_data_or_file, str):
            self.input_file = case_data_or_file
            self.case_name = os.path.splitext(os.path.basename(case_data_or_file))[0]
            if self.case_name.endswith('_converted'):
                self.case_name = self.case_name[:-10]
            self.full_data = InputReader.read_from_python(case_data_or_file)
        else:
            self.input_file = "in_memory_case.py"
            self.case_name = case_data_or_file.get('project_name', 'NETWORK_CASE')
            self.full_data = case_data_or_file

        # Candidate Buses Parsing
        if isinstance(candidate_buses, (int, str)):
            self.candidate_buses = [int(candidate_buses)] if str(candidate_buses).isdigit() else [candidate_buses]
        elif isinstance(candidate_buses, (list, tuple)):
            self.candidate_buses = [int(b) if str(b).isdigit() else b for b in candidate_buses]
        else:
            self.candidate_buses = []

        self.target_mw = float(target_mw)
        self.min_mw = float(min_mw)
        self.mw_tolerance = float(mw_tolerance)
        self.max_bisection_iters = int(max_bisection_iters)
        self.power_factor = float(power_factor)
        self.q_mode = q_mode
        self.v_set = float(v_set)
        self.sink_mode = sink_mode
        self.v_min_limit = float(v_min_limit)
        self.v_max_limit = float(v_max_limit)
        self.branch_loading_limit = float(branch_loading_limit)
        self.monitored_contingency_branches = monitored_contingency_branches
        self.k_hops = int(k_hops)
        self.monitor_scope = str(monitor_scope).lower()
        self.monitor_hops = int(monitor_hops)
        self.parallel_ckt_optimization = parallel_ckt_optimization
        self.ignore_q_limits = bool(ignore_q_limits)
        self.industry_std_pv = bool(industry_std_pv)
        self.check_base_n1 = bool(check_base_n1)
        self.lfa_tol = float(lfa_tol)
        self.lfa_max_iter = int(lfa_max_iter)

        # Output folder
        if not output_folder:
            base_dir = os.path.dirname(self.input_file) if os.path.exists(self.input_file) else os.getcwd()
            self.output_folder = os.path.join(base_dir, f"{self.case_name}_HOSTING_CAPACITY")
        else:
            self.output_folder = output_folder

        self.progress_callback = progress_callback
        self.report_writer = HostingCapacityReportWriter(
            self.output_folder, self.case_name,
            v_min_limit=self.v_min_limit,
            v_max_limit=self.v_max_limit,
            branch_loading_limit=self.branch_loading_limit
        )

    def _notify(self, msg, pct=0.0):
        if self.progress_callback:
            try:
                self.progress_callback(msg, pct)
            except Exception:
                pass
        print(msg)

    def _solve_power_flow(self, case_dict, warm_start=None):
        """
        Solves full AC Load Flow using DevEN's robust solver.
        Returns: (converged, bus_results, branch_results, total_gen, total_load, total_loss)
        """
        try:
            from power_flow_engine import PowerFlowEngine
        except ImportError:
            from engines.power_flow_engine import PowerFlowEngine
        data_copy = copy.deepcopy(case_dict)

        # If warm_start voltages provided, update bus initial voltages
        if warm_start:
            for b_num, b_res in warm_start.items():
                if b_num in data_copy.get('buses', {}):
                    data_copy['buses'][b_num]['V_init'] = b_res.get('V_mag', 1.0)
                    data_copy['buses'][b_num]['angle_init'] = b_res.get('V_ang_deg', 0.0)

        bus_data_engine, branch_data_engine, full_data_engine = InputReader.convert_to_engine_format(data_copy)

        engine = PowerFlowEngine(baseMVA=data_copy.get('base_mva', 100.0))
        engine.initialize(
            bus_data_engine, branch_data_engine, full_data=data_copy,
            solver_method='andes_nr', tol=self.lfa_tol, max_iter=self.lfa_max_iter,
            ignore_q_tol=self.ignore_q_limits,
            industry_std_pv=self.industry_std_pv, v_init_mode='flat' if not warm_start else 'initial'
        )
        samples, valid_count = engine.run_batch(n_samples=1, variation_strength=0.0)
        converged = (valid_count > 0 and len(samples) > 0 and bool(samples[0].get('converged', False)))
        if not converged:
            return False, {}, {}, 0.0, 0.0, 0.0

        # Extract bidirectional flows and losses with standard ReportWriter
        rep_writer = ReportWriter(engine, data_copy, samples, 0.0)

        buses = data_copy.get('buses', {})
        bus_res = {}
        for b_num in buses.keys():
            idx = engine.bus_index_map.get(b_num, 0)
            vm = rep_writer._safe_get_v(idx) if hasattr(rep_writer, '_safe_get_v') else float(rep_writer.avg_V[idx])
            va = rep_writer._safe_get_va(idx) if hasattr(rep_writer, '_safe_get_va') else float(rep_writer.avg_Va[idx])
            bus_res[b_num] = {'V_mag': float(vm), 'V_ang_deg': float(va)}

        branch_res = {}
        tot_loss = 0.0
        # Lines
        for l_num, line in data_copy.get('lines', {}).items():
            st = rep_writer._get_line_stats(l_num, line)
            pf = float(st.get('avg_P_fwd', 0.0))
            qf = float(st.get('avg_Q_fwd', 0.0))
            pr = float(st.get('avg_P_rev', 0.0))
            qr = float(st.get('avg_Q_rev', 0.0))
            sf = math.sqrt(pf**2 + qf**2)
            sr = math.sqrt(pr**2 + qr**2)
            s_max = max(sf, sr)
            rate = float(line.get('rateA', 0.0) or line.get('rating', 0.0) or 0.0)
            loading = (s_max / rate * 100.0) if (rate > 0.0 and rate < 9000.0) else 0.0
            loss = float(st.get('avg_loss', 0.0))
            tot_loss += loss
            branch_res[f"Line_{l_num}"] = {
                'type': 'line', 'id': l_num, 'name': line.get('name', f'Line_{l_num}'),
                'from_bus': line.get('from_bus', 0), 'to_bus': line.get('to_bus', 0),
                'P_MW': pf, 'Q_MVar': qf, 'S_MVA': s_max, 'flow_mva': s_max, 'Loss_MW': loss,
                'Loading_Pct': loading, 'rateA': rate, 'RateA': rate, 'status': line.get('status', 1)
            }

        # Transformers
        for x_num, xfmr in data_copy.get('transformers', {}).items():
            st = rep_writer._get_xfmr_stats(x_num, xfmr)
            pf = float(st.get('avg_P_fwd', 0.0))
            qf = float(st.get('avg_Q_fwd', 0.0))
            pr = float(st.get('avg_P_rev', 0.0))
            qr = float(st.get('avg_Q_rev', 0.0))
            sf = math.sqrt(pf**2 + qf**2)
            sr = math.sqrt(pr**2 + qr**2)
            s_max = max(sf, sr)
            rate = float(xfmr.get('rateA', 0.0) or xfmr.get('rating', 0.0) or 0.0)
            loading = (s_max / rate * 100.0) if (rate > 0.0 and rate < 9000.0) else 0.0
            loss = float(st.get('avg_loss', 0.0))
            tot_loss += loss
            branch_res[f"Xfmr_{x_num}"] = {
                'type': 'transformer', 'id': x_num, 'name': xfmr.get('name', f'Xfmr_{x_num}'),
                'from_bus': xfmr.get('from_bus', 0), 'to_bus': xfmr.get('to_bus', 0),
                'P_MW': pf, 'Q_MVar': qf, 'S_MVA': s_max, 'flow_mva': s_max, 'Loss_MW': loss,
                'Loading_Pct': loading, 'rateA': rate, 'RateA': rate, 'status': xfmr.get('status', 1)
            }

        tot_gen = 0.0
        for gid, gen in data_copy.get('generators', {}).items():
            if gen.get('status', 1) == 1:
                op, oq = rep_writer.get_generator_outputs(gid, gen)
                tot_gen += float(op)

        tot_load = 0.0
        for lid, load in data_copy.get('loads', {}).items():
            if load.get('status', 1) == 1:
                tot_load += float(load.get('P_demand', 0.0))

        return True, bus_res, branch_res, tot_gen, tot_load, tot_loss

    def _check_grid_security(self, bus_results, branch_results, monitored_branch_keys=None, monitored_bus_ids=None, branch_hop_map=None, bus_hop_map=None):
        """
        Checks thermal loading and voltage limits strictly on monitored elements.
        Returns:
            pass_bool (bool),
            max_loading (float),
            max_loading_branch (str),
            v_min (float),
            v_min_bus (int/str),
            v_max (float),
            v_max_bus (int/str),
            fail_reason (str),
            overload_list (list of dicts),
            voltage_viol_list (list of dicts)
        """
        v_min = 999.0
        v_min_bus = None
        v_max = -999.0
        v_max_bus = None
        voltage_viol_list = []

        for b_num, b_res in bus_results.items():
            if monitored_bus_ids is not None:
                if b_num not in monitored_bus_ids and str(b_num) not in monitored_bus_ids:
                    continue

            vm = b_res.get('V_mag', 1.0)
            b_name = b_res.get('name', f"Bus_{b_num}")
            b_kv = float(b_res.get('base_kV', 0.0))

            if vm < v_min:
                v_min = vm
                v_min_bus = b_num
            if vm > v_max:
                v_max = vm
                v_max_bus = b_num

            h = 0
            if bus_hop_map:
                h = bus_hop_map.get(b_num, bus_hop_map.get(str(b_num), 0))

            if vm < self.v_min_limit:
                voltage_viol_list.append({
                    'bus': b_num, 'name': b_name, 'base_kV': b_kv,
                    'v_mag': vm, 'type': 'Undervoltage', 'limit': self.v_min_limit,
                    'dev_pu': self.v_min_limit - vm, 'hop': h
                })
            elif vm > self.v_max_limit:
                voltage_viol_list.append({
                    'bus': b_num, 'name': b_name, 'base_kV': b_kv,
                    'v_mag': vm, 'type': 'Overvoltage', 'limit': self.v_max_limit,
                    'dev_pu': vm - self.v_max_limit, 'hop': h
                })

        # Sort voltage violations by largest deviation descending
        voltage_viol_list.sort(key=lambda x: x['dev_pu'], reverse=True)

        max_loading = 0.0
        max_loading_branch = "N/A"
        overload_list = []

        for br_key, br in branch_results.items():
            if br.get('status', 1) == 0:
                continue

            if monitored_branch_keys is not None:
                is_monitored = False
                key_variants = [
                    br_key, str(br_key),
                    f"Line_{br.get('id', br_key)}", f"Xfmr_{br.get('id', br_key)}",
                    f"Line_{br.get('line_num', '')}", f"Xfmr_{br.get('xfmr_num', '')}",
                    br.get('name', ''),
                    f"Line_{br.get('from_bus')}_{br.get('to_bus')}",
                    f"Xfmr_{br.get('from_bus')}_{br.get('to_bus')}"
                ]
                for kv in key_variants:
                    if kv and (kv in monitored_branch_keys or (str(kv).isdigit() and int(kv) in monitored_branch_keys)):
                        is_monitored = True
                        break
                if not is_monitored:
                    continue

            ld = br.get('Loading_Pct', 0.0)
            if ld > max_loading:
                max_loading = ld
                max_loading_branch = f"{br.get('name', br_key)} ({br.get('from_bus')}->{br.get('to_bus')})"

            if ld > self.branch_loading_limit:
                h = 0
                if branch_hop_map:
                    h = branch_hop_map.get(br_key, branch_hop_map.get(str(br.get('id', '')), branch_hop_map.get(br.get('name', ''), 0)))
                    if h == 0 and 'from_bus' in br and 'to_bus' in br:
                        pair = f"{br['from_bus']}_{br['to_bus']}"
                        h = branch_hop_map.get(pair, branch_hop_map.get(f"{br['to_bus']}_{br['from_bus']}", 0))

                overload_list.append({
                    'id': br_key,
                    'name': br.get('name', br_key),
                    'from_bus': br.get('from_bus'),
                    'to_bus': br.get('to_bus'),
                    'loading_pct': ld,
                    'flow_mva': br.get('flow_mva', br.get('S_MVA', br.get('MVA_From', 0.0))),
                    'rating_mva': br.get('rateA', br.get('RateA', br.get('rating', 0.0))),
                    'hop': h
                })

        # Sort overloads by loading descending
        overload_list.sort(key=lambda x: x['loading_pct'], reverse=True)

        thermal_violation = len(overload_list) > 0
        v_violation = len(voltage_viol_list) > 0

        fail_msg = "OK (Within Limits)"
        if thermal_violation and v_violation:
            worst_ov = overload_list[0]
            worst_v = voltage_viol_list[0]
            fail_msg = f"Thermal Overload ({worst_ov['loading_pct']:.2f}% on {worst_ov['name']}) & {worst_v['type']} ({worst_v['v_mag']:.4f} pu at Bus {worst_v['bus']})"
        elif thermal_violation:
            worst_ov = overload_list[0]
            fail_msg = f"Thermal Overload ({worst_ov['loading_pct']:.2f}% > {self.branch_loading_limit:.1f}%) on {worst_ov['name']}"
        elif v_violation:
            worst_v = voltage_viol_list[0]
            fail_msg = f"{worst_v['type']} ({worst_v['v_mag']:.4f} pu) at Bus {worst_v['bus']}"

        pass_bool = not (thermal_violation or v_violation)
        return pass_bool, max_loading, max_loading_branch, v_min, v_min_bus, v_max, v_max_bus, fail_msg, overload_list, voltage_viol_list

    def _get_monitored_contingencies(self, candidate_bus):
        """
        Determines the list of branch contingency outages to test, respecting user check/uncheck selections
        and multi-hop double-circuit exploration.
        """
        lines = self.full_data.get('lines', {})
        xfmrs = self.full_data.get('transformers', {})
        contingency_list = []

        if isinstance(self.monitored_contingency_branches, dict):
            # Check if nested by candidate bus {bus_id: {branch_id: bool}} or {bus_id: [branch_id, ...]}
            bus_key = candidate_bus
            if bus_key not in self.monitored_contingency_branches and str(bus_key) in self.monitored_contingency_branches:
                bus_key = str(bus_key)
            elif bus_key not in self.monitored_contingency_branches and str(bus_key).isdigit() and int(bus_key) in self.monitored_contingency_branches:
                bus_key = int(bus_key)

            if bus_key in self.monitored_contingency_branches:
                bus_spec = self.monitored_contingency_branches[bus_key]
                if isinstance(bus_spec, dict):
                    for k, is_sel in bus_spec.items():
                        if is_sel: contingency_list.append(k)
                elif isinstance(bus_spec, (list, tuple, set)):
                    contingency_list = list(bus_spec)
            else:
                # Flat map {branch_id: bool}
                for k, is_sel in self.monitored_contingency_branches.items():
                    if is_sel:
                        contingency_list.append(k)

        elif isinstance(self.monitored_contingency_branches, (list, set, tuple)):
            # User specified list of branches
            for item in self.monitored_contingency_branches:
                s_item = str(item)
                if s_item.startswith("Line_") or s_item.startswith("Xfmr_") or s_item.startswith("3WXfmr_"):
                    contingency_list.append(s_item)
                elif s_item in lines or (s_item.isdigit() and int(s_item) in lines):
                    contingency_list.append(f"Line_{s_item}")
                elif s_item in xfmrs or (s_item.isdigit() and int(s_item) in xfmrs):
                    contingency_list.append(f"Xfmr_{s_item}")

        elif self.monitored_contingency_branches == "substation" or isinstance(self.monitored_contingency_branches, int):
            try:
                from contingency_branch_finder import find_substation_branches_by_hops
            except ImportError:
                from utils.contingency_branch_finder import find_substation_branches_by_hops
            hop_branches = find_substation_branches_by_hops(self.full_data, candidate_bus, max_hops=self.k_hops)
            contingency_list = [br['id'] for br in hop_branches if br.get('is_multi_circuit', False)]
            if not contingency_list:
                self._notify(f"   ℹ️ Notice: No parallel double/multi-circuit branches exist within {self.k_hops} hops of Bus {candidate_bus}.")

        else:
            # "all" branches
            for lid in sorted(lines.keys(), key=lambda x: int(x) if str(x).isdigit() else str(x)):
                contingency_list.append(f"Line_{lid}")
            for xid in sorted(xfmrs.keys(), key=lambda x: int(x) if str(x).isdigit() else str(x)):
                contingency_list.append(f"Xfmr_{xid}")

        return contingency_list

    def _inject_power(self, case_dict, candidate_bus, p_inject_mw):
        """
        Injects p_inject_mw at candidate_bus as a candidate generator.
        """
        case_mod = copy.deepcopy(case_dict)
        gens = case_mod.setdefault('generators', {})

        # Calculate reactive power injection based on power factor
        if self.power_factor >= 1.0 or self.power_factor <= 0.0:
            q_inject_mvar = 0.0
        else:
            phi = math.acos(max(-1.0, min(1.0, self.power_factor)))
            q_inject_mvar = p_inject_mw * math.tan(phi)

        existing_g_ids = [int(k) for k in gens.keys() if str(k).isdigit()]
        cand_gen_id = max(existing_g_ids) + 100 if existing_g_ids else 9999

        bus_info = case_mod.get('buses', {}).get(candidate_bus, {})
        base_kv = float(bus_info.get('base_kV', 132.0))

        gens[cand_gen_id] = {
            'gen_num': cand_gen_id,
            'name': f"Candidate_Injection_Bus_{candidate_bus}",
            'bus': candidate_bus,
            'P_out': float(p_inject_mw),
            'Q_out': float(q_inject_mvar),
            'V_set': self.v_set,
            'Qmin': -9999.0,
            'Qmax': 9999.0,
            'status': 1,
            'area': bus_info.get('area', 1),
            'zone': bus_info.get('zone', 1),
            'owner': bus_info.get('owner', 1)
        }

        # If candidate bus was a PQ load bus, convert to PV generator bus if in v_set mode
        if self.q_mode == 'v_set' and candidate_bus in case_mod.get('buses', {}):
            if case_mod['buses'][candidate_bus].get('type') == 1:
                case_mod['buses'][candidate_bus]['type'] = 2

        # In pro_rata_gen sink mode, scale down other generators
        if self.sink_mode == 'pro_rata_gen' and p_inject_mw > 0:
            other_gens = [g for gid, g in gens.items() if gid != cand_gen_id and g.get('status', 1) == 1]
            tot_p_other = sum(g.get('P_out', 0.0) for g in other_gens)
            if tot_p_other > p_inject_mw:
                scale_factor = (tot_p_other - p_inject_mw) / tot_p_other
                for g in other_gens:
                    g['P_out'] = g.get('P_out', 0.0) * scale_factor

        return case_mod

    def _evaluate_security_step(
        self,
        cand_bus,
        p_test,
        contingencies_to_test,
        monitored_branch_keys=None,
        monitored_bus_ids=None,
        branch_hop_map=None,
        bus_hop_map=None,
        step_label="Iter"
    ):
        """
        Runs 2-Tier Security Assessment (N-0 Base + N-1 Contingencies) for a given candidate bus and P_test MW.
        Returns:
            step_passed (bool),
            n0_result (dict),
            n1_results (list),
            binding_msg (str),
            critical_outage (str),
            n0_bus_res (dict),
            n0_br_res (dict)
        """
        # Prepare case: if 0 MW, evaluate the base grid directly without perturbation
        if p_test <= 1e-6:
            case_injected = self.full_data
        else:
            case_injected = self._inject_power(self.full_data, cand_bus, p_test)

        # ── TIER 1: N-0 Base Case Check at P_test ──
        n0_conv, n0_bus_res, n0_br_res, n0_g, n0_l, n0_loss = self._solve_power_flow(case_injected)

        n0_pass = False
        n0_fail_reason = ""
        n0_max_ld = 0.0
        n0_crit_br = "N/A"
        n0_vmin, n0_vmax = 1.0, 1.0
        n0_vmin_bus, n0_vmax_bus = cand_bus, cand_bus
        n0_overloads = []
        n0_volt_viols = []

        if not n0_conv:
            n0_fail_reason = "Power Flow Diverged (Voltage Collapse)"
        else:
            n0_pass, n0_max_ld, n0_crit_br, n0_vmin, n0_vmin_bus, n0_vmax, n0_vmax_bus, n0_fail_reason, n0_overloads, n0_volt_viols = self._check_grid_security(
                n0_bus_res, n0_br_res, monitored_branch_keys, monitored_bus_ids, branch_hop_map, bus_hop_map
            )

        n0_result = {
            'pass': n0_pass,
            'converged': n0_conv,
            'max_loading_pct': n0_max_ld,
            'max_loading_branch': n0_crit_br,
            'v_min_pu': n0_vmin,
            'v_min_bus': n0_vmin_bus,
            'v_max_pu': n0_vmax,
            'v_max_bus': n0_vmax_bus,
            'fail_reason': n0_fail_reason,
            'overloads': n0_overloads,
            'voltage_violations': n0_volt_viols
        }

        if not n0_pass:
            self._notify(f"      ├─ N-0 Base Check: ❌ FAIL | Max Loading: {n0_max_ld:.2f}% ({n0_crit_br}) | V_min: {n0_vmin:.4f} pu | V_max: {n0_vmax:.4f} pu")
            if n0_overloads:
                self._notify(f"      │  🔥 Thermal Overloads ({len(n0_overloads)} monitored branches > {self.branch_loading_limit:.1f}%):")
                for ov in n0_overloads[:6]:
                    hop_tag = f"[Hop {ov['hop']}] " if ov.get('hop') else ""
                    self._notify(f"      │     • {hop_tag}{ov['name']} ({ov['from_bus']}->{ov['to_bus']}): {ov['loading_pct']:.2f}% (Flow: {ov['flow_mva']:.1f} MVA / Rating: {ov['rating_mva']:.1f} MVA)")
                if len(n0_overloads) > 6:
                    self._notify(f"      │     ... and {len(n0_overloads) - 6} more overloaded branches")
            if n0_volt_viols:
                self._notify(f"      │  ⚡ Voltage Violations ({len(n0_volt_viols)} monitored buses outside [{self.v_min_limit:.2f}, {self.v_max_limit:.2f}] pu):")
                for vv in n0_volt_viols[:6]:
                    hop_tag = f"[Hop {vv['hop']}] " if vv.get('hop') else ""
                    self._notify(f"      │     • {hop_tag}Bus {vv['bus']} ({vv['name']}): {vv['v_mag']:.4f} pu ({vv['type']} limit: {vv['limit']:.2f} pu)")
                if len(n0_volt_viols) > 6:
                    self._notify(f"      │     ... and {len(n0_volt_viols) - 6} more voltage violations")
            self._notify(f"      └─ N-1 Contingencies: SKIPPED (N-0 Base Check Failed: {n0_fail_reason})")
        else:
            self._notify(f"      ├─ N-0 Base Check: ✅ PASS | Max Loading: {n0_max_ld:.2f}% ({n0_crit_br}) | V_min: {n0_vmin:.4f} pu | V_max: {n0_vmax:.4f} pu")

        # ── TIER 2: N-1 Contingencies Check (if N-0 passed) ──
        n1_results = []
        all_n1_passed = True
        first_n1_fail_msg = ""
        first_n1_fail_outage = ""
        first_n1_overloads = []
        first_n1_volt_viols = []

        if n0_pass and contingencies_to_test:
            for cont_key in contingencies_to_test:
                case_n1 = copy.deepcopy(case_injected)
                outage_name = cont_key
                if cont_key.startswith("Line_"):
                    lid = cont_key[5:]
                    if lid in case_n1.get('lines', {}):
                        case_n1['lines'][lid]['status'] = 0
                        outage_name = f"Line {lid} ({case_n1['lines'][lid].get('name', '')})"
                    elif lid.isdigit() and int(lid) in case_n1.get('lines', {}):
                        case_n1['lines'][int(lid)]['status'] = 0
                        outage_name = f"Line {lid} ({case_n1['lines'][int(lid)].get('name', '')})"
                elif cont_key.startswith("Xfmr_"):
                    xid = cont_key[5:]
                    if xid in case_n1.get('transformers', {}):
                        case_n1['transformers'][xid]['status'] = 0
                        outage_name = f"Xfmr {xid} ({case_n1['transformers'][xid].get('name', '')})"
                    elif xid.isdigit() and int(xid) in case_n1.get('transformers', {}):
                        case_n1['transformers'][int(xid)]['status'] = 0
                        outage_name = f"Xfmr {xid} ({case_n1['transformers'][int(xid)].get('name', '')})"

                n1_conv, n1_bus_res, n1_br_res, _, _, _ = self._solve_power_flow(case_n1, warm_start=n0_bus_res)

                if not n1_conv:
                    n1_pass = False
                    n1_reason = "N-1 Voltage Collapse (Diverged)"
                    n1_ld, n1_br = 999.0, outage_name
                    n1_vmin, n1_vmax, n1_vmb = 0.0, 0.0, 0
                    n1_ov, n1_vv = [], []
                else:
                    n1_pass, n1_ld, n1_br, n1_vmin, n1_vmb, n1_vmax, _, n1_reason, n1_ov, n1_vv = self._check_grid_security(
                        n1_bus_res, n1_br_res, monitored_branch_keys, monitored_bus_ids, branch_hop_map, bus_hop_map
                    )

                out_hop = branch_hop_map.get(cont_key, 1) if branch_hop_map else 0
                n1_ld_hop = 0
                if branch_hop_map and n1_br:
                    n1_ld_hop = branch_hop_map.get(n1_br, 0)
                    if n1_ld_hop == 0 and n1_ov:
                        n1_ld_hop = n1_ov[0].get('hop', 0)
                n1_vm_hop = bus_hop_map.get(n1_vmb, bus_hop_map.get(str(n1_vmb), 0)) if bus_hop_map else 0

                n1_results.append({
                    'outage_key': cont_key,
                    'outage_name': outage_name,
                    'outage_hop': out_hop,
                    'pass': n1_pass,
                    'max_loading_pct': n1_ld,
                    'max_loading_branch': n1_br,
                    'max_loading_hop': n1_ld_hop,
                    'v_min_pu': n1_vmin,
                    'v_min_bus': n1_vmb,
                    'v_min_hop': n1_vm_hop,
                    'fail_reason': n1_reason,
                    'overloads': n1_ov,
                    'voltage_violations': n1_vv
                })

                if not n1_pass and all_n1_passed:
                    all_n1_passed = False
                    first_n1_fail_msg = n1_reason
                    first_n1_fail_outage = outage_name
                    first_n1_overloads = n1_ov
                    first_n1_volt_viols = n1_vv

            failed_n1_count = sum(1 for r in n1_results if not r['pass'])
            if all_n1_passed:
                self._notify(f"      └─ N-1 Contingencies: ✅ ALL {len(n1_results)} OUTAGES PASSED (Zero Violations)")
            else:
                self._notify(f"      └─ N-1 Contingencies: ❌ {failed_n1_count}/{len(n1_results)} OUTAGES FAILED | Critical: {first_n1_fail_outage}")
                if first_n1_overloads:
                    self._notify(f"         🔥 Post-Contingency Overloads under {first_n1_fail_outage}:")
                    for ov in first_n1_overloads[:4]:
                        hop_tag = f"[Hop {ov['hop']}] " if ov.get('hop') else ""
                        self._notify(f"            • {hop_tag}{ov['name']} ({ov['from_bus']}->{ov['to_bus']}): {ov['loading_pct']:.2f}% (Flow: {ov['flow_mva']:.1f} MVA / Rating: {ov['rating_mva']:.1f} MVA)")
                if first_n1_volt_viols:
                    self._notify(f"         ⚡ Post-Contingency Voltage Violations under {first_n1_fail_outage}:")
                    for vv in first_n1_volt_viols[:4]:
                        hop_tag = f"[Hop {vv['hop']}] " if vv.get('hop') else ""
                        self._notify(f"            • {hop_tag}Bus {vv['bus']} ({vv['name']}): {vv['v_mag']:.4f} pu ({vv['type']} limit: {vv['limit']:.2f} pu)")

        step_passed = n0_pass and all_n1_passed
        if not n0_pass:
            binding_msg = f"N-0: {n0_fail_reason}"
            critical_outage = "N-0 (All in Service)"
        elif not all_n1_passed:
            binding_msg = f"N-1: {first_n1_fail_msg}"
            critical_outage = first_n1_fail_outage
        else:
            binding_msg = "None (Limits Respected)"
            critical_outage = "None"

        return step_passed, n0_result, n1_results, binding_msg, critical_outage, n0_bus_res, n0_br_res

    def run(self):
        """
        Executes full N-1 security-constrained hosting capacity assessment across all candidate buses.
        """
        start_time = time.time()
        self._notify("\n" + "=" * 80)
        self._notify("⚡ DevEN N-1 SECURITY-CONSTRAINED HOSTING CAPACITY ANALYZER")
        self._notify("=" * 80)
        self._notify(f"📁 Case: {self.case_name}")
        self._notify(f"🎯 Target Injection Capacity: {self.target_mw:.1f} MW (Tolerance: {self.mw_tolerance:.1f} MW)")
        self._notify(f"🏢 Candidate Buses to Evaluate: {self.candidate_buses}")
        self._notify("=" * 80 + "\n")

        # 1. Evaluate Pre-Injection Base Case (0 MW)
        self._notify("⏳ Evaluating Pre-Injection Base Case Grid (0 MW)...", 0.05)
        conv, base_bus_res, base_br_res, tot_g, tot_l, tot_loss = self._solve_power_flow(self.full_data)
        if not conv:
            self._notify("❌ CRITICAL: Initial Base Case Grid DIVERGED. Cannot proceed with hosting study.")
            return {'error': 'Base Case Diverged', 'results': []}

        pass_sec, max_ld, max_br, v_min, v_min_bus, v_max, v_max_bus, fail_msg, base_ov, base_vv = self._check_grid_security(base_bus_res, base_br_res)
        base_case_info = {
            'converged': conv,
            'total_gen_mw': tot_g,
            'total_gen_mvar': 0.0,
            'total_load_mw': tot_l,
            'total_load_mvar': 0.0,
            'total_loss_mw': tot_loss,
            'loss_pct': (tot_loss / max(1e-6, tot_g) * 100.0) if tot_g > 0 else 0.0,
            'max_loading_pct': max_ld,
            'max_loading_branch': max_br,
            'v_min_pu': v_min,
            'v_min_bus': v_min_bus,
            'v_max_pu': v_max,
            'v_max_bus': v_max_bus
        }
        self.report_writer.log_base_case(base_case_info)
        if pass_sec:
            self._notify(f"✅ Base Case Healthy | Load: {tot_l:.1f} MW | Losses: {tot_loss:.2f} MW | Max Loading: {max_ld:.1f}% ({max_br}) | V_min: {v_min:.4f} pu")
        else:
            self._notify(f"ℹ️ Base Case Solved with {len(base_ov)} pre-existing overloads & {len(base_vv)} voltage deviations across database.")

        all_buses_summaries = []
        tot_candidates = len(self.candidate_buses)

        for b_idx, cand_bus in enumerate(self.candidate_buses, 1):
            bus_info = self.full_data.get('buses', {}).get(cand_bus, {})
            bus_name = bus_info.get('name', f"Bus_{cand_bus}")
            base_kv = float(bus_info.get('base_kV', 132.0))

            self._notify(f"\n[{b_idx}/{tot_candidates}] 🔍 Starting Assessment for Bus {cand_bus} ({bus_name}) - {base_kv:.1f} kV...")
            self.report_writer.log_bus_header(cand_bus, bus_name, base_kv, self.target_mw)

            # Get monitored N-1 contingencies
            contingencies_to_test = self._get_monitored_contingencies(cand_bus)

            if self.monitor_scope == "substation":
                try:
                    from contingency_branch_finder import find_substation_branches_by_hops
                except ImportError:
                    from utils.contingency_branch_finder import find_substation_branches_by_hops
                hop_branches = find_substation_branches_by_hops(self.full_data, [cand_bus], max_hops=self.monitor_hops)
                monitored_branch_keys = set()
                monitored_bus_ids = {cand_bus, str(cand_bus)}
                branch_hop_map = {}
                bus_hop_map = {cand_bus: 0, str(cand_bus): 0}
                for br in hop_branches:
                    h = br.get('hop', 1)
                    bid = br['id']
                    monitored_branch_keys.add(bid)
                    branch_hop_map[bid] = h
                    branch_hop_map[str(br.get('raw_id', ''))] = h
                    if 'name' in br:
                        monitored_branch_keys.add(br['name'])
                        branch_hop_map[br['name']] = h
                    if 'pair_key' in br:
                        monitored_branch_keys.add(br['pair_key'])
                        branch_hop_map[br['pair_key']] = h
                    fb, tb = br['from_bus'], br['to_bus']
                    monitored_bus_ids.add(fb)
                    monitored_bus_ids.add(str(fb))
                    monitored_bus_ids.add(tb)
                    monitored_bus_ids.add(str(tb))
                    if fb not in bus_hop_map: bus_hop_map[fb] = h
                    if str(fb) not in bus_hop_map: bus_hop_map[str(fb)] = h
                    if tb not in bus_hop_map: bus_hop_map[tb] = h
                    if str(tb) not in bus_hop_map: bus_hop_map[str(tb)] = h

                for cont_k in contingencies_to_test:
                    monitored_branch_keys.add(cont_k)
                    if cont_k not in branch_hop_map:
                        branch_hop_map[cont_k] = 1
                self._notify(f"   • Monitored Zone Scope: {len(monitored_branch_keys)} branches & {len(monitored_bus_ids)} buses within {self.monitor_hops} hops")
            else:
                monitored_branch_keys = None
                monitored_bus_ids = None
                branch_hop_map = None
                bus_hop_map = None
                self._notify(f"   • Monitored Zone Scope: ENTIRE DATABASE ({len(self.full_data.get('lines', {})) + len(self.full_data.get('transformers', {}))} branches, {len(self.full_data.get('buses', {}))} buses)")

            p_low = self.min_mw
            p_high = self.target_mw
            best_feasible_p = 0.0
            best_feasible_bus_res = base_bus_res
            best_feasible_br_res = base_br_res
            iter_count = 0

            binding_constraint = "None (Target MW Fully Feasible)"
            critical_n1_outage = "None"
            max_ld_at_best = max_ld
            base_0mw_pass = True

            # ── BASELINE 0 MW CHECK (if enabled) ──
            if self.check_base_n1:
                self._notify(f"   [Step 00] Baseline 0.00 MW Security Screening (N-0 & N-1 Contingencies)...")
                b0_passed, b0_n0_res, b0_n1_res, b0_bind_msg, b0_crit_out, b0_bus_res, b0_br_res = self._evaluate_security_step(
                    cand_bus, 0.0, contingencies_to_test,
                    monitored_branch_keys, monitored_bus_ids, branch_hop_map, bus_hop_map,
                    step_label="Step 00"
                )
                base_0mw_pass = b0_passed
                if b0_passed:
                    best_feasible_p = 0.0
                    best_feasible_bus_res = b0_bus_res
                    best_feasible_br_res = b0_br_res
                    max_ld_at_best = b0_n0_res['max_loading_pct']
                    verdict_0 = "FEASIBLE"
                    self._notify(f"      ✅ 0.00 MW Baseline PASSED all N-0 and N-1 criteria.")
                else:
                    verdict_0 = "REJECTED"
                    binding_constraint = b0_bind_msg
                    critical_n1_outage = b0_crit_out
                    self._notify(f"      ⚠️ 0.00 MW Baseline FAILED N-1 criteria: {b0_bind_msg}")
                    self._notify(f"      ℹ️ Proceeding with bisection search (injections may relieve pre-existing base bottlenecks)...")

                self.report_writer.log_iteration_step(
                    cand_bus, 0, 0.0, b0_n0_res, b0_n1_res, verdict_0, (p_low, p_high)
                )

            # First test: Try 100% Target MW
            p_test = p_high

            while iter_count < self.max_bisection_iters:
                iter_count += 1
                prog_pct = (b_idx - 1) / tot_candidates + (iter_count / (self.max_bisection_iters * tot_candidates))
                self._notify(f"   [Iter {iter_count:02d}] Testing P_test = {p_test:.2f} MW (Range: {p_low:.2f} to {p_high:.2f} MW)...", prog_pct)

                step_passed, n0_result, n1_results, bind_msg, crit_outage, n0_bus_res, n0_br_res = self._evaluate_security_step(
                    cand_bus, p_test, contingencies_to_test,
                    monitored_branch_keys, monitored_bus_ids, branch_hop_map, bus_hop_map,
                    step_label=f"Iter {iter_count:02d}"
                )

                if step_passed:
                    best_feasible_p = p_test
                    best_feasible_bus_res = n0_bus_res
                    best_feasible_br_res = n0_br_res
                    max_ld_at_best = n0_result['max_loading_pct']
                    p_low = p_test
                    verdict = "FEASIBLE"
                else:
                    p_high = p_test
                    verdict = "REJECTED"
                    binding_constraint = bind_msg
                    critical_n1_outage = crit_outage

                # Immediately log iteration to .invout and detailed CSV!
                self.report_writer.log_iteration_step(
                    cand_bus, iter_count, p_test, n0_result, n1_results, verdict, (p_low, p_high)
                )

                # Check convergence
                if (p_high - p_low) <= self.mw_tolerance:
                    self._notify(f"   🎯 Converged at {best_feasible_p:.2f} MW within tolerance ({self.mw_tolerance} MW) after {iter_count} iterations.")
                    break

                # Next Bisection Midpoint
                p_test = round((p_low + p_high) / 2.0, 3)

            # Bus Final Summary Record
            v_point = best_feasible_bus_res.get(cand_bus, {}).get('V_mag', 1.0)
            if best_feasible_p >= (self.target_mw - self.mw_tolerance):
                status_str = "FULLY_FEASIBLE"
                binding_constraint = "None (Target MW Fully Feasible)"
                critical_n1_outage = "None"
            elif best_feasible_p > 0:
                status_str = "PARTIALLY_FEASIBLE"
            else:
                if self.check_base_n1 and not base_0mw_pass:
                    status_str = "UNFEASIBLE (0 MW Base Bottleneck)"
                else:
                    status_str = "UNFEASIBLE"

            bus_summary = {
                'bus_id': cand_bus,
                'bus_name': bus_name,
                'base_kV': base_kv,
                'target_mw': self.target_mw,
                'max_feasible_mw': best_feasible_p,
                'status': status_str,
                'binding_constraint': binding_constraint,
                'critical_n1_outage': critical_n1_outage,
                'v_at_max_pu': v_point,
                'max_loading_pct': max_ld_at_best,
                'iterations_count': iter_count
            }
            all_buses_summaries.append(bus_summary)
            self.report_writer.log_bus_final_summary(bus_summary)

            self._notify(f"🏁 Bus {cand_bus} ({base_kv:.1f} kV) -> Max Feasible: {best_feasible_p:.2f} MW [{status_str}] (Constraint: {binding_constraint})")

        # Finalize Multi-Bus Master Executive Report
        total_time = time.time() - start_time
        self.report_writer.finalize_executive_report(all_buses_summaries, total_time)

        self._notify("\n" + "=" * 80)
        self._notify(" HOSTING CAPACITY ANALYSIS COMPLETE!")
        self._notify("=" * 80)
        self._notify(f"📁 Reports saved in: {self.output_folder}")
        self._notify(f"   • Master Audit Report:    {self.case_name}_HOSTING_CAPACITY_REPORT.invout")
        self._notify(f"   • Summary Comparison CSV: {self.case_name}_HOSTING_CAPACITY_SUMMARY.csv")
        self._notify(f"   • Detailed Step Log CSV:  {self.case_name}_HOSTING_CAPACITY_STEP_LOG.csv")
        self._notify(f"   • Python Results File:    {self.case_name}_HOSTING_CAPACITY_RESULTS.py")
        self._notify(f"⏱️ Elapsed Time: {total_time:.2f} seconds")
        self._notify("=" * 80 + "\n")

        return {
            'output_folder': self.output_folder,
            'summaries': all_buses_summaries,
            'elapsed_sec': total_time
        }


def main():
    # Support --hep typo alias as --help
    if "--hep" in sys.argv:
        sys.argv[sys.argv.index("--hep")] = "--help"

    cli_description = """
========================================================================================
⚡ DevEN N-1 Security-Constrained Hosting Capacity & Power Injection Analyzer (CLI)
========================================================================================
Evaluates maximum renewable / generator injection capacity across candidate substations
subject to N-0 continuous thermal/voltage limits and N-1 double-circuit contingency outages.

Features:
  • Bisection Search Engine with warm-started Newton-Raphson LFA power flow.
  • Multi-Hop Graph Traversal to isolate local evacuation corridors and double-circuits.
  • Itemized Violation Diagnostics: Displays [Hop N] tags for all overloads & voltages.
  • Headless execution: Runs independently without UI, generating .INVOUT & CSV reports.
"""

    cli_epilog = """
----------------------------------------------------------------------------------------
📋 PRACTICAL CLI USAGE EXAMPLES:
----------------------------------------------------------------------------------------
1. Single Bus Assessment (4 Hops Local Corridor, 300 MW Target):
   python run_hosting_capacity.py -i case.py -b 7 -t 300.0

2. Multi-Bus Assessment with Custom Voltage & Thermal Limits:
   python run_hosting_capacity.py -i case.db -b 7,13,18,21 -t 500.0 --v-min 0.90 --v-max 1.10 --loading-limit 100.0

3. Restrict Violation Scope to Local Substation (2 Hops away):
   python run_hosting_capacity.py -i case.py -b 3 --monitor-scope substation --monitor-hops 2

4. Full Grid Database Exhaustive N-1 Screen:
   python run_hosting_capacity.py -i case.py -b 7 --monitor-scope all --contingency all

5. Pro-Rata Generator Sinking (Dispatch Sunk Pro-Rata across Existing Generators):
   python run_hosting_capacity.py -i case.py -b 7 -t 250.0 --sink-mode pro_rata_gen

========================================================================================
"""

    parser = argparse.ArgumentParser(
        description=cli_description,
        epilog=cli_epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("-i", "--input", type=str, required=True, help="Input Python (.py) or SQLite (.db) case file path")
    parser.add_argument("-b", "--buses", type=str, required=True, help="Candidate injection bus IDs (comma-separated, e.g. 7 or 7,13,18)")
    parser.add_argument("-t", "--target-mw", type=float, default=300.0, help="Target generator injection capacity in MW (default: 300.0)")
    parser.add_argument("--min-mw", type=float, default=0.0, help="Minimum starting capacity in MW (default: 0.0)")
    parser.add_argument("--tol", type=float, default=1.0, help="Bisection search convergence tolerance in MW (default: 1.0)")
    parser.add_argument("--max-iter", type=int, default=20, help="Maximum bisection iterations per candidate bus (default: 20)")
    parser.add_argument("--pf", type=float, default=1.0, help="Injection power factor: 1.0=UPF, <1.0=Lagging/Leading (default: 1.0)")
    parser.add_argument("--v-set", type=float, default=1.0, help="Candidate generator voltage setpoint in pu (default: 1.0)")
    parser.add_argument("--sink-mode", type=str, default="slack", choices=["slack", "pro_rata_gen", "pro_rata_load"], help="Sink mode: 'slack' (System Slack bus), 'pro_rata_gen' (Spread across online gens), 'pro_rata_load' (Load tracking) (default: slack)")
    parser.add_argument("--v-min", type=float, default=0.95, help="Minimum allowable bus voltage limit in pu (default: 0.95)")
    parser.add_argument("--v-max", type=float, default=1.05, help="Maximum allowable bus voltage limit in pu (default: 1.05)")
    parser.add_argument("--loading-limit", type=float, default=100.0, help="Maximum allowable branch MVA loading limit in %% (default: 100.0)")
    parser.add_argument("--contingency", type=str, default="substation", help="N-1 Contingency selection: 'substation' (automated multi-circuit hops), 'all' (entire grid), or comma-separated branch list (default: substation)")
    parser.add_argument("--hops", type=int, default=4, help="Substation branch exploration hop distance for N-1 outages (default: 4)")
    parser.add_argument("--monitor-scope", type=str, default="substation", choices=["substation", "all"], help="Scope for monitoring thermal & voltage violations ('substation'=local corridor, 'all'=entire grid database) (default: substation)")
    parser.add_argument("--monitor-hops", type=int, default=4, help="Transmission hop distance from candidate bus monitored for overloads/voltages (default: 4)")
    parser.add_argument("--selection-file", type=str, default="", help="Optional path to custom JSON file with per-bus monitored branch mappings")
    parser.add_argument("--ignore-q", action="store_true", help="Ignore generator reactive power Q limits during power flow")
    parser.add_argument("--no-industry-pv", action="store_true", help="Disable industry standard PV bus conversion limits")
    parser.add_argument("--lfa-tol", type=float, default=1e-6, help="Newton-Raphson power flow solver tolerance (default: 1e-6)")
    parser.add_argument("--lfa-max-iter", type=int, default=25, help="Newton-Raphson maximum power flow solver iterations (default: 25)")
    parser.add_argument("--check-base-n1", action="store_true", default=True, help="Perform N-1 contingency check at 0 MW Base Case (default: True)")
    parser.add_argument("--no-check-base-n1", action="store_false", dest="check_base_n1", help="Disable N-1 contingency check at 0 MW Base Case (use legacy method)")
    parser.add_argument("-o", "--output", type=str, default="", help="Custom output folder path (defaults to <CaseName>_HOSTING_CAPACITY)")

    args = parser.parse_args()

    bus_list = [b.strip() for b in args.buses.split(",") if b.strip()]
    cand_buses = [int(b) if b.isdigit() else b for b in bus_list]

    cont_mode = args.contingency
    if args.selection_file and os.path.exists(args.selection_file):
        import json
        try:
            with open(args.selection_file, 'r', encoding='utf-8') as f:
                cont_mode = json.load(f)
        except Exception as e:
            print(f"Warning: Failed to load selection file: {e}")
    elif "," in cont_mode:
        cont_mode = [c.strip() for c in cont_mode.split(",") if c.strip()]

    engine = HostingCapacityEngine(
        case_data_or_file=args.input,
        candidate_buses=cand_buses,
        target_mw=args.target_mw,
        min_mw=args.min_mw,
        mw_tolerance=args.tol,
        max_bisection_iters=args.max_iter,
        power_factor=args.pf,
        v_set=args.v_set,
        sink_mode=args.sink_mode,
        v_min_limit=args.v_min,
        v_max_limit=args.v_max,
        branch_loading_limit=args.loading_limit,
        monitored_contingency_branches=cont_mode,
        k_hops=args.hops,
        monitor_scope=args.monitor_scope,
        monitor_hops=args.monitor_hops,
        ignore_q_limits=args.ignore_q,
        industry_std_pv=(not args.no_industry_pv),
        lfa_tol=args.lfa_tol,
        lfa_max_iter=args.lfa_max_iter,
        check_base_n1=args.check_base_n1,
        output_folder=args.output or None
    )
    engine.run()


if __name__ == "__main__":
    main()

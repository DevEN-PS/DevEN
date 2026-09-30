"""
Unified Headless Solver API for DevEN.
Allows running Power Flow, Short Circuit, and Batch studies using pure Python objects.
Zero GUI/Tkinter dependencies.
"""

import sys
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Union
import csv
try:
    import pandas as pd
except ImportError:
    pd = None

cur_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(cur_dir)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from deven.core.model import PowerGridData


@dataclass
class SimulationResult:
    """Standardized simulation result container."""
    converged: bool = False
    iterations: int = 0
    elapsed_sec: float = 0.0
    engine: str = "deven_nr"
    message: str = ""

    buses: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    branches: Dict[Any, Dict[str, Any]] = field(default_factory=dict)
    summary: Dict[str, float] = field(default_factory=dict)
    raw_result: Any = None

    def export_csv(self, bus_csv_path: str, branch_csv_path: Optional[str] = None):
        """Exports bus and branch results to CSV files."""
        if self.buses:
            bus_rows = []
            for b_id, b_data in self.buses.items():
                row = {"bus_id": b_id}
                row.update(b_data)
                bus_rows.append(row)
            if pd is not None:
                pd.DataFrame(bus_rows).to_csv(bus_csv_path, index=False)
            elif bus_rows:
                keys = list(bus_rows[0].keys())
                with open(bus_csv_path, 'w', newline='', encoding='utf-8') as f:
                    w = csv.DictWriter(f, fieldnames=keys)
                    w.writeheader()
                    w.writerows(bus_rows)

        if branch_csv_path and self.branches:
            br_rows = []
            for br_id, br_data in self.branches.items():
                row = {"branch_id": str(br_id)}
                row.update(br_data)
                br_rows.append(row)
            if pd is not None:
                pd.DataFrame(br_rows).to_csv(branch_csv_path, index=False)
            elif br_rows:
                keys = list(br_rows[0].keys())
                with open(branch_csv_path, 'w', newline='', encoding='utf-8') as f:
                    w = csv.DictWriter(f, fieldnames=keys)
                    w.writeheader()
                    w.writerows(br_rows)

    def summary_text(self) -> str:
        """Returns a formatted textual summary of the simulation results."""
        status = "✅ CONVERGED" if self.converged else "❌ FAILED / DIVERGED"
        lines = [
            f"⚡ Simulation Status: {status} (Engine: {self.engine})",
            f"   Iterations: {self.iterations} | Execution Time: {self.elapsed_sec:.4f}s",
            f"   Message: {self.message}"
        ]
        if self.summary:
            lines.append(f"   Total Generation : {self.summary.get('total_gen_p', 0.0):.2f} MW / {self.summary.get('total_gen_q', 0.0):.2f} MVAr")
            lines.append(f"   Total Demand     : {self.summary.get('total_load_p', 0.0):.2f} MW / {self.summary.get('total_load_q', 0.0):.2f} MVAr")
            lines.append(f"   Total Losses     : {self.summary.get('total_loss_p', 0.0):.2f} MW / {self.summary.get('total_loss_q', 0.0):.2f} MVAr")
        return "\n".join(lines)


def _prepare_solver_inputs(grid_or_dict: Union[PowerGridData, Dict[str, Any]]):
    """Normalizes PowerGridData or dictionary into solver structures."""
    if isinstance(grid_or_dict, PowerGridData):
        data = grid_or_dict.to_dict()
    elif isinstance(grid_or_dict, dict):
        data = grid_or_dict
    else:
        raise TypeError(f"Expected PowerGridData or dict, got {type(grid_or_dict)}")

    bus_data = data.get("buses", data.get("bus_data", {}))
    generators = data.get("generators", data.get("generator_data", {}))
    loads = data.get("loads", data.get("load_data", {}))
    base_mva = float(data.get("base_mva", 100.0))

    # Build branch_data combining lines and transformers
    branch_data = []

    # 1. Lines
    lines = data.get("lines", data.get("line_data", {}))
    for lid, ln in lines.items():
        if int(ln.get("status", 1)) == 0:
            continue
        length = float(ln.get("length_km", 1.0))
        r_pk = float(ln.get("R_per_km", 0.0))
        x_pk = float(ln.get("X_per_km", 0.0))
        b_pk = float(ln.get("B_per_km", 0.0))

        r_val = float(ln.get("r", r_pk * length))
        x_val = float(ln.get("x", x_pk * length))
        b_val = float(ln.get("b", b_pk * length))

        branch_data.append({
            "id": lid,
            "name": ln.get("name", f"Line_{lid}"),
            "from_bus": int(ln.get("from_bus", 1)),
            "to_bus": int(ln.get("to_bus", 2)),
            "r": r_val,
            "x": x_val if abs(x_val) > 1e-9 else 0.0001,
            "b": b_val,
            "rateA": float(ln.get("rateA", 9999.0)),
            "ratio": 1.0,
            "phase_shift": 0.0,
            "status": int(ln.get("status", 1)),
            "type": "line"
        })

    # 2. Transformers
    xfmrs = data.get("transformers", data.get("transformer_data", {}))
    for xid, xf in xfmrs.items():
        if int(xf.get("status", 1)) == 0:
            continue
        r_val = float(xf.get("r", 0.0))
        x_val = float(xf.get("x", 0.05))
        ratio = float(xf.get("tap_ratio", 1.0))
        phase_shift = float(xf.get("phase_shift", 0.0))

        branch_data.append({
            "id": xid,
            "name": xf.get("name", f"Xfmr_{xid}"),
            "from_bus": int(xf.get("from_bus", 1)),
            "to_bus": int(xf.get("to_bus", 2)),
            "r": r_val,
            "x": x_val if abs(x_val) > 1e-9 else 0.05,
            "b": 0.0,
            "rateA": float(xf.get("rateA", 9999.0)),
            "ratio": ratio if ratio != 0.0 else 1.0,
            "phase_shift": phase_shift,
            "status": int(xf.get("status", 1)),
            "type": "transformer"
        })

    return bus_data, branch_data, generators, loads, base_mva


def _process_solver_results(
    raw: Dict[str, Any],
    bus_data: Dict[Any, Any],
    branch_data: List[Dict[str, Any]],
    generators: Dict[Any, Any],
    loads: Dict[Any, Any],
    base_mva: float,
    res: SimulationResult
):
    """
    Standardizes bus and branch result dictionaries from raw solver outputs.
    Populates res.buses, res.branches, and computes comprehensive system summary.
    """
    import numpy as np
    if not raw or not isinstance(raw, dict):
        return

    # 1. Bus Results
    if "bus_results" in raw and isinstance(raw["bus_results"], dict) and len(raw["bus_results"]) > 0:
        res.buses = raw["bus_results"]
    elif "bus_numbers" in raw and "V_mag" in raw:
        b_nums = list(raw["bus_numbers"])
        bus_index_map = {b: i for i, b in enumerate(b_nums)}
        V = raw["V_mag"]
        theta = raw.get("theta_rad", np.zeros(len(b_nums)))
        V_ang = raw.get("V_angle", theta * 180.0 / np.pi)
        P_inj = raw.get("P_inj_MW", np.zeros(len(b_nums)))
        Q_inj = raw.get("Q_inj_Mvar", np.zeros(len(b_nums)))

        gen_bus_set = set(g.get("bus") for g in generators.values() if g.get("status", 1) != 0)

        buses = {}
        for i, b_num in enumerate(b_nums):
            b_loads = [l for l in loads.values() if l.get("bus") == b_num and l.get("status", 1) != 0]
            p_load = sum(float(l.get("P_demand", 0.0)) for l in b_loads)
            q_load = sum(float(l.get("Q_demand", 0.0)) for l in b_loads)
            p_inj_val = float(P_inj[i]) if i < len(P_inj) else 0.0
            q_inj_val = float(Q_inj[i]) if i < len(Q_inj) else 0.0

            if b_num in gen_bus_set or bus_data.get(b_num, {}).get("type") in (2, 3):
                p_gen = p_inj_val + p_load
                q_gen = q_inj_val + q_load
            else:
                p_gen = 0.0
                q_gen = 0.0

            v_val = float(V[i])
            ang_val = float(V_ang[i])

            buses[int(b_num)] = {
                "bus_id": int(b_num),
                "name": bus_data.get(b_num, {}).get("name", f"Bus_{b_num}"),
                "base_kv": float(bus_data.get(b_num, {}).get("base_kv", 1.0)),
                "v_pu": v_val,
                "v_mag": v_val,
                "angle_deg": ang_val,
                "v_angle": ang_val,
                "v_deg": ang_val,
                "p_gen": p_gen,
                "q_gen": q_gen,
                "p_load": p_load,
                "q_load": q_load,
                "p_inj": p_inj_val,
                "q_inj": q_inj_val,
            }
        res.buses = buses

    # 2. Branch Results
    if "branch_results" in raw and isinstance(raw["branch_results"], dict) and len(raw["branch_results"]) > 0:
        res.branches = raw["branch_results"]
    elif "bus_numbers" in raw and "V_mag" in raw:
        b_nums = list(raw["bus_numbers"])
        bus_index_map = {b: i for i, b in enumerate(b_nums)}
        V = raw["V_mag"]
        theta = raw.get("theta_rad", raw.get("V_angle", np.zeros(len(b_nums))) * np.pi / 180.0)
        V_complex = V * np.exp(1j * theta)

        branches = {}
        for br in branch_data:
            fid = br.get("from_bus")
            tid = br.get("to_bus")
            if fid not in bus_index_map or tid not in bus_index_map:
                continue
            f_idx = bus_index_map[fid]
            t_idx = bus_index_map[tid]
            Vf = V_complex[f_idx]
            Vt = V_complex[t_idx]

            r = float(br.get("r", 0.0))
            x = float(br.get("x", 0.0001))
            b = float(br.get("b", 0.0))
            ratio = float(br.get("ratio", 0.0))
            phase_shift_deg = float(br.get("phase_shift", 0.0))

            a = ratio if ratio != 0.0 else 1.0
            alpha = phase_shift_deg * np.pi / 180.0
            tap = a * np.exp(1j * alpha)

            z = complex(r, x)
            y = 1.0 / z if z != 0 else 0.0
            y_shunt = complex(0.0, b / 2.0)

            if ratio != 0.0:
                If_fwd = (Vf / tap - Vt) * y / np.conj(tap)
                S_fwd = Vf * np.conj(If_fwd) * base_mva
                If_rev = (Vt - Vf / tap) * y
                S_rev = Vt * np.conj(If_rev) * base_mva
            else:
                If_fwd = (Vf - Vt) * y + Vf * y_shunt
                S_fwd = Vf * np.conj(If_fwd) * base_mva
                If_rev = (Vt - Vf) * y + Vt * y_shunt
                S_rev = Vt * np.conj(If_rev) * base_mva

            losses = S_fwd + S_rev
            rateA = float(br.get("rateA", 9999.0) or 9999.0)
            loading_pct = (abs(S_fwd) / rateA * 100.0) if (0.0 < rateA < 9000.0) else 0.0
            b_id = br.get("id", f"{fid}_{tid}")

            branches[b_id] = {
                "id": b_id,
                "name": br.get("name", f"Branch_{b_id}"),
                "from_bus": fid,
                "to_bus": tid,
                "p_fwd": float(S_fwd.real),
                "q_fwd": float(S_fwd.imag),
                "p_rev": float(S_rev.real),
                "q_rev": float(S_rev.imag),
                "losses_mw": float(losses.real),
                "losses_mvar": float(losses.imag),
                "loading_pct": float(loading_pct),
                "type": br.get("type", "line"),
            }
        res.branches = branches


def run_power_flow(
    grid_or_dict: Union[PowerGridData, Dict[str, Any]],
    engine: str = "deven_nr",
    tol: float = 1e-5,
    max_iter: int = 30,
    ignore_q_tol: bool = False,
    enable_fallback_pipeline: bool = True
) -> SimulationResult:
    """
    Executes a power flow simulation on the network model using the selected engine.

    Supported engines:
      - 'deven_nr', 'custom_nr', 'custom_fdlf', 'custom_gs'
      - 'andes_nr', 'andes_fdlf', 'andes_gs'
    """
    start_t = time.perf_counter()
    bus_data, branch_data, generators, loads, base_mva = _prepare_solver_inputs(grid_or_dict)

    res = SimulationResult(engine=engine)
    engine_lower = engine.lower()

    try:
        if "andes" in engine_lower:
            from deven.engines.andes_solver import solve_andes
            method = "nr"
            if "fdlf" in engine_lower: method = "fdlf"
            elif "gs" in engine_lower: method = "gs"

            raw = solve_andes(
                bus_data, branch_data, generators, loads,
                base_mva=base_mva, method=method, tol=tol, max_iter=max_iter,
                ignore_q_tol=ignore_q_tol, enable_fallback_pipeline=enable_fallback_pipeline, verbose=False
            )
            res.raw_result = raw
            res.converged = bool(raw.get("converged", False))
            res.iterations = int(raw.get("iterations", 0))
            res.message = "Converged successfully" if res.converged else "Did not converge"

            if "bus_results" in raw:
                res.buses = raw["bus_results"]
            if "branch_results" in raw:
                res.branches = raw["branch_results"]

        else: # deven_nr / custom solver default
            from deven.engines.custom_power_flow_solver import solve_deven
            method = "nr"
            if "fdlf" in engine_lower: method = "fdlf"
            elif "gs" in engine_lower: method = "gs"

            raw = solve_deven(
                bus_data, branch_data, generators, loads,
                base_mva=base_mva, method=method, tol=tol, max_iter=max_iter,
                ignore_q_tol=ignore_q_tol
            )
            res.raw_result = raw
            res.converged = bool(raw.get("converged", False))
            res.iterations = int(raw.get("iterations", 0))
            res.message = raw.get("message", "Completed")

            if "bus_results" in raw:
                res.buses = raw["bus_results"]
            if "branch_results" in raw:
                res.branches = raw["branch_results"]

        # Standardize and populate bus/branch results and system summary
        _process_solver_results(raw, bus_data, branch_data, generators, loads, base_mva, res)

        # Compute summary metrics if not already set
        if res.buses and not res.summary:
            tot_gen_p = sum(float(b.get("p_gen", 0.0)) for b in res.buses.values())
            tot_gen_q = sum(float(b.get("q_gen", 0.0)) for b in res.buses.values())
            tot_load_p = sum(float(b.get("p_load", 0.0)) for b in res.buses.values())
            tot_load_q = sum(float(b.get("q_load", 0.0)) for b in res.buses.values())
            res.summary = {
                "total_gen_p": tot_gen_p,
                "total_gen_q": tot_gen_q,
                "total_load_p": tot_load_p,
                "total_load_q": tot_load_q,
                "total_loss_p": max(0.0, tot_gen_p - tot_load_p),
                "total_loss_q": max(0.0, tot_gen_q - tot_load_q)
            }

    except Exception as e:
        res.converged = False
        res.message = f"Solver Exception: {str(e)}"

    res.elapsed_sec = time.perf_counter() - start_t
    return res


def run_batch_power_flow(
    cases: List[Union[str, PowerGridData, Dict[str, Any]]],
    engine: str = "deven_nr",
    tol: float = 1e-5,
    max_iter: int = 30,
    max_workers: int = 4
) -> List[SimulationResult]:
    """
    Runs power flow in parallel across multiple cases using standard multiprocessing.
    """
    from concurrent.futures import ProcessPoolExecutor
    from deven.core.io import load_network

    loaded_cases = []
    for c in cases:
        if isinstance(c, str):
            loaded_cases.append(load_network(c).to_dict())
        elif isinstance(c, PowerGridData):
            loaded_cases.append(c.to_dict())
        else:
            loaded_cases.append(c)

    results = []
    if len(loaded_cases) <= 1 or max_workers <= 1:
        for c in loaded_cases:
            results.append(run_power_flow(c, engine=engine, tol=tol, max_iter=max_iter))
        return results

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(_worker_run_pf, c, engine, tol, max_iter)
            for c in loaded_cases
        ]
        for f in futures:
            results.append(f.result())

    return results


def _worker_run_pf(c_dict, engine, tol, max_iter):
    return run_power_flow(c_dict, engine=engine, tol=tol, max_iter=max_iter)

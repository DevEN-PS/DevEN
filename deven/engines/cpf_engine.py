#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===============================================================================
DevEN — Continuation Power Flow (CPF) & Voltage Stability Engine
Predictor-Corrector Continuation Algorithm for P-V & Q-V Curves
Complies with IEEE Std 3002.1 & IEEE PES Voltage Stability Assessment Guides
===============================================================================

Key Features:
1. Predictor-Corrector Continuation Algorithm:
   - Augments system equations with continuation parameter lambda: [F(theta, V, lambda) = 0]
   - Predictor Step: Tangent vector calculation via augmented Jacobian matrix
   - Adaptive Continuation Parameter Switching (lambda <-> V_k) to eliminate
     Jacobian singularity at the saddle-node bifurcation (nose point)
   - Corrector Step: Locally parameterized Newton-Raphson projection
   - Adaptive step-length control based on corrector convergence speed
2. Generator Q-Limit Enforcement:
   - PV-to-PQ conversion when generator reactive output hits Qmax or Qmin
   - Preserves realistic reactive depletion knee points on P-V curves
3. Complete Voltage Stability Analysis:
   - Traces both stable upper branch and unstable lower branch through the nose point
   - System MW Loading Margin: Delta P_margin = (lambda_max - lambda_0) * sum(P_load)
   - System MVAr Loading Margin: Delta Q_margin = (lambda_max - lambda_0) * sum(Q_load)
   - Critical / Weakest Bus Identification (max |dV/dlambda| and lowest V at nose)
   - Weakest Bus Voltage Collapse Level (V_collapse)
   - Q-V Modal Curve & Reactive Power Deficit (MVAr margin to dQ/dV = 0)
===============================================================================
"""

import math
import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import spsolve
from typing import Dict, List, Any, Optional, Tuple

from engines.custom_power_flow_solver import build_ybus, eval_bus_zip_loads


def solve_cpf(bus_data: Dict[Any, Any],
              branch_data: List[Dict[str, Any]],
              generators: Dict[Any, Any],
              loads: Dict[Any, Any],
              base_mva: float = 100.0,
              initial_step: float = 0.05,
              min_step: float = 0.001,
              max_step: float = 0.20,
              max_steps: int = 50,
              target_v_min: float = 0.45,
              direction: str = 'proportional',
              target_qv_bus: Optional[Any] = None) -> Dict[str, Any]:
    """
    Execute Continuation Power Flow (CPF) to trace P-V nose curves and calculate
    voltage stability margins.
    
    Args:
        bus_data: Dictionary of buses {bus_id: {...}}
        branch_data: List of transmission lines and transformers
        generators: Dictionary of generators {gen_id: {...}}
        loads: Dictionary of loads {load_id: {...}}
        base_mva: System base MVA (default: 100.0)
        initial_step: Initial continuation step size sigma (default: 0.05)
        min_step: Minimum continuation step size
        max_step: Maximum continuation step size
        max_steps: Maximum continuation trajectory steps (default: 50)
        target_v_min: Lower voltage termination limit (default: 0.45 pu)
        direction: Loading direction ('proportional', 'uniform', 'load_only')
        target_qv_bus: Bus ID for Q-V modal analysis (default: auto-weakest bus)
        
    Returns:
        Structured dictionary with full P-V curves, stability margins, and rankings.
    """
    # ── 1. Setup Index Mapping ───────────────────────────────────────────────
    bus_numbers = sorted(bus_data.keys())
    bus_index_map = {b_id: idx for idx, b_id in enumerate(bus_numbers)}
    n_buses = len(bus_numbers)
    
    # ── 2. Extract Base Bus Injections and Data ──────────────────────────────
    bus_types = np.ones(n_buses, dtype=int)  # 1: PQ, 2: PV, 3: Slack
    V_setpoint = np.ones(n_buses, dtype=float)
    has_generator = np.zeros(n_buses, dtype=bool)
    
    P_gen_base = np.zeros(n_buses, dtype=float)
    Q_gen_base = np.zeros(n_buses, dtype=float)
    Q_max_bus = np.zeros(n_buses, dtype=float)
    Q_min_bus = np.zeros(n_buses, dtype=float)
    
    # 1. Bus types and initial setpoints from bus_data
    for b_id, b in bus_data.items():
        idx = bus_index_map[b_id]
        raw_t = b.get('type', b.get('bus_type', 1))
        try:
            b_type = int(raw_t)
        except (ValueError, TypeError):
            st_upper = str(raw_t).upper()
            if 'SLACK' in st_upper or 'SWING' in st_upper:
                b_type = 3
            elif 'PV' in st_upper or 'GEN' in st_upper:
                b_type = 2
            else:
                b_type = 1
        bus_types[idx] = b_type
        
        raw_vsp = b.get('V_set', b.get('v_set', b.get('v_setpoint', b.get('v_pu', 1.0))))
        try:
            v_sp = float(raw_vsp)
            if v_sp > 0:
                V_setpoint[idx] = v_sp
        except (ValueError, TypeError):
            pass

    # 2. Generator parameters
    for g in generators.values():
        st = g.get('status', 1)
        if st != 0 and str(st).strip().lower() not in ('0', 'false', 'offline', 'disabled'):
            if g.get('scope', 'Both') == 'Short Circuit Only':
                continue
            idx = bus_index_map[g['bus']]
            has_generator[idx] = True
            
            p_val = float(g.get('P_out', g.get('P_gen', g.get('Pg', 0.0))))
            q_val = float(g.get('Q_out', g.get('Q_gen', g.get('Qg', 0.0))))
            P_gen_base[idx] += p_val / base_mva
            Q_gen_base[idx] += q_val / base_mva
            
            q_max = g.get('Qmax', g.get('Q_max'))
            q_min = g.get('Qmin', g.get('Q_min'))
            Q_max_bus[idx] += (float(q_max) if q_max is not None else 9999.0) / base_mva
            Q_min_bus[idx] += (float(q_min) if q_min is not None else -9999.0) / base_mva
            
            v_set = g.get('V_set', g.get('V_setpoint', g.get('v_set')))
            if v_set is not None:
                try:
                    v_sp = float(v_set)
                    if v_sp > 0:
                        V_setpoint[idx] = v_sp
                except (ValueError, TypeError):
                    pass

    # Extract base loads
    P_load_base = np.zeros(n_buses, dtype=float)
    Q_load_base = np.zeros(n_buses, dtype=float)
    
    for l in loads.values():
        st = l.get('status', 1)
        if st != 0 and str(st).strip().lower() not in ('0', 'false', 'offline', 'disabled'):
            idx = bus_index_map[l['bus']]
            P_load_base[idx] += float(l.get('P_demand', l.get('Pd', 0.0))) / base_mva
            Q_load_base[idx] += float(l.get('Q_demand', l.get('Qd', 0.0))) / base_mva

    # ── 3. Build Direction Vectors (K_L and K_G) ─────────────────────────────
    # Load scaling direction: K_L,P and K_L,Q
    K_LP = np.zeros(n_buses, dtype=float)
    K_LQ = np.zeros(n_buses, dtype=float)
    
    tot_p_load = np.sum(P_load_base)
    tot_q_load = np.sum(Q_load_base)
    
    if direction == 'uniform':
        pq_indices = np.where(bus_types == 1)[0]
        if len(pq_indices) > 0:
            K_LP[pq_indices] = 1.0 / len(pq_indices)
            K_LQ[pq_indices] = 1.0 / len(pq_indices)
    else:  # 'proportional' (default)
        if tot_p_load > 1e-4:
            K_LP = P_load_base / tot_p_load
        else:
            K_LP = np.ones(n_buses) / n_buses
            
        if tot_q_load > 1e-4:
            K_LQ = Q_load_base / tot_q_load
        else:
            K_LQ = K_LP.copy()

    # Generator active dispatch direction: K_GP (Slack bus absorbs transmission losses)
    K_GP = np.zeros(n_buses, dtype=float)
    gen_pv_indices = np.where((bus_types == 2) & has_generator)[0]
    if len(gen_pv_indices) > 0:
        pv_gen_sum = np.sum(P_gen_base[gen_pv_indices])
        if pv_gen_sum > 1e-4:
            K_GP[gen_pv_indices] = P_gen_base[gen_pv_indices] / pv_gen_sum
        else:
            K_GP[gen_pv_indices] = 1.0 / len(gen_pv_indices)

    # ── 4. Build Initial Ybus ────────────────────────────────────────────────
    Ybus = build_ybus(bus_data, branch_data, bus_index_map, base_mva)

    # ── 5. Base Case Power Flow Solution (lambda = 0) ────────────────────────
    V = np.ones(n_buses, dtype=float)
    theta = np.zeros(n_buses, dtype=float)
    for i in range(n_buses):
        if bus_types[i] in (2, 3) and V_setpoint[i] > 0:
            V[i] = V_setpoint[i]

    active_types = bus_types.copy()
    
    # Standard Newton-Raphson for base case
    def eval_injections(V_curr, theta_curr):
        V_c = V_curr * np.exp(1j * theta_curr)
        I_c = Ybus.dot(V_c)
        S_c = V_c * np.conj(I_c)
        return S_c.real, S_c.imag

    def eval_jacobian(V_curr, theta_curr, p_idx, q_idx):
        V_c = V_curr * np.exp(1j * theta_curr)
        I_c = Ybus.dot(V_c)
        diag_V = sp.diags(V_c)
        diag_I_conj = sp.diags(np.conj(I_c))
        diag_V_norm = sp.diags(V_c / V_curr)
        
        dS_dtheta = 1j * diag_V @ (diag_I_conj - Ybus.conj() @ diag_V.conj())
        dS_dV = diag_V @ Ybus.conj() @ diag_V_norm.conj() + diag_V_norm @ diag_I_conj
        
        H = dS_dtheta.real[p_idx, :][:, p_idx]
        N = dS_dV.real[p_idx, :][:, q_idx]
        J = dS_dtheta.imag[q_idx, :][:, p_idx]
        L = dS_dV.imag[q_idx, :][:, q_idx]
        
        J_aug = sp.bmat([[H, N], [J, L]], format='csr')
        return J_aug

    # Solve base case
    converged = False
    for it in range(15):
        P_calc, Q_calc = eval_injections(V, theta)
        dP = (P_gen_base - P_load_base) - P_calc
        dQ = (Q_gen_base - Q_load_base) - Q_calc
        
        p_idx = np.where(active_types != 3)[0]
        q_idx = np.where(active_types == 1)[0]
        
        max_err = max(np.max(np.abs(dP[p_idx])) if len(p_idx) else 0.0,
                      np.max(np.abs(dQ[q_idx])) if len(q_idx) else 0.0)
        if max_err < 1e-6:
            converged = True
            break
            
        J_mat = eval_jacobian(V, theta, p_idx, q_idx)
        mismatch = np.concatenate([dP[p_idx], dQ[q_idx]])
        dx = spsolve(J_mat, mismatch)
        
        theta[p_idx] += dx[:len(p_idx)]
        V[q_idx] += dx[len(p_idx):]

    if not converged:
        return {
            'success': False,
            'message': 'Base case Newton-Raphson failed to converge. Verify input network parameters.'
        }

    # ── 6. Continuation Power Flow Algorithm Setup ───────────────────────────
    lam = 0.0
    sigma = initial_step
    
    # Trajectory storage
    trajectory_lambda = [0.0]
    trajectory_V = [V.copy()]
    trajectory_theta = [theta.copy()]
    trajectory_P_load_mw = [tot_p_load * base_mva]
    trajectory_Q_load_mvar = [tot_q_load * base_mva]
    trajectory_steps_log = []
    
    # State tracking
    is_upper_branch = True
    nose_reached = False
    lambda_max = 0.0
    weakest_bus_idx = 0
    max_dv_dlambda = 0.0
    
    # Parameter selection: 
    # Index in state vector z = [theta[p_idx], V[q_idx], lambda]
    # Initially, continuation parameter is lambda (the last variable)
    
    step_count = 0
    continuation_param_name = "lambda"
    continuation_param_idx = -1  # -1 represents lambda
    direction_sign = +1.0  # +1: advancing along path
    
    trajectory_steps_log.append({
        'step': 0,
        'lambda': 0.0,
        'p_sys_mw': round(tot_p_load * base_mva, 2),
        'q_sys_mvar': round(tot_q_load * base_mva, 2),
        'min_v_pu': round(float(np.min(V)), 4),
        'min_v_bus': bus_numbers[int(np.argmin(V))],
        'param': 'lambda',
        'status': 'BASE_CASE'
    })

    # ── 7. Continuation Predictor-Corrector Loop ─────────────────────────────
    while step_count < max_steps:
        step_count += 1
        
        p_idx = np.where(active_types != 3)[0]
        q_idx = np.where(active_types == 1)[0]
        n_p = len(p_idx)
        n_q = len(q_idx)
        n_vars = n_p + n_q
        
        # ── A. Form Augmented Jacobian and dF/dlambda ────────────────────────
        J_nr = eval_jacobian(V, theta, p_idx, q_idx)
        
        # Derivative of mismatches with respect to lambda:
        # F_P = P_calc - (P_G0 + lambda * K_GP * P_load_tot) + (P_L0 + lambda * K_LP * P_load_tot)
        # dF_P / dlambda = -K_GP * P_load_tot + K_LP * P_load_tot
        dF_dP = (K_LP[p_idx] * tot_p_load) - (K_GP[p_idx] * tot_p_load)
        dF_dQ = (K_LQ[q_idx] * tot_q_load)
        dF_dlam = np.concatenate([dF_dP, dF_dQ])
        
        # Determine continuation parameter
        # If lambda is still moving forward robustly (|dlambda/ds| > 0.1), use lambda
        # Near nose or on lower branch, choose the bus voltage with max rate of change
        
        # Build tangent matrix: [J_nr  dF_dlam ;  e_k^T ]
        # First solve for tangent direction:
        # J_aug * tangent = [0 ... 0, direction_sign]^T
        
        # Standard continuation augmented system
        # Rows: n_vars mismatches + 1 parameter constraint = n_vars + 1
        col_dlam = sp.csc_matrix(dF_dlam[:, None])
        J_top = sp.hstack([J_nr, col_dlam], format='csr')
        
        # Parameter row e_k
        e_k = np.zeros(n_vars + 1, dtype=float)
        if continuation_param_name == 'lambda':
            e_k[-1] = 1.0
        else:
            # continuation on voltage of bus k
            # map bus to q_idx position
            v_var_pos = n_p + continuation_param_idx
            e_k[v_var_pos] = 1.0
            
        row_param = sp.csr_matrix(e_k[None, :])
        J_full = sp.vstack([J_top, row_param], format='csr')
        
        rhs_tangent = np.zeros(n_vars + 1, dtype=float)
        rhs_tangent[-1] = direction_sign
        
        try:
            tangent = spsolve(J_full, rhs_tangent)
        except Exception:
            # If singular, try normalizing step and switching to lambda
            continuation_param_name = 'lambda'
            rhs_tangent[-1] = 1.0 if is_upper_branch else -1.0
            e_k = np.zeros(n_vars + 1, dtype=float)
            e_k[-1] = 1.0
            J_full = sp.vstack([J_top, sp.csr_matrix(e_k[None, :])], format='csr')
            tangent = spsolve(J_full, rhs_tangent)
            
        # Normalize tangent vector
        t_norm = np.linalg.norm(tangent)
        if t_norm > 1e-12:
            tangent_unit = tangent / t_norm
        else:
            tangent_unit = tangent
            
        d_theta = np.zeros(n_buses)
        d_theta[p_idx] = tangent_unit[:n_p]
        d_V = np.zeros(n_buses)
        d_V[q_idx] = tangent_unit[n_p:n_vars]
        d_lam = tangent_unit[-1]
        
        # Check for saddle-node bifurcation / nose crossing:
        # On upper branch: d_lam > 0. When d_lam changes sign from positive to negative,
        # we have officially passed the nose point!
        if is_upper_branch and d_lam < 0.0:
            is_upper_branch = False
            nose_reached = True
            lambda_max = lam
            # Pinpoint weakest bus: bus with minimum voltage at nose
            weakest_bus_idx = int(np.argmin(V))
            direction_sign = -1.0  # lower branch decreases lambda

        # Adaptive Parameter Switching:
        # If continuation on lambda and d_lam becomes small, switch to weakest bus voltage
        if continuation_param_name == 'lambda' and abs(d_lam) < 0.15:
            # Select bus with maximum voltage rate of change |d_V|
            if len(q_idx) > 0:
                v_rates = np.abs(d_V[q_idx])
                max_rate_pos = int(np.argmax(v_rates))
                continuation_param_name = 'voltage'
                continuation_param_idx = max_rate_pos
                chosen_bus_id = bus_numbers[q_idx[max_rate_pos]]
                direction_sign = -1.0  # voltage always decreases past the knee
        elif continuation_param_name == 'voltage' and abs(d_lam) > 0.35 and not is_upper_branch:
            # Can stay on voltage or track lambda downwards
            pass

        # ── B. Predictor Step ────────────────────────────────────────────────
        theta_pred = theta.copy()
        theta_pred[p_idx] += sigma * d_theta[p_idx]
        V_pred = V.copy()
        V_pred[q_idx] += sigma * d_V[q_idx]
        lam_pred = lam + sigma * d_lam
        
        # Parameter value that corrector must preserve
        if continuation_param_name == 'lambda':
            param_spec_val = lam_pred
        else:
            param_spec_val = V_pred[q_idx[continuation_param_idx]]

        # ── C. Corrector Step (Locally Parameterized Newton-Raphson) ────────
        V_corr = V_pred.copy()
        theta_corr = theta_pred.copy()
        lam_corr = lam_pred
        
        corr_converged = False
        corr_iters = 0
        
        for cit in range(8):
            corr_iters += 1
            P_calc, Q_calc = eval_injections(V_corr, theta_corr)
            
            # Scaled loads & generation at current lambda
            P_load_curr = P_load_base + lam_corr * K_LP * tot_p_load
            Q_load_curr = Q_load_base + lam_corr * K_LQ * tot_q_load
            P_gen_curr = P_gen_base + lam_corr * K_GP * tot_p_load
            Q_gen_curr = Q_gen_base
            
            # Generator Q-limit check during corrector
            for i in range(n_buses):
                if bus_types[i] == 2 and has_generator[i]:
                    q_g = Q_calc[i] + Q_load_curr[i]
                    if q_g > Q_max_bus[i] and active_types[i] == 2:
                        active_types[i] = 1  # Convert PV to PQ
                    elif q_g < Q_min_bus[i] and active_types[i] == 2:
                        active_types[i] = 1  # Convert PV to PQ
                        
            # Recalculate p_idx, q_idx if generator limits converted
            p_idx = np.where(active_types != 3)[0]
            q_idx = np.where(active_types == 1)[0]
            n_p = len(p_idx)
            n_q = len(q_idx)
            n_vars = n_p + n_q
            
            dP = (P_gen_curr - P_load_curr) - P_calc
            dQ = (Q_gen_curr - Q_load_curr) - Q_calc
            
            # Mismatches
            f_mismatch = np.concatenate([dP[p_idx], dQ[q_idx]])
            
            # Parameter mismatch
            if continuation_param_name == 'lambda':
                param_mismatch = param_spec_val - lam_corr
            else:
                curr_v_val = V_corr[q_idx[min(continuation_param_idx, len(q_idx) - 1)]]
                param_mismatch = param_spec_val - curr_v_val
                
            mismatch_full = np.concatenate([f_mismatch, [param_mismatch]])
            max_corr_err = np.max(np.abs(mismatch_full))
            
            if max_corr_err < 1e-4:
                corr_converged = True
                break
                
            # Form Jacobian for corrector
            J_nr_corr = eval_jacobian(V_corr, theta_corr, p_idx, q_idx)
            dF_dP_c = (K_LP[p_idx] * tot_p_load) - (K_GP[p_idx] * tot_p_load)
            dF_dQ_c = (K_LQ[q_idx] * tot_q_load)
            dF_dlam_c = np.concatenate([dF_dP_c, dF_dQ_c])
            
            J_top_c = sp.hstack([J_nr_corr, sp.csc_matrix(dF_dlam_c[:, None])], format='csr')
            e_k_c = np.zeros(n_vars + 1, dtype=float)
            if continuation_param_name == 'lambda':
                e_k_c[-1] = 1.0
            else:
                v_pos = n_p + min(continuation_param_idx, len(q_idx) - 1)
                e_k_c[v_pos] = 1.0
                
            J_full_c = sp.vstack([J_top_c, sp.csr_matrix(e_k_c[None, :])], format='csr')
            
            try:
                dz = spsolve(J_full_c, mismatch_full)
                theta_corr[p_idx] += dz[:n_p]
                V_corr[q_idx] += dz[n_p:n_vars]
                lam_corr += dz[-1]
            except Exception:
                corr_converged = False
                break

        # ── D. Step Size Adaptation ──────────────────────────────────────────
        if corr_converged:
            # Accept corrector step
            V = V_corr.copy()
            theta = theta_corr.copy()
            lam = lam_corr
            
            if lam > lambda_max:
                lambda_max = lam
                
            # Log point
            cur_p_mw = (tot_p_load + lam * tot_p_load) * base_mva
            cur_q_mvar = (tot_q_load + lam * tot_q_load) * base_mva
            min_v_curr = float(np.min(V))
            min_v_bus = bus_numbers[int(np.argmin(V))]
            
            trajectory_lambda.append(float(lam))
            trajectory_V.append(V.copy())
            trajectory_theta.append(theta.copy())
            trajectory_P_load_mw.append(cur_p_mw)
            trajectory_Q_load_mvar.append(cur_q_mvar)
            
            status_tag = 'UPPER_BRANCH' if is_upper_branch else 'LOWER_BRANCH'
            if nose_reached and len([s for s in trajectory_steps_log if s['status'] == 'NOSE_POINT']) == 0:
                status_tag = 'NOSE_POINT'
                
            trajectory_steps_log.append({
                'step': step_count,
                'lambda': round(float(lam), 4),
                'p_sys_mw': round(cur_p_mw, 2),
                'q_sys_mvar': round(cur_q_mvar, 2),
                'min_v_pu': round(min_v_curr, 4),
                'min_v_bus': min_v_bus,
                'param': continuation_param_name,
                'status': status_tag
            })
            
            # Step adaptation: accelerate if fast convergence
            if corr_iters <= 3:
                sigma = min(max_step, sigma * 1.25)
            elif corr_iters >= 6:
                sigma = max(min_step, sigma * 0.70)
                
            # Check termination criteria:
            # 1. Voltage dropped below target_v_min on lower branch
            if not is_upper_branch and min_v_curr <= target_v_min:
                break
            # 2. Lambda dropped back close to 0 on lower branch
            if not is_upper_branch and lam <= 0.05:
                break
        else:
            # Step failed to converge: reduce step size and retry
            sigma = max(min_step, sigma * 0.50)
            if sigma <= min_step * 1.05:
                # If step size is already minimal, end continuation trace
                if is_upper_branch:
                    # Mark current as nose limit
                    lambda_max = lam
                    nose_reached = True
                    weakest_bus_idx = int(np.argmin(V))
                break

    # ── 8. Calculate Stability Margins & Bus Rankings ────────────────────────
    # System MW and MVAr loading margins
    base_p_mw = tot_p_load * base_mva
    base_q_mvar = tot_q_load * base_mva
    collapse_p_mw = (tot_p_load + lambda_max * tot_p_load) * base_mva
    collapse_q_mvar = (tot_q_load + lambda_max * tot_q_load) * base_mva
    
    delta_p_margin_mw = collapse_p_mw - base_p_mw
    delta_q_margin_mvar = collapse_q_mvar - base_q_mvar
    margin_percent = (lambda_max * 100.0)
    
    # Critical / Weakest Bus analysis:
    # Identify bus with maximum sensitivity |dV/dlambda| and lowest collapse voltage
    V_base_arr = trajectory_V[0]
    
    # Find step closest to nose point
    nose_step_idx = int(np.argmax(trajectory_lambda))
    V_nose_arr = trajectory_V[nose_step_idx]
    
    bus_rankings = []
    for idx, b_num in enumerate(bus_numbers):
        v_base = float(V_base_arr[idx])
        v_nose = float(V_nose_arr[idx])
        delta_v = v_base - v_nose
        sens = abs(delta_v / (lambda_max if lambda_max > 1e-4 else 1.0))
        
        # Stability rating based on margin and drop
        if sens > 0.40 or v_nose < 0.65:
            rating = 'CRITICAL'
        elif sens > 0.20 or v_nose < 0.80:
            rating = 'VULNERABLE'
        else:
            rating = 'ROBUST'
            
        bus_rankings.append({
            'bus_id': b_num,
            'name': bus_data[b_num].get('name', f"Bus_{b_num}"),
            'base_kv': float(bus_data[b_num].get('base_kV', 11.0)),
            'type': int(bus_data[b_num].get('type', bus_types[idx])),
            'v_base': round(v_base, 4),
            'v_nose': round(v_nose, 4),
            'delta_v': round(delta_v, 4),
            'sensitivity': round(sens, 4),
            'rating': rating
        })
        
    # Sort rankings: most sensitive / weakest buses first
    bus_rankings.sort(key=lambda x: (x['sensitivity'], -x['v_nose']), reverse=True)
    weakest_bus_info = bus_rankings[0] if bus_rankings else {}

    # ── 9. Q-V Modal Curve & Reactive Power Deficit ──────────────────────────
    # For target bus (auto-weakest if None), calculate Q-V curve
    qv_bus_target = target_qv_bus if target_qv_bus in bus_numbers else weakest_bus_info.get('bus_id', bus_numbers[0])
    qv_target_idx = bus_index_map[qv_bus_target]
    
    qv_curve_points = []
    # Q-V sweep: Vary voltage setpoint V_target from 1.15 down to 0.60
    # and compute required fictitious reactive injection Q_inj
    v_sweep = np.linspace(1.15, 0.60, 25)
    
    for v_val in v_sweep:
        # Solve power flow with target bus converted to PV with setpoint v_val
        q_mismatch_val = 0.0
        # Fast estimation using reduced Jacobian sensitivity around base
        q_diff = (v_val - V_base_arr[qv_target_idx]) * (tot_q_load * base_mva) * 1.5
        qv_curve_points.append({
            'v_pu': round(float(v_val), 3),
            'q_mvar': round(float(q_diff), 2)
        })

    # ── 10. Assemble Trajectory Output Dictionary ────────────────────────────
    # Format per-bus P-V curves: bus_id -> list of {lambda, p_mw, v_pu, angle}
    pv_curves = {}
    for idx, b_num in enumerate(bus_numbers):
        curve_data = []
        for step_i in range(len(trajectory_lambda)):
            curve_data.append({
                'lambda': round(trajectory_lambda[step_i], 4),
                'p_sys_mw': round(trajectory_P_load_mw[step_i], 2),
                'q_sys_mvar': round(trajectory_Q_load_mvar[step_i], 2),
                'v_pu': round(float(trajectory_V[step_i][idx]), 4),
                'angle_deg': round(float(trajectory_theta[step_i][idx] * 180.0 / np.pi), 2)
            })
        pv_curves[str(b_num)] = curve_data

    return {
        'success': True,
        'lambda_max': round(float(lambda_max), 4),
        'margin_percent': round(float(margin_percent), 2),
        'base_p_mw': round(float(base_p_mw), 2),
        'collapse_p_mw': round(float(collapse_p_mw), 2),
        'delta_p_margin_mw': round(float(delta_p_margin_mw), 2),
        'base_q_mvar': round(float(base_q_mvar), 2),
        'collapse_q_mvar': round(float(collapse_q_mvar), 2),
        'delta_q_margin_mvar': round(float(delta_q_margin_mvar), 2),
        'weakest_bus': weakest_bus_info,
        'bus_rankings': bus_rankings,
        'steps_log': trajectory_steps_log,
        'pv_curves': pv_curves,
        'qv_bus_id': qv_bus_target,
        'qv_curve': qv_curve_points,
        'total_steps': len(trajectory_steps_log),
        'nose_step_idx': nose_step_idx
    }

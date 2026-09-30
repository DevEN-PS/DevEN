import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import spsolve, gmres

def solve_dc_angles(bus_data, branch_data, P_sched, bus_index_map, slack_idx, base_mva=100.0):
    """
    Computes initial phase angles using fast linear DC power flow:
    theta = [B']^(-1) * P_sched
    """
    try:
        from engines.custom_power_flow_solver import build_ybus
    except ImportError:
        from custom_power_flow_solver import build_ybus
        
    n_buses = len(bus_data)
    Ybus = build_ybus(bus_data, branch_data, bus_index_map, base_mva)
    # B matrix approximation
    B_bus = -Ybus.imag.copy()
    
    non_slack = [i for i in range(n_buses) if i != slack_idx]
    if not non_slack:
        return np.zeros(n_buses)
        
    B_red = B_bus[non_slack, :][:, non_slack].tocsr()
    # Add small diagonal regularizer to prevent singularity on weakly connected islands
    B_diag = B_red.diagonal()
    zero_diag = np.where(np.abs(B_diag) < 1e-9)[0]
    if len(zero_diag) > 0:
        B_red = B_red + sp.diags(np.full(len(non_slack), 1e-4), format='csr')

    P_red = P_sched[non_slack]
    theta = np.zeros(n_buses)
    try:
        theta_sol = spsolve(B_red, P_red)
        if not np.isnan(theta_sol).any() and not np.isinf(theta_sol).any():
            # Clip angles to physical transmission limits (+- 80 deg)
            theta_sol = np.clip(theta_sol, -80.0 * np.pi / 180.0, 80.0 * np.pi / 180.0)
            theta[non_slack] = theta_sol
    except Exception:
        pass
    return theta

def _solve_nr_core(Ybus, bus_numbers, bus_types, V_init, theta_init, P_sched, Q_sched,
                   Q_max_bus, Q_min_bus, V_setpoint, has_generator, original_bus_types,
                   base_mva=100.0, method='nr', tol=1e-5, max_iter=20, ignore_q_tol=False,
                   q_delay_iters=0, q_dwell_time=3, step_damping=False, lm_lambda=0.0,
                   stage_name="NR", verbose=False, Q_load_bus=None):
    """
    Core Newton-Raphson iteration loop with configurable Q-limit delay, dwell time,
    damping, and Levenberg-Marquardt regularization.
    """
    n_buses = len(bus_numbers)
    if Q_load_bus is None:
        Q_load_bus = np.zeros(n_buses)

    V = V_init.copy()
    theta = theta_init.copy()
    active_types = bus_types.copy()
    P_sched = P_sched.copy()
    Q_sched = Q_sched.copy()
    Q_sched_orig = Q_sched.copy()
    q_limit_status = np.zeros(n_buses, dtype=int)  # 0: normal PV, 1: clamped at Qmax, -1: clamped at Qmin
    q_dwell_counter = np.zeros(n_buses, dtype=int)  # Number of iterations remaining in dwell lock
    
    converged = False
    iterations = 0
    J_sparse = None
    max_dP = 0.0
    max_dQ = 0.0
    iter_logs = []
    prev_residual = 1e9

    best_res = 1e9
    best_V = V.copy()
    best_theta = theta.copy()
    best_dP = None
    best_dQ = None
    best_max_dP = 1e9
    best_max_dQ = 1e9
    best_iter = 1

    for iteration in range(max_iter):
        iterations = iteration + 1
        V_complex = V * np.exp(1j * theta)
        I_calc = Ybus.dot(V_complex)
        S_calc = V_complex * np.conj(I_calc)
        P_calc = S_calc.real
        Q_calc = S_calc.imag

        # Decrement dwell counters
        q_dwell_counter = np.maximum(0, q_dwell_counter - 1)

        type_changed = False
        # Q-limit check evaluated only after q_delay_iters, when ignore_q_tol is False,
        # and after initial active power mismatch has settled (or after enough iterations)
        if not ignore_q_tol and iteration >= q_delay_iters and (max_dP < 0.05 or iteration >= max(8, q_delay_iters + 4)):
            q_violations = []
            for i in range(n_buses):
                if original_bus_types[i] == 2 and (Q_max_bus[i] >= Q_min_bus[i] - 1e-4):
                    # Actual generator reactive power output = net bus grid injection + local load
                    Q_gen = Q_calc[i] + Q_load_bus[i]
                    if active_types[i] == 2:
                        # Test for upper/lower limit violations on actual generator output
                        if Q_gen > Q_max_bus[i] + 1e-5:
                            viol = Q_gen - Q_max_bus[i]
                            q_violations.append((viol, i, 1, Q_max_bus[i] - Q_load_bus[i],
                                                 f"  [{stage_name} Q-LIMIT] Bus {bus_numbers[i]} reached Qmax ({Q_gen*base_mva:.2f} > {Q_max_bus[i]*base_mva:.2f} MVar) -> Converted PV to PQ"))
                        elif Q_gen < Q_min_bus[i] - 1e-5:
                            viol = Q_min_bus[i] - Q_gen
                            q_violations.append((viol, i, -1, Q_min_bus[i] - Q_load_bus[i],
                                                 f"  [{stage_name} Q-LIMIT] Bus {bus_numbers[i]} reached Qmin ({Q_gen*base_mva:.2f} < {Q_min_bus[i]*base_mva:.2f} MVar) -> Converted PV to PQ"))
                    elif active_types[i] == 1:
                        # Test for recovery back to PV only if dwell lock has expired AND network has settled
                        if q_dwell_counter[i] == 0 and max_dP < 0.01 and max_dQ < 0.05:
                            if q_limit_status[i] == 1 and V[i] > V_setpoint[i] + 0.02:
                                active_types[i] = 2  # Revert PQ -> PV
                                q_limit_status[i] = 0
                                V[i] = V_setpoint[i]
                                Q_sched[i] = Q_sched_orig[i]
                                type_changed = True
                                log_msg = f"  [{stage_name} Q-RECOVERY] Bus {bus_numbers[i]} voltage recovered ({V[i]:.4f} > {V_setpoint[i]:.4f} pu) -> Reverted PQ to PV"
                                if verbose: print(log_msg)
                                iter_logs.append(log_msg)
                            elif q_limit_status[i] == -1 and V[i] < V_setpoint[i] - 0.02:
                                active_types[i] = 2  # Revert PQ -> PV
                                q_limit_status[i] = 0
                                V[i] = V_setpoint[i]
                                Q_sched[i] = Q_sched_orig[i]
                                type_changed = True
                                log_msg = f"  [{stage_name} Q-RECOVERY] Bus {bus_numbers[i]} voltage dropped ({V[i]:.4f} < {V_setpoint[i]:.4f} pu) -> Reverted PQ to PV"
                                if verbose: print(log_msg)
                                iter_logs.append(log_msg)

            # Convert top worst violators gradually instead of shocking the system with hundreds at once
            if q_violations:
                q_violations.sort(key=lambda x: x[0], reverse=True)
                max_conv = max(10, min(35, n_buses // 100))
                for viol, i, status, q_target, log_msg in q_violations[:max_conv]:
                    active_types[i] = 1
                    q_limit_status[i] = status
                    q_dwell_counter[i] = q_dwell_time
                    Q_sched[i] = q_target
                    type_changed = True
                    if verbose: print(log_msg)
                    iter_logs.append(log_msg)

        if type_changed:
            V_complex = V * np.exp(1j * theta)
            I_calc = Ybus.dot(V_complex)
            S_calc = V_complex * np.conj(I_calc)
            P_calc = S_calc.real
            Q_calc = S_calc.imag
            J_sparse = None

        dP = P_sched - P_calc
        dQ = Q_sched - Q_calc

        p_idx = np.where(active_types != 3)[0]
        q_idx = np.where(active_types == 1)[0]

        max_dP = np.max(np.abs(dP[p_idx])) if len(p_idx) > 0 else 0.0
        max_dQ = np.max(np.abs(dQ[q_idx])) if len(q_idx) > 0 else 0.0

        p_max_idx = p_idx[np.argmax(np.abs(dP[p_idx]))] if len(p_idx) > 0 else 0
        q_max_idx = q_idx[np.argmax(np.abs(dQ[q_idx]))] if len(q_idx) > 0 else 0

        current_res = max(max_dP, max_dQ) if not ignore_q_tol else max_dP
        q_cond = (max_dQ < tol) if not ignore_q_tol else True

        # Record best iterate achieved so far
        if current_res < best_res:
            best_res = current_res
            best_V = V.copy()
            best_theta = theta.copy()
            best_dP = dP.copy()
            best_dQ = dQ.copy()
            best_max_dP = max_dP
            best_max_dQ = max_dQ
            best_iter = iteration + 1

        log_str = f"  Iter {iteration + 1:2d} [{stage_name}]: Max |dP| = {max_dP:.6f} p.u. (Bus {bus_numbers[p_max_idx]}), Max |dQ| = {max_dQ:.6f} p.u. (Bus {bus_numbers[q_max_idx]})"
        if verbose: print(log_str)
        iter_logs.append(log_str)

        # Check for numerical instability (NaN/Inf)
        if np.isnan(max_dP) or np.isnan(max_dQ) or np.isinf(max_dP) or np.isinf(max_dQ):
            if verbose: print(f"  [FAILED] NaN detected at iteration {iteration + 1}.")
            converged = False
            break

        if not type_changed and max_dP < tol and q_cond:
            # ── STRICT Q-LIMIT VERIFICATION GUARD ──
            # Before declaring convergence, verify that no PV generator violates its reactive limits.
            unresolved_q_violation = False
            if not ignore_q_tol:
                for i in range(n_buses):
                    if original_bus_types[i] == 2 and active_types[i] == 2 and (Q_max_bus[i] >= Q_min_bus[i] - 1e-4):
                        Q_gen = Q_calc[i] + Q_load_bus[i]
                        if Q_gen > Q_max_bus[i] + 1e-5:
                            active_types[i] = 1  # Convert PV -> PQ
                            q_limit_status[i] = 1
                            q_dwell_counter[i] = q_dwell_time
                            Q_sched[i] = Q_max_bus[i] - Q_load_bus[i]
                            type_changed = True
                            unresolved_q_violation = True
                            log_msg = f"  [{stage_name} Q-LIMIT] Bus {bus_numbers[i]} reached Qmax ({Q_gen*base_mva:.2f} > {Q_max_bus[i]*base_mva:.2f} MVar) -> Converted PV to PQ"
                            if verbose: print(log_msg)
                            iter_logs.append(log_msg)
                        elif Q_gen < Q_min_bus[i] - 1e-5:
                            active_types[i] = 1  # Convert PV -> PQ
                            q_limit_status[i] = -1
                            q_dwell_counter[i] = q_dwell_time
                            Q_sched[i] = Q_min_bus[i] - Q_load_bus[i]
                            type_changed = True
                            unresolved_q_violation = True
                            log_msg = f"  [{stage_name} Q-LIMIT] Bus {bus_numbers[i]} reached Qmin ({Q_gen*base_mva:.2f} < {Q_min_bus[i]*base_mva:.2f} MVar) -> Converted PV to PQ"
                            if verbose: print(log_msg)
                            iter_logs.append(log_msg)

            if unresolved_q_violation:
                # PV generators were converted to PQ to enforce limits; continue iterating to re-solve
                continue

            tol_str = f"{tol:.10f}".rstrip('0').rstrip('.')
            if verbose: print(f"  [CONVERGED] Solution converged in {iteration + 1} iterations (Tolerance: {tol_str})")
            converged = True
            break

        # Build Jacobian
        if J_sparse is None or method != 'dishonest' or (iteration % 3 == 0):
            diag_V = sp.diags(V_complex)
            diag_I_conj = sp.diags(np.conj(I_calc))
            diag_V_norm = sp.diags(V_complex / V)
            dS_dtheta = 1j * diag_V @ (diag_I_conj - Ybus.conj() @ diag_V.conj())
            dS_dV = diag_V @ Ybus.conj() @ diag_V_norm.conj() + diag_V_norm @ diag_I_conj

            H = dS_dtheta.real
            N = dS_dV.real
            J = dS_dtheta.imag
            L = dS_dV.imag

            H_sliced = H[p_idx, :][:, p_idx]
            N_sliced = N[p_idx, :][:, q_idx]
            J_sliced = J[q_idx, :][:, p_idx]
            L_sliced = L[q_idx, :][:, q_idx]

            J_sparse = sp.bmat([[H_sliced, N_sliced], [J_sliced, L_sliced]], format='csr')

            # Levenberg-Marquardt regularizer (if enabled)
            if lm_lambda > 0:
                n_vars = J_sparse.shape[0]
                diag_mod = sp.diags(np.full(n_vars, lm_lambda), format='csr')
                J_sparse = J_sparse + diag_mod

        mismatch = np.concatenate([dP[p_idx], dQ[q_idx]])

        try:
            if method == 'nk':
                dx, info = gmres(J_sparse, mismatch, rtol=1e-4, maxiter=20)
            else:
                dx = spsolve(J_sparse, mismatch)
        except Exception:
            if verbose: print(f"  [FAILED] Matrix solver exception at iteration {iteration + 1}.")
            converged = False
            break

        if np.isnan(dx).any() or np.isinf(dx).any():
            converged = False
            break

        n_p = len(p_idx)
        # Step Damping / Adaptive Backtracking
        alpha = 1.0
        if step_damping and iteration >= 2:
            if current_res > 1.5 * prev_residual:
                alpha = 0.25  # Severe mismatch increase -> strong damping
            elif current_res > prev_residual:
                alpha = 0.5   # Moderate mismatch increase -> half step
        prev_residual = current_res

        d_theta = np.clip(alpha * dx[:n_p], -0.35, 0.35)
        d_V = np.clip(alpha * dx[n_p:], -0.15, 0.15)

        theta[p_idx] += d_theta
        V[q_idx] += d_V
        V = np.clip(V, 0.35, 1.85)

    # If unconverged, restore the iterate with the lowest residual
    if not converged and best_res < 1e8 and best_dP is not None:
        V = best_V
        theta = best_theta
        max_dP = best_max_dP
        max_dQ = best_max_dQ
        dP = best_dP
        dQ = best_dQ

    V_complex = V * np.exp(1j * theta)
    I_inj = Ybus @ V_complex
    S_inj = V_complex * np.conj(I_inj)

    if converged and not ignore_q_tol:
        # Final strict validation: verify no generator is violating reactive power limits
        for i in range(n_buses):
            if original_bus_types[i] == 2 and (Q_max_bus[i] >= Q_min_bus[i] - 1e-4):
                q_g = S_inj.imag[i] + Q_load_bus[i]
                if q_g > Q_max_bus[i] + 1e-4 or q_g < Q_min_bus[i] - 1e-4:
                    if verbose:
                        print(f"  [{stage_name} FAILSAFE] Bus {bus_numbers[i]} violated Q limit: Qg = {q_g*base_mva:.2f} MVar (limits: [{Q_min_bus[i]*base_mva:.2f}, {Q_max_bus[i]*base_mva:.2f}] MVar)")
                    converged = False
                    break

    return {
        'converged': converged,
        'iterations': iterations,
        'iter_logs': iter_logs,
        'bus_numbers': bus_numbers,
        'V_mag': V,
        'V_angle': theta * 180.0 / np.pi,
        'theta_rad': theta,
        'best_V': best_V,
        'best_theta': best_theta,
        'best_res': best_res,
        'best_iter': best_iter,
        'P_inj_MW': S_inj.real * base_mva,
        'Q_inj_Mvar': S_inj.imag * base_mva,
        'max_dP': max_dP,
        'max_dQ': max_dQ,
        'dP': dP,
        'dQ': dQ,
        'p_idx': p_idx,
        'q_idx': q_idx
    }

def get_error_mismatch_diagnostics(res, bus_numbers, base_mva=100.0):
    """
    Analyzes unconverged solution and generates a prioritized report of top mismatch buses.
    """
    dP = res.get('dP')
    dQ = res.get('dQ')
    if dP is None or dQ is None:
        return "No mismatch vectors available for diagnostics."

    p_abs = np.abs(dP)
    q_abs = np.abs(dQ)
    
    top_p_indices = np.argsort(p_abs)[::-1][:5]
    top_q_indices = np.argsort(q_abs)[::-1][:5]

    lines = ["\n[DIAGNOSTIC ERROR MISMATCH ANALYSIS - TOP PROBLEM BUSES]"]
    lines.append("-" * 70)
    lines.append("  Top Active Power Mismatches (Max dP):")
    for rank, idx in enumerate(top_p_indices, 1):
        bnum = bus_numbers[idx]
        lines.append(f"    {rank}. Bus {bnum:<8}: dP = {dP[idx]:+.4f} p.u. ({dP[idx]*base_mva:+.2f} MW)")

    lines.append("  Top Reactive Power Mismatches (Max dQ):")
    for rank, idx in enumerate(top_q_indices, 1):
        bnum = bus_numbers[idx]
        lines.append(f"    {rank}. Bus {bnum:<8}: dQ = {dQ[idx]:+.4f} p.u. ({dQ[idx]*base_mva:+.2f} MVar)")
    lines.append("-" * 70)
    return "\n".join(lines)

def solve_andes(bus_data, branch_data, generators, loads, base_mva=100.0, method='nr', tol=1e-5, max_iter=30,
                ignore_q_tol=False, industry_std_pv=True, v_init_mode='flat', verbose=False,
                enable_fallback_pipeline=True, stage_max_iter=None,
                use_dc_angle_init=True, use_postponed_q_limits=True, use_step_damping=True,
                use_levenberg_marquardt=True, use_homotopy_ramping=True, use_diagnostics=True):
    """
    Solves power flow with automated Multi-Stage Robust Solver Fallback Pipeline:
    - Stage 0: Standard solver run (Initial or Flat)
    - Stage 1: Linear DC Power Flow Angle Pre-Conditioning
    - Stage 2: Postponed Q-Limits + Anti-Chattering Dwell Time + Step Damping
    - Stage 3: Levenberg-Marquardt Trust-Region Regularization
    - Stage 4: Homotopy Continuation Load Ramping (20% -> 50% -> 80% -> 100%)
    - Stage 5: Diagnostic Error Mismatch Reporting on Failure
    """
    try:
        from engines.custom_power_flow_solver import build_ybus
    except ImportError:
        from custom_power_flow_solver import build_ybus
    
    bus_numbers = sorted(bus_data.keys())
    n_buses = len(bus_numbers)
    bus_index_map = {b: i for i, b in enumerate(bus_numbers)}
    
    bus_types = np.ones(n_buses, dtype=int)
    V = np.ones(n_buses)
    theta = np.zeros(n_buses)
    P_sched = np.zeros(n_buses)
    Q_sched = np.zeros(n_buses)
    Q_load_bus = np.zeros(n_buses)
    Q_max_bus = np.zeros(n_buses)
    Q_min_bus = np.zeros(n_buses)
    V_setpoint = np.ones(n_buses)
    has_generator = np.zeros(n_buses, dtype=bool)

    is_flat_mode = (str(v_init_mode).lower().startswith('flat') or v_init_mode == 'flat')
    slack_idx = 0

    for b, d in bus_data.items():
        idx = bus_index_map[b]
        b_type = d.get('type', 1)
        bus_types[idx] = b_type
        if b_type == 3:
            slack_idx = idx

        if is_flat_mode:
            if b_type == 1:
                V[idx] = 1.0
                theta[idx] = 0.0
            else:
                V[idx] = d.get('V_set', d.get('V_init', 1.0))
                theta[idx] = 0.0
        else:
            raw_v = d.get('V_init', 1.0)
            try: raw_v_f = float(raw_v)
            except Exception: raw_v_f = 1.0
            if raw_v_f <= 0.0001: raw_v_f = 1.0
            V[idx] = raw_v_f
            theta[idx] = d.get('angle_init', 0.0) * np.pi / 180.0

    for l_num, l in loads.items():
        st = l.get('status', 1)
        if st != 0 and str(st).strip().lower() not in ('0', 'false', 'offline', 'disabled'):
            if l.get('scope', 'Both') == 'Short Circuit Only':
                continue
            idx = bus_index_map[l['bus']]
            q_dem = l.get('Q_demand', 0.0) / base_mva
            P_sched[idx] -= l.get('P_demand', 0.0) / base_mva
            Q_sched[idx] -= q_dem
            Q_load_bus[idx] += q_dem

    for g_num, g in generators.items():
        if g.get('status', 1) == 1:
            if g.get('scope', 'Both') == 'Short Circuit Only':
                continue
            idx = bus_index_map[g['bus']]
            has_generator[idx] = True
            P_sched[idx] += g.get('P_out', 0.0) / base_mva
            Q_sched[idx] += g.get('Q_out', 0.0) / base_mva
            q_max = g.get('Qmax')
            q_min = g.get('Qmin')
            if q_max is None: q_max = 9999.0
            if q_min is None: q_min = -9999.0
            Q_max_bus[idx] += float(q_max) / base_mva
            Q_min_bus[idx] += float(q_min) / base_mva
            V_setpoint[idx] = g.get('V_set', 1.0)

    warm_iters = 0
    if is_flat_mode and not ignore_q_tol:
        # Two-stage Flat Start: establish baseline operating angles and voltages via unconstrained solve
        Ybus_warm = build_ybus(bus_data, branch_data, bus_index_map, base_mva)
        res_warm = _solve_nr_core(
            Ybus_warm, bus_numbers, bus_types.copy(), V.copy(), theta.copy(), P_sched, Q_sched,
            Q_max_bus, Q_min_bus, V_setpoint, has_generator, original_bus_types=bus_types.copy(),
            base_mva=base_mva, method='nr', tol=1e-3, max_iter=min(15, int(max_iter)),
            ignore_q_tol=True, q_delay_iters=99, q_dwell_time=3,
            step_damping=True, lm_lambda=0.0, stage_name="Warm Start", verbose=verbose,
            Q_load_bus=Q_load_bus
        )
        if res_warm.get('converged', False):
            V = res_warm['V_mag'].copy()
            theta = res_warm['theta_rad'].copy()
            warm_iters = res_warm.get('iterations', 0)

    for i in range(n_buses):
        if bus_types[i] == 2:
            if not has_generator[i] or V_setpoint[i] <= 0.1:
                bus_types[i] = 1
            elif not ignore_q_tol and abs(Q_max_bus[i] - Q_min_bus[i]) < 1e-4:
                bus_types[i] = 1
                Q_sched[i] = Q_max_bus[i] - Q_load_bus[i]

    original_bus_types = bus_types.copy()
    for i in range(n_buses):
        if bus_types[i] in (2, 3) and has_generator[i] and V_setpoint[i] > 0:
            V[i] = V_setpoint[i]

    Ybus = build_ybus(bus_data, branch_data, bus_index_map, base_mva)
    if stage_max_iter is not None and int(stage_max_iter) > 0:
        stage_iters = min(int(max_iter), int(stage_max_iter))
    else:
        stage_iters = int(max_iter)

    # ─────────────────────────────────────────────────────────────────────────
    # STAGE 0: Standard Initial/Flat Solve (with gentle Q-delay)
    # ─────────────────────────────────────────────────────────────────────────
    if is_flat_mode:
        s0_q_delay = max(6, min(8, stage_iters // 3))
    else:
        s0_q_delay = min(max(2, stage_iters // 4), 4)
    res = _solve_nr_core(
        Ybus, bus_numbers, bus_types, V, theta, P_sched, Q_sched,
        Q_max_bus, Q_min_bus, V_setpoint, has_generator, original_bus_types,
        base_mva=base_mva, method=method, tol=tol, max_iter=stage_iters,
        ignore_q_tol=ignore_q_tol, q_delay_iters=s0_q_delay, q_dwell_time=3,
        step_damping=True, lm_lambda=0.0, stage_name="Stage 0 (Standard)", verbose=verbose,
        Q_load_bus=Q_load_bus
    )

    if res['converged'] or not enable_fallback_pipeline:
        res['iterations'] += warm_iters
        return res

    if verbose:
        print(f"\n  [INFO] Stage 0 did not meet tolerance within {stage_iters} iters. Cascading to Multi-Stage Fallback Pipeline...")

    # Preserve best state achieved so far to avoid artificial shock
    curr_V = res.get('best_V', res['V_mag']).copy()
    curr_theta = res.get('best_theta', res['theta_rad']).copy()

    # ─────────────────────────────────────────────────────────────────────────
    # STAGE 1: DC Power Flow Angle Pre-Conditioning
    # ─────────────────────────────────────────────────────────────────────────
    if use_dc_angle_init:
        if verbose:
            print("  [RECOVERY STAGE 1]: Computing linear DC angle initialization...")
        theta_dc = solve_dc_angles(bus_data, branch_data, P_sched, bus_index_map, slack_idx, base_mva)
        s1_q_delay = min(max(2, stage_iters // 4), 4)
        res_s1 = _solve_nr_core(
            Ybus, bus_numbers, bus_types, curr_V, theta_dc, P_sched, Q_sched,
            Q_max_bus, Q_min_bus, V_setpoint, has_generator, original_bus_types,
            base_mva=base_mva, method=method, tol=tol, max_iter=stage_iters,
            ignore_q_tol=ignore_q_tol, q_delay_iters=s1_q_delay, q_dwell_time=3,
            step_damping=True, lm_lambda=0.0, stage_name="Stage 1 (DC Angle)", verbose=verbose,
            Q_load_bus=Q_load_bus
        )
        if res_s1['converged']:
            if verbose: print(f"  [AUTO-RECOVERY SUCCESS] Converged using Stage 1 (DC Angle Pre-Conditioning) in {res_s1['iterations']} iterations!")
            return res_s1
        if not np.isnan(res_s1.get('best_V', res_s1['V_mag'])).any():
            curr_V = res_s1.get('best_V', res_s1['V_mag']).copy()
            curr_theta = res_s1.get('best_theta', res_s1['theta_rad']).copy()

    # ─────────────────────────────────────────────────────────────────────────
    # STAGE 2: Postponed Q-Limits + Anti-Chattering Dwell Time + Step Damping
    # ─────────────────────────────────────────────────────────────────────────
    if use_postponed_q_limits or use_step_damping:
        s2_q_delay = min(max(2, stage_iters // 4), 4)
        if verbose:
            print(f"  [RECOVERY STAGE 2]: Running with extended Q-delay ({s2_q_delay} iters) and step damping...")
        res_s2 = _solve_nr_core(
            Ybus, bus_numbers, bus_types, curr_V, curr_theta, P_sched, Q_sched,
            Q_max_bus, Q_min_bus, V_setpoint, has_generator, original_bus_types,
            base_mva=base_mva, method=method, tol=tol, max_iter=stage_iters,
            ignore_q_tol=ignore_q_tol, q_delay_iters=s2_q_delay, q_dwell_time=4,
            step_damping=True, lm_lambda=0.0, stage_name="Stage 2 (Damped + Q-Delay)", verbose=verbose,
            Q_load_bus=Q_load_bus
        )
        if res_s2['converged']:
            if verbose: print(f"  [AUTO-RECOVERY SUCCESS] Converged using Stage 2 (Damped NR + Q-Delay) in {res_s2['iterations']} iterations!")
            return res_s2
        if not np.isnan(res_s2.get('best_V', res_s2['V_mag'])).any():
            curr_V = res_s2.get('best_V', res_s2['V_mag']).copy()
            curr_theta = res_s2.get('best_theta', res_s2['theta_rad']).copy()

    # ─────────────────────────────────────────────────────────────────────────
    # STAGE 3: Levenberg-Marquardt Trust-Region Regularization (λI Damping)
    # ─────────────────────────────────────────────────────────────────────────
    if use_levenberg_marquardt:
        if verbose:
            print("  [RECOVERY STAGE 3]: Activating Levenberg-Marquardt Trust-Region Regularization (lambda=1e-3)...")
        s3_q_delay = min(max(2, stage_iters // 4), 3)
        res_s3 = _solve_nr_core(
            Ybus, bus_numbers, bus_types, curr_V, curr_theta, P_sched, Q_sched,
            Q_max_bus, Q_min_bus, V_setpoint, has_generator, original_bus_types,
            base_mva=base_mva, method=method, tol=tol, max_iter=stage_iters,
            ignore_q_tol=ignore_q_tol, q_delay_iters=s3_q_delay, q_dwell_time=4,
            step_damping=True, lm_lambda=1e-3, stage_name="Stage 3 (Levenberg-Marquardt)", verbose=verbose,
            Q_load_bus=Q_load_bus
        )
        if res_s3['converged']:
            if verbose: print(f"  [AUTO-RECOVERY SUCCESS] Converged using Stage 3 (Levenberg-Marquardt) in {res_s3['iterations']} iterations!")
            return res_s3
        if not np.isnan(res_s3.get('best_V', res_s3['V_mag'])).any():
            curr_V = res_s3.get('best_V', res_s3['V_mag']).copy()
            curr_theta = res_s3.get('best_theta', res_s3['theta_rad']).copy()

    # ─────────────────────────────────────────────────────────────────────────
    # STAGE 4: Homotopy Continuation Load Ramping (20% -> 50% -> 80% -> 100%)
    # ─────────────────────────────────────────────────────────────────────────
    if use_homotopy_ramping:
        if verbose:
            print("  [RECOVERY STAGE 4]: Executing Homotopy Continuation Load Ramping (20% -> 50% -> 80% -> 100%)...")
        ramp_factors = [0.20, 0.50, 0.80, 1.00]
        h_v = curr_V.copy()
        h_theta = curr_theta.copy()
        h_converged = True
        total_h_iters = 0
        h_max_iter = max(1, stage_iters // 2)
        s4_q_delay = min(max(2, h_max_iter // 4), 3)

        for r_factor in ramp_factors:
            p_ramp = P_sched * r_factor
            q_ramp = Q_sched * r_factor
            res_h = _solve_nr_core(
                Ybus, bus_numbers, bus_types, h_v, h_theta, p_ramp, q_ramp,
                Q_max_bus * r_factor, Q_min_bus * r_factor, V_setpoint, has_generator, original_bus_types,
                base_mva=base_mva, method=method, tol=tol, max_iter=h_max_iter,
                ignore_q_tol=ignore_q_tol, q_delay_iters=s4_q_delay, q_dwell_time=3,
                step_damping=True, lm_lambda=1e-4, stage_name=f"Homotopy {int(r_factor*100)}%", verbose=verbose,
                Q_load_bus=Q_load_bus * r_factor
            )
            total_h_iters += res_h['iterations']
            if not res_h['converged']:
                h_converged = False
                break
            h_v = res_h.get('best_V', res_h['V_mag'])
            h_theta = res_h.get('best_theta', res_h['theta_rad'])

        if h_converged:
            res_h['iterations'] = total_h_iters
            if verbose: print(f"  [AUTO-RECOVERY SUCCESS] Converged using Stage 4 (Homotopy Load Ramping) in {total_h_iters} total iterations!")
            return res_h

    # ─────────────────────────────────────────────────────────────────────────
    # STAGE 5: Diagnostic Error Mismatch Reporting
    # ─────────────────────────────────────────────────────────────────────────
    last_res = res_s3 if 'res_s3' in locals() else (res_s2 if 'res_s2' in locals() else (res_s1 if 'res_s1' in locals() else res))
    if use_diagnostics and verbose:
        diag_report = get_error_mismatch_diagnostics(last_res, bus_numbers, base_mva)
        print(diag_report)
        last_res['iter_logs'].append(diag_report)

    return last_res


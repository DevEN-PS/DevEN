import warnings
warnings.filterwarnings('ignore', category=UserWarning)
warnings.filterwarnings('ignore', category=RuntimeWarning)
try:
    from scipy.sparse.linalg import MatrixRankWarning
    warnings.filterwarnings('ignore', category=MatrixRankWarning)
except ImportError:
    pass

"""
DevEN (Develop Electric Network) - Custom Power Flow Solver Library
Fully-featured, standalone, and fast power flow engine using NumPy.
Supports:
- Newton-Raphson (NR) with PV-to-PQ conversion for Q limits
- Gauss-Seidel (GS) with acceleration factor
- Fast Decoupled Load Flow (FDLF - FDXB and FDBX modes)
"""

import numpy as np

def build_ybus(bus_data, branch_data, bus_index_map, base_mva=100.0):
    """
    Build the admittance matrix (Ybus) as a sparse CSR matrix.
    """
    import scipy.sparse as sp
    n_buses = len(bus_data)
    
    row = []
    col = []
    val = []
    
    # Shunts from bus data
    for bus_num, bus in bus_data.items():
        idx = bus_index_map[bus_num]
        g_shunt = bus.get('shunt_G', 0.0) / base_mva
        b_shunt = bus.get('shunt_B', 0.0) / base_mva
        y_sh = complex(g_shunt, b_shunt)
        if y_sh != 0:
            row.append(idx)
            col.append(idx)
            val.append(y_sh)
            
    # Branches (Lines and Transformers)
    for br in branch_data:
        if br.get('status', 1) == 0:
            continue
            
        f_idx = bus_index_map[br['from_bus']]
        t_idx = bus_index_map[br['to_bus']]
        r = br.get('r', 0.0)
        x = br.get('x', 0.0)
        b = br.get('b', 0.0)  # Shunt susceptance
        ratio = br.get('ratio', br.get('tap_ratio', 0.0))
        phase_shift_deg = br.get('phase_shift', 0.0)
        
        # Tap ratio and complex tap representation
        a = ratio if ratio != 0.0 else 1.0
        alpha = phase_shift_deg * np.pi / 180.0
        tap = a * np.exp(1j * alpha)
        
        # Standard threshold for near-zero impedance branches (switches/breakers/couplers)
        if abs(x) < 1e-4 and abs(r) < 1e-4:
            x = 1e-4 if x >= 0 else -1e-4

        z = complex(r, x)
        if z != 0:
            y = 1.0 / z
            y_shunt = complex(0.0, b / 2.0)
            
            # Diagonal
            row.append(f_idx)
            col.append(f_idx)
            val.append((y + y_shunt) / (a ** 2))
            
            row.append(t_idx)
            col.append(t_idx)
            val.append(y + y_shunt)
            
            # Off-diagonal
            row.append(f_idx)
            col.append(t_idx)
            val.append(-y / np.conj(tap))
            
            row.append(t_idx)
            col.append(f_idx)
            val.append(-y / tap)
            
    if not val:
        return sp.csr_matrix((n_buses, n_buses), dtype=complex)
        
    Ybus = sp.coo_matrix((val, (row, col)), shape=(n_buses, n_buses), dtype=complex)
    return Ybus.tocsr()

def eval_bus_zip_loads(V, P0, Q0, Zp, Ip, Pp, Zq, Iq, Pq, V0):
    """
    Evaluates polynomial ZIP load and voltage derivatives according to IEEE Std 3002.1 / IEEE Std 399.
    
    Equations:
      P_load(V) = P0 * [ Zp*(V/V0)^2 + Ip*(V/V0) + Pp ]
      Q_load(V) = Q0 * [ Zq*(V/V0)^2 + Iq*(V/V0) + Pq ]
      
      dP_load/dV = P0 * [ 2*Zp*V / (V0^2) + Ip / V0 ]
      dQ_load/dV = Q0 * [ 2*Zq*V / (V0^2) + Iq / V0 ]
    """
    v_safe = np.maximum(V, 1e-4)
    v0_safe = np.maximum(V0, 1e-4)
    v_ratio = v_safe / v0_safe
    
    P_load = P0 * (Zp * (v_ratio ** 2) + Ip * v_ratio + Pp)
    Q_load = Q0 * (Zq * (v_ratio ** 2) + Iq * v_ratio + Pq)
    
    dP_dV = P0 * (2.0 * Zp * v_safe / (v0_safe ** 2) + Ip / v0_safe)
    dQ_dV = Q0 * (2.0 * Zq * v_safe / (v0_safe ** 2) + Iq / v0_safe)
    
    return P_load, Q_load, dP_dV, dQ_dV


def adjust_discrete_ltc_taps(branch_data, V_mag, bus_index_map, deadband=0.015):
    """
    Adjusts discrete LTC transformer taps according to IEEE Std 3002.1.
    
    Standard discrete tap stepping with deadband to prevent hunting.
    Default step size: 0.00625 pu (5/8% for standard 32-step LTC)
    Deadband: +/-0.015 pu (prevents continuous cycling)
    
    Returns:
    --------
    changed : bool, True if at least one tap was adjusted
    logs : list of str
    """
    changed = False
    logs = []
    
    for br in branch_data:
        ratio = br.get('ratio', br.get('tap_ratio', 0.0))
        if ratio == 0.0:
            continue
            
        is_ltc = bool(br.get('is_ltc', False) or br.get('ltc_enabled', False) or br.get('auto_tap', False))
        if not is_ltc:
            continue
            
        if br.get('status', 1) == 0:
            continue
            
        f_bus = br['from_bus']
        t_bus = br['to_bus']
        ctrl_bus = br.get('controlled_bus', t_bus)
        if ctrl_bus not in bus_index_map:
            continue
            
        c_idx = bus_index_map[ctrl_bus]
        v_act = V_mag[c_idx]
        v_target = float(br.get('v_target', br.get('v_set', 1.0)))
        step = float(br.get('step_size', 0.00625))
        if step <= 0:
            step = 0.00625
        min_tap = float(br.get('min_tap', 0.90))
        max_tap = float(br.get('max_tap', 1.10))
        current_tap = float(br.get('ratio', br.get('tap_ratio', 1.0)))
        
        # Deadband check: if within [v_target - deadband, v_target + deadband], no change needed
        v_diff = v_act - v_target
        if abs(v_diff) <= deadband:
            continue
            
        # Direction: If controlled bus is 'to' bus: V_to ~ V_from / a.
        # So v_act < v_target -> tap should decrease.
        # If v_act > v_target -> tap should increase.
        if ctrl_bus == t_bus:
            tap_step_dir = 1.0 if v_diff > 0 else -1.0
        else:
            tap_step_dir = -1.0 if v_diff > 0 else 1.0
            
        new_tap = current_tap + tap_step_dir * step
        # Quantize to discrete steps
        num_steps = round((new_tap - 1.0) / step)
        new_tap = round(1.0 + num_steps * step, 5)
        new_tap = max(min_tap, min(max_tap, new_tap))
        
        if abs(new_tap - current_tap) > 1e-5:
            msg = (f"  [DevEN LTC] Transformer '{br.get('name', f'{f_bus}-{t_bus}')}' tap stepped: "
                   f"{current_tap:.5f} -> {new_tap:.5f} (Ctrl Bus {ctrl_bus} V={v_act:.4f} pu, target={v_target:.4f} pu)")
            br['ratio'] = new_tap
            br['tap_ratio'] = new_tap
            changed = True
            logs.append(msg)
            print(msg)
            
    return changed, logs


def solve_deven(bus_data, branch_data, generators, loads, base_mva=100.0, method='nr', 
                tol=1e-8, max_iter=10, accel=1.6, ignore_q_tol=False, v_init_mode='flat',
                enable_ltc=False, ltc_deadband=0.015, max_ltc_iter=10):
    """
    Main solver entry point for DevEN with full Q-limit enforcement (PV-to-PQ conversion & recovery).
    Complies with IEEE Std 3002.1:
      - Polynomial ZIP load modeling (Zp, Ip, Pp and Zq, Iq, Pq)
      - Discrete LTC transformer tap stepping with deadband
    Returns a rich dictionary containing solved voltages, angles, flows, and injections.
    """
    # 1. Build index mapping
    bus_numbers = sorted(bus_data.keys())
    bus_index_map = {bus_num: idx for idx, bus_num in enumerate(bus_numbers)}
    n_buses = len(bus_numbers)
    
    # 2. Extract active/reactive power loads and IEEE 3002.1 ZIP parameters
    P_load = np.zeros(n_buses)
    Q_load = np.zeros(n_buses)
    zip_Zp = np.zeros(n_buses)
    zip_Ip = np.zeros(n_buses)
    zip_Pp = np.ones(n_buses)
    zip_Zq = np.zeros(n_buses)
    zip_Iq = np.zeros(n_buses)
    zip_Pq = np.ones(n_buses)
    zip_V0 = np.ones(n_buses)
    
    p_weights = np.zeros(n_buses)
    q_weights = np.zeros(n_buses)
    has_zip_load = False

    for l in loads.values():
        st = l.get('status', 1)
        if st != 0 and str(st).strip().lower() not in ('0', 'false', 'offline', 'disabled'):
            if l.get('scope', 'Both') == 'Short Circuit Only':
                continue
            idx = bus_index_map[l['bus']]
            p_dem = l['P_demand'] / base_mva
            q_dem = l['Q_demand'] / base_mva
            P_load[idx] += p_dem
            Q_load[idx] += q_dem

            zp = float(l.get('zp', l.get('Z_p', 0.0)))
            ip = float(l.get('ip', l.get('I_p', 0.0)))
            pp = float(l.get('pp', l.get('P_p', 1.0)))
            zq = float(l.get('zq', l.get('Z_q', 0.0)))
            iq = float(l.get('iq', l.get('I_q', 0.0)))
            pq = float(l.get('pq', l.get('P_q', 1.0)))
            v0 = float(l.get('v0', l.get('V_0', 1.0)))
            if v0 <= 0:
                v0 = 1.0

            tot_p = zp + ip + pp
            if tot_p > 1e-6:
                zp, ip, pp = zp / tot_p, ip / tot_p, pp / tot_p
            else:
                zp, ip, pp = 0.0, 0.0, 1.0

            tot_q = zq + iq + pq
            if tot_q > 1e-6:
                zq, iq, pq = zq / tot_q, iq / tot_q, pq / tot_q
            else:
                zq, iq, pq = 0.0, 0.0, 1.0

            if abs(zp) > 1e-5 or abs(ip) > 1e-5 or abs(zq) > 1e-5 or abs(iq) > 1e-5:
                has_zip_load = True

            p_abs = abs(p_dem)
            q_abs = abs(q_dem)
            p_weights[idx] += p_abs
            q_weights[idx] += q_abs

            if p_weights[idx] > 1e-6:
                w = p_abs / p_weights[idx]
                zip_Zp[idx] = (1.0 - w) * zip_Zp[idx] + w * zp
                zip_Ip[idx] = (1.0 - w) * zip_Ip[idx] + w * ip
                zip_Pp[idx] = (1.0 - w) * zip_Pp[idx] + w * pp
            if q_weights[idx] > 1e-6:
                w = q_abs / q_weights[idx]
                zip_Zq[idx] = (1.0 - w) * zip_Zq[idx] + w * zq
                zip_Iq[idx] = (1.0 - w) * zip_Iq[idx] + w * iq
                zip_Pq[idx] = (1.0 - w) * zip_Pq[idx] + w * pq
            zip_V0[idx] = v0

    zip_params = (P_load, Q_load, zip_Zp, zip_Ip, zip_Pp, zip_Zq, zip_Iq, zip_Pq, zip_V0) if has_zip_load else None

            
    # 3. Extract generator settings & limits
    P_gen_sched = np.zeros(n_buses)
    V_setpoint = np.zeros(n_buses)
    Q_max_bus = np.zeros(n_buses)
    Q_min_bus = np.zeros(n_buses)
    Q_gen_sched = np.zeros(n_buses)
    has_generator = np.zeros(n_buses, dtype=bool)
    
    for g in generators.values():
        if g.get('status', 1) == 1:
            if g.get('scope', 'Both') == 'Short Circuit Only':
                continue
            idx = bus_index_map[g['bus']]
            has_generator[idx] = True
            P_gen_sched[idx] += g.get('P_out', 0.0) / base_mva
            V_setpoint[idx] = g.get('V_set', 1.0)
            q_max = g.get('Qmax')
            q_min = g.get('Qmin')
            if q_max is None: q_max = 9999.0
            if q_min is None: q_min = -9999.0
            Q_max_bus[idx] += q_max / base_mva
            Q_min_bus[idx] += q_min / base_mva
            # If bus is PQ, generator injects fixed Q_out; if Qmin == Qmax, fixed Q output
            b_type = bus_data.get(g['bus'], {}).get('type', 1)
            if b_type == 1:
                Q_gen_sched[idx] += float(g.get('Q_out', 0.0)) / base_mva
            elif abs(q_max - q_min) < 1e-4:
                Q_gen_sched[idx] += float(g.get('Q_out', q_max)) / base_mva
            
    # 4. Extract bus types & initial voltages
    bus_types = np.zeros(n_buses, dtype=int)
    V = np.zeros(n_buses)
    theta = np.zeros(n_buses)
    
    is_flat_mode = (str(v_init_mode).lower().startswith('flat') or v_init_mode == 'flat')
    for bus_num, bus in bus_data.items():
        idx = bus_index_map[bus_num]
        b_type = bus.get('type', 1)
        bus_types[idx] = b_type
        if is_flat_mode:
            if b_type == 1:
                V[idx] = 1.0
                theta[idx] = 0.0
            else:
                V[idx] = bus.get('V_set', bus.get('V_init', 1.0))
                theta[idx] = 0.0
        else:
            raw_v = bus.get('V_init', 1.0)
            try:
                raw_v_f = float(raw_v)
            except (ValueError, TypeError):
                raw_v_f = 1.0
            if raw_v_f <= 0.0001:
                raw_v_f = 1.0
            V[idx] = raw_v_f
            theta[idx] = bus.get('angle_init', 0.0) * np.pi / 180.0
    
    warm_iters = 0
    if is_flat_mode and not ignore_q_tol:
        # Two-stage Flat Start: establish baseline operating angles and voltages via unconstrained solve
        Ybus_warm = build_ybus(bus_data, branch_data, bus_index_map, base_mva)
        bus_types_warm = bus_types.copy()
        res_warm = solve_nr(
            Ybus_warm, bus_types_warm, V.copy(), theta.copy(), P_load, Q_load, Q_gen_sched, P_gen_sched,
            Q_max_bus, Q_min_bus, V_setpoint, has_generator, tol=1e-3, max_iter=min(15, max_iter),
            ignore_q_tol=True, bus_numbers=bus_numbers, base_mva=base_mva, zip_params=zip_params
        )
        if len(res_warm) >= 3 and res_warm[2]:
            V = res_warm[0].copy()
            theta = res_warm[1].copy()
            warm_iters = res_warm[3]

    # Downgrade PV buses with no active generator or fixed Q limits to PQ
    for i in range(n_buses):
        if bus_types[i] == 2:
            if not has_generator[i] or V_setpoint[i] <= 0.1:
                bus_types[i] = 1
            elif not ignore_q_tol and abs(Q_max_bus[i] - Q_min_bus[i]) < 1e-4:
                # Generator has fixed Q output (Qmin == Qmax) -> cannot regulate voltage -> treat as PQ
                bus_types[i] = 1
        
    # 5. Build admittance matrix & solve with optional discrete LTC outer loop
    has_any_ltc = enable_ltc or any(
        bool(br.get('is_ltc') or br.get('ltc_enabled') or br.get('auto_tap'))
        for br in branch_data if br.get('ratio', br.get('tap_ratio', 0.0)) != 0.0
    )
    
    ltc_iter = 0
    max_ltc_passes = max_ltc_iter if has_any_ltc else 1

    while ltc_iter < max_ltc_passes:
        ltc_iter += 1
        Ybus = build_ybus(bus_data, branch_data, bus_index_map, base_mva)
        
        # Check for isolated/disconnected buses (zero connected branches)
        row_nnz = Ybus.getnnz(axis=1)
        isolated_buses = np.where(row_nnz == 0)[0]
        if len(isolated_buses) > 0:
            bus_types[isolated_buses] = 4

        # 6. Execute solver
        converged = False
        iterations = 0
        max_dP = 0.0
        max_dQ = 0.0
        
        if method in ('nr', 'deven', 'default', ''):
            res_nr = solve_nr(
                Ybus, bus_types, V, theta, P_load, Q_load, Q_gen_sched, P_gen_sched,
                Q_max_bus, Q_min_bus, V_setpoint, has_generator, tol, max_iter, ignore_q_tol,
                bus_numbers=bus_numbers, base_mva=base_mva, zip_params=zip_params
            )
            if len(res_nr) >= 6:
                V, theta, converged, iterations, max_dP, max_dQ = res_nr[:6]
            else:
                V, theta, converged, iterations = res_nr[:4]
        elif method == 'gs':
            res_gs = solve_gs(
                Ybus, bus_types, V, theta, P_load, Q_load, Q_gen_sched, P_gen_sched,
                Q_max_bus, Q_min_bus, V_setpoint, has_generator, tol, max_iter, accel,
                bus_numbers=bus_numbers, base_mva=base_mva, ignore_q_tol=ignore_q_tol, zip_params=zip_params
            )
            if len(res_gs) >= 6:
                V, theta, converged, iterations, max_dP, max_dQ = res_gs[:6]
            else:
                V, theta, converged, iterations = res_gs[:4]
        elif method in ('fdxb', 'fdbx'):
            res_fd = solve_fdlf(
                Ybus, bus_types, V, theta, P_load, Q_load, Q_gen_sched, P_gen_sched,
                Q_max_bus, Q_min_bus, V_setpoint, has_generator, bus_data, branch_data,
                bus_index_map, tol, max_iter, fdlf_type=method,
                bus_numbers=bus_numbers, base_mva=base_mva,
                ignore_q_tol=ignore_q_tol, zip_params=zip_params
            )
            if len(res_fd) >= 6:
                V, theta, converged, iterations, max_dP, max_dQ = res_fd[:6]
            else:
                V, theta, converged, iterations = res_fd[:4]
        else:
            raise ValueError(f"Unknown solver method: {method}")

        if not converged:
            break

        if has_any_ltc:
            taps_changed, _ = adjust_discrete_ltc_taps(
                branch_data, V, bus_index_map, deadband=ltc_deadband
            )
            if not taps_changed:
                break
        
    # 7. Compute outputs
    V_complex = V * np.exp(1j * theta)
    I_inj = Ybus @ V_complex
    S_inj = V_complex * np.conj(I_inj)
    
    # Active/reactive injections in MW/Mvar
    P_inj_MW = S_inj.real * base_mva
    Q_inj_Mvar = S_inj.imag * base_mva
    
    # Compute branch flows
    flows = []
    for br in branch_data:
        f_idx = bus_index_map[br['from_bus']]
        t_idx = bus_index_map[br['to_bus']]
        Vf = V_complex[f_idx]
        Vt = V_complex[t_idx]
        
        r, x, b = br.get('r', 0.0), br.get('x', 0.0), br.get('b', 0.0)
        ratio = br.get('ratio', br.get('tap_ratio', 0.0))
        phase_shift_deg = br.get('phase_shift', 0.0)
        
        a = ratio if ratio != 0.0 else 1.0
        alpha = phase_shift_deg * np.pi / 180.0
        tap = a * np.exp(1j * alpha)
        
        z = complex(r, x)
        y = 1.0 / z if z != 0 else 0.0
        y_shunt = complex(0.0, b / 2.0)
        
        # Current from and to
        if ratio != 0.0:  # Transformer
            # From side current
            If_fwd = (Vf / tap - Vt) * y / np.conj(tap)
            S_fwd = Vf * np.conj(If_fwd)
            # To side current
            If_rev = (Vt - Vf / tap) * y
            S_rev = Vt * np.conj(If_rev)
        else:  # Line
            If_fwd = (Vf - Vt) * y + Vf * y_shunt
            S_fwd = Vf * np.conj(If_fwd)
            
            If_rev = (Vt - Vf) * y + Vt * y_shunt
            S_rev = Vt * np.conj(If_rev)
            
        losses = S_fwd + S_rev
        rateA = br.get('rateA', 9999) or 9999
        loading_pct = (abs(S_fwd) * base_mva) / rateA * 100 if rateA > 0 else 0.0
        
        flows.append({
            'from_bus': br['from_bus'],
            'to_bus': br['to_bus'],
            'P_fwd_MW': S_fwd.real * base_mva,
            'Q_fwd_Mvar': S_fwd.imag * base_mva,
            'P_rev_MW': S_rev.real * base_mva,
            'Q_rev_Mvar': S_rev.imag * base_mva,
            'losses_MW': losses.real * base_mva,
            'loading_pct': loading_pct,
            'type': 'transformer' if ratio != 0.0 else 'line'
        })
        
    if zip_params is not None:
        P_load_final, Q_load_final, _, _ = eval_bus_zip_loads(V, *zip_params)
    else:
        P_load_final, Q_load_final = P_load, Q_load
        
    P_gen_MW = P_inj_MW + (P_load_final * base_mva)
    Q_gen_Mvar = Q_inj_Mvar + (Q_load_final * base_mva)
    return {
        'converged': converged,
        'iterations': warm_iters + iterations,
        'bus_numbers': bus_numbers,
        'V_mag': V,
        'V_angle': theta * 180.0 / np.pi,
        'P_inj_MW': P_inj_MW,
        'Q_inj_Mvar': Q_inj_Mvar,
        'P_load_MW': P_load_final * base_mva,
        'Q_load_Mvar': Q_load_final * base_mva,
        'P_gen': P_gen_MW,
        'Q_gen': Q_gen_Mvar,
        'flows': flows,
        'Ybus': Ybus,
        'max_dP': max_dP,
        'max_dQ': max_dQ
    }

def solve_nr(Ybus, bus_types, V, theta, P_load, Q_load, Q_gen_sched, P_gen_sched, Q_max_bus, Q_min_bus, V_setpoint, has_generator, tol, max_iter, ignore_q_tol=False, bus_numbers=None, base_mva=100.0, zip_params=None):
    import scipy.sparse as sp
    from scipy.sparse.linalg import spsolve
    
    iter_logs = []
    n_buses = len(bus_types)
    if bus_numbers is None:
        bus_numbers = [i + 1 for i in range(n_buses)]
        
    P_sched = P_gen_sched - P_load
    Q_sched = Q_gen_sched - Q_load
    original_bus_types = bus_types.copy()
    active_types = bus_types.copy()
    q_limit_status = np.zeros(n_buses, dtype=int)  # 0: PV normal, 1: Qmax clamped, -1: Qmin clamped
    q_dwell_counter = np.zeros(n_buses, dtype=int)
    q_dwell_time = 3
    max_dP = 0.0
    max_dQ = 0.0
    prev_residual = 1e9

    best_res = 1e9
    best_V = V.copy()
    best_theta = theta.copy()
    best_max_dP = 1e9
    best_max_dQ = 1e9
    best_iter = 1

    # Set generator setpoints
    for i in range(n_buses):
        if active_types[i] in (2, 3) and has_generator[i] and V_setpoint[i] > 0:
            V[i] = V_setpoint[i]
            
    for iteration in range(max_iter):
        q_dwell_counter = np.maximum(0, q_dwell_counter - 1)
        if zip_params is not None:
            P_load_curr, Q_load_curr, dP_load_dV, dQ_load_dV = eval_bus_zip_loads(V, *zip_params)
            P_sched = P_gen_sched - P_load_curr
            Q_sched = Q_gen_sched - Q_load_curr
            for i in range(n_buses):
                if q_limit_status[i] == 1:
                    Q_sched[i] = Q_max_bus[i] - Q_load_curr[i]
                elif q_limit_status[i] == -1:
                    Q_sched[i] = Q_min_bus[i] - Q_load_curr[i]
            curr_q_load = Q_load_curr
        else:
            curr_q_load = Q_load

        V_complex = V * np.exp(1j * theta)
        I_calc = Ybus.dot(V_complex)
        S_calc = V_complex * np.conj(I_calc)
        P_calc = S_calc.real
        Q_calc = S_calc.imag
        
        # Check PV generator limits (evaluated after initial power mismatch has settled)
        type_changed = False
        if not ignore_q_tol and iteration >= 2 and (max_dP < 0.05 or iteration >= 8):
            q_violations = []
            for i in range(n_buses):
                if original_bus_types[i] == 2 and (Q_max_bus[i] > Q_min_bus[i] + 1e-4):  # Originally a regulating PV Bus
                    Q_gen = Q_calc[i] + curr_q_load[i]
                    if active_types[i] == 2:
                        if Q_gen > Q_max_bus[i] + 1e-5:
                            viol = Q_gen - Q_max_bus[i]
                            q_violations.append((viol, i, 1, Q_max_bus[i] - curr_q_load[i],
                                                 f"  [DevEN Q-LIMIT] Bus {bus_numbers[i]} reached Qmax ({Q_gen*base_mva:.2f} > {Q_max_bus[i]*base_mva:.2f} MVar) -> Converted PV to PQ"))
                        elif Q_gen < Q_min_bus[i] - 1e-5:
                            viol = Q_min_bus[i] - Q_gen
                            q_violations.append((viol, i, -1, Q_min_bus[i] - curr_q_load[i],
                                                 f"  [DevEN Q-LIMIT] Bus {bus_numbers[i]} reached Qmin ({Q_gen*base_mva:.2f} < {Q_min_bus[i]*base_mva:.2f} MVar) -> Converted PV to PQ"))
                    elif active_types[i] == 1:
                        # Test for recovery back to PV only if dwell lock has expired AND network has settled
                        if q_dwell_counter[i] == 0 and max_dP < 0.01 and max_dQ < 0.05:
                            if q_limit_status[i] == 1 and V[i] > V_setpoint[i] + 0.02:
                                active_types[i] = 2  # Revert to PV
                                q_limit_status[i] = 0
                                V[i] = V_setpoint[i]
                                type_changed = True
                                log_msg = f"  [DevEN Q-RECOVERY] Bus {bus_numbers[i]} voltage recovered ({V[i]:.4f} > {V_setpoint[i]:.4f} pu) -> Reverted PQ to PV"
                                print(log_msg)
                                iter_logs.append(log_msg)
                            elif q_limit_status[i] == -1 and V[i] < V_setpoint[i] - 0.02:
                                active_types[i] = 2  # Revert to PV
                                q_limit_status[i] = 0
                                V[i] = V_setpoint[i]
                                type_changed = True
                                log_msg = f"  [DevEN Q-RECOVERY] Bus {bus_numbers[i]} voltage dropped ({V[i]:.4f} < {V_setpoint[i]:.4f} pu) -> Reverted PQ to PV"
                                print(log_msg)
                                iter_logs.append(log_msg)

            # Gradual conversion of top violators
            if q_violations:
                q_violations.sort(key=lambda x: x[0], reverse=True)
                max_conv = max(10, min(35, n_buses // 100))
                for viol, i, status, q_target, log_msg in q_violations[:max_conv]:
                    active_types[i] = 1
                    q_limit_status[i] = status
                    q_dwell_counter[i] = q_dwell_time
                    Q_sched[i] = q_target
                    type_changed = True
                    print(log_msg)
                    iter_logs.append(log_msg)
                        
        if type_changed:
            # Recompute injections
            V_complex = V * np.exp(1j * theta)
            I_calc = Ybus.dot(V_complex)
            S_calc = V_complex * np.conj(I_calc)
            P_calc = S_calc.real
            Q_calc = S_calc.imag
            
        dP = P_sched - P_calc
        dQ = Q_sched - Q_calc
        
        p_idx = np.where(np.isin(active_types, [1, 2]))[0]
        q_idx = np.where(active_types == 1)[0]
        max_dP = np.max(np.abs(dP[p_idx])) if len(p_idx) > 0 else 0.0
        max_dQ = np.max(np.abs(dQ[q_idx])) if len(q_idx) > 0 else 0.0
        p_max_idx = p_idx[np.argmax(np.abs(dP[p_idx]))] if len(p_idx) > 0 else 0
        q_max_idx = q_idx[np.argmax(np.abs(dQ[q_idx]))] if len(q_idx) > 0 else 0
        
        current_res = max(max_dP, max_dQ) if not ignore_q_tol else max_dP
        if current_res < best_res:
            best_res = current_res
            best_V = V.copy()
            best_theta = theta.copy()
            best_max_dP = max_dP
            best_max_dQ = max_dQ
            best_iter = iteration + 1

        log_str = f"  Iter {iteration + 1:2d} [DevEN NR]: Max |dP| = {max_dP:.6f} p.u. (Bus {bus_numbers[p_max_idx]}), Max |dQ| = {max_dQ:.6f} p.u. (Bus {bus_numbers[q_max_idx]})"
        print(log_str)
        iter_logs.append(log_str)
        
        # Check for numerical instability (NaN/Inf)
        if np.isnan(max_dP) or np.isnan(max_dQ) or np.isinf(max_dP) or np.isinf(max_dQ):
            print(f"\n  ❌ [FAILED] Numerical instability (NaN detected in power mismatch) at iteration {iteration + 1}.")
            return V, theta, False, iteration + 1, 999.0, 999.0, iter_logs

        q_cond = (max_dQ < tol) if not ignore_q_tol else True
        if not type_changed and max_dP < tol and q_cond:
            # ── STRICT Q-LIMIT VERIFICATION GUARD ──
            # Before declaring convergence, verify that no PV generator violates its reactive limits.
            unresolved_q_violation = False
            if not ignore_q_tol:
                for i in range(n_buses):
                    if original_bus_types[i] == 2 and active_types[i] == 2 and (Q_max_bus[i] > Q_min_bus[i] + 1e-4):
                        Q_gen = Q_calc[i] + curr_q_load[i]
                        if Q_gen > Q_max_bus[i] + 1e-5:
                            active_types[i] = 1  # Convert to PQ
                            q_limit_status[i] = 1
                            q_dwell_counter[i] = q_dwell_time
                            Q_sched[i] = Q_max_bus[i] - curr_q_load[i]
                            type_changed = True
                            unresolved_q_violation = True
                            log_msg = f"  [DevEN Q-LIMIT] Bus {bus_numbers[i]} reached Qmax ({Q_gen*base_mva:.2f} > {Q_max_bus[i]*base_mva:.2f} MVar) -> Converted PV to PQ"
                            print(log_msg)
                            iter_logs.append(log_msg)
                        elif Q_gen < Q_min_bus[i] - 1e-5:
                            active_types[i] = 1  # Convert to PQ
                            q_limit_status[i] = -1
                            q_dwell_counter[i] = q_dwell_time
                            Q_sched[i] = Q_min_bus[i] - curr_q_load[i]
                            type_changed = True
                            unresolved_q_violation = True
                            log_msg = f"  [DevEN Q-LIMIT] Bus {bus_numbers[i]} reached Qmin ({Q_gen*base_mva:.2f} < {Q_min_bus[i]*base_mva:.2f} MVar) -> Converted PV to PQ"
                            print(log_msg)
                            iter_logs.append(log_msg)

            if unresolved_q_violation:
                continue

            print(f"\n  [CONVERGED] Solution converged in {iteration + 1} iterations (Tolerance: {tol:.1e})")
            return V, theta, True, iteration + 1, max_dP, max_dQ, iter_logs
            
        # Fast Vectorized Jacobian construction:
        diag_V = sp.diags(V_complex)
        diag_I_conj = sp.diags(np.conj(I_calc))
        diag_V_norm = sp.diags(V_complex / V)  # exp(j * theta)
        
        # dS/dtheta and dS/dV complex derivatives
        dS_dtheta = 1j * diag_V @ (diag_I_conj - Ybus.conj() @ diag_V.conj())
        dS_dV = diag_V @ Ybus.conj() @ diag_V_norm.conj() + diag_V_norm @ diag_I_conj
        
        # Split into real (P) and imaginary (Q) components
        H = dS_dtheta.real
        N = dS_dV.real
        J = dS_dtheta.imag
        L = dS_dV.imag
        
        # Slices to match equation variables (p_idx for theta, q_idx for V)
        H_sliced = H[p_idx, :][:, p_idx]
        N_sliced = N[p_idx, :][:, q_idx]
        J_sliced = J[q_idx, :][:, p_idx]
        L_sliced = L[q_idx, :][:, q_idx]
        
        # Add IEEE 3002.1 ZIP load derivatives to Jacobian diagonal blocks
        if zip_params is not None:
            p_pos = {b: k for k, b in enumerate(p_idx)}
            row_N = [p_pos[b] for b in q_idx if b in p_pos]
            col_N = [k for k, b in enumerate(q_idx) if b in p_pos]
            data_N = [dP_load_dV[b] for b in q_idx if b in p_pos]
            if data_N:
                adj_N = sp.coo_matrix((data_N, (row_N, col_N)), shape=N_sliced.shape, dtype=float).tocsr()
                N_sliced = N_sliced + adj_N

            diag_L_adj = np.array([dQ_load_dV[b] for b in q_idx], dtype=float)
            if np.any(diag_L_adj != 0):
                L_sliced = L_sliced + sp.diags(diag_L_adj, format='csr')

        # Stack blocks using scipy.sparse.bmat
        J_sparse = sp.bmat([
            [H_sliced, N_sliced],
            [J_sliced, L_sliced]
        ], format='csr')
        
        mismatch = np.concatenate([dP[p_idx], dQ[q_idx]])
        try:
            dx = spsolve(J_sparse, mismatch)
        except Exception:
            print(f"\n  [FAILED] Singular Jacobian matrix at iteration {iteration + 1}.")
            return V, theta, False, iteration + 1, max_dP, max_dQ, iter_logs
            
        if np.isnan(dx).any() or np.isinf(dx).any():
            print(f"\n  ❌ [FAILED] Matrix solution produced NaN/Inf at iteration {iteration + 1}.")
            return V, theta, False, iteration + 1, max_dP, max_dQ, iter_logs

        n_p = len(p_idx)
        # Step Damping / Adaptive Backtracking
        alpha = 1.0
        if iteration >= 2:
            if current_res > 1.5 * prev_residual:
                alpha = 0.25  # Severe mismatch increase -> strong damping
            elif current_res > prev_residual:
                alpha = 0.5   # Moderate mismatch increase -> half step
        prev_residual = current_res

        d_theta = np.clip(alpha * dx[:n_p], -0.3, 0.3)
        d_V = np.clip(alpha * dx[n_p:], -0.15, 0.15)
        
        theta[p_idx] += d_theta
        V[q_idx] += d_V
        V = np.clip(V, 0.4, 1.8)
        
    if best_res < 1e8:
        V = best_V
        theta = best_theta
        max_dP = best_max_dP
        max_dQ = best_max_dQ

    print(f"\n  [NOT CONVERGED] Exceeded maximum iterations ({max_iter}) without meeting tolerance ({tol:.1e}). Best Max |dP|={max_dP:.6f}, Max |dQ|={max_dQ:.6f}")
    return V, theta, False, max_iter, max_dP, max_dQ, iter_logs

def solve_gs(Ybus, bus_types, V, theta, P_load, Q_load, Q_gen_sched, P_gen_sched, Q_max_bus, Q_min_bus, V_setpoint, has_generator, tol, max_iter, accel=1.6, bus_numbers=None, base_mva=100.0, ignore_q_tol=False, zip_params=None):
    n_buses = len(bus_types)
    if bus_numbers is None:
        bus_numbers = [i + 1 for i in range(n_buses)]
        
    P_sched = P_gen_sched - P_load
    Q_sched = Q_gen_sched - Q_load
    original_bus_types = bus_types.copy()
    active_types = bus_types.copy()
    q_limit_status = np.zeros(n_buses, dtype=int)
    q_dwell_counter = np.zeros(n_buses, dtype=int)
    q_dwell_time = 3
    V_complex = V * np.exp(1j * theta)
    
    for i in range(n_buses):
        if active_types[i] in (2, 3) and has_generator[i] and V_setpoint[i] > 0:
            V_complex[i] = V_setpoint[i] * np.exp(1j * theta[i])
            
    max_dP = 0.0
    max_dQ = 0.0

    for iteration in range(max_iter):
        q_dwell_counter = np.maximum(0, q_dwell_counter - 1)
        V_old = V_complex.copy()
        if zip_params is not None:
            P_load_curr, Q_load_curr, _, _ = eval_bus_zip_loads(np.abs(V_complex), *zip_params)
            P_sched = P_gen_sched - P_load_curr
            curr_q_load = Q_load_curr
        else:
            curr_q_load = Q_load
        
        for i in range(n_buses):
            if active_types[i] not in (1, 2):
                continue
                
            if original_bus_types[i] == 2 and (Q_max_bus[i] >= Q_min_bus[i] - 1e-4):
                I_sum = np.sum(Ybus[i] * V_complex)
                Q_calc = -np.imag(np.conj(V_complex[i]) * I_sum)
                Q_gen = Q_calc + curr_q_load[i]
                
                if not ignore_q_tol and iteration >= 2:
                    if active_types[i] == 2:
                        if Q_gen > Q_max_bus[i] + 1e-5:
                            Q_sched[i] = Q_max_bus[i] - curr_q_load[i]
                            active_types[i] = 1
                            q_limit_status[i] = 1
                            q_dwell_counter[i] = q_dwell_time
                            print(f"  [DevEN GS Q-LIMIT] Bus {bus_numbers[i]} reached Qmax ({Q_gen*base_mva:.2f} > {Q_max_bus[i]*base_mva:.2f} MVar) -> Converted PV to PQ")
                        elif Q_gen < Q_min_bus[i] - 1e-5:
                            Q_sched[i] = Q_min_bus[i] - curr_q_load[i]
                            active_types[i] = 1
                            q_limit_status[i] = -1
                            q_dwell_counter[i] = q_dwell_time
                            print(f"  [DevEN GS Q-LIMIT] Bus {bus_numbers[i]} reached Qmin ({Q_gen*base_mva:.2f} < {Q_min_bus[i]*base_mva:.2f} MVar) -> Converted PV to PQ")
                        else:
                            Q_sched[i] = Q_calc
                    elif active_types[i] == 1:
                        if q_dwell_counter[i] == 0:
                            v_mag_curr = np.abs(V_complex[i])
                            if q_limit_status[i] == 1 and v_mag_curr > V_setpoint[i] + 0.02:
                                active_types[i] = 2
                                q_limit_status[i] = 0
                                print(f"  [DevEN GS Q-RECOVERY] Bus {bus_numbers[i]} voltage recovered -> Reverted PQ to PV")
                            elif q_limit_status[i] == -1 and v_mag_curr < V_setpoint[i] - 0.02:
                                active_types[i] = 2
                                q_limit_status[i] = 0
                                print(f"  [DevEN GS Q-RECOVERY] Bus {bus_numbers[i]} voltage dropped -> Reverted PQ to PV")
                else:
                    Q_sched[i] = Q_calc
                    
            sum_Y_V = np.sum(Ybus[i] * V_complex) - Ybus[i, i] * V_complex[i]
            V_new_raw = ((P_sched[i] - 1j * Q_sched[i]) / np.conj(V_complex[i]) - sum_Y_V) / Ybus[i, i]
            
            if active_types[i] == 1:
                V_complex[i] = V_complex[i] + accel * (V_new_raw - V_complex[i])
            elif active_types[i] == 2:
                V_mag = V_setpoint[i] if V_setpoint[i] > 0 else V[i]
                theta_new = np.angle(V_new_raw)
                V_complex[i] = V_mag * np.exp(1j * theta_new)
                
        max_diff = np.max(np.abs(V_complex - V_old))
        if max_diff < tol:
            I_calc = Ybus.dot(V_complex)
            S_calc = V_complex * np.conj(I_calc)
            p_idx = np.where(active_types != 3)[0]
            q_idx = np.where(active_types == 1)[0]
            max_dP = np.max(np.abs((P_sched - S_calc.real)[p_idx])) if len(p_idx) > 0 else 0.0
            max_dQ = np.max(np.abs((Q_sched - S_calc.imag)[q_idx])) if len(q_idx) > 0 else 0.0
            return np.abs(V_complex), np.angle(V_complex), True, iteration + 1, max_dP, max_dQ
            
    I_calc = Ybus.dot(V_complex)
    S_calc = V_complex * np.conj(I_calc)
    p_idx = np.where(active_types != 3)[0]
    q_idx = np.where(active_types == 1)[0]
    max_dP = np.max(np.abs((P_sched - S_calc.real)[p_idx])) if len(p_idx) > 0 else 0.0
    max_dQ = np.max(np.abs((Q_sched - S_calc.imag)[q_idx])) if len(q_idx) > 0 else 0.0
    return np.abs(V_complex), np.angle(V_complex), False, max_iter, max_dP, max_dQ

def build_fdlf_matrices(bus_data, branch_data, bus_index_map, active_types, fdlf_type='fdxb', base_mva=100.0):
    import scipy.sparse as sp
    n_buses = len(bus_data)
    
    p_idx = np.where(np.isin(active_types, [1, 2]))[0]
    n_p = len(p_idx)
    p_map = {bus_i: eq_i for eq_i, bus_i in enumerate(p_idx)}
    
    q_idx = np.where(active_types == 1)[0]
    n_q = len(q_idx)
    q_map = {bus_i: eq_i for eq_i, bus_i in enumerate(q_idx)}
    
    # Accumulators for Bprime
    bp_row = []
    bp_col = []
    bp_val = []
    
    # Build Bprime
    for br in branch_data:
        if br.get('status', 1) == 0:
            continue
        f_idx = bus_index_map[br['from_bus']]
        t_idx = bus_index_map[br['to_bus']]
        r = br['r']
        x = br['x']
        ratio = br.get('ratio', 1.0)
        if ratio == 0.0:
            ratio = 1.0
            
        if fdlf_type == 'fdxb':
            b_val = -1.0 / x if x != 0 else 0.0
        else:
            z2 = r**2 + x**2
            b_val = -x / z2 if z2 != 0 else 0.0
            b_val = b_val / ratio
            
        if f_idx in p_map and t_idx in p_map:
            rf = p_map[f_idx]
            rt = p_map[t_idx]
            bp_row.extend([rf, rt, rf, rt])
            bp_col.extend([rt, rf, rf, rt])
            bp_val.extend([-b_val, -b_val, b_val, b_val])
        elif f_idx in p_map:
            rf = p_map[f_idx]
            bp_row.append(rf)
            bp_col.append(rf)
            bp_val.append(b_val)
        elif t_idx in p_map:
            rt = p_map[t_idx]
            bp_row.append(rt)
            bp_col.append(rt)
            bp_val.append(b_val)
            
    if bp_val:
        Bprime = sp.coo_matrix((bp_val, (bp_row, bp_col)), shape=(n_p, n_p), dtype=float).tocsr()
    else:
        Bprime = sp.csr_matrix((n_p, n_p), dtype=float)
        
    # Accumulators for Bdoubleprime
    bdp_row = []
    bdp_col = []
    bdp_val = []
    
    # Build Bdoubleprime
    for br in branch_data:
        if br.get('status', 1) == 0:
            continue
        f_idx = bus_index_map[br['from_bus']]
        t_idx = bus_index_map[br['to_bus']]
        r = br['r']
        x = br['x']
        b = br['b']
        ratio = br.get('ratio', 1.0)
        if ratio == 0.0:
            ratio = 1.0
            
        if fdlf_type == 'fdxb':
            z = complex(r, x)
            y = 1.0 / z if z != 0 else 0.0
            y_shunt = complex(0.0, b / 2.0)
            b_self_f = (y.imag + y_shunt.imag) / (ratio**2)
            b_self_t = y.imag + y_shunt.imag
            b_mut = -(y / ratio).imag
        else:  # fdbx
            b_val = -1.0 / x if x != 0 else 0.0
            b_self_f = b_val / (ratio**2)
            b_self_t = b_val
            b_mut = -b_val / ratio
            
        if f_idx in q_map and t_idx in q_map:
            rf = q_map[f_idx]
            rt = q_map[t_idx]
            bdp_row.extend([rf, rt, rf, rt])
            bdp_col.extend([rt, rf, rf, rt])
            bdp_val.extend([b_mut, b_mut, b_self_f, b_self_t])
        elif f_idx in q_map:
            rf = q_map[f_idx]
            bdp_row.append(rf)
            bdp_col.append(rf)
            bdp_val.append(b_self_f)
        elif t_idx in q_map:
            rt = q_map[t_idx]
            bdp_row.append(rt)
            bdp_col.append(rt)
            bdp_val.append(b_self_t)
            
    if fdlf_type == 'fdxb':
        for bus_num, bus in bus_data.items():
            idx = bus_index_map[bus_num]
            if idx in q_map:
                rf = q_map[idx]
                b_shunt = bus.get('shunt_B', 0.0) / base_mva
                bdp_row.append(rf)
                bdp_col.append(rf)
                bdp_val.append(b_shunt)
                
    if bdp_val:
        Bdoubleprime = sp.coo_matrix((bdp_val, (bdp_row, bdp_col)), shape=(n_q, n_q), dtype=float).tocsr()
    else:
        Bdoubleprime = sp.csr_matrix((n_q, n_q), dtype=float)
        
    return Bprime, Bdoubleprime

def solve_fdlf(Ybus, bus_types, V, theta, P_load, Q_load, Q_gen_sched, P_gen_sched, Q_max_bus, Q_min_bus, V_setpoint, has_generator, bus_data, branch_data, bus_index_map, tol, max_iter, fdlf_type='fdxb', bus_numbers=None, base_mva=100.0, ignore_q_tol=False, zip_params=None):
    from scipy.sparse.linalg import spsolve
    n_buses = len(bus_types)
    if bus_numbers is None:
        bus_numbers = [i + 1 for i in range(n_buses)]
        
    P_sched = P_gen_sched - P_load
    Q_sched = Q_gen_sched - Q_load
    original_bus_types = bus_types.copy()
    active_types = bus_types.copy()
    q_limit_status = np.zeros(n_buses, dtype=int)
    q_dwell_counter = np.zeros(n_buses, dtype=int)
    q_dwell_time = 3
    
    best_res = 1e9
    best_V = V.copy()
    best_theta = theta.copy()
    best_max_dP = 1e9
    best_max_dQ = 1e9

    for i in range(n_buses):
        if active_types[i] in (2, 3) and has_generator[i] and V_setpoint[i] > 0:
            V[i] = V_setpoint[i]
            
    Bprime, Bdoubleprime = build_fdlf_matrices(bus_data, branch_data, bus_index_map, active_types, fdlf_type)
    
    p_idx = np.where(active_types != 3)[0]
    q_idx = np.where(active_types == 1)[0]
    
    max_dP = 0.0
    max_dQ = 0.0

    for iteration in range(max_iter):
        q_dwell_counter = np.maximum(0, q_dwell_counter - 1)
        if zip_params is not None:
            P_load_curr, Q_load_curr, _, _ = eval_bus_zip_loads(V, *zip_params)
            P_sched = P_gen_sched - P_load_curr
            curr_q_load = Q_load_curr
        else:
            curr_q_load = Q_load

        V_complex = V * np.exp(1j * theta)
        I_calc = Ybus.dot(V_complex)
        S_calc = V_complex * np.conj(I_calc)
        P_calc = S_calc.real
        Q_calc = S_calc.imag
        
        type_changed = False
        if not ignore_q_tol and iteration >= 2 and (iteration >= 4 or (len(p_idx) > 0 and np.max(np.abs(P_sched[p_idx] - P_calc[p_idx])) < 0.5)):
            q_violations = []
            for i in range(n_buses):
                if original_bus_types[i] == 2 and (Q_max_bus[i] >= Q_min_bus[i] - 1e-4):
                    Q_gen = Q_calc[i] + curr_q_load[i]
                    if active_types[i] == 2:
                        if Q_gen > Q_max_bus[i] + 1e-5:
                            viol = Q_gen - Q_max_bus[i]
                            q_violations.append((viol, i, 1, Q_max_bus[i] - curr_q_load[i],
                                                 f"  [DevEN FDLF Q-LIMIT] Bus {bus_numbers[i]} reached Qmax ({Q_gen*base_mva:.2f} > {Q_max_bus[i]*base_mva:.2f} MVar) -> Converted PV to PQ"))
                        elif Q_gen < Q_min_bus[i] - 1e-5:
                            viol = Q_min_bus[i] - Q_gen
                            q_violations.append((viol, i, -1, Q_min_bus[i] - curr_q_load[i],
                                                 f"  [DevEN FDLF Q-LIMIT] Bus {bus_numbers[i]} reached Qmin ({Q_gen*base_mva:.2f} < {Q_min_bus[i]*base_mva:.2f} MVar) -> Converted PV to PQ"))
                    elif active_types[i] == 1:
                        if q_dwell_counter[i] == 0 and (iteration >= 10 or (len(p_idx) > 0 and max_dP < 0.01)):
                            if q_limit_status[i] == 1 and V[i] > V_setpoint[i] + 0.02:
                                active_types[i] = 2
                                q_limit_status[i] = 0
                                V[i] = V_setpoint[i]
                                type_changed = True
                                print(f"  [DevEN FDLF Q-RECOVERY] Bus {bus_numbers[i]} voltage recovered -> Reverted PQ to PV")
                            elif q_limit_status[i] == -1 and V[i] < V_setpoint[i] - 0.02:
                                active_types[i] = 2
                                q_limit_status[i] = 0
                                V[i] = V_setpoint[i]
                                type_changed = True
                                print(f"  [DevEN FDLF Q-RECOVERY] Bus {bus_numbers[i]} voltage dropped -> Reverted PQ to PV")

            if q_violations:
                q_violations.sort(key=lambda x: x[0], reverse=True)
                max_conv = max(10, min(35, n_buses // 100))
                for viol, i, status, q_target, log_msg in q_violations[:max_conv]:
                    active_types[i] = 1
                    q_limit_status[i] = status
                    q_dwell_counter[i] = q_dwell_time
                    Q_sched[i] = q_target
                    type_changed = True
                    print(log_msg)
                        
        if type_changed:
            Bprime, Bdoubleprime = build_fdlf_matrices(bus_data, branch_data, bus_index_map, active_types, fdlf_type)
            p_idx = np.where(active_types != 3)[0]
            q_idx = np.where(active_types == 1)[0]
            
            V_complex = V * np.exp(1j * theta)
            I_calc = Ybus.dot(V_complex)
            S_calc = V_complex * np.conj(I_calc)
            P_calc = S_calc.real
            Q_calc = S_calc.imag
            
        dP = P_sched - P_calc
        dQ = Q_sched - Q_calc
        
        max_dP = np.max(np.abs(dP[p_idx])) if len(p_idx) > 0 else 0.0
        max_dQ = np.max(np.abs(dQ[q_idx])) if len(q_idx) > 0 else 0.0
        
        current_res = max(max_dP, max_dQ) if not ignore_q_tol else max_dP
        if current_res < best_res:
            best_res = current_res
            best_V = V.copy()
            best_theta = theta.copy()
            best_max_dP = max_dP
            best_max_dQ = max_dQ

        if not type_changed and max_dP < tol and (max_dQ < tol or ignore_q_tol):
            unresolved_q_violation = False
            if not ignore_q_tol:
                for i in range(n_buses):
                    if original_bus_types[i] == 2 and active_types[i] == 2 and (Q_max_bus[i] >= Q_min_bus[i] - 1e-4):
                        Q_gen = Q_calc[i] + curr_q_load[i]
                        if Q_gen > Q_max_bus[i] + 1e-5:
                            active_types[i] = 1
                            q_limit_status[i] = 1
                            q_dwell_counter[i] = q_dwell_time
                            Q_sched[i] = Q_max_bus[i] - curr_q_load[i]
                            type_changed = True
                            unresolved_q_violation = True
                            print(f"  [DevEN FDLF Q-LIMIT] Bus {bus_numbers[i]} reached Qmax ({Q_gen*base_mva:.2f} > {Q_max_bus[i]*base_mva:.2f} MVar) -> Converted PV to PQ")
                        elif Q_gen < Q_min_bus[i] - 1e-5:
                            active_types[i] = 1
                            q_limit_status[i] = -1
                            q_dwell_counter[i] = q_dwell_time
                            Q_sched[i] = Q_min_bus[i] - curr_q_load[i]
                            type_changed = True
                            unresolved_q_violation = True
                            print(f"  [DevEN FDLF Q-LIMIT] Bus {bus_numbers[i]} reached Qmin ({Q_gen*base_mva:.2f} < {Q_min_bus[i]*base_mva:.2f} MVar) -> Converted PV to PQ")
            if unresolved_q_violation:
                continue
            return V, theta, True, iteration + 1, max_dP, max_dQ
            
        if len(p_idx) > 0:
            mismatch_p = dP[p_idx] / V[p_idx]
            try:
                d_theta = spsolve(Bprime, mismatch_p)
                d_theta = np.clip(d_theta, -0.3, 0.3)
                theta[p_idx] -= d_theta
            except Exception:
                return best_V, best_theta, False, iteration + 1, best_max_dP, best_max_dQ
                
        V_complex = V * np.exp(1j * theta)
        I_calc = Ybus.dot(V_complex)
        Q_calc = (V_complex * np.conj(I_calc)).imag
        dQ = Q_sched - Q_calc
        
        if len(q_idx) > 0:
            mismatch_q = dQ[q_idx] / V[q_idx]
            try:
                d_V = spsolve(Bdoubleprime, mismatch_q)
                d_V = np.clip(d_V, -0.1, 0.1)
                V[q_idx] -= d_V
                V[q_idx] = np.clip(V[q_idx], 0.5, 1.5)
            except Exception:
                return best_V, best_theta, False, iteration + 1, best_max_dP, best_max_dQ
                
    if best_res < 1e8:
        V = best_V
        theta = best_theta
        max_dP = best_max_dP
        max_dQ = best_max_dQ

    return V, theta, False, max_iter, max_dP, max_dQ

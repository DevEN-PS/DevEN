"""
DevEN Island & Network Connectivity Detector Module
===================================================
Detects if taking a line, transformer, or bus out of service splits the electrical network into islands,
and provides robust multi-island classification for large networks (30k+ buses).
"""

from collections import deque

def check_network_islands(case_data, element_offline=None):
    """
    Check connected components (islands) of the power network.
    
    Parameters:
        case_data (dict): DevEN network case dict containing 'buses', 'lines', 'transformers', etc.
        element_offline (dict, optional): Specific element to simulate offline e.g. {'type': 'line', 'num': 1}
        
    Returns:
        dict: {
            'is_islanded': bool,
            'num_islands': int,
            'base_islands': int,
            'island_sizes': list of int,
            'island_buses': list of lists,
            'message': str
        }
    """
    if not case_data or 'buses' not in case_data:
        return {'is_islanded': False, 'num_islands': 1, 'base_islands': 1, 'island_sizes': [], 'island_buses': [], 'message': ''}

    # Helper to compute components
    def _compute_components(offline_elem):
        all_buses = case_data.get('buses', {})
        lines = case_data.get('lines', {})
        xfmrs = case_data.get('transformers', {})
        tw_xfmrs = case_data.get('three_winding_transformers', {}) or case_data.get('three_winding_xfmrs', {})

        target_type = str(offline_elem.get('type', '')).lower() if isinstance(offline_elem, dict) else None
        target_num = offline_elem.get('num') if isinstance(offline_elem, dict) else None
        target_num_str = str(target_num) if target_num is not None else None

        active_buses = set()
        for b_num, b_info in all_buses.items():
            if b_info.get('status', 1) != 0:
                if target_type == 'bus_outage' and (target_num == b_num or target_num_str == str(b_num)):
                    continue
                active_buses.add(b_num)


        if not active_buses:
            return []

        adj = {b: set() for b in active_buses}

        # Add lines
        for l_num, l_info in lines.items():
            if l_info.get('status', 1) == 0:
                continue
            if target_type in ('line', 'lines') and target_num == l_num:
                continue
            fb = l_info.get('from_bus')
            tb = l_info.get('to_bus')
            if target_type == 'bus_outage' and (fb == target_num or tb == target_num):
                continue
            if fb in adj and tb in adj:
                adj[fb].add(tb)
                adj[tb].add(fb)

        # Add transformers
        for x_num, x_info in xfmrs.items():
            if x_info.get('status', 1) == 0:
                continue
            if target_type in ('transformer', 'transformers', 'xfmr') and target_num == x_num:
                continue
            fb = x_info.get('from_bus')
            tb = x_info.get('to_bus')
            if target_type == 'bus_outage' and (fb == target_num or tb == target_num):
                continue
            if fb in adj and tb in adj:
                adj[fb].add(tb)
                adj[tb].add(fb)

        # Add 3-winding transformers
        for tw_num, tw in tw_xfmrs.items():
            if tw.get('status', 1) == 0:
                continue
            if target_type in ('3w_transformer', '3wx_transformer', 'tw_xfmr') and target_num == tw_num:
                continue
            h, m, l = tw.get('hv_bus'), tw.get('mv_bus'), tw.get('lv_bus')
            for (u, v) in [(h, m), (m, l), (h, l)]:
                if u in adj and v in adj:
                    adj[u].add(v)
                    adj[v].add(u)

        visited = set()
        comps = []
        for b in active_buses:
            if b not in visited:
                comp = []
                queue = deque([b])
                visited.add(b)
                while queue:
                    curr = queue.popleft()
                    comp.append(curr)
                    for nxt in adj[curr]:
                        if nxt not in visited:
                            visited.add(nxt)
                            queue.append(nxt)
                comps.append(comp)
        return comps

    base_comps = _compute_components(None)
    base_islands = len(base_comps)

    if element_offline:
        current_comps = _compute_components(element_offline)
    else:
        current_comps = base_comps

    num_islands = len(current_comps)
    island_sizes = [len(c) for c in current_comps]
    island_sizes.sort(reverse=True)

    # Islanded if taking element offline split network further or if network has multiple islands
    is_islanded = (num_islands > base_islands) if element_offline else (num_islands > 1)

    msg_lines = []
    if is_islanded:
        msg_lines.append(f"Network is split into {num_islands} separate islands!")
        # Show top 5 largest islands
        for idx, sz in enumerate(island_sizes[:5], 1):
            msg_lines.append(f"  • Island {idx}: {sz} Buses")
        if len(island_sizes) > 5:
            rem_count = len(island_sizes) - 5
            rem_buses = sum(island_sizes[5:])
            msg_lines.append(f"  • ... and {rem_count} other smaller/floating islands ({rem_buses} buses total)")

    return {
        'is_islanded': is_islanded,
        'num_islands': num_islands,
        'base_islands': base_islands,
        'island_sizes': island_sizes,
        'island_buses': current_comps,
        'message': "\n".join(msg_lines)
    }

def detect_and_classify_islands(bus_data, branch_data, full_data=None, auto_slack=True):
    """
    Detects all connected islands in the power network and classifies them as:
      1. Solvable / Energized islands (contains at least one Slack bus, or an active generator that can act as Slack)
      2. Floating / Unenergized islands (contains only passive buses/loads with no source)
      
    For each solvable island, if no explicit Type 3 Slack bus exists, automatically assigns
    the generator with the largest P_out (or capacity) as the Slack bus for that island.
    
    Parameters:
        bus_data (dict): Mapping bus_id -> bus dict with 'type', 'status', etc.
        branch_data (list of dict): List of branch dicts with 'from_bus', 'to_bus', 'status', etc.
        full_data (dict, optional): Full network case dictionary with 'generators', 'loads', etc.
        auto_slack (bool): If True, automatically designates a Slack bus for islands having generators but no Slack bus.
        
    Returns:
        solvable_islands (list of dict):
            [{
                'island_id': int,
                'buses': set of bus_ids,
                'slack_bus': bus_id,
                'is_main': bool,
                'num_buses': int,
                'auto_slack': bool
            }, ...]
        floating_buses (set of bus_ids): All buses in floating/unenergized islands.
        all_islands (list of list of bus_ids): Raw connected components.
    """
    active_buses = set()
    for b_id, b_info in bus_data.items():
        if b_info.get('status', 1) != 0:
            active_buses.add(b_id)

    if not active_buses:
        return [], set(), []

    adj = {b: set() for b in active_buses}

    for br in branch_data:
        if br.get('status', 1) == 0:
            continue
        fb = br.get('from_bus')
        tb = br.get('to_bus')
        if fb in adj and tb in adj:
            adj[fb].add(tb)
            adj[tb].add(fb)

    # Check 3-winding transformers if present in full_data
    if full_data:
        tw_xfmrs = full_data.get('three_winding_transformers', {}) or full_data.get('three_winding_xfmrs', {})
        for tw in tw_xfmrs.values():
            if tw.get('status', 1) == 0:
                continue
            h = tw.get('hv_bus')
            m = tw.get('mv_bus')
            l = tw.get('lv_bus')
            for (u, v) in [(h, m), (m, l), (h, l)]:
                if u in adj and v in adj:
                    adj[u].add(v)
                    adj[v].add(u)

    visited = set()
    all_islands = []

    for b in active_buses:
        if b not in visited:
            comp = []
            queue = deque([b])
            visited.add(b)
            while queue:
                curr = queue.popleft()
                comp.append(curr)
                for nxt in adj[curr]:
                    if nxt not in visited:
                        visited.add(nxt)
                        queue.append(nxt)
            all_islands.append(comp)

    # Sort islands by size (largest first)
    all_islands.sort(key=lambda c: len(c), reverse=True)

    gens = (full_data.get('generators', {}) if full_data else {})
    hvdcs = (full_data.get('hvdc_links', {}) if full_data else {})
    sync_motors = (full_data.get('synchronous_motors', {}) if full_data else {})
    solvable_islands = []
    floating_buses = set()

    for idx, comp in enumerate(all_islands, 1):
        comp_set = set(comp)
        
        # Check for explicit Slack buses in this component
        slack_buses = [b for b in comp if bus_data.get(b, {}).get('type', 1) == 3]
        
        # Check for active generators in this component
        island_gens = [gid for gid, g in gens.items() if g.get('status', 1) == 1 and g.get('bus') in comp_set]
        
        # Check for active HVDC terminals in this component (inverter injection or rectifier)
        island_hvdcs = [
            hid for hid, h in hvdcs.items()
            if h.get('status', 1) == 1 and (h.get('to_bus') in comp_set or h.get('from_bus') in comp_set)
        ]

        # Check for active synchronous motors/condensers in this component
        island_sms = [
            smid for smid, sm in sync_motors.items()
            if sm.get('status', 1) == 1 and sm.get('bus') in comp_set
        ]

        has_sources = bool(slack_buses) or bool(island_gens) or bool(island_hvdcs) or bool(island_sms)
        is_viable_grid = (len(comp) >= 2) or (len(all_islands) == 1) or has_sources

        if slack_buses and is_viable_grid:
            solvable_islands.append({
                'island_id': idx,
                'buses': comp_set,
                'slack_bus': slack_buses[0],
                'is_main': (idx == 1),
                'num_buses': len(comp),
                'auto_slack': False
            })
        elif island_gens and auto_slack and is_viable_grid:
            # Auto-designate the highest P_out (or highest capacity) generator as Slack
            best_gid = max(island_gens, key=lambda gid: (gens[gid].get('P_out', 0.0), gens[gid].get('Qmax', 0.0)))
            chosen_slack = gens[best_gid]['bus']
            solvable_islands.append({
                'island_id': idx,
                'buses': comp_set,
                'slack_bus': chosen_slack,
                'is_main': (idx == 1),
                'num_buses': len(comp),
                'auto_slack': True
            })
        elif (island_hvdcs or island_sms) and auto_slack and is_viable_grid:
            # Auto-designate the HVDC inverter terminal or synchronous machine bus as Slack for this island
            chosen_slack = None
            if island_hvdcs:
                # Prefer to_bus (inverter station injection), fallback to from_bus
                h_first = hvdcs[island_hvdcs[0]]
                chosen_slack = h_first.get('to_bus') if h_first.get('to_bus') in comp_set else h_first.get('from_bus')
            if not chosen_slack and island_sms:
                chosen_slack = sync_motors[island_sms[0]].get('bus')
            if not chosen_slack:
                chosen_slack = sorted(list(comp_set))[0]

            solvable_islands.append({
                'island_id': idx,
                'buses': comp_set,
                'slack_bus': chosen_slack,
                'is_main': (idx == 1),
                'num_buses': len(comp),
                'auto_slack': True
            })
        else:
            # Passive / unenergized floating island or isolated open-breaker node (no closed branch)
            floating_buses.update(comp_set)

    return solvable_islands, floating_buses, all_islands

def find_slack_islands(bus_data, branch_data, full_data=None):
    """
    Backward-compatible wrapper for find_slack_islands.
    """
    solvable_islands, floating_buses, all_islands = detect_and_classify_islands(
        bus_data, branch_data, full_data=full_data, auto_slack=True
    )
    
    slack_connected_buses = set()
    for isl in solvable_islands:
        slack_connected_buses.update(isl['buses'])
        
    return slack_connected_buses, floating_buses, all_islands



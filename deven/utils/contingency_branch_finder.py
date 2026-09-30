# DevEN Path Bootstrapper
import sys
import os
from collections import deque

"""
DevEN Branch Graph Traversal & Multi-Circuit Finder
Discovers all transmission lines, transformers, 3W transformers, and series elements
up to N branch hops away from candidate bus(es), identifying parallel double/multi-circuits.
"""

def find_substation_branches_by_hops(full_data, candidate_buses, max_hops=4):
    """
    Performs graph BFS from candidate_buses up to max_hops.
    Returns:
        branches_list: list of dicts with element details, hop level, and multi-circuit tags.
        hop_summary: dict of {hop_num: count}
    """
    if isinstance(candidate_buses, (int, str)):
        start_buses = {int(candidate_buses) if str(candidate_buses).isdigit() else candidate_buses}
    else:
        start_buses = {int(b) if str(b).isdigit() else b for b in candidate_buses}

    buses = full_data.get('buses', {})
    lines = full_data.get('lines', {})
    xfmrs = full_data.get('transformers', {})
    tw_xfmrs = full_data.get('three_winding_transformers', {})
    series_comps = full_data.get('series_comps', {})
    series_reactors = full_data.get('series_reactors', {})

    visited_buses = set(start_buses)
    visited_branches = set()
    branches_by_hop = []

    # Queue contains: (bus_id, current_hop)
    queue = deque([(b, 0) for b in start_buses])
    buses_at_hop = {0: set(start_buses)}

    for h in range(1, max_hops + 1):
        buses_at_hop[h] = set()

    # Detect parallel circuits across all lines, transformers, 3w xfmrs, series components
    pair_count = {}
    for lid, line in lines.items():
        fb, tb = line.get('from_bus'), line.get('to_bus')
        if fb is not None and tb is not None:
            pair = tuple(sorted([fb, tb]))
            pair_count[pair] = pair_count.get(pair, 0) + 1

    for xid, xfmr in xfmrs.items():
        fb, tb = xfmr.get('from_bus'), xfmr.get('to_bus')
        if fb is not None and tb is not None:
            pair = tuple(sorted([fb, tb]))
            pair_count[pair] = pair_count.get(pair, 0) + 1

    for tw_id, tw in tw_xfmrs.items():
        pb, sb = tw.get('prim_bus'), tw.get('sec_bus')
        if pb is not None and sb is not None:
            pair = tuple(sorted([pb, sb]))
            pair_count[pair] = pair_count.get(pair, 0) + 1

    for sc_id, sc in series_comps.items():
        fb, tb = sc.get('from_bus'), sc.get('to_bus')
        if fb is not None and tb is not None:
            pair = tuple(sorted([fb, tb]))
            pair_count[pair] = pair_count.get(pair, 0) + 1

    for sr_id, sr in series_reactors.items():
        fb, tb = sr.get('from_bus'), sr.get('to_bus')
        if fb is not None and tb is not None:
            pair = tuple(sorted([fb, tb]))
            pair_count[pair] = pair_count.get(pair, 0) + 1

    # Breadth-first search per hop level
    current_frontier = set(start_buses)

    for hop in range(1, max_hops + 1):
        next_frontier = set()

        # 1. Lines
        for lid, line in sorted(lines.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
            key = f"Line_{lid}"
            if key in visited_branches:
                continue
            fb, tb = line.get('from_bus'), line.get('to_bus')
            if fb in current_frontier or tb in current_frontier:
                pair = tuple(sorted([fb, tb]))
                is_multi = pair_count.get(pair, 1) > 1
                f_kv = buses.get(fb, {}).get('base_kV', 0)
                t_kv = buses.get(tb, {}).get('base_kV', 0)
                f_name = buses.get(fb, {}).get('name', f"Bus_{fb}")
                t_name = buses.get(tb, {}).get('name', f"Bus_{tb}")

                branches_by_hop.append({
                    'id': key,
                    'raw_id': lid,
                    'type': 'line',
                    'name': line.get('name', f"Line_{lid}"),
                    'from_bus': fb,
                    'to_bus': tb,
                    'from_name': f_name,
                    'to_name': t_name,
                    'base_kV': max(f_kv, t_kv),
                    'rateA': float(line.get('rateA', 9999.0) or 9999.0),
                    'hop': hop,
                    'is_multi_circuit': is_multi,
                    'pair_key': f"{pair[0]}_{pair[1]}",
                    'circuit_num': line.get('circuit', 1),
                    'default_selected': is_multi
                })
                visited_branches.add(key)
                next_frontier.add(fb)
                next_frontier.add(tb)

        # 2. 2-Winding Transformers
        for xid, xfmr in sorted(xfmrs.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
            key = f"Xfmr_{xid}"
            if key in visited_branches:
                continue
            fb, tb = xfmr.get('from_bus'), xfmr.get('to_bus')
            if fb in current_frontier or tb in current_frontier:
                pair = tuple(sorted([fb, tb]))
                is_multi = pair_count.get(pair, 1) > 1
                f_kv = buses.get(fb, {}).get('base_kV', 0)
                t_kv = buses.get(tb, {}).get('base_kV', 0)
                f_name = buses.get(fb, {}).get('name', f"Bus_{fb}")
                t_name = buses.get(tb, {}).get('name', f"Bus_{tb}")

                branches_by_hop.append({
                    'id': key,
                    'raw_id': xid,
                    'type': 'transformer',
                    'name': xfmr.get('name', f"Xfmr_{xid}"),
                    'from_bus': fb,
                    'to_bus': tb,
                    'from_name': f_name,
                    'to_name': t_name,
                    'base_kV': f"{f_kv:.1f}/{t_kv:.1f} kV",
                    'rateA': float(xfmr.get('rateA', 9999.0) or 9999.0),
                    'hop': hop,
                    'is_multi_circuit': is_multi,
                    'pair_key': f"{pair[0]}_{pair[1]}",
                    'circuit_num': xfmr.get('circuit', 1),
                    'default_selected': is_multi
                })
                visited_branches.add(key)
                next_frontier.add(fb)
                next_frontier.add(tb)

        # 3. 3-Winding Transformers
        for tw_id, tw in sorted(tw_xfmrs.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
            key = f"3WXfmr_{tw_id}"
            if key in visited_branches:
                continue
            pb, sb, tb = tw.get('prim_bus'), tw.get('sec_bus'), tw.get('tert_bus')
            if pb in current_frontier or sb in current_frontier or tb in current_frontier:
                pair = tuple(sorted([pb, sb]))
                is_multi = pair_count.get(pair, 1) > 1
                branches_by_hop.append({
                    'id': key,
                    'raw_id': tw_id,
                    'type': '3w_transformer',
                    'name': tw.get('name', f"3WXfmr_{tw_id}"),
                    'from_bus': pb,
                    'to_bus': sb,
                    'from_name': f"Bus {pb}",
                    'to_name': f"Bus {sb}/{tb}",
                    'base_kV': "3-Winding",
                    'rateA': float(tw.get('rateA', 9999.0) or 9999.0),
                    'hop': hop,
                    'is_multi_circuit': is_multi,
                    'pair_key': f"{pb}_{sb}",
                    'circuit_num': 1,
                    'default_selected': is_multi
                })
                visited_branches.add(key)
                if pb: next_frontier.add(pb)
                if sb: next_frontier.add(sb)
                if tb: next_frontier.add(tb)

        # 4. Series Components (Capacitors & Reactors)
        for sc_id, sc in sorted(series_comps.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
            key = f"SerCap_{sc_id}"
            if key in visited_branches: continue
            fb, tb = sc.get('from_bus'), sc.get('to_bus')
            if fb in current_frontier or tb in current_frontier:
                pair = tuple(sorted([fb, tb]))
                is_multi = pair_count.get(pair, 1) > 1
                branches_by_hop.append({
                    'id': key, 'raw_id': sc_id, 'type': 'series_comp',
                    'name': sc.get('name', f"SerCap_{sc_id}"),
                    'from_bus': fb, 'to_bus': tb,
                    'from_name': f"Bus {fb}", 'to_name': f"Bus {tb}",
                    'base_kV': "Series Cap", 'rateA': 9999.0, 'hop': hop,
                    'is_multi_circuit': is_multi, 'pair_key': f"{fb}_{tb}",
                    'circuit_num': 1, 'default_selected': is_multi
                })
                visited_branches.add(key)
                next_frontier.add(fb); next_frontier.add(tb)

        for sr_id, sr in sorted(series_reactors.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0])):
            key = f"SerRct_{sr_id}"
            if key in visited_branches: continue
            fb, tb = sr.get('from_bus'), sr.get('to_bus')
            if fb in current_frontier or tb in current_frontier:
                pair = tuple(sorted([fb, tb]))
                is_multi = pair_count.get(pair, 1) > 1
                branches_by_hop.append({
                    'id': key, 'raw_id': sr_id, 'type': 'series_reactor',
                    'name': sr.get('name', f"SerRct_{sr_id}"),
                    'from_bus': fb, 'to_bus': tb,
                    'from_name': f"Bus {fb}", 'to_name': f"Bus {tb}",
                    'base_kV': "Series Reactor", 'rateA': 9999.0, 'hop': hop,
                    'is_multi_circuit': is_multi, 'pair_key': f"{fb}_{tb}",
                    'circuit_num': 1, 'default_selected': is_multi
                })
                visited_branches.add(key)
                next_frontier.add(fb); next_frontier.add(tb)

        current_frontier = next_frontier

    return branches_by_hop

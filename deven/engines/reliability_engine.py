#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
  DevEN (Develop Electric Network) - Reliability Analysis Engine
=============================================================================
  Standards Compliant:
    - IEEE Std 493-2007: Gold Book (Design of Reliable Industrial and
      Commercial Power Systems)
    - IEEE Std 3006.7-2013: Recommended Practice for Determining the
      Reliability of Power Distribution System Designs
    - IEEE Std 1366-2022: Guide for Electric Power Distribution Reliability
      Indices (SAIFI, SAIDI, CAIDI, ASAI)
=============================================================================
"""

import math

# IEEE Std 493 (Gold Book) Appendix A: Equipment Reliability Data
# lambda_per_year: Failure rate (failures per year, or per km-year for lines/cables)
# mttr_hours: Mean Time To Repair (hours)
IEEE_GOLD_BOOK_EQUIPMENT = {
    'TRANSFORMER_LIQUID': {
        'name': 'Power Transformer (Liquid-Filled)',
        'lambda_per_year': 0.0059,  # 0.0059 failures/yr (~1 in 170 yrs)
        'mttr_hours': 130.0,
        'unit': 'unit'
    },
    'TRANSFORMER_DRY': {
        'name': 'Distribution Transformer (Dry-Type)',
        'lambda_per_year': 0.0028,
        'mttr_hours': 48.0,
        'unit': 'unit'
    },
    'BREAKER_VACUUM': {
        'name': 'Circuit Breaker (Vacuum, MV)',
        'lambda_per_year': 0.0036,
        'mttr_hours': 15.0,
        'unit': 'unit'
    },
    'BREAKER_AIR': {
        'name': 'Circuit Breaker (Air / ACB, LV)',
        'lambda_per_year': 0.0027,
        'mttr_hours': 8.0,
        'unit': 'unit'
    },
    'BREAKER_SF6': {
        'name': 'Circuit Breaker (SF6, HV)',
        'lambda_per_year': 0.0040,
        'mttr_hours': 24.0,
        'unit': 'unit'
    },
    'CABLE_XLPE_KM': {
        'name': 'Underground Cable (XLPE, per km)',
        'lambda_per_year': 0.0141,  # failures/km-year
        'mttr_hours': 26.5,
        'unit': 'km'
    },
    'OVERHEAD_LINE_KM': {
        'name': 'Overhead Line (Open Wire, per km)',
        'lambda_per_year': 0.0450,  # failures/km-year
        'mttr_hours': 4.5,
        'unit': 'km'
    },
    'DISCONNECT_SWITCH': {
        'name': 'Disconnect / Isolator Switch',
        'lambda_per_year': 0.0016,
        'mttr_hours': 4.0,
        'unit': 'unit'
    },
    'GENERATOR_DIESEL': {
        'name': 'Emergency Diesel Generator (Standby)',
        'lambda_per_year': 0.0820,
        'mttr_hours': 20.0,
        'unit': 'unit'
    },
    'UPS_STATIC': {
        'name': 'Static UPS System (Rectifier + Inverter)',
        'lambda_per_year': 0.0350,
        'mttr_hours': 5.0,
        'unit': 'unit'
    },
    'BUS_SWITCHGEAR': {
        'name': 'Switchgear Busbar Section',
        'lambda_per_year': 0.0010,
        'mttr_hours': 24.0,
        'unit': 'unit'
    }
}


def calc_series_reliability(components: list) -> dict:
    """
    Computes equivalent reliability of series components (all must function).
    lambda_s = sum(lambda_i)
    U_s = sum(U_i) = sum(lambda_i * r_i)
    r_s = U_s / lambda_s
    """
    tot_lambda = 0.0
    tot_u_hours = 0.0
    
    for c in components:
        lam = float(c.get('lambda', c.get('failure_rate', 0.0)))
        qty = float(c.get('quantity', c.get('length_km', 1.0)))
        eff_lam = lam * qty
        mttr = float(c.get('mttr', c.get('mttr_hours', 10.0)))
        u = eff_lam * mttr
        tot_lambda += eff_lam
        tot_u_hours += u
        
    eq_mttr = (tot_u_hours / max(1e-6, tot_lambda)) if tot_lambda > 0 else 0.0
    availability = (8760.0 - tot_u_hours) / 8760.0
    
    return {
        'lambda': tot_lambda,
        'mttr_hours': eq_mttr,
        'unavailability_hours_per_year': tot_u_hours,
        'availability': max(0.0, availability),
        'forced_outage_rate': tot_u_hours / 8760.0
    }


def calc_parallel_reliability(branch1: dict, branch2: dict) -> dict:
    """
    Computes equivalent reliability of two redundant parallel branches (IEEE 493).
    lambda_p = (lambda1 * lambda2 * (r1 + r2)) / 8760
    r_p = (r1 * r2) / (r1 + r2)
    U_p = lambda_p * r_p
    """
    l1 = float(branch1['lambda'])
    r1 = float(branch1['mttr_hours'])
    l2 = float(branch2['lambda'])
    r2 = float(branch2['mttr_hours'])
    
    r_p = (r1 * r2) / max(1e-4, r1 + r2)
    l_p = (l1 * l2 * (r1 + r2)) / 8760.0
    u_p = l_p * r_p
    availability = (8760.0 - u_p) / 8760.0
    
    return {
        'lambda': l_p,
        'mttr_hours': r_p,
        'unavailability_hours_per_year': u_p,
        'availability': max(0.0, availability),
        'forced_outage_rate': u_p / 8760.0
    }


def evaluate_system_indices(load_points: list) -> dict:
    """
    Evaluates IEEE Std 1366 reliability indices for an electrical system or network.
    
    Parameters:
    -----------
    load_points: list of dicts, each with:
      - 'name' / 'bus': Bus identifier
      - 'lambda': Outage frequency (failures/year)
      - 'mttr_hours': Average outage duration (hours)
      - 'num_customers': Number of connected customers (default 1)
      - 'load_kw': Average or peak load at bus (kW)
      - 'cost_per_kwh': Interruption cost rate ($/kWh, default $5.00/kWh)
      
    Returns:
    --------
    dict containing SAIFI, SAIDI, CAIDI, ASAI, EENS, ECOST and compliance notes.
    """
    tot_cust = 0
    tot_lambda_cust = 0.0
    tot_u_cust = 0.0
    tot_eens_kwh = 0.0
    tot_ecost = 0.0
    
    results_table = []
    
    for lp in load_points:
        n_cust = int(lp.get('num_customers', 1))
        lam = float(lp.get('lambda', 0.1))
        mttr = float(lp.get('mttr_hours', lp.get('r', 4.0)))
        u_hrs = lam * mttr
        load_kw = float(lp.get('load_kw', lp.get('P_demand', 100.0)))
        cost_rate = float(lp.get('cost_per_kwh', 5.0))
        
        eens_kwh = u_hrs * load_kw
        ecost = eens_kwh * cost_rate
        
        tot_cust += n_cust
        tot_lambda_cust += lam * n_cust
        tot_u_cust += u_hrs * n_cust
        tot_eens_kwh += eens_kwh
        tot_ecost += ecost
        
        results_table.append({
            'bus': lp.get('name', lp.get('bus', 'Bus')),
            'customers': n_cust,
            'lambda_per_yr': lam,
            'mttr_hrs': mttr,
            'outage_hrs_per_yr': u_hrs,
            'availability_pct': ((8760.0 - u_hrs) / 8760.0) * 100.0,
            'load_kw': load_kw,
            'eens_mwh_yr': eens_kwh / 1000.0,
            'ecost_usd_yr': ecost
        })
        
    tot_cust = max(1, tot_cust)
    saifi = tot_lambda_cust / tot_cust
    saidi = tot_u_cust / tot_cust
    caidi = (saidi / saifi) if saifi > 0 else 0.0
    asai = (8760.0 - saidi) / 8760.0
    eens_mwh = tot_eens_kwh / 1000.0
    
    # Benchmarking notes against typical industrial/commercial criteria
    compliance = []
    status = "EXCELLENT"
    
    # ASAI Benchmark: 99.99% ("Four Nines") is standard goal for reliable industrial power
    asai_pct = asai * 100.0
    if asai_pct >= 99.99:
        compliance.append(f"[PASS] ASAI: {asai_pct:.4f}% >= 99.99% (Meets 'Four Nines' High Reliability Goal).")
    elif asai_pct >= 99.9:
        compliance.append(f"[INFO] ASAI: {asai_pct:.4f}% (Meets standard commercial utility benchmark).")
        status = "GOOD"
    else:
        compliance.append(f"[WARNING] ASAI: {asai_pct:.4f}% < 99.9% (Sub-standard availability, excessive outage hours).")
        status = "MARGINAL"
        
    if saifi <= 1.0:
        compliance.append(f"[PASS] SAIFI: {saifi:.2f} interruptions/cust-yr (Excellent, <= 1.0).")
    elif saifi <= 2.5:
        compliance.append(f"[INFO] SAIFI: {saifi:.2f} interruptions/cust-yr (Average industrial feeder).")
    else:
        compliance.append(f"[WARNING] SAIFI: {saifi:.2f} interruptions/cust-yr (Elevated trip frequency).")
        if status != "MARGINAL": status = "AVERAGE"

    if saidi <= 2.0:
        compliance.append(f"[PASS] SAIDI: {saidi:.2f} hrs/cust-yr (Under 2 hours annual downtime).")
    elif saidi <= 8.0:
        compliance.append(f"[INFO] SAIDI: {saidi:.2f} hrs/cust-yr (Acceptable industrial downtime).")
    else:
        compliance.append(f"[WARNING] SAIDI: {saidi:.2f} hrs/cust-yr (High outage duration).")
        status = "MARGINAL"

    return {
        'status': status,
        'total_customers': tot_cust,
        'saifi': saifi,
        'saidi_hours': saidi,
        'caidi_hours': caidi,
        'asai': asai,
        'asai_pct': asai_pct,
        'eens_mwh_yr': eens_mwh,
        'total_interruption_cost_usd': tot_ecost,
        'load_points': results_table,
        'compliance_notes': compliance
    }

# DevEN Path Bootstrapper
import sys
import os
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
Contingency Batch Mode for Inverse Power Flow
- Includes ALL components: Lines, Transformers, Generators, Loads, Capacitors, Reactors, Series Comps, Series Reactors, Shunts
- Bus Outage removes ALL connected elements with detailed description
- Consolidated reports with proper headers
- Alphabetical menu for all component types
"""

import os
import sys
import argparse
import copy
import numpy as np
import csv
import re
from datetime import datetime


try:
    from utils.input_reader import InputReader
except ImportError:
    from input_reader import InputReader

try:
    from engines.power_flow_engine import PowerFlowEngine
except ImportError:
    from power_flow_engine import PowerFlowEngine

try:
    from utils.report_writer import ReportWriter
except ImportError:
    from report_writer import ReportWriter


class ContingencyBatch:
    """
    Batch contingency analysis - runs each contingency and saves full reports
    """
    
    def __init__(self, input_file, baseMVA=100.0):
        self.input_file = input_file
        self.baseMVA = baseMVA
        self.original_data = None
        self.bus_data = None
        self.branch_data = None
        self.full_data = None
        self.original_bus_data = None
        self.original_branch_data = None
        self.original_full_data = None
        # self.case_name = None
        # self.output_folder = None
        # self.generated_files = []
        self.case_name = None
        self.output_folder = None
        self.generated_files = []
        self.engine_choice = 'andes'
        self.method = 'nr'
        self.tol = 0.000001
        self.max_iter = 20
        self.v_init_base = 'flat'
        self.v_init_cont = 'warm'
        self.ignore_q_tol = False
        self.ignore_islands = True
        self.industry_std_pv = True
        self.fallback_opts = {
            'enable_fallback_pipeline': True,
            'stage_max_iter': self.max_iter,
            'use_dc_angle_init': True,
            'use_postponed_q_limits': True,
            'use_step_damping': True,
            'use_levenberg_marquardt': True,
            'use_homotopy_ramping': True,
            'use_diagnostics': True
        }
        self.base_case_v_mag = None
        self.base_case_v_angle = None
        self.prev_cont_v_mag = None
        self.prev_cont_v_angle = None
        
        # Store originally out-of-service elements
        self.originally_offline = {
            'lines': [], 'transformers': [], 'generators': [], 'loads': [],
            'capacitors': [], 'reactors': [], 'series_comps': [], 'series_reactors': [], 'shunts': []
        }
        
        # Store element details for display
        self.element_details = {}
        self.bus_connections = {}
        
    def load_system(self):
        """Load original system data"""
        print(f"\n[LOADING] {self.input_file}")
        self.case_name = os.path.splitext(os.path.basename(self.input_file))[0]
        self.original_data = InputReader.read_from_python(self.input_file)
        if not self.original_data:
            return False
        
        self.bus_data, self.branch_data, self.full_data = InputReader.convert_to_engine_format(self.original_data)
        
        # Store original data for reset
        self.original_bus_data = copy.deepcopy(self.bus_data)
        self.original_branch_data = copy.deepcopy(self.branch_data)
        self.original_full_data = copy.deepcopy(self.full_data)
        
        print(f"   Buses: {len(self.bus_data)}")
        print(f"   Branches: {len(self.branch_data)}")
        
        # Record element details and offline elements
        self._record_element_details()
        self._record_offline_elements()
        
        # Build bus connection map
        self._build_bus_connections()
        
        return True
    
    def _record_element_details(self):
        """Store details of all elements for display purposes"""
        
        # Lines
        for line_num, line in self.original_data.get('lines', {}).items():
            from_bus = line.get('from_bus', 0)
            bus_info = self.original_data.get('buses', {}).get(from_bus, {})
            self.element_details[f'LINE_{line_num}'] = {
                'name': line.get('name', f'Line_{line_num}'),
                'from_bus': from_bus,
                'to_bus': line.get('to_bus', 0),
                'length_km': line.get('length_km', 0),
                'voltage': bus_info.get('base_kV', 'Unknown'),
                'display': f"Line {line_num}: {line.get('name', f'Line_{line_num}')} (Bus {from_bus} <-> Bus {line.get('to_bus', 0)}) of length {line.get('length_km', 0)} km at {bus_info.get('base_kV', 'Unknown')} kV"
            }
        
        # Transformers
        for xfmr_num, xfmr in self.original_data.get('transformers', {}).items():
            self.element_details[f'XFMR_{xfmr_num}'] = {
                'name': xfmr.get('name', f'Xfmr_{xfmr_num}'),
                'from_bus': xfmr.get('from_bus', 0),
                'to_bus': xfmr.get('to_bus', 0),
                'rating': xfmr.get('rateA', 'Unknown'),
                'tap': xfmr.get('tap_ratio', 1.0),
                'display': f"Transformer {xfmr_num}: {xfmr.get('name', f'Xfmr_{xfmr_num}')} (Bus {xfmr.get('from_bus', 0)} <-> Bus {xfmr.get('to_bus', 0)}) of rating {xfmr.get('rateA', 'Unknown')} MVA"
            }
        
        # Generators & Synchronous Motors
        for gen_num, gen in self.original_data.get('generators', {}).items():
            is_sm = (str(gen.get('gen_type', '')).upper() == 'SYNC_MOTOR' or 
                     str(gen.get('name', '')).upper().startswith('SM') or 
                     float(gen.get('P_out', gen.get('P_gen', 0.0))) < 0)
            prefix = 'SYNC_MOTOR_' if is_sm else 'GEN_'
            type_label = "Synchronous Motor" if is_sm else "Generator"
            p_val = gen.get('P_out', 0)
            p_str = f"{abs(p_val)} MW (Motor Load)" if is_sm else f"{p_val} MW"
            detail_entry = {
                'name': gen.get('name', f'{prefix}{gen_num}'),
                'bus': gen.get('bus', 0),
                'p_out': p_val,
                'q_out': gen.get('Q_out', 0),
                'voltage': gen.get('V_set', 1.0),
                'display': f"{type_label} {gen_num}: {gen.get('name', f'{prefix}{gen_num}')} at Bus {gen.get('bus', 0)} of {p_str} & {gen.get('Q_out', 0)} MVAR"
            }
            self.element_details[f'{prefix}{gen_num}'] = detail_entry
            if is_sm and f'GEN_{gen_num}' not in self.element_details:
                self.element_details[f'GEN_{gen_num}'] = detail_entry
        
        # Loads
        for load_num, load in self.original_data.get('loads', {}).items():
            self.element_details[f'LOAD_{load_num}'] = {
                'name': load.get('name', f'Load_{load_num}'),
                'bus': load.get('bus', 0),
                'p_demand': load.get('P_demand', 0),
                'q_demand': load.get('Q_demand', 0),
                'display': f"Load {load_num}: {load.get('name', f'Load_{load_num}')} at Bus {load.get('bus', 0)} of {load.get('P_demand', 0)} MW & {load.get('Q_demand', 0)} MVAR"
            }
        
        # Capacitors
        for cap_num, cap in self.original_data.get('capacitors', {}).items():
            self.element_details[f'CAP_{cap_num}'] = {
                'name': cap.get('name', f'Cap_{cap_num}'),
                'bus': cap.get('bus', 0),
                'q_cap': cap.get('Q_cap', 0),
                'display': f"Capacitor {cap_num}: {cap.get('name', f'Cap_{cap_num}')} at Bus {cap.get('bus', 0)} of {cap.get('Q_cap', 0)} MVAR"
            }
        
        # Reactors
        for reactor_num, reactor in self.original_data.get('reactors', {}).items():
            self.element_details[f'REACTOR_{reactor_num}'] = {
                'name': reactor.get('name', f'Reactor_{reactor_num}'),
                'bus': reactor.get('bus', 0),
                'q_react': reactor.get('Q_react', 0),
                'display': f"Reactor {reactor_num}: {reactor.get('name', f'Reactor_{reactor_num}')} at Bus {reactor.get('bus', 0)} of {reactor.get('Q_react', 0)} MVAR"
            }
        
        # Series Compensation
        for sc_num, sc in self.original_data.get('series_comps', {}).items():
            self.element_details[f'SERIES_COMP_{sc_num}'] = {
                'name': sc.get('name', f'SC_{sc_num}'),
                'from_bus': sc.get('from_bus', 0),
                'to_bus': sc.get('to_bus', 0),
                'comp_pct': sc.get('comp_pct', 0),
                'display': f"Series Compensation {sc_num}: {sc.get('name', f'SC_{sc_num}')} between Bus {sc.get('from_bus', 0)} and Bus {sc.get('to_bus', 0)} of {sc.get('comp_pct', 0)}%"
            }
        
        # Series Reactors
        for sr_num, sr in self.original_data.get('series_reactors', {}).items():
            self.element_details[f'SERIES_REACTOR_{sr_num}'] = {
                'name': sr.get('name', f'SR_{sr_num}'),
                'from_bus': sr.get('from_bus', 0),
                'to_bus': sr.get('to_bus', 0),
                'x': sr.get('x', 0),
                'display': f"Series Reactor {sr_num}: {sr.get('name', f'SR_{sr_num}')} between Bus {sr.get('from_bus', 0)} and Bus {sr.get('to_bus', 0)} of reactance {sr.get('x', 0)} pu"
            }
        
        # Shunts
        for shunt_num, shunt in self.original_data.get('shunts', {}).items():
            self.element_details[f'SHUNT_{shunt_num}'] = {
                'name': shunt.get('name', f'Shunt_{shunt_num}'),
                'bus': shunt.get('bus', 0),
                'q_shunt': shunt.get('Q_shunt', 0),
                'display': f"Shunt {shunt_num}: {shunt.get('name', f'Shunt_{shunt_num}')} at Bus {shunt.get('bus', 0)} of {shunt.get('Q_shunt', 0)} MVAR"
            }
        
        # Buses
        for bus_num, bus in self.original_data.get('buses', {}).items():
            self.element_details[f'BUS_{bus_num}'] = {
                'name': bus.get('name', f'Bus_{bus_num}'),
                'base_kv': bus.get('base_kV', 0),
                'voltage_pu': bus.get('V_init', 1.0),
                'display': f"Bus {bus_num}: {bus.get('name', f'Bus_{bus_num}')} at {bus.get('base_kV', 0)} kV"
            }
    
    def _record_offline_elements(self):
        """Record elements that are originally out-of-service"""
        
        for line_num, line in self.original_data.get('lines', {}).items():
            if line.get('status', 1) != 1:
                self.originally_offline['lines'].append(line_num)
        
        for xfmr_num, xfmr in self.original_data.get('transformers', {}).items():
            if xfmr.get('status', 1) != 1:
                self.originally_offline['transformers'].append(xfmr_num)
        
        for gen_num, gen in self.original_data.get('generators', {}).items():
            if gen.get('status', 1) != 1:
                self.originally_offline['generators'].append(gen_num)
        
        for load_num, load in self.original_data.get('loads', {}).items():
            if load.get('status', 1) != 1:
                self.originally_offline['loads'].append(load_num)
        
        for cap_num, cap in self.original_data.get('capacitors', {}).items():
            if cap.get('status', 1) != 1:
                self.originally_offline['capacitors'].append(cap_num)
        
        for reactor_num, reactor in self.original_data.get('reactors', {}).items():
            if reactor.get('status', 1) != 1:
                self.originally_offline['reactors'].append(reactor_num)
        
        for sc_num, sc in self.original_data.get('series_comps', {}).items():
            if sc.get('status', 1) != 1:
                self.originally_offline['series_comps'].append(sc_num)
        
        for sr_num, sr in self.original_data.get('series_reactors', {}).items():
            if sr.get('status', 1) != 1:
                self.originally_offline['series_reactors'].append(sr_num)
        
        for shunt_num, shunt in self.original_data.get('shunts', {}).items():
            if shunt.get('status', 1) != 1:
                self.originally_offline['shunts'].append(shunt_num)
        
        if any(self.originally_offline.values()):
            print(f"\n  ⚠️ Originally offline elements (will remain offline)")
    
    def _build_bus_connections(self):
        """Build mapping of bus to all connected elements"""
        self.bus_connections = {bus_num: {
            'lines': [], 'transformers': [], 'generators': [], 'loads': [],
            'capacitors': [], 'reactors': [], 'series_comps': [], 'series_reactors': [], 'shunts': []
        } for bus_num in self.bus_data.keys()}
        
        # Lines
        for line_num, line in self.original_data.get('lines', {}).items():
            from_bus = line.get('from_bus', 0)
            to_bus = line.get('to_bus', 0)
            if from_bus in self.bus_connections:
                self.bus_connections[from_bus]['lines'].append(line_num)
            if to_bus in self.bus_connections:
                self.bus_connections[to_bus]['lines'].append(line_num)
        
        # Transformers
        for xfmr_num, xfmr in self.original_data.get('transformers', {}).items():
            from_bus = xfmr.get('from_bus', 0)
            to_bus = xfmr.get('to_bus', 0)
            if from_bus in self.bus_connections:
                self.bus_connections[from_bus]['transformers'].append(xfmr_num)
            if to_bus in self.bus_connections:
                self.bus_connections[to_bus]['transformers'].append(xfmr_num)
        
        # Generators
        for gen_num, gen in self.original_data.get('generators', {}).items():
            bus = gen.get('bus', 0)
            if bus in self.bus_connections:
                self.bus_connections[bus]['generators'].append(gen_num)
        
        # Loads
        for load_num, load in self.original_data.get('loads', {}).items():
            bus = load.get('bus', 0)
            if bus in self.bus_connections:
                self.bus_connections[bus]['loads'].append(load_num)
        
        # Capacitors
        for cap_num, cap in self.original_data.get('capacitors', {}).items():
            bus = cap.get('bus', 0)
            if bus in self.bus_connections:
                self.bus_connections[bus]['capacitors'].append(cap_num)
        
        # Reactors
        for reactor_num, reactor in self.original_data.get('reactors', {}).items():
            bus = reactor.get('bus', 0)
            if bus in self.bus_connections:
                self.bus_connections[bus]['reactors'].append(reactor_num)
        
        # Series Compensation
        for sc_num, sc in self.original_data.get('series_comps', {}).items():
            from_bus = sc.get('from_bus', 0)
            to_bus = sc.get('to_bus', 0)
            if from_bus in self.bus_connections:
                self.bus_connections[from_bus]['series_comps'].append(sc_num)
            if to_bus in self.bus_connections:
                self.bus_connections[to_bus]['series_comps'].append(sc_num)
        
        # Series Reactors
        for sr_num, sr in self.original_data.get('series_reactors', {}).items():
            from_bus = sr.get('from_bus', 0)
            to_bus = sr.get('to_bus', 0)
            if from_bus in self.bus_connections:
                self.bus_connections[from_bus]['series_reactors'].append(sr_num)
            if to_bus in self.bus_connections:
                self.bus_connections[to_bus]['series_reactors'].append(sr_num)
        
        # Shunts
        for shunt_num, shunt in self.original_data.get('shunts', {}).items():
            bus = shunt.get('bus', 0)
            if bus in self.bus_connections:
                self.bus_connections[bus]['shunts'].append(shunt_num)
    
    def get_connected_elements_description(self, bus_num):
        """Get detailed description of all elements connected to a bus"""
        conn = self.bus_connections.get(bus_num, {})
        descriptions = []
        
        for line_num in conn.get('lines', []):
            if f'LINE_{line_num}' in self.element_details:
                descriptions.append(f"    • {self.element_details[f'LINE_{line_num}']['display']}")
        
        for xfmr_num in conn.get('transformers', []):
            if f'XFMR_{xfmr_num}' in self.element_details:
                descriptions.append(f"    • {self.element_details[f'XFMR_{xfmr_num}']['display']}")
        
        for gen_num in conn.get('generators', []):
            if f'GEN_{gen_num}' in self.element_details:
                descriptions.append(f"    • {self.element_details[f'GEN_{gen_num}']['display']}")
        
        for load_num in conn.get('loads', []):
            if f'LOAD_{load_num}' in self.element_details:
                descriptions.append(f"    • {self.element_details[f'LOAD_{load_num}']['display']}")
        
        for cap_num in conn.get('capacitors', []):
            if f'CAP_{cap_num}' in self.element_details:
                descriptions.append(f"    • {self.element_details[f'CAP_{cap_num}']['display']}")
        
        for reactor_num in conn.get('reactors', []):
            if f'REACTOR_{reactor_num}' in self.element_details:
                descriptions.append(f"    • {self.element_details[f'REACTOR_{reactor_num}']['display']}")
        
        for sc_num in conn.get('series_comps', []):
            if f'SERIES_COMP_{sc_num}' in self.element_details:
                descriptions.append(f"    • {self.element_details[f'SERIES_COMP_{sc_num}']['display']}")
        
        for sr_num in conn.get('series_reactors', []):
            if f'SERIES_REACTOR_{sr_num}' in self.element_details:
                descriptions.append(f"    • {self.element_details[f'SERIES_REACTOR_{sr_num}']['display']}")
        
        for shunt_num in conn.get('shunts', []):
            if f'SHUNT_{shunt_num}' in self.element_details:
                descriptions.append(f"    • {self.element_details[f'SHUNT_{shunt_num}']['display']}")
        
        return descriptions
    
    def reset_to_base(self):
        """Reset to original system state"""
        self.bus_data = copy.deepcopy(self.original_bus_data)
        self.branch_data = copy.deepcopy(self.original_branch_data)
        self.full_data = copy.deepcopy(self.original_full_data)
    
    def apply_contingency(self, contingency):
        """Apply contingency based on type"""
        
        self.reset_to_base()
        contingency_info = {}
        
        if contingency['type'] == 'line':
            line_num = contingency['num']
            if line_num in self.full_data.get('lines', {}):
                self.full_data['lines'][line_num]['status'] = 0
                details = self.element_details.get(f'LINE_{line_num}', {})
                contingency_info = {
                    'id': f"LINE_{line_num}",
                    'name': contingency['name'],
                    'type': 'Line Outage',
                    'description': f"OUTAGE OF {contingency['name']}",
                    'details': details.get('display', ''),
                    'display': f"OUTAGE OF {details.get('display', f'Line {line_num}')}"
                }
        
        elif contingency['type'] == 'transformer':
            xfmr_num = contingency['num']
            if xfmr_num in self.full_data.get('transformers', {}):
                self.full_data['transformers'][xfmr_num]['status'] = 0
                details = self.element_details.get(f'XFMR_{xfmr_num}', {})
                contingency_info = {
                    'id': f"XFMR_{xfmr_num}",
                    'name': contingency['name'],
                    'type': 'Transformer Outage',
                    'description': f"OUTAGE OF {contingency['name']}",
                    'details': details.get('display', ''),
                    'display': f"OUTAGE OF {details.get('display', f'Transformer {xfmr_num}')}"
                }
        
        elif contingency['type'] in ('generator', 'sync_motor'):
            gen_num = contingency['num']
            if gen_num in self.full_data.get('generators', {}):
                gen_dict = self.full_data['generators'][gen_num]
                is_sm = (contingency['type'] == 'sync_motor' or 
                         str(gen_dict.get('gen_type', '')).upper() == 'SYNC_MOTOR' or
                         str(gen_dict.get('name', '')).upper().startswith('SM') or
                         float(gen_dict.get('P_out', gen_dict.get('P_gen', 0.0))) < 0)
                prefix = 'SYNC_MOTOR_' if is_sm else 'GEN_'
                outage_title = 'Synchronous Motor Outage' if is_sm else 'Generator Outage'
                details = self.element_details.get(f'{prefix}{gen_num}', self.element_details.get(f'GEN_{gen_num}', {}))
                self.full_data['generators'][gen_num]['status'] = 0
                self.full_data['generators'][gen_num]['P_out'] = 0
                self.full_data['generators'][gen_num]['Q_out'] = 0
                contingency_info = {
                    'id': f"{prefix}{gen_num}",
                    'name': contingency['name'],
                    'type': outage_title,
                    'description': f"OUTAGE OF {contingency['name']}",
                    'details': details.get('display', ''),
                    'display': f"OUTAGE OF {details.get('display', f'{outage_title} {gen_num}')}"
                }
        
        elif contingency['type'] == 'load':
            load_num = contingency['num']
            if load_num in self.full_data.get('loads', {}):
                details = self.element_details.get(f'LOAD_{load_num}', {})
                original_p = self.full_data['loads'][load_num].get('P_demand', 0)
                original_q = self.full_data['loads'][load_num].get('Q_demand', 0)
                self.full_data['loads'][load_num]['P_demand'] = original_p * 0
                self.full_data['loads'][load_num]['Q_demand'] = original_q * 0

                # self.full_data['loads'][load_num]['P_demand'] = original_p * 1.2
                # self.full_data['loads'][load_num]['Q_demand'] = original_q * 1.2

                contingency_info = {
                    'id': f"LOAD_{load_num}",
                    'name': contingency['name'],
                    'type': 'Load Increase',
                    'description': f"LOAD INCREASE FOR {contingency['name']}",
                    'details': details.get('display', ''),
                    'display': f"LOAD INCREASE FOR {details.get('display', f'Load {load_num}')} from {original_p:.1f} MW to {original_p*1.2:.1f} MW (0%)"
                }
                
        
        elif contingency['type'] == 'capacitor':
            cap_num = contingency['num']
            if cap_num in self.full_data.get('capacitors', {}):
                self.full_data['capacitors'][cap_num]['status'] = 0
                details = self.element_details.get(f'CAP_{cap_num}', {})
                contingency_info = {
                    'id': f"CAP_{cap_num}",
                    'name': contingency['name'],
                    'type': 'Capacitor Outage',
                    'description': f"OUTAGE OF {contingency['name']}",
                    'details': details.get('display', ''),
                    'display': f"OUTAGE OF {details.get('display', f'Capacitor {cap_num}')}"
                }
        
        elif contingency['type'] == 'reactor':
            reactor_num = contingency['num']
            if reactor_num in self.full_data.get('reactors', {}):
                self.full_data['reactors'][reactor_num]['status'] = 0
                details = self.element_details.get(f'REACTOR_{reactor_num}', {})
                contingency_info = {
                    'id': f"REACTOR_{reactor_num}",
                    'name': contingency['name'],
                    'type': 'Reactor Outage',
                    'description': f"OUTAGE OF {contingency['name']}",
                    'details': details.get('display', ''),
                    'display': f"OUTAGE OF {details.get('display', f'Reactor {reactor_num}')}"
                }
        
        elif contingency['type'] == 'series_comp':
            sc_num = contingency['num']
            if sc_num in self.full_data.get('series_comps', {}):
                self.full_data['series_comps'][sc_num]['status'] = 0
                details = self.element_details.get(f'SERIES_COMP_{sc_num}', {})
                contingency_info = {
                    'id': f"SERIES_COMP_{sc_num}",
                    'name': contingency['name'],
                    'type': 'Series Compensation Outage',
                    'description': f"OUTAGE OF {contingency['name']}",
                    'details': details.get('display', ''),
                    'display': f"OUTAGE OF {details.get('display', f'Series Compensation {sc_num}')}"
                }
        
        elif contingency['type'] == 'series_reactor':
            sr_num = contingency['num']
            if sr_num in self.full_data.get('series_reactors', {}):
                self.full_data['series_reactors'][sr_num]['status'] = 0
                details = self.element_details.get(f'SERIES_REACTOR_{sr_num}', {})
                contingency_info = {
                    'id': f"SERIES_REACTOR_{sr_num}",
                    'name': contingency['name'],
                    'type': 'Series Reactor Outage',
                    'description': f"OUTAGE OF {contingency['name']}",
                    'details': details.get('display', ''),
                    'display': f"OUTAGE OF {details.get('display', f'Series Reactor {sr_num}')}"
                }
        
        elif contingency['type'] == 'shunt':
            shunt_num = contingency['num']
            if shunt_num in self.full_data.get('shunts', {}):
                self.full_data['shunts'][shunt_num]['status'] = 0
                details = self.element_details.get(f'SHUNT_{shunt_num}', {})
                contingency_info = {
                    'id': f"SHUNT_{shunt_num}",
                    'name': contingency['name'],
                    'type': 'Shunt Outage',
                    'description': f"OUTAGE OF {contingency['name']}",
                    'details': details.get('display', ''),
                    'display': f"OUTAGE OF {details.get('display', f'Shunt {shunt_num}')}"
                }
        
        elif contingency['type'] == 'bus_outage':
            bus_num = contingency['num']
            connected_elements = self.get_connected_elements_description(bus_num)
            details = self.element_details.get(f'BUS_{bus_num}', {})
            
            conn = self.bus_connections.get(bus_num, {})
            offline_count = 0
            
            for line_num in conn.get('lines', []):
                if line_num in self.full_data.get('lines', {}):
                    if line_num not in self.originally_offline['lines']:
                        self.full_data['lines'][line_num]['status'] = 0
                        offline_count += 1
            
            for xfmr_num in conn.get('transformers', []):
                if xfmr_num in self.full_data.get('transformers', {}):
                    if xfmr_num not in self.originally_offline['transformers']:
                        self.full_data['transformers'][xfmr_num]['status'] = 0
                        offline_count += 1
            
            for gen_num in conn.get('generators', []):
                if gen_num in self.full_data.get('generators', {}):
                    if gen_num not in self.originally_offline['generators']:
                        self.full_data['generators'][gen_num]['status'] = 0
                        self.full_data['generators'][gen_num]['P_out'] = 0
                        offline_count += 1
            
            for load_num in conn.get('loads', []):
                if load_num in self.full_data.get('loads', {}):
                    if load_num not in self.originally_offline['loads']:
                        self.full_data['loads'][load_num]['status'] = 0
                        self.full_data['loads'][load_num]['P_demand'] = 0
                        self.full_data['loads'][load_num]['Q_demand'] = 0
                        offline_count += 1
            
            for cap_num in conn.get('capacitors', []):
                if cap_num in self.full_data.get('capacitors', {}):
                    if cap_num not in self.originally_offline['capacitors']:
                        self.full_data['capacitors'][cap_num]['status'] = 0
                        offline_count += 1
            
            for reactor_num in conn.get('reactors', []):
                if reactor_num in self.full_data.get('reactors', {}):
                    if reactor_num not in self.originally_offline['reactors']:
                        self.full_data['reactors'][reactor_num]['status'] = 0
                        offline_count += 1
            
            elements_desc = "\n".join(connected_elements) if connected_elements else "    • No connected elements found"
            
            contingency_info = {
                'id': f"BUS_OUTAGE_{bus_num}",
                'name': details.get('name', f'Bus_{bus_num}'),
                'type': 'Bus Outage (All Connected Elements)',
                'description': f"OUTAGE OF BUS {bus_num} - ALL CONNECTED ELEMENTS REMOVED",
                'details': f"Bus {bus_num}: {details.get('name', f'Bus_{bus_num}')} at {details.get('base_kv', 0)} kV\n\nConnected elements removed ({offline_count} elements):\n{elements_desc}",
                'display': f"OUTAGE OF BUS {bus_num}: {details.get('name', f'Bus_{bus_num}')} at {details.get('base_kv', 0)} kV - Removed {offline_count} connected elements"
            }
        
        elif contingency['type'] == 'bus_voltage':
            bus_num = contingency['num']
            if bus_num in self.bus_data:
                details = self.element_details.get(f'BUS_{bus_num}', {})
                original_v = self.bus_data[bus_num].get('V_init', 1.0)
                self.bus_data[bus_num]['V_init'] = original_v * 0.95
                contingency_info = {
                    'id': f"BUS_VOLTAGE_{bus_num}",
                    'name': details.get('name', f'Bus_{bus_num}'),
                    'type': 'Voltage Reduction',
                    'description': f"VOLTAGE REDUCTION AT BUS {bus_num}",
                    'details': f"Bus {bus_num}: {details.get('name', f'Bus_{bus_num}')} at {details.get('base_kv', 0)} kV\nVoltage reduced from {original_v:.3f} pu to {original_v*0.95:.3f} pu (-5%)",
                    'display': f"VOLTAGE REDUCTION AT BUS {bus_num}: {details.get('name', f'Bus_{bus_num}')} from {original_v:.3f} pu to {original_v*0.95:.3f} pu (-5%)"
                }
        
        # Convert to engine format
        bus_data_engine, branch_data_engine, full_data_engine = InputReader.convert_to_engine_format(self.full_data)
        
        # Update bus_data_engine with modified V_init
        for bus_num, bus in self.bus_data.items():
            if bus_num in bus_data_engine:
                bus_data_engine[bus_num]['V_init'] = bus.get('V_init', 1.0)
        
        return bus_data_engine, branch_data_engine, full_data_engine, contingency_info
    
    def run_single_contingency(self, contingency, variation_strength=0.10, n_samples=200):
        """Run a single contingency and return results"""
        mod_bus_data, mod_branch_data, mod_full_data, info = self.apply_contingency(contingency)
        
        # Determine voltage initialization mode for contingency
        cont_init = str(getattr(self, 'v_init_cont', 'warm')).lower()
        if 'warm' in cont_init and not 'seq' in cont_init and getattr(self, 'base_case_v_mag', None) is not None:
            v_mag = self.base_case_v_mag
            v_ang = self.base_case_v_angle
            for idx, b_num in enumerate(sorted(mod_bus_data.keys())):
                if idx < len(v_mag):
                    mod_bus_data[b_num]['V_init'] = v_mag[idx]
                    mod_bus_data[b_num]['angle_init'] = v_ang[idx]
            v_init_mode = 'initial'
        elif 'seq' in cont_init and getattr(self, 'prev_cont_v_mag', None) is not None:
            v_mag = self.prev_cont_v_mag
            v_ang = self.prev_cont_v_angle
            for idx, b_num in enumerate(sorted(mod_bus_data.keys())):
                if idx < len(v_mag):
                    mod_bus_data[b_num]['V_init'] = v_mag[idx]
                    mod_bus_data[b_num]['angle_init'] = v_ang[idx]
            v_init_mode = 'initial'
        elif 'initial' in cont_init:
            v_init_mode = 'initial'
        else:
            v_init_mode = 'flat'

        # Resolve solver method tag
        eng_choice = getattr(self, 'engine_choice', 'andes').lower()
        meth = getattr(self, 'method', 'nr').lower()
        if eng_choice == 'inverse':
            solver_method = 'inverse'
        elif '_' in meth:
            solver_method = meth
        else:
            solver_method = f"{eng_choice}_{meth}"

        fb_opts = getattr(self, 'fallback_opts', None)
        if fb_opts and isinstance(fb_opts, dict):
            fb_opts = dict(fb_opts)
            fb_opts['stage_max_iter'] = min(getattr(self, 'max_iter', 20), int(fb_opts.get('stage_max_iter', getattr(self, 'max_iter', 20))))

        engine = PowerFlowEngine(baseMVA=self.baseMVA)
        engine.initialize(
            mod_bus_data, mod_branch_data, full_data=mod_full_data,
            solver_method=solver_method, tol=getattr(self, 'tol', 0.000001),
            max_iter=getattr(self, 'max_iter', 20),
            ignore_q_tol=getattr(self, 'ignore_q_tol', False),
            ignore_islands=getattr(self, 'ignore_islands', True),
            industry_std_pv=getattr(self, 'industry_std_pv', True),
            v_init_mode=v_init_mode,
            fallback_opts=fb_opts
        )
        samples, valid_count = engine.run_batch(n_samples=n_samples, variation_strength=variation_strength)
        
        if samples:
            self.prev_cont_v_mag = samples[0].get('V_mag')
            self.prev_cont_v_angle = samples[0].get('V_angle')

        return samples, valid_count, engine, mod_full_data, info
    
    def get_all_contingencies(self):
        """Return all possible contingencies with their descriptions"""
        contingencies = []
        
        # Lines
        for line_num, line in self.original_data.get('lines', {}).items():
            if line_num not in self.originally_offline['lines'] and line.get('status', 1) == 1:
                details = self.element_details.get(f'LINE_{line_num}', {})
                contingencies.append({
                    'type': 'line',
                    'num': line_num,
                    'name': line.get('name', f'Line_{line_num}'),
                    'display': f" {details.get('display', f'Line {line_num}')}"
                })
        
        # Transformers
        for xfmr_num, xfmr in self.original_data.get('transformers', {}).items():
            if xfmr_num not in self.originally_offline['transformers'] and xfmr.get('status', 1) == 1:
                details = self.element_details.get(f'XFMR_{xfmr_num}', {})
                contingencies.append({
                    'type': 'transformer',
                    'num': xfmr_num,
                    'name': xfmr.get('name', f'Xfmr_{xfmr_num}'),
                    'display': f" {details.get('display', f'Transformer {xfmr_num}')}"
                })
        
        # Generators & Synchronous Motors
        for gen_num, gen in self.original_data.get('generators', {}).items():
            if gen_num not in self.originally_offline['generators'] and gen.get('status', 1) == 1:
                is_sm = (str(gen.get('gen_type', '')).upper() == 'SYNC_MOTOR' or 
                         str(gen.get('name', '')).upper().startswith('SM') or 
                         float(gen.get('P_out', gen.get('P_gen', 0.0))) < 0)
                prefix = 'SYNC_MOTOR_' if is_sm else 'GEN_'
                details = self.element_details.get(f'{prefix}{gen_num}', self.element_details.get(f'GEN_{gen_num}', {}))
                c_type = 'sync_motor' if is_sm else 'generator'
                default_name = f'SM_{gen_num}' if is_sm else f'Gen_{gen_num}'
                contingencies.append({
                    'type': c_type,
                    'num': gen_num,
                    'name': gen.get('name', default_name),
                    'display': f" {details.get('display', f'{c_type} {gen_num}')}"
                })
        
        # Loads
        for load_num, load in self.original_data.get('loads', {}).items():
            if load_num not in self.originally_offline['loads'] and load.get('status', 1) == 1:
                details = self.element_details.get(f'LOAD_{load_num}', {})
                contingencies.append({
                    'type': 'load',
                    'num': load_num,
                    'name': load.get('name', f'Load_{load_num}'),
                    'display': f" {details.get('display', f'Load {load_num}')} [0%]"
                })
        
        # Capacitors
        for cap_num, cap in self.original_data.get('capacitors', {}).items():
            if cap_num not in self.originally_offline['capacitors'] and cap.get('status', 1) == 1:
                details = self.element_details.get(f'CAP_{cap_num}', {})
                contingencies.append({
                    'type': 'capacitor',
                    'num': cap_num,
                    'name': cap.get('name', f'Cap_{cap_num}'),
                    'display': f" {details.get('display', f'Capacitor {cap_num}')}"
                })
        
        # Reactors
        for reactor_num, reactor in self.original_data.get('reactors', {}).items():
            if reactor_num not in self.originally_offline['reactors'] and reactor.get('status', 1) == 1:
                details = self.element_details.get(f'REACTOR_{reactor_num}', {})
                contingencies.append({
                    'type': 'reactor',
                    'num': reactor_num,
                    'name': reactor.get('name', f'Reactor_{reactor_num}'),
                    'display': f" {details.get('display', f'Reactor {reactor_num}')}"
                })
        
        # Series Compensation
        for sc_num, sc in self.original_data.get('series_comps', {}).items():
            if sc_num not in self.originally_offline['series_comps'] and sc.get('status', 1) == 1:
                details = self.element_details.get(f'SERIES_COMP_{sc_num}', {})
                contingencies.append({
                    'type': 'series_comp',
                    'num': sc_num,
                    'name': sc.get('name', f'SC_{sc_num}'),
                    'display': f" {details.get('display', f'Series Compensation {sc_num}')}"
                })
        
        # Series Reactors
        for sr_num, sr in self.original_data.get('series_reactors', {}).items():
            if sr_num not in self.originally_offline['series_reactors'] and sr.get('status', 1) == 1:
                details = self.element_details.get(f'SERIES_REACTOR_{sr_num}', {})
                contingencies.append({
                    'type': 'series_reactor',
                    'num': sr_num,
                    'name': sr.get('name', f'SR_{sr_num}'),
                    'display': f" {details.get('display', f'Series Reactor {sr_num}')}"
                })
        
        # Shunts
        for shunt_num, shunt in self.original_data.get('shunts', {}).items():
            if shunt_num not in self.originally_offline['shunts'] and shunt.get('status', 1) == 1:
                details = self.element_details.get(f'SHUNT_{shunt_num}', {})
                contingencies.append({
                    'type': 'shunt',
                    'num': shunt_num,
                    'name': shunt.get('name', f'Shunt_{shunt_num}'),
                    'display': f" {details.get('display', f'Shunt {shunt_num}')}"
                })
        
        # Bus Outage
        for bus_num, bus in self.original_data.get('buses', {}).items():
            details = self.element_details.get(f'BUS_{bus_num}', {})
            contingencies.append({
                'type': 'bus_outage',
                'num': bus_num,
                'name': bus.get('name', f'Bus_{bus_num}'),
                'display': f" BUS OUTAGE {bus_num}: {details.get('display', f'Bus_{bus_num}')} - Remove ALL connected elements"
            })
        
        # Bus Voltage Reduction
        for bus_num, bus in self.original_data.get('buses', {}).items():
            details = self.element_details.get(f'BUS_{bus_num}', {})
            contingencies.append({
                'type': 'bus_voltage',
                'num': bus_num,
                'name': bus.get('name', f'Bus_{bus_num}'),
                'display': f" {details.get('display', f'Bus_{bus_num}')} (Voltage -5%)"
            })
        
        return contingencies


# ============================================================================
# CONSOLIDATION MODULE
# ============================================================================

class ReportConsolidator:
    """Consolidates all individual contingency reports into single master files"""
    
    def __init__(self, output_folder, case_name):
        self.output_folder = output_folder
        self.case_name = case_name
        self.contingency_files = []
        
    def scan_for_files(self):
        """Scan the output folder for all contingency report files"""
        self.contingency_files = []
        
        for file in os.listdir(self.output_folder):
            if file.endswith('_ALL_DATA.csv') and 'BASE_CASE' not in file and 'CONSOLIDATED' not in file:
                match = re.match(r'(LINE_\d+|XFMR_\d+|GEN_\d+|LOAD_\d+|CAP_\d+|REACTOR_\d+|SERIES_COMP_\d+|SERIES_REACTOR_\d+|SHUNT_\d+|BUS_OUTAGE_\d+|BUS_VOLTAGE_\d+)_', file)
                if match:
                    csv_path = os.path.join(self.output_folder, file)
                    summary_path = csv_path.replace('_ALL_DATA.csv', '_SUMMARY.txt')
                    info_path = csv_path.replace('_ALL_DATA.csv', '_CONTINGENCY_INFO.txt')
                    py_path = csv_path.replace('_ALL_DATA.csv', '_ALL_DATA.py')

                    contingency = {
                        'csv': csv_path,
                        'summary': summary_path,
                        'info': info_path,
                        'py': py_path,
                        'id': match.group(1),
                        'timestamp': re.search(r'_(\d{14})_', file).group(1) if re.search(r'_(\d{14})_', file) else ''
                    }
                    
                    if os.path.exists(csv_path):
                        self.contingency_files.append(contingency)
        
        self.contingency_files.sort(key=lambda x: x['id'])
        print(f"\n Found {len(self.contingency_files)} contingency files to consolidate")
        return self.contingency_files
    
    def extract_display_info(self, info_path):
        """Extract the display description from INFO file"""
        if not os.path.exists(info_path):
            return "Unknown Contingency"
        
        try:
            with open(info_path, 'r', encoding='utf-8') as f:
                content = f.read()
                display_match = re.search(r'Display: (.+)', content)
                if display_match:
                    return display_match.group(1).strip()
                desc_match = re.search(r'Description: (.+)', content)
                if desc_match:
                    return desc_match.group(1).strip()
        except:
            pass
        return "Unknown Contingency"
    
    def consolidate_csv(self):
        """Combine all CSV files into one master CSV"""
        
        master_csv = os.path.join(self.output_folder, f"{self.case_name}_CONSOLIDATED_ALL_DATA.csv")
        
        with open(master_csv, 'w', newline='', encoding='utf-8') as outfile:
            writer = csv.writer(outfile)
            
            writer.writerow(['#' + '='*78])
            writer.writerow(['# CONSOLIDATED CONTINGENCY ANALYSIS - ALL DATA'])
            writer.writerow(['# ' + f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'])
            writer.writerow(['# ' + f'Case: {self.case_name}'])
            writer.writerow(['# ' + f'Total Contingencies: {len(self.contingency_files)}'])
            writer.writerow(['#' + '='*78])
            writer.writerow([])
            
            # Table of Contents
            writer.writerow(['# TABLE OF CONTENTS'])
            writer.writerow(['#' + '-'*78])
            for idx, cf in enumerate(self.contingency_files, 1):
                display = self.extract_display_info(cf.get('info', ''))
                writer.writerow([f'#   {idx:3d}. {display[:70]}'])
            writer.writerow(['#' + '-'*78])
            writer.writerow([])
            
            for idx, cf in enumerate(self.contingency_files, 1):
                display = self.extract_display_info(cf.get('info', ''))
                
                writer.writerow([f'#{"="*78}'])
                writer.writerow([f'# CONTINGENCY {idx}: {cf["id"]}'])
                writer.writerow([f'# {display}'])
                writer.writerow([f'#{"="*78}'])
                writer.writerow([])
                
                if os.path.exists(cf['csv']):
                    with open(cf['csv'], 'r', encoding='utf-8') as infile:
                        csv_reader = csv.reader(infile)
                        for row in csv_reader:
                            if row and row[0].startswith('#'):
                                continue
                            writer.writerow(row)
                
                writer.writerow([])
        
        print(f"   Consolidated CSV: {master_csv}")
        return master_csv
    
    def consolidate_txt(self):
        """Combine all TXT summary files into one master TXT"""
        
        master_txt = os.path.join(self.output_folder, f"{self.case_name}_CONSOLIDATED_SUMMARY.txt")
        
        with open(master_txt, 'w', encoding='utf-8') as outfile:
            outfile.write("="*100 + "\n")
            outfile.write("CONSOLIDATED CONTINGENCY ANALYSIS - MASTER SUMMARY\n")
            outfile.write("="*100 + "\n")
            outfile.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            outfile.write(f"Case: {self.case_name}\n")
            outfile.write(f"Total Contingencies: {len(self.contingency_files)}\n")
            outfile.write("="*100 + "\n\n")
            
            # Table of Contents
            outfile.write("TABLE OF CONTENTS\n")
            outfile.write("-"*80 + "\n")
            for idx, cf in enumerate(self.contingency_files, 1):
                display = self.extract_display_info(cf.get('info', ''))
                outfile.write(f"  {idx:3d}. {display}\n")
            outfile.write("\n" + "="*100 + "\n\n")
            
            for idx, cf in enumerate(self.contingency_files, 1):
                display = self.extract_display_info(cf.get('info', ''))
                
                outfile.write("\n" + "="*100 + "\n")
                outfile.write(f"CONTINGENCY {idx}: {cf['id']}\n")
                outfile.write("="*100 + "\n")
                outfile.write(f"Description: {display}\n")
                outfile.write("-"*100 + "\n\n")
                
                if os.path.exists(cf.get('info', '')):
                    with open(cf['info'], 'r', encoding='utf-8') as infof:
                        content = infof.read()
                        lines = content.split('\n')
                        for line in lines:
                            if line.startswith('Type:') or line.startswith('Element:') or line.startswith('Details:'):
                                outfile.write(line + '\n')
                        outfile.write('\n')
                
                if os.path.exists(cf.get('summary', '')):
                    with open(cf['summary'], 'r', encoding='utf-8') as infof:
                        summary_content = infof.read()
                        lines = summary_content.split('\n')
                        copy_mode = False
                        for line in lines:
                            if 'SYSTEM SUMMARY' in line or 'BUS VOLTAGE' in line or 'SECTION 1:' in line:
                                copy_mode = True
                            if copy_mode:
                                outfile.write(line + '\n')
                        outfile.write('\n')
                
                outfile.write("-"*80 + "\n\n")
        
        print(f"   Consolidated TXT: {master_txt}")
        return master_txt
    
    # def consolidate_py(self):
    #     """Combine all PY files into one master PY file"""
        
    #     master_py = os.path.join(self.output_folder, f"{self.case_name}_CONSOLIDATED_ALL_DATA.py")
        
    #     with open(master_py, 'w', encoding='utf-8') as outfile:
    #         # Master Header
    #         outfile.write('"""\n')
    #         outfile.write('CONSOLIDATED CONTINGENCY ANALYSIS - ALL DATA\n')
    #         outfile.write(f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
    #         outfile.write(f'Case: {self.case_name}\n')
    #         outfile.write(f'Total Contingencies: {len(self.contingency_files)}\n')
    #         outfile.write('This file contains ALL contingency results in Python format\n')
    #         outfile.write('"""\n\n')
            
    #         outfile.write('import numpy as np\n\n')
            
    #         # Create master dictionary
    #         outfile.write('# ============================================================================\n')
    #         outfile.write('# MASTER CONTINGENCY RESULTS DICTIONARY\n')
    #         outfile.write('# ============================================================================\n\n')
    #         outfile.write('CONSOLIDATED_CONTINGENCIES = {\n')
    #         outfile.write(f'    "case_name": "{self.case_name}",\n')
    #         outfile.write(f'    "generated": "{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}",\n')
    #         outfile.write(f'    "total_contingencies": {len(self.contingency_files)},\n')
    #         outfile.write('    "contingencies": [\n')
            
    #         # Add each contingency summary
    #         for idx, cf in enumerate(self.contingency_files, 1):
    #             display = self.extract_display_info(cf.get('info', ''))
    #             outfile.write(f'        {{\n')
    #             outfile.write(f'            "id": "{cf["id"]}",\n')
    #             outfile.write(f'            "index": {idx},\n')
    #             outfile.write(f'            "description": "{display[:100]}",\n')
    #             outfile.write(f'            "file_prefix": "{cf["id"]}"\n')
    #             outfile.write(f'        }},\n')
            
    #         outfile.write('    ]\n')
    #         outfile.write('}\n\n')
            
    #         # Write each contingency's full data
    #         for idx, cf in enumerate(self.contingency_files, 1):
    #             display = self.extract_display_info(cf.get('info', ''))
                
    #             outfile.write(f'\n# ============================================================================\n')
    #             outfile.write(f'# CONTINGENCY {idx}: {cf["id"]}\n')
    #             outfile.write(f'# {display}\n')
    #             outfile.write(f'# ============================================================================\n\n')
                
    #             outfile.write(f'CONTINGENCY_{idx} = {{\n')
    #             outfile.write(f'    "id": "{cf["id"]}",\n')
    #             outfile.write(f'    "index": {idx},\n')
    #             outfile.write(f'    "description": "{display}",\n')
    #             outfile.write(f'    "file_prefix": "{cf["id"]}"\n')
    #             outfile.write('}\n\n')
                
    #             # Copy the PY file content (skip header comments)
    #             py_file = cf.get('py', cf['csv'].replace('_ALL_DATA.csv', '_ALL_DATA.py'))
    #             if os.path.exists(py_file):
    #                 with open(py_file, 'r', encoding='utf-8') as infile:
    #                     content = infile.read()
    #                     # Skip the initial docstring/comments
    #                     lines = content.split('\n')
    #                     copy_mode = False
    #                     for line in lines:
    #                         if 'BUS_DATA' in line or 'LINE_DATA' in line or 'TRANSFORMER_DATA' in line or 'SYSTEM_SUMMARY' in line:
    #                             copy_mode = True
    #                         if copy_mode and not line.startswith('"""') and not line.startswith('if __name__'):
    #                             outfile.write(line + '\n')
                
    #             outfile.write('\n')
            
    #         # Add helper function to get contingency by ID
    #         outfile.write('\n# ============================================================================\n')
    #         outfile.write('# HELPER FUNCTIONS\n')
    #         outfile.write('# ============================================================================\n\n')
    #         outfile.write('def get_contingency_by_id(contingency_id):\n')
    #         outfile.write('    """Get contingency data by ID (e.g., "LINE_1", "GEN_2")"""\n')
    #         outfile.write('    for i in range(1, len(CONSOLIDATED_CONTINGENCIES["contingencies"]) + 1):\n')
    #         outfile.write('        if globals().get(f"CONTINGENCY_{i}", {}).get("id") == contingency_id:\n')
    #         outfile.write('            return globals().get(f"CONTINGENCY_{i}")\n')
    #         outfile.write('    return None\n\n')
            
    #         outfile.write('def get_all_contingency_ids():\n')
    #         outfile.write('    """Get list of all contingency IDs"""\n')
    #         outfile.write('    return [c["id"] for c in CONSOLIDATED_CONTINGENCIES["contingencies"]]\n\n')
            
    #         outfile.write('if __name__ == "__main__":\n')
    #         outfile.write('    print("="*60)\n')
    #         outfile.write('    print("CONSOLIDATED CONTINGENCY ANALYSIS")\n')
    #         outfile.write('    print("="*60)\n')
    #         outfile.write(f'    print(f"Case: {self.case_name}")\n')
    #         outfile.write(f'    print(f"Total Contingencies: {len(self.contingency_files)}")\n')
    #         outfile.write('    print("="*60)\n')
    #         outfile.write('    for c in CONSOLIDATED_CONTINGENCIES["contingencies"]:\n')
    #         outfile.write('        print(f"  {c[\'index\']:3d}. {c[\'description\']}")\n')
    #         outfile.write('    print("="*60)\n')
        
    #     print(f"  ✅ Consolidated PY: {master_py}")
    #     return master_py

    # def consolidate_py(self):
    #     """Combine all PY files into one master PY file with proper structure"""
        
    #     master_py = os.path.join(self.output_folder, f"{self.case_name}_CONSOLIDATED_ALL_DATA.py")
        
    #     with open(master_py, 'w', encoding='utf-8') as outfile:
    #         # Master Header
    #         outfile.write('"""\n')
    #         outfile.write('CONSOLIDATED CONTINGENCY ANALYSIS - ALL DATA\n')
    #         outfile.write(f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
    #         outfile.write(f'Case: {self.case_name}\n')
    #         outfile.write(f'Total Contingencies: {len(self.contingency_files)}\n')
    #         outfile.write('This file contains ALL contingency results in Python format\n')
    #         outfile.write('"""\n\n')
            
    #         outfile.write('import numpy as np\n\n')
            
    #         # =========================================================
    #         # MASTER DICTIONARY WITH ALL CONTINGENCIES
    #         # =========================================================
    #         outfile.write('# ============================================================================\n')
    #         outfile.write('# MASTER CONTINGENCY RESULTS DICTIONARY\n')
    #         outfile.write('# ============================================================================\n\n')
    #         outfile.write('CONSOLIDATED_CONTINGENCIES = {\n')
    #         outfile.write(f'    "case_name": "{self.case_name}",\n')
    #         outfile.write(f'    "generated": "{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}",\n')
    #         outfile.write(f'    "total_contingencies": {len(self.contingency_files)},\n')
    #         outfile.write('    "contingencies": [\n')
            
    #         for idx, cf in enumerate(self.contingency_files, 1):
    #             display = self.extract_display_info(cf.get('info', ''))
    #             outfile.write(f'        {{\n')
    #             outfile.write(f'            "id": "{cf["id"]}",\n')
    #             outfile.write(f'            "index": {idx},\n')
    #             outfile.write(f'            "description": "{display[:100]}",\n')
    #             outfile.write(f'            "var_name": "CONTINGENCY_{idx}"\n')
    #             outfile.write(f'        }},\n')
            
    #         outfile.write('    ]\n')
    #         outfile.write('}\n\n')
            
    #         # =========================================================
    #         # BASE CASE DATA
    #         # =========================================================
    #         outfile.write('# ============================================================================\n')
    #         outfile.write('# BASE CASE (No Contingency)\n')
    #         outfile.write('# ============================================================================\n\n')
            
    #         # Find base case files
    #         base_csv = None
    #         base_py = None
    #         for file in os.listdir(self.output_folder):
    #             if file.startswith('BASE_CASE_') and file.endswith('_ALL_DATA.py'):
    #                 base_py = os.path.join(self.output_folder, file)
    #                 break
            
    #         if base_py and os.path.exists(base_py):
    #             with open(base_py, 'r', encoding='utf-8') as infile:
    #                 content = infile.read()
    #                 # Extract only data arrays (skip header comments)
    #                 lines = content.split('\n')
    #                 in_data = False
    #                 for line in lines:
    #                     if 'BUS_DATA = [' in line or 'GENERATOR_DATA = [' in line or 'LINE_DATA = [' in line or 'TRANSFORMER_DATA = [' in line or 'CAPACITOR_DATA = [' in line or 'REACTOR_DATA = [' in line:
    #                         in_data = True
    #                     if in_data:
    #                         outfile.write(line + '\n')
    #                         if line.strip() == ']' and 'BUS_DATA' not in line:
    #                             in_data = False
    #         else:
    #             outfile.write('BASE_CASE_DATA = {\n')
    #             outfile.write('    "id": "BASE_CASE",\n')
    #             outfile.write('    "description": "Base Case - No Contingency",\n')
    #             outfile.write('    "data": {}\n')
    #             outfile.write('}\n\n')
            
    #         # =========================================================
    #         # EACH CONTINGENCY DATA
    #         # =========================================================
    #         for idx, cf in enumerate(self.contingency_files, 1):
    #             display = self.extract_display_info(cf.get('info', ''))
                
    #             outfile.write(f'\n# ============================================================================\n')
    #             outfile.write(f'# CONTINGENCY {idx}: {cf["id"]}\n')
    #             outfile.write(f'# {display}\n')
    #             outfile.write(f'# ============================================================================\n\n')
                
    #             # Write contingency info dictionary
    #             outfile.write(f'CONTINGENCY_{idx} = {{\n')
    #             outfile.write(f'    "id": "{cf["id"]}",\n')
    #             outfile.write(f'    "index": {idx},\n')
    #             outfile.write(f'    "description": "{display}",\n')
    #             outfile.write(f'    "file_prefix": "{cf["id"]}",\n')
    #             outfile.write(f'    "data": {{\n')
                
    #             # Extract and embed the PY data from contingency file
    #             py_file = cf.get('py', cf['csv'].replace('_ALL_DATA.csv', '_ALL_DATA.py'))
    #             if os.path.exists(py_file):
    #                 with open(py_file, 'r', encoding='utf-8') as infile:
    #                     content = infile.read()
                        
    #                     # Extract each data section
    #                     sections = ['BUS_DATA', 'GENERATOR_DATA', 'LINE_DATA', 'TRANSFORMER_DATA', 
    #                                 'CAPACITOR_DATA', 'REACTOR_DATA', 'SERIES_COMP_DATA', 'SERIES_REACTOR_DATA', 
    #                                 'SHUNT_DATA', 'SYSTEM_SUMMARY']
                        
    #                     for section in sections:
    #                         # Find the section content
    #                         pattern = rf'{section}\s*=\s*\[(.*?)\];?\s*\n'
    #                         import re
    #                         match = re.search(pattern, content, re.DOTALL)
    #                         if match:
    #                             section_content = match.group(0)
    #                             # Indent properly
    #                             indented = '\n        '.join(section_content.split('\n'))
    #                             outfile.write(f'        "{section}": {indented}\n')
    #                         else:
    #                             outfile.write(f'        "{section}": [],\n')
                
    #             outfile.write(f'    }}\n')
    #             outfile.write(f'}}\n\n')
            
    #         # =========================================================
    #         # HELPER FUNCTIONS
    #         # =========================================================
    #         outfile.write('\n# ============================================================================\n')
    #         outfile.write('# HELPER FUNCTIONS\n')
    #         outfile.write('# ============================================================================\n\n')
            
    #         outfile.write('def get_contingency_by_id(contingency_id):\n')
    #         outfile.write('    """Get contingency data by ID (e.g., "LINE_1", "GEN_2", "BUS_OUTAGE_11")"""\n')
    #         outfile.write('    for i in range(1, len(CONSOLIDATED_CONTINGENCIES["contingencies"]) + 1):\n')
    #         outfile.write('        if globals().get(f"CONTINGENCY_{i}", {}).get("id") == contingency_id:\n')
    #         outfile.write('            return globals().get(f"CONTINGENCY_{i}")\n')
    #         outfile.write('    return None\n\n')
            
    #         outfile.write('def get_contingency_by_index(index):\n')
    #         outfile.write('    """Get contingency data by index (1-based)"""\n')
    #         outfile.write('    return globals().get(f"CONTINGENCY_{index}", None)\n\n')
            
    #         outfile.write('def get_all_contingency_ids():\n')
    #         outfile.write('    """Get list of all contingency IDs"""\n')
    #         outfile.write('    return [c["id"] for c in CONSOLIDATED_CONTINGENCIES["contingencies"]]\n\n')
            
    #         outfile.write('def get_contingency_bus_data(contingency_id):\n')
    #         outfile.write('    """Get BUS_DATA for a specific contingency"""\n')
    #         outfile.write('    cont = get_contingency_by_id(contingency_id)\n')
    #         outfile.write('    return cont["data"]["BUS_DATA"] if cont else []\n\n')
            
    #         outfile.write('def get_contingency_line_data(contingency_id):\n')
    #         outfile.write('    """Get LINE_DATA for a specific contingency"""\n')
    #         outfile.write('    cont = get_contingency_by_id(contingency_id)\n')
    #         outfile.write('    return cont["data"]["LINE_DATA"] if cont else []\n\n')
            
    #         outfile.write('def get_contingency_generator_data(contingency_id):\n')
    #         outfile.write('    """Get GENERATOR_DATA for a specific contingency"""\n')
    #         outfile.write('    cont = get_contingency_by_id(contingency_id)\n')
    #         outfile.write('    return cont["data"]["GENERATOR_DATA"] if cont else []\n\n')
            
    #         outfile.write('def get_contingency_summary(contingency_id):\n')
    #         outfile.write('    """Get SYSTEM_SUMMARY for a specific contingency"""\n')
    #         outfile.write('    cont = get_contingency_by_id(contingency_id)\n')
    #         outfile.write('    return cont["data"].get("SYSTEM_SUMMARY", {}) if cont else {}\n\n')
            
    #         outfile.write('def list_all_contingencies():\n')
    #         outfile.write('    """Print all contingencies in a formatted table"""\n')
    #         outfile.write('    print("="*80)\n')
    #         outfile.write('    print("CONTINGENCY LIST")\n')
    #         outfile.write('    print("="*80)\n')
    #         outfile.write('    print(f"\\n{'Index':<8} {'ID':<20} {'Description'}")\n')
    #         outfile.write('    print("-"*80)\n')
    #         outfile.write('    for c in CONSOLIDATED_CONTINGENCIES["contingencies"]:\n')
    #         outfile.write('        print(f"{c[\\"index\\"]:<8} {c[\\"id\\"]:<20} {c[\\"description\\"][:50]}")\n')
    #         outfile.write('    print("="*80)\n\n')
            
    #         # =========================================================
    #         # MAIN EXECUTION
    #         # =========================================================
    #         outfile.write('\n# ============================================================================\n')
    #         outfile.write('# MAIN EXECUTION\n')
    #         outfile.write('# ============================================================================\n\n')
    #         outfile.write('if __name__ == "__main__":\n')
    #         outfile.write('    print("="*60)\n')
    #         outfile.write('    print("CONSOLIDATED CONTINGENCY ANALYSIS")\n')
    #         outfile.write('    print("="*60)\n')
    #         outfile.write(f'    print(f"Case: {self.case_name}")\n')
    #         outfile.write(f'    print(f"Total Contingencies: {len(self.contingency_files)}")\n')
    #         outfile.write('    print("="*60)\n')
    #         outfile.write('    list_all_contingencies()\n')
    #         outfile.write('    print("\\n" + "="*60)\n')
    #         outfile.write('    print("Example usage:")\n')
    #         outfile.write('    print(\'  data = get_contingency_by_id("LINE_1")\')\n')
    #         outfile.write('    print(\'  buses = get_contingency_bus_data("LINE_1")\')\n')
    #         outfile.write('    print(\'  summary = get_contingency_summary("LINE_1")\')\n')
    #         outfile.write('    print("="*60)\n')
        
    #     print(f"  ✅ Consolidated PY: {master_py}")
    #     return master_py


    def consolidate_py(self):
        """Combine all PY files into one master PY file with proper structure"""
        
        master_py = os.path.join(self.output_folder, f"{self.case_name}_CONSOLIDATED_ALL_DATA.py")
        
        with open(master_py, 'w', encoding='utf-8') as outfile:
            # Master Header
            outfile.write('"""\n')
            outfile.write('CONSOLIDATED CONTINGENCY ANALYSIS - ALL DATA\n')
            outfile.write(f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
            outfile.write(f'Case: {self.case_name}\n')
            outfile.write(f'Total Contingencies: {len(self.contingency_files)}\n')
            outfile.write('This file contains ALL contingency results in Python format\n')
            outfile.write('"""\n\n')
            
            outfile.write('import numpy as np\n\n')
            
            # =========================================================
            # MASTER DICTIONARY WITH ALL CONTINGENCIES
            # =========================================================
            outfile.write('# ============================================================================\n')
            outfile.write('# MASTER CONTINGENCY RESULTS DICTIONARY\n')
            outfile.write('# ============================================================================\n\n')
            outfile.write('CONSOLIDATED_CONTINGENCIES = {\n')
            outfile.write(f'    "case_name": "{self.case_name}",\n')
            outfile.write(f'    "generated": "{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}",\n')
            outfile.write(f'    "total_contingencies": {len(self.contingency_files)},\n')
            outfile.write('    "contingencies": [\n')
            
            for idx, cf in enumerate(self.contingency_files, 1):
                display = self.extract_display_info(cf.get('info', ''))
                # Escape any quotes in display string
                display_escaped = display.replace('"', '\\"')
                outfile.write(f'        {{\n')
                outfile.write(f'            "id": "{cf["id"]}",\n')
                outfile.write(f'            "index": {idx},\n')
                outfile.write(f'            "description": "{display_escaped[:100]}",\n')
                outfile.write(f'            "var_name": "CONTINGENCY_{idx}"\n')
                outfile.write(f'        }},\n')
            
            outfile.write('    ]\n')
            outfile.write('}\n\n')
            
            # =========================================================
            # BASE CASE DATA
            # =========================================================
            outfile.write('# ============================================================================\n')
            outfile.write('# BASE CASE (No Contingency)\n')
            outfile.write('# ============================================================================\n\n')
            
            outfile.write('BASE_CASE = {\n')
            outfile.write('    "id": "BASE_CASE",\n')
            outfile.write('    "description": "Base Case - No Contingency",\n')
            outfile.write('    "data": {}\n')
            outfile.write('}\n\n')
            
            # =========================================================
            # EACH CONTINGENCY DATA
            # =========================================================
            for idx, cf in enumerate(self.contingency_files, 1):
                display = self.extract_display_info(cf.get('info', ''))
                display_escaped = display.replace('"', '\\"')
                
                outfile.write(f'\n# ============================================================================\n')
                outfile.write(f'# CONTINGENCY {idx}: {cf["id"]}\n')
                outfile.write(f'# {display_escaped}\n')
                outfile.write(f'# ============================================================================\n\n')
                
                # Write contingency info dictionary
                outfile.write(f'CONTINGENCY_{idx} = {{\n')
                outfile.write(f'    "id": "{cf["id"]}",\n')
                outfile.write(f'    "index": {idx},\n')
                outfile.write(f'    "description": "{display_escaped}",\n')
                outfile.write(f'    "file_prefix": "{cf["id"]}",\n')
                outfile.write(f'    "data": {{\n')
                
                # Extract and embed the PY data from contingency file
                py_file = cf.get('py', cf['csv'].replace('_ALL_DATA.csv', '_ALL_DATA.py'))
                if os.path.exists(py_file):
                    with open(py_file, 'r', encoding='utf-8') as infile:
                        content = infile.read()
                        
                        # Extract each data section
                        sections = ['BUS_DATA', 'GENERATOR_DATA', 'LINE_DATA', 'TRANSFORMER_DATA', 
                                    'CAPACITOR_DATA', 'REACTOR_DATA', 'SERIES_COMP_DATA', 'SERIES_REACTOR_DATA', 
                                    'SHUNT_DATA', 'SYSTEM_SUMMARY']
                        
                        for section in sections:
                            # Find the section content using regex
                            pattern = rf'{section}\s*=\s*\[(.*?)\];?\s*\n'
                            import re
                            match = re.search(pattern, content, re.DOTALL)
                            if match:
                                section_content = match.group(0)
                                # Remove trailing comma if exists
                                section_content = section_content.rstrip(',\n')
                                # Indent properly
                                indented = '\n        '.join(section_content.split('\n'))
                                outfile.write(f'        "{section}": {indented},\n')
                            else:
                                outfile.write(f'        "{section}": [],\n')
                
                outfile.write(f'    }}\n')
                outfile.write(f'}}\n\n')
            
            # =========================================================
            # HELPER FUNCTIONS
            # =========================================================
            outfile.write('\n# ============================================================================\n')
            outfile.write('# HELPER FUNCTIONS\n')
            outfile.write('# ============================================================================\n\n')
            
            outfile.write('def get_contingency_by_id(contingency_id):\n')
            outfile.write('    """Get contingency data by ID (e.g., "LINE_1", "GEN_2", "BUS_OUTAGE_11")"""\n')
            outfile.write('    for i in range(1, len(CONSOLIDATED_CONTINGENCIES["contingencies"]) + 1):\n')
            outfile.write('        if globals().get(f"CONTINGENCY_{i}", {}).get("id") == contingency_id:\n')
            outfile.write('            return globals().get(f"CONTINGENCY_{i}")\n')
            outfile.write('    return None\n\n')
            
            outfile.write('def get_contingency_by_index(index):\n')
            outfile.write('    """Get contingency data by index (1-based)"""\n')
            outfile.write('    return globals().get(f"CONTINGENCY_{index}", None)\n\n')
            
            outfile.write('def get_all_contingency_ids():\n')
            outfile.write('    """Get list of all contingency IDs"""\n')
            outfile.write('    return [c["id"] for c in CONSOLIDATED_CONTINGENCIES["contingencies"]]\n\n')
            
            outfile.write('def get_contingency_bus_data(contingency_id):\n')
            outfile.write('    """Get BUS_DATA for a specific contingency"""\n')
            outfile.write('    cont = get_contingency_by_id(contingency_id)\n')
            outfile.write('    return cont["data"]["BUS_DATA"] if cont else []\n\n')
            
            outfile.write('def get_contingency_line_data(contingency_id):\n')
            outfile.write('    """Get LINE_DATA for a specific contingency"""\n')
            outfile.write('    cont = get_contingency_by_id(contingency_id)\n')
            outfile.write('    return cont["data"]["LINE_DATA"] if cont else []\n\n')
            
            outfile.write('def get_contingency_generator_data(contingency_id):\n')
            outfile.write('    """Get GENERATOR_DATA for a specific contingency"""\n')
            outfile.write('    cont = get_contingency_by_id(contingency_id)\n')
            outfile.write('    return cont["data"]["GENERATOR_DATA"] if cont else []\n\n')
            
            outfile.write('def get_contingency_summary(contingency_id):\n')
            outfile.write('    """Get SYSTEM_SUMMARY for a specific contingency"""\n')
            outfile.write('    cont = get_contingency_by_id(contingency_id)\n')
            outfile.write('    return cont["data"].get("SYSTEM_SUMMARY", {}) if cont else {}\n\n')
            
            outfile.write('def list_all_contingencies():\n')
            outfile.write('    """Print all contingencies in a formatted table"""\n')
            outfile.write('    print("="*80)\n')
            outfile.write('    print("CONTINGENCY LIST")\n')
            outfile.write('    print("="*80)\n')
            outfile.write('    print("\\nIndex     ID                   Description")\n')
            outfile.write('    print("-"*80)\n')
            outfile.write('    for c in CONSOLIDATED_CONTINGENCIES["contingencies"]:\n')
            outfile.write('        print(f"{c[\\"index\\"]:<8} {c[\\"id\\"]:<20} {c[\\"description\\"][:50]}")\n')
            outfile.write('    print("="*80)\n\n')
            
            # =========================================================
            # CREATE CONTINGENCIES LIST FOR EASY ACCESS
            # =========================================================
            outfile.write('\n# ============================================================================\n')
            outfile.write('# CREATE CONTINGENCIES LIST FOR EASY ACCESS\n')
            outfile.write('# ============================================================================\n\n')
            outfile.write('CONTINGENCIES_LIST = []\n')
            for idx, cf in enumerate(self.contingency_files, 1):
                outfile.write(f'CONTINGENCIES_LIST.append(CONTINGENCY_{idx})\n')
            outfile.write('\n')
            
            # =========================================================
            # MAIN EXECUTION
            # =========================================================
            outfile.write('\n# ============================================================================\n')
            outfile.write('# MAIN EXECUTION\n')
            outfile.write('# ============================================================================\n\n')
            outfile.write('if __name__ == "__main__":\n')
            outfile.write('    print("="*60)\n')
            outfile.write('    print("CONSOLIDATED CONTINGENCY ANALYSIS")\n')
            outfile.write('    print("="*60)\n')
            outfile.write(f'    print(f"Case: {self.case_name}")\n')
            outfile.write(f'    print(f"Total Contingencies: {len(self.contingency_files)}")\n')
            outfile.write('    print("="*60)\n')
            outfile.write('    list_all_contingencies()\n')
            outfile.write('    print("\\n" + "="*60)\n')
            outfile.write('    print("Example usage:")\n')
            outfile.write('    print(\'  data = get_contingency_by_id("LINE_1")\')\n')
            outfile.write('    print(\'  buses = get_contingency_bus_data("LINE_1")\')\n')
            outfile.write('    print(\'  summary = get_contingency_summary("LINE_1")\')\n')
            outfile.write('    print(\'  lst = CONTINGENCIES_LIST\')\n')
            outfile.write('    print("="*60)\n')
        
        print(f"   Consolidated PY: {master_py}")
        return master_py
    
    
    # def consolidate_all(self):
    #     """Run all consolidation functions"""
    #     print("\n" + "="*80)
    #     print("📦 CONSOLIDATING REPORTS INTO MASTER FILES")
    #     print("="*80)
        
    #     self.scan_for_files()
        
    #     if not self.contingency_files:
    #         print("  ⚠️ No contingency files found to consolidate")
    #         return None
        
    #     csv_file = self.consolidate_csv()
    #     txt_file = self.consolidate_txt()
    #     py_file = self.consolidate_py()
        
    #     print("\n  ✅ Consolidation complete!")
    #     #return {'csv': csv_file, 'txt': txt_file}
    #     return {'csv': csv_file, 'txt': txt_file, 'py': py_file}
    def consolidate_all(self):
        """Run all consolidation functions (CSV, TXT, PY)"""
        print("\n" + "="*80)
        print(" CONSOLIDATING REPORTS INTO MASTER FILES")
        print("="*80)
        
        self.scan_for_files()
        
        if not self.contingency_files:
            print("   No contingency files found to consolidate")
            return None
        
        csv_file = self.consolidate_csv()
        txt_file = self.consolidate_txt()
        py_file = self.consolidate_py()
        
        print("\n   Consolidation complete!")
        return {'csv': csv_file, 'txt': txt_file, 'py': py_file}



# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def run_single_simulation(engine, full_data, samples, valid_count, output_folder, 
                          contingency_info, variation, n_samples, case_name, generated_files):
    """Run full report generation for a single contingency"""
    
    reporter = ReportWriter(engine, full_data, samples, variation)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = f"{contingency_info['id']}_{timestamp}"
    
    csv_path = os.path.join(output_folder, f"{prefix}_ALL_DATA.csv")
    py_all_path = os.path.join(output_folder, f"{prefix}_ALL_DATA.py")
    txt_path = os.path.join(output_folder, f"{prefix}_SUMMARY.txt")
    
    reporter.write_csv_all_data(csv_path)
    reporter.write_py_all_data(py_all_path)
    reporter.write_txt_summary(txt_path)
    
    generated_files.append({
        'csv': csv_path, 'py': py_all_path, 'txt': txt_path,
        'id': contingency_info['id'], 'info': None
    })
    
    # Save contingency info file
    info_file = os.path.join(output_folder, f"{prefix}_CONTINGENCY_INFO.txt")
    with open(info_file, 'w', encoding='utf-8') as f:
        f.write("="*80 + "\n")
        f.write("CONTINGENCY INFORMATION\n")
        f.write("="*80 + "\n")
        f.write(f"Contingency ID: {contingency_info['id']}\n")
        f.write(f"Type: {contingency_info['type']}\n")
        f.write(f"Element: {contingency_info['name']}\n")
        f.write(f"Description: {contingency_info['description']}\n")
        f.write(f"Display: {contingency_info['display']}\n")
        if contingency_info.get('details'):
            f.write(f"\nDetails:\n{contingency_info['details']}\n")
        f.write(f"\nSimulation Parameters:\n")
        f.write(f"  Variation: {variation*100:.0f}%\n")
        f.write(f"  Samples: {n_samples}\n")
        f.write(f"  Valid Samples: {valid_count}\n")
        f.write("="*80 + "\n")
    
    for gf in generated_files:
        if gf['id'] == contingency_info['id']:
            gf['info'] = info_file
            break


def print_menu(all_contingencies):
    """Print complete menu with numbers for ALL components"""
    
    print("\n" + "="*100)
    print("AVAILABLE CONTINGENCIES - ALL COMPONENTS")
    print("="*100)
    
    # Group by type
    lines = [c for c in all_contingencies if c['type'] == 'line']
    xfmrs = [c for c in all_contingencies if c['type'] == 'transformer']
    gens = [c for c in all_contingencies if c['type'] == 'generator']
    sync_motors = [c for c in all_contingencies if c['type'] == 'sync_motor']
    loads = [c for c in all_contingencies if c['type'] == 'load']
    caps = [c for c in all_contingencies if c['type'] == 'capacitor']
    reactors = [c for c in all_contingencies if c['type'] == 'reactor']
    series_comps = [c for c in all_contingencies if c['type'] == 'series_comp']
    series_reactors = [c for c in all_contingencies if c['type'] == 'series_reactor']
    shunts = [c for c in all_contingencies if c['type'] == 'shunt']
    bus_outages = [c for c in all_contingencies if c['type'] == 'bus_outage']
    bus_voltages = [c for c in all_contingencies if c['type'] == 'bus_voltage']
    
    idx = 1
    index_map = {}
    
    if lines:
        print(f"\n{'='*45}  LINES ({len(lines)}) {'='*45}")
        for c in lines:
            print(f"  [{idx:3d}] {c['display']}")
            c['menu_index'] = idx
            index_map[idx] = c
            idx += 1
    
    if xfmrs:
        print(f"\n{'='*43}  TRANSFORMERS ({len(xfmrs)}) {'='*43}")
        for c in xfmrs:
            print(f"  [{idx:3d}] {c['display']}")
            c['menu_index'] = idx
            index_map[idx] = c
            idx += 1
    
    if gens:
        print(f"\n{'='*43}  GENERATORS ({len(gens)}) {'='*44}")
        for c in gens:
            print(f"  [{idx:3d}] {c['display']}")
            c['menu_index'] = idx
            index_map[idx] = c
            idx += 1
            
    if sync_motors:
        print(f"\n{'='*38}  SYNCHRONOUS MOTORS ({len(sync_motors)}) {'='*39}")
        for c in sync_motors:
            print(f"  [{idx:3d}] {c['display']}")
            c['menu_index'] = idx
            index_map[idx] = c
            idx += 1
    
    if loads:
        print(f"\n{'='*45}  LOADS ({len(loads)}) {'='*46}")
        for c in loads:
            print(f"  [{idx:3d}] {c['display']}")
            c['menu_index'] = idx
            index_map[idx] = c
            idx += 1
    
    if caps:
        print(f"\n{'='*43}  CAPACITORS ({len(caps)}) {'='*44}")
        for c in caps:
            print(f"  [{idx:3d}] {c['display']}")
            c['menu_index'] = idx
            index_map[idx] = c
            idx += 1
    
    if reactors:
        print(f"\n{'='*43}  REACTORS ({len(reactors)}) {'='*44}")
        for c in reactors:
            print(f"  [{idx:3d}] {c['display']}")
            c['menu_index'] = idx
            index_map[idx] = c
            idx += 1
    
    if series_comps:
        print(f"\n{'='*40}  SERIES COMPENSATION ({len(series_comps)}) {'='*40}")
        for c in series_comps:
            print(f"  [{idx:3d}] {c['display']}")
            c['menu_index'] = idx
            index_map[idx] = c
            idx += 1
    
    if series_reactors:
        print(f"\n{'='*41}  SERIES REACTORS ({len(series_reactors)}) {'='*41}")
        for c in series_reactors:
            print(f"  [{idx:3d}] {c['display']}")
            c['menu_index'] = idx
            index_map[idx] = c
            idx += 1
    
    if shunts:
        print(f"\n{'='*43}  SHUNTS ({len(shunts)}) {'='*44}")
        for c in shunts:
            print(f"  [{idx:3d}] {c['display']}")
            c['menu_index'] = idx
            index_map[idx] = c
            idx += 1
    
    if bus_outages:
        print(f"\n{'='*43}  BUS OUTAGES ({len(bus_outages)}) {'='*45}")
        for c in bus_outages:
            print(f"  [{idx:3d}] {c['display']}")
            c['menu_index'] = idx
            index_map[idx] = c
            idx += 1
    
    if bus_voltages:
        print(f"\n{'='*41}  BUS VOLTAGE REDUCTION ({len(bus_voltages)}) {'='*41}")
        for c in bus_voltages:
            print(f"  [{idx:3d}] {c['display']}")
            c['menu_index'] = idx
            index_map[idx] = c
            idx += 1
    
    return index_map


# ============================================================================
# MAIN FUNCTION
# ============================================================================

def main():
    print("\n" + "="*80)
    print("BATCH CONTINGENCY ANALYSIS - INVERSE POWER FLOW")
    print("="*80)
    
    parser = argparse.ArgumentParser()
    parser.add_argument('-i', '--input', help='Input Python file path')
    parser.add_argument('-v', '--variation', type=float, default=10, help='Variation strength (percent)')
    #parser.add_argument('-n', '--samples', type=int, default=200, help='Samples per contingency')
    parser.add_argument('-n', '--samples', type=int, default=200, help='Samples per contingency')
    parser.add_argument('-e', '--engine', type=str, choices=['inverse', 'deven'], default='deven',
                        help='Engine: inverse (random sampling) or deven (custom DevEN solver, default)')
    parser.add_argument('-m', '--method', type=str, default='nr',
                        help='Solver method (only used with deven)')
    parser.add_argument('-t', '--tol', type=float, default=1e-8,
                        help='Solver convergence tolerance')
    parser.add_argument('--max-iter', type=int, default=10,
                        help='Solver max iterations')
    parser.add_argument('--ignore-q', action='store_true',
                        help='Ignore Q limits checking')
    
    
    args = parser.parse_args()
    
    if args.input:
        input_file = args.input
        variation = args.variation / 100.0
        n_samples = args.samples
    else:
        input_file = input("\nEnter input file path: ").strip().strip('"').strip("'")
        variation = float(input("Variation strength (10 = 10%) [default: 10]: ") or 10) / 100.0
        n_samples = int(input("Samples per contingency [default: 200]: ") or 200)
    
    if not os.path.isfile(input_file):
        print(f"\n File not found: {input_file}")
        return
    
    #batch = ContingencyBatch(input_file)
    batch = ContingencyBatch(input_file)
    batch.engine_choice = args.engine
    batch.method = args.method
    batch.tol = args.tol
    batch.max_iter = args.max_iter
    if not batch.load_system():
        return
    
    all_contingencies = batch.get_all_contingencies()
    index_map = print_menu(all_contingencies)
    
    print("\n" + "="*100)
    print("SELECTION OPTIONS")
    print("="*100)
    print("  [A] Select ALL contingencies")
    print("  [L] Select ALL LINES only")
    print("  [T] Select ALL TRANSFORMERS only")
    print("  [G] Select ALL GENERATORS only")
    print("  [M] Select ALL SYNCHRONOUS MOTORS only")
    print("  [D] Select ALL LOADS only")
    print("  [C] Select ALL CAPACITORS only")
    print("  [R] Select ALL REACTORS only")
    print("  [S] Select ALL SERIES COMPENSATION only")
    print("  [X] Select ALL SERIES REACTORS only")
    print("  [H] Select ALL SHUNTS only")
    print("  [O] Select ALL BUS OUTAGES only")
    print("  [V] Select ALL BUS VOLTAGE REDUCTIONS only")
    print("  [U] CUSTOM (enter numbers, e.g., 1,3,5,7)")
    print("  [0] Run BASE CASE only (no contingency)")
    print("="*100)
    
    choice = input("\nEnter your choice: ").strip().upper()
    
    selected_contingencies = []
    
    if choice == '0':
        selected_contingencies = []
        print("\n Running BASE CASE only")
    
    elif choice == 'A':
        selected_contingencies = all_contingencies
        print(f"\n Selected ALL {len(selected_contingencies)} contingencies")
    
    elif choice == 'L':
        selected_contingencies = [c for c in all_contingencies if c['type'] == 'line']
        print(f"\n Selected ALL LINES ({len(selected_contingencies)} contingencies)")
    
    elif choice == 'T':
        selected_contingencies = [c for c in all_contingencies if c['type'] == 'transformer']
        print(f"\n Selected ALL TRANSFORMERS ({len(selected_contingencies)} contingencies)")
    
    elif choice == 'G':
        selected_contingencies = [c for c in all_contingencies if c['type'] == 'generator']
        print(f"\n Selected ALL GENERATORS ({len(selected_contingencies)} contingencies)")
        
    elif choice == 'M':
        selected_contingencies = [c for c in all_contingencies if c['type'] == 'sync_motor']
        print(f"\n Selected ALL SYNCHRONOUS MOTORS ({len(selected_contingencies)} contingencies)")
    
    elif choice == 'D':
        selected_contingencies = [c for c in all_contingencies if c['type'] == 'load']
        print(f"\n Selected ALL LOADS ({len(selected_contingencies)} contingencies)")
    
    elif choice == 'C':
        selected_contingencies = [c for c in all_contingencies if c['type'] == 'capacitor']
        print(f"\n Selected ALL CAPACITORS ({len(selected_contingencies)} contingencies)")
    
    elif choice == 'R':
        selected_contingencies = [c for c in all_contingencies if c['type'] == 'reactor']
        print(f"\n Selected ALL REACTORS ({len(selected_contingencies)} contingencies)")
    
    elif choice == 'S':
        selected_contingencies = [c for c in all_contingencies if c['type'] == 'series_comp']
        print(f"\n Selected ALL SERIES COMPENSATION ({len(selected_contingencies)} contingencies)")
    
    elif choice == 'X':
        selected_contingencies = [c for c in all_contingencies if c['type'] == 'series_reactor']
        print(f"\n Selected ALL SERIES REACTORS ({len(selected_contingencies)} contingencies)")
    
    elif choice == 'H':
        selected_contingencies = [c for c in all_contingencies if c['type'] == 'shunt']
        print(f"\n Selected ALL SHUNTS ({len(selected_contingencies)} contingencies)")
    
    elif choice == 'O':
        selected_contingencies = [c for c in all_contingencies if c['type'] == 'bus_outage']
        print(f"\n Selected ALL BUS OUTAGES ({len(selected_contingencies)} contingencies)")
    
    elif choice == 'V':
        selected_contingencies = [c for c in all_contingencies if c['type'] == 'bus_voltage']
        print(f"\n Selected ALL BUS VOLTAGE REDUCTIONS ({len(selected_contingencies)} contingencies)")
    
    elif choice == 'U':
        print("\nEnter contingency numbers (comma separated, e.g., 1,3,5,7):")
        nums = input("Numbers: ").strip()
        for num in nums.split(','):
            num = num.strip()
            if num.isdigit():
                n = int(num)
                if n in index_map:
                    selected_contingencies.append(index_map[n])
                else:
                    print(f"   Invalid number: {n}")
        print(f"\n Selected {len(selected_contingencies)} contingencies")
    
    else:
        print("\n Invalid choice")
        return
    
    # Create output folder
    case_name = batch.case_name
    output_folder = os.path.join(os.path.dirname(os.path.abspath(input_file)), f"{case_name}_CONTINGENCY")
    os.makedirs(output_folder, exist_ok=True)
    
    batch.output_folder = output_folder
    generated_files = []
    
    print(f"\n Output folder: {output_folder}")
    print(f"  Variation: {variation*100:.0f}% | Samples per contingency: {n_samples}")
    
    # =========================================================
    # BASE CASE
    # =========================================================
    print(f"\n{'='*80}")
    print(f" RUNNING BASE CASE (No Contingency)")
    print(f"{'='*80}")
    
    batch.reset_to_base()
    bus_data_engine, branch_data_engine, full_data_engine = InputReader.convert_to_engine_format(batch.full_data)
    
    # engine = PowerFlowEngine(baseMVA=batch.baseMVA)
    # engine.initialize(bus_data_engine, branch_data_engine)
    # samples, valid_count = engine.run_batch(n_samples=n_samples, variation_strength=variation)
    if args.engine == 'deven':
        engine = PowerFlowEngine(baseMVA=batch.baseMVA)
        engine.initialize(bus_data_engine, branch_data_engine, full_data=full_data_engine,
                           solver_method=args.method, tol=args.tol, max_iter=args.max_iter)
    else:  # inverse
        engine = PowerFlowEngine(baseMVA=batch.baseMVA)
        engine.initialize(bus_data_engine, branch_data_engine)
    samples, valid_count = engine.run_batch(n_samples=n_samples, variation_strength=variation)


    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    reporter = ReportWriter(engine, full_data_engine, samples, variation)
    reporter.write_csv_all_data(os.path.join(output_folder, f"BASE_CASE_{timestamp}_ALL_DATA.csv"))
    reporter.write_py_all_data(os.path.join(output_folder, f"BASE_CASE_{timestamp}_ALL_DATA.py"))
    reporter.write_txt_summary(os.path.join(output_folder, f"BASE_CASE_{timestamp}_SUMMARY.txt"))
    
    # Save base case info
    with open(os.path.join(output_folder, f"BASE_CASE_{timestamp}_CONTINGENCY_INFO.txt"), 'w') as f:
        f.write("="*80 + "\n")
        f.write("BASE CASE - NO CONTINGENCY\n")
        f.write("="*80 + "\n")
        f.write(f"Description: Base Case - All elements in normal operation\n")
        f.write(f"Valid Samples: {valid_count}/{n_samples}\n")
        f.write("="*80 + "\n")
    
    print(f"   Base Case completed")
    
    # =========================================================
    # CONTINGENCIES
    # =========================================================
    for idx, contingency in enumerate(selected_contingencies, 1):
        print(f"\n{'='*80}")
        print(f" CONTINGENCY {idx}/{len(selected_contingencies)}: {contingency['display'][:70]}")
        print(f"{'='*80}")
        
        samples, valid_count, engine, full_data_after, info = batch.run_single_contingency(
            contingency, variation, n_samples
        )
        
        run_single_simulation(engine, full_data_after, samples, valid_count, 
                             output_folder, info, variation, n_samples, case_name, generated_files)
        
        print(f"   Contingency {idx}/{len(selected_contingencies)} completed")
    
    # =========================================================
    # CONSOLIDATE ALL REPORTS
    # =========================================================
    consolidator = ReportConsolidator(output_folder, case_name)
    consolidated = consolidator.consolidate_all()
    
    print("\n" + "="*80)
    print(" BATCH CONTINGENCY ANALYSIS COMPLETE!")
    print("="*80)
    print(f"\n All results saved in: {output_folder}")
    print(f"\n MASTER FILES (All contingencies in one file):")
    if consolidated:
        print(f"    CSV Master: {os.path.basename(consolidated['csv'])}")
        print(f"    TXT Master: {os.path.basename(consolidated['txt'])}")
        print(f"    PY Master:  {os.path.basename(consolidated['py'])}")
    print("\n Individual contingency files:")
    print(f"   • *_ALL_DATA.csv - Complete data for each contingency")
    print(f"   • *_SUMMARY.txt - Summary report for each contingency")
    print(f"   • *_CONTINGENCY_INFO.txt - Contingency details")
    print("="*80)


if __name__ == "__main__":
    main()
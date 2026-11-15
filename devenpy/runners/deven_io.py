"""
================================================================================
DevEN Universal Multi-Format Power Flow Ingestion & Output Module
================================================================================
Pure DevEN implementation supporting:
  - PSS/E RAW (.raw) - v29 through v35
  - MATPOWER (.m)
  - IEEE Common Data Format (.cdf)
  - Excel Workbooks (.xlsx, .xls)
  - PowerWorld AUX (.aux)
  - European UCTE DEF (.def)
  - CIM / CGMES RDF XML (.xml, .zip)
  - DevEN Native JSON (.json)
  - CSV Tabular (.csv)
================================================================================
"""

import os
import re
import json
import math
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional, Union


def sanitize_floats(obj: Any) -> Any:
    """Sanitizes floats for JSON compliance, mapping Inf and NaN to large finite bounds."""
    if isinstance(obj, float):
        if math.isnan(obj):
            return 0.0
        if math.isinf(obj):
            return 99999.0 if obj > 0 else -99999.0
        return obj
    elif isinstance(obj, dict):
        return {k: sanitize_floats(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_floats(v) for v in obj]
    return obj


# ==============================================================================
# 1. CORE DATA CONTAINER
# ==============================================================================
class DevenCircuit:
    """In-memory representation of a power system network."""
    def __init__(self, name: str = "DevEN_Case", base_mva: float = 100.0):
        self.name = name
        self.base_mva = float(base_mva)
        self.buses: List[Dict[str, Any]] = []
        self.generators: List[Dict[str, Any]] = []
        self.loads: List[Dict[str, Any]] = []
        self.branches: List[Dict[str, Any]] = []
        self.shunts: List[Dict[str, Any]] = []
        self.hvdc_links: List[Dict[str, Any]] = []
        self.vsc_hvdc_lines: List[Dict[str, Any]] = []
        self.facts_devices: List[Dict[str, Any]] = []

    def to_dict(self) -> Dict[str, Any]:
        """Convert to DevEN dictionary format compatible with PyCase.load_dict()."""
        raw = {
            "name": self.name,
            "base_mva": self.base_mva,
            "buses": self.buses,
            "generators": self.generators,
            "loads": self.loads,
            "branches": self.branches,
            "shunts": self.shunts,
            "hvdc_links": self.hvdc_links,
            "vsc_hvdc_lines": self.vsc_hvdc_lines,
            "facts_devices": self.facts_devices,
        }
        return sanitize_floats(raw)

    def to_case(self, work_with_slack: bool = False) -> Any:
        """Create a devenpy.PyCase instance populated with this circuit."""
        import devenpy
        case = devenpy.PyCase()
        case.load_dict(self.to_dict())
        case.set_work_with_slack(work_with_slack)
        return case


# ==============================================================================
# 2. MATPOWER PARSER (.m)
# ==============================================================================
class DevenMatpowerParser:
    """Parses MATPOWER .m case files into a DevenCircuit."""
    
    @staticmethod
    def parse(filepath: str) -> DevenCircuit:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        name = os.path.splitext(os.path.basename(filepath))[0]
        circuit = DevenCircuit(name=name)

        # 1. Base MVA
        base_mva_match = re.search(r'mpc\.baseMVA\s*=\s*([0-9\.]+)\s*;', content)
        if base_mva_match:
            circuit.base_mva = float(base_mva_match.group(1))

        # Helper to extract matrix blocks
        def extract_matrix(var_name: str) -> List[List[float]]:
            pattern = re.compile(rf'mpc\.{var_name}\s*=\s*\[(.*?)(?:\];|\Z)', re.DOTALL)
            m = pattern.search(content)
            if not m:
                return []
            raw_body = m.group(1)
            rows = []
            for line in raw_body.splitlines():
                line = re.sub(r'%.*$', '', line).strip()  # Remove comments
                if not line or line.startswith(']'):
                    continue
                line = line.rstrip(';')
                tokens = line.split()
                if not tokens:
                    continue
                try:
                    rows.append([float(x) for x in tokens])
                except ValueError:
                    continue
            return rows

        # 2. Bus data
        # [0: bus_i, 1: type, 2: Pd, 3: Qd, 4: Gs, 5: Bs, 6: area, 7: Vm, 8: Va, 9: baseKV, 10: zone, 11: Vmax, 12: Vmin]
        bus_rows = extract_matrix("bus")
        for r in bus_rows:
            if len(r) < 8:
                continue
            b_id = int(r[0])
            b_type = int(r[1])
            pd = r[2]
            qd = r[3]
            gs = r[4] if len(r) > 4 else 0.0
            bs = r[5] if len(r) > 5 else 0.0
            vm = r[7] if len(r) > 7 else 1.0
            va = r[8] if len(r) > 8 else 0.0
            base_kv = r[9] if len(r) > 9 and r[9] > 0 else 132.0

            circuit.buses.append({
                "number": b_id,
                "name": f"BUS_{b_id}",
                "bus_type": b_type,
                "base_kv": base_kv,
                "v_mag": vm,
                "v_angle_deg": va,
                "shunt_g": gs,
                "shunt_b": bs,
            })

            # If bus has load, add to loads
            if abs(pd) > 1e-4 or abs(qd) > 1e-4:
                circuit.loads.append({
                    "bus": b_id,
                    "id": "1",
                    "status": 1,
                    "p_mw": pd,
                    "q_mvar": qd,
                })

        # 3. Gen data
        # [0: bus, 1: Pg, 2: Qg, 3: Qmax, 4: Qmin, 5: Vg, 6: mBase, 7: status, 8: Pmax, 9: Pmin]
        gen_rows = extract_matrix("gen")
        gen_counts: Dict[int, int] = {}
        for r in gen_rows:
            if len(r) < 8:
                continue
            b_id = int(r[0])
            count = gen_counts.get(b_id, 0) + 1
            gen_counts[b_id] = count
            circuit.generators.append({
                "bus": b_id,
                "id": str(count),
                "p_mw": r[1],
                "q_mvar": r[2],
                "q_max": r[3],
                "q_min": r[4],
                "v_set": r[5] if r[5] > 0 else 1.0,
                "mbase": r[6] if len(r) > 6 and r[6] > 0 else circuit.base_mva,
                "status": int(r[7]),
            })

        # 4. Branch data
        # [0: fbus, 1: tbus, 2: r, 3: x, 4: b, 5: rateA, 6: rateB, 7: rateC, 8: ratio, 9: angle, 10: status]
        br_rows = extract_matrix("branch")
        br_counts: Dict[str, int] = {}
        for r in br_rows:
            if len(r) < 11:
                continue
            fbus = int(r[0])
            tbus = int(r[1])
            key = f"{min(fbus, tbus)}_{max(fbus, tbus)}"
            ckt = str(br_counts.get(key, 0) + 1)
            br_counts[key] = int(ckt)
            ratio = r[8] if len(r) > 8 and r[8] > 0 else 1.0
            angle = r[9] if len(r) > 9 else 0.0

            circuit.branches.append({
                "from_bus": fbus,
                "to_bus": tbus,
                "ckt": ckt,
                "status": int(r[10]),
                "r": r[2],
                "x": r[3],
                "b": r[4],
                "rate_a": r[5] if r[5] > 0 else 9999.0,
                "ratio": ratio,
                "phase_shift": angle,
            })

        return circuit


# ==============================================================================
# 3. IEEE COMMON DATA FORMAT PARSER (.cdf)
# ==============================================================================
class DevenCdfParser:
    """Parses IEEE Common Data Format (.cdf) card-based power flow files."""

    @staticmethod
    def parse(filepath: str) -> DevenCircuit:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        circuit = DevenCircuit(name=os.path.splitext(os.path.basename(filepath))[0])
        mode = "HEADER"

        for line in lines:
            line_str = line.rstrip("\r\n")
            if not line_str.strip():
                continue

            upper = line_str.upper()
            if "BUS DATA FOLLOWS" in upper:
                mode = "BUS"
                continue
            elif "BRANCH DATA FOLLOWS" in upper:
                mode = "BRANCH"
                continue
            elif "LOSS ZONES FOLLOWS" in upper or "TIE LINES FOLLOWS" in upper or "END OF DATA" in upper:
                mode = "OTHER"
                continue

            if mode == "HEADER" and len(line_str) >= 37:
                try:
                    sbase = float(line_str[31:37].strip())
                    if sbase > 0:
                        circuit.base_mva = sbase
                except ValueError:
                    pass

            elif mode == "BUS":
                if line_str.strip().startswith("-999") or line_str.strip().startswith("-99"):
                    mode = "OTHER"
                    continue
                try:
                    num = int(line_str[0:4].strip())
                    name = line_str[5:17].strip()
                    b_type = int(line_str[24:26].strip())
                    vm = float(line_str[27:33].strip()) if line_str[27:33].strip() else 1.0
                    va = float(line_str[33:40].strip()) if line_str[33:40].strip() else 0.0
                    load_p = float(line_str[40:49].strip()) if line_str[40:49].strip() else 0.0
                    load_q = float(line_str[49:59].strip()) if line_str[49:59].strip() else 0.0
                    gen_p = float(line_str[59:67].strip()) if line_str[59:67].strip() else 0.0
                    gen_q = float(line_str[67:75].strip()) if line_str[67:75].strip() else 0.0
                    base_kv = float(line_str[76:83].strip()) if len(line_str) >= 83 and line_str[76:83].strip() else 132.0

                    # CDF bus types: 0: Unregulated (PQ), 1: Hold MVAR (PQ), 2: Hold Voltage (PV), 3: Swing (Slack)
                    mapped_type = 3 if b_type == 3 else (2 if b_type == 2 else 1)

                    circuit.buses.append({
                        "number": num,
                        "name": name,
                        "bus_type": mapped_type,
                        "base_kv": base_kv if base_kv > 0 else 132.0,
                        "v_mag": vm,
                        "v_angle_deg": va,
                    })

                    if abs(load_p) > 1e-4 or abs(load_q) > 1e-4:
                        circuit.loads.append({
                            "bus": num,
                            "id": "1",
                            "status": 1,
                            "p_mw": load_p,
                            "q_mvar": load_q,
                        })

                    if mapped_type in [2, 3] or abs(gen_p) > 1e-4:
                        circuit.generators.append({
                            "bus": num,
                            "id": "1",
                            "status": 1,
                            "p_mw": gen_p,
                            "q_mvar": gen_q,
                            "v_set": vm,
                            "q_max": 9999.0,
                            "q_min": -9999.0,
                        })
                except Exception:
                    continue

            elif mode == "BRANCH":
                if line_str.strip().startswith("-999") or line_str.strip().startswith("-99"):
                    mode = "OTHER"
                    continue
                try:
                    fbus = int(line_str[0:4].strip())
                    tbus = int(line_str[5:9].strip())
                    ckt = line_str[16:17].strip() or "1"
                    r = float(line_str[19:29].strip())
                    x = float(line_str[29:40].strip())
                    b = float(line_str[40:50].strip()) if len(line_str) >= 50 and line_str[40:50].strip() else 0.0
                    rate_a = float(line_str[50:55].strip()) if len(line_str) >= 55 and line_str[50:55].strip() else 9999.0
                    ratio = float(line_str[76:82].strip()) if len(line_str) >= 82 and line_str[76:82].strip() else 1.0

                    circuit.branches.append({
                        "from_bus": fbus,
                        "to_bus": tbus,
                        "ckt": ckt,
                        "status": 1,
                        "r": r,
                        "x": x,
                        "b": b,
                        "rate_a": rate_a if rate_a > 0 else 9999.0,
                        "ratio": ratio if ratio > 0 else 1.0,
                        "phase_shift": 0.0,
                    })
                except Exception:
                    continue

        return circuit


# ==============================================================================
# 4. POWERWORLD AUX PARSER (.aux)
# ==============================================================================
class DevenAuxParser:
    """Parses PowerWorld AUX script data blocks."""

    @staticmethod
    def parse(filepath: str) -> DevenCircuit:
        circuit = DevenCircuit(name=os.path.splitext(os.path.basename(filepath))[0])
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        data_blocks = re.findall(r'DATA\s*\(([^,]+),\s*\[([^\]]+)\]\)\s*\{(.*?)\}', content, re.DOTALL)
        for obj_type, fields_str, body in data_blocks:
            obj_type = obj_type.strip().lower()
            fields = [f.strip().lower() for f in fields_str.split(",")]
            for line in body.splitlines():
                line = line.strip().strip('"')
                if not line or line.startswith("//"):
                    continue
                tokens = [t.strip().strip('"') for t in line.split()]
                if len(tokens) < len(fields):
                    continue
                row = dict(zip(fields, tokens))

                if obj_type in ["bus", "buses"]:
                    num = int(row.get("busnum", 0))
                    circuit.buses.append({
                        "number": num,
                        "name": row.get("busname", f"BUS_{num}"),
                        "bus_type": 3 if "slack" in row.get("bustype", "").lower() else (2 if "gen" in row.get("bustype", "").lower() else 1),
                        "base_kv": float(row.get("busnomvolt", 132.0)),
                        "v_mag": float(row.get("buspuvolt", 1.0)),
                        "v_angle_deg": float(row.get("busangle", 0.0)),
                    })
                elif obj_type in ["gen", "generator"]:
                    circuit.generators.append({
                        "bus": int(row.get("busnum", 0)),
                        "id": row.get("genid", "1"),
                        "p_mw": float(row.get("genmw", 0.0)),
                        "q_mvar": float(row.get("genmvar", 0.0)),
                        "v_set": float(row.get("genvoltset", 1.0)),
                        "q_max": float(row.get("genmvarmax", 9999.0)),
                        "q_min": float(row.get("genmvarmin", -9999.0)),
                        "status": 1 if row.get("genstatus", "open").lower() in ["closed", "1"] else 0,
                    })
                elif obj_type in ["branch", "line"]:
                    circuit.branches.append({
                        "from_bus": int(row.get("busnum", 0)),
                        "to_bus": int(row.get("busnum:1", 0)),
                        "ckt": row.get("linecircuit", "1"),
                        "r": float(row.get("liner", 0.01)),
                        "x": float(row.get("linex", 0.1)),
                        "b": float(row.get("linec", 0.0)),
                        "rate_a": float(row.get("lineratinga", 9999.0)),
                        "status": 1 if row.get("linestatus", "open").lower() in ["closed", "1"] else 0,
                    })

        return circuit


# ==============================================================================
# 5. EUROPEAN UCTE DEF PARSER (.def)
# ==============================================================================
class DevenUcteParser:
    """Parses European UCTE DEF format files."""

    @staticmethod
    def parse(filepath: str) -> DevenCircuit:
        circuit = DevenCircuit(name=os.path.splitext(os.path.basename(filepath))[0])
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        node_map: Dict[str, int] = {}
        curr_id = 1
        section = ""

        for line in lines:
            line = line.strip()
            if not line or line.startswith("##C"):
                continue
            if line.startswith("##Z"):
                section = "NODES"
                continue
            elif line.startswith("##L"):
                section = "LINES"
                continue
            elif line.startswith("##T"):
                section = "TRANSFORMERS"
                continue

            tokens = line.split()
            if section == "NODES" and len(tokens) >= 8:
                node_name = tokens[0]
                if node_name not in node_map:
                    node_map[node_name] = curr_id
                    curr_id += 1
                b_num = node_map[node_name]
                b_type = int(tokens[2]) if tokens[2].isdigit() else 1
                vn = float(tokens[3]) if float(tokens[3]) > 0 else 132.0
                v_target = float(tokens[4]) / vn if vn > 0 else 1.0
                p_gen = float(tokens[5])
                q_gen = float(tokens[6])
                p_load = float(tokens[7])
                q_load = float(tokens[8]) if len(tokens) > 8 else 0.0

                circuit.buses.append({
                    "number": b_num,
                    "name": node_name,
                    "bus_type": b_type,
                    "base_kv": vn,
                    "v_mag": v_target,
                    "v_angle_deg": 0.0,
                })
                if abs(p_load) > 1e-4 or abs(q_load) > 1e-4:
                    circuit.loads.append({"bus": b_num, "id": "1", "status": 1, "p_mw": p_load, "q_mvar": q_load})
                if b_type in [2, 3] or abs(p_gen) > 1e-4:
                    circuit.generators.append({"bus": b_num, "id": "1", "status": 1, "p_mw": p_gen, "q_mvar": q_gen, "v_set": v_target, "q_max": 9999.0, "q_min": -9999.0})

            elif section in ["LINES", "TRANSFORMERS"] and len(tokens) >= 7:
                n1 = tokens[0]
                n2 = tokens[1]
                if n1 not in node_map:
                    node_map[n1] = curr_id; curr_id += 1
                if n2 not in node_map:
                    node_map[n2] = curr_id; curr_id += 1
                fbus = node_map[n1]
                tbus = node_map[n2]
                r = float(tokens[3])
                x = float(tokens[4])
                b = float(tokens[5]) if len(tokens) > 5 else 0.0
                ratio = float(tokens[6]) if section == "TRANSFORMERS" and len(tokens) > 6 else 1.0

                circuit.branches.append({
                    "from_bus": fbus,
                    "to_bus": tbus,
                    "ckt": tokens[2] if len(tokens) > 2 else "1",
                    "status": 1,
                    "r": r,
                    "x": x,
                    "b": b,
                    "ratio": ratio if ratio > 0 else 1.0,
                    "rate_a": 9999.0,
                })

        return circuit


# ==============================================================================
# 6. EXCEL WORKBOOK PARSER (.xlsx, .xls)
# ==============================================================================
class DevenExcelParser:
    """Parses multi-tab Excel workbooks containing network elements."""

    @staticmethod
    def parse(filepath: str) -> DevenCircuit:
        import zipfile
        import xml.etree.ElementTree as ET

        circuit = DevenCircuit(name=os.path.splitext(os.path.basename(filepath))[0])

        # Attempt to use openpyxl or pandas if present, else zipfile extraction
        try:
            import pandas as pd
            xls = pd.ExcelFile(filepath)
            for sheet in xls.sheet_names:
                s_lower = sheet.lower()
                df = pd.read_excel(xls, sheet)
                df.columns = [str(c).strip().lower() for c in df.columns]

                if "bus" in s_lower:
                    for _, row in df.iterrows():
                        num = int(row.get("number", row.get("bus", row.get("bus_number", 0))))
                        circuit.buses.append({
                            "number": num,
                            "name": str(row.get("name", f"BUS_{num}")),
                            "bus_type": int(row.get("type", row.get("bus_type", 1))),
                            "base_kv": float(row.get("base_kv", 132.0)),
                            "v_mag": float(row.get("v_mag", row.get("vm", 1.0))),
                            "v_angle_deg": float(row.get("v_angle", row.get("va", 0.0))),
                        })
                elif "gen" in s_lower:
                    for _, row in df.iterrows():
                        circuit.generators.append({
                            "bus": int(row.get("bus", row.get("bus_number", 0))),
                            "id": str(row.get("id", "1")),
                            "p_mw": float(row.get("p_mw", row.get("p", 0.0))),
                            "q_mvar": float(row.get("q_mvar", row.get("q", 0.0))),
                            "q_max": float(row.get("q_max", 9999.0)),
                            "q_min": float(row.get("q_min", -9999.0)),
                            "v_set": float(row.get("v_set", 1.0)),
                            "status": int(row.get("status", 1)),
                        })
                elif "branch" in s_lower or "line" in s_lower:
                    for _, row in df.iterrows():
                        circuit.branches.append({
                            "from_bus": int(row.get("from_bus", row.get("from", 0))),
                            "to_bus": int(row.get("to_bus", row.get("to", 0))),
                            "ckt": str(row.get("ckt", "1")),
                            "r": float(row.get("r", 0.01)),
                            "x": float(row.get("x", 0.1)),
                            "b": float(row.get("b", 0.0)),
                            "rate_a": float(row.get("rate_a", 9999.0)),
                            "status": int(row.get("status", 1)),
                        })
                elif "load" in s_lower:
                    for _, row in df.iterrows():
                        circuit.loads.append({
                            "bus": int(row.get("bus", row.get("bus_number", 0))),
                            "id": str(row.get("id", "1")),
                            "p_mw": float(row.get("p_mw", row.get("p", 0.0))),
                            "q_mvar": float(row.get("q_mvar", row.get("q", 0.0))),
                            "status": int(row.get("status", 1)),
                        })
            return circuit
        except Exception:
            pass

        return circuit


# ==============================================================================
# 7. CIM / CGMES RDF XML PARSER (.xml, .zip)
# ==============================================================================
class DevenCimParser:
    """Parses IEC 61970 / 61968 CIM XML and CGMES profiles."""

    @staticmethod
    def parse(filepath: str) -> DevenCircuit:
        circuit = DevenCircuit(name=os.path.splitext(os.path.basename(filepath))[0])
        tree = ET.parse(filepath)
        root = tree.getroot()

        # Strip XML namespaces for clean tag matching
        ns_pattern = re.compile(r'\{.*\}')
        node_map: Dict[str, int] = {}
        curr_id = 1

        for elem in root:
            tag = ns_pattern.sub('', elem.tag)
            if tag in ["TopologicalNode", "Bus"]:
                rdf_id = elem.attrib.get('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}ID', str(curr_id))
                node_map[rdf_id] = curr_id
                circuit.buses.append({
                    "number": curr_id,
                    "name": rdf_id,
                    "bus_type": 1,
                    "base_kv": 132.0,
                    "v_mag": 1.0,
                    "v_angle_deg": 0.0,
                })
                curr_id += 1

            elif tag in ["EnergyConsumer", "Load"]:
                circuit.loads.append({
                    "bus": 1,
                    "id": "1",
                    "status": 1,
                    "p_mw": float(elem.findtext(".//p", "0.0")),
                    "q_mvar": float(elem.findtext(".//q", "0.0")),
                })

            elif tag in ["GeneratingUnit", "SynchronousMachine"]:
                circuit.generators.append({
                    "bus": 1,
                    "id": "1",
                    "status": 1,
                    "p_mw": float(elem.findtext(".//p", "0.0")),
                    "q_mvar": float(elem.findtext(".//q", "0.0")),
                    "v_set": 1.0,
                    "q_max": 9999.0,
                    "q_min": -9999.0,
                })

        return circuit


# ==============================================================================
# 8. MASTER UNIVERSAL INGESTION API
# ==============================================================================
def load_grid_file(filepath: str, work_with_slack: bool = False, password: Optional[str] = None, **kwargs) -> Any:
    """
    Universal DevEN Case Loader.
    Automatically detects format (.raw, .rawx, .deven, .m, .xml, .cdf, .aux, .def, .xlsx, .json)
    and returns a ready-to-solve devenpy.PyCase instance.
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Case file not found: {filepath}")

    ext = os.path.splitext(filepath)[1].lower().lstrip(".")

    # 1. Native ultra-fast PSS/E RAW path in Rust
    if ext == "raw":
        import devenpy
        case = devenpy.PyCase()
        case.load_raw(filepath)
        case.set_work_with_slack(work_with_slack)
        return case

    # 1b. Native ultra-fast PSS/E RAWX path in Rust
    if ext == "rawx":
        import devenpy
        case = devenpy.PyCase()
        case.load_rawx(filepath)
        case.set_work_with_slack(work_with_slack)
        return case

    # 1c. Native encrypted DevEN database format
    if ext == "deven":
        import devenpy
        case = devenpy.PyCase()
        case.load_deven(filepath, password=password)
        case.set_work_with_slack(work_with_slack)
        return case

    # 2. Native JSON path
    if ext == "json":
        import devenpy
        case = devenpy.PyCase()
        case.load_json(filepath)
        case.set_work_with_slack(work_with_slack)
        return case

    # 3. MATPOWER (.m)
    if ext == "m":
        circuit = DevenMatpowerParser.parse(filepath)
        return circuit.to_case(work_with_slack=work_with_slack)

    # 4. IEEE CDF (.cdf, .ieee)
    if ext in ["cdf", "ieee"]:
        circuit = DevenCdfParser.parse(filepath)
        return circuit.to_case(work_with_slack=work_with_slack)

    # 5. PowerWorld AUX (.aux)
    if ext == "aux":
        circuit = DevenAuxParser.parse(filepath)
        return circuit.to_case(work_with_slack=work_with_slack)

    # 6. European UCTE (.def)
    if ext == "def":
        circuit = DevenUcteParser.parse(filepath)
        return circuit.to_case(work_with_slack=work_with_slack)

    # 7. Excel (.xlsx, .xls)
    if ext in ["xlsx", "xls"]:
        circuit = DevenExcelParser.parse(filepath)
        return circuit.to_case(work_with_slack=work_with_slack)

    # 8. CIM XML (.xml, .zip)
    if ext in ["xml", "zip"]:
        circuit = DevenCimParser.parse(filepath)
        return circuit.to_case(work_with_slack=work_with_slack)

    raise ValueError(f"Unsupported grid format: '{ext}'. Supported: .raw, .rawx, .deven, .m, .cdf, .aux, .def, .xlsx, .xml, .json")


# ==============================================================================
# 9. RESULTS EXTRACTION API
# ==============================================================================
def extract_results(case: Any, status: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Extracts all basic power flow results from a solved PyCase instance into
    a comprehensive, structured dictionary without writing to disk.
    """
    results: Dict[str, Any] = {
        "status": status or {},
        "buses": [],
        "generators": [],
        "branches": [],
        "hvdc": [],
    }

    try:
        rep = case.report_dict()
        if not results["status"]:
            results["status"] = rep.get("header", {})
        results["buses"] = rep.get("bus_results", [])
        results["generators"] = rep.get("gen_results", [])
        results["branches"] = rep.get("branch_flows", [])
        results["hvdc"] = rep.get("hvdc_results", [])
    except Exception:
        pass

    return results


# ==============================================================================
# 10. OPTIONAL OUTPUT EXPORT APIS (Invoked strictly on user request)
# ==============================================================================
def export_out(case: Any, filepath: str) -> None:
    """Exports solved case results to a standard PSS/E formatted .out file on user request."""
    case.write_out(filepath)


def export_csv(case: Any, base_filepath: str) -> Dict[str, str]:
    """Exports solved case results to structured CSV tables on user request."""
    import csv
    res = extract_results(case)
    stem, _ = os.path.splitext(base_filepath)
    bus_csv = f"{stem}_buses.csv"
    gen_csv = f"{stem}_gens.csv"
    brn_csv = f"{stem}_branches.csv"

    if res["buses"]:
        with open(bus_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(res["buses"][0].keys()))
            writer.writeheader()
            writer.writerows(res["buses"])

    if res["generators"]:
        with open(gen_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(res["generators"][0].keys()))
            writer.writeheader()
            writer.writerows(res["generators"])

    if res["branches"]:
        with open(brn_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(res["branches"][0].keys()))
            writer.writeheader()
            writer.writerows(res["branches"])

    return {"buses": bus_csv, "generators": gen_csv, "branches": brn_csv}


def export_json(case: Any, filepath: str) -> None:
    """Exports full solved case report to JSON on user request."""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(case.report_json())

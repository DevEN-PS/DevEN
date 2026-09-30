"""
DevEN Pure Python Data Model for Power Grid Networks.
Zero GUI/Tkinter dependencies. 100% standard Python primitives (dict, list, dataclass, float, int, str).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
import json


@dataclass
class PowerGridData:
    """
    Represents a complete power system network case.
    All elements use integer IDs mapped to dictionaries of parameters.

    Supported input file formats:
        - .py   — Python-based network database (native format)
        - .sql  — SQLite database export
        - .raw  — Raw bus/branch data format (PSS/E compatible)
        - .dgs  — DIgSILENT Gateway Script export format
        - .dat  — Fixed-column tabular network data format

    Default solver: deven_nr | Tolerance: 1e-5 | Max iterations: 30
    """
    project_name: str = "Untitled_Project"
    project_id: str = "1"
    base_mva: float = 100.0
    description: str = ""

    buses: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    generators: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    loads: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    lines: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    transformers: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    three_winding_transformers: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    capacitors: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    reactors: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    series_comps: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    series_reactors: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    shunts: Dict[int, Dict[str, Any]] = field(default_factory=dict)

    fault_cases: List[Any] = field(default_factory=list)
    line_voltage_factors: List[Any] = field(default_factory=list)
    global_factors: Dict[str, Any] = field(default_factory=dict)
    map_settings: Dict[str, Any] = field(default_factory=dict)
    solver_config: Dict[str, Any] = field(default_factory=lambda: {"engine": "deven_nr", "tol": 1e-5, "max_iter": 30})
    sld_json: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_counts(self) -> Dict[str, int]:
        """Returns element counts summary."""
        return {
            "buses": len(self.buses),
            "generators": len(self.generators),
            "loads": len(self.loads),
            "lines": len(self.lines),
            "transformers": len(self.transformers),
            "three_winding_transformers": len(self.three_winding_transformers),
            "capacitors": len(self.capacitors),
            "reactors": len(self.reactors),
            "series_comps": len(self.series_comps),
            "series_reactors": len(self.series_reactors),
            "shunts": len(self.shunts),
            "fault_cases": len(self.fault_cases)
        }

    def summary(self) -> str:
        """Returns a human-readable formatted summary string."""
        counts = self.get_counts()
        total_p_gen = sum(float(g.get("P_out", 0.0)) for g in self.generators.values() if int(g.get("status", 1)) == 1)
        total_q_gen = sum(float(g.get("Q_out", 0.0)) for g in self.generators.values() if int(g.get("status", 1)) == 1)
        total_p_load = sum(float(l.get("P_demand", 0.0)) for l in self.loads.values())
        total_q_load = sum(float(l.get("Q_demand", 0.0)) for l in self.loads.values())

        lines = [
            f"⚡ Power Grid Model: {self.project_name} (ID: {self.project_id})",
            f"   Base MVA: {self.base_mva:.1f} MVA | Description: {self.description or 'N/A'}",
            f"   Buses: {counts['buses']} | Generators: {counts['generators']} | Loads: {counts['loads']}",
            f"   Lines: {counts['lines']} | 2W Xfmrs: {counts['transformers']} | 3W Xfmrs: {counts['three_winding_transformers']}",
            f"   Capacitors: {counts['capacitors']} | Reactors: {counts['reactors']} | Shunts: {counts['shunts']}",
            f"   Total Gen: {total_p_gen:.2f} MW / {total_q_gen:.2f} MVAr",
            f"   Total Load: {total_p_load:.2f} MW / {total_q_load:.2f} MVAr"
        ]
        return "\n".join(lines)

    def validate(self) -> List[str]:
        """Validates network topology and parameters, returning any errors or warnings."""
        issues = []
        if not self.buses:
            issues.append("Network contains 0 buses.")
            return issues

        # Check for swing/slack bus
        slack_buses = [b_id for b_id, b in self.buses.items() if int(b.get("type", 3)) == 1]
        if not slack_buses:
            issues.append("Warning: No Slack/Swing Bus (type 1) defined in network.")

        # Check branch endpoints
        bus_ids = set(self.buses.keys())
        for ln_id, ln in self.lines.items():
            f_b = int(ln.get("from_bus", 0))
            t_b = int(ln.get("to_bus", 0))
            if f_b not in bus_ids:
                issues.append(f"Line {ln_id} references non-existent From Bus: {f_b}")
            if t_b not in bus_ids:
                issues.append(f"Line {ln_id} references non-existent To Bus: {t_b}")

        for x_id, xf in self.transformers.items():
            f_b = int(xf.get("from_bus", 0))
            t_b = int(xf.get("to_bus", 0))
            if f_b not in bus_ids:
                issues.append(f"Transformer {x_id} references non-existent From Bus: {f_b}")
            if t_b not in bus_ids:
                issues.append(f"Transformer {x_id} references non-existent To Bus: {t_b}")

        return issues

    def to_dict(self) -> Dict[str, Any]:
        """Serializes model into a standard Python dictionary."""
        return {
            "project_name": self.project_name,
            "project_id": self.project_id,
            "base_mva": self.base_mva,
            "description": self.description,
            "buses": self.buses,
            "generators": self.generators,
            "loads": self.loads,
            "lines": self.lines,
            "transformers": self.transformers,
            "three_winding_transformers": self.three_winding_transformers,
            "capacitors": self.capacitors,
            "reactors": self.reactors,
            "series_comps": self.series_comps,
            "series_reactors": self.series_reactors,
            "shunts": self.shunts,
            "fault_cases": self.fault_cases,
            "line_voltage_factors": self.line_voltage_factors,
            "global_factors": self.global_factors,
            "map_settings": self.map_settings,
            "solver_config": self.solver_config,
            "sld_json": self.sld_json,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PowerGridData":
        """Instantiates a PowerGridData model from a standard dictionary."""
        # Normalize list-format data if needed
        buses = cls._normalize_element_dict(data.get("buses", data.get("bus_data", {})))
        generators = cls._normalize_element_dict(data.get("generators", data.get("generator_data", {})))
        loads = cls._normalize_element_dict(data.get("loads", data.get("load_data", {})))
        lines = cls._normalize_element_dict(data.get("lines", data.get("line_data", {})))
        xfmrs = cls._normalize_element_dict(data.get("transformers", data.get("transformer_data", {})))
        tw_xfmrs = cls._normalize_element_dict(data.get("three_winding_transformers", data.get("three_w_xfmr_data", {})))
        caps = cls._normalize_element_dict(data.get("capacitors", data.get("capacitor_data", {})))
        reactors = cls._normalize_element_dict(data.get("reactors", data.get("reactor_data", {})))
        sc = cls._normalize_element_dict(data.get("series_comps", data.get("series_comp_data", {})))
        sr = cls._normalize_element_dict(data.get("series_reactors", data.get("series_reactor_data", {})))
        shunts = cls._normalize_element_dict(data.get("shunts", data.get("shunt_data", {})))

        return cls(
            project_name=str(data.get("project_name", "Untitled_Project")),
            project_id=str(data.get("project_id", "1")),
            base_mva=float(data.get("base_mva", 100.0)),
            description=str(data.get("description", "")),
            buses=buses,
            generators=generators,
            loads=loads,
            lines=lines,
            transformers=xfmrs,
            three_winding_transformers=tw_xfmrs,
            capacitors=caps,
            reactors=reactors,
            series_comps=sc,
            series_reactors=sr,
            shunts=shunts,
            fault_cases=data.get("fault_cases", []),
            line_voltage_factors=data.get("line_voltage_factors", data.get("line_factors", [])),
            global_factors=data.get("global_factors", {}),
            map_settings=data.get("map_settings", {}),
            solver_config=data.get("solver_config", {"engine": "deven_nr", "tol": 1e-5, "max_iter": 30}),
            sld_json=data.get("sld_json"),
            metadata=data.get("metadata", {})
        )

    @staticmethod
    def _normalize_element_dict(raw: Any) -> Dict[int, Dict[str, Any]]:
        """Ensures element collections are integer-keyed dicts of attribute dicts."""
        if isinstance(raw, dict):
            return {int(k): dict(v) for k, v in raw.items()}
        elif isinstance(raw, list):
            res = {}
            for item in raw:
                if isinstance(item, list) and len(item) > 0:
                    try:
                        res[int(item[0])] = {"raw_row": item}
                    except (ValueError, TypeError):
                        pass
                elif isinstance(item, dict) and "id" in item:
                    res[int(item["id"])] = item
            return res
        return {}

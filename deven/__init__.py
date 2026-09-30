"""
DevEN Power System Analysis Engine & Python Library
===================================================
A high-performance, scriptable power system simulation suite for:
  - Load Flow Analysis (LFA)
  - Short Circuit Studies (SCS)
  - Contingency Analysis (CA)
  - Time Series Load Flow (TS-LFA)

Supported Case Formats: .py, .sql, .raw, .dgs, .dat
"""

import sys
import os

__version__ = "1.0.0"
__author__ = "DevEN Team"

# Package root & search paths
_root = os.path.dirname(os.path.abspath(__file__))
_parent = os.path.dirname(_root)
_engines = os.path.join(_root, "engines")
_utils = os.path.join(_root, "utils")

for p in (_parent, _root, _engines, _utils):
    if os.path.exists(p) and p not in sys.path:
        sys.path.insert(0, p)

from deven.core.model import PowerGridData
from deven.core.io import load_network, save_network
from deven.core.deven_api import (
    DevENSession,
    load_case,
    save_case,
    new_case,
    run_lfa,
    run_scs,
    run_ca,
    run_timeseries,
    get_bus_voltage,
    get_line_flows,
    get_violations,
    execute,
)
from deven.utils.license_manager import LicenseManager
from deven.cli import get_docs_index_path, serve_docs

def set_license(license_path: str) -> bool:
    """Sets custom commercial license file path (.pyd or .deven)."""
    return LicenseManager.set_custom_license_path(license_path)

def open_docs():
    """Launches local documentation web server and opens browser."""
    serve_docs(port=8080, open_browser=True)

__all__ = [
    "DevENSession",
    "PowerGridData",
    "load_network",
    "save_network",
    "load_case",
    "save_case",
    "new_case",
    "run_lfa",
    "run_scs",
    "run_ca",
    "run_timeseries",
    "get_bus_voltage",
    "get_line_flows",
    "get_violations",
    "execute",
    "set_license",
    "open_docs",
    "get_docs_index_path",
    "LicenseManager",
    "__version__",
]

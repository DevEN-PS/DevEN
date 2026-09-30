"""
DevEN High-Performance Computational Engines
============================================
Includes native compiled binary extensions (.pyd) supporting multiple CPython ABI versions:
  - CPython 3.10 (win_amd64)
  - CPython 3.11 (win_amd64)
  - CPython 3.12 (win_amd64)
  - CPython 3.13 (win_amd64)
  - CPython 3.14 (win_amd64)

Computational Engines:
  - PowerFlowEngine (deven_nr, Newton-Raphson, Fast Decoupled, Gauss-Seidel)
  - ShortCircuitSolver (IEC 60909 fault calculations)
  - ContingencyBatch / ContingencyRunner (N-1 & multi-element contingencies)
  - TimeSeriesEngine (24h+ time-domain profile simulation)
  - Format Parsers & Converters (.raw, .dgs, .dat)
"""

import sys
import os
import platform

# Ensure engines and utils directories are in search path
_cur_dir = os.path.dirname(os.path.abspath(__file__))
_utils_dir = os.path.join(os.path.dirname(_cur_dir), 'utils')
for p in (_cur_dir, _utils_dir):
    if os.path.exists(p) and p not in sys.path:
        sys.path.insert(0, p)

def get_engine_status():
    """Returns details about loaded binary engine extensions."""
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}"
    arch = platform.architecture()[0]
    return {
        "python_version": py_ver,
        "architecture": arch,
        "engine_directory": _cur_dir,
    }

__all__ = ["get_engine_status"]

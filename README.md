# DevEN Power System Analysis Engine & Python Library

[![PyPI version](https://img.shields.io/pypi/v/deven.svg)](https://pypi.org/project/deven/)
[![Python versions](https://img.shields.io/pypi/pyversions/deven.svg)](https://pypi.org/project/deven/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**DevEN** is a high-performance, scriptable power system simulation library designed for rapid power flow, short-circuit, contingency analysis, and time-series automation. All core computational engines are compiled to high-speed native binary extensions (`.pyd`) for maximum execution speed and intellectual property protection.

---

## ⚡ Installation

Install via pip:

```bash
pip install deven
```

When you install `deven`, all required dependencies (`numpy`, `scipy`, `pandas`, `networkx`, `openpyxl`, `prettytable`, `typing_extensions`) are automatically installed.

---

## 📁 Supported Input File Formats

DevEN seamlessly ingests power system models across multiple standard file formats:

| Format | Extension | Description |
|:---|:---|:---|
| **Python Case Database** | `.py` | Native dictionary-based power network model |
| **SQL Database** | `.sql`, `.sqlite`, `.db` | Relational SQLite database container |
| **Raw Grid Data** | `.raw` | Standard ASCII bus/branch power network file |
| **DGS General Schema** | `.dgs`, `.pfd` | General schema data exchange file |
| **Tabular Network Data** | `.dat`, `.dat0` | Fixed-column tabular network data file |

---

## 🔬 Core Capabilities

DevEN provides four primary study modules:

1. **Load Flow Analysis (LFA)**
   - High-performance Newton-Raphson solver (`deven_nr`)
   - Configurable tolerance (default `1e-5`) and iterations (default `30`)
   - Detailed generation, load, branch flow, voltage magnitude, and loss calculations
   - Automatic IEEE, CEA, and KCL compliance reporting

2. **Short Circuit Studies (SCS)**
   - Standard-compliant fault calculations (IEC 60909)
   - Three-phase symmetrical faults (3-Ph) and single line-to-ground faults (SLG)
   - Initial symmetrical short-circuit current ($I_k''$), peak current ($i_p$), and breaking current ($I_b$)

3. **Contingency Analysis (CA)**
   - Comprehensive N-1, N-k, and user-defined multi-element contingencies
   - Outage simulation for transmission lines and power transformers
   - Island detection and post-contingency voltage/thermal limit violations

4. **Time Series Load Flow (TS-LFA)**
   - Multi-period time-domain simulation (e.g. 24-hour profiles)
   - Hourly or sub-hourly dispatch steps
   - Time-series voltage profiles, branch loadings, and loss accumulation

---

## 🚀 Quickstart Example

```python
import deven

# Initialize stateful simulation session
sess = deven.DevENSession()

# Load power system case (.py, .sql, .raw, .dgs, or .dat)
sess.load_case("case.py")

# 1. Run Load Flow Analysis
lfa_res = sess.run_lfa(engine="deven_nr", tol=1e-5, max_iter=30)
print(f"LFA Converged: {lfa_res['converged']} in {lfa_res['iterations']} iterations")

# 2. Run Short Circuit Analysis (IEC 60909)
scs_res = sess.run_scs(method="iec")
print(f"SCS Calculated: {scs_res['buses_calculated']} buses evaluated")

# 3. Run Contingency Analysis (Outage of specific lines & transformers)
ca_res = sess.run_ca(
    lines=[1, 2, 3, 4],
    transformers=[1, 2],
    engine="deven_nr"
)
print(f"CA Evaluated: {ca_res['total_contingencies']} cases")

# 4. Run 24-Hour Time Series Load Flow
ts_res = sess.run_timeseries(
    duration=24.0,
    dur_unit="Hours",
    step_size=1.0,
    step_unit="Hours",
    engine="deven_nr"
)
print(f"Time Series Completed: {ts_res['steps_completed']} steps")
```

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

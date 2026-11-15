# DevEN (devenpy) — Power system study engine

Made in India from Bengaluru.

A pure native, ultra-fast power system simulation engine for AC Load Flow Analysis (LFA), Short Circuit Studies (SCS), Harmonic Power Flow & Frequency Scan (HA), 3-Phase Unbalanced Power Flow (3PH), Arc Flash Hazard Analysis (AF), and Batch Contingency Screening (BC).

---

## 1. Supported Grid Ingestion Formats

### ★ PSS/E RAWX (`.rawx`) [First Preference]
Recommended standard: Modern schema-validated XML/JSON format with high numerical precision and structured definitions.

### Universal Multi-Format Ingestion (`deven_io.py`)
- **PSS/E Formats**: `.rawx` (v32-v35), `.raw` (v29-v35)
- **MATPOWER**: `.m` files (bus, gen, branch matrices)
- **IEEE Common Data Format**: `.cdf`
- **Spreadsheets**: Excel `.xlsx` / `.xls` (multi-sheet: Bus, Branch, Generator, Load)
- **PowerWorld**: `.aux` scripts
- **European UCTE**: `.def` format
- **CIM / CGMES**: `.xml` schema
- **Native Encrypted**: `.deven` binary databases

---

## 2. Installation

Install `devenpy` via pip:

```bash
# Install directly from the wheel
pip install devenpy-1.0.0-cp311-abi3-win_amd64.whl

# Or install from directory
pip install .
```

---

## 3. Interactive Web Documentation & Runner Scaffolding

DevEN includes an automated local documentation server and template exporter built right into the package CLI:

### 📖 View Web Documentation Locally
Launch an automated zero-dependency local web server that opens the complete single-file interactive documentation portal in your default browser:
```bash
devenpy --docs
# or:
python -m devenpy --docs
```

### 📁 Export Ready-to-Edit Study Runners & Sample Cases
Export all 6 standalone study runners and benchmark network models directly into your current terminal working directory:
```bash
devenpy --export-runners
# or specify a custom destination:
devenpy --export-runners ./my_project
```

Once exported, you will find:
- `run_lfa.py`  : AC Load Flow Analysis (NR, FDLF, DC, Gauss-Seidel, voltage limits, in-code generator & load edits)
- `run_scs.py`  : Short Circuit Studies (IEC 60909:2016 & ANSI C37, custom fault scenarios, breaker duty, contributions)
- `run_ha.py`   : Harmonic Power Flow & Frequency Scan (IEEE 519-2022, resonance detection, custom sources & filters)
- `run_3ph.py`  : 3-Phase Unbalanced Power Flow (4-Wire/3-Wire FCIM, phase voltage unbalance rate, sequence components)
- `run_af.py`   : Arc Flash Hazard Analysis (IEEE 1584-2018 & NFPA 70E-2024, incident energy, PPE categories)
- `run_bc.py`   : Batch Contingency & N-1 Outage Screening (editable in-code lines, transformers, and generator trips)
- `deven_io.py` : Universal Multi-Format Grid Ingestion parser (MATPOWER, CDF, Excel, AUX, etc.)
- `cases/`      : Benchmark grids (`bench.rawx`, `case14.raw`, `iec60909_testnetwork_50Hz.raw`, `bench2.raw`)

---

## 4. Python API Quickstart

```python
import devenpy

# 1. Initialize case and load grid model (RAWX is first preference)
case = devenpy.PyCase()
case.load_rawx("cases/bench.rawx")

# Or load extended formats using universal I/O layer
# case = devenpy.load_grid_file("my_case.m")
# case = devenpy.load_grid_file("my_network.xlsx")

# 2. AC Load Flow (Newton-Raphson)
status = case.solve_load_flow(method="nr", tol=1e-5, show_q_limits=True)
print(f"LFA Converged: {status['converged']} in {status['iterations']} iters")

# 3. Short Circuit (IEC 60909 3-Phase Fault at Bus 1)
scs = case.solve_short_circuit(fault_bus=1, fault_type="3phase", method="iec")
print(f"Initial Symmetrical Current (Ik\"): {scs['ik_ka']:.3f} kA")

# 4. Save to Standard Encrypted Database
case.save_deven("cases/bench.deven")
```

---

## 5. Master CLI Usage

The pure Python CLI runs simulations directly without external dependencies:

```bash
# AC Load Flow with columnar PSS/E .out report
devenpy cases/bench.rawx --format out -o bench.out

# Short Circuit Study (IEC 60909 3-Phase Fault at Bus 1)
devenpy cases/bench.rawx --study scs --fault-bus 1 --fault-type 3phase

# System-Wide Fault Scan Across All Buses (< 1 ms)
devenpy cases/bench.rawx --study scs --scan
```

---

## 6. Contact & Support

- **GitHub Repository**: [https://github.com/DevEN-PS/DevEN](https://github.com/DevEN-PS/DevEN)
- **Email Support**: [devarajedeva2002@gmail.com](mailto:devarajedeva2002@gmail.com)
- **Engine**: DevEN (devenpy) · Power system study engine · Made in India from Bengaluru

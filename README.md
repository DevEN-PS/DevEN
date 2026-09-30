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

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

## 🌐 About DevEN — Develop Electric Network

**DevEN** (Develop Electric Network) is an ultra-fast, scriptable AC power flow and grid analysis engine developed by **Devaraj E & team**, Bengaluru (ಬೆಂಗಳೂರು), India. DevEN features native C/C++ compiled mathematical kernels (compiled to `.pyd` extensions) for maximum execution speed and intellectual property protection. It is designed to replace slow, expensive commercial power system tools for rapid prototyping, automation, scripting, and large-scale batch simulation.

The **free tier** supports up to **100 buses**. Commercial licensing is available for unlimited bus counts.  
Contact: [devarajedeva2002@gmail.com](mailto:devarajedeva2002@gmail.com)

- 📖 **Docs / GitHub Pages**: https://deven-ps.github.io/DevEN/
- ⭐ **GitHub Repository**: https://github.com/DevEN-PS/DevEN
- 📄 **Master PDF Manual**: [DevEN_Master_User_and_API_Reference_Manual.pdf](https://github.com/DevEN-PS/DevEN/releases/download/v1.1/DevEN_Master_User_and_API_Reference_Manual.pdf)

---

## 🔬 All 16 Power System Studies

### 1. 1-Phase Load Flow Analysis (LFA)
Calculates steady-state bus voltage magnitudes (V), phase angles (θ), active/reactive power flows (P, Q), and system losses. Uses Newton-Raphson (NR), Fast-Decoupled (FDLF), Gauss-Seidel (GS), Levenberg-Marquardt (LM), and Continuation Power Flow (CPF) solvers.  
**Standards**: IEEE 399 / IEEE 3004.2 / IEC 60909-0  
```python
sess.run_lfa(engine="deven_nr", tol=1e-5, max_iter=30)
```

### 2. 3-Phase Unbalanced Load Flow (3P LFA)
Solves full coupled 3-phase nodal equations (Y_abc × V_abc = I_abc) for unbalanced distribution grids. Calculates neutral voltage rise (Vn), phase loadings, Voltage Unbalance Factor (VUF%).  
**Standards**: IEEE Std 1159 / NEMA MG 1 / IEC 61000-4-30  
```python
sess.run_3ph_lfa()
```

### 3. Short Circuit Study (SCS)
IEC 60909 and ANSI/IEEE C37 fault calculations. Initial symmetrical short-circuit current (Ik''), peak current (ip), breaking current (Ib), DC offset. Supports 3-Ph, SLG, LL, DLG fault types.  
**Standards**: IEC 60909-0 / ANSI/IEEE C37.010  
```python
sess.run_scs(method="iec")
```

### 4. Contingency Analysis (CA)
N-1, N-k, and user-defined multi-element contingency simulation for lines and transformers. Island detection, post-contingency thermal/voltage violations.  
**Standards**: NERC TPL / IEEE 3006  
```python
sess.run_ca(lines=[1,2,3], transformers=[1])
```

### 5. Time Series Load Flow (TS-LFA)
Multi-period time-domain simulation (24-hour, 8760-hour annual). Hourly/sub-hourly dispatch. Time-series voltage profiles, branch loadings, loss accumulation stored in SQLite.  
```python
sess.run_timeseries(duration=24.0, step_size=1.0)
```

### 6. Optimal Power Flow (OPF)
Minimizes total generation cost ($/MWh) subject to power flow equations, voltage limits, thermal limits, and generator MW/MVAr capability constraints. KKT interior point and IPOPT solvers.  
```python
sess.run_opf(obj="min_cost")
```

### 7. Voltage Stability Analysis (VSA)
Computes PV nose curves and QV curves. Reports voltage stability index (VSI), maximum loadability (Pmax), critical operating points.  
**Standards**: IEEE Std 1110 / IEC 60038  
```python
sess.run_vsa(bus=5, direction="load")
```

### 8. Motor Starting Study (MSS)
Calculates bus voltage dip (ΔV%) during induction motor DOL, star-delta (Y-Δ), and soft-starter transients. NEMA MG 1 voltage dip limit compliance.  
**Standards**: IEEE 399 / IEC 60034-12  
```python
sess.run_mss(motor_bus=12, hp=1500, method="dol")
```

### 9. Harmonic Load Flow (HLF)
Injects harmonic current spectra (orders 3, 5, 7, 11, 13…) from VFDs/UPS/arc furnaces. Solves harmonic bus voltages, reports THD%.  
**Standards**: IEEE 519-2022 / IEC 61000-3-6  
```python
sess.run_hlf(harmonic_orders=[3,5,7,11,13])
```

### 10. Protection Coordination Study (PCS)
OCR, DOCR, differential, and distance relays. TCC plots, coordination margins (CTI ≥ 0.3 s), selectivity gap detection.  
**Standards**: IEEE Std 242 (Buff Book) / IEC 60255  
```python
sess.run_pcs(relay_type="ocr", curve="IEC_EI")
```

### 11. Ground Fault Study (GFS)
Earth fault currents for solidly/resistance/reactance grounded and ungrounded systems. Ground potential rise (GPR), step/touch voltages, grounding adequacy.  
**Standards**: IEEE Std 80 / IEC 60364  
```python
sess.run_gfs(grounding="resistance", Rg=40.0)
```

### 12. Power Quality Study (PQS)
Voltage sags, swells, flicker (Pst, Plt), THD, TDD, power factor, unbalance. Reports against IEEE 519, EN 50160, IEC 61000-4-30.  
```python
sess.run_pqs(metrics=["thd","pf","flicker"])
```

### 13. Cable Ampacity & Thermal Rating (CAT)
Maximum continuous ampacity of underground cables and overhead conductors per IEC 60287 and IEEE 835. Accounts for soil thermal resistivity, installation depth, burial grouping, ambient temperature.  
```python
sess.run_cat(cable_id=3, soil_rho=1.0, depth=0.9)
```

### 14. Transient Stability Study (TSS)
Time-domain swing equation integration with generator dynamic models (Classical, GENROU, AVR exciter) after fault clearing. Critical clearing time (CCT), rotor angle trajectories, speed deviations.  
**Standards**: IEEE Std 1110  
```python
sess.run_tss(fault_bus=3, fault_dur=0.1)
```

### 15. Total Transfer Capability (TTC/ATC)
TTC and ATC (= TTC − TRM − ETC − CBM) for transmission corridors. FERC Order 888 compliance and open-access tariff studies.  
**Standards**: NERC MOD-001 / NERC TPL  
```python
sess.run_ttc(from_area=1, to_area=2)
```

### 16. Reactive Power Planning (RPP)
Optimal locations/sizes for reactive compensation (shunt capacitors, SVCs, STATCOMs) to minimize losses, improve voltage profiles, maximize loadability. Sensitivity-based (∂Q/∂V) and mixed-integer optimization.  
```python
sess.run_rpp(method="sensitivity")
```

---

## ⚙️ Solvers & Engines

| Engine ID | Method | Convergence | Best For |
|:---|:---|:---|:---|
| `deven_nr` | Newton-Raphson | Quadratic | Transmission networks, general use |
| `deven_fdlf` | Fast-Decoupled (XB/BX) | Linear per sub-problem | Large systems, high X/R ratio |
| `deven_gs` | Gauss-Seidel | Linear | Small radial distribution networks |
| `deven_lm` | Levenberg-Marquardt | Quadratic (robust) | Ill-conditioned, heavily loaded grids |
| `deven_cpf` | Continuation Power Flow | Predictor-corrector | Voltage stability nose curves |

---

## 🏗️ Element Library

DevEN supports a comprehensive set of power system elements modelled from first principles:

| Element | Key Parameters |
|:---|:---|
| **Bus** | Slack / PV / PQ / Isolated types; V-pu, angle, kV base |
| **Generator** | MW, MVAr, Vset, Pmin/Pmax, Qmin/Qmax, droop |
| **Load** | Constant power (ZIP), constant current, constant impedance, motor loads |
| **Transmission Line** | Pi-model: R, X, B/2 per unit or ohm/km; thermal rating (MVA) |
| **2-Winding Transformer** | YY, YD, DD, ZigZag; OLTC, ULTC, phase shifting |
| **3-Winding Transformer** | Star equivalent; primary/secondary/tertiary MVA ratings and impedances |
| **Shunt Capacitor/Reactor** | Fixed/switched MVAr; harmonic filter C-R-L banks |
| **SVC / STATCOM** | Voltage-controlled reactive injection; slope and deadband |
| **Induction Motor** | Equivalent circuit (Rs, Xs, Rr, Xr, Xm, slip); starting curve |
| **Harmonic Source** | Current injection model; VFD, UPS, arc furnace spectra |
| **Wind / Solar PV** | Type 3/4 DFIG, full-converter PV inverter; FRT capability |
| **Battery Storage (BESS)** | 4-quadrant inverter; SOC model; charge/discharge scheduling |

---

## 📐 Key Power Flow Equations

**Active and Reactive Power Injection at Bus i:**

```
P_i = Σ_j |V_i||V_j| (G_ij cos θ_ij + B_ij sin θ_ij)
Q_i = Σ_j |V_i||V_j| (G_ij sin θ_ij − B_ij cos θ_ij)
```

**Short Circuit — Initial Symmetrical Current (IEC 60909):**

```
I_k'' = c × V_n / (√3 × |Z_k|)
```

**Cable Ampacity (IEC 60287):**

```
I = √[ (Δθ − W_d[0.5T₁ + n(T₂+T₃+T₄)]) / (T₁·R + n(1+λ₁)T₂·R + n(1+λ₁+λ₂)(T₃+T₄)·R) ]
```

**Voltage Unbalance Factor (VUF):**

```
VUF% = (|V₋₋₋| / |V₊₊₊|) × 100
```

---

## 💻 CLI Quick Reference

```bash
deven run-lfa  grid.dss  --engine deven_nr --tol 1e-6 --max-iter 50 --output results.db3
deven run-scs  grid.raw  --method iec --fault-bus 5 --fault-type slg --output scs.xlsx
deven run-ca   grid.json --contingencies n1 --monitor voltage thermal --output ca_report.pdf
deven run-ts   grid.xlsx --duration 8760 --step 1.0 --profile load_profile.csv --output ts.db3
deven info                     # print version, license status, bus count limit
deven license activate --key <YOUR_KEY>   # unlock unlimited buses
```

---

## 📋 Standards & Compliance Reference

| Standard | Scope |
|:---|:---|
| **IEC 60909-0:2016** | Short-circuit currents in three-phase AC systems |
| **IEC 60287** | Electric cables — current ratings |
| **IEC 61000-3-6 / 4-30** | Harmonics & power quality |
| **IEEE 519-2022** | Harmonic control in power systems |
| **IEEE 399 / 3004.2** | Power system analysis & load flow |
| **IEEE Std 242 (Buff Book)** | Protection & coordination |
| **IEEE Std 80** | Grounding of AC substations |
| **NERC TPL / MOD-001** | Transmission planning standards |
| **NEMA MG 1** | Motors and generators |
| **EN 50160** | Voltage characteristics of public electricity supply |
| **FERC Order 888** | Open-access transmission tariff |
| **IEC 60034-12** | Rotating electrical machines — starting performance |

---

© 2024–2025 Devaraj E & Team, Bengaluru, India · DevEN — Develop Electric Network

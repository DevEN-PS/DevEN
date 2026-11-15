"""
DevEN Unified Power Flow & Short Circuit Engine - Type Stub File (devenpy.pyi)
Provides 100% IDE autocomplete, type hints, parameter descriptions, and PSS/E compatibility.
"""

from typing import Any, Dict, List, Optional, Tuple, Union

def load(path: str, password: Optional[str] = None) -> Any:
    """Ingest any power system grid file (PSS/E RAW v30-v36, RAWX, DevEN, MATPOWER .m, IEEE CDF, Excel, JSON)."""
    ...

def extract_results(case: "PyCase") -> Dict[str, Any]:
    """Extract complete simulation results (buses, gens, branches) into a Python dictionary."""
    ...

def export_out(case: "PyCase", path: str) -> None:
    """Generate a PSS/E-style columnar text report (.out) on demand."""
    ...

def export_csv(case: "PyCase", path_prefix: str) -> None:
    """Export simulation results to CSV tables (_buses.csv, _generators.csv, _branches.csv) on demand."""
    ...

def export_json(case: "PyCase", path: str) -> None:
    """Export complete solved grid state dictionary to JSON on demand."""
    ...

class PyCase:
    """
    DevEN Native AC Power Flow (LFA) & Short Circuit Studies (SCS) Engine.
    Holds network topology, sparse admittance matrices, sequence networks (Z1, Z2, Z0),
    and solved states in native Rust memory with zero-copy CPython bindings.
    """

    def __init__(self) -> None:
        """Construct a new empty PyCase instance."""
        ...

    def copy(self) -> "PyCase":
        """Create a fast, independent in-memory clone of the entire case (topology, parameters, warm start)."""
        ...

    def __copy__(self) -> "PyCase":
        ...

    def __deepcopy__(self, memo: Any) -> "PyCase":
        ...

    # =========================================================================
    # 1. DATA INGESTION & CONFIGURATION
    # =========================================================================
    def load_raw(self, path: str) -> None:
        """Load a PSS/E RAW format file (v30 to v36) including sequence parameters."""
        ...

    def load_rawx(self, path: str) -> None:
        """Load a PSS/E RAWX format file (v35/v36 XML/JSON format)."""
        ...

    def load_deven(self, path: str, password: Optional[str] = None) -> None:
        """
        Load an encrypted native DevEN database file (.deven).
        Seamlessly decrypts files using DevEN standard AES-256-GCM encryption without requiring
        a password prompt, or uses the supplied password for custom password-protected files.
        """
        ...

    def load(self, path: str, password: Optional[str] = None) -> None:
        """Auto-detect format by extension (.raw, .rawx, .deven, .json) and load grid model."""
        ...

    def save_deven(self, path: str, password: Optional[str] = None) -> None:
        """
        Save the in-memory case to an encrypted native DevEN database (.deven).
        By default (password=None), encrypts using DevEN standard AES-256-GCM encryption (mode 0x03)
        to protect data from external viewers (DBeaver, sqlite3) while allowing seamless loading
        without user password prompts. An optional password can be supplied for custom protection.
        """
        ...

    def load_json(self, path: str) -> None:
        """Load a DevEN native JSON case file."""
        ...

    def load_dict(self, d: Dict[str, Any]) -> None:
        """Load grid topology and parameters from a Python dictionary."""
        ...

    def set_work_with_slack(self, val: bool) -> None:
        """
        Configure Slack generator enforcement mode.
        - True: Strictly enforces that an in-service slack generator exists. Halts with error if missing.
        - False: Allows distributed boundary angle reference mode.
        """
        ...

    def get_work_with_slack(self) -> bool:
        """Return the current Slack enforcement policy (True or False)."""
        ...

    def set_show_q_limits(self, val: bool) -> None:
        """Enable or disable console printing of generator Q-limit transitions during solve."""
        ...

    def get_show_q_limits(self) -> bool:
        """Return whether generator Q-limit transitions are printed to stdout (True or False)."""
        ...

    @property
    def show_q_limits(self) -> bool:
        """Console logging toggle for generator Q-limit transitions during solve."""
        ...

    @show_q_limits.setter
    def show_q_limits(self, val: bool) -> None:
        ...

    def get_stats(self) -> Dict[str, Any]:
        """Return high-level summary counts of buses, gens, branches, loads, shunts, swshunts, and versions."""
        ...

    def swshunt_count(self) -> int:
        """Return the total number of switched shunt devices in the network."""
        ...

    # =========================================================================
    # 2. IN-MEMORY DATA MODIFIERS (SETTERS FOR LFA & SCS)
    # =========================================================================
    def chng_bus(
        self,
        bus_id: int,
        vm: Optional[float] = None,
        va: Optional[float] = None,
        base_kv: Optional[float] = None,
        ide: Optional[int] = None,
        gl: Optional[float] = None,
        bl: Optional[float] = None,
    ) -> None:
        """Modify bus operating voltage, base kV, type (1=PQ, 2=PV, 3=Slack), or shunts in memory."""
        ...

    def chng_bus_limits(
        self,
        bus_id: int,
        nvhi: Optional[float] = None,
        nvlo: Optional[float] = None,
        evhi: Optional[float] = None,
        evlo: Optional[float] = None,
    ) -> None:
        """Modify bus normal and emergency voltage limits (NVHI, NVLO, EVHI, EVLO). Bumps numeric_version."""
        ...

    def chng_bus_name(self, bus_id: int, name: str) -> None:
        """Modify bus name in memory. Bumps numeric_version."""
        ...

    def chng_bus_zone_owner(
        self,
        bus_id: int,
        area: Optional[int] = None,
        zone: Optional[int] = None,
        owner: Optional[int] = None,
    ) -> None:
        """Modify bus area, zone, and owner assignments. Bumps numeric_version."""
        ...

    def chng_load(
        self,
        bus_id: int,
        id: str = "",
        pl: Optional[float] = None,
        ql: Optional[float] = None,
        status: Optional[int] = None,
    ) -> None:
        """Modify load active power (MW), reactive power (MVAr), or service status in memory."""
        ...

    def chng_gen(
        self,
        bus_id: int,
        id: str = "",
        pg: Optional[float] = None,
        qg: Optional[float] = None,
        vs: Optional[float] = None,
        status: Optional[int] = None,
        qmax: Optional[float] = None,
        qmin: Optional[float] = None,
    ) -> None:
        """Modify generator active power, voltage setpoint, reactive limits, or status in memory."""
        ...

    def chng_brn(
        self,
        f: int,
        t: int,
        ckt: str = "",
        r: Optional[float] = None,
        x: Optional[float] = None,
        b: Optional[float] = None,
        ratio: Optional[float] = None,
        angle: Optional[float] = None,
        status: Optional[int] = None,
        rate_a: Optional[float] = None,
    ) -> None:
        """Modify branch impedance (R, X, B), tap ratio, phase shift, status, or rating in memory."""
        ...

    def scs_chng_bus(
        self,
        bus_id: int,
        is_grid_infeed: Optional[bool] = None,
        sk_mva: Optional[float] = None,
        rx_ratio: Optional[float] = None,
        z01_ratio: Optional[float] = None,
        cb_mva: Optional[float] = None,
        cb_k_factor: Optional[float] = None,
    ) -> None:
        """
        Modify bus short circuit parameters in memory:
        :param is_grid_infeed: Whether bus is an external grid connection / infeed point.
        :param sk_mva: Short circuit capacity in MVA (for grid infeeds).
        :param rx_ratio: System R/X ratio at this bus.
        :param z01_ratio: Ratio of zero-sequence to positive-sequence impedance (Z0/Z1).
        :param cb_mva: Substation circuit breaker rated interrupting MVA capability.
        :param cb_k_factor: Circuit breaker voltage range factor K (default: 1.15).
        """
        ...

    def scs_chng_gen(
        self,
        bus_id: int,
        id: str = "",
        xd_sub: Optional[float] = None,
        x2: Optional[float] = None,
        x0: Optional[float] = None,
        r1: Optional[float] = None,
        r2: Optional[float] = None,
        r0: Optional[float] = None,
        conn: Optional[str] = None,
        gnd_r: Optional[float] = None,
        gnd_x: Optional[float] = None,
        gen_type: Optional[str] = None,
    ) -> None:
        """
        Modify generator sequence parameters and neutral grounding in memory:
        :param xd_sub: Subtransient reactance Xd'' in p.u. (default: 0.20).
        :param x2: Negative-sequence reactance X2 in p.u. (default: 0.20).
        :param x0: Zero-sequence reactance X0 in p.u. (default: 0.05).
        :param r1: Positive-sequence stator resistance in p.u.
        :param r2: Negative-sequence resistance in p.u.
        :param r0: Zero-sequence resistance in p.u.
        :param conn: Connection type: 'G' (Grounded Wye), 'W' (Ungrounded Wye), 'D' (Delta).
        :param gnd_r: Neutral grounding resistance in p.u.
        :param gnd_x: Neutral grounding reactance in p.u.
        :param gen_type: Machine category: 'thermal', 'hydro', 'nuclear', 'wind', 'solar'.
        """
        ...

    def scs_chng_brn(
        self,
        f: int,
        t: int,
        ckt: str = "",
        r0: Optional[float] = None,
        x0: Optional[float] = None,
        b0: Optional[float] = None,
        from_conn: Optional[str] = None,
        to_conn: Optional[str] = None,
        from_gnd_r: Optional[float] = None,
        from_gnd_x: Optional[float] = None,
        to_gnd_r: Optional[float] = None,
        to_gnd_x: Optional[float] = None,
        from_cb_mva: Optional[float] = None,
        to_cb_mva: Optional[float] = None,
    ) -> None:
        """
        Modify branch zero-sequence impedances and transformer grounding in memory:
        :param r0: Zero-sequence resistance R0 in p.u.
        :param x0: Zero-sequence reactance X0 in p.u. (typically 2.5x to 3.5x X1).
        :param b0: Zero-sequence shunt susceptance B0 in p.u.
        :param from_conn: Sending end winding connection: 'G' (Grd Wye), 'W' (Wye), 'D' (Delta).
        :param to_conn: Receiving end winding connection: 'G' (Grd Wye), 'W' (Wye), 'D' (Delta).
        :param from_gnd_r: Sending end neutral grounding resistance in p.u.
        :param from_gnd_x: Sending end neutral grounding reactance in p.u.
        :param to_gnd_r: Receiving end neutral grounding resistance in p.u.
        :param to_gnd_x: Receiving end neutral grounding reactance in p.u.
        :param from_cb_mva: Sending terminal breaker rating in MVA.
        :param to_cb_mva: Receiving terminal breaker rating in MVA.
        """
        ...

    # =========================================================================
    # 3. LOAD FLOW SOLVERS & RESULTS (LFA)
    # =========================================================================
    def solve_load_flow(
        self,
        method: Optional[str] = "nr",
        tol: Optional[float] = 1e-5,
        max_iter: Optional[int] = 30,
        work_with_slack: Optional[bool] = None,
        island_policy: Optional[str] = "auto_isolate",
        ignore_q_tol: Optional[bool] = False,
        enforce_q_limits: Optional[bool] = True,
        flat_start: Optional[bool] = None,
        use_pre_ran_results: Optional[bool] = None,
        show_q_limits: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Execute Power Flow Analysis.
        :param method: Algorithm selection:
                       - "nr" / "newton": Full Newton-Raphson with exact complex-derivative Jacobian.
                       - "dc" / "dclf": One-shot DC Linear Load Flow solving B*theta = P (V=1.0 pu).
                       - "dishonest": Constant Jacobian Newton (factorizes J(x0) once at iter 0).
                       - "fdlf" / "fdxb": Fast Decoupled Load Flow with decoupled B' & B'' and NR fallback.
                       - "gs" / "gauss": Gauss-Seidel with acceleration factor 1.6.
        :param tol: Convergence mismatch tolerance in p.u. (default: 1e-5 / 0.00001).
        :param max_iter: Maximum iteration limit (default: 30).
        :param work_with_slack: Override slack mode (True = strict generator online, False = distributed).
        :param island_policy: Policy for handling disconnected sub-grids and isolated dummy buses:
                              - "auto_isolate" (Default): Automatically marks disconnected buses (and their
                                connected loads, generators, and shunts) as out of service, solving the
                                remaining healthy, connected grid cleanly without crashing.
                              - "skip": Immediately halts and returns a clean error message if any active
                                bus is disconnected from the Slack bus (optimized for fast N-1 contingency sweeps).
                              - "strict": Performs no automatic filtering; attempts calculation as-is (legacy behavior).
        :param ignore_q_tol: If True, bypasses generator reactive power limit enforcement.
        :param enforce_q_limits: If True (default), enforces generator Q limits (PV -> PQ switching). If False, disables Q limit enforcement.
        :param flat_start: If True, forces flat start initialization (1.0 pu on PQ, Vset on PV/Slack, 0 deg) and clears warm start.
                           If False, forces cold start from pre-run file voltages/angles. If None (default), auto-detects.
        :param use_pre_ran_results: If True, forces using pre-run voltages/angles from the file/case (equivalent to flat_start=False).
        :param show_q_limits: If True, prints live indented [DevEN Q-LIMIT] and [DevEN Q-RECOVERY] transitions to stdout.
                              If False, runs in quiet mode showing only iteration residuals. If None, uses case.show_q_limits.
        :return: Solution status dict with keys: 'converged', 'iterations', 'max_dp', 'max_dq'.
        """
        ...

    def solve_batch(
        self,
        snaps: List[Dict[str, Any]],
        method: Optional[str] = "fdlf",
        work_with_slack: Optional[bool] = None,
        island_policy: Optional[str] = "auto_isolate",
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Execute parallel batch contingency (N-1) or time-series scenarios natively in Rust.
        :param snaps: List of perturbation dictionaries.
        :param method: Algorithm for batch runs (default: "fdlf").
        :param work_with_slack: Override slack mode (True = strict generator online, False = distributed).
        :param island_policy: Policy for handling disconnected islands ("auto_isolate", "skip", "strict").
        :return: (List of scenario result summaries, overall batch status).
        """
        ...

    def bus_voltage(self, id: int) -> Tuple[float, float]:
        """Return (voltage_magnitude_pu, phase_angle_deg) for bus `id`."""
        ...

    def bus_power(self, id: int) -> Tuple[float, float]:
        """Return (p_injection_mw, q_injection_mvar) for bus `id`."""
        ...

    def branch_flow(self, f: int, t: int, ckt: str = "") -> Dict[str, Any]:
        """Return flow dictionary (p_from, q_from, p_to, q_to, losses_mw, losses_mvar, loading_pct)."""
        ...

    def gen_output(self, b: int, id: str = "") -> Dict[str, Any]:
        """Return generator operating point (p_mw, q_mvar, v_set)."""
        ...

    def hvdc_flow(self, num: int) -> Dict[str, Any]:
        """Return HVDC line power flows and converter firings."""
        ...

    def bus_real(self, id: int, param: str) -> float:
        """Query scalar float parameter for bus `id` ('VM', 'VA', 'BASEKV', 'MISMW', 'MISMVAR', 'PLOAD', 'QLOAD', etc.)."""
        ...

    def bus_int(self, id: int, param: str) -> int:
        """Query integer parameter for bus `id` ('TYPE', 'STATUS', 'NUMBER', 'AREA', 'ZONE')."""
        ...

    def bus_char(self, id: int, param: str) -> str:
        """Query alphanumeric string parameter for bus `id` ('NAME')."""
        ...

    def gen_real(self, b: int, id: str, param: str) -> float:
        """Query scalar float parameter for generator at bus `b` ('P', 'Q', 'VS', 'QMAX', 'QMIN', 'MBASE')."""
        ...

    def gen_int(self, b: int, id: str, param: str) -> int:
        """Query integer parameter for generator at bus `b` ('STATUS', 'BUS')."""
        ...

    def brn_real(self, f: int, t: int, ckt: str, param: str) -> float:
        """Query scalar float parameter for branch ('R', 'X', 'B', 'RATIO', 'ANG', 'RATEA', 'PFROM', 'QFROM', 'PTO', 'QTO', 'PLOSS', 'PCT')."""
        ...

    def brn_int(self, f: int, t: int, ckt: str, param: str) -> int:
        """Query integer parameter for branch ('STATUS', 'FROM', 'TO')."""
        ...

    def facts_real(self, name: str, param: str) -> float:
        """Query FACTS device scalar parameter."""
        ...

    def facts_int(self, name: str, param: str) -> int:
        """Query FACTS device integer parameter."""
        ...

    def vsc_line_real(self, name: str, param: str) -> float:
        """Query VSC DC line parameter."""
        ...

    def vsc_conv_real(self, name: str, conv: int, param: str) -> float:
        """Query VSC converter parameter."""
        ...

    def vsc_conv_int(self, name: str, conv: int, param: str) -> int:
        """Query VSC converter integer parameter."""
        ...

    def bus_data_array(self, param: str) -> List[float]:
        """Return vectorized list of values for parameter `param` across all buses."""
        ...

    def gen_data_array(self, param: str) -> List[float]:
        """Return vectorized list of values for parameter `param` across all generators."""
        ...

    def brn_data_array(self, param: str) -> List[float]:
        """Return vectorized list of values for parameter `param` across all branches."""
        ...

    def report_dict(self) -> Dict[str, Any]:
        """Return complete solved network report as a structured Python dictionary."""
        ...

    def report_sections(self, secs: List[str]) -> Dict[str, Any]:
        """Return specified report sections ('bus', 'gen', 'branch', etc.) as a dictionary."""
        ...

    def report_json(self) -> str:
        """Return complete solved network report as a serialized JSON string."""
        ...

    def write_out(self, path: str) -> None:
        """Write columnar PSS/E-style text report file to `path`."""
        ...

    def kcl_report(self) -> str:
        """
        Generate comprehensive Kirchhoff's Current Law (KCL) & Power Balance Report.
        - Displays both terminal flows simultaneously (from-side & to-side) with MW, Mvar, MVA, and Amps.
        - Details individual elements (generators, loads, switched shunts) with their IDs and currents.
        - Provides exact bus-level KCL balance verification (dP, dQ, dI) and system energy conservation.
        :return: Multi-line formatted KCL report string.
        """
        ...

    def check_q_limits(self, bus: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Check generator reactive power (Q) operating points against Qmin and Qmax limits.
        :param bus: Optional bus ID to filter. If omitted, checks all generators in the grid.
        :return: List of generator status dictionaries containing:
                 - 'bus': Bus integer ID
                 - 'bus_name': Bus name string
                 - 'bus_type': Bus type code (1=PQ, 2=PV, 3=Slack)
                 - 'gen_id': Generator ID string
                 - 'status': In-service status (1=Online, 0=Offline)
                 - 'p_mw': Active power generation (MW)
                 - 'q_mvar': Solved reactive power generation (Mvar)
                 - 'q_min_mvar': Minimum reactive power capability (Mvar)
                 - 'q_max_mvar': Maximum reactive power capability (Mvar)
                 - 'v_set_pu': Target voltage setpoint (p.u.)
                 - 'v_actual_pu': Actual bus voltage magnitude (p.u.)
                 - 'v_actual_kv': Actual line-to-line voltage (kV)
                 - 'violation_status': "WITHIN_LIMITS", "AT_QMAX", "AT_QMIN", "VIOLATED_QMAX", "VIOLATED_QMIN", or "OFFLINE"
                 - 'is_violated': Boolean flag (True if outside limits)
                 - 'mismatch_mvar': Magnitude of Q violation beyond limit (Mvar)
        """
        ...

    def has_q_limit_violations(self) -> bool:
        """
        Check if any online generator in the solved network violates its Qmin/Qmax limits.
        :return: True if any generator has exceeded Qmin or Qmax beyond tolerance, False otherwise.
        """
        ...

    # =========================================================================
    # 3.5 PRE-SOLVE GATED VIOLATION CHECKERS & UTILITIES (PHASE 1)
    # =========================================================================
    def check_voltage_violations(
        self,
        v_min: Optional[float] = None,
        v_max: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Check bus voltages against normal limits (or custom v_min, v_max).
        Gated: returns {'solved': False, 'status': 'NOT_SOLVED', ...} if power flow has not been solved.
        :return: Dict containing 'solved', 'status', 'violations', 'n_violations'.
        """
        ...

    def verify_energy_conservation(self) -> Dict[str, Any]:
        """
        Verify global grid energy conservation: Generation + Shunt Q == Load + Losses.
        Gated: returns {'solved': False, 'status': 'NOT_SOLVED', ...} if power flow has not been solved.
        :return: Dict containing 'solved', 'status', 'total_gen_mw', 'total_gen_mvar',
                 'total_load_mw', 'total_load_mvar', 'total_shunt_mw', 'total_shunt_mvar',
                 'total_loss_mw', 'total_loss_mvar', 'p_mismatch_mw', 'q_mismatch_mvar', 'conserved'.
        """
        ...

    def check_q_violations(self, bus: Optional[int] = None) -> Dict[str, Any]:
        """
        Filter and report only generator reactive power capability violations.
        Gated: returns {'solved': False, 'status': 'NOT_SOLVED', ...} if power flow has not been solved.
        :return: Dict containing 'solved', 'status', 'violations', 'n_violations'.
        """
        ...

    def clear_q_limit_switches(self) -> None:
        """Reset all PV->PQ generator clamped states back to voltage regulation mode without reloading."""
        ...

    def get_last_iteration_mismatches(self) -> Dict[str, Any]:
        """
        Retrieve final iteration active (dP) and reactive (dQ) power mismatches per bus.
        :return: Dict with 'max_dp_pu', 'max_dq_pu', 'dp' (list of float), 'dq' (list of float).
        """
        ...

    def clear_solver_cache(self) -> None:
        """Clear solver cached Y-bus factorization, warm-start state, and Q-limit states."""
        ...

    def reset_workspace(self) -> None:
        """Alias for clear_solver_cache(). Clears solver internal cache without altering case data."""
        ...

    def set_flat_start(self) -> None:
        """Reset all bus voltage magnitudes to 1.0 pu (or Vset for PV/Slack) and angles to 0 deg, and clear solver cache."""
        ...

    def has_pre_ran_results(self) -> bool:
        """Check if network buses currently contain non-flat pre-run voltage magnitudes or phase angles from file or previous solve."""
        ...

    # =========================================================================
    # 3.6 TOPOLOGY & CONNECTIVITY QUERIES (PHASE 1)
    # =========================================================================
    def get_isolated_buses(self) -> List[int]:
        """Return list of bus IDs statically flagged as isolated (Type 4)."""
        ...

    def get_unreachable_buses(self) -> List[int]:
        """Return list of bus IDs electrically unreachable from any active slack bus (islanded/disconnected)."""
        ...

    def get_island_list(self) -> List[List[int]]:
        """Return all connected electrical components (islands) of active buses, sorted by island size descending."""
        ...

    def get_bus_by_name(self, name: str) -> Optional[int]:
        """Find bus ID matching the given name (case-insensitive). Raises ValueError if ambiguous."""
        ...

    def get_bus_name(self, bus_id: int) -> str:
        """Return the name string of the given bus ID. Raises KeyError if bus not found."""
        ...

    def get_slack_bus(self) -> int:
        """Return the bus number of the primary system Slack bus (Type 3). Raises ValueError if none."""
        ...

    def get_pv_buses(self) -> List[int]:
        """Return list of all generator voltage-controlled (PV, Type 2) bus numbers."""
        ...

    def get_pq_buses(self) -> List[int]:
        """Return list of all load (PQ, Type 1) bus numbers."""
        ...

    def get_neighbors(self, bus_id: int) -> List[int]:
        """Return list of adjacent bus numbers directly connected to bus_id via in-service branches."""
        ...

    def get_branches_at_bus(self, bus_id: int) -> List[Tuple[int, int, str]]:
        """Return list of (from_bus, to_bus, ckt) tuples for all branches incident to bus_id."""
        ...

    def get_gens_at_bus(self, bus_id: int) -> List[str]:
        """Return list of generator ID strings located at bus_id."""
        ...

    def get_loads_at_bus(self, bus_id: int) -> List[str]:
        """Return list of load ID strings located at bus_id."""
        ...

    # =========================================================================
    # 4. SHORT CIRCUIT SOLVERS & RESULTS (SCS)
    # =========================================================================
    def solve_short_circuit(
        self,
        fault_bus: int,
        fault_type: str = "3phase",
        r_f: float = 0.0,
        x_f: float = 0.0,
        c_factor: float = 1.1,
        zero_seq_factor: float = 3.0,
        xd_sync: float = 0.2,
        xg_zero: float = 0.05,
        r_gen: float = 0.01,
        method: str = "iec",
        breaker_check: bool = True,
        use_pre_fault_lfa: bool = False,
    ) -> Dict[str, Any]:
        """
        Execute short circuit calculation at a single specified bus.
        :param fault_bus: Bus number where fault occurs (int).
        :param fault_type: "3phase" (or "3ph"), "slg", "ll", or "dlg".
        :param r_f: Fault resistance in ohms (default: 0.0).
        :param x_f: Fault reactance in ohms (default: 0.0).
        :param c_factor: IEC 60909 voltage factor c (default: 1.10).
        :param zero_seq_factor: Branch zero-to-positive sequence ratio X0/X1 fallback (default: 3.0).
        :param xd_sync: Generator subtransient reactance Xd'' fallback in p.u. (default: 0.20).
        :param xg_zero: Generator zero sequence reactance X0 fallback in p.u. (default: 0.05).
        :param r_gen: Generator stator resistance in p.u. (default: 0.01).
        :param method: Calculation standard: "iec" (IEC 60909:2016) or "ansi" (ANSI/IEEE C37.010).
        :param breaker_check: Automatically evaluate circuit breaker interrupting duty (default: True).
        :param use_pre_fault_lfa: Use pre-fault bus voltages from AC load flow solution (default: False).
        :return: Dictionary containing fault currents (ik_ka, ik_pu, sk_mva, ip_ka, ib_ka, ith_ka),
                 X/R ratio, Thevenin impedances (Z1, Z0), post-fault voltages, and breaker duty evaluation.
        """
        ...

    def solve_short_circuit_scan(
        self,
        method: str = "iec",
        c_factor: float = 1.1,
        zero_seq_factor: float = 3.0,
        xd_sync: float = 0.2,
        xg_zero: float = 0.05,
        r_gen: float = 0.01,
    ) -> List[Dict[str, Any]]:
        """
        Execute system-wide short circuit scan across all buses in the grid.
        Calculates both 3-Phase and Single Line-to-Ground (SLG) faults at every bus in a single native call.
        :return: List of bus fault summary records (bus_id, bus_name, base_kv, ik_3ph_ka, ik_slg_ka, sk_mva, xr_ratio, ip_ka).
        """
        ...

    def scs_bus_real(self, bus_id: int, param: str) -> float:
        """
        Query post-fault scalar parameter at `bus_id`:
        - 'VA_PU', 'VB_PU', 'VC_PU': Post-fault phase voltage magnitudes in per-unit.
        - 'VA_KV', 'VB_KV', 'VC_KV': Post-fault physical phase-to-ground voltages in kV.
        - 'VA_ANG', 'VB_ANG', 'VC_ANG': Post-fault phase angles in degrees.
        - 'V1_PU', 'V2_PU', 'V0_PU': Sequence voltage magnitudes in per-unit.
        - 'BASE_KV': Bus nominal voltage in kV.
        """
        ...

    def scs_fault_real(self, param: str) -> float:
        """
        Query scalar result parameter from the active fault solution:
        - 'IK_KA', 'IK': Initial symmetrical fault current in kA (RMS).
        - 'IK_PU': Symmetrical fault current in per-unit.
        - 'SK_MVA', 'SK': Symmetrical short circuit power in MVA.
        - 'IP_KA', 'IP': Peak making current in kA.
        - 'IB_KA', 'IB': Breaking current in kA.
        - 'ITH_KA', 'ITH': Thermal equivalent short circuit current in kA.
        - 'XR_RATIO', 'XR': System X/R ratio at fault location.
        - 'Z1_R', 'Z1_X': Thevenin positive sequence resistance/reactance in ohms.
        - 'Z0_R', 'Z0_X': Thevenin zero sequence resistance/reactance in ohms.
        - 'DUTY_PCT': Circuit breaker duty percentage.
        - 'MARGIN_PCT': Circuit breaker safety margin percentage.
        """
        ...

    def scs_fault_dict(self) -> Dict[str, Any]:
        """Return the complete dictionary of the last calculated short circuit fault."""
        ...

    def scs_brn_flow(self, f: int, t: int, ckt: str = "") -> Dict[str, Any]:
        """
        Return phase and sequence fault currents flowing through branch f-t during the active fault:
        - 'ia_ka', 'ib_ka', 'ic_ka': Three-phase currents in kA.
        - 'i_max_ka': Maximum phase current in kA.
        - 'i1_ka', 'i2_ka', 'i0_ka': Positive, negative, and zero sequence currents in kA.
        """
        ...

    def scs_gen_contrib(self, b: int, id: str = "") -> Dict[str, Any]:
        """
        Return fault current contribution from generator at bus `b`:
        - 'ia_ka', 'ib_ka', 'ic_ka': Three-phase infeed currents in kA.
        - 'i_max_ka': Maximum infeed current in kA.
        - 'i1_ka', 'i2_ka', 'i0_ka': Sequence currents in kA.
        """
        ...

    def scs_breaker_duty(self, bus: int, cb_mva: Optional[float] = None) -> Dict[str, Any]:
        """
        Evaluate switchgear and circuit breaker rating duty at specified `bus`:
        - 'bus': Bus number.
        - 'cb_mva': Rated circuit breaker capability in MVA.
        - 'interrupting_ka': Breaker interrupting capability in kA adjusted for operating voltage and K-factor.
        - 'effective_fault_ka': Symmetrical fault current adjusted for DC offset via multiplying factor MF(X/R).
        - 'duty_pct': Breaker duty percentage (effective_fault_ka / interrupting_ka * 100%).
        - 'margin_pct': Breaker safety margin (100% - duty_pct).
        - 'status': Rating evaluation status ('OK' if < 80%, 'MARGINAL' if 80-100%, 'OVERDUTY' if > 100%).
        """
        ...

    def scs_bus_data_array(self, param: str) -> List[float]:
        """Return vectorized list of post-fault values for parameter `param` across all buses."""
        ...

    # =========================================================================
    # 5. 3-PHASE UNBALANCED LOAD FLOW (3PH LFA: 3-WIRE / 4-WIRE / 5-WIRE)
    # =========================================================================
    def solve_three_phase_lfa(
        self,
        wire: Optional[str] = "4wire",
        method: Optional[str] = "fcim",
        tol: Optional[float] = 1e-5,
        max_iter: Optional[int] = 30,
        unbalance_ratio: Optional[float] = 0.15,
    ) -> Dict[str, Any]:
        """
        Execute 3-Phase Unbalanced Load Flow Analysis (ECS-3PH-001).
        :param wire: Wire configuration:
                     - "3wire": a, b, c conductors (Kron-reduced neutral, lightweight).
                     - "4wire": a, b, c, n conductors (explicit neutral conductor, neutral shift Vn).
                     - "5wire": a, b, c, n, g conductors (explicit neutral + multi-grounded earth path).
        :param method: Algorithm selection:
                       - "fcim" / "cim": True Four/Five-Conductor Current Injection Method (active).
                       - "nr": Newton-Raphson (scheduled under ECS-3PH-001 Phase 3).
                       - "bfs": Backward-Forward Sweep (scheduled under ECS-3PH-001 Phase 4).
                       - "gs": Gauss-Seidel (scheduled under ECS-3PH-001 Phase 5).
                       - "zbus": Z-Bus Impedance (scheduled under ECS-3PH-001 Phase 6).
        :param tol: Voltage mismatch convergence tolerance in p.u. (default: 1e-5).
        :param max_iter: Maximum iterations (default: 30).
        :param unbalance_ratio: Phase load imbalance ratio (default: 0.15 / 15%).
        :return: Solution status dict:
                 - 'converged': bool
                 - 'iterations': int
                 - 'max_mismatch_pu': float
                 - 'solve_time_ms': float
                 - 'wire_model': str ("3wire"|"4wire"|"5wire")
                 - 'algorithm_implemented': str ("fcim")
                 - 'algorithm_requested': str
                 - 'max_vuf_pct': float (Max Voltage Unbalance Factor % per IEC 61000-4-30)
                 - 'max_neutral_shift_v': float (Max neutral voltage shift in Volts)
                 - 'total_loss_mw': float
                 - 'total_loss_mvar': float
                 - 'total_slack_gen_p_mw': float
                 - 'total_slack_gen_q_mvar': float
                 - 'total_load_p_mw': float
                 - 'total_load_q_mvar': float
                 - 'slack_balance_error_mw': float
        """
        ...

    def three_phase_bus_results(self) -> List[Dict[str, Any]]:
        """
        Return comprehensive per-bus 3-phase results as a list of dictionaries:
        - 'bus_id', 'bus_name', 'base_kv', 'bus_type': Bus attributes.
        - 'va_mag_pu', 'va_ang_deg': Phase A voltage magnitude (pu) and angle (deg).
        - 'vb_mag_pu', 'vb_ang_deg': Phase B voltage magnitude (pu) and angle (deg).
        - 'vc_mag_pu', 'vc_ang_deg': Phase C voltage magnitude (pu) and angle (deg).
        - 'vn_mag_pu', 'vn_ang_deg', 'vn_volts': Neutral wire voltage shift (Volts).
        - 'vg_mag_pu', 'vg_ang_deg', 'vg_volts': Ground potential rise (Volts).
        - 'van_kv', 'vbn_kv', 'vcn_kv': Phase-to-Neutral voltages in kV.
        - 'vab_kv', 'vbc_kv', 'vca_kv': Phase-to-Phase voltages in kV.
        - 'v0_mag_pu', 'v1_mag_pu', 'v2_mag_pu': Sequence components (Zero, Positive, Negative).
        - 'vuf_pct': Voltage Unbalance Factor (|V2|/|V1| * 100% per IEC 61000-4-30).
        - 'pvur_pct': Phase Voltage Unbalance Rate (max|Vp - Vavg|/Vavg * 100% per IEEE 1159).
        - 'zsvu_pct': Zero Sequence Voltage Unbalance (|V0|/|V1| * 100%).
        - 'pa_mw', 'qa_mvar', 'pb_mw', 'qb_mvar', 'pc_mw', 'qc_mvar': Per-phase powers.
        - 'p_total_mw', 'q_total_mvar': Total active and reactive bus injection.
        """
        ...

    def three_phase_branch_results(self) -> List[Dict[str, Any]]:
        """
        Return comprehensive per-branch 3-phase flow and loss results:
        - 'from_bus', 'to_bus', 'ckt': Branch terminals and circuit ID.
        - 'ia_mag_a', 'ia_ang_deg': Phase A current (Amperes) and angle.
        - 'ib_mag_a', 'ib_ang_deg': Phase B current (Amperes) and angle.
        - 'ic_mag_a', 'ic_ang_deg': Phase C current (Amperes) and angle.
        - 'in_mag_a', 'in_ang_deg': Neutral conductor current (Amperes).
        - 'ig_mag_a', 'ig_ang_deg': Earth/ground return path current (Amperes).
        - 'ploss_a_kw', 'ploss_b_kw', 'ploss_c_kw': Phase conductor losses in kW.
        - 'ploss_n_kw': Neutral wire Joule heating loss in kW.
        - 'ploss_g_kw': Earth return dissipation loss in kW.
        - 'ploss_total_kw', 'qloss_total_kvar': Total branch power losses.
        - 'p_from_total_mw', 'q_from_total_mvar': Complex power entering from-terminal.
        - 'p_to_total_mw', 'q_to_total_mvar': Complex power entering to-terminal.
        """
        ...

    def three_phase_bus_voltage(self, bus_id: int) -> Dict[str, Any]:
        """Return 3-phase voltage and unbalance metrics for a specific `bus_id`."""
        ...

    # =========================================================================
    # 7. ARC FLASH HAZARD ANALYSIS (IEEE 1584-2018 / NFPA 70E / RALPH LEE)
    # =========================================================================
    def solve_arc_flash(
        self,
        bus: int,
        config: str = "vcb",
        gap_mm: Optional[float] = None,
        working_dist_mm: Optional[float] = None,
        width_mm: Optional[float] = None,
        height_mm: Optional[float] = None,
        depth_mm: Optional[float] = None,
        clearing_time_arc: float = 0.1,
        clearing_time_arc_min: float = 0.1,
        bolted_fault_ka: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Execute Arc Flash Hazard Analysis for a single substation bus.
        Complies with IEEE 1584-2018, NFPA 70E-2024, CSA Z462, and Ralph Lee (>15 kV).

        :param bus: Target substation bus number.
        :param config: Electrode configuration: 'VCB', 'VCBB', 'HCB', 'VOA', 'HOA'.
        :param gap_mm: Conductor electrode gap in mm (defaults applied if None).
        :param working_dist_mm: Distance from arc to worker in mm (defaults applied if None).
        :param width_mm: Enclosure width in mm (IEEE typical defaults applied if None).
        :param height_mm: Enclosure height in mm (IEEE typical defaults applied if None).
        :param depth_mm: Enclosure depth in mm (IEEE typical defaults applied if None).
        :param clearing_time_arc: Protective device clearing time at maximum arcing current I_arc in seconds.
        :param clearing_time_arc_min: Protective device clearing time at reduced arcing current I_arc,min in seconds (Trap 1).
        :param bolted_fault_ka: Optional prospective bolted fault current in kA. If None, runs SCS 3-phase fault solver.
        :return: Arc flash results dictionary:
                 - 'fault_bus': int
                 - 'bus_name': str
                 - 'base_kv': float
                 - 'bolted_fault_current_ka': float
                 - 'electrode_config': str
                 - 'gap_mm', 'working_distance_mm', 'working_distance_in': float
                 - 'enclosure_width_mm', 'enclosure_height_mm', 'enclosure_cf': float
                 - 'arcing_current_ka', 'arcing_current_min_ka': float
                 - 'clearing_time_arc_sec', 'clearing_time_arc_min_sec': float
                 - 'incident_energy_arc_cal_cm2', 'incident_energy_min_cal_cm2': float
                 - 'incident_energy_cal_cm2', 'incident_energy_j_cm2': float (governing worst-case)
                 - 'arc_flash_boundary_mm', 'arc_flash_boundary_in': float
                 - 'ppe_category': int (0 to 4, 5 for DANGER >40 cal/cm²)
                 - 'ppe_description': str (NFPA 70E required PPE gear)
                 - 'standard_used': str ('IEEE 1584-2018 / NFPA 70E-2024' or 'Ralph Lee Theoretical Radiated Model (>15 kV)')
                 - 'governing_case': str ('Max Current (I_arc)' or 'Reduced Current (I_arc_min)')
        """
        ...

    def solve_arc_flash_scan(
        self,
        config: str = "vcb",
        gap_mm: Optional[float] = None,
        working_dist_mm: Optional[float] = None,
        width_mm: Optional[float] = None,
        height_mm: Optional[float] = None,
        depth_mm: Optional[float] = None,
        clearing_time_arc: float = 0.1,
        clearing_time_arc_min: float = 0.1,
    ) -> List[Dict[str, Any]]:
        """
        Execute system-wide Arc Flash Hazard scan across all energized buses.
        Returns a list of arc flash summary dictionaries for every bus.
        """
        ...

    # =========================================================================
    # 8. HARMONIC ANALYSIS & RESONANCE FREQUENCY SCAN (IEEE 519-2022 / IEC 61000)
    # =========================================================================
    def add_harmonic_source(
        self,
        bus: int,
        name: str,
        phase: str = "3PH",
        i_fund_amps: float = 100.0,
        ang_deg: float = 0.0,
        spectrum_type: str = "custom",
        norton_r_pu: Optional[float] = None,
        norton_x_pu: Optional[float] = None,
    ) -> None:
        """
        Configure a harmonic current source at a designated bus.
        :param bus: Bus number where harmonic device is connected.
        :param name: Unique identifier name for the source.
        :param phase: '3PH' (balanced positive/negative sequence), 'A', 'B', or 'C'.
        :param i_fund_amps: Fundamental current magnitude in Amperes.
        :param ang_deg: Fundamental current phase angle in degrees.
        :param spectrum_type: Built-in spectrum ('standard_6_pulse', 'standard_12_pulse', 'pwm_inverter', 'arc_furnace') or 'custom'.
        :param norton_r_pu: Optional Norton parallel resistance in per-unit for Solver 2 (INC).
        :param norton_x_pu: Optional Norton parallel reactance in per-unit for Solver 2 (INC).
        """
        ...

    def add_harmonic_order(
        self,
        name: str,
        order: int,
        current_amps: float,
        angle_deg: float = 0.0,
    ) -> None:
        """Add an individual harmonic order to an existing custom harmonic source."""
        ...

    def set_harmonic_spectrum(
        self,
        name: str,
        orders: List[int],
        amps: List[float],
        angles: Optional[List[float]] = None,
    ) -> None:
        """Set or replace the full spectrum for a source using parallel lists of orders, amps, and optional angles."""
        ...

    def add_harmonic_filter(
        self,
        bus: int,
        name: str,
        filter_type: str = "single_tuned",
        tuning_order: float = 4.85,
        q_factor: float = 40.0,
        mvar_rating: float = 2.5,
        status: int = 1,
    ) -> None:
        """
        Add a harmonic mitigation filter (Single-Tuned Notch or High-Pass) at a bus.
        :param bus: Bus number.
        :param name: Unique filter name.
        :param filter_type: 'single_tuned' (notch) or 'high_pass'.
        :param tuning_order: Harmonic tuning order (e.g. 4.85 for 5th harmonic notch).
        :param q_factor: Quality factor Q = X0 / R (typically 30-60).
        :param mvar_rating: Effective capacitive reactive power rating in MVAr at fundamental frequency.
        :param status: 1 for active / in-service, 0 for out-of-service.
        """
        ...

    def clear_harmonic_sources(self) -> None:
        """Remove all defined harmonic sources."""
        ...

    def clear_harmonic_filters(self) -> None:
        """Remove all configured harmonic filters."""
        ...

    def solve_harmonics(
        self,
        solver: str = "cim",
        max_order: int = 50,
        skin_effect: bool = True,
        pcc_bus: Optional[int] = None,
        pcc_kv: Optional[float] = None,
        isc_il_ratio: float = 35.0,
        standard: str = "ieee519",
        max_iter: int = 30,
        tol: float = 1e-8,
        use_lfa_voltage: bool = True,
    ) -> Dict[str, Any]:
        """
        Execute multi-order harmonic power flow and compliance evaluation.
        :param solver: 'cim' (Primary Decoupled Current Injection) or 'inc' (Iterative Norton Compensation).
        :param max_order: Maximum harmonic order to simulate (default 50).
        :param skin_effect: Enable frequency-dependent line skin effect and transformer eddy loss scaling.
        :param pcc_bus: Point of Common Coupling bus number for IEEE 519 compliance assessment.
        :param pcc_kv: Base voltage at PCC bus in kV (auto-detected if None).
        :param isc_il_ratio: Short-circuit ratio Isc / IL for IEEE 519 Table 2 current limits.
        :param standard: Compliance standard: 'ieee519' (IEEE 519-2022 default), 'iec61000' (IEC 61000-3-6), or 'ukg55' (UK ER G5/5).
        :param max_iter: Maximum iterations for Solver 2 (INC).
        :param tol: Convergence tolerance in per-unit mismatch.
        :param use_lfa_voltage: True for Option A (LFA-Dependent, uses pre-fault converged LFA V1 & angles);
                                False for Option B (Flat-Start standalone, V1 = 1.0 pu / 0 deg).
        :return: Harmonic study summary dictionary:
                 - 'converged': bool
                 - 'solver_used': str
                 - 'operating_mode': str ('LFA-Dependent' or 'Flat-Start')
                 - 'iterations': int
                 - 'max_order': int
                 - 'execution_time_ms': float
                 - 'overall_ieee519_pass': bool (True if both voltage and current comply)
                 - 'overall_thd_pass': bool (Voltage THD & IHD compliance)
                 - 'overall_tdd_pass': bool (Current TDD compliance)
                 - 'tdd_limit_pct': float (Applicable TDD limit percentage)
                 - 'pcc_thd_v_pct': float
                 - 'pcc_tdd_i_pct': float
                 - 'bus_count': int
                 - 'branch_count': int
        """
        ...

    def solve_frequency_scan(
        self,
        buses: Optional[List[int]] = None,
        start_hz: float = 60.0,
        end_hz: float = 3000.0,
        step_hz: float = 10.0,
        inject_amp: float = 1.0,
        use_lfa_voltage: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Execute high-performance multi-threaded parallel frequency scan (Solver 4) using Rayon.
        Calculates driving-point impedance Z(f) across target buses and detects parallel/series resonances.
        :param buses: List of bus numbers to scan (defaults to all buses if None or empty).
        :param start_hz: Scan frequency start in Hz (default 60.0).
        :param end_hz: Scan frequency end in Hz (default 3000.0).
        :param step_hz: Frequency resolution step in Hz (default 10.0).
        :param inject_amp: Test injection current magnitude in Amperes.
        :param use_lfa_voltage: Operating mode for load equivalent admittance calculation.
        :return: List of detected resonance points dictionaries (bus_id, freq_hz, order, res_type, z_peak_ohm, severity).
        """
        ...

    def harmonic_bus_results(self) -> List[Dict[str, Any]]:
        """
        Retrieve per-bus harmonic results for the last solved harmonic study:
        Contains: bus_id, bus_name, base_kv, v_fund_kv, v_fund_pu, thd_v_pct,
                  max_ihd_v_pct, max_ihd_order, ieee519_status, ieee519_limit_pct,
                  and v_harmonics_kv dictionary {order: kv}.
        """
        ...

    def harmonic_branch_results(self) -> List[Dict[str, Any]]:
        """
        Retrieve per-branch harmonic current flows, losses, and transformer thermal derating:
        Contains: from_bus, to_bus, circuit_id, i_fund_amps, thd_i_pct, tdd_i_pct,
                  k_factor (IEEE C57.110), loss_fund_kw, loss_harmonic_kw, loss_total_kw,
                  and i_harmonics_amps dictionary {order: amps}.
        """
        ...

    def harmonic_detected_resonances(self) -> List[Dict[str, Any]]:
        """Retrieve list of all detected parallel and series resonance points from the last frequency scan."""
        ...

    def harmonic_scan_profile(self, bus_id: int) -> List[Dict[str, Any]]:
        """
        Retrieve driving-point impedance frequency spectrum profile for a specific bus.
        Returns a list of frequency data points with:
        freq_hz, order, z_mag_ohm, z_ang_deg, r_ohm, x_ohm.
        """
        ...




"""
DevEN Command Line Interface & Interactive Help System
======================================================
Provides CLI tools, study execution, documentation server,
and full API overview for DevEN power system simulation suite.
"""

import sys
import os
import argparse
import webbrowser
import http.server
import socketserver
import threading
import time

def get_docs_dir() -> str:
    """Returns absolute path to the bundled documentation directory."""
    pkg_root = os.path.dirname(os.path.abspath(__file__))
    docs_dir = os.path.join(pkg_root, "docs")
    return docs_dir

def get_docs_index_path() -> str:
    """Returns absolute path to index.html."""
    return os.path.join(get_docs_dir(), "index.html")

def print_help_banner():
    """Prints comprehensive DevEN API reference and documentation instructions."""
    docs_path = get_docs_index_path()
    docs_uri = f"file:///{docs_path.replace(os.sep, '/')}"
    
    help_text = f"""
================================================================================
  DevEN - High-Performance Power System Simulation Suite (v1.0.0)
================================================================================

DevEN is an ultra-fast, scriptable AC power flow and grid analysis engine
featuring native C/C++ compiled mathematical kernels (.pyd).

================================================================================
[*] FREE TIER & LICENSING
================================================================================
  - Free Tier Limit: 100 Buses (Mathematically accepts up to 101 buses without license).
  - Unlimited Free Simulations for all 4 core studies (LFA, SCS, CA, TS-LFA).
  - For systems > 101 buses, a commercial .pyd license file is required.
  - Commercial License Contact: devarajedeva2002@gmail.com
  - How to set commercial license:
      sess.set_license("path/to/deven_license.pyd")
      deven.set_license("path/to/deven_license.pyd")

================================================================================
[*] INTERACTIVE WEB DOCUMENTATION (GitHub Primer Design)
================================================================================
  DevEN includes full interactive web documentation with dedicated side tabs
  for each study's API, parameter tables, formulas, and runnable examples.

  - Direct File Path : {docs_path}
  - Browser URI      : {docs_uri}
  - Launch Docs Server:
      deven docs                   (Starts local server & opens browser)
      deven docs --port 8080       (Custom port)

================================================================================
[*] CORE PYTHON APIS (All 4 Core Studies)
================================================================================

1. LOAD FLOW ANALYSIS (LFA)
   >>> import deven
   >>> sess = deven.DevENSession()
   >>> sess.load_case("case.py")  # or .raw, .dgs, .dat
   >>> res = sess.run_lfa(method="nr", tol=1e-6, max_iter=20, v_init="flat")
   Parameters:
     method           : 'nr' (Newton-Raphson), 'fdlf' (Fast Decoupled), 'gs'
     tol              : Convergence tolerance in p.u. (default: 1e-6)
     max_iter         : Maximum iterations (default: 20)
     v_init           : 'flat' (1.0 p.u.) or 'previous'
     enforce_q_limits : bool (default: True)
   Returns:
     {{'converged': bool, 'iterations': int, 'time_sec': float,
      'buses': {{...}}, 'branches': {{...}}, 'summary': {{...}}}}

2. SHORT CIRCUIT STUDIES (SCS - IEC 60909 / VDE 0102)
   >>> res = sess.run_scs(fault_bus=1, method="iec", fault_type="3phase")
   Parameters:
     fault_bus   : Bus ID or None (evaluates all buses if None)
     method      : 'iec' (IEC 60909) or 'complete'
     fault_type  : '3phase', '1phase'/'lg', 'll', 'llg'
     c_factor    : Voltage factor (default: 1.05)
     duration_s  : Fault clearing duration in seconds (default: 0.1)
   Calculates:
     Initial current (Ik"), peak current (ip), breaking current (Ib),
     thermal equivalent current (Ith), and fault power (Sk").

3. CONTINGENCY ANALYSIS (CA - N-1 / N-2)
   >>> res = sess.run_ca(scope="all_lines", rank_by="overload", max_loading=100.0)
   Parameters:
     scope       : 'all_lines', 'all_transformers', 'all_branches'
     rank_by     : 'overload', 'pi' (performance index), 'voltage_drop'
     max_loading : Thermal overload threshold percentage (default: 100.0)
     n_threads   : Number of parallel worker threads
   Outputs:
     Evaluates branch tripping, detects topological islands, and ranks overloads.

4. TIME-SERIES LOAD FLOW (TS-LFA)
   >>> res = sess.run_timeseries(steps=24, step_size_s=3600.0)
   Parameters:
     steps        : Number of time steps (default: 24)
     step_size_s  : Duration per step in seconds (3600 = 1 hr, 900 = 15 min)
     profiles     : Dict of load / renewable generation variation profiles
     progress_bar : bool (default: True)
   Outputs:
     Sequential multi-period AC power flows and cumulative energy losses (MWh).

================================================================================
[*] FILE INGESTION & CONVERTERS (.raw, .dgs, .dat, .py, .sql)
================================================================================
  >>> grid = deven.load_network("network.raw") # PSS/E Raw
  >>> grid = deven.load_network("network.dgs") # PowerFactory DGS
  >>> grid = deven.load_network("network.dat") # IEEE Common Format
  >>> grid = deven.load_network("network.py")  # Python Network Definition
  >>> grid = deven.load_network("network.sql") # SQLite Grid Database

================================================================================
[*] CLI COMMANDS SUMMARY
================================================================================
  deven --help, -h               Show this complete API guide and docs link
  deven docs [--port PORT]       Start local documentation web server & open browser
  deven info                     Check Python runtime and compiled .pyd status
  deven run <file> [--study ...] Execute power system analysis from command line
================================================================================
"""
    print(help_text)

def serve_docs(port: int = 8080, open_browser: bool = True):
    """Starts a local HTTP server serving DevEN documentation and opens browser."""
    docs_dir = get_docs_dir()
    index_file = get_docs_index_path()
    
    if not os.path.exists(index_file):
        print(f"[!] Error: Documentation file not found at: {index_file}")
        sys.exit(1)

    # Change working directory to docs_dir for simple HTTP serving
    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=docs_dir, **kwargs)
        def log_message(self, format, *args):
            # Suppress normal access logs to keep terminal clean
            pass

    # Find open port
    active_port = port
    server = None
    for p in range(port, port + 20):
        try:
            server = socketserver.TCPServer(("127.0.0.1", p), QuietHandler)
            active_port = p
            break
        except OSError:
            continue

    if server is None:
        print(f"[!] Error: Could not bind HTTP server on ports {port}-{port+20}.")
        print(f"[*] You can view documentation directly at: file:///{index_file.replace(os.sep, '/')}")
        return

    url = f"http://127.0.0.1:{active_port}/index.html"
    file_uri = f"file:///{index_file.replace(os.sep, '/')}"

    print("=" * 80)
    print("  DevEN Interactive Web Documentation Server")
    print("=" * 80)
    print(f"[*] Local Web URL  : {url}")
    print(f"[*] Direct File URI: {file_uri}")
    print("[*] Serving documentation with GitHub Primer UI & Sidebar Study Tabs.")
    print("[*] Press Ctrl+C in terminal to stop server.")
    print("=" * 80)

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception as e:
            print(f"[*] Note: Please open {url} manually in your browser.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Stopping documentation server. Goodbye!")
        server.server_close()

def print_info():
    """Prints diagnostic information about runtime environment and compiled .pyd modules."""
    import platform
    print("=" * 80)
    print("  DevEN System & Runtime Information")
    print("=" * 80)
    print(f"DevEN Version   : 1.0.0")
    print(f"Python Version  : {platform.python_version()} ({platform.architecture()[0]})")
    print(f"Python Executable: {sys.executable}")
    print(f"Operating System: {platform.system()} {platform.release()} ({platform.machine()})")
    
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    print(f"Package Path    : {pkg_dir}")
    print(f"Free Tier Limit : 100 Buses (Accepts up to 101 buses without license)")
    print(f"Commercial Email: devarajedeva2002@gmail.com")
    print("-" * 80)
    print("Compiled Binary Engines (.pyd status):")
    
    # Check engines
    engines_dir = os.path.join(pkg_dir, "engines")
    utils_dir = os.path.join(pkg_dir, "utils")
    
    for folder, name in [(engines_dir, "Engines"), (utils_dir, "Utilities")]:
        if os.path.exists(folder):
            files = [f for f in os.listdir(folder) if f.endswith(".pyd")]
            print(f"  {name} ({len(files)} compiled .pyd modules):")
            for f in sorted(files):
                print(f"    - {f}")
        else:
            print(f"  {name}: Directory not found")
    print("=" * 80)

def run_study(case_path: str, study: str = "lfa", fault_bus: int = 1):
    """Executes a study directly from CLI."""
    if not os.path.exists(case_path):
        print(f"[!] Error: File not found: {case_path}")
        sys.exit(1)
        
    try:
        from deven.core.deven_api import DevENSession
    except ImportError:
        import deven
        DevENSession = deven.DevENSession

    print(f"[*] Loading network case: {case_path}")
    sess = DevENSession()
    sess.load_case(case_path)
    
    study = study.lower()
    if study == "lfa":
        print("[*] Running Newton-Raphson Load Flow Analysis...")
        res = sess.run_lfa()
        print(f"[+] LFA Result: Converged = {res['converged']} (Iterations: {res['iterations']})")
    elif study == "scs":
        print(f"[*] Running IEC 60909 Short Circuit at Bus {fault_bus}...")
        res = sess.run_scs(fault_bus=fault_bus)
        print(f"[+] SCS Result: Fault Current = {res.get('fault_current_ka', 0.0):.3f} kA")
    elif study == "ca":
        print("[*] Running N-1 Contingency Analysis...")
        res = sess.run_ca()
        print(f"[+] CA Result: Evaluated {len(res.get('contingencies', []))} contingencies.")
    elif study in ("ts", "timeseries"):
        print("[*] Running 24-step Time Series simulation...")
        res = sess.run_timeseries(steps=24)
        print(f"[+] TS Result: Total Energy Loss = {res.get('total_loss_mwh', 0.0):.2f} MWh")
    else:
        print(f"[!] Unknown study: '{study}'. Choose from: lfa, scs, ca, ts")

def main():
    """Main CLI entrypoint."""
    if len(sys.argv) == 1 or sys.argv[1] in ("--help", "-h", "help"):
        print_help_banner()
        return

    cmd = sys.argv[1].lower()

    if cmd in ("docs", "--docs", "serve", "--serve"):
        parser = argparse.ArgumentParser(description="DevEN Documentation Server")
        parser.add_argument("--port", type=int, default=8080, help="HTTP server port (default: 8080)")
        parser.add_argument("--no-browser", action="store_true", help="Do not automatically launch web browser")
        args, _ = parser.parse_known_args(sys.argv[2:])
        serve_docs(port=args.port, open_browser=not args.no_browser)

    elif cmd in ("info", "--info", "--version", "-v"):
        print_info()

    elif cmd == "run":
        if len(sys.argv) < 3:
            print("Usage: deven run <case_path> [--study lfa|scs|ca|ts] [--fault-bus <id>]")
            sys.exit(1)
        case_path = sys.argv[2]
        parser = argparse.ArgumentParser(description="DevEN Study Runner")
        parser.add_argument("--study", type=str, default="lfa", choices=["lfa", "scs", "ca", "ts"])
        parser.add_argument("--fault-bus", type=int, default=1)
        args, _ = parser.parse_known_args(sys.argv[3:])
        run_study(case_path=case_path, study=args.study, fault_bus=args.fault_bus)

    else:
        print(f"[!] Unrecognized command: '{cmd}'")
        print("Run 'deven --help' to see all available commands and API references.")

if __name__ == "__main__":
    main()

"""
DevEN CLI & Package Entrypoint
Invoked via `devenpy ...` or `python -m devenpy ...`
"""

import sys
import os
import argparse
from pathlib import Path

import devenpy


def print_help_banner():
    banner = """
================================================================================
 DevEN (devenpy) — Power system study engine
 Made in India from Bengaluru · https://github.com/DevEN-PS/DevEN
================================================================================

USAGE:
  devenpy [OPTIONS] [FILE]
  python -m devenpy [OPTIONS] [FILE]

INTERACTIVE WEB DOCUMENTATION:
  To open the complete single-file interactive documentation portal on your
  web browser via an automated zero-dependency local web server:

    devenpy --docs
    or:
    python -m devenpy --docs

  Options:
    --docs, -d             Launch local web server and open docs in browser
    --port <number>        Local server port (default: 8080)

EXPORT EDITABLE STUDY RUNNERS & CASES:
  To export all 6 standalone study runner scripts (LFA, SCS, HA, 3PH, AF, BC),
  universal extended I/O parser (deven_io.py), and benchmark grid cases
  into your current folder so you can edit and run them:

    devenpy --export-runners [target_directory]
    or:
    python -m devenpy --export-runners [target_directory]

  * Note: If [target_directory] is omitted, files are pasted directly into your
    active terminal working directory!

FIRST PREFERENCE FORMAT:
  ★ PSS/E RAWX (.rawx) [First Preference]
  Recommended standard: Modern schema-validated XML/JSON format with high
  numerical precision and structured definitions.

STANDALONE SIMULATION STUDIES:
  devenpy cases/bench.rawx                         AC Load Flow (Newton-Raphson)
  devenpy cases/case14.raw --format out -o out.txt PSS/E columnar report
  devenpy cases/bench.rawx --study scs             Short Circuit Study (IEC 60909)
  devenpy cases/bench.rawx --scan                  Full system-wide fault scan

CLI OPTIONS:
  --study <lfa|scs>        Study type: lfa (Load Flow) or scs (Short Circuit)
  --method, -m <name>      LFA: nr, fdlf, dc, gs; SCS: iec, ansi
  --tol, -t <float>        Convergence mismatch tolerance (default: 1e-5)
  --max-iter, -i <int>     Maximum iterations limit (default: 30)
  --show-q-limits          Display indented [DevEN Q-LIMIT] lines during solve
  --flat-start             Force 1.0 pu / 0.0 deg flat start
  --fault-bus <int>        Target bus for short-circuit study
  --fault-type <type>      Short-circuit fault: 3phase, slg, ll, dlg
  --scan                   Execute full system-wide fault scan across all buses
  --format <out|json|csv>  Report format: out (columnar), json, csv
  -o, --output <path>      Output file path (default: stdout)
  --version, -v            Display DevEN engine version
  --help, -h               Show this comprehensive help manual
================================================================================
"""
    print(banner)


def main():
    args = sys.argv[1:]

    if not args or "-h" in args or "--help" in args or "help" in args:
        print_help_banner()
        return

    if "--version" in args or "-v" in args:
        print(f"DevEN (devenpy) v1.0.0 — Power system study engine (Made in India from Bengaluru)")
        return

    # Check for --docs
    if "--docs" in args or "-d" in args or "docs" in args:
        port = 8080
        if "--port" in args:
            idx = args.index("--port")
            if idx + 1 < len(args):
                try:
                    port = int(args[idx + 1])
                except ValueError:
                    pass
        devenpy.open_docs(port=port)
        return

    # Check for --export-runners
    if "--export-runners" in args or "-e" in args or "export" in args:
        dest = None
        for i, a in enumerate(args):
            if a in ("--export-runners", "-e", "export") and i + 1 < len(args) and not args[i+1].startswith("-"):
                dest = args[i+1]
                break
        devenpy.export_runners(destination=dest)
        return

    # Direct execution of simulations using Python + devenpy.PyCase
    file_path = None
    study = "lfa"
    method = None
    tol = 1e-5
    max_iter = 30
    flat_start = False
    show_q_limits = False
    fault_bus = 1
    fault_type = "3phase"
    scan = False
    fmt = "out"
    output_path = None

    i = 0
    while i < len(args):
        a = args[i]
        if a == "--study" and i + 1 < len(args):
            study = args[i+1].lower()
            i += 2
        elif a in ("--method", "-m") and i + 1 < len(args):
            method = args[i+1].lower()
            i += 2
        elif a in ("--tol", "-t") and i + 1 < len(args):
            tol = float(args[i+1])
            i += 2
        elif a in ("--max-iter", "-i") and i + 1 < len(args):
            max_iter = int(args[i+1])
            i += 2
        elif a == "--flat-start":
            flat_start = True
            i += 1
        elif a == "--show-q-limits":
            show_q_limits = True
            i += 1
        elif a == "--fault-bus" and i + 1 < len(args):
            fault_bus = int(args[i+1])
            i += 2
        elif a == "--fault-type" and i + 1 < len(args):
            fault_type = args[i+1].lower()
            i += 2
        elif a == "--scan":
            scan = True
            i += 1
        elif a == "--format" and i + 1 < len(args):
            fmt = args[i+1].lower()
            i += 2
        elif a in ("-o", "--output") and i + 1 < len(args):
            output_path = args[i+1]
            i += 2
        elif not a.startswith("-") and file_path is None:
            file_path = a
            i += 1
        else:
            i += 1

    if not file_path:
        print("[DevEN Error] No grid file specified.")
        print_help_banner()
        return

    p = Path(file_path)
    if not p.exists():
        print(f"[DevEN Error] File not found: {p}")
        return

    case = devenpy.PyCase()
    ext = p.suffix.lower()
    if ext == ".rawx":
        case.load_rawx(str(p))
    elif ext == ".raw":
        case.load_raw(str(p))
    elif ext == ".deven":
        case.load_deven(str(p))
    elif ext in (".m", ".cdf", ".xlsx", ".xls", ".aux", ".def", ".xml"):
        try:
            import devenpy.deven_io as deven_io
            case = deven_io.load_grid_file(str(p))
        except Exception as e:
            print(f"[DevEN Error] Extended I/O failed: {e}")
            return
    else:
        case.load(str(p))

    if study == "scs":
        if scan:
            sc_method = method or "iec"
            res = case.solve_short_circuit_scan(method=sc_method)
            print(f"[DevEN SCS Scan] Evaluated {len(res)} buses (Method: {sc_method.upper()})")
            for r in res[:15]:
                print(f"  Bus {r['bus_id']:<6} {r.get('bus_name',''):<14} Ik\" = {r['ik_3ph_ka']:.3f} kA  ip = {r.get('ip_3ph_ka',0.0):.3f} kA  Sk\" = {r.get('sk_3ph_mva',0.0):.1f} MVA")
        else:
            sc_method = method or "iec"
            res = case.solve_short_circuit(fault_bus=fault_bus, fault_type=fault_type, method=sc_method)
            print(f"[DevEN SCS] Fault at Bus {fault_bus} ({fault_type.upper()} - {sc_method.upper()}):")
            print(f"  Initial Symmetrical Ik\" : {res['ik_ka']:.3f} kA")
            print(f"  Peak Asymmetrical ip   : {res.get('ip_ka', 0.0):.3f} kA")
            print(f"  Short Circuit Power Sk\" : {res.get('sk_mva', 0.0):.1f} MVA")
            print(f"  Equivalent X/R Ratio   : {res.get('xr_ratio', 0.0):.2f}")
    else:  # LFA
        lf_method = method or "nr"
        st = case.solve_load_flow(
            method=lf_method,
            tol=tol,
            max_iter=max_iter,
            flat_start=flat_start,
            show_q_limits=show_q_limits,
        )
        print(f"[DevEN LFA] Method: {lf_method.upper()} | Converged: {st.get('converged', False)} in {st.get('iterations', 0)} iters (Tolerance: {tol:.1e})")

        if output_path:
            if fmt == "json":
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(case.report_json())
                print(f"Report exported to JSON: {output_path}")
            elif fmt == "out":
                case.write_out(output_path)
                print(f"Report exported to OUT: {output_path}")
            elif fmt == "kcl":
                case.kcl_report(output_path)
                print(f"Report exported to KCL: {output_path}")


if __name__ == "__main__":
    main()

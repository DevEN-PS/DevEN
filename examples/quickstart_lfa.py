"""
DevEN Load Flow Analysis (LFA) Quickstart Example
=================================================
Runs Newton-Raphson power flow on a case model using deven_nr solver.
"""

import sys
import os

# Allow running directly from local repo clone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deven import DevENSession

def main():
    sess = DevENSession()
    
    default_case = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bench.py")
    case_path = sys.argv[1] if len(sys.argv) > 1 else default_case
    print(f"Loading case: {case_path}")
    sess.load_case(case_path)
    
    print("\n--- Running Load Flow Analysis (LFA) ---")
    res = sess.run_lfa(
        method="deven_nr",
        tol=1e-5,
        max_iter=30,
        to_terminal=True
    )
    
    print("\n--- Summary Results ---")
    print(f"Converged   : {res.get('converged')}")
    print(f"Iterations  : {res.get('iterations')}")
    print(f"Engine      : {res.get('engine')}")

if __name__ == "__main__":
    main()

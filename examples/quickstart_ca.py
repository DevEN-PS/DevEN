"""
DevEN Contingency Analysis (CA) Quickstart Example
==================================================
Runs contingency simulations with specified lines and transformers out of service.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deven import DevENSession

def main():
    sess = DevENSession()
    
    default_case = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bench.py")
    case_path = sys.argv[1] if len(sys.argv) > 1 else default_case
    print(f"Loading case: {case_path}")
    sess.load_case(case_path)
    
    print("\n--- Running Contingency Analysis (CA) ---")
    res = sess.run_ca(
        scope="selected",
        lines="1,2,3,4",
        engine="deven_nr",
        tol=1e-5,
        max_iter=30,
        to_terminal=True
    )
    
    print("\n--- Summary Results ---")
    print(f"Status: {res.get('status')}")
    print(f"Scope : {res.get('scope')}")

if __name__ == "__main__":
    main()

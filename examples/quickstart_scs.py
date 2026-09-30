"""
DevEN Short Circuit Studies (SCS) Quickstart Example
====================================================
Runs standard-compliant IEC 60909 fault calculations across network buses.
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
    
    print("\n--- Running Short Circuit Studies (IEC 60909) ---")
    res = sess.run_scs(
        method="iec",
        to_terminal=True
    )
    
    print("\n--- Summary Results ---")
    print(f"Buses Calculated: {res.get('buses_calculated')}")
    print(f"Status          : {res.get('status')}")

if __name__ == "__main__":
    main()

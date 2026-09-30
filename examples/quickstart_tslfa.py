"""
DevEN Time Series Load Flow (TS-LFA) Quickstart Example
=======================================================
Runs 24-hour time series power flow with hourly steps.
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
    
    print("\n--- Running 24-Hour Time Series Load Flow ---")
    res = sess.run_timeseries(
        duration=24.0,
        dur_unit="Hours",
        step_size=1.0,
        step_unit="Hours",
        engine="deven_nr",
        tol=1e-5,
        max_iter=30,
        to_terminal=True
    )
    
    print("\n--- Summary Results ---")
    print(f"Status         : {res.get('status')}")
    print(f"Steps Completed: {res.get('steps_completed')}")

if __name__ == "__main__":
    main()

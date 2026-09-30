"""
DevEN DAT Format Converter Module
=================================
Independent converter engine for parsing standard DAT0 / DAT power flow and short circuit files.
"""

import os
import sys

cur_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(cur_dir)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from engines.others_converter import parse_dat0, parse_sc_dat0, convert_dat0_to_py

__all__ = ['parse_dat0', 'parse_sc_dat0', 'convert_dat0_to_py']

if __name__ == '__main__':
    if len(sys.argv) > 1:
        sec = sys.argv[2] if len(sys.argv) > 2 else None
        out = convert_dat0_to_py(sys.argv[1], secondary_dat0_path=sec)
        print(f"Converted DAT file to: {out}")
    else:
        print("Usage: python -m engines.dat_converter <input.dat0> [secondary.dat0]")

"""
DevEN RAW Format Converter Module
=================================
Independent converter engine for parsing standard RAW power network models.
"""

import os
import sys

cur_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(cur_dir)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from engines.psse_converter import parse_raw, convert_psse_raw_to_py as convert_raw_to_py

__all__ = ['parse_raw', 'convert_raw_to_py']

if __name__ == '__main__':
    if len(sys.argv) > 1:
        out = convert_raw_to_py(sys.argv[1])
        print(f"Converted RAW file to: {out}")
    else:
        print("Usage: python -m engines.raw_converter <input.raw>")

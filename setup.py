import os
import sys
from setuptools import setup, find_packages, Extension

# Check if Cython is available for compiling sources to binary extensions
try:
    from Cython.Build import cythonize
    USE_CYTHON = True
except ImportError:
    USE_CYTHON = False

# Modules targeted for binary compilation (.pyd on Windows / .so on POSIX)
MODULES_TO_COMPILE = [
    ("deven.engines.power_flow_engine", "deven/engines/power_flow_engine.py"),
    ("deven.engines.custom_power_flow_solver", "deven/engines/custom_power_flow_solver.py"),
    ("deven.engines.andes_solver", "deven/engines/andes_solver.py"),
    ("deven.engines.short_circuit_solver", "deven/engines/short_circuit_solver.py"),
    ("deven.engines.contingency_batch", "deven/engines/contingency_batch.py"),
    ("deven.engines.contingency_runner", "deven/engines/contingency_runner.py"),
    ("deven.engines.time_series_engine", "deven/engines/time_series_engine.py"),
    ("deven.engines.raw_converter", "deven/engines/raw_converter.py"),
    ("deven.engines.dat_converter", "deven/engines/dat_converter.py"),
    ("deven.engines.others_converter", "deven/engines/others_converter.py"),
    ("deven.engines.powerfactory_converter", "deven/engines/powerfactory_converter.py"),
    ("deven.engines.psse_converter", "deven/engines/psse_converter.py"),
    ("deven.utils.island_detector", "deven/utils/island_detector.py"),
    ("deven.utils.contingency_branch_finder", "deven/utils/contingency_branch_finder.py"),
]

ext_modules = []
if USE_CYTHON and "--no-compile" not in sys.argv:
    for mod_name, src_file in MODULES_TO_COMPILE:
        if os.path.exists(src_file):
            ext_modules.append(Extension(mod_name, [src_file]))
    if ext_modules:
        ext_modules = cythonize(
            ext_modules,
            compiler_directives={
                "language_level": "3",
                "binding": True,
                "embedsignature": True,
            },
        )
elif "--no-compile" in sys.argv:
    sys.argv.remove("--no-compile")

setup(
    name="deven",
    version="1.0.0",
    description="High-Performance Power System Simulation Suite (LFA, SCS, CA, TS-LFA)",
    packages=find_packages(),
    ext_modules=ext_modules,
    package_data={
        "deven": ["*.pyd", "*.so", "*.pyi", "py.typed"],
        "deven.docs": ["*.html", "*.css", "*.js", "*.png", "*.svg", "*.ico"],
        "deven.engines": ["*.pyd", "*.so", "*.pyi"],
        "deven.utils": ["*.pyd", "*.so", "*.pyi"],
    },
    include_package_data=True,
    entry_points={
        "console_scripts": [
            "deven = deven.cli:main",
        ],
    },
    install_requires=[
        "numpy>=1.24.0",
        "scipy>=1.10.0",
        "pandas>=2.0.0",
        "networkx>=3.0",
        "openpyxl>=3.0.0",
        "prettytable>=3.0.0",
        "typing_extensions>=4.5.0",
    ],
    extras_require={
        "plotting": ["matplotlib>=3.7.0", "plotly>=5.0.0"],
        "all": ["matplotlib>=3.7.0", "plotly>=5.0.0"],
    },
    python_requires=">=3.9",
)


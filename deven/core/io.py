"""
Headless Network I/O for DevEN Power System Models.
Supports loading and saving .py, .sql/.sqlite, .raw, .dgs, .dat, and .json network definitions
with zero GUI dependencies.
"""

import os
import sys
import json
import importlib.util
from typing import Optional, Union, List

cur_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(cur_dir)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from deven.core.model import PowerGridData


def load_network(file_path: str, project_id: Optional[str] = None) -> PowerGridData:
    """
    Loads a power system case from a file.

    Supported file formats:
        - .py           : Python-based network case database
        - .sqlite, .db, .sql : Relational SQLite database
        - .raw          : Raw power network bus/branch format
        - .dgs, .pfd    : General schema exchange format
        - .dat, .dat0   : Tabular network data format
        - .json         : JSON serialized network model
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Network file not found: {file_path}")

    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".py":
        return _load_from_py_file(file_path)
    elif ext in (".sqlite", ".db", ".sqlite3", ".sql"):
        return _load_from_sqlite(file_path, project_id=project_id)
    elif ext == ".raw":
        return _load_from_raw(file_path)
    elif ext in (".dgs", ".pfd"):
        return _load_from_dgs(file_path)
    elif ext in (".dat", ".dat0"):
        return _load_from_dat(file_path)
    elif ext == ".json":
        return _load_from_json(file_path)
    else:
        raise ValueError(
            f"Unsupported network file extension: '{ext}'. "
            f"Supported extensions: .py, .sql, .sqlite, .raw, .dgs, .dat, .json"
        )


def _load_from_py_file(file_path: str) -> PowerGridData:
    """Loads a PowerGridData model directly from a .py file."""
    try:
        from deven.utils.input_reader import InputReader
        parsed_data = InputReader.read_from_python(file_path)
        if parsed_data and parsed_data.get("buses"):
            return PowerGridData.from_dict(parsed_data)
    except Exception:
        pass

    spec = importlib.util.spec_from_file_location("_deven_temp_case", file_path)
    if not spec or not spec.loader:
        raise ImportError(f"Cannot load module from: {file_path}")

    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # If the file exports a project dict or tables
    raw_dict = {}
    for attr in [
        "BUS_DATA", "GENERATOR_DATA", "LOAD_DATA", "LINE_DATA",
        "TRANSFORMER_DATA", "THREE_WINDING_TRANSFORMER_DATA",
        "CAPACITOR_DATA", "REACTOR_DATA", "SERIES_COMP_DATA",
        "SERIES_REACTOR_DATA", "SHUNT_DATA", "FAULT_CASES", "PROJECT_NAME"
    ]:
        if hasattr(mod, attr):
            raw_dict[attr.lower()] = getattr(mod, attr)

    # Alternatively check for project_data or similar dict
    if not raw_dict and hasattr(mod, "project_data"):
        raw_dict = getattr(mod, "project_data")

    # If already a PowerGridData object
    if hasattr(mod, "grid") and isinstance(mod.grid, PowerGridData):
        return mod.grid

    # Use tools.sqldb.converter if needed
    try:
        from deven.tools.sqldb.converter import load_py_db_file
        proj_dict = load_py_db_file(file_path)
        if proj_dict:
            return PowerGridData.from_dict(proj_dict)
    except Exception:
        pass

    return PowerGridData.from_dict(raw_dict)


def _load_from_sqlite(file_path: str, project_id: Optional[str] = None) -> PowerGridData:
    """Loads a PowerGridData model from a SQLite database."""
    from deven.tools.sqldb.converter import load_project_dict_from_sqlite
    proj_dict = load_project_dict_from_sqlite(file_path, project_id=project_id)
    return PowerGridData.from_dict(proj_dict)


def _load_from_raw(file_path: str) -> PowerGridData:
    """Parses and loads a power network from a .raw file."""
    from deven.engines.raw_converter import convert_raw_to_py
    import tempfile
    out_py = os.path.join(tempfile.gettempdir(), f"deven_raw_{os.getpid()}.py")
    convert_raw_to_py(file_path, out_py)
    grid = _load_from_py_file(out_py)
    try:
        os.remove(out_py)
    except Exception:
        pass
    return grid


def _load_from_dgs(file_path: str) -> PowerGridData:
    """Parses and loads a power network from a .dgs / .pfd file."""
    from deven.engines.powerfactory_converter import PowerFactoryDGSParser
    parser = PowerFactoryDGSParser(file_path)
    if hasattr(parser, "to_dict"):
        return PowerGridData.from_dict(parser.to_dict())
    elif hasattr(parser, "export_to_py"):
        import tempfile
        out_py = os.path.join(tempfile.gettempdir(), f"deven_dgs_{os.getpid()}.py")
        parser.export_to_py(out_py)
        grid = _load_from_py_file(out_py)
        try:
            os.remove(out_py)
        except Exception:
            pass
        return grid
    else:
        raise RuntimeError("Failed to parse general schema file.")


def _load_from_dat(file_path: str) -> PowerGridData:
    """Parses and loads a power network from a .dat / .dat0 tabular file."""
    from deven.engines.dat_converter import convert_dat0_to_py
    import tempfile
    out_py = os.path.join(tempfile.gettempdir(), f"deven_dat_{os.getpid()}.py")
    convert_dat0_to_py(file_path, output_py_path=out_py)
    grid = _load_from_py_file(out_py)
    try:
        os.remove(out_py)
    except Exception:
        pass
    return grid


def _load_from_json(file_path: str) -> PowerGridData:
    """Loads a PowerGridData model from a JSON file."""
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return PowerGridData.from_dict(data)


def save_network(
    grid: PowerGridData,
    target_path: str,
    format: Optional[str] = None,
    project_name: Optional[str] = None,
    project_id: Optional[str] = None,
    overwrite: bool = True
) -> str:
    """
    Saves a PowerGridData model to a .py file, .sqlite database, or .json file.
    """
    if not format:
        ext = os.path.splitext(target_path)[1].lower()
        format = "sqlite" if ext in (".sqlite", ".db", ".sqlite3") else "json" if ext == ".json" else "py"

    os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)

    if format == "py":
        import tempfile
        tmp_db = os.path.join(tempfile.gettempdir(), f"tmp_export_{os.getpid()}.sqlite")
        try:
            from deven.tools.sqldb.converter import sqlite_to_py, py_to_sqlite
            # Save to temp sqlite first then convert to clean py
            save_network(grid, tmp_db, format="sqlite", project_name=project_name, project_id=project_id)
            sqlite_to_py(tmp_db, target_path, project_id=project_id)
        finally:
            if os.path.exists(tmp_db):
                try:
                    os.remove(tmp_db)
                except Exception:
                    pass
        return target_path

    elif format == "sqlite":
        from deven.tools.sqldb.schema import init_database
        from deven.tools.sqldb.converter import insert_project_dict
        init_database(target_path)
        data_dict = grid.to_dict()
        insert_project_dict(
            target_path,
            data_dict,
            project_name=project_name or grid.project_name,
            project_id=project_id or grid.project_id
        )
        return target_path

    elif format == "json":
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(grid.to_dict(), f, indent=2)
        return target_path

    else:
        raise ValueError(f"Unsupported export format: '{format}'. Supported: py, sqlite, json")

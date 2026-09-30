"""
SQLDB Module for DevEN Power System Application.
Supports converting .py database files into a unified SQLite database and reverse extraction.
Can be used standalone or from within the DevEN GUI.
"""

import sys
import os
cur_dir = os.path.dirname(os.path.abspath(__file__))
if cur_dir not in sys.path:
    sys.path.insert(0, cur_dir)

try:
    from .schema import create_tables
    from .converter import (
        py_to_sqlite,
        sqlite_to_py,
        list_projects,
        delete_project,
        export_all_projects,
        load_project_dict_from_sqlite
    )
except ImportError:
    from schema import create_tables
    from converter import (
        py_to_sqlite,
        sqlite_to_py,
        list_projects,
        delete_project,
        export_all_projects,
        load_project_dict_from_sqlite
    )

__all__ = [
    'create_tables',
    'py_to_sqlite',
    'sqlite_to_py',
    'list_projects',
    'delete_project',
    'export_all_projects',
    'load_project_dict_from_sqlite'
]

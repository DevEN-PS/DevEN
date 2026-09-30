"""
Database schema and table creation scripts for DevEN SQLite unified storage.
"""

import sqlite3

SCHEMA_VERSION = "1.0.1"

DDL_STATEMENTS = [
    # 1. Master Projects Registry
    """
    CREATE TABLE IF NOT EXISTS projects (
        project_id TEXT PRIMARY KEY,
        project_name TEXT NOT NULL,
        description TEXT DEFAULT '',
        base_mva REAL DEFAULT 100.0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        solver_config_json TEXT DEFAULT '{}',
        map_settings_json TEXT DEFAULT '{}',
        metadata_json TEXT DEFAULT '{}'
    );
    """,

    # 2. Buses Table
    """
    CREATE TABLE IF NOT EXISTS buses (
        project_id TEXT NOT NULL,
        bus_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        type INTEGER NOT NULL,
        base_kV REAL NOT NULL,
        V_init REAL NOT NULL,
        angle_init REAL NOT NULL,
        shunt_G REAL DEFAULT 0.0,
        shunt_B REAL DEFAULT 0.0,
        area INTEGER DEFAULT 1,
        zone INTEGER DEFAULT 1,
        owner INTEGER DEFAULT 1,
        lat REAL DEFAULT 0.0,
        long REAL DEFAULT 0.0,
        sk_mva REAL DEFAULT 1000.0,
        rx_ratio REAL DEFAULT 0.1,
        z01_ratio REAL DEFAULT 1.0,
        PRIMARY KEY (project_id, bus_id),
        FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
    );
    """,

    # 3. Generators Table
    """
    CREATE TABLE IF NOT EXISTS generators (
        project_id TEXT NOT NULL,
        gen_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        bus INTEGER NOT NULL,
        P_out REAL NOT NULL,
        Q_out REAL NOT NULL,
        V_set REAL NOT NULL,
        Qmin REAL NOT NULL,
        Qmax REAL NOT NULL,
        status INTEGER DEFAULT 1,
        area INTEGER DEFAULT 1,
        zone INTEGER DEFAULT 1,
        owner INTEGER DEFAULT 1,
        R1_pu REAL DEFAULT 0.0,
        X1_pu REAL DEFAULT 0.0,
        R2_pu REAL DEFAULT 0.0,
        X2_pu REAL DEFAULT 0.0,
        R0_pu REAL DEFAULT 0.0,
        X0_pu REAL DEFAULT 0.0,
        cb_mva REAL DEFAULT 0.0,
        wind_conn TEXT DEFAULT '0',
        gnd_r REAL DEFAULT 0.0,
        gnd_x REAL DEFAULT 0.0,
        PRIMARY KEY (project_id, gen_id),
        FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
    );
    """,

    # 4. Loads Table
    """
    CREATE TABLE IF NOT EXISTS loads (
        project_id TEXT NOT NULL,
        load_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        bus INTEGER NOT NULL,
        P_demand REAL NOT NULL,
        Q_demand REAL NOT NULL,
        model TEXT NOT NULL,
        area INTEGER DEFAULT 1,
        zone INTEGER DEFAULT 1,
        cb_mva REAL DEFAULT 0.0,
        wind_conn TEXT DEFAULT '0',
        PRIMARY KEY (project_id, load_id),
        FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
    );
    """,

    # 5. Transmission Lines Table
    """
    CREATE TABLE IF NOT EXISTS lines (
        project_id TEXT NOT NULL,
        line_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        from_bus INTEGER NOT NULL,
        to_bus INTEGER NOT NULL,
        length_km REAL NOT NULL,
        R_per_km REAL NOT NULL,
        X_per_km REAL NOT NULL,
        B_per_km REAL NOT NULL,
        rateA REAL DEFAULT 0.0,
        status INTEGER DEFAULT 1,
        area INTEGER DEFAULT 1,
        zone INTEGER DEFAULT 1,
        owner INTEGER DEFAULT 1,
        R0_per_km REAL DEFAULT 0.0,
        X0_per_km REAL DEFAULT 0.0,
        B0_per_km REAL DEFAULT 0.0,
        from_cb_mva REAL DEFAULT 0.0,
        to_cb_mva REAL DEFAULT 0.0,
        bends_json TEXT DEFAULT '[]',
        PRIMARY KEY (project_id, line_id),
        FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
    );
    """,

    # 6. Two-Winding Transformers Table
    """
    CREATE TABLE IF NOT EXISTS transformers (
        project_id TEXT NOT NULL,
        xfmr_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        from_bus INTEGER NOT NULL,
        to_bus INTEGER NOT NULL,
        r REAL NOT NULL,
        x REAL NOT NULL,
        tap_ratio REAL DEFAULT 1.0,
        rateA REAL DEFAULT 9999.0,
        phase_shift REAL DEFAULT 0.0,
        min_tap REAL DEFAULT 0.9,
        max_tap REAL DEFAULT 1.1,
        step_size REAL DEFAULT 0.01,
        status INTEGER DEFAULT 1,
        area INTEGER DEFAULT 1,
        zone INTEGER DEFAULT 1,
        owner INTEGER DEFAULT 1,
        R0_pu REAL DEFAULT 0.0,
        X0_pu REAL DEFAULT 0.0,
        from_conn TEXT DEFAULT '0',
        to_conn TEXT DEFAULT '0',
        from_gnd_r REAL DEFAULT 0.0,
        from_gnd_x REAL DEFAULT 0.0,
        to_gnd_r REAL DEFAULT 0.0,
        to_gnd_x REAL DEFAULT 0.0,
        from_cb_mva REAL DEFAULT 0.0,
        to_cb_mva REAL DEFAULT 0.0,
        PRIMARY KEY (project_id, xfmr_id),
        FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
    );
    """,

    # 7. Three-Winding Transformers Table
    """
    CREATE TABLE IF NOT EXISTS three_winding_transformers (
        project_id TEXT NOT NULL,
        tw_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        hv_bus INTEGER NOT NULL,
        mv_bus INTEGER NOT NULL,
        lv_bus INTEGER NOT NULL,
        r_hm REAL DEFAULT 0.0,
        x_hm REAL DEFAULT 0.05,
        r_hl REAL DEFAULT 0.0,
        x_hl REAL DEFAULT 0.05,
        r_ml REAL DEFAULT 0.0,
        x_ml REAL DEFAULT 0.05,
        rate_h REAL DEFAULT 9999.0,
        rate_m REAL DEFAULT 9999.0,
        rate_l REAL DEFAULT 9999.0,
        tap_h REAL DEFAULT 1.0,
        tap_m REAL DEFAULT 1.0,
        tap_l REAL DEFAULT 1.0,
        status INTEGER DEFAULT 1,
        area INTEGER DEFAULT 1,
        zone INTEGER DEFAULT 1,
        owner INTEGER DEFAULT 1,
        PRIMARY KEY (project_id, tw_id),
        FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
    );
    """,

    # 8. Capacitors Table
    """
    CREATE TABLE IF NOT EXISTS capacitors (
        project_id TEXT NOT NULL,
        cap_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        bus INTEGER NOT NULL,
        Q_cap REAL NOT NULL,
        status INTEGER DEFAULT 1,
        area INTEGER DEFAULT 1,
        zone INTEGER DEFAULT 1,
        PRIMARY KEY (project_id, cap_id),
        FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
    );
    """,

    # 9. Reactors Table
    """
    CREATE TABLE IF NOT EXISTS reactors (
        project_id TEXT NOT NULL,
        reactor_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        bus INTEGER NOT NULL,
        Q_react REAL NOT NULL,
        status INTEGER DEFAULT 1,
        area INTEGER DEFAULT 1,
        zone INTEGER DEFAULT 1,
        G1_pu REAL DEFAULT 0.0,
        B1_pu REAL DEFAULT 0.0,
        G0_pu REAL DEFAULT 0.0,
        B0_pu REAL DEFAULT 0.0,
        cb_mva REAL DEFAULT 0.0,
        PRIMARY KEY (project_id, reactor_id),
        FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
    );
    """,

    # 10. Series Compensation Table
    """
    CREATE TABLE IF NOT EXISTS series_comps (
        project_id TEXT NOT NULL,
        sc_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        from_bus INTEGER NOT NULL,
        to_bus INTEGER NOT NULL,
        r REAL DEFAULT 0.0,
        x REAL DEFAULT 0.0,
        comp_pct REAL DEFAULT 0.0,
        status INTEGER DEFAULT 1,
        area INTEGER DEFAULT 1,
        zone INTEGER DEFAULT 1,
        owner INTEGER DEFAULT 1,
        PRIMARY KEY (project_id, sc_id),
        FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
    );
    """,

    # 11. Series Reactors Table
    """
    CREATE TABLE IF NOT EXISTS series_reactors (
        project_id TEXT NOT NULL,
        sr_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        from_bus INTEGER NOT NULL,
        to_bus INTEGER NOT NULL,
        r REAL DEFAULT 0.0,
        x REAL DEFAULT 0.0,
        status INTEGER DEFAULT 1,
        area INTEGER DEFAULT 1,
        zone INTEGER DEFAULT 1,
        owner INTEGER DEFAULT 1,
        PRIMARY KEY (project_id, sr_id),
        FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
    );
    """,

    # 12. Shunts Table
    """
    CREATE TABLE IF NOT EXISTS shunts (
        project_id TEXT NOT NULL,
        shunt_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        bus INTEGER NOT NULL,
        Q_shunt REAL NOT NULL,
        status INTEGER DEFAULT 1,
        area INTEGER DEFAULT 1,
        zone INTEGER DEFAULT 1,
        PRIMARY KEY (project_id, shunt_id),
        FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
    );
    """,

    # 13. Short Circuit Fault Cases
    """
    CREATE TABLE IF NOT EXISTS short_circuit_faults (
        row_id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id TEXT NOT NULL,
        case_num INTEGER NOT NULL,
        fault_bus INTEGER NOT NULL,
        fault_type TEXT NOT NULL,
        r_phase REAL DEFAULT 0.0,
        x_phase REAL DEFAULT 0.0,
        r_gnd REAL DEFAULT 0.0,
        x_gnd REAL DEFAULT 0.0,
        FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
    );
    """,

    # 14. Zero Sequence Voltage Factors
    """
    CREATE TABLE IF NOT EXISTS zero_seq_factors (
        row_id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id TEXT NOT NULL,
        voltage_kV REAL NOT NULL,
        zero_seq_res_mult REAL DEFAULT 3.0,
        zero_seq_rea_mult REAL DEFAULT 3.0,
        zero_seq_adm_mult REAL DEFAULT 0.6,
        FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
    );
    """,

    # 15. Global Sequence Factors
    """
    CREATE TABLE IF NOT EXISTS global_factors (
        project_id TEXT NOT NULL,
        key_name TEXT NOT NULL,
        val_data TEXT NOT NULL,
        PRIMARY KEY (project_id, key_name),
        FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
    );
    """,

    # 16. SLD Diagram Storage (supports multiple named diagrams per project)
    """
    CREATE TABLE IF NOT EXISTS sld_diagrams (
        project_id TEXT NOT NULL,
        diagram_name TEXT NOT NULL DEFAULT 'Diagram 1',
        sld_json TEXT NOT NULL,
        is_primary INTEGER DEFAULT 1,
        created_at TEXT,
        updated_at TEXT,
        PRIMARY KEY (project_id, diagram_name),
        FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
    );
    """,

    # 17. Battery Energy Storage System (BESS) Table
    """
    CREATE TABLE IF NOT EXISTS bess (
        project_id TEXT NOT NULL,
        bess_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        bus INTEGER NOT NULL,
        rated_mw REAL NOT NULL,
        rated_mwh REAL NOT NULL,
        soc_init REAL DEFAULT 0.5,
        soc_min REAL DEFAULT 0.1,
        soc_max REAL DEFAULT 0.9,
        eff_ch REAL DEFAULT 0.95,
        eff_dis REAL DEFAULT 0.95,
        strategy TEXT DEFAULT 'peak_shaving',
        target_mw REAL DEFAULT 0.0,
        status INTEGER DEFAULT 1,
        area INTEGER DEFAULT 1,
        zone INTEGER DEFAULT 1,
        owner INTEGER DEFAULT 1,
        PRIMARY KEY (project_id, bess_id),
        FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
    );
    """,

    # 18. Harmonic Sources Table (IEEE 519 / IEC 61000)
    """
    CREATE TABLE IF NOT EXISTS harmonic_sources (
        project_id TEXT NOT NULL,
        source_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        bus INTEGER NOT NULL,
        source_type TEXT DEFAULT 'current',
        unit TEXT DEFAULT 'amp_rms',
        fund_val REAL DEFAULT 100.0,
        spectrum_json TEXT DEFAULT '{}',
        status INTEGER DEFAULT 1,
        area INTEGER DEFAULT 1,
        zone INTEGER DEFAULT 1,
        PRIMARY KEY (project_id, source_id),
        FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
    );
    """,

    # 19. Passive Harmonic Filters Table
    """
    CREATE TABLE IF NOT EXISTS harmonic_filters (
        project_id TEXT NOT NULL,
        filter_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        bus INTEGER NOT NULL,
        filter_type TEXT DEFAULT 'single_tuned',
        tuning_order REAL DEFAULT 5.0,
        q_factor REAL DEFAULT 50.0,
        mvar_rated REAL DEFAULT 1.0,
        r_ohm REAL DEFAULT 0.0,
        l_mh REAL DEFAULT 0.0,
        c_uf REAL DEFAULT 0.0,
        status INTEGER DEFAULT 1,
        area INTEGER DEFAULT 1,
        zone INTEGER DEFAULT 1,
        PRIMARY KEY (project_id, filter_id),
        FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
    );
    """
]

INDEX_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS idx_buses_project ON buses(project_id);",
    "CREATE INDEX IF NOT EXISTS idx_gens_project ON generators(project_id);",
    "CREATE INDEX IF NOT EXISTS idx_loads_project ON loads(project_id);",
    "CREATE INDEX IF NOT EXISTS idx_lines_project ON lines(project_id);",
    "CREATE INDEX IF NOT EXISTS idx_xfmrs_project ON transformers(project_id);",
    "CREATE INDEX IF NOT EXISTS idx_tw_project ON three_winding_transformers(project_id);",
    "CREATE INDEX IF NOT EXISTS idx_bess_project ON bess(project_id);",
    "CREATE INDEX IF NOT EXISTS idx_harmsrc_project ON harmonic_sources(project_id);",
    "CREATE INDEX IF NOT EXISTS idx_harmflt_project ON harmonic_filters(project_id);",
    "CREATE INDEX IF NOT EXISTS idx_zero_seq_project ON zero_seq_factors(project_id);",
    "CREATE INDEX IF NOT EXISTS idx_faults_project ON short_circuit_faults(project_id);",
    "CREATE INDEX IF NOT EXISTS idx_sld_project ON sld_diagrams(project_id);",
]

def create_tables(conn_or_cursor):
    """Executes all DDL and index statements to prepare the SQLite database."""
    if isinstance(conn_or_cursor, sqlite3.Connection):
        cur = conn_or_cursor.cursor()
    else:
        cur = conn_or_cursor

    for stmt in DDL_STATEMENTS:
        cur.execute(stmt)

    for idx_stmt in INDEX_STATEMENTS:
        cur.execute(idx_stmt)

    # Auto-migration for existing databases
    try:
        cur.execute("PRAGMA table_info(generators)")
        cols = [r[1] for r in cur.fetchall()]
        if 'gnd_r' not in cols:
            cur.execute("ALTER TABLE generators ADD COLUMN gnd_r REAL DEFAULT 0.0")
        if 'gnd_x' not in cols:
            cur.execute("ALTER TABLE generators ADD COLUMN gnd_x REAL DEFAULT 0.0")
    except Exception:
        pass

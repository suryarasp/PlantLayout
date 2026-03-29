"""database/db.py — SQLite connection manager and schema initializer"""
import sqlite3
import os
import json
from config import AISC_SECTIONS, MATERIALS

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "epc_design.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.executescript("""
    CREATE TABLE IF NOT EXISTS projects (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        name          TEXT NOT NULL,
        description   TEXT,
        code_standard TEXT DEFAULT 'AISC-360',
        wind_speed    REAL DEFAULT 45,
        wind_exposure TEXT DEFAULT 'C',
        wind_zone     TEXT DEFAULT 'B',
        seismic_sds   REAL DEFAULT 0.2,
        seismic_sd1   REAL DEFAULT 0.1,
        seismic_r     REAL DEFAULT 3.0,
        seismic_ie    REAL DEFAULT 1.0,
        site_class    TEXT DEFAULT 'D',
        soil_bearing  REAL DEFAULT 150,
        soil_depth    REAL DEFAULT 1500,
        created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS equipment (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id       INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        tag              TEXT NOT NULL,
        type             TEXT NOT NULL DEFAULT 'VESSEL',
        description      TEXT,
        weight_empty     REAL DEFAULT 0,
        weight_operating REAL DEFAULT 0,
        weight_test      REAL DEFAULT 0,
        length_mm        REAL DEFAULT 0,
        diameter_mm      REAL DEFAULT 0,
        height_mm        REAL DEFAULT 0,
        cog_x            REAL DEFAULT 0,
        cog_y            REAL DEFAULT 0,
        cog_z            REAL DEFAULT 0,
        pos_x            REAL DEFAULT 0,
        pos_y            REAL DEFAULT 0,
        pos_z            REAL DEFAULT 0,
        orientation      TEXT DEFAULT 'H',
        elevation        REAL DEFAULT 0,
        tier_level       INTEGER DEFAULT 1,
        bay_number       INTEGER DEFAULT 1,
        support_type     TEXT DEFAULT 'SKID',
        notes            TEXT
    );

    CREATE TABLE IF NOT EXISTS nozzles (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        equipment_id INTEGER NOT NULL REFERENCES equipment(id) ON DELETE CASCADE,
        nozzle_tag   TEXT NOT NULL,
        service      TEXT,
        size_dn      REAL DEFAULT 50,
        rating       TEXT DEFAULT '150#',
        pos_x        REAL DEFAULT 0,
        pos_y        REAL DEFAULT 0,
        pos_z        REAL DEFAULT 0,
        direction    TEXT DEFAULT '+Z',
        force_fx     REAL DEFAULT 0,
        force_fy     REAL DEFAULT 0,
        force_fz     REAL DEFAULT 0,
        moment_mx    REAL DEFAULT 0,
        moment_my    REAL DEFAULT 0,
        moment_mz    REAL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS base_plates (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        equipment_id     INTEGER UNIQUE REFERENCES equipment(id) ON DELETE CASCADE,
        plate_length     REAL DEFAULT 300,
        plate_width      REAL DEFAULT 300,
        plate_thickness  REAL DEFAULT 20,
        anchor_bolt_dia  REAL DEFAULT 20,
        anchor_bolt_qty  INTEGER DEFAULT 4,
        anchor_bolt_pcd  REAL DEFAULT 250,
        grout_thickness  REAL DEFAULT 25,
        bearing_pressure REAL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS load_cases (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        name        TEXT NOT NULL,
        type        TEXT NOT NULL,
        description TEXT,
        active      INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS nodal_loads (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        load_case_id INTEGER REFERENCES load_cases(id) ON DELETE CASCADE,
        node_tag     TEXT NOT NULL,
        fx           REAL DEFAULT 0,
        fy           REAL DEFAULT 0,
        fz           REAL DEFAULT 0,
        mx           REAL DEFAULT 0,
        my           REAL DEFAULT 0,
        mz           REAL DEFAULT 0,
        load_source  TEXT DEFAULT 'MANUAL'
    );

    CREATE TABLE IF NOT EXISTS distributed_loads (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        load_case_id INTEGER REFERENCES load_cases(id) ON DELETE CASCADE,
        member_tag   TEXT NOT NULL,
        load_type    TEXT DEFAULT 'UDL',
        w1           REAL DEFAULT 0,
        w2           REAL DEFAULT 0,
        distance_a   REAL DEFAULT 0,
        distance_b   REAL DEFAULT 0,
        direction    TEXT DEFAULT 'GLOBAL-Y'
    );

    CREATE TABLE IF NOT EXISTS pipe_rack_geometry (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id       INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        rack_tag         TEXT NOT NULL,
        total_length     REAL DEFAULT 0,
        bay_span         REAL DEFAULT 9000,
        number_of_bays   INTEGER DEFAULT 3,
        number_of_tiers  INTEGER DEFAULT 2,
        tier_heights     TEXT DEFAULT '[4000,7500]',
        width_of_rack    REAL DEFAULT 6000,
        column_spacing   TEXT DEFAULT '[]',
        orientation_angle REAL DEFAULT 0,
        origin_x         REAL DEFAULT 0,
        origin_y         REAL DEFAULT 0,
        origin_z         REAL DEFAULT 0,
        bracing_type     TEXT DEFAULT 'X-BRACE'
    );

    CREATE TABLE IF NOT EXISTS nodes (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        rack_id      INTEGER REFERENCES pipe_rack_geometry(id) ON DELETE CASCADE,
        node_tag     TEXT NOT NULL,
        x            REAL DEFAULT 0,
        y            REAL DEFAULT 0,
        z            REAL DEFAULT 0,
        node_type    TEXT DEFAULT 'FRAME_NODE',
        is_support   INTEGER DEFAULT 0,
        support_type TEXT DEFAULT 'PINNED'
    );

    CREATE TABLE IF NOT EXISTS sections (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        designation  TEXT UNIQUE NOT NULL,
        section_type TEXT,
        d            REAL, bf REAL, tw REAL, tf REAL,
        area         REAL, ix REAL, sx REAL, zx REAL, rx REAL,
        iy REAL, sy REAL, zy REAL, ry REAL,
        j REAL, cw REAL, weight_per_m REAL
    );

    CREATE TABLE IF NOT EXISTS materials (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        name     TEXT UNIQUE NOT NULL,
        fy       REAL, fu REAL,
        e_modulus REAL DEFAULT 200000,
        g_modulus REAL DEFAULT 77000,
        density  REAL DEFAULT 7850,
        poisson  REAL DEFAULT 0.3
    );

    CREATE TABLE IF NOT EXISTS members (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id       INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        rack_id          INTEGER REFERENCES pipe_rack_geometry(id),
        member_tag       TEXT NOT NULL,
        member_type      TEXT DEFAULT 'BEAM',
        start_node       TEXT,
        end_node         TEXT,
        section_id       INTEGER REFERENCES sections(id),
        material_id      INTEGER REFERENCES materials(id),
        length_mm        REAL DEFAULT 0,
        unbraced_length  REAL DEFAULT 0,
        k_factor         REAL DEFAULT 1.0,
        orientation_angle REAL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS load_combinations (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        combo_name  TEXT NOT NULL,
        combo_type  TEXT DEFAULT 'LRFD',
        factors     TEXT DEFAULT '{}',
        governing   INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS member_results (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id           INTEGER REFERENCES projects(id) ON DELETE CASCADE,
        member_tag           TEXT,
        combo_name           TEXT,
        axial_force          REAL DEFAULT 0,
        shear_y              REAL DEFAULT 0,
        shear_z              REAL DEFAULT 0,
        moment_y             REAL DEFAULT 0,
        moment_z             REAL DEFAULT 0,
        torsion              REAL DEFAULT 0,
        max_deflection_mm    REAL DEFAULT 0,
        uc_bending           REAL DEFAULT 0,
        uc_shear             REAL DEFAULT 0,
        uc_axial             REAL DEFAULT 0,
        uc_combined          REAL DEFAULT 0,
        phi_mn               REAL DEFAULT 0,
        phi_vn               REAL DEFAULT 0,
        phi_pn               REAL DEFAULT 0,
        status               TEXT DEFAULT 'UNCHECKED'
    );

    CREATE TABLE IF NOT EXISTS support_reactions (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id  INTEGER REFERENCES projects(id) ON DELETE CASCADE,
        node_tag    TEXT,
        load_case   TEXT,
        combo_name  TEXT,
        rx          REAL DEFAULT 0,
        ry          REAL DEFAULT 0,
        rz          REAL DEFAULT 0,
        rmx         REAL DEFAULT 0,
        rmy         REAL DEFAULT 0,
        rmz         REAL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS foundations (
        id                     INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id             INTEGER REFERENCES projects(id) ON DELETE CASCADE,
        footing_tag            TEXT,
        node_tag               TEXT,
        footing_type           TEXT DEFAULT 'SPREAD',
        length_mm              REAL DEFAULT 1200,
        width_mm               REAL DEFAULT 1200,
        depth_mm               REAL DEFAULT 1500,
        thickness_mm           REAL DEFAULT 500,
        soil_bearing_kpa       REAL DEFAULT 150,
        concrete_fc_mpa        REAL DEFAULT 28,
        steel_fy_mpa           REAL DEFAULT 420,
        rebar_top_x            TEXT DEFAULT '12@150',
        rebar_top_y            TEXT DEFAULT '12@150',
        rebar_bot_x            TEXT DEFAULT '16@150',
        rebar_bot_y            TEXT DEFAULT '16@150',
        bearing_actual_kpa     REAL DEFAULT 0,
        uc_punching            REAL DEFAULT 0,
        uc_shear_x             REAL DEFAULT 0,
        uc_shear_y             REAL DEFAULT 0,
        uc_flexure_x           REAL DEFAULT 0,
        uc_flexure_y           REAL DEFAULT 0,
        as_req_x_mm2pm         REAL DEFAULT 0,
        as_req_y_mm2pm         REAL DEFAULT 0,
        status                 TEXT DEFAULT 'UNCHECKED'
    );
    """)

    # Seed sections
    existing = c.execute("SELECT COUNT(*) FROM sections").fetchone()[0]
    if existing == 0:
        for s in AISC_SECTIONS:
            c.execute("""INSERT OR IGNORE INTO sections
                (designation,section_type,d,bf,tw,tf,area,ix,sx,zx,rx,iy,sy,zy,ry,j,cw,weight_per_m)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (s["designation"], s["type"], s["d"], s["bf"], s["tw"], s["tf"],
                 s["A"], s.get("Ix",0), s.get("Sx",0), s.get("Zx",0), s.get("rx",0),
                 s.get("Iy",0), s.get("Sy",0), s.get("Zy",0), s.get("ry",0),
                 s.get("J",0), s.get("Cw",0), s.get("w",0)))

    # Seed materials
    for m in MATERIALS:
        c.execute("""INSERT OR IGNORE INTO materials(name,fy,fu,e_modulus,g_modulus,density)
                     VALUES(?,?,?,?,?,?)""",
                  (m["name"], m["fy"], m["fu"], m["E"], m["G"], m["density"]))

    conn.commit()
    conn.close()


def seed_default_load_cases(project_id):
    """Insert standard load cases for a new project."""
    conn = get_conn()
    cases = [
        ("DL",   "DEAD",    "Dead Load - Self weight + permanent"),
        ("LL",   "LIVE",    "Live Load - Operating + maintenance"),
        ("WL-X", "WIND",    "Wind Load in X direction"),
        ("WL-Y", "WIND",    "Wind Load in Y direction"),
        ("EQ-X", "SEISMIC", "Seismic Load in X direction (ELF)"),
        ("EQ-Y", "SEISMIC", "Seismic Load in Y direction (ELF)"),
        ("TL",   "THERMAL", "Thermal Load - Pipe friction/expansion"),
        ("OL",   "OPERATING","Operating Load - Nozzle forces/moments"),
        ("FDL",  "FRICTION", "Friction Dead Load - Pipe anchor friction"),
        ("ERE",  "EMPTY",    "Empty condition - hydrotest/erection"),
    ]
    for name, ltype, desc in cases:
        conn.execute("""INSERT INTO load_cases(project_id,name,type,description)
                        VALUES(?,?,?,?)""", (project_id, name, ltype, desc))
    conn.commit()
    conn.close()

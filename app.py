"""
app.py — EPC Structural Design Software
Flask REST API backend
"""
import os, json, math, io, csv
from flask import Flask, request, jsonify, send_file, render_template
from flask_cors import CORS

from database.db import get_conn, init_db, seed_default_load_cases
from calculations.structural import (
    check_member, generate_rack_nodes, generate_rack_members,
    auto_size_rack, generate_wind_loads, generate_seismic_loads,
    calculate_reactions, flexural_capacity, shear_capacity,
    axial_compression_capacity, generate_equipment_support_members
)
from calculations.foundation import design_spread_footing
from config import LRFD_COMBINATIONS, ASD_COMBINATIONS, AISC_SECTIONS

app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)

# ─── Database init ────────────────────────────────────────────
@app.before_request
def _ensure_db():
    init_db()


# ─── Helpers ──────────────────────────────────────────────────
def row_to_dict(row):
    if row is None:
        return None
    return dict(row)

def rows_to_list(rows):
    return [dict(r) for r in rows]

def _json_error(msg, code=400):
    return jsonify({"error": msg}), code

def _get_project_or_404(pid):
    conn = get_conn()
    p = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    conn.close()
    if not p:
        return None
    return dict(p)


# ─── FRONTEND ─────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


# ═══════════════════════════════════════════════════════════════
# PROJECTS
# ═══════════════════════════════════════════════════════════════
@app.route("/api/projects", methods=["GET"])
def list_projects():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@app.route("/api/projects", methods=["POST"])
def create_project():
    d = request.json or {}
    if not d.get("name"):
        return _json_error("Project name is required")
    conn = get_conn()
    cur = conn.execute("""
        INSERT INTO projects(name,description,code_standard,wind_speed,wind_exposure,
            wind_zone,seismic_sds,seismic_sd1,seismic_r,seismic_ie,site_class,
            soil_bearing,soil_depth)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (d["name"], d.get("description",""), d.get("code_standard","AISC-360"),
         d.get("wind_speed",45), d.get("wind_exposure","C"), d.get("wind_zone","B"),
         d.get("seismic_sds",0.2), d.get("seismic_sd1",0.1), d.get("seismic_r",3.0),
         d.get("seismic_ie",1.0), d.get("site_class","D"),
         d.get("soil_bearing",150), d.get("soil_depth",1500)))
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    seed_default_load_cases(pid)
    return jsonify({"id": pid, "message": "Project created"}), 201


@app.route("/api/projects/<int:pid>", methods=["GET"])
def get_project(pid):
    p = _get_project_or_404(pid)
    if not p:
        return _json_error("Project not found", 404)
    return jsonify(p)


@app.route("/api/projects/<int:pid>", methods=["PUT"])
def update_project(pid):
    d = request.json or {}
    fields = ["name","description","code_standard","wind_speed","wind_exposure",
              "wind_zone","seismic_sds","seismic_sd1","seismic_r","seismic_ie",
              "site_class","soil_bearing","soil_depth"]
    sets   = ", ".join(f"{f}=?" for f in fields if f in d)
    vals   = [d[f] for f in fields if f in d]
    if not sets:
        return _json_error("No fields to update")
    conn = get_conn()
    conn.execute(f"UPDATE projects SET {sets}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                 vals + [pid])
    conn.commit()
    conn.close()
    return jsonify({"message": "Updated"})


@app.route("/api/projects/<int:pid>", methods=["DELETE"])
def delete_project(pid):
    conn = get_conn()
    conn.execute("DELETE FROM projects WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    return jsonify({"message": "Deleted"})


# ═══════════════════════════════════════════════════════════════
# EQUIPMENT
# ═══════════════════════════════════════════════════════════════
@app.route("/api/projects/<int:pid>/equipment", methods=["GET"])
def list_equipment(pid):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM equipment WHERE project_id=? ORDER BY tag", (pid,)).fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@app.route("/api/projects/<int:pid>/equipment", methods=["POST"])
def add_equipment(pid):
    d = request.json or {}
    if not d.get("tag"):
        return _json_error("Equipment tag required")
    conn = get_conn()
    cur = conn.execute("""
        INSERT INTO equipment(project_id,tag,type,description,weight_empty,weight_operating,weight_test,
            length_mm,diameter_mm,height_mm,cog_x,cog_y,cog_z,
            pos_x,pos_y,pos_z,orientation,elevation,tier_level,bay_number,support_type,notes)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (pid, d["tag"], d.get("type","VESSEL"), d.get("description",""),
         d.get("weight_empty",0), d.get("weight_operating",0), d.get("weight_test",0),
         d.get("length_mm",0), d.get("diameter_mm",0), d.get("height_mm",0),
         d.get("cog_x",0), d.get("cog_y",0), d.get("cog_z",0),
         d.get("pos_x",0), d.get("pos_y",0), d.get("pos_z",0),
         d.get("orientation","H"), d.get("elevation",0),
         d.get("tier_level",1), d.get("bay_number",1),
         d.get("support_type","SKID"), d.get("notes","")))
    eid = cur.lastrowid
    conn.commit()
    conn.close()
    return jsonify({"id": eid, "message": "Equipment added"}), 201


@app.route("/api/equipment/<int:eid>", methods=["GET"])
def get_equipment(eid):
    conn = get_conn()
    eq = conn.execute("SELECT * FROM equipment WHERE id=?", (eid,)).fetchone()
    conn.close()
    if not eq:
        return _json_error("Not found", 404)
    return jsonify(row_to_dict(eq))


@app.route("/api/equipment/<int:eid>", methods=["PUT"])
def update_equipment(eid):
    d = request.json or {}
    fields = ["tag","type","description","weight_empty","weight_operating","weight_test",
              "length_mm","diameter_mm","height_mm","cog_x","cog_y","cog_z",
              "pos_x","pos_y","pos_z","orientation","elevation","tier_level","bay_number",
              "support_type","notes"]
    sets = ", ".join(f"{f}=?" for f in fields if f in d)
    vals = [d[f] for f in fields if f in d]
    if sets:
        conn = get_conn()
        conn.execute(f"UPDATE equipment SET {sets} WHERE id=?", vals + [eid])
        conn.commit()
        conn.close()
    return jsonify({"message": "Updated"})


@app.route("/api/equipment/<int:eid>", methods=["DELETE"])
def delete_equipment(eid):
    conn = get_conn()
    conn.execute("DELETE FROM equipment WHERE id=?", (eid,))
    conn.commit()
    conn.close()
    return jsonify({"message": "Deleted"})


# ── Nozzles ───────────────────────────────────────────────────
@app.route("/api/equipment/<int:eid>/nozzles", methods=["GET"])
def list_nozzles(eid):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM nozzles WHERE equipment_id=?", (eid,)).fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@app.route("/api/equipment/<int:eid>/nozzles", methods=["POST"])
def add_nozzle(eid):
    d = request.json or {}
    conn = get_conn()
    cur = conn.execute("""
        INSERT INTO nozzles(equipment_id,nozzle_tag,service,size_dn,rating,
            pos_x,pos_y,pos_z,direction,force_fx,force_fy,force_fz,
            moment_mx,moment_my,moment_mz)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (eid, d.get("nozzle_tag","N1"), d.get("service",""), d.get("size_dn",50),
         d.get("rating","150#"),
         d.get("pos_x",0), d.get("pos_y",0), d.get("pos_z",0),
         d.get("direction","+Z"),
         d.get("force_fx",0), d.get("force_fy",0), d.get("force_fz",0),
         d.get("moment_mx",0), d.get("moment_my",0), d.get("moment_mz",0)))
    nid = cur.lastrowid
    conn.commit()
    conn.close()
    return jsonify({"id": nid, "message": "Nozzle added"}), 201


@app.route("/api/nozzles/<int:nid>", methods=["PUT"])
def update_nozzle(nid):
    d = request.json or {}
    fields = ["nozzle_tag","service","size_dn","rating","pos_x","pos_y","pos_z",
              "direction","force_fx","force_fy","force_fz","moment_mx","moment_my","moment_mz"]
    sets = ", ".join(f"{f}=?" for f in fields if f in d)
    vals = [d[f] for f in fields if f in d]
    if sets:
        conn = get_conn()
        conn.execute(f"UPDATE nozzles SET {sets} WHERE id=?", vals + [nid])
        conn.commit()
        conn.close()
    return jsonify({"message": "Updated"})


@app.route("/api/nozzles/<int:nid>", methods=["DELETE"])
def delete_nozzle(nid):
    conn = get_conn()
    conn.execute("DELETE FROM nozzles WHERE id=?", (nid,))
    conn.commit()
    conn.close()
    return jsonify({"message": "Deleted"})


# ── Base Plates ───────────────────────────────────────────────
@app.route("/api/equipment/<int:eid>/baseplate", methods=["GET"])
def get_baseplate(eid):
    conn = get_conn()
    row = conn.execute("SELECT * FROM base_plates WHERE equipment_id=?", (eid,)).fetchone()
    conn.close()
    return jsonify(row_to_dict(row) or {})


@app.route("/api/equipment/<int:eid>/baseplate", methods=["PUT"])
def upsert_baseplate(eid):
    d = request.json or {}
    conn = get_conn()
    exists = conn.execute("SELECT id FROM base_plates WHERE equipment_id=?", (eid,)).fetchone()
    if exists:
        conn.execute("""UPDATE base_plates SET plate_length=?,plate_width=?,plate_thickness=?,
            anchor_bolt_dia=?,anchor_bolt_qty=?,anchor_bolt_pcd=?,grout_thickness=?
            WHERE equipment_id=?""",
            (d.get("plate_length",300), d.get("plate_width",300),
             d.get("plate_thickness",20), d.get("anchor_bolt_dia",20),
             d.get("anchor_bolt_qty",4), d.get("anchor_bolt_pcd",250),
             d.get("grout_thickness",25), eid))
    else:
        conn.execute("""INSERT INTO base_plates(equipment_id,plate_length,plate_width,plate_thickness,
            anchor_bolt_dia,anchor_bolt_qty,anchor_bolt_pcd,grout_thickness)
            VALUES(?,?,?,?,?,?,?,?)""",
            (eid, d.get("plate_length",300), d.get("plate_width",300),
             d.get("plate_thickness",20), d.get("anchor_bolt_dia",20),
             d.get("anchor_bolt_qty",4), d.get("anchor_bolt_pcd",250),
             d.get("grout_thickness",25)))
    conn.commit()
    conn.close()
    return jsonify({"message": "Baseplate saved"})


# ═══════════════════════════════════════════════════════════════
# LOADS
# ═══════════════════════════════════════════════════════════════
@app.route("/api/projects/<int:pid>/load-cases", methods=["GET"])
def list_load_cases(pid):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM load_cases WHERE project_id=?", (pid,)).fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@app.route("/api/projects/<int:pid>/load-cases", methods=["POST"])
def add_load_case(pid):
    d = request.json or {}
    conn = get_conn()
    cur = conn.execute("INSERT INTO load_cases(project_id,name,type,description) VALUES(?,?,?,?)",
                       (pid, d.get("name"), d.get("type","DEAD"), d.get("description","")))
    conn.commit()
    conn.close()
    return jsonify({"id": cur.lastrowid}), 201


@app.route("/api/load-cases/<int:lcid>", methods=["PUT"])
def update_load_case(lcid):
    d = request.json or {}
    conn = get_conn()
    conn.execute("UPDATE load_cases SET name=?,type=?,description=?,active=? WHERE id=?",
                 (d.get("name"), d.get("type"), d.get("description"), d.get("active",1), lcid))
    conn.commit()
    conn.close()
    return jsonify({"message": "Updated"})


@app.route("/api/projects/<int:pid>/nodal-loads", methods=["GET"])
def list_nodal_loads(pid):
    conn = get_conn()
    rows = conn.execute("""SELECT nl.*, lc.name as load_case_name
        FROM nodal_loads nl LEFT JOIN load_cases lc ON nl.load_case_id=lc.id
        WHERE nl.project_id=?""", (pid,)).fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@app.route("/api/projects/<int:pid>/nodal-loads", methods=["POST"])
def add_nodal_load(pid):
    d = request.json or {}
    conn = get_conn()
    cur = conn.execute("""INSERT INTO nodal_loads(project_id,load_case_id,node_tag,fx,fy,fz,mx,my,mz,load_source)
        VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (pid, d.get("load_case_id"), d.get("node_tag",""),
         d.get("fx",0), d.get("fy",0), d.get("fz",0),
         d.get("mx",0), d.get("my",0), d.get("mz",0),
         d.get("load_source","MANUAL")))
    conn.commit()
    conn.close()
    return jsonify({"id": cur.lastrowid}), 201


@app.route("/api/nodal-loads/<int:nlid>", methods=["DELETE"])
def delete_nodal_load(nlid):
    conn = get_conn()
    conn.execute("DELETE FROM nodal_loads WHERE id=?", (nlid,))
    conn.commit()
    conn.close()
    return jsonify({"message": "Deleted"})


@app.route("/api/projects/<int:pid>/distributed-loads", methods=["GET"])
def list_dist_loads(pid):
    conn = get_conn()
    rows = conn.execute("""SELECT dl.*, lc.name as load_case_name
        FROM distributed_loads dl LEFT JOIN load_cases lc ON dl.load_case_id=lc.id
        WHERE dl.project_id=?""", (pid,)).fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@app.route("/api/projects/<int:pid>/distributed-loads", methods=["POST"])
def add_dist_load(pid):
    d = request.json or {}
    conn = get_conn()
    cur = conn.execute("""INSERT INTO distributed_loads(project_id,load_case_id,member_tag,load_type,w1,w2,distance_a,distance_b,direction)
        VALUES(?,?,?,?,?,?,?,?,?)""",
        (pid, d.get("load_case_id"), d.get("member_tag",""),
         d.get("load_type","UDL"), d.get("w1",0), d.get("w2",0),
         d.get("distance_a",0), d.get("distance_b",0), d.get("direction","GLOBAL-Y")))
    conn.commit()
    conn.close()
    return jsonify({"id": cur.lastrowid}), 201


@app.route("/api/distributed-loads/<int:dlid>", methods=["DELETE"])
def delete_dist_load(dlid):
    conn = get_conn()
    conn.execute("DELETE FROM distributed_loads WHERE id=?", (dlid,))
    conn.commit()
    conn.close()
    return jsonify({"message": "Deleted"})


@app.route("/api/projects/<int:pid>/load-combinations", methods=["GET"])
def list_combos(pid):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM load_combinations WHERE project_id=?", (pid,)).fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@app.route("/api/projects/<int:pid>/load-combinations/generate", methods=["POST"])
def generate_combos(pid):
    """Auto-generate ASCE 7 LRFD + ASD combinations for a project."""
    d = request.json or {}
    combo_type = d.get("type", "LRFD")
    combos = LRFD_COMBINATIONS if combo_type == "LRFD" else ASD_COMBINATIONS
    conn = get_conn()
    conn.execute("DELETE FROM load_combinations WHERE project_id=? AND combo_type=?", (pid, combo_type))
    for c in combos:
        conn.execute("INSERT INTO load_combinations(project_id,combo_name,combo_type,factors) VALUES(?,?,?,?)",
                     (pid, c["name"], combo_type, json.dumps(c["factors"])))
    conn.commit()
    conn.close()
    return jsonify({"message": f"Generated {len(combos)} {combo_type} combinations"})


@app.route("/api/load-combinations/<int:cid>", methods=["DELETE"])
def delete_combo(cid):
    conn = get_conn()
    conn.execute("DELETE FROM load_combinations WHERE id=?", (cid,))
    conn.commit()
    conn.close()
    return jsonify({"message": "Deleted"})


# ═══════════════════════════════════════════════════════════════
# SECTIONS & MATERIALS
# ═══════════════════════════════════════════════════════════════
@app.route("/api/sections", methods=["GET"])
def list_sections():
    sec_type = request.args.get("type")
    search   = request.args.get("q","")
    conn = get_conn()
    query = "SELECT * FROM sections WHERE 1=1"
    params = []
    if sec_type:
        query += " AND section_type=?"
        params.append(sec_type)
    if search:
        query += " AND designation LIKE ?"
        params.append(f"%{search}%")
    query += " ORDER BY weight_per_m"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@app.route("/api/sections/<designation>", methods=["GET"])
def get_section(designation):
    conn = get_conn()
    row = conn.execute("SELECT * FROM sections WHERE designation=?", (designation,)).fetchone()
    conn.close()
    if not row:
        return _json_error("Section not found", 404)
    return jsonify(row_to_dict(row))


@app.route("/api/materials", methods=["GET"])
def list_materials():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM materials").fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


# ═══════════════════════════════════════════════════════════════
# STRUCTURE / RACK
# ═══════════════════════════════════════════════════════════════
@app.route("/api/projects/<int:pid>/rack", methods=["GET"])
def list_racks(pid):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM pipe_rack_geometry WHERE project_id=?", (pid,)).fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@app.route("/api/projects/<int:pid>/rack", methods=["POST"])
def add_rack(pid):
    d = request.json or {}
    conn = get_conn()
    cur = conn.execute("""INSERT INTO pipe_rack_geometry
        (project_id,rack_tag,total_length,bay_span,number_of_bays,number_of_tiers,
         tier_heights,width_of_rack,column_spacing,orientation_angle,
         origin_x,origin_y,origin_z,bracing_type)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (pid, d.get("rack_tag","RACK-A"),
         d.get("total_length",27000), d.get("bay_span",9000),
         d.get("number_of_bays",3), d.get("number_of_tiers",2),
         d.get("tier_heights","[4000,7500]"),
         d.get("width_of_rack",6000),
         d.get("column_spacing","[]"),
         d.get("orientation_angle",0),
         d.get("origin_x",0), d.get("origin_y",0), d.get("origin_z",0),
         d.get("bracing_type","X-BRACE")))
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    return jsonify({"id": rid, "message": "Rack created"}), 201


@app.route("/api/rack/<int:rid>", methods=["PUT"])
def update_rack(rid):
    d = request.json or {}
    fields = ["rack_tag","total_length","bay_span","number_of_bays","number_of_tiers",
              "tier_heights","width_of_rack","column_spacing","orientation_angle",
              "origin_x","origin_y","origin_z","bracing_type"]
    sets = ", ".join(f"{f}=?" for f in fields if f in d)
    vals = [d[f] for f in fields if f in d]
    if sets:
        conn = get_conn()
        conn.execute(f"UPDATE pipe_rack_geometry SET {sets} WHERE id=?", vals + [rid])
        conn.commit()
        conn.close()
    return jsonify({"message": "Updated"})


@app.route("/api/rack/<int:rid>/generate-grid", methods=["POST"])
def generate_grid(rid):
    """Generate nodes and members from rack geometry."""
    conn = get_conn()
    rack = row_to_dict(conn.execute("SELECT * FROM pipe_rack_geometry WHERE id=?", (rid,)).fetchone())
    if not rack:
        conn.close()
        return _json_error("Rack not found", 404)
    pid = rack["project_id"]

    # Clear existing nodes and members for this rack
    conn.execute("DELETE FROM nodes WHERE rack_id=?", (rid,))
    conn.execute("DELETE FROM members WHERE rack_id=?", (rid,))

    nodes = generate_rack_nodes(rack)
    for n in nodes:
        conn.execute("""INSERT INTO nodes(project_id,rack_id,node_tag,x,y,z,node_type,is_support,support_type)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            (n["project_id"], n["rack_id"], n["node_tag"], n["x"], n["y"], n["z"],
             n["node_type"], n["is_support"], n.get("support_type")))

    # Reload nodes as dict
    node_rows = conn.execute("SELECT * FROM nodes WHERE rack_id=?", (rid,)).fetchall()
    nodes_dict = {r["node_tag"]: dict(r) for r in node_rows}

    members = generate_rack_members(rack, nodes_dict)

    # Get default section and material
    default_sec = conn.execute("SELECT * FROM sections WHERE section_type='W' ORDER BY weight_per_m LIMIT 1").fetchone()
    default_mat = conn.execute("SELECT * FROM materials WHERE name='A992' OR name='A36' LIMIT 1").fetchone()
    sid = default_sec["id"] if default_sec else None
    mid = default_mat["id"] if default_mat else None

    for m in members:
        conn.execute("""INSERT INTO members(project_id,rack_id,member_tag,member_type,
            start_node,end_node,length_mm,unbraced_length,k_factor,section_id,material_id)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (m["project_id"], m["rack_id"], m["member_tag"], m["member_type"],
             m["start_node"], m["end_node"], m["length_mm"],
             m.get("unbraced_length", m["length_mm"]),
             m.get("k_factor",1.0), sid, mid))

    # ── Equipment support members ──────────────────────────────────
    eq_rows = conn.execute(
        "SELECT * FROM equipment WHERE project_id=?", (pid,)
    ).fetchall()
    equipment_list = rows_to_list(eq_rows)

    if equipment_list:
        sup_members, sup_nodes = generate_equipment_support_members(
            rack, equipment_list, nodes_dict, start_idx=500
        )
        for n in sup_nodes:
            conn.execute(
                """INSERT INTO nodes(project_id,rack_id,node_tag,x,y,z,node_type,is_support,support_type)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (n["project_id"], n["rack_id"], n["node_tag"],
                 n["x"], n["y"], n["z"], n["node_type"], n["is_support"], None)
            )
        for m in sup_members:
            conn.execute(
                """INSERT INTO members(project_id,rack_id,member_tag,member_type,
                   start_node,end_node,length_mm,unbraced_length,k_factor,section_id,material_id)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (m["project_id"], m["rack_id"], m["member_tag"], m["member_type"],
                 m["start_node"], m["end_node"], m["length_mm"],
                 m.get("unbraced_length", m["length_mm"]),
                 m.get("k_factor", 1.0), sid, mid)
            )
        n_sup_nodes   = len(sup_nodes)
        n_sup_members = len(sup_members)
    else:
        n_sup_nodes = n_sup_members = 0

    conn.commit()

    n_nodes   = len(nodes) + n_sup_nodes
    n_members = len(members) + n_sup_members
    conn.close()

    return jsonify({
        "message": f"Generated {n_nodes} nodes and {n_members} members "
                   f"({n_sup_members} equipment support members)",
        "nodes": n_nodes,
        "members": n_members,
        "support_members": n_sup_members,
    })


@app.route("/api/projects/<int:pid>/nodes", methods=["GET"])
def list_nodes(pid):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM nodes WHERE project_id=? ORDER BY node_tag", (pid,)).fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@app.route("/api/projects/<int:pid>/members", methods=["GET"])
def list_members(pid):
    conn = get_conn()
    rows = conn.execute("""
        SELECT m.*, s.designation as section_name, s.weight_per_m,
               mat.name as material_name, mat.fy
        FROM members m
        LEFT JOIN sections s ON m.section_id = s.id
        LEFT JOIN materials mat ON m.material_id = mat.id
        WHERE m.project_id=?
        ORDER BY m.member_tag""", (pid,)).fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@app.route("/api/members/<int:mid>", methods=["PUT"])
def update_member(mid):
    d = request.json or {}
    fields = ["member_tag","member_type","section_id","material_id","k_factor","unbraced_length"]
    sets = ", ".join(f"{f}=?" for f in fields if f in d)
    vals = [d[f] for f in fields if f in d]
    if sets:
        conn = get_conn()
        conn.execute(f"UPDATE members SET {sets} WHERE id=?", vals + [mid])
        conn.commit()
        conn.close()
    return jsonify({"message": "Updated"})


# ═══════════════════════════════════════════════════════════════
# CALCULATIONS
# ═══════════════════════════════════════════════════════════════
@app.route("/api/projects/<int:pid>/calculate/section-checks", methods=["POST"])
def run_section_checks(pid):
    """Run AISC 360 checks for all members."""
    conn = get_conn()
    members = rows_to_list(conn.execute("""
        SELECT m.*, s.designation,s.d,s.bf,s.tw,s.tf,s.area,s.ix,s.sx,s.zx,s.rx,
               s.iy,s.sy,s.zy,s.ry,s.j,s.cw,
               mat.fy,mat.fu,mat.e_modulus,mat.name as mat_name
        FROM members m
        LEFT JOIN sections s ON m.section_id=s.id
        LEFT JOIN materials mat ON m.material_id=mat.id
        WHERE m.project_id=?""", (pid,)).fetchall())

    combos = rows_to_list(conn.execute("SELECT * FROM load_combinations WHERE project_id=?", (pid,)).fetchall())
    dist_loads = rows_to_list(conn.execute("""
        SELECT dl.*, lc.name as lc_name FROM distributed_loads dl
        LEFT JOIN load_cases lc ON dl.load_case_id=lc.id
        WHERE dl.project_id=?""", (pid,)).fetchall())

    # Clear old results
    conn.execute("DELETE FROM member_results WHERE project_id=?", (pid,))

    all_results = []
    for m in members:
        sec = {k: m.get(k) for k in ["d","bf","tw","tf","area","ix","sx","zx","rx",
                                       "iy","sy","zy","ry","j","cw"]}
        mat = {"fy": m.get("fy",250), "fu": m.get("fu",400), "e_modulus": m.get("e_modulus",200000)}

        if not sec.get("area"):
            continue  # no section assigned

        # Build loads per combo
        loads_by_combo = {}
        for combo in combos:
            factors = json.loads(combo.get("factors","{}"))
            w_dl = 0
            w_ll = 0
            # Get UDL from distributed loads on this member
            for dl in dist_loads:
                if dl.get("member_tag") == m.get("member_tag"):
                    lc_name = dl.get("lc_name","")
                    w1 = dl.get("w1",0)
                    lc_type_map = {"DL":"DL","LL":"LL","WL-X":"WL","WL-Y":"WL","EQ-X":"EQ","EQ-Y":"EQ"}
                    for code, ftype in lc_type_map.items():
                        if lc_name == code:
                            f = factors.get(ftype, factors.get(code, 0))
                            if lc_name in ("DL","ERE"):
                                w_dl += w1 * f
                            else:
                                w_ll += w1 * f

            wu = w_dl + w_ll
            L  = m.get("length_mm",1000)
            Mu = wu * L**2 / 8  # N.mm
            Vu = wu * L / 2
            loads_by_combo[combo["combo_name"]] = {
                "wu": wu, "Mu": Mu, "Vu": Vu, "Pu": 0, "w_svc": wu/1.35
            }

        # Fall back to a simple gravity check if no combos defined
        if not loads_by_combo:
            loads_by_combo["GRAVITY"] = {"wu":0, "Mu":0, "Vu":0, "Pu":0, "w_svc":0}

        results = check_member(m, sec, mat, loads_by_combo)
        for r in results:
            conn.execute("""INSERT INTO member_results
                (project_id,member_tag,combo_name,axial_force,shear_y,moment_z,
                 max_deflection_mm,uc_bending,uc_shear,uc_axial,uc_combined,
                 phi_mn,phi_vn,phi_pn,status)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (pid, r["member_tag"], r["combo_name"],
                 r.get("axial_force",0), r.get("shear_y",0), r.get("moment_z",0),
                 r.get("max_deflection",0), r.get("uc_bending",0), r.get("uc_shear",0),
                 r.get("uc_axial",0), r.get("uc_combined",0),
                 r.get("phi_mn",0), r.get("phi_vn",0), r.get("phi_pn",0),
                 r.get("status","UNCHECKED")))
        all_results.extend(results)

    conn.commit()
    conn.close()

    n_fail = sum(1 for r in all_results if r.get("status") == "FAIL")
    n_marg = sum(1 for r in all_results if r.get("status") == "MARGINAL")
    return jsonify({
        "message": f"Checked {len(members)} members × {len(combos)} combos",
        "total_checks": len(all_results),
        "failed": n_fail,
        "marginal": n_marg,
    })


@app.route("/api/projects/<int:pid>/calculate/reactions", methods=["POST"])
def run_reactions(pid):
    """Calculate support reactions for all load cases."""
    conn = get_conn()
    racks = rows_to_list(conn.execute("SELECT * FROM pipe_rack_geometry WHERE project_id=?", (pid,)).fetchall())
    members_all = rows_to_list(conn.execute("SELECT * FROM members WHERE project_id=?", (pid,)).fetchall())
    nodal_loads = rows_to_list(conn.execute("""
        SELECT nl.*, lc.name as lc_name FROM nodal_loads nl
        LEFT JOIN load_cases lc ON nl.load_case_id=lc.id
        WHERE nl.project_id=?""", (pid,)).fetchall())
    dist_loads = rows_to_list(conn.execute("""
        SELECT dl.*, lc.name as lc_name FROM distributed_loads dl
        LEFT JOIN load_cases lc ON dl.load_case_id=lc.id
        WHERE dl.project_id=?""", (pid,)).fetchall())
    nodes = rows_to_list(conn.execute("SELECT * FROM nodes WHERE project_id=? AND is_support=1", (pid,)).fetchall())

    # Group loads by case
    nl_by_case = {}
    for nl in nodal_loads:
        k = nl.get("lc_name","UNKNOWN")
        nl_by_case.setdefault(k, []).append(nl)

    dl_by_case = {}
    for dl in dist_loads:
        k = dl.get("lc_name","UNKNOWN")
        # Attach member length
        for m in members_all:
            if m.get("member_tag") == dl.get("member_tag"):
                dl["member_length_mm"] = m.get("length_mm",6000)
                # Get support nodes for this beam (start and end)
                dl["support_nodes"] = [m.get("start_node"), m.get("end_node")]
                break
        dl_by_case.setdefault(k, []).append(dl)

    # Self-weight dead loads on columns
    sw_loads = {}
    conn2 = get_conn()
    for m in members_all:
        if m.get("member_type") not in ("BEAM","STRINGER","COLUMN"):
            continue
        sec = row_to_dict(conn2.execute("SELECT * FROM sections WHERE id=?", (m.get("section_id"),)).fetchone() or {})
        if not sec:
            continue
        w_pm = sec.get("weight_per_m", 0)
        L    = m.get("length_mm",0)
        W_sw = w_pm * 9.81 * L / 1000   # N (kg/m * 9.81 m/s2 * mm / 1000)

        # Apply to start and end nodes equally
        for node_tag in [m.get("start_node"), m.get("end_node")]:
            if node_tag:
                sw_loads.setdefault(node_tag, 0)
                sw_loads[node_tag] -= W_sw / 2   # negative = downward

    conn2.close()
    for node_tag, fy in sw_loads.items():
        nl_by_case.setdefault("DL", []).append({
            "node_tag": node_tag, "fx":0, "fy": fy, "fz":0, "load_source":"SELF_WEIGHT"
        })

    # Also include equipment loads
    eq_list = rows_to_list(conn.execute("SELECT * FROM equipment WHERE project_id=?", (pid,)).fetchall())
    for eq in eq_list:
        W_op = eq.get("weight_operating", 0) * 9.81   # N (kg → N)
        tier = eq.get("tier_level",1)
        bay  = eq.get("bay_number",1)
        # Map to nearest node (simplified: use bay column-A node at tier)
        node_tag = f"A{bay}T{tier}"
        nl_by_case.setdefault("DL", []).append({
            "node_tag": node_tag, "fx":0, "fy": -W_op, "fz":0, "load_source":"EQUIPMENT"
        })

    # Calculate reactions per load case
    if racks:
        reactions_raw = calculate_reactions(racks[0], members_all, nl_by_case, dl_by_case)
    else:
        reactions_raw = {}

    # Generate LRFD-2 (governing gravity) combination reactions
    lrfd2_factors = {"DL":1.2, "LL":1.6, "ERE":1.2}
    combo_reactions = {}
    for node_tag, by_case in reactions_raw.items():
        combo_reactions.setdefault(node_tag, {})
        for combo in ["GRAVITY-LRFD", "WIND-LRFD", "SEISMIC-LRFD"]:
            combo_reactions[node_tag][combo] = {"rx":0,"ry":0,"rz":0,"rmx":0,"rmy":0,"rmz":0}

        # LRFD-2: 1.2DL + 1.6LL
        for lc, f in lrfd2_factors.items():
            if lc in by_case:
                for comp in ["rx","ry","rz","rmx","rmy","rmz"]:
                    combo_reactions[node_tag]["GRAVITY-LRFD"][comp] += by_case[lc].get(comp,0) * f

        # Wind combo: 1.2DL + 1.0WL + 1.0LL
        for lc in ["DL","LL","WL-X","WL-Y"]:
            f = 1.2 if lc=="DL" else 1.0
            if lc in by_case:
                for comp in ["rx","ry","rz","rmx","rmy","rmz"]:
                    combo_reactions[node_tag]["WIND-LRFD"][comp] += by_case[lc].get(comp,0) * f

        # Seismic: 1.2DL + 1.0EQ + 1.0LL
        for lc in ["DL","LL","EQ-X","EQ-Y"]:
            f = 1.2 if lc=="DL" else 1.0
            if lc in by_case:
                for comp in ["rx","ry","rz","rmx","rmy","rmz"]:
                    combo_reactions[node_tag]["SEISMIC-LRFD"][comp] += by_case[lc].get(comp,0) * f

    # Save to DB
    conn.execute("DELETE FROM support_reactions WHERE project_id=?", (pid,))
    for node_tag, by_case in reactions_raw.items():
        for lc_name, vals in by_case.items():
            conn.execute("""INSERT INTO support_reactions(project_id,node_tag,load_case,rx,ry,rz,rmx,rmy,rmz)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (pid, node_tag, lc_name, vals["rx"], vals["ry"], vals["rz"],
                 vals["rmx"], vals["rmy"], vals["rmz"]))

    for node_tag, by_combo in combo_reactions.items():
        for combo_name, vals in by_combo.items():
            conn.execute("""INSERT INTO support_reactions(project_id,node_tag,combo_name,rx,ry,rz,rmx,rmy,rmz)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (pid, node_tag, combo_name, vals["rx"], vals["ry"], vals["rz"],
                 vals["rmx"], vals["rmy"], vals["rmz"]))

    conn.commit()
    conn.close()

    return jsonify({
        "message": f"Reactions calculated for {len(reactions_raw)} support nodes",
        "support_nodes": len(reactions_raw),
    })


@app.route("/api/projects/<int:pid>/calculate/foundations", methods=["POST"])
def run_foundations(pid):
    """Design spread footings for all support nodes."""
    conn = get_conn()
    proj = row_to_dict(conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone())
    nodes = rows_to_list(conn.execute(
        "SELECT * FROM nodes WHERE project_id=? AND is_support=1", (pid,)).fetchall())

    # Get envelope reactions (worst vertical + moments)
    reactions = rows_to_list(conn.execute("""
        SELECT node_tag, MAX(ABS(ry)) as max_ry, MAX(ABS(rx)) as max_rx,
               MAX(ABS(rz)) as max_rz, MAX(ABS(rmx)) as max_rmx, MAX(ABS(rmy)) as max_rmy
        FROM support_reactions WHERE project_id=?
        GROUP BY node_tag""", (pid,)).fetchall())

    # Get default column section dimensions
    col_sec = row_to_dict(conn.execute("""
        SELECT s.* FROM members m
        JOIN sections s ON m.section_id=s.id
        WHERE m.project_id=? AND m.member_type='COLUMN' LIMIT 1""", (pid,)).fetchone() or {})

    col_w = col_sec.get("d", 200) if col_sec else 200
    col_d = col_sec.get("bf", 200) if col_sec else 200

    soil_bearing = proj.get("soil_bearing", 150) if proj else 150
    soil_depth   = proj.get("soil_depth", 1500) if proj else 1500

    conn.execute("DELETE FROM foundations WHERE project_id=?", (pid,))

    reactions_dict = {r["node_tag"]: r for r in reactions}
    footing_results = []

    for i, node in enumerate(nodes):
        tag = node["node_tag"]
        r   = reactions_dict.get(tag, {"max_ry":100000,"max_rx":0,"max_rz":0,"max_rmx":0,"max_rmy":0})

        Pu  = abs(r.get("max_ry", 100000))   # N vertical
        Mux = abs(r.get("max_rmx", 0))
        Muy = abs(r.get("max_rmy", 0))
        Hx  = abs(r.get("max_rx", 0))
        Hz  = abs(r.get("max_rz", 0))

        if Pu < 50000:
            Pu = 200000  # minimum design load 200kN

        result = design_spread_footing(
            Pu_N=Pu, Mux_Nmm=Mux, Muy_Nmm=Muy, Hx_N=Hx, Hz_N=Hz,
            col_width_mm=col_w, col_depth_mm=col_d,
            soil_bearing_kpa=soil_bearing,
            depth_mm=soil_depth,
            fc_mpa=28, fy_mpa=420,
            project_id=pid,
            node_tag=tag,
            footing_tag=f"F-{i+101:03d}",
        )

        conn.execute("""INSERT INTO foundations
            (project_id,footing_tag,node_tag,footing_type,length_mm,width_mm,depth_mm,
             thickness_mm,soil_bearing_kpa,concrete_fc_mpa,steel_fy_mpa,
             rebar_top_x,rebar_top_y,rebar_bot_x,rebar_bot_y,
             bearing_actual_kpa,uc_punching,uc_shear_x,uc_shear_y,
             uc_flexure_x,uc_flexure_y,as_req_x_mm2pm,as_req_y_mm2pm,status)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (pid, result["footing_tag"], tag, result["footing_type"],
             result["length_mm"], result["width_mm"], result["depth_mm"],
             result["thickness_mm"], result["soil_bearing_kpa"],
             result["concrete_fc_mpa"], result["steel_fy_mpa"],
             result["rebar_top_x"], result["rebar_top_y"],
             result["rebar_bot_x"], result["rebar_bot_y"],
             result["bearing_actual_kpa"],
             result["uc_punching"], result["uc_shear_x"], result["uc_shear_y"],
             result["uc_flexure_x"], result["uc_flexure_y"],
             result["as_req_x_mm2pm"], result["as_req_y_mm2pm"],
             result["status"]))
        footing_results.append(result)

    conn.commit()
    conn.close()

    n_fail = sum(1 for r in footing_results if r["status"] == "FAIL")
    return jsonify({
        "message": f"Designed {len(footing_results)} footings",
        "footings": len(footing_results),
        "failed": n_fail,
    })


@app.route("/api/projects/<int:pid>/calculate/all", methods=["POST"])
def run_all(pid):
    """Run complete analysis: reactions → section checks → foundations."""
    results = {}
    with app.test_request_context():
        pass

    # Step 1: reactions
    with app.test_client() as client:
        r = client.post(f"/api/projects/{pid}/calculate/reactions")
        results["reactions"] = r.get_json()

        r = client.post(f"/api/projects/{pid}/calculate/section-checks")
        results["section_checks"] = r.get_json()

        r = client.post(f"/api/projects/{pid}/calculate/foundations")
        results["foundations"] = r.get_json()

    return jsonify({"message": "Complete analysis done", "results": results})


# ═══════════════════════════════════════════════════════════════
# RESULTS
# ═══════════════════════════════════════════════════════════════
@app.route("/api/projects/<int:pid>/results/members", methods=["GET"])
def get_member_results(pid):
    conn = get_conn()
    rows = conn.execute("""
        SELECT mr.*, m.member_type, s.designation as section, s.weight_per_m
        FROM member_results mr
        LEFT JOIN members m ON mr.member_tag=m.member_tag AND m.project_id=mr.project_id
        LEFT JOIN sections s ON m.section_id=s.id
        WHERE mr.project_id=?
        ORDER BY mr.uc_combined DESC""", (pid,)).fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@app.route("/api/projects/<int:pid>/results/reactions", methods=["GET"])
def get_reaction_results(pid):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM support_reactions WHERE project_id=? ORDER BY node_tag", (pid,)).fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@app.route("/api/projects/<int:pid>/results/foundations", methods=["GET"])
def get_foundation_results(pid):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM foundations WHERE project_id=? ORDER BY footing_tag", (pid,)).fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@app.route("/api/projects/<int:pid>/results/summary", methods=["GET"])
def get_summary(pid):
    conn = get_conn()
    eq_count = conn.execute("SELECT COUNT(*) FROM equipment WHERE project_id=?", (pid,)).fetchone()[0]
    member_total = conn.execute("SELECT COUNT(DISTINCT member_tag) FROM member_results WHERE project_id=?", (pid,)).fetchone()[0]
    member_fail  = conn.execute("SELECT COUNT(*) FROM member_results WHERE project_id=? AND status='FAIL'", (pid,)).fetchone()[0]
    member_marg  = conn.execute("SELECT COUNT(*) FROM member_results WHERE project_id=? AND status='MARGINAL'", (pid,)).fetchone()[0]
    foot_total   = conn.execute("SELECT COUNT(*) FROM foundations WHERE project_id=?", (pid,)).fetchone()[0]
    foot_fail    = conn.execute("SELECT COUNT(*) FROM foundations WHERE project_id=? AND status='FAIL'", (pid,)).fetchone()[0]
    max_uc       = conn.execute("SELECT MAX(uc_combined) FROM member_results WHERE project_id=?", (pid,)).fetchone()[0]
    max_bearing  = conn.execute("SELECT MAX(bearing_actual_kpa) FROM foundations WHERE project_id=?", (pid,)).fetchone()[0]
    conn.close()

    return jsonify({
        "equipment_count": eq_count,
        "member_total":    member_total,
        "member_fail":     member_fail,
        "member_marginal": member_marg,
        "member_pass":     member_total - member_fail - member_marg,
        "footing_total":   foot_total,
        "footing_fail":    foot_fail,
        "max_uc":          round(max_uc or 0, 3),
        "max_bearing_kpa": round(max_bearing or 0, 1),
        "overall_status":  "FAIL" if (member_fail or foot_fail) else "PASS",
    })


# ═══════════════════════════════════════════════════════════════
# CSV IMPORT / EXPORT
# ═══════════════════════════════════════════════════════════════
@app.route("/api/projects/<int:pid>/import/equipment-csv", methods=["POST"])
def import_equipment_csv(pid):
    file = request.files.get("file")
    if not file:
        return _json_error("No file uploaded")

    content = file.read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))
    conn = get_conn()
    added = 0
    errors = []

    for i, row in enumerate(reader, 1):
        try:
            tag = row.get("TAG","").strip()
            if not tag:
                errors.append(f"Row {i}: Missing TAG")
                continue
            conn.execute("""INSERT OR REPLACE INTO equipment
                (project_id,tag,type,description,weight_empty,weight_operating,weight_test,
                 length_mm,diameter_mm,height_mm,cog_x,cog_y,cog_z,
                 pos_x,pos_y,pos_z,orientation,elevation,tier_level,bay_number,support_type,notes)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (pid, tag, row.get("TYPE","VESSEL"), row.get("DESCRIPTION",""),
                 float(row.get("WEIGHT_EMPTY_KG",0) or 0),
                 float(row.get("WEIGHT_OPERATING_KG",0) or 0),
                 float(row.get("WEIGHT_TEST_KG",0) or 0),
                 float(row.get("LENGTH_MM",0) or 0),
                 float(row.get("DIAMETER_MM",0) or 0),
                 float(row.get("HEIGHT_MM",0) or 0),
                 float(row.get("COG_X",0) or 0), float(row.get("COG_Y",0) or 0),
                 float(row.get("COG_Z",0) or 0),
                 float(row.get("POS_X",0) or 0), float(row.get("POS_Y",0) or 0),
                 float(row.get("POS_Z",0) or 0),
                 row.get("ORIENTATION","H"), float(row.get("ELEVATION",0) or 0),
                 int(row.get("TIER_LEVEL",1) or 1), int(row.get("BAY_NUMBER",1) or 1),
                 row.get("SUPPORT_TYPE","SKID"), row.get("NOTES","")))
            added += 1
        except Exception as e:
            errors.append(f"Row {i}: {str(e)}")

    conn.commit()
    conn.close()
    return jsonify({"added": added, "errors": errors})


@app.route("/api/templates/equipment-csv", methods=["GET"])
def download_equipment_template():
    headers = ("TAG,TYPE,DESCRIPTION,WEIGHT_EMPTY_KG,WEIGHT_OPERATING_KG,WEIGHT_TEST_KG,"
               "LENGTH_MM,DIAMETER_MM,HEIGHT_MM,COG_X,COG_Y,COG_Z,"
               "POS_X,POS_Y,POS_Z,ORIENTATION,ELEVATION,TIER_LEVEL,BAY_NUMBER,SUPPORT_TYPE,NOTES\n"
               "V-101,VESSEL,Feed Drum,5000,15000,25000,3000,1200,3500,0,1750,0,0,3500,0,V,3500,1,1,SKID,\n"
               "E-101,EXCHANGER,Feed/Effluent Exch,8000,22000,30000,6000,1000,1200,3000,600,0,9000,3500,0,H,1200,1,2,SADDLE,\n"
               "P-101A,PUMP,Feed Pump,500,600,0,1500,400,800,750,400,0,0,1000,0,H,1000,1,1,SKID,\n")
    return send_file(io.BytesIO(headers.encode()), mimetype="text/csv",
                     as_attachment=True, download_name="equipment_template.csv")


@app.route("/api/templates/equipment-sample", methods=["GET"])
def download_equipment_sample():
    """Download the filled sample equipment CSV (tanks, vessels, reactors, pumps, blowers)."""
    sample_path = os.path.join(os.path.dirname(__file__), "csv_templates", "equipment_sample.csv")
    return send_file(sample_path, mimetype="text/csv",
                     as_attachment=True, download_name="equipment_sample.csv")


@app.route("/api/templates/nozzles-csv", methods=["GET"])
def download_nozzles_template():
    sample_path = os.path.join(os.path.dirname(__file__), "csv_templates", "nozzles_sample.csv")
    return send_file(sample_path, mimetype="text/csv",
                     as_attachment=True, download_name="nozzles_sample.csv")


@app.route("/api/projects/<int:pid>/import/nozzles-csv", methods=["POST"])
def import_nozzles_csv(pid):
    """
    Import nozzle loads from CSV.
    Matches equipment by TAG; inserts nozzles with force/moment data.
    """
    file = request.files.get("file")
    if not file:
        return _json_error("No file uploaded")

    content = file.read().decode("utf-8")
    reader  = csv.DictReader(io.StringIO(content))
    conn    = get_conn()
    added   = 0
    skipped = 0
    errors  = []

    # Build tag→id lookup for this project
    eq_rows = conn.execute(
        "SELECT id, tag FROM equipment WHERE project_id=?", (pid,)).fetchall()
    eq_map = {r["tag"]: r["id"] for r in eq_rows}

    for i, row in enumerate(reader, 1):
        try:
            eq_tag = row.get("EQUIPMENT_TAG", "").strip()
            if not eq_tag:
                errors.append(f"Row {i}: Missing EQUIPMENT_TAG")
                continue
            eid = eq_map.get(eq_tag)
            if eid is None:
                errors.append(f"Row {i}: Equipment '{eq_tag}' not found in project — import equipment first")
                skipped += 1
                continue

            conn.execute("""
                INSERT INTO nozzles(equipment_id,nozzle_tag,service,size_dn,rating,
                    pos_x,pos_y,pos_z,direction,force_fx,force_fy,force_fz,
                    moment_mx,moment_my,moment_mz)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (eid,
                 row.get("NOZZLE_TAG","N?").strip(),
                 row.get("SERVICE","").strip(),
                 float(row.get("SIZE_DN",50) or 50),
                 row.get("RATING","150#").strip(),
                 float(row.get("POS_X",0) or 0),
                 float(row.get("POS_Y",0) or 0),
                 float(row.get("POS_Z",0) or 0),
                 row.get("DIRECTION","+Z").strip(),
                 float(row.get("FX_N",0) or 0),
                 float(row.get("FY_N",0) or 0),
                 float(row.get("FZ_N",0) or 0),
                 float(row.get("MX_NMM",0) or 0),
                 float(row.get("MY_NMM",0) or 0),
                 float(row.get("MZ_NMM",0) or 0)))
            added += 1
        except Exception as e:
            errors.append(f"Row {i}: {str(e)}")

    # After importing nozzles, automatically push resultant nozzle loads
    # to nodal loads (OL load case) for each equipment's rack position
    lc_ol = conn.execute(
        "SELECT id FROM load_cases WHERE project_id=? AND name='OL' LIMIT 1", (pid,)).fetchone()
    lc_id = lc_ol["id"] if lc_ol else None

    if lc_id:
        nozzle_rows = conn.execute("""
            SELECT n.*, e.tier_level, e.bay_number, e.pos_x, e.pos_y
            FROM nozzles n
            JOIN equipment e ON n.equipment_id = e.id
            WHERE e.project_id=?""", (pid,)).fetchall()

        # Group nozzle loads by (tier, bay) → sum into OL nodal loads
        node_loads = {}
        for nr in nozzle_rows:
            node_tag = f"A{nr['bay_number']}T{nr['tier_level']}"
            if node_tag not in node_loads:
                node_loads[node_tag] = {"fx":0,"fy":0,"fz":0,"mx":0,"my":0,"mz":0}
            node_loads[node_tag]["fx"] += nr["force_fx"] or 0
            node_loads[node_tag]["fy"] += nr["force_fy"] or 0
            node_loads[node_tag]["fz"] += nr["force_fz"] or 0
            node_loads[node_tag]["mx"] += nr["moment_mx"] or 0
            node_loads[node_tag]["my"] += nr["moment_my"] or 0
            node_loads[node_tag]["mz"] += nr["moment_mz"] or 0

        # Remove previous auto-generated OL nodal loads
        conn.execute("""DELETE FROM nodal_loads
            WHERE project_id=? AND load_case_id=? AND load_source='NOZZLE'""", (pid, lc_id))

        for node_tag, frc in node_loads.items():
            conn.execute("""INSERT INTO nodal_loads
                (project_id,load_case_id,node_tag,fx,fy,fz,mx,my,mz,load_source)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (pid, lc_id, node_tag,
                 round(frc["fx"],1), round(frc["fy"],1), round(frc["fz"],1),
                 round(frc["mx"],1), round(frc["my"],1), round(frc["mz"],1),
                 "NOZZLE"))

    conn.commit()
    conn.close()
    return jsonify({
        "added": added,
        "skipped": skipped,
        "nodal_loads_generated": len(node_loads) if lc_id else 0,
        "errors": errors,
    })


@app.route("/api/templates/loads-csv", methods=["GET"])
def download_loads_template():
    headers = ("NODE_TAG,LOAD_CASE,FX_N,FY_N,FZ_N,MX_NMM,MY_NMM,MZ_NMM,SOURCE\n"
               "A1T1,DL,0,-50000,0,0,0,0,EQUIPMENT\n"
               "A2T2,OL,5000,-20000,3000,500000,200000,300000,NOZZLE\n")
    return send_file(io.BytesIO(headers.encode()), mimetype="text/csv",
                     as_attachment=True, download_name="loads_template.csv")


@app.route("/api/projects/<int:pid>/export/results-csv", methods=["GET"])
def export_results_csv(pid):
    conn = get_conn()
    rows = rows_to_list(conn.execute("""
        SELECT mr.member_tag, mr.combo_name, mr.axial_force, mr.shear_y, mr.moment_z,
               mr.max_deflection_mm, mr.uc_bending, mr.uc_shear, mr.uc_axial,
               mr.uc_combined, mr.status, s.designation as section
        FROM member_results mr
        LEFT JOIN members m ON mr.member_tag=m.member_tag AND m.project_id=mr.project_id
        LEFT JOIN sections s ON m.section_id=s.id
        WHERE mr.project_id=?""", (pid,)).fetchall())
    conn.close()

    if not rows:
        return _json_error("No results to export")

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
    return send_file(io.BytesIO(buf.getvalue().encode()), mimetype="text/csv",
                     as_attachment=True, download_name=f"results_project_{pid}.csv")


# ═══════════════════════════════════════════════════════════════
# SECTION CAPACITY CALCULATOR (standalone)
# ═══════════════════════════════════════════════════════════════
@app.route("/api/sections/<designation>/capacity", methods=["POST"])
def section_capacity(designation):
    """Calculate capacities for a given section + material + parameters."""
    d   = request.json or {}
    fy  = d.get("fy", 250)
    E   = d.get("E", 200000)
    Lb  = d.get("Lb", 0)
    KL  = d.get("KL", 0)

    conn = get_conn()
    sec = row_to_dict(conn.execute("SELECT * FROM sections WHERE designation=?", (designation,)).fetchone())
    conn.close()
    if not sec:
        return _json_error("Section not found", 404)

    return jsonify({
        "designation": designation,
        "phi_Mn_kNm": round(flexural_capacity(sec, fy, E, Lb=Lb) / 1e6, 2),
        "phi_Vn_kN":  round(shear_capacity(sec, fy, E) / 1e3, 2),
        "phi_Pn_kN":  round(axial_compression_capacity(sec, fy, E, KL=KL) / 1e3, 2),
    })


if __name__ == "__main__":
    init_db()
    print("EPC Design Software — starting on http://localhost:5000")
    app.run(debug=True, port=5000)

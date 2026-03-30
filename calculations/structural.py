"""
calculations/structural.py
AISC 360-22 section adequacy checks + pipe rack span/tier sizing
All units: N, mm, MPa (N/mm2)
"""
import math
import json
from config import RACK_GUIDELINES


# ─────────────────────────────────────────────────────────────
# SECTION CHECKS (AISC 360-22, ASD/LRFD)
# ─────────────────────────────────────────────────────────────

def check_compactness(sec, fy, E=200000):
    """Return compactness classification for W-section flanges and web."""
    lp_f = 0.38 * math.sqrt(E / fy)
    lr_f = 1.0  * math.sqrt(E / fy)
    lp_w = 3.76 * math.sqrt(E / fy)
    lr_w = 5.70 * math.sqrt(E / fy)

    bf = sec.get("bf", 0)
    tf = sec.get("tf", 1)
    tw = sec.get("tw", 1)
    d  = sec.get("d", 0)

    lambda_f = bf / (2 * tf) if tf > 0 else 999
    lambda_w = (d - 2 * tf) / tw if tw > 0 else 999

    if lambda_f <= lp_f and lambda_w <= lp_w:
        return "COMPACT"
    elif lambda_f <= lr_f and lambda_w <= lr_w:
        return "NONCOMPACT"
    else:
        return "SLENDER"


def flexural_capacity(sec, fy, E=200000, Lb=0, Cb=1.0, phi=0.90):
    """
    AISC 360-22 Chapter F flexural capacity phi*Mn (N.mm)
    sec: section dict with Zx, Sx, rx, ry, J, d, tf, E
    Lb: unbraced length (mm)
    Cb: moment gradient factor (conservative = 1.0)
    Returns: phi_Mn (N.mm)
    """
    Zx = sec.get("zx", 0) or sec.get("Zx", 0)
    Sx = sec.get("sx", 0) or sec.get("Sx", 0)
    ry = sec.get("ry", 0) or sec.get("ry", 1)
    J  = sec.get("j",  0) or sec.get("J",  0)
    d  = sec.get("d",  0)
    tf = sec.get("tf", 0)
    Iy = sec.get("iy", 0) or sec.get("Iy", 0)

    Mp = fy * Zx   # plastic moment

    # rts approximation: sqrt(sqrt(Iy*Cw)/Sx) — use simplified rts ≈ ry for HSS
    Cw = sec.get("cw", 0) or sec.get("Cw", 0)
    if Cw > 0 and Sx > 0 and Iy > 0:
        rts = math.sqrt(math.sqrt(Iy * Cw) / Sx)
    else:
        rts = ry if ry > 0 else 1

    ho = d - tf  # distance between flange centroids

    # Lp, Lr per AISC F2
    Lp = 1.76 * ry * math.sqrt(E / fy) if ry > 0 else 0
    c  = 1.0  # doubly symmetric I-shape

    # Lr calculation
    if Sx > 0 and ho > 0 and J > 0 and rts > 0:
        term = (J * c / (Sx * ho))
        Lr = 1.95 * rts * (E / (0.7 * fy)) * math.sqrt(
            term + math.sqrt(term**2 + 6.76 * (0.7 * fy / E)**2)
        )
    else:
        Lr = Lp * 3  # fallback

    if Lb == 0 or Lb <= Lp:
        Mn = Mp
    elif Lb <= Lr:
        Mn = Cb * (Mp - (Mp - 0.7 * fy * Sx) * (Lb - Lp) / (Lr - Lp))
        Mn = min(Mn, Mp)
    else:
        # elastic LTB
        if rts > 0 and Lb > 0:
            Fcr = (Cb * math.pi**2 * E / (Lb / rts)**2) * math.sqrt(
                1 + 0.078 * J * c / (Sx * ho) * (Lb / rts)**2
            ) if ho > 0 and Sx > 0 else 0
        else:
            Fcr = 0
        Mn = Fcr * Sx

    Mn = min(Mn, Mp)
    return phi * Mn


def shear_capacity(sec, fy, E=200000, phi=1.00):
    """AISC 360-22 Chapter G shear capacity phi*Vn (N)."""
    d  = sec.get("d",  0)
    tw = sec.get("tw", 0)
    tf = sec.get("tf", 0)
    Aw = (d - 2 * tf) * tw  # web area

    # kv = 5.34 for unstiffened web
    kv = 5.34
    h_tw = (d - 2 * tf) / tw if tw > 0 else 999

    limit = 2.24 * math.sqrt(E / fy)
    if h_tw <= limit:
        Cv1 = 1.0
        phi = 1.00
    else:
        kv_limit = 1.10 * math.sqrt(kv * E / fy)
        if h_tw <= kv_limit:
            Cv1 = 1.0
        else:
            Cv1 = kv_limit / h_tw

    Vn = 0.6 * fy * Aw * Cv1
    return phi * Vn


def axial_compression_capacity(sec, fy, E=200000, KL=0, phi=0.90):
    """AISC 360-22 Chapter E compression capacity phi*Pn (N)."""
    A   = sec.get("area", 0)
    rx  = sec.get("rx", 0) or sec.get("rx", 1)
    ry  = sec.get("ry", 0) or sec.get("ry", 1)

    r = min(rx, ry) if rx > 0 and ry > 0 else max(rx, ry, 1)
    if r <= 0:
        r = 1

    slenderness = KL / r if KL > 0 and r > 0 else 0
    Fe = math.pi**2 * E / slenderness**2 if slenderness > 0 else 1e9

    limit = 4.71 * math.sqrt(E / fy)
    if slenderness <= limit:
        Fcr = (0.658 ** (fy / Fe)) * fy
    else:
        Fcr = 0.877 * Fe

    Pn = Fcr * A
    return phi * Pn


def axial_tension_capacity(sec, fy, fu, phi_t=0.90):
    """AISC 360-22 Chapter D tension capacity phi*Pn (N)."""
    A = sec.get("area", 0)
    return phi_t * fy * A


def deflection_simply_supported(w_per_mm, L, E, I):
    """Max deflection for UDL on simply supported beam (mm)."""
    if E <= 0 or I <= 0 or L <= 0:
        return 0
    return 5 * w_per_mm * L**4 / (384 * E * I)


def combined_check_H1(Pu, phi_Pn, Mux, phi_Mnx, Muy=0, phi_Mny=1e9):
    """AISC 360-22 H1-1 combined check. Returns UC ratio."""
    if phi_Pn <= 0:
        return 999
    ratio_p = abs(Pu) / phi_Pn
    ratio_m = abs(Mux) / phi_Mnx if phi_Mnx > 0 else 0
    ratio_m += abs(Muy) / phi_Mny if phi_Mny > 0 else 0

    if ratio_p >= 0.2:
        return ratio_p + (8/9) * ratio_m
    else:
        return ratio_p / 2 + ratio_m


def check_member(member, section, material, loads_by_combo):
    """
    Run all section checks for a member across all load combinations.
    Returns list of result dicts per combo.
    """
    fy = material.get("fy", 250)
    E  = material.get("e_modulus", 200000)
    L  = member.get("length_mm", 1000)
    KL = member.get("unbraced_length", L) * member.get("k_factor", 1.0)
    Lb = member.get("unbraced_length", L)
    mtype = member.get("member_type", "BEAM")

    phi_Mn = flexural_capacity(section, fy, E, Lb=Lb)
    phi_Vn = shear_capacity(section, fy, E)
    phi_Pn = axial_compression_capacity(section, fy, E, KL=KL)
    phi_Tn = axial_tension_capacity(section, fy, material.get("fu", 400))

    Ix = section.get("ix", 0) or section.get("Ix", 0)

    results = []
    for combo_name, forces in loads_by_combo.items():
        Mu  = forces.get("Mu", 0)   # N.mm
        Vu  = forces.get("Vu", 0)   # N
        Pu  = forces.get("Pu", 0)   # N (+ tension, - compression)
        w_u = forces.get("wu", 0)   # N/mm UDL for deflection

        # Unity checks
        uc_bend  = abs(Mu)  / phi_Mn if phi_Mn > 0 else 0
        uc_shear = abs(Vu)  / phi_Vn if phi_Vn > 0 else 0
        uc_axial = abs(Pu)  / phi_Pn if Pu < 0 else abs(Pu) / max(phi_Tn, 1)

        uc_comb  = combined_check_H1(Pu, phi_Pn if Pu < 0 else phi_Tn,
                                      Mu, phi_Mn)

        # Deflection (use unfactored LL for serviceability)
        w_svc = forces.get("w_svc", w_u / 1.6)  # rough unfactored
        delta = deflection_simply_supported(w_svc, L, E, Ix) if mtype == "BEAM" else 0
        allow_delta = L / RACK_GUIDELINES["max_beam_deflection_ratio"]

        uc_delta = delta / allow_delta if allow_delta > 0 else 0

        # Governing UC
        uc_gov = max(uc_bend, uc_shear, uc_comb)

        if uc_gov <= 0.90:
            status = "PASS"
        elif uc_gov <= 1.00:
            status = "MARGINAL"
        else:
            status = "FAIL"

        results.append({
            "member_tag":     member.get("member_tag"),
            "combo_name":     combo_name,
            "axial_force":    Pu,
            "shear_y":        Vu,
            "moment_z":       Mu,
            "max_deflection": round(delta, 2),
            "uc_bending":     round(uc_bend, 3),
            "uc_shear":       round(uc_shear, 3),
            "uc_axial":       round(uc_axial, 3),
            "uc_combined":    round(uc_comb, 3),
            "phi_mn":         round(phi_Mn / 1e6, 1),   # kN.m
            "phi_vn":         round(phi_Vn / 1e3, 1),   # kN
            "phi_pn":         round(phi_Pn / 1e3, 1),   # kN
            "status":         status,
        })
    return results


# ─────────────────────────────────────────────────────────────
# PIPE RACK GEOMETRY & SIZING
# ─────────────────────────────────────────────────────────────

def auto_size_rack(rack_config, equipment_list, pipe_loads_per_tier, sections, material):
    """
    Auto-generate tier heights and bay span for a pipe rack.
    rack_config: dict with width_of_rack, number_of_tiers, etc.
    pipe_loads_per_tier: [{"tier":1,"w_pipe_N_per_m":2000,"max_pipe_od_mm":300}, ...]
    sections: list of section dicts sorted by Ix ascending
    Returns: updated rack_config with tier_heights and suggested beam sections
    """
    fy = material.get("fy", 250)
    E  = material.get("e_modulus", 200000)
    g  = RACK_GUIDELINES

    # 1. Determine bay span
    chosen_span = None
    chosen_beam_section = None

    # Find the minimum span where the beam passes all checks
    for span in g["typical_bay_spans_mm"]:
        for sec in sections:
            if sec.get("section_type") != "W":
                continue
            Ix = sec.get("ix", 0)
            w  = sec.get("weight_per_m", 0)
            if Ix <= 0:
                continue

            # Worst-case tier: sum all pipe loads + self-weight
            max_pipe_udl = max((t["w_pipe_N_per_m"] for t in pipe_loads_per_tier), default=5000)
            w_sw = w * 9.81  # N/m self-weight
            w_total = max_pipe_udl * (1 + g["pipe_load_surcharge_pct"]) + w_sw
            w_mm = w_total / 1000  # N/mm

            # Factored for LRFD (1.2DL + 1.6LL)
            w_dl = (w_sw + max_pipe_udl * 0.7) / 1000   # dead: SW + 70% pipe
            w_ll = max_pipe_udl * 0.3 * (1 + g["pipe_load_surcharge_pct"]) / 1000
            wu   = 1.2 * w_dl + 1.6 * w_ll

            Mu  = wu * span**2 / 8
            phi_Mn = flexural_capacity(sec, fy, E, Lb=span)
            uc_b = Mu / phi_Mn if phi_Mn > 0 else 999

            Vu = wu * span / 2
            phi_Vn = shear_capacity(sec, fy, E)
            uc_v = Vu / phi_Vn if phi_Vn > 0 else 999

            # Serviceability deflection (unfactored LL)
            w_svc = w_ll / 1.6
            delta = deflection_simply_supported(w_svc, span, E, Ix)
            uc_d  = delta / (span / 360)

            if max(uc_b, uc_v, uc_d) <= 1.0:
                chosen_span = span
                chosen_beam_section = sec
                break

        if chosen_span:
            break

    if not chosen_span:
        chosen_span = g["typical_bay_spans_mm"][-1]
        chosen_beam_section = sections[-1] if sections else None

    # 2. Determine tier heights
    tier_heights = []
    current_height = g["min_bottom_clearance_mm"]

    for i, tier in enumerate(pipe_loads_per_tier):
        max_od = tier.get("max_pipe_od_mm", 300)
        tier_spacing = max(g["min_tier_spacing_mm"],
                          max_od + 300 + 500)  # pipe OD + clearances
        if i == 0:
            tier_heights.append(current_height)
        else:
            current_height += tier_spacing
            tier_heights.append(round(current_height / 50) * 50)  # round to 50mm

    return {
        "bay_span": chosen_span,
        "tier_heights": tier_heights,
        "suggested_beam_section": chosen_beam_section.get("designation") if chosen_beam_section else None,
        "number_of_tiers": len(tier_heights),
    }


def generate_rack_nodes(rack):
    """
    Generate node coordinates for a pipe rack.
    Returns list of node dicts.
    """
    nodes = []
    tier_heights = json.loads(rack.get("tier_heights", "[3500]"))
    tier_heights = [0] + tier_heights  # add grade level

    n_bays  = rack.get("number_of_bays", 3)
    bay_span = rack.get("bay_span", 9000)
    width   = rack.get("width_of_rack", 6000)
    ox = rack.get("origin_x", 0)
    oy = rack.get("origin_y", 0)
    oz = rack.get("origin_z", 0)

    col_spacings_raw = rack.get("column_spacing", "[]")
    try:
        col_spacings = json.loads(col_spacings_raw)
    except Exception:
        col_spacings = []

    if not col_spacings:
        col_spacings = [bay_span] * n_bays

    # Columns at X positions 0 and +width, Z positions per bay
    z_positions = [0]
    for span in col_spacings:
        z_positions.append(z_positions[-1] + span)

    col_x = [0, width]  # two column lines (near and far)
    rack_id = rack.get("id")
    project_id = rack.get("project_id")

    for ci, cx in enumerate(col_x):
        line = "A" if ci == 0 else "B"
        for bi, bz in enumerate(z_positions):
            for ti, ty in enumerate(tier_heights):
                tag = f"{line}{bi+1}T{ti}"
                nodes.append({
                    "project_id": project_id,
                    "rack_id": rack_id,
                    "node_tag": tag,
                    "x": ox + cx,
                    "y": oy + ty,
                    "z": oz + bz,
                    "node_type": "COLUMN_BASE" if ti == 0 else "FRAME_NODE",
                    "is_support": 1 if ti == 0 else 0,
                    "support_type": "PINNED" if ti == 0 else None,
                })
    return nodes


def generate_rack_members(rack, nodes_dict):
    """
    Generate members (beams, columns, braces) for a pipe rack.
    nodes_dict: {node_tag: node_dict}
    Returns list of member dicts.
    """
    members = []
    tier_heights = json.loads(rack.get("tier_heights", "[3500]"))
    tier_heights = [0] + tier_heights

    n_bays   = rack.get("number_of_bays", 3)
    n_tiers  = len(tier_heights) - 1
    bracing  = rack.get("bracing_type", "X-BRACE")
    rack_id  = rack.get("id")
    project_id = rack.get("project_id")

    member_idx = 1

    # Columns: A-line and B-line
    for line in ["A", "B"]:
        for bi in range(n_bays + 1):
            for ti in range(len(tier_heights) - 1):
                start_tag = f"{line}{bi+1}T{ti}"
                end_tag   = f"{line}{bi+1}T{ti+1}"
                if start_tag in nodes_dict and end_tag in nodes_dict:
                    n1 = nodes_dict[start_tag]
                    n2 = nodes_dict[end_tag]
                    L  = abs(n2["y"] - n1["y"])
                    members.append({
                        "project_id": project_id,
                        "rack_id": rack_id,
                        "member_tag": f"COL-{member_idx:03d}",
                        "member_type": "COLUMN",
                        "start_node": start_tag,
                        "end_node":   end_tag,
                        "length_mm":  L,
                        "unbraced_length": L,
                        "k_factor": 1.0,
                    })
                    member_idx += 1

    # Beams: across width (A to B) at each tier level above grade
    for bi in range(n_bays + 1):
        for ti in range(1, len(tier_heights)):
            start_tag = f"A{bi+1}T{ti}"
            end_tag   = f"B{bi+1}T{ti}"
            if start_tag in nodes_dict and end_tag in nodes_dict:
                n1 = nodes_dict[start_tag]
                n2 = nodes_dict[end_tag]
                L  = abs(n2["x"] - n1["x"])
                members.append({
                    "project_id": project_id,
                    "rack_id": rack_id,
                    "member_tag": f"BM-{member_idx:03d}",
                    "member_type": "BEAM",
                    "start_node": start_tag,
                    "end_node":   end_tag,
                    "length_mm":  L,
                    "unbraced_length": L,
                    "k_factor": 1.0,
                })
                member_idx += 1

    # Longitudinal stringers (along Z, top chord) at each tier
    for line in ["A", "B"]:
        for ti in range(1, len(tier_heights)):
            for bi in range(n_bays):
                start_tag = f"{line}{bi+1}T{ti}"
                end_tag   = f"{line}{bi+2}T{ti}"
                if start_tag in nodes_dict and end_tag in nodes_dict:
                    n1 = nodes_dict[start_tag]
                    n2 = nodes_dict[end_tag]
                    L  = abs(n2["z"] - n1["z"])
                    members.append({
                        "project_id": project_id,
                        "rack_id": rack_id,
                        "member_tag": f"STR-{member_idx:03d}",
                        "member_type": "STRINGER",
                        "start_node": start_tag,
                        "end_node":   end_tag,
                        "length_mm":  L,
                        "unbraced_length": L,
                        "k_factor": 1.0,
                    })
                    member_idx += 1

    # Bracing (X-brace at end bays per tier)
    if bracing == "X-BRACE":
        for ti in range(1, len(tier_heights)):
            for line in ["A", "B"]:
                # Brace in first and last bay at each tier
                for bi in [0, n_bays - 1]:
                    n1_tag = f"{line}{bi+1}T{ti-1}"
                    n2_tag = f"{line}{bi+2}T{ti}"
                    n3_tag = f"{line}{bi+1}T{ti}"
                    n4_tag = f"{line}{bi+2}T{ti-1}"
                    for s, e in [(n1_tag, n2_tag), (n4_tag, n3_tag)]:
                        if s in nodes_dict and e in nodes_dict:
                            n1 = nodes_dict[s]
                            n2 = nodes_dict[e]
                            L  = math.sqrt((n2["x"]-n1["x"])**2 +
                                           (n2["y"]-n1["y"])**2 +
                                           (n2["z"]-n1["z"])**2)
                            members.append({
                                "project_id": project_id,
                                "rack_id": rack_id,
                                "member_tag": f"BR-{member_idx:03d}",
                                "member_type": "BRACE",
                                "start_node": s,
                                "end_node":   e,
                                "length_mm":  round(L),
                                "unbraced_length": round(L),
                                "k_factor": 0.85,
                            })
                            member_idx += 1

    return members


# ─────────────────────────────────────────────────────────────
# LOAD GENERATION
# ─────────────────────────────────────────────────────────────

def generate_wind_loads(rack, tier_info, wind_speed_ms, kz=0.85, kzt=1.0, kd=0.85):
    """
    ASCE 7-22 Simplified wind load for open frame pipe rack.
    Returns list of nodal load dicts (lateral, per tier node).
    wind_speed_ms: basic wind speed (m/s)
    tier_info: [{"tier": 1, "node_tags_windward": [...], "projected_area_mm2": ..., "height_m": ...}]
    """
    # Dynamic pressure
    qz = 0.613 * kz * kzt * kd * wind_speed_ms**2  # Pa = N/m2
    Cf = RACK_GUIDELINES["wind_drag_coeff_open_frame"]

    nodal_loads = []
    for tier in tier_info:
        Af = tier.get("projected_area_mm2", 0) / 1e6   # m2
        F_total_N = qz * Cf * Af                         # N lateral per tier

        nodes_ww = tier.get("node_tags_windward", [])
        if not nodes_ww:
            continue
        F_per_node = F_total_N / len(nodes_ww)

        for node_tag in nodes_ww:
            nodal_loads.append({
                "node_tag": node_tag,
                "fx": round(F_per_node, 1),
                "fy": 0,
                "fz": 0,
                "load_source": "WIND-ASCE7",
            })
    return nodal_loads


def generate_seismic_loads(rack, tier_weights_N, sds=0.2, sd1=0.1, R=3.0, Ie=1.0):
    """
    ASCE 7-22 Equivalent Lateral Force procedure.
    tier_weights_N: [{"tier": 1, "weight_N": 50000, "height_m": 4.0, "node_tags": [...]}]
    Returns list of nodal lateral loads.
    """
    # Approximate fundamental period T = 0.02 * H^0.75 (ASCE 7 Table 12.8-2, steel moment frame approx)
    H = max((t.get("height_m", 4) for t in tier_weights_N), default=4.0)
    T = 0.02 * H**0.75

    # Seismic response coefficient
    Cs = sds / (R / Ie)
    Cs = max(Cs, max(0.01, 0.044 * sds * Ie))
    if T > 0 and sd1 > 0:
        Cs = min(Cs, sd1 / (T * (R / Ie)))

    W_total = sum(t.get("weight_N", 0) for t in tier_weights_N)
    V = Cs * W_total   # base shear

    # Vertical distribution (k=1 for T<=0.5s)
    k = 1.0 if T <= 0.5 else (0.75 + 0.5 * T if T <= 2.5 else 2.0)

    denom = sum(t["weight_N"] * t["height_m"]**k for t in tier_weights_N)

    nodal_loads = []
    for tier in tier_weights_N:
        wx = tier["weight_N"]
        hx = tier["height_m"]
        Fx = V * (wx * hx**k / denom) if denom > 0 else 0
        nodes = tier.get("node_tags", [])
        if not nodes:
            continue
        F_per_node = Fx / len(nodes)
        for node_tag in nodes:
            nodal_loads.append({
                "node_tag": node_tag,
                "fx": round(F_per_node, 1),
                "fy": 0,
                "fz": 0,
                "load_source": "SEISMIC-ELF",
            })
    return nodal_loads


# ─────────────────────────────────────────────────────────────
# REACTION CALCULATION (simplified tributary area method)
# ─────────────────────────────────────────────────────────────

def calculate_reactions(rack, members, nodal_loads_by_case, dist_loads_by_case):
    """
    Simple tributary area reaction calculation for pipe rack frames.
    Returns support_reactions: {node_tag: {case: {rx,ry,rz,...}}}
    """
    reactions = {}

    # Collect support nodes
    support_nodes = [m for m in members if m.get("is_support")]
    # Get all column-base nodes from rack geometry
    tier_heights = json.loads(rack.get("tier_heights", "[3500]"))

    # For each load case, sum vertical reactions at column bases
    all_cases = set()
    for lc_name in nodal_loads_by_case:
        all_cases.add(lc_name)
    for lc_name in dist_loads_by_case:
        all_cases.add(lc_name)

    for lc_name in all_cases:
        # Nodal loads summed at each node
        for load in nodal_loads_by_case.get(lc_name, []):
            tag = load["node_tag"]
            if tag not in reactions:
                reactions[tag] = {}
            if lc_name not in reactions[tag]:
                reactions[tag][lc_name] = {"rx":0,"ry":0,"rz":0,"rmx":0,"rmy":0,"rmz":0}
            reactions[tag][lc_name]["ry"] += load.get("fy", 0)
            reactions[tag][lc_name]["rx"] += load.get("fx", 0)
            reactions[tag][lc_name]["rz"] += load.get("fz", 0)

        # Distributed loads on beams → end reactions at beam support nodes
        for dl in dist_loads_by_case.get(lc_name, []):
            w1 = dl.get("w1", 0)   # N/mm
            L  = dl.get("member_length_mm", rack.get("width_of_rack", 6000))
            # Reaction = wL/2 for UDL
            end_reaction = w1 * L / 2
            for node_tag in dl.get("support_nodes", []):
                if node_tag not in reactions:
                    reactions[node_tag] = {}
                if lc_name not in reactions[node_tag]:
                    reactions[node_tag][lc_name] = {"rx":0,"ry":0,"rz":0,"rmx":0,"rmy":0,"rmz":0}
                reactions[node_tag][lc_name]["ry"] -= end_reaction  # downward = negative Y reaction

    return reactions


# ─────────────────────────────────────────────────────────────
# EQUIPMENT SUPPORT MEMBER GENERATION
# ─────────────────────────────────────────────────────────────

def generate_equipment_support_members(rack, equipment_list, nodes_dict, start_idx=500):
    """
    Generate secondary structural members to physically support each piece of equipment.

    Support patterns:
      SADDLE  (H vessel / exchanger)  → 2 transverse saddle beams at 0.2L and 0.8L
      SKID    (pump / compressor)     → 2 longitudinal platform beams spanning full bay
      LEG     (V vessel / reactor / tall drum) → 4 leg connection beams at PCD
      LUGA    (lug-mounted vertical)  → 2 trunnion cross-beams at lug elevation
      TRUNNION                        → same as LUGA
      Default                         → 1 transverse support beam at bay centre

    Returns: (new_members, new_nodes)
    """
    members   = []
    new_nodes = []
    idx = start_idx

    raw_th = json.loads(rack.get("tier_heights", "[4000]"))
    tier_heights = [0] + raw_th          # index 0 = grade, 1 = tier-1, …
    bay_span  = rack.get("bay_span",  9000)
    width     = rack.get("width_of_rack", 6000)
    n_bays    = rack.get("number_of_bays", 3)
    pid       = rack.get("project_id")
    rid       = rack.get("id")

    def _node(tag, x, y, z, ntype="SUPPORT_NODE"):
        n = {"project_id": pid, "rack_id": rid, "node_tag": tag,
             "x": x, "y": y, "z": z, "node_type": ntype, "is_support": 0}
        new_nodes.append(n)
        nodes_dict[tag] = n
        return tag

    def _mem(tag, start, end, length, mtype="SUPPORT_BEAM", notes=""):
        members.append({
            "project_id": pid, "rack_id": rid,
            "member_tag": tag, "member_type": mtype,
            "start_node": start, "end_node": end,
            "length_mm": max(int(length), 100),
            "unbraced_length": max(int(length), 100),
            "k_factor": 1.0, "notes": notes,
        })

    for eq in equipment_list:
        tier    = max(1, int(eq.get("tier_level", 1) or 1))
        bay     = max(1, int(eq.get("bay_number",  1) or 1))
        support = (eq.get("support_type") or "SKID").upper()
        orient  = (eq.get("orientation")  or "H").upper()
        tag     = eq.get("tag", "EQ")

        if tier >= len(tier_heights):
            continue

        y_tier   = tier_heights[tier]
        bay_z0   = (bay - 1) * bay_span       # start Z of bay
        bay_zctr = bay_z0 + bay_span / 2
        L_eq     = float(eq.get("length_mm",   3000) or 3000)
        D_eq     = float(eq.get("diameter_mm", 1000) or 1000)

        nA  = nodes_dict.get(f"A{bay}T{tier}")
        nB  = nodes_dict.get(f"B{bay}T{tier}")
        if not nA or not nB:
            continue

        xA = float(nA["x"])
        xB = float(nB["x"])

        # ── SADDLE-SUPPORTED HORIZONTAL VESSEL / EXCHANGER ──────────
        if support == "SADDLE" or (support == "SKID" and orient == "H"
                                    and L_eq > 2000):
            for i, frac in enumerate([0.2, 0.8]):
                saddle_z = bay_z0 + min(frac * L_eq, bay_span - 300)
                tA = _node(f"SD{idx}A", xA, y_tier, saddle_z, "SADDLE_NODE")
                tB = _node(f"SD{idx}B", xB, y_tier, saddle_z, "SADDLE_NODE")
                _mem(f"SADDLE-{idx:03d}", tA, tB, width,
                     notes=f"Saddle S{i+1} for {tag}")
                idx += 1

        # ── SKID / BASEPLATE (pumps, compressors, blowers) ──────────
        elif support in ("SKID", "CLIP") and orient == "H":
            # Two longitudinal platform beams at 30% and 70% of rack width
            nA2 = nodes_dict.get(f"A{bay+1}T{tier}")
            nB2 = nodes_dict.get(f"B{bay+1}T{tier}")
            if nA2 and nB2:
                for j, xf in enumerate([0.3, 0.7]):
                    px = xA + width * xf
                    tS = _node(f"SK{idx}S", px, y_tier, bay_z0,       "SKID_NODE")
                    tE = _node(f"SK{idx}E", px, y_tier, bay_z0 + bay_span, "SKID_NODE")
                    _mem(f"SKID-{idx:03d}", tS, tE, bay_span,
                         notes=f"Skid platform P{j+1} for {tag}")
                    idx += 1
                # Cross-tie at mid-span
                tM1 = _node(f"SK{idx}M1", xA + width*0.3, y_tier, bay_zctr, "SKID_NODE")
                tM2 = _node(f"SK{idx}M2", xA + width*0.7, y_tier, bay_zctr, "SKID_NODE")
                _mem(f"SKID-{idx:03d}", tM1, tM2, width * 0.4,
                     notes=f"Skid cross-tie for {tag}")
                idx += 1
            else:
                # Single bay skid
                tS = _node(f"SK{idx}S", xA + width*0.5, y_tier, bay_z0,          "SKID_NODE")
                tE = _node(f"SK{idx}E", xA + width*0.5, y_tier, bay_z0 + bay_span, "SKID_NODE")
                _mem(f"SKID-{idx:03d}", tS, tE, bay_span,
                     notes=f"Skid centreline beam for {tag}")
                idx += 1

        # ── LEG / LUGA / TRUNNION (vertical vessels, reactors, tanks) ─
        elif support in ("LEG", "LUGA", "TRUNNION") or orient == "V":
            leg_r = max(D_eq * 0.35, 300)   # leg PCD ≈ 70% of vessel radius
            xctr  = xA + width / 2
            corners = [(-1, -1), (+1, -1), (+1, +1), (-1, +1)]
            for li, (sx, sz) in enumerate(corners):
                lx = xctr + sx * leg_r * 0.707
                lz = bay_zctr + sz * leg_r * 0.707
                # Nearest main rack node to connect to
                nearest = f"A{bay}T{tier}" if lx < xctr else f"B{bay}T{tier}"
                nR = nodes_dict[nearest]
                tL = _node(f"LG{idx}L{li}", lx, y_tier, lz, "LEG_NODE")
                dist = math.sqrt((lx - float(nR["x"]))**2 +
                                 (lz - float(nR["z"]))**2)
                _mem(f"LEG-{idx:03d}", nearest, tL, dist,
                     notes=f"Leg L{li+1} for {tag}")
                idx += 1
            # Leg cap cross-beams (ring connecting legs)
            for li in range(4):
                n1_tag = f"LG{idx - 4 + li}L{li}"
                n2_tag = f"LG{idx - 4 + (li+1)%4}L{(li+1)%4}"
                if n1_tag in nodes_dict and n2_tag in nodes_dict:
                    n1c = nodes_dict[n1_tag]
                    n2c = nodes_dict[n2_tag]
                    d = math.sqrt((float(n1c["x"])-float(n2c["x"]))**2 +
                                  (float(n1c["z"])-float(n2c["z"]))**2)
                    _mem(f"LCAP-{idx:03d}", n1_tag, n2_tag, d,
                         notes=f"Leg cap ring for {tag}")
                    idx += 1

        # ── GENERIC FALLBACK ─────────────────────────────────────────
        else:
            tA = _node(f"SP{idx}A", xA, y_tier, bay_zctr, "SUPPORT_NODE")
            tB = _node(f"SP{idx}B", xB, y_tier, bay_zctr, "SUPPORT_NODE")
            _mem(f"SUP-{idx:03d}", tA, tB, width,
                 notes=f"Support beam for {tag}")
            idx += 1

    return members, new_nodes

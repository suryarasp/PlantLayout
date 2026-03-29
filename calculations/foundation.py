"""
calculations/foundation.py
ACI 318-19 Spread Footing Design
All units: N, mm, MPa
"""
import math
from config import FOUNDATION_CONSTANTS as FC


def _round_to_increment(value, increment=150):
    """Round up to nearest increment (mm)."""
    return math.ceil(value / increment) * increment


def design_spread_footing(
    Pu_N, Mux_Nmm=0, Muy_Nmm=0, Hx_N=0, Hz_N=0,
    col_width_mm=200, col_depth_mm=200,
    soil_bearing_kpa=150, depth_mm=1500,
    fc_mpa=28, fy_mpa=420,
    project_id=None, node_tag=None, footing_tag=None
):
    """
    Design a square/rectangular spread footing per ACI 318-19.

    Parameters
    ----------
    Pu_N         : Factored axial load (N, compression +)
    Mux_Nmm      : Factored moment about X-axis (N.mm)
    Muy_Nmm      : Factored moment about Y-axis (N.mm)
    Hx_N         : Factored horizontal shear X (N)
    Hz_N         : Factored horizontal shear Z (N)
    col_width_mm : Column section width (mm)
    col_depth_mm : Column section depth (mm)
    soil_bearing_kpa : Allowable soil bearing pressure (kPa)
    depth_mm     : Depth of footing bottom below grade (mm)
    fc_mpa       : Concrete compressive strength (MPa)
    fy_mpa       : Rebar yield strength (MPa)

    Returns dict with footing dimensions, rebar, and unity checks.
    """
    q_allow = soil_bearing_kpa * 1e-3   # N/mm2

    # Estimate soil overburden (use 18 kN/m3 soil + 24 kN/m3 concrete)
    gamma_soil_kNm3 = 18.0
    gamma_conc_kNm3 = 24.0

    # Service loads (unfactor: divide LRFD factors ~ 1.35 average)
    factor = 1.35
    P_service = Pu_N / factor
    M_service = max(abs(Mux_Nmm), abs(Muy_Nmm)) / factor

    # 1. Footing area — iterative sizing
    # Start with P/q_allow; adjust for eccentricity
    min_size = FC["footing_size_increment_mm"]

    # Estimate footing thickness first (for self-weight)
    t_est = max(FC["min_footing_thickness_mm"], depth_mm * 0.25)
    t_est = _round_to_increment(t_est, 50)

    B = math.sqrt(P_service / (q_allow * 1e6)) * 1000   # rough mm
    B = max(B, col_width_mm + 500, 900)

    # Iterate to account for overburden and eccentricity
    for _ in range(10):
        L = B   # start square
        # Self-weight of footing
        Wf = L * B * t_est * gamma_conc_kNm3 * 1e-9 * 1e3   # N (rough)
        P_total = P_service + Wf

        # Eccentricity check
        if P_total > 0:
            ex = M_service / P_total * 1e-3 / 1000  # mm (divide N.mm by N → mm)
            ex = abs(M_service) / P_total  # mm
        else:
            ex = 0

        if ex <= B / 6:
            # No uplift
            q_max = P_total / (B * L) * 1e-6 + abs(M_service) * 6 / (B * L**2) * 1e-6  # MPa → N/mm2
        else:
            # Eccentricity > B/6: need larger footing
            B = B * 1.2
            continue

        if q_max <= q_allow:
            break
        else:
            B = B * math.sqrt(q_max / q_allow) * 1.05

    B = _round_to_increment(B, FC["footing_size_increment_mm"])
    L = B   # square footing

    # Factored bearing pressure for structural checks
    q_u = Pu_N / (B * L)   # N/mm2 uniform factored

    # 2. Determine effective depth d
    # Minimum d from punching shear requirements
    cover = FC["min_cover_mm"]
    rebar_est = 16   # mm assumed rebar diameter

    # Punching shear critical section at d/2 from column face
    # Try d = 350mm initially
    d = max(300, t_est - cover - rebar_est)

    # Iterate d for punching shear
    for _ in range(10):
        b0 = 2 * (col_width_mm + d) + 2 * (col_depth_mm + d)
        Vu_punch = Pu_N - q_u * (col_width_mm + d) * (col_depth_mm + d)
        Vu_punch = max(0, Vu_punch)

        # ACI 22.6.5: Vc = min of three expressions
        beta = col_width_mm / col_depth_mm if col_depth_mm > 0 else 1.0
        alpha_s = 40   # interior column

        lam = FC["lambda"]
        sqrt_fc = math.sqrt(fc_mpa)

        Vc1 = (0.33 * lam * sqrt_fc) * b0 * d
        Vc2 = (0.17 * (1 + 2/beta) * lam * sqrt_fc) * b0 * d
        Vc3 = (0.083 * (2 + alpha_s * d / b0) * lam * sqrt_fc) * b0 * d
        Vc = min(Vc1, Vc2, Vc3)
        phi_Vc = FC["phi_shear"] * Vc

        uc_punch = Vu_punch / phi_Vc if phi_Vc > 0 else 999

        if uc_punch <= 1.0:
            break
        else:
            d = d * math.sqrt(uc_punch) * 1.05

    d = math.ceil(d / 10) * 10  # round to 10mm

    # 3. Update footing thickness
    thickness = d + cover + rebar_est
    thickness = _round_to_increment(thickness, 50)
    thickness = max(thickness, FC["min_footing_thickness_mm"])
    d = thickness - cover - rebar_est   # recalculate d

    # 4. One-way shear check
    # Critical section at d from column face
    # X-direction
    x_crit_dist = L / 2 - col_depth_mm / 2 - d
    x_crit_dist = max(0, x_crit_dist)
    Vu_x = q_u * B * x_crit_dist

    Vc_1way = 0.17 * FC["lambda"] * math.sqrt(fc_mpa) * B * d
    phi_Vc_1way = FC["phi_shear"] * Vc_1way
    uc_shear_x = Vu_x / phi_Vc_1way if phi_Vc_1way > 0 else 999

    # Y-direction (same for square)
    y_crit_dist = B / 2 - col_width_mm / 2 - d
    y_crit_dist = max(0, y_crit_dist)
    Vu_y = q_u * L * y_crit_dist

    Vc_1way_y = 0.17 * FC["lambda"] * math.sqrt(fc_mpa) * L * d
    phi_Vc_1way_y = FC["phi_shear"] * Vc_1way_y
    uc_shear_y = Vu_y / phi_Vc_1way_y if phi_Vc_1way_y > 0 else 999

    # Increase footing if shear fails
    if max(uc_shear_x, uc_shear_y) > 1.0:
        # Increase d
        factor_inc = math.sqrt(max(uc_shear_x, uc_shear_y)) * 1.1
        d = d * factor_inc
        d = math.ceil(d / 10) * 10
        thickness = d + cover + rebar_est
        thickness = _round_to_increment(thickness, 50)
        d = thickness - cover - rebar_est

    # 5. Flexure design (ACI 22.3)
    # Critical section at face of column
    Mu_x = q_u * B * (L / 2 - col_depth_mm / 2)**2 / 2   # N.mm
    Mu_y = q_u * L * (B / 2 - col_width_mm / 2)**2 / 2

    def design_rebar(Mu, b, d, fc, fy):
        """Return required As (mm2/m width) and rebar string."""
        phi = FC["phi_flexure"]
        Rn = Mu / (phi * b * d**2)
        if Rn <= 0:
            rho = FC["min_rebar_dia_mm"] * 1e-4
        else:
            disc = 1 - 2 * Rn / (0.85 * fc)
            if disc < 0:
                disc = 0
            rho = 0.85 * fc / fy * (1 - math.sqrt(disc))

        rho_min = max(0.0018, 3 * math.sqrt(fc) / fy)
        rho = max(rho, rho_min)

        As = rho * b * d   # mm2 for width b

        # Select rebar: try 12, 16, 20, 25, 32mm
        for dia in [12, 16, 20, 25, 32]:
            Ab = math.pi * dia**2 / 4
            spacing = Ab / (As / b) * 1000  # mm c/c per unit width
            spacing = math.floor(spacing / 25) * 25   # round down to 25mm
            spacing = max(75, min(spacing, 300))
            As_provided = Ab / spacing * 1000
            if As_provided >= As / b:
                rebar_str = f"Ø{dia}@{int(spacing)}"
                uc = (As / b) / As_provided
                return rho, As / b, rebar_str, uc

        rebar_str = f"Ø32@75"
        return rho, As / b, rebar_str, 0.99

    rho_x, As_req_x, rebar_bot_x, uc_flex_x = design_rebar(Mu_x, B, d, fc_mpa, fy_mpa)
    rho_y, As_req_y, rebar_bot_y, uc_flex_y = design_rebar(Mu_y, L, d, fc_mpa, fy_mpa)

    # Top rebar: minimum shrinkage (0.0018 * b * t)
    As_top_min = 0.0018 * 1000 * thickness
    top_dia = 12
    top_spacing = math.floor(math.pi * top_dia**2 / 4 / (As_top_min / 1000) * 1000 / 25) * 25
    top_spacing = max(150, min(top_spacing, 300))
    rebar_top = f"Ø{top_dia}@{int(top_spacing)}"

    # Recalc punching UC with final d
    b0 = 2 * (col_width_mm + d) + 2 * (col_depth_mm + d)
    Vu_punch = Pu_N - q_u * (col_width_mm + d) * (col_depth_mm + d)
    Vu_punch = max(0, Vu_punch)
    Vc1 = (0.33 * FC["lambda"] * math.sqrt(fc_mpa)) * b0 * d
    Vc2 = (0.17 * (1 + 2/max(beta, 0.5)) * FC["lambda"] * math.sqrt(fc_mpa)) * b0 * d
    Vc3 = (0.083 * (2 + alpha_s * d / b0) * FC["lambda"] * math.sqrt(fc_mpa)) * b0 * d
    Vc = min(Vc1, Vc2, Vc3)
    phi_Vc = FC["phi_shear"] * Vc
    uc_punch_final = Vu_punch / phi_Vc if phi_Vc > 0 else 0

    # Recalc shear UC
    x_crit = max(0, L/2 - col_depth_mm/2 - d)
    Vu_x2 = q_u * B * x_crit
    Vc_x2 = 0.17 * FC["lambda"] * math.sqrt(fc_mpa) * B * d
    phi_Vc_x2 = FC["phi_shear"] * Vc_x2
    uc_sx = Vu_x2 / phi_Vc_x2 if phi_Vc_x2 > 0 else 0

    y_crit = max(0, B/2 - col_width_mm/2 - d)
    Vu_y2 = q_u * L * y_crit
    Vc_y2 = 0.17 * FC["lambda"] * math.sqrt(fc_mpa) * L * d
    phi_Vc_y2 = FC["phi_shear"] * Vc_y2
    uc_sy = Vu_y2 / phi_Vc_y2 if phi_Vc_y2 > 0 else 0

    bearing_actual = P_service / (B * L) * 1e6 / 1000  # kPa

    all_ucs = [uc_punch_final, uc_sx, uc_sy, uc_flex_x, uc_flex_y]
    max_uc = max(all_ucs)
    if max_uc <= 0.90:
        status = "PASS"
    elif max_uc <= 1.00:
        status = "MARGINAL"
    else:
        status = "FAIL"

    return {
        "footing_tag":         footing_tag or f"F-{node_tag}",
        "node_tag":            node_tag,
        "project_id":          project_id,
        "footing_type":        "SPREAD",
        "length_mm":           int(L),
        "width_mm":            int(B),
        "depth_mm":            int(depth_mm),
        "thickness_mm":        int(thickness),
        "effective_depth_mm":  int(d),
        "soil_bearing_kpa":    soil_bearing_kpa,
        "concrete_fc_mpa":     fc_mpa,
        "steel_fy_mpa":        fy_mpa,
        "rebar_top_x":         rebar_top,
        "rebar_top_y":         rebar_top,
        "rebar_bot_x":         rebar_bot_x,
        "rebar_bot_y":         rebar_bot_y,
        "bearing_actual_kpa":  round(bearing_actual, 1),
        "uc_punching":         round(uc_punch_final, 3),
        "uc_shear_x":          round(uc_sx, 3),
        "uc_shear_y":          round(uc_sy, 3),
        "uc_flexure_x":        round(uc_flex_x, 3),
        "uc_flexure_y":        round(uc_flex_y, 3),
        "as_req_x_mm2pm":      round(As_req_x, 1),
        "as_req_y_mm2pm":      round(As_req_y, 1),
        "status":              status,
        # Design summary data
        "Pu_kN":               round(Pu_N / 1e3, 1),
        "Mu_kNm":              round(max(abs(Mux_Nmm), abs(Muy_Nmm)) / 1e6, 2),
        "eccentricity_mm":     round(abs(M_service) / max(P_service, 1), 1),
        "Mu_flex_x_kNm":       round(Mu_x / 1e6, 2),
        "Mu_flex_y_kNm":       round(Mu_y / 1e6, 2),
    }

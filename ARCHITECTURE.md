# EPC Structural Design Software — Architecture & Technical Reference

**Version:** 1.0 (2026-03-31)
**Repository:** https://github.com/suryarasp/PlantLayout
**Codes:** AISC 360-22 · ACI 318-19 · ASCE 7-22

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Directory Structure](#2-directory-structure)
3. [Architecture Diagram](#3-architecture-diagram)
4. [Information Flow](#4-information-flow)
5. [Database Schema](#5-database-schema)
6. [REST API Reference](#6-rest-api-reference)
7. [Backend Functions](#7-backend-functions)
8. [Frontend JavaScript Functions](#8-frontend-javascript-functions)
9. [Configuration Constants](#9-configuration-constants)
10. [Calculation Engine](#10-calculation-engine)
11. [3D Viewer Architecture](#11-3d-viewer-architecture)
12. [Typical Workflow](#12-typical-workflow)

---

## 1. System Overview

EPC Structural Design Software is a locally-hosted web application for designing
pipe rack structures and equipment supports to industrial plant layout standards.

| Layer | Technology |
|---|---|
| Backend server | Python 3.9+ / Flask 3.x |
| Database | SQLite 3 (WAL mode, single file `epc_design.db`) |
| Frontend | Single-page HTML5 — Bootstrap 5.3, Three.js 0.162 (WebGL) |
| Structural code | AISC 360-22 (LRFD/ASD steel design) |
| Foundation code | ACI 318-19 (reinforced concrete spread footings) |
| Load code | ASCE 7-22 (wind simplified open frame, seismic ELF) |
| Sections library | 62 AISC sections (W, HSS-SQ, C channel) |
| Materials library | 6 steel grades (A36, A992, A500-B/C, IS-E250, IS-E350) |
| Deployment | Local — launched via `start.bat`, served on http://localhost:5000 |

---

## 2. Directory Structure

```
EPC-A/
├── app.py                      # Flask application — all REST endpoints (48 routes)
├── config.py                   # AISC sections, materials, load combos, design constants
├── start.bat                   # Windows launcher — checks port, installs deps, opens browser
├── requirements.txt            # Python dependencies
├── epc_design.db               # SQLite database (auto-created on first run)
│
├── calculations/
│   ├── structural.py           # AISC 360-22 checks + rack geometry generators
│   └── foundation.py           # ACI 318-19 spread footing design
│
├── database/
│   └── db.py                   # Connection manager + schema init + data seeding
│
├── templates/
│   └── index.html              # Single-page UI (Bootstrap + Three.js, ~3500 lines)
│
└── csv_templates/
    ├── equipment_sample.csv    # 24 equipment items with all columns populated
    └── nozzles_sample.csv      # 50 nozzles with Fx/Fy/Fz/Mx/My/Mz
```

---

## 3. Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        BROWSER (localhost:5000)                  │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  index.html  (single-page application)                   │    │
│  │                                                           │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐  │    │
│  │  │ Project  │  │Equipment │  │  Loads   │  │Structure│  │    │
│  │  │   Tab    │  │   Tab    │  │   Tab    │  │   Tab   │  │    │
│  │  └──────────┘  └──────────┘  └──────────┘  └────────┘  │    │
│  │                                                           │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐  │    │
│  │  │Calculate │  │ Results  │  │Import/   │  │ Manual │  │    │
│  │  │   Tab    │  │   Tab    │  │Export Tab│  │   Tab  │  │    │
│  │  └──────────┘  └──────────┘  └──────────┘  └────────┘  │    │
│  │                                                           │    │
│  │  ┌─────────────────────────────────────────────────┐    │    │
│  │  │  3D View Tab  (Three.js WebGL module)            │    │    │
│  │  │  ┌──────────┐  ┌───────────────┐  ┌──────────┐  │    │    │
│  │  │  │Model Tree│  │  WebGL Canvas │  │Property  │  │    │    │
│  │  │  │(show/hide│  │ (OrbitControls│  │ Inspector│  │    │    │
│  │  │  │ groups)  │  │  raycasting)  │  │          │  │    │    │
│  │  │  └──────────┘  └───────────────┘  └──────────┘  │    │    │
│  │  └─────────────────────────────────────────────────┘    │    │
│  └─────────────────────────────────────────────────────────┘    │
│                         │ fetch() REST calls                      │
└─────────────────────────│───────────────────────────────────────┘
                          │ HTTP/JSON  (localhost:5000/api/*)
┌─────────────────────────▼───────────────────────────────────────┐
│                     Flask  app.py                                 │
│                                                                   │
│   @before_request → init_db()   (auto-creates schema on boot)    │
│                                                                   │
│   ┌──────────────┐  ┌──────────────────┐  ┌──────────────────┐  │
│   │  CRUD routes │  │  Calculate routes│  │  Import / Export │  │
│   │  /projects   │  │  /section-checks │  │  /import/equip   │  │
│   │  /equipment  │  │  /reactions      │  │  /import/nozzles │  │
│   │  /nozzles    │  │  /foundations    │  │  /export/results │  │
│   │  /load-cases │  │  /calculate/all  │  │  /templates/*    │  │
│   │  /rack       │  └──────────────────┘  └──────────────────┘  │
│   │  /members    │                                               │
│   └──────┬───────┘                                               │
│          │ imports                                                │
│   ┌──────▼────────────────────────────────────────────────────┐  │
│   │  calculations/structural.py                                │  │
│   │  ┌─────────────┐  ┌──────────────┐  ┌─────────────────┐  │  │
│   │  │AISC 360-22  │  │ Rack Geometry│  │ Wind / Seismic  │  │  │
│   │  │Section Checks│ │ Generators   │  │ Load Generators │  │  │
│   │  └─────────────┘  └──────────────┘  └─────────────────┘  │  │
│   │                                                            │  │
│   │  calculations/foundation.py                                │  │
│   │  ┌──────────────────────────────────────────────────────┐ │  │
│   │  │  ACI 318-19 Spread Footing Design                    │ │  │
│   │  └──────────────────────────────────────────────────────┘ │  │
│   └───────────────────────────────────────────────────────────┘  │
│          │ SQL                                                     │
│   ┌──────▼────────────────────────────────────────────────────┐  │
│   │  database/db.py  →  epc_design.db  (SQLite WAL)           │  │
│   │  16 tables, foreign-key cascades, seeded sections/mats    │  │
│   └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. Information Flow

### 4.1 Project Creation Flow
```
User: New Project → POST /api/projects
  → INSERT projects row (wind/seismic/soil params)
  → seed_default_load_cases() inserts 10 standard load cases
  → UI selects new project, loads all sub-data
```

### 4.2 Equipment Import Flow
```
User: Upload equipment_sample.csv → POST /api/projects/{pid}/import/equipment-csv
  → Parse CSV rows → validate TAG, TYPE columns
  → INSERT equipment rows (weight, dims, tier, bay, support_type)
  → Return {added, skipped, errors}
  → UI refreshes Equipment table
```

### 4.3 Nozzle Load Import Flow
```
User: Upload nozzles_sample.csv → POST /api/projects/{pid}/import/nozzles-csv
  → Parse CSV, match EQUIPMENT_TAG → equipment.id
  → INSERT nozzle rows (Fx/Fy/Fz, Mx/My/Mz per nozzle)
  → GROUP BY equipment tier_level + bay_number → map to rack node tag A{bay}T{tier}
  → SUM all forces/moments at each node
  → DELETE previous OL (Operating Load) nodal_loads for that project
  → INSERT summed nodal loads with load_source='NOZZLE' under OL load case
  → Return {added, nodal_loads_generated, errors}
```

### 4.4 Structure Generation Flow
```
User: Save Rack → POST /api/projects/{pid}/rack (or PUT /api/rack/{rid})
  → INSERT/UPDATE pipe_rack_geometry (bays, spans, tier_heights, width, bracing)

User: Generate Grid → POST /api/rack/{rid}/generate-grid
  → DELETE existing nodes and members for this rack
  → generate_rack_nodes(rack)
    → Creates nodes: A{bay}T{tier} and B{bay}T{tier} for each bay × tier intersection
    → Ground nodes (T0) are is_support=1
  → INSERT nodes
  → generate_rack_members(rack, nodes_dict)
    → COLUMN: A{bay}T{tier-1} → A{bay}T{tier} (and B line)
    → BEAM: A{bay}T{tier} → B{bay}T{tier} (transverse)
    → STRINGER: A{bay}T{tier} → A{bay+1}T{tier} (longitudinal)
    → BRACE: diagonal X or K per bracing_type
  → generate_equipment_support_members(rack, equipment_list, nodes_dict)
    → SADDLE: 2 transverse beams at 0.2L and 0.8L of vessel length
    → SKID: 2 longitudinal platform beams + cross-tie at mid-span
    → LEG/LUGA/TRUNNION: 4 leg beams at PCD corners + ring cap beams
    → Default: 1 transverse beam at bay centre
  → INSERT all members with default section (lightest W-section) + A992 material
  → Return {nodes, members, support_members}
```

### 4.5 Calculation Flow
```
User: Calculate → POST /api/projects/{pid}/calculate/section-checks

  Step 1 — Build load data
    → Fetch all members, sections, materials
    → Fetch all load_combinations
    → Fetch nodal_loads grouped by (load_case_id)
    → Fetch distributed_loads grouped by (member_tag)

  Step 2 — Apply wind loads
    → generate_wind_loads(rack, tier_info, wind_speed_ms)
    → Uses ASCE 7-22 simplified: qz = 0.613·Kz·Kzt·Kd·V²
    → Force per tier node = qz · Cf(1.3) · tributary_area

  Step 3 — Apply seismic loads
    → generate_seismic_loads(rack, tier_weights, sds, sd1, R, Ie)
    → V = Cs · W,  Cs = SDS / (R/Ie),  capped by SD1/(T·R/Ie)
    → Vertical distribution: Fx = V · wx·hx / Σ(wi·hi)

  Step 4 — For each member × each load combination
    → Apply load factors from combo (e.g. 1.2DL + 1.6LL + 0.5WL)
    → check_member(member, section, material, factored_loads)
      → flexural_capacity() → phi_Mn (AISC F2 + LTB)
      → shear_capacity()    → phi_Vn (AISC G2)
      → axial_compression_capacity() → phi_Pn (AISC E3)
      → combined_check_H1() → UC (AISC H1-1)
      → deflection_simply_supported() → delta vs L/360 limit
    → INSERT member_results row

  → Return {checked, passed, failed}

User: Support Reactions → POST /api/projects/{pid}/calculate/reactions
  → calculate_reactions(rack, members, nodal_loads, dist_loads)
  → Tributary area method: each node gets half-span of adjacent members
  → INSERT support_reactions (Rx, Ry, Rz, Rmx, Rmy, Rmz per node per case)

User: Foundation Design → POST /api/projects/{pid}/calculate/foundations
  → Fetch support_reactions for governing combo
  → For each column base node:
    → design_spread_footing(Pu, Mux, Muy, Hx, Hz, soil_bearing, ...)
    → Iterative footing sizing: increase L×W until bearing < allowable
    → ACI 318-19:
      → Punching shear: Vu ≤ φ·Vc, Vc = min(3 expressions) × b0 × d
      → One-way shear: critical at d from column face
      → Flexure: Mu at column face, As = Mu / (φ·fy·(d - a/2))
      → Rebar selection from [12,16,20,25,32]mm bars
    → INSERT foundations row with dimensions, rebar schedule, UC ratios
```

### 4.6 3D Viewer Load Flow
```
User: Click '3D View' tab → on3DTabShow()
  → Queues load request if Three.js module not yet ready
  → Three.js module sets window.v3d on init → drains queue
  → loadModel(pid)
    → Parallel fetch: equipment, members, nodes, rack
    → fetchAllNozzles(pid, eqList)
    → Build nodeMap {node_tag → node}
    → Build rackGeo {tierHeights[], baySpan, width}
    → renderStructure(memberList, nodeMap)
      → BoxGeometry per member, colour by MEM_COLORS[type]
      → Width: COLUMN=0.22m, BEAM=0.20m, BRACE=0.12m, SUPPORT=0.18m
    → renderEquipment(eqList, rackGeo)
      → eqWorldPos(): derive XYZ from tier_level/bay_number + rack geometry
      → buildEqMesh(eq): proper 3D shapes per type
        TANK → CylinderGeometry + ConeGeometry roof
        VESSEL/REACTOR (V) → shell + hemispherical heads + skirt + nozzle stubs
        VESSEL/DRUM/EXCHANGER (H) → cylinder + end caps + saddles
        PUMP → volute casing + nozzles + motor + baseplate
        COMPRESSOR → cylinder block + pistons + driver
        BLOWER → scroll casing + discharge duct + inlet + motor
    → renderNozzleForces(nozzles, eqList, rackGeo)
      → ArrowHelper per nozzle, length scaled to force magnitude
    → buildModelTree(eqList, memberList, nodeList)
      → Group by type, eye-icon per group and item for show/hide

User: Export HTML → exportHTML()
  → Serialise scene geometry to JSON (equipment positions + member geometry)
  → Generate self-contained HTML (Three.js via CDN importmap)
  → Download as {ProjectName}_3D.html
```

---

## 5. Database Schema

### 5.1 Entity Relationship

```
projects ──< equipment ──< nozzles
         │              └─ base_plates (1:1)
         ├──< load_cases ──< nodal_loads
         │                └─ distributed_loads
         ├──< load_combinations
         ├──< pipe_rack_geometry ──< nodes
         │                       └─< members ──> sections
         │                                    └─> materials
         ├──< member_results
         ├──< support_reactions
         └──< foundations
```

### 5.2 Table Definitions

#### `projects`
| Column | Type | Description |
|---|---|---|
| id | INTEGER PK | Auto-increment |
| name | TEXT | Project name |
| code_standard | TEXT | AISC-360 / IS-800 |
| wind_speed | REAL | Basic wind speed m/s (ASCE 7) |
| wind_exposure | TEXT | B / C / D |
| seismic_sds | REAL | Short-period spectral accel |
| seismic_sd1 | REAL | 1-second spectral accel |
| seismic_r | REAL | Response modification factor |
| seismic_ie | REAL | Importance factor |
| site_class | TEXT | A–E |
| soil_bearing | REAL | Allowable bearing kPa |
| soil_depth | REAL | Depth to bearing stratum mm |

#### `equipment`
| Column | Type | Description |
|---|---|---|
| project_id | FK | → projects |
| tag | TEXT | Unique equipment tag e.g. T-101 |
| type | TEXT | TANK/VESSEL/DRUM/REACTOR/PUMP/COMPRESSOR/BLOWER/EXCHANGER |
| weight_empty / _operating / _test | REAL | kg |
| length_mm / diameter_mm / height_mm | REAL | Outer dimensions mm |
| orientation | TEXT | H = horizontal, V = vertical |
| tier_level | INTEGER | Rack tier (1 = bottom) |
| bay_number | INTEGER | Rack bay (1 = first bay from origin) |
| support_type | TEXT | SADDLE/SKID/LEG/LUGA/TRUNNION |
| cog_x/y/z | REAL | Centre of gravity offset mm |
| elevation | REAL | Base elevation mm |

#### `nozzles`
| Column | Type | Description |
|---|---|---|
| equipment_id | FK | → equipment |
| nozzle_tag | TEXT | N1, N2 … |
| service | TEXT | INLET/OUTLET/VENT/DRAIN etc. |
| size_dn | REAL | Nominal bore mm |
| rating | TEXT | 150#/300#/600#/900# |
| pos_x/y/z | REAL | Nozzle position relative to equipment origin mm |
| direction | TEXT | +X/-X/+Y/-Y/+Z/-Z |
| force_fx/fy/fz | REAL | Sustained piping forces N |
| moment_mx/my/mz | REAL | Sustained piping moments N·mm |

#### `pipe_rack_geometry`
| Column | Type | Description |
|---|---|---|
| rack_tag | TEXT | e.g. RACK-A |
| bay_span | REAL | Uniform bay span mm |
| number_of_bays | INTEGER | Count |
| number_of_tiers | INTEGER | Count |
| tier_heights | TEXT | JSON array e.g. [4000, 7500] mm elevations |
| width_of_rack | REAL | A-line to B-line distance mm |
| bracing_type | TEXT | X-BRACE / K-BRACE / PORTAL |
| origin_x/y/z | REAL | World origin of rack mm |
| orientation_angle | REAL | Rotation from North degrees |

#### `nodes`
| Column | Type | Description |
|---|---|---|
| node_tag | TEXT | A{bay}T{tier} or B{bay}T{tier} or support/saddle tags |
| x / y / z | REAL | World coordinates mm |
| node_type | TEXT | FRAME_NODE/SUPPORT_NODE/SADDLE_NODE/SKID_NODE/LEG_NODE |
| is_support | INTEGER | 1 = column base (boundary condition) |

#### `members`
| Column | Type | Description |
|---|---|---|
| member_tag | TEXT | COL-001, BM-001, SADDLE-501 etc. |
| member_type | TEXT | BEAM/COLUMN/BRACE/STRINGER/SUPPORT_BEAM/SADDLE_BEAM/SKID_BEAM/LEG_BEAM |
| start_node / end_node | TEXT | node_tag references |
| section_id | FK | → sections |
| material_id | FK | → materials |
| length_mm | REAL | Member length mm |
| unbraced_length | REAL | Lb for LTB check mm |
| k_factor | REAL | Effective length factor (default 1.0) |

#### `nodal_loads`
| Column | Type | Description |
|---|---|---|
| load_case_id | FK | → load_cases |
| node_tag | TEXT | Matches nodes.node_tag |
| fx/fy/fz | REAL | Forces N |
| mx/my/mz | REAL | Moments N·mm |
| load_source | TEXT | MANUAL / NOZZLE (auto-generated from nozzle import) |

#### `load_combinations`
| Column | Type | Description |
|---|---|---|
| combo_name | TEXT | 1.2DL+1.6LL, etc. |
| combo_type | TEXT | LRFD / ASD |
| factors | TEXT | JSON dict {load_case_name: factor} |
| governing | INTEGER | 1 if this combo governs results |

#### `member_results`
| Column | Type | Description |
|---|---|---|
| member_tag | TEXT | |
| combo_name | TEXT | Load combination that produced this result |
| axial_force / shear_y / shear_z / moment_y / moment_z | REAL | N or N·mm |
| uc_bending / uc_shear / uc_axial / uc_combined | REAL | Unity check ratios (≤1.0 = PASS) |
| phi_mn / phi_vn / phi_pn | REAL | Design capacities N·mm or N |
| max_deflection_mm | REAL | Computed deflection mm |
| status | TEXT | PASS / MARGINAL / FAIL / UNCHECKED |

#### `foundations`
| Column | Type | Description |
|---|---|---|
| footing_tag | TEXT | FTG-A1T0 etc. |
| node_tag | TEXT | Column base node |
| length_mm / width_mm / thickness_mm | REAL | Footing dimensions mm |
| depth_mm | REAL | Depth below grade mm |
| concrete_fc_mpa | REAL | 28 MPa default |
| steel_fy_mpa | REAL | 420 MPa default |
| rebar_bot_x / _bot_y | TEXT | e.g. "Ø16@150" |
| uc_punching / uc_shear_x / uc_shear_y / uc_flexure_x / uc_flexure_y | REAL | Unity checks |
| bearing_actual_kpa | REAL | Actual soil pressure |
| status | TEXT | PASS / MARGINAL / FAIL |

---

## 6. REST API Reference

All endpoints return JSON. Base URL: `http://localhost:5000/api`

### 6.1 Projects

| Method | URL | Body / Params | Returns | Notes |
|---|---|---|---|---|
| GET | `/projects` | — | `[{id, name, ...}]` | All projects, newest first |
| POST | `/projects` | `{name, wind_speed, seismic_sds, ...}` | `{id, message}` | Creates project + 10 load cases |
| GET | `/projects/{pid}` | — | Project object | |
| PUT | `/projects/{pid}` | Any project fields | `{message}` | |
| DELETE | `/projects/{pid}` | — | `{message}` | Cascades all data |

### 6.2 Equipment

| Method | URL | Body / Params | Returns |
|---|---|---|---|
| GET | `/projects/{pid}/equipment` | — | `[{id, tag, type, ...}]` |
| POST | `/projects/{pid}/equipment` | `{tag, type, weight_operating, tier_level, bay_number, support_type, ...}` | `{id, message}` |
| GET | `/equipment/{eid}` | — | Equipment object |
| PUT | `/equipment/{eid}` | Any equipment fields | `{message}` |
| DELETE | `/equipment/{eid}` | — | `{message}` |

### 6.3 Nozzles

| Method | URL | Body / Params | Returns |
|---|---|---|---|
| GET | `/equipment/{eid}/nozzles` | — | `[{nozzle_tag, force_fx, ...}]` |
| POST | `/equipment/{eid}/nozzles` | `{nozzle_tag, size_dn, force_fx, force_fy, force_fz, moment_mx, moment_my, moment_mz}` | `{id}` |
| PUT | `/nozzles/{nid}` | Any nozzle fields | `{message}` |
| DELETE | `/nozzles/{nid}` | — | `{message}` |
| GET | `/equipment/{eid}/baseplate` | — | Baseplate object |
| PUT | `/equipment/{eid}/baseplate` | `{plate_length, plate_width, anchor_bolt_dia, ...}` | `{message}` |

### 6.4 Load Cases & Loads

| Method | URL | Body / Params | Returns |
|---|---|---|---|
| GET | `/projects/{pid}/load-cases` | — | `[{name, type, ...}]` |
| POST | `/projects/{pid}/load-cases` | `{name, type, description}` | `{id}` |
| PUT | `/load-cases/{lcid}` | Any load case fields | `{message}` |
| GET | `/projects/{pid}/nodal-loads` | — | `[{node_tag, fx, fy, ...}]` |
| POST | `/projects/{pid}/nodal-loads` | `{node_tag, load_case_id, fx, fy, fz, mx, my, mz}` | `{id}` |
| DELETE | `/nodal-loads/{nlid}` | — | `{message}` |
| GET | `/projects/{pid}/distributed-loads` | — | `[{member_tag, w1, ...}]` |
| POST | `/projects/{pid}/distributed-loads` | `{member_tag, load_case_id, w1, w2, distance_a, distance_b, direction}` | `{id}` |
| DELETE | `/distributed-loads/{dlid}` | — | `{message}` |

### 6.5 Load Combinations

| Method | URL | Body / Params | Returns |
|---|---|---|---|
| GET | `/projects/{pid}/load-combinations` | — | `[{combo_name, combo_type, factors}]` |
| POST | `/projects/{pid}/load-combinations/generate` | `{type: "LRFD"\|"ASD"\|"BOTH"}` | `{generated}` |
| DELETE | `/load-combinations/{cid}` | — | `{message}` |

### 6.6 Sections & Materials

| Method | URL | Params | Returns |
|---|---|---|---|
| GET | `/sections` | `?type=W&search=W310` | `[{designation, d, bf, area, ...}]` |
| GET | `/sections/{designation}` | — | Single section object |
| POST | `/sections/{designation}/capacity` | `{fy, E, KL, Lb, Cb, phi_b, phi_c}` | `{phi_Mn, phi_Vn, phi_Pn}` |
| GET | `/materials` | — | `[{name, fy, fu, e_modulus}]` |

### 6.7 Structure (Rack)

| Method | URL | Body | Returns |
|---|---|---|---|
| GET | `/projects/{pid}/rack` | — | `[rack object]` |
| POST | `/projects/{pid}/rack` | `{rack_tag, bay_span, number_of_bays, tier_heights, width_of_rack, bracing_type}` | `{id}` |
| PUT | `/rack/{rid}` | Any rack fields | `{message}` |
| POST | `/rack/{rid}/generate-grid` | — | `{nodes, members, support_members, message}` |
| GET | `/projects/{pid}/nodes` | — | `[{node_tag, x, y, z, is_support}]` |
| GET | `/projects/{pid}/members` | — | `[{member_tag, member_type, section_name, ...}]` |
| PUT | `/members/{mid}` | `{section_id, material_id, k_factor, unbraced_length}` | `{message}` |

### 6.8 Calculations

| Method | URL | Body | Returns |
|---|---|---|---|
| POST | `/projects/{pid}/calculate/section-checks` | — | `{checked, passed, failed}` |
| POST | `/projects/{pid}/calculate/reactions` | — | `{nodes_computed}` |
| POST | `/projects/{pid}/calculate/foundations` | — | `{designed, passed, failed}` |
| POST | `/projects/{pid}/calculate/all` | — | Combined results from all three |

### 6.9 Results

| Method | URL | Returns |
|---|---|---|
| GET | `/projects/{pid}/results/members` | `[{member_tag, uc_combined, uc_bending, uc_shear, status, ...}]` |
| GET | `/projects/{pid}/results/reactions` | `[{node_tag, load_case, rx, ry, rz, rmx, rmy, rmz}]` |
| GET | `/projects/{pid}/results/foundations` | `[{footing_tag, length_mm, width_mm, rebar_bot_x, uc_punching, status, ...}]` |
| GET | `/projects/{pid}/results/summary` | `{total_members, pass, fail, max_uc, foundations_pass, foundations_fail}` |
| GET | `/projects/{pid}/export/results-csv` | CSV file download |

### 6.10 Import / Export

| Method | URL | Body | Returns |
|---|---|---|---|
| POST | `/projects/{pid}/import/equipment-csv` | multipart file | `{added, skipped, errors}` |
| POST | `/projects/{pid}/import/nozzles-csv` | multipart file | `{added, nodal_loads_generated, errors}` |
| GET | `/templates/equipment-csv` | — | Blank CSV template |
| GET | `/templates/equipment-sample` | — | Filled sample CSV (24 items) |
| GET | `/templates/nozzles-csv` | — | Blank nozzle CSV template |

---

## 7. Backend Functions

### 7.1 `calculations/structural.py`

All units: **N** and **mm** throughout.

#### `check_compactness(sec, fy, E=200000) → str`
Returns compactness classification per AISC 360-22 Table B4.1b.
- Checks flange `λ_f = bf/(2·tf)` vs `λ_pf = 0.38√(E/fy)`, `λ_rf = 1.0√(E/fy)`
- Checks web `λ_w = (d-2tf)/tw` vs `λ_pw = 3.76√(E/fy)`, `λ_rw = 5.70√(E/fy)`
- Returns: `"COMPACT"` | `"NONCOMPACT"` | `"SLENDER"`

#### `flexural_capacity(sec, fy, E, Lb, Cb, phi) → float`
AISC 360-22 Chapter F2. Returns `φ·Mn` (N·mm).
- `Mp = Fy·Zx`
- `Lp = 1.76·ry·√(E/Fy)` — no LTB below Lp
- `Lr = 1.95·rts·(E/(0.7·Fy))·√(J·c/(Sx·ho) + √((J·c/(Sx·ho))² + 6.76·(0.7Fy/E)²))`
- Linear interpolation Lp ≤ Lb ≤ Lr; elastic LTB above Lr

#### `shear_capacity(sec, fy, E, phi) → float`
AISC 360-22 Chapter G2. Returns `φ·Vn` (N).
- `Aw = d·tw`, Cv1 shear coefficient based on `h/tw` vs `2.24√(E/fy)`
- `Vn = 0.6·Fy·Aw·Cv1`

#### `axial_compression_capacity(sec, fy, E, KL, phi) → float`
AISC 360-22 Chapter E3. Returns `φ·Pn` (N).
- `Fe = π²E / (KL/r)²` (Euler buckling)
- If `KL/r ≤ 4.71√(E/Fy)`: `Fcr = 0.658^(Fy/Fe) · Fy`
- Else: `Fcr = 0.877·Fe`

#### `combined_check_H1(Pu, phi_Pn, Mux, phi_Mnx, Muy, phi_Mny) → float`
AISC 360-22 H1-1. Returns unity check ratio.
- If `Pu/φPn ≥ 0.2`: UC = `Pu/φPn + (8/9)·(Mux/φMnx + Muy/φMny)`
- Else: UC = `Pu/(2φPn) + (Mux/φMnx + Muy/φMny)`

#### `deflection_simply_supported(w_per_mm, L, E, I) → float`
Returns midspan deflection (mm) for UDL: `δ = 5wL⁴/(384EI)`

#### `check_member(member, section, material, loads_by_combo) → list[dict]`
Runs all checks for a member across all load combinations.
Returns list of result dicts with: `{combo, uc_bending, uc_shear, uc_axial, uc_combined, phi_mn, phi_vn, phi_pn, status}`

#### `auto_size_rack(rack_config, equipment_list, pipe_loads_per_tier, sections, material) → dict`
Iterates bay spans from RACK_GUIDELINES defaults. For each span/tier combo tries lightest section, runs `check_member`, returns first configuration where all members pass.

#### `generate_rack_nodes(rack) → list[dict]`
Creates nodes at every bay × tier intersection.
- Tag format: `A{bay}T{tier}` (column line A, x=0) and `B{bay}T{tier}` (x=width)
- Tier 0 = grade (is_support=1, PINNED)

#### `generate_rack_members(rack, nodes_dict) → list[dict]`
Creates all main structural members:
- **COLUMN**: vertical A{bay}T{tier-1}→A{bay}T{tier}, k=2.0 for sway
- **BEAM**: transverse A{bay}T{tier}→B{bay}T{tier}
- **STRINGER**: longitudinal A{bay}T{tier}→A{bay+1}T{tier}
- **BRACE**: X-BRACE diagonals or K-BRACE chevrons in each panel

#### `generate_equipment_support_members(rack, equipment_list, nodes_dict, start_idx) → (list, list)`
Creates secondary framing for equipment support. Returns `(members, new_nodes)`.
- **SADDLE**: 2 transverse beams at 0.2L and 0.8L of vessel length
- **SKID**: 2 longitudinal beams at 30%/70% width + cross-tie
- **LEG/LUGA/TRUNNION**: 4 legs at PCD corners (PCD ≈ 70% vessel diameter) + ring cap beams
- **Default**: 1 transverse beam at bay centre

#### `generate_wind_loads(rack, tier_info, wind_speed_ms, kz, kzt, kd) → list[dict]`
ASCE 7-22 §27 simplified open frame.
- `qz = 0.613 · Kz · Kzt · Kd · V²` Pa
- `Cf = 1.3` (open frame force coefficient)
- Force per tier = `qz · Cf · exposed_area` applied at tier beam nodes

#### `generate_seismic_loads(rack, tier_weights_N, sds, sd1, R, Ie) → list[dict]`
ASCE 7-22 §12.8 ELF.
- `Cs = SDS / (R/Ie)`, capped at `SD1 / (T·R/Ie)`, minimum `0.01`
- `V = Cs · W` (total base shear)
- Vertical distribution: `Fx = V · wx·hx^k / Σ(wi·hi^k)`, k=1 for T≤0.5s

#### `calculate_reactions(rack, members, nodal_loads_by_case, dist_loads_by_case) → dict`
Tributary area method. Returns `{node_tag: {case: {rx, ry, rz, rmx, rmy, rmz}}}`.

---

### 7.2 `calculations/foundation.py`

#### `design_spread_footing(Pu_N, Mux_Nmm, Muy_Nmm, Hx_N, Hz_N, col_width_mm, col_depth_mm, soil_bearing_kpa, depth_mm, fc_mpa, fy_mpa, ...) → dict`
ACI 318-19 spread footing design. Full iterative sizing.

**Sizing loop:**
1. Initial size: `L = W = √(Pu / q_allow)`
2. Check eccentricity: `e = M/P`, ensure `e < L/6` (no tension)
3. Bearing check: `q_max = P/A + M·(L/2)/I ≤ q_allow`
4. Round up to 150mm increments

**ACI checks (all must pass):**
- **Punching shear** (§22.6): `Vu = Pu - q·(c1+d)·(c2+d)`, `Vc = min(λ·√fc·b0·d, (2+4/βc)·..., (2+αs·d/b0)·...)`, φ=0.75
- **One-way shear X** (§22.5): at `d` from column face in x-direction
- **One-way shear Z** (§22.5): at `d` from column face in z-direction
- **Flexure X** (§22.3): `Mu` at column face, `As = Mu / (φ·fy·(d-a/2))`, select from [12,16,20,25,32]mm bars
- **Flexure Z** (§22.3): same in z-direction

Returns dict with: `{length_mm, width_mm, thickness_mm, rebar_bot_x, rebar_bot_y, bearing_actual_kpa, uc_punching, uc_shear_x, uc_shear_z, uc_flexure_x, uc_flexure_z, status}`

---

### 7.3 `database/db.py`

#### `get_conn() → sqlite3.Connection`
Opens WAL-mode connection with `row_factory = sqlite3.Row` and `PRAGMA foreign_keys = ON`.

#### `init_db()`
Idempotent. Creates all 16 tables if not exist. Seeds sections from `config.AISC_SECTIONS` and materials from `config.MATERIALS` on first run (only when sections table is empty).

#### `seed_default_load_cases(project_id)`
Inserts 10 standard load cases:
`DL, LL, WL-X, WL-Y, EQ-X, EQ-Y, TL, OL, FDL, ERE`

---

## 8. Frontend JavaScript Functions

All reside in `templates/index.html` in a single `<script>` block (main) and one `<script type="module">` block (Three.js).

### 8.1 Main Script — State & Utilities

| Function | Description |
|---|---|
| `fmt(v, d)` | Format number to d decimal places, returns `—` for null |
| `fmtK(v)` | N → kN |
| `fmtM(v)` | N·mm → kN·m |
| `ucBadge(uc)` | Returns HTML badge: green PASS / yellow MARGINAL / red FAIL |
| `api(method, url, body)` | `fetch()` wrapper, returns parsed JSON |

### 8.2 Project Functions

| Function | Description |
|---|---|
| `loadProjects()` | GET /api/projects → populate dropdown + table |
| `createProject()` | POST /api/projects from modal form |
| `selectProject(pid)` | Sets `window.currentProject`, loads all sub-data, triggers 3D reload |
| `saveProject()` | PUT /api/projects/{pid} from settings form |
| `deleteProject(pid)` | DELETE with confirmation |

### 8.3 Equipment Functions

| Function | Description |
|---|---|
| `loadEquipment()` | GET /api/projects/{pid}/equipment → render table |
| `saveEquipment()` | POST or PUT equipment from modal |
| `deleteEquipment(eid)` | DELETE equipment |
| `showNozzles(eid, tag)` | Expands nozzle sub-panel for equipment |
| `loadNozzles(eid)` | GET /api/equipment/{eid}/nozzles → render table |
| `saveNozzle()` | POST /api/equipment/{eid}/nozzles |
| `deleteNozzle(nid)` | DELETE nozzle |
| `saveBaseplate()` | PUT /api/equipment/{eid}/baseplate |
| `openNozzleImport()` | Switches to Import tab, pre-selects nozzles-csv |

### 8.4 Load Functions

| Function | Description |
|---|---|
| `loadLoadCases()` | GET load-cases → render table |
| `loadNodalLoads()` | GET nodal-loads → render table |
| `saveNodalLoad()` | POST nodal load from modal |
| `deleteNodalLoad(id)` | DELETE |
| `loadDistLoads()` | GET distributed-loads → render table |
| `saveDistLoad()` | POST distributed load |
| `deleteDistLoad(id)` | DELETE |
| `loadCombos()` | GET load-combinations |
| `generateCombos(type)` | POST /load-combinations/generate |

### 8.5 Structure Functions

| Function | Description |
|---|---|
| `loadRack()` | GET rack → populate form fields + drawRackSVG |
| `saveRack()` | POST or PUT rack geometry |
| `generateGrid()` | POST /rack/{rid}/generate-grid → reload members |
| `drawRackSVG(rack)` | Renders elevation view SVG with columns, beams, braces, legend |
| `updateRackSummary(rack)` | Updates text summary card below SVG |
| `loadMembers()` | GET members → render table with section dropdowns |
| `filterMembers()` | Client-side filter by type/section |
| `assignSection(mid, sid)` | PUT /members/{mid} to change section |

### 8.6 Calculation Functions

| Function | Description |
|---|---|
| `runStep(step)` | POST /calculate/{step}, updates step status icons |
| `runAll()` | Sequential: section-checks → reactions → foundations |
| `setStepState(step, state)` | Updates run-step icon: pending/running/done/fail |

### 8.7 Result Functions

| Function | Description |
|---|---|
| `loadSummary()` | GET /results/summary → stat cards |
| `loadMemberResults()` | GET /results/members → table with UC bars |
| `loadReactionResults()` | GET /results/reactions → table |
| `loadFoundationResults()` | GET /results/foundations → table |
| `exportResultsCSV()` | Opens /export/results-csv in new tab |

### 8.8 Import Functions

| Function | Description |
|---|---|
| `updateImportHint()` | Updates hint text based on selected import type |
| `doImport()` | POST multipart file to /import/{type}, shows log |
| `downloadTemplate(type)` | Opens /api/templates/{type} |

---

## 9. Configuration Constants

### 9.1 AISC Sections (`config.AISC_SECTIONS`)
62 sections in three types:

| Type | Count | Range | Key Properties |
|---|---|---|---|
| W (Wide Flange) | 38 | W150×13 → W530×82 | d, bf, tw, tf, Ix, Sx, Zx, Iy, J, Cw |
| HSS-SQ (Square Hollow) | 14 | HSS100×100×5 → HSS300×300×12 | A, Ix, Sx, Zx, J |
| C (Channel) | 10 | C150×12 → C380×50 | d, bf, tw, tf, Ix, Sx |

### 9.2 Materials (`config.MATERIALS`)

| Name | fy (MPa) | fu (MPa) | E (MPa) | Use |
|---|---|---|---|---|
| A36 | 250 | 400 | 200,000 | General structural steel |
| A992 | 345 | 450 | 200,000 | W-shape beams/columns (default) |
| A500-Gr-B | 290 | 400 | 200,000 | HSS round |
| A500-Gr-C | 315 | 427 | 200,000 | HSS square/rectangular |
| IS-E250 | 250 | 410 | 200,000 | Indian standard |
| IS-E350 | 350 | 490 | 200,000 | Indian standard high-strength |

### 9.3 LRFD Combinations (`config.LRFD_COMBINATIONS`)

| Name | Formula |
|---|---|
| 1.4DL | 1.4 × DL |
| 1.2DL+1.6LL | 1.2 DL + 1.6 LL |
| 1.2DL+1.0LL+1.0WL-X | 1.2 DL + 1.0 LL + 1.0 WL-X |
| 1.2DL+1.0LL+1.0WL-Y | 1.2 DL + 1.0 LL + 1.0 WL-Y |
| 1.2DL+1.0LL+1.0EQ-X | 1.2 DL + 1.0 LL + 1.0 EQ-X |
| 1.2DL+1.0LL+1.0EQ-Y | 1.2 DL + 1.0 LL + 1.0 EQ-Y |
| 0.9DL+1.0WL-X | 0.9 DL + 1.0 WL-X (uplift check) |

### 9.4 Rack Design Guidelines (`config.RACK_GUIDELINES`)

| Parameter | Value | Reference |
|---|---|---|
| min_bottom_clearance_mm | 3,500 | IPS-E-PR-370 |
| min_tier_spacing_mm | 2,500 | Industry practice |
| typical_bay_spans | [6000, 7500, 9000, 10500, 12000] mm | — |
| preferred_bay_span_mm | 9,000 | Industry preference |
| max_beam_deflection_ratio | L/360 | Serviceability |
| min_rack_width_mm | 3,000 | — |
| max_rack_width_mm | 9,000 | — |
| preferred_rack_width_mm | 6,000 | — |

### 9.5 Foundation Constants (`config.FOUNDATION_CONSTANTS`)

| Parameter | Value | Reference |
|---|---|---|
| phi_flexure | 0.90 | ACI 318-19 §21.2.1 |
| phi_shear | 0.75 | ACI 318-19 §21.2.1 |
| lambda | 1.0 | Normal-weight concrete |
| min_cover_mm | 75 | ACI 318-19 §20.6.1 |
| min_footing_thickness_mm | 350 | Practical minimum |
| increment_mm | 150 | Rounding increment |
| marginal_threshold | 0.95 | UC ≥ 0.95 → MARGINAL |

---

## 10. Calculation Engine

### 10.1 AISC 360-22 Section Checks

```
For each member:
  1. check_compactness(sec, fy)          → COMPACT / NONCOMPACT / SLENDER
  2. flexural_capacity(sec, fy, Lb, Cb)  → φMn (N·mm)
  3. shear_capacity(sec, fy)             → φVn (N)
  4. axial_compression_capacity(sec, KL) → φPn (N)

For each load combination:
  5. Apply factors to load_cases → Pu, Mux, Muy, Vuy
  6. uc_bending  = Mux / φMnx
  7. uc_shear    = Vuy / φVny
  8. uc_axial    = Pu  / φPn
  9. uc_combined = combined_check_H1(Pu, φPn, Mux, φMnx)
  10. deflection = 5wL⁴/384EI  vs  L/360 limit

Status:  uc_max < 0.95 → PASS
         0.95 ≤ uc_max ≤ 1.0 → MARGINAL
         uc_max > 1.0 → FAIL
```

### 10.2 ACI 318-19 Foundation Design

```
Inputs: Pu (N), Mux, Muy (N·mm), Hx, Hz (N), column size, soil bearing, fc, fy

Step 1 — Size footing
  A_req = Pu / q_allow
  L = W = √A_req, round up to 150mm
  Check eccentricity e < L/6 (no uplift)
  Increase until q_max ≤ q_allow

Step 2 — Effective depth
  d = thickness - cover - bar_dia/2 (min 75mm cover)

Step 3 — Punching shear (ACI §22.6)
  b0 = 2·(c1+d) + 2·(c2+d)
  Vc = min of 3 expressions × λ × √fc × b0 × d
  φVc ≥ Vu = Pu - q_net·(c1+d)·(c2+d)

Step 4 — One-way shear (ACI §22.5)
  Critical section at d from column face
  Vc = 0.17·λ·√fc·b·d  (simplified)

Step 5 — Flexure (ACI §22.3)
  Mu at column face = q_net · (L/2 - c/2)² · W / 2
  As = Mu / (φ·fy·(d - fy·As/(1.7·fc·b)))  (iterate)
  Select bar dia from [12, 16, 20, 25, 32]mm
  Spacing = (W - 2·cover) / (n_bars - 1)
```

---

## 11. 3D Viewer Architecture

The viewer is a `<script type="module">` block using Three.js r162 via CDN importmap (no build step).

### State variables
```javascript
scene, camera, renderer, controls   // Three.js core
sceneReady                          // bool — module initialised
allMeshes                           // [{mesh, id, type, data}] — all pickable objects
labelGroup, nozzleGroup             // THREE.Group — toggled independently
sceneBox                            // THREE.Box3 — used for fitView()
_visHidden                          // Set of hidden mesh IDs
```

### Initialisation sequence
```
window.on3DTabShow() [main script, always available]
  → queues {action:'load', pid} in window._3dQueue if module not ready

module loads → window.v3d registered
  → drains _3dQueue → calls v3d._loadModel(pid)
  → initScene() → WebGLRenderer, Camera, OrbitControls, lights, grid
  → loadModel(pid)
    → parallel fetch: equipment, members, nodes, rack
    → fetchAllNozzles()
    → renderStructure() → renderEquipment() → renderNozzleForces()
    → buildModelTree()
    → fitView()
```

### Equipment geometry
Each type is a `THREE.Group` of sub-meshes at local origin (base at y=0):

| Type | Sub-meshes |
|---|---|
| TANK | CylinderGeometry (shell) + ConeGeometry (cone roof) |
| VESSEL/REACTOR (V) | CylinderGeometry + 2× SphereGeometry (heads) + cylinder (skirt) + nozzle stubs |
| VESSEL/DRUM/EXCHANGER (H) | CylinderGeometry (rotated 90°) + 2× SphereGeometry (end caps) + saddle blocks |
| PUMP | SphereGeometry (casing) + CylinderGeometry (motor + nozzles) + BoxGeometry (baseplate) |
| COMPRESSOR | BoxGeometry (body) + CylinderGeometry (pistons + driver) + BoxGeometry (base) |
| BLOWER | CylinderGeometry (scroll) + BoxGeometry (duct) + CylinderGeometry (motor + inlet) |

### Member rendering
`makeMemberMesh(p1, p2, w, color)` — `BoxGeometry(w, w, len)` oriented with quaternion from `setFromUnitVectors(Z, direction)`.

### Colour coding

| Colour (hex) | Element |
|---|---|
| `#1565C0` (blue) | BEAM |
| `#37474F` (dark grey) | COLUMN |
| `#B71C1C` (dark red) | BRACE |
| `#00695C` (teal) | STRINGER |
| `#F57F17` (orange) | SUPPORT_BEAM / SADDLE_BEAM |
| `#4CAF50` (green) | SKID_BEAM |
| `#9C27B0` (purple) | LEG_BEAM |

### Export HTML
`exportHTML()` serialises scene data to a JSON blob embedded in a self-contained HTML file with Three.js loaded from CDN. The exported file includes a full model tree with group/item show-hide controls and works offline (only requires CDN for Three.js).

---

## 12. Typical Workflow

```
1. START SERVER
   Double-click start.bat
   → checks port 5000, installs missing packages, opens http://localhost:5000

2. CREATE PROJECT
   Project tab → New Project
   → Set name, wind speed (m/s), SDS, SD1, R, Ie, soil bearing (kPa)
   → Save Project Settings

3. IMPORT EQUIPMENT
   Import/Export tab → Equipment → upload equipment_sample.csv (or own file)
   OR Equipment tab → Add Equipment (manual, one at a time)
   → Verify in Equipment tab: TAG, TYPE, Tier, Bay, Support Type

4. IMPORT NOZZLE LOADS  (optional, from piping stress analysis)
   Equipment tab → "Import Nozzle Loads CSV" button
   → Upload nozzles_sample.csv format
   → Forces auto-aggregated to OL load case on rack nodes

5. DEFINE STRUCTURE
   Structure tab → Rack Geometry sub-tab
   → Set: Bay Span (mm), No. of Bays, Tier Heights (comma-separated mm), Width, Bracing
   → Click "Save Rack"
   → Click "Generate Grid"
   → Check Members sub-tab: all members created with default sections

6. REVIEW MEMBERS (optional)
   Structure tab → Members sub-tab
   → Filter by type, reassign sections if needed
   → Adjust k-factor for columns if required

7. CALCULATE
   Calculate tab:
   a. "Generate Combinations" → creates ASCE 7 LRFD + ASD combos
   b. "Section Checks" → AISC 360-22 UC ratios for all members
   c. "Support Reactions" → base shear/moment at each column
   d. "Foundation Design" → ACI 318-19 spread footings at all column bases

8. REVIEW RESULTS
   Results tab:
   → Member Results: UC table, green PASS / red FAIL
   → Support Reactions: forces/moments per node per load case
   → Foundation: footing sizes, rebar, all UC checks

9. EXPORT
   → Results tab → "Export Results CSV"
   → 3D View tab → "Export HTML" → self-contained 3D viewer file

10. 3D VIEW
    3D View tab → model loads automatically when project is selected
    → Model Tree: show/hide individual items or whole groups by type
    → Toolbar: Top/Front/Side/Iso views, Wireframe, Labels, Nozzle arrows
    → Click any object → Property panel shows all attributes
```

---

*Document generated: 2026-03-31*
*Software: EPC Structural Design Software v1.0*
*Repository: https://github.com/suryarasp/PlantLayout*

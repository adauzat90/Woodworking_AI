# Design Packet — Oak Base Cabinet 900

A frameless (Euro-style) kitchen base cabinet: one soft-close top drawer over a
pair of doors, with an adjustable shelf. Birch plywood carcass, solid oak
fronts and countertop, clear finish, Blum soft-close hardware.

![Renders](out/render.png)

## 1. Intended use

A general-purpose kitchen base unit: the drawer holds utensils/tools at hand
height; the door section below stores pots and small appliances on one
adjustable shelf. Sized to take a countertop and sit flush in a standard
kitchen run.

## 2. Overall dimensions & why

| Dimension | Value | Rationale |
|---|---|---|
| Width | 900 mm | Standard module; widest practical two-door box |
| Carcass height | 820 mm | 720 mm box + 100 mm toe kick |
| Working height | ~858 mm + counter build-up ≈ 900 mm | Standard counter height with the 38 mm oak top |
| Depth | 560 mm carcass / 590 mm with fronts | Standard base-cabinet depth; 615 mm counter gives a 30 mm overhang |
| Toe kick | 100 mm high × 60 mm setback | Exceeds the KCMA minimum (75 × 50 mm) |
| Reveals | 3 mm around fronts | Frameless overlay standard |

## 3. Proportions

- **Drawer over doors graduates naturally**: a 140 mm drawer front over
  571 mm doors — the shallow band on top reads lighter and is more useful.
- **Doors are a pair**, not one 894 mm slab: a single door past ~550 mm sags,
  racks, and swings into the work aisle. Each leaf is 445.5 mm — comfortably
  inside hinge-cup territory.
- Front coverage is 98 % of the face (verified by the geometry critic).

## 4. Structure & joinery

| Joint | Where | Why |
|---|---|---|
| Dado, 18 × 9 mm | Bottom into both sides | Mechanical support for the loaded floor — not a butt joint |
| Rabbet, 6 × 6 mm | Back panel into sides/top/bottom | Squares the box and resists racking |
| Dovetails, 12 mm, **tails on the sides** | Drawer box corners | Drawers get pulled open; tails on the sides can't pull off the front |
| Groove, 6 × 6 mm | Drawer bottom, captured | Floats the bottom panel |

Full setup dimensions: run `woodai build spec.json --joinery` (5 ops).

## 5. Material & movement

- **Carcass**: 18 mm birch plywood — dimensionally stable, so the box needs no
  movement allowance. 6 mm ply back, 12 mm ply drawer box.
- **Show wood**: solid oak drawer front, doors, and 38 mm countertop.
- **Shelf**: 860 mm span in 18 mm ply is the one watch-point — fine for pots
  and light appliances; for heavy dishware, thicken to 25 mm
  (`"material": {"shelf": 25}`) or add a solid front lip.
- The adjustable shelf lives in the **door section below the drawer box**; the
  validator's advisory ("shelf above a drawer bank may be obstructed") is
  acknowledged — don't pin the shelf in the top row of holes, where the
  500 mm-deep drawer box hangs.

## 6. Hardware & finish

- **Hinges**: 4 × Blum CLIP top BLUMOTION 110° (soft-close), 35 mm cup bore —
  18 mm oak door stock hosts the cup fine.
- **Slides**: Blum 230M side-mount, 500 mm, soft-close.
- **Pulls**: 96 mm CC, one per front.
- **Shelf pins**: 5 mm, in 32 mm-system rows (76 shelf-pin holes total).
- **Finish**: clear (oil-poly) — durable on the oak counter, wipeable inside.

## 7. Verification

Built with `woodai build spec.json --estimate --drill` — **0 errors,
geometry verified ✓** (17 panels, 0 interferences, envelope matches spec).
The single remaining warning (shelf/drawer advisory) is a deliberate,
documented choice — see §5.

## 8. Numbers at a glance

- **17 parts** (12 unique) — full dimensions in [out/cutlist.csv](out/cutlist.csv)
- **~4.47 m² sheet goods** (4 sheets) + 4.8 bd ft solid oak, 11 m edge banding
- **Hardware**: 31 items — [out/hardware.csv](out/hardware.csv)
- **Drilling**: 94 holes — [out/drilling.csv](out/drilling.csv)
- **Estimated cost**: **$668** (materials $440, hardware $40, banding $17, labour $140 @ 2.1 h, finishing $33)
- **Build time**: ~4.4 h, skill level: advanced (dovetail jig + dado)

## 9. Packet contents

| File | What |
|---|---|
| [spec.json](spec.json) | Source of truth — the parametric DSL spec |
| [out/build_package.pdf](out/build_package.pdf) | Printable build package (all sheets in one PDF) |
| [out/drawings.svg](out/drawings.svg) | Dimensioned 2D shop drawings |
| [out/render.png](out/render.png) | Front / side / isometric renders |
| [out/cutlist.csv](out/cutlist.csv) | Cut list |
| [out/hardware.csv](out/hardware.csv) | Hardware BOM |
| [out/drilling.csv](out/drilling.csv) | Drilling schedule (32 mm system) |
| [out/cutlayout.dxf](out/cutlayout.dxf) | Sheet-nesting layout |
| [out/cabinet.step](out/cabinet.step) / [.stl](out/cabinet.stl) / [.glb](out/cabinet.glb) | 3D models (CAD / print / web) |

The `out/` folder is generated (gitignored, per repo convention) — `spec.json`
is the source of truth. To (re)generate the packet or tweak the design: edit
`spec.json`, then

```bash
woodai build designs/base-cabinet-900/spec.json --estimate --drill \
  --package --drawings --render --step --stl --glb --dxf \
  --out designs/base-cabinet-900/out
```

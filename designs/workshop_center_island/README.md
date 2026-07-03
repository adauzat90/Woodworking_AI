# Workshop Center Island Bench

A heavy, double-sided drawer island for the middle of a workshop — work from any
side, store a shop's worth of tools in **18 slide-free drawers** down the long
sides and **32 open pigeonholes** capping the two ends.

![Island — front, side, isometric](island_render.png)

## Full assembly — plan & elevation

The 6 × 4 ft drawer island (below), plus a **12″-deep pigeonhole cabinet on one
end and an 18″-deep one on the other**, all under one continuous benchtop.

![Plan and elevation of the full assembly](assembly_plan.png)

## At a glance

| | |
|---|---|
| **Footprint** | 2592 × 1220 mm (**≈8.5 × 4 ft**) — 1830 mm drawer core + 305 mm (12″) + 457 mm (18″) end cabinets |
| **Work-surface height** | 915 mm (**36″ = 3 ft**) |
| **Drawers** | **18** — six banks of three graduated drawers, opening on **both** long sides |
| **Pigeonholes** | **32** open cubbies — a 4×4 grid in each end cabinet, opening outward at the ends |
| **Drawer motion** | **No metal slides** — traditional side-hung **wooden runners** |
| **Primary wood** | Hard maple (drawer banks); **birch plywood** (benchtop core + pigeonhole carcasses) |
| **Joinery** | M&T frames, **dovetailed** drawer boxes, **dadoed** cubby dividers/shelves |
| **Est. cost** | ≈ **$4,840** — banks ≈ $2,530 + pigeonholes ≈ $1,710 + plywood benchtop ≈ $600 |
| **Est. shop time** | ≈ 120 h banks + ~35 h pigeonholes + ~10 h benchtop (advanced) |

## Why this layout

A center island earns its floor space by being reachable from all four sides, so
the storage is split into **two back-to-back rows of three drawer banks**. You
get drawers on both 6-ft faces and can stand and work at any edge. Each bank is a
self-contained maple pedestal; the six bolt together and to the benchtop into one
rigid mass — a center table you can plane against without it walking across the
floor.

```
 PLAN (looking down)          1830 mm (6 ft)
      ┌───────┬───────┬───────┐
      │ Front │ Front │ Front │  ← 3 banks, drawers open this way
  1220│   L   │   C   │   R   │
  mm  ├───────┼───────┼───────┤  ← ~40 mm center spine
 (4ft)│ Back  │ Back  │ Back  │  ← 3 banks, drawers open the other way
      │   L   │   C   │   R   │
      └───────┴───────┴───────┘
     Each bank: 610 W × 590 D × 875 H, 3 graduated drawers
```

## The drawer system — no slides

Every drawer rides on **wooden runners**, the way case furniture was built for
centuries — nothing to buy, nothing to wear out, and dead simple to repair.

- Each drawer **side is ploughed with a groove** (12 × 6 mm) that rides a
  **maple runner strip** fixed to the bank frame (2 runners per drawer).
- Drawer boxes are **dovetailed** (tails on the sides so a front can never pull
  off) with a 6 mm plywood bottom in a groove.
- Fronts **graduate 200 / 250 / 300 mm** top-to-bottom — shallow drawers up top
  for hand tools and hardware, deep ones at the bottom for power tools.
- **Zero holes to drill** for hardware, and the only metal in the whole piece is
  the drawer pulls. (The tool's own drilling schedule confirms: *0 holes.*)

Wax the runners and grooves and the drawers glide. Because maple sides on maple
runners wear slowly and are easily re-waxed or re-planed, this outlasts any
ball-bearing slide.

## Structure & joinery

- **Legs:** 75 mm square hard-maple posts, four per bank.
- **Frames:** aprons and rails join the legs with **mortise-and-tenon** (7 × 45
  mm tenons) — the joint that resists the racking that kills legged furniture.
- **Assembly:** banks are screwed to each other along their touching faces and
  lag-screwed up into the benchtop, so the island behaves as one heavy unit.
- **Benchtop:** a **shop-built plywood slab**, 2592 × 1220 mm, running unbroken
  over the drawer banks *and* both pigeonhole ends. **Two layers of 18 mm birch
  plywood** are glued and screwed into a **36 mm** core — lay the two butt seams
  at **opposite ends so they stagger** and the top stays dead flat and stiff (it's
  continuously supported by the cabinets, so it never spans unsupported). A
  **40 mm solid-maple edge nosing** wraps and protects the plywood edges and gives
  you something to clamp against. Screw it down to the bank/cabinet tops through
  slotted holes (plywood is stable — no wood-movement worry like a solid top).
  - **Optional replaceable skin:** a **6 mm tempered-hardboard** sacrificial
    surface, **screwed (not glued)** on top so you can peel it off and swap it
    when it gets chewed up. With the skin the surface sits ~917 mm (36″); without
    it, ~911 mm — both "around 3 ft."

  Plywood buys you a lighter, flatter, cheaper top than the solid-maple glue-up,
  and the hardboard skin means the real work surface is a $25 consumable.

## End pigeonhole cabinets

![18″ pigeonhole cabinet](pigeonhole_18in_render.png)

Two open cubby cabinets butt against the 4-ft ends and stand to the benchtop, so
the top runs over them. One is **12″ (305 mm) deep**, the other **18″ (457 mm)
deep** — shallow for small parts and hardware, deep for jigs, sanders, and boxes.

- Each is a **4-column × 4-row grid = 16 open pigeonholes** (32 total), on a
  100 mm **toe-kick base** so you can stand right up to the end.
- Cubby opening ≈ **269 mm wide × ~180 mm tall**; depth is the full 12″/18″.
- Built from **18 mm birch plywood**, carcass and dividers, with **dadoed
  (housed) fixed shelves and dividers** — an egg-crate that needs no shelf pins
  and can't sag. *(The auto-BOM still lists shelf pins; ignore them — the shelves
  are captured in dadoes.)*
- **How it's modeled:** each cabinet is expressed as four side-by-side plywood
  **columns** (`pigeonhole_12in.json` / `pigeonhole_18in.json`), because a column
  side *is* a pigeonhole divider and a one-cubby-wide shelf can't sag — which is
  how the DSL sidesteps its lack of a vertical-divider field. Built for real as
  one **egg-crate** the adjacent columns share a divider, so you can drop ~3
  panels of the estimated material per cabinet.

Wood note: birch ply keeps the cubbies light, stable, and cheap; band the front
edges (and swap to maple ply) if you want them to match the maple bench.

## Materials & wood movement

The **drawer banks** are **hard maple** — the right wood for a bench (hard, tough,
heavy) and specifically for wooden runners, which need a dense, stable species.
The **benchtop and pigeonhole carcasses are plywood** (stable sheet goods).
Movement decisions that matter:

- The **plywood benchtop** doesn't move, so it's simply **screwed down** to the
  cabinet tops (through slightly slotted holes) — no figure-8 float needed.
- Drawer **bottoms are 6 mm plywood** (dimensionally stable) in a groove.

**Further cost / weight option:** the drawer banks are still solid maple (an
heirloom, and heavy — a *feature* for a center table). To cut roughly a third
more cost and weight, build the **bank carcasses and drawer boxes from
Baltic-birch plywood** too, keeping solid maple only for the legs, runners, and
drawer fronts. Wooden runners still work — just glue a solid-maple wear strip
where the ply drawer side rides.

## Per-bank cut list (×6 banks)

| Qty | L × W × T (mm) | Part |
|---:|---|---|
| 1 | 610 × 590 × 18 | Sub-top / mounting deck |
| 4 | 857 × 75 × 75 | Leg |
| 2 | 390 × 90 × 22 | Apron, side |
| 1 | 410 × 90 × 22 | Apron, back |
| 1 | 410 × 30 × 22 | Front rail (above top drawer) |
| 1 | 410 × 200 × 18 | Drawer front 1 (top) |
| 1 | 410 × 250 × 18 | Drawer front 2 |
| 1 | 410 × 300 × 18 | Drawer front 3 (bottom) |
| 6 | 525 × 160–260 × 12 | Drawer sides (dovetailed, grooved) |
| 6 | 361 × 160–260 × 12 | Drawer ends |
| 3 | 361 × 513 × 6 | Drawer bottoms (plywood) |
| 6 | 525 × 18 × 12 | **Wooden runners** |

Benchtop (built once): **32 × 1855 × 38 × 40 mm** maple strips, edge-glued to a
1830 × 1220 × 40 slab.

Full machine-readable lists: [`cutlist_one_bank.csv`](cutlist_one_bank.csv),
[`cutlist_banks.csv`](cutlist_banks.csv) (all six),
[`cutlist_benchtop.csv`](cutlist_benchtop.csv).

## Hardware

- **18 × bar pulls** (one per drawer) — the *only* purchased hardware on the base.
- Benchtop: **wood screws** into the cabinet tops (plywood is stable — no clips).
- Pigeonholes: assembly/back screws only — **no pins** (shelves are dadoed).
- **No drawer slides. No slide screws. No hinges.**

## A single drawer bank

![One drawer bank](drawer_bank_render.png)

## Rebuild / verify it yourself

The design is a parametric spec. From the repo root:

```bash
woodai build designs/workshop_center_island/workshop_island.json  --estimate --joinery
woodai build designs/workshop_center_island/pigeonhole_12in.json  --estimate
woodai build designs/workshop_center_island/pigeonhole_18in.json  --estimate
```

All three validate with **0 errors and 0 part interferences**. Edit the JSON
(drawer graduation, cubby grid, wood species, sizes) and rebuild to explore
variations.

### Note on the model

The island is expressed as six drawer-bank modules (the DSL's `nightstand` type
with `slide_type: "wood"`, which is the only drawer primitive that models
slide-free wooden runners) and the two pigeonhole cabinets as columns of open
`bookcase` boxes. The **plywood benchtop** that caps and unifies everything isn't
a parametric spec — it's just two laminated sheets and an edge, continuously
supported by the cabinets, so it's given as a plain sheet-goods cut list
([`cutlist_benchtop.csv`](cutlist_benchtop.csv)) rather than a `woodai` build.
Physically it's one slab screwed down over all eight cabinets.

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
| **Primary wood** | Hard maple (banks/top); birch plywood (pigeonhole carcasses) |
| **Joinery** | M&T frames, **dovetailed** drawer boxes, **dadoed** cubby dividers/shelves |
| **Est. cost** | ≈ **$4,890** — banks ≈ $2,530 + pigeonholes ≈ $1,710 + benchtop ≈ $650 |
| **Est. shop time** | ≈ 120 h banks + ~35 h pigeonholes + ~15 h benchtop (advanced) |

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
- **Benchtop:** a **40 mm edge-grain laminated hard-maple slab**, now
  **2592 × 1220 mm** so it runs unbroken over the drawer banks *and* both
  pigeonhole ends (~32 strips of 38 mm stock, ~54 bd ft). It is fastened down
  with **figure-8 / Z-clips** so the solid top can expand and contract across its
  width without cracking. *(An 8.5-ft solid top is a big glue-up; if you'd rather,
  keep the 1830 mm top over the banks and give each end cabinet its own flush
  40 mm top — the seams fall at the ends where you work least.)*

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

Everything shown is **hard maple** — the right wood for a bench (hard, tough,
heavy) and specifically for wooden runners, which need a dense, stable species.
Two deliberate movement decisions:

- The **benchtop floats** on figure-8 fasteners — never rigidly screwed across
  its width.
- Drawer **bottoms are 6 mm plywood** (dimensionally stable) in a groove.

**Cost / weight option:** an all-maple island is an heirloom (and heavy, which is
a *feature* for a center table). To cut roughly a third of the cost and a lot of
weight, build the **carcasses and drawer boxes from Baltic-birch plywood** and
keep solid maple only for the legs, runners, drawer fronts, and benchtop. Wooden
runners still work — just glue a solid-maple wear strip where the ply drawer side
rides.

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
- **~40 × figure-8 / Z-clip** tabletop fasteners (benchtop attachment).
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
woodai build designs/workshop_center_island/benchtop.json         --estimate
```

All four validate with **0 errors and 0 part interferences**. Edit the JSON
(drawer graduation, cubby grid, wood species, sizes) and rebuild to explore
variations.

### Note on the model

The island is expressed as six drawer-bank modules (the DSL's `nightstand` type
with `slide_type: "wood"`, which is the only drawer primitive that models
slide-free wooden runners). The 40 mm benchtop that caps and unifies them is a
separate glue-up (`benchtop.json`) — in the tool a single top can't span across
independent modules, so it's specified and costed on its own. Physically it's one
slab lagged down over all six banks.

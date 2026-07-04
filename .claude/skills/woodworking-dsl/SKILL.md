---
name: woodworking-dsl
description: Author and verify furniture in the Woodworking_AI parametric DSL — write a JSON spec, build it with the `woodai` CLI, read the validator + geometry critic feedback, and repair until it passes. Use when turning a furniture design into a runnable spec, producing a cut list / cost / drilling schedule / 3D export, or debugging a spec that fails validation. Pairs with the furniture-design skill (which decides WHAT to build; this skill EXPRESSES and VERIFIES it).
---

# Woodworking_AI DSL

The source of truth is a small, typed **JSON spec**. You don't draw geometry —
you write a spec, the engine compiles it into geometry, a cut list, a hardware
schedule, a cost estimate, and a drilling plan, and a **validator + critic**
tell you exactly what's wrong so you can repair the spec. This is an
execute-and-verify loop: **propose → build → read feedback → repair → repeat.**

## The loop (do this every time)

1. **Pick the `kind`** (see below), copy the matching minimal example.
2. **Write the spec** to a `.json` file. Add fields only to override a default —
   every unset field has a sane default and a minimal spec is already buildable.
3. **Build & verify it** with the CLI:
   ```bash
   woodai build spec.json --estimate --drill --joinery
   ```
   This validates, critiques the geometry, and prints the cut list, hardware
   BOM, cost, drilling schedule, and joinery setup. Add `--imperial` for
   fractional-inch reports, `--step --stl --glb --dxf --out ./out` to export.
4. **Read the feedback.** The build prints `issues` — lines tagged `error:` or
   `warning:`. **Every `error:` must be fixed** (the design isn't buildable);
   `warning:` is advice — fix it or make a deliberate choice.
5. **Repair the spec** to resolve every error, rebuild, repeat until clean.
6. A spec with **no errors** and a passing critique is done. Report the spec plus
   the cut-list summary / quote.

You can also drive it from Python when you need to inspect objects:
```python
from woodworking_ai import spec_from_dict, validate, generate_cutlist, estimate
spec = spec_from_dict(json.load(open("spec.json")))
r = validate(spec); print(r.ok, [str(i) for i in r.issues])
print(generate_cutlist(spec).summary()); print(estimate(spec).total)
```

> If `woodai` isn't on PATH, the package needs installing once:
> `pip install -e ".[cad,render]"` from the repo root. The DSL + validator +
> cut list work with **no** extras; `[cad]` adds 3D/STEP/STL/GLB, `[render]`
> adds PNG snapshots.

## Choosing the `kind`

Set `"kind"` first; it selects the whole spec shape. Available kinds:

| kind | what | key fields |
|---|---|---|
| `cabinet` | one box of casework | `cabinet_type`, width/height/depth, doors, drawers, shelves, `material`, `hardware_brand`, `stock` |
| `table` | top on four legs + aprons | width(=length)/depth/height, leg, apron_height, top_fixing |
| `wall_shelf` | one board + wall fixing | length/depth/thickness, fixing, load_kg_per_m |
| `box` | six-board box / chest | width/depth/height, thickness, corner_joint, lid |
| `bench` | seat on legs (+ stool) | width/depth/height, stretchers, joinery |
| `frame` | picture / mirror frame | opening_w/opening_h, molding_width, corner_joint |
| `bed` | knock-down bed | size, post, head/foot/deck height, `rail_height`, `rail_thickness`, `panel`, `slats`, connector, finish |
| `cutting_board` | edge/end-grain glue-up | length/width/thickness, grain_style, species |
| `nightstand` | small legged cabinet + drawer | width/depth/height, drawers, shelf |
| `desk` | writing desk | width/depth/height, drawers, modesty_panel, grommet |
| `workbench` | heavy bench, dog holes, vise | width/depth/height, top_thickness, vise |
| `project` | **>1 piece** — a run / built-in | `runs` or `components` |

`cabinet_type` (for `kind:"cabinet"`): `base` (toe kick, open top, takes a
counter), `wall` (hung, NO toe kick — set `"toe_kick": null`, enclosed top,
300–350 deep), `tall` (pantry, floor-to-ceiling, toe kick, many shelves),
`corner_blind` (set `blind_width`), `corner_diagonal` (set `corner_cut`),
`bookcase` (`doors:0`, several shelves), `dresser` (drawer bank).

## Minimal examples (copy, then adjust)

```json
{"kind":"cabinet","cabinet_type":"base","name":"Sink Base","width":900,"height":720,"depth":560,"doors":2,"shelves":1,"drawers":[{"front_height":140}]}
```
```json
{"kind":"table","name":"Dining Table","width":1600,"depth":900,"height":740,"leg":70,"species":"walnut","material_form":"solid","top_fixing":"floating"}
```
```json
{"kind":"bookcase","cabinet_type":"bookcase","name":"Bookcase","width":800,"height":1800,"depth":300,"doors":0,"shelves":4,"toe_kick":null}
```

## Multi-piece projects — PREFER declarative `runs`

For a kitchen run / built-in, emit `"kind":"project"`. **Use a `runs` block, not
hand-computed x/y coordinates** — the loader lays each run's `items` end-to-end
along a wall and computes every x/y/rotation, eliminating the cumulative-width
arithmetic that is the #1 source of overlap errors.

```json
{"kind":"project","name":"Galley","units":"mm","runs":[
  {"start":[0,0],"angle":0,"gap":0,"items":[
    {"spec":{"kind":"cabinet","cabinet_type":"base","width":600,"drawers":[{"front_height":140},{"front_height":200},{"front_height":260}],"doors":0}},
    {"spec":{"kind":"cabinet","cabinet_type":"base","width":900,"doors":2}},
    {"spec":{"kind":"appliance_void","type":"dishwasher","width":600}}
  ]}
]}
```
- An **L/U kitchen** is two+ runs at right angles: `angle` is degrees CCW
  (`0`=+X, `90`=+Y). The second run's `start` turns the corner.
- A repeated group → declare it once under `"definitions"` and drop copies with
  `{"ref":"name","x":..,"y":..}`.
- The validator checks plan collisions across the whole run — footprints must
  not overlap.

### Appliances — two shapes
- **Sink / cooktop** = a cutout *hosted by a countertop*: add to a cabinet's
  `accessories`: `{"kind":"appliance","type":"sink","cutout_w":700,"cutout_d":450}`
  alongside `{"kind":"countertop",...}`.
- **Range / dishwasher / fridge** = a free-standing GAP: place as its own
  component `{"kind":"appliance_void","type":"dishwasher","width":600}` — no box,
  no cut-list parts.

## Reading validator / critic feedback

Feedback arrives as `issues` (and in Python, `validate(spec).issues` /
`critique(spec)`). Each issue has a **level**: `error:` (blocks the build — must
fix), `warning:` (advice — fix or make a deliberate, stated choice), and `info:`
(informational only — proportion notes, buying/finishing tips; never blocks).
Translate each into a spec edit:

| Message theme | Fix |
|---|---|
| `panel … exceeds 2440×1220 sheet` | split the piece, or it's a glue-up — set realistic dims |
| `shelf … deflection/sag` | thicker shelf, stiffer `shelf_species`, shorter span, or add support |
| `tall/dresser … tip-over / ASTM F2057` | set `"anti_tip": true` |
| `toe space shallower/shorter than minimum` | toe_kick height ≥75, setback ≥50 |
| `door too wide to host a hinge cup` / single wide door | split into 2 doors or add `center_mullion` |
| `drawer corner … butt … weak` | `corner_joint`: dovetail / box / rabbet |
| `dovetail tails on the front` | `dovetail_tails: "sides"` |
| `solid top fixed … will crack` | `top_fixing: "floating"` |
| `sheet thickness … not real stock` | use 6/9/12/15/18/21/25 mm |
| `joint not makeable with your tools` | switch to the suggested feasible joinery |
| footprints `overlap` in a project | fix `gap`/`start`, or prefer a `runs` block |
| field "was not recognized and was ignored" (lint) | you used a wrong/typo field name — use the correct one |

The critic also rebuilds the geometry and checks the **envelope, part
interferences, and front coverage** against the spec — trust it; it catches real
collisions measurement-only checks miss.

## Tooling constraint (optional)

Constrain the design to joints a shop can actually cut:
```bash
woodai build spec.json --shop hand        # hand tools + drill only
woodai build spec.json --shop hobbyist    # table saw, router, jigs (no Domino)
woodai build spec.json --tools "table_saw,router,drill,pocket_jig,domino"
woodai build spec.json --tools-list       # just print the tool/jig checklist
```
Unmakeable joints are flagged with a feasible substitute; a tool gap never
blocks the math.

## Recent options worth knowing

- **Tapered legs**: `table`/`bench`/`nightstand`/`desk` take `"leg_taper": true`
  (+ optional `"leg_tip"`, 0 = auto). The cut list notes the taper; the envelope
  is unchanged.
- **Drawer runners**: a `nightstand`/`desk` drawer defaults to metal slides; set
  `"slide_type": "wood"` for traditional wooden runners (no metal hardware, no
  slide drilling) — the right call for a hand-tool build — or `"none"`.
- **Bed deck**: a queen/king bed warns about slat sag; set
  `"center_support": true` to add a centre rail + leg and clear it.
- **Run worktop**: a `project` takes a top-level
  `"countertop": {"material","thickness","overhang"}` for ONE continuous slab
  spanning the base run — a per-cabinet countertop can't span multiple cabinets.
- **Construction lumber** (cheap shop furniture): set `"species": "spf"` (or
  `"douglas_fir"`) and give legs a dimensional section with `"leg_depth"` — e.g.
  `"leg": 38, "leg_depth": 89` is a 2x4 (wide face along the depth), `89/89` a
  4x4. Any solid part whose section is a stock size (2x4, 4x4, 1x4, …) is then
  priced **by the stick** (whole 8/10/12/16ft lengths, first-fit nested) instead
  of hardwood board feet — no 15% milling allowance, since it's S4S. The
  validator also flags a near-miss ("leg 91×91 is nearly a 4x4 — spec 89×89")
  so you snap onto stock and skip a rip.
- **Cleaner output**: `woodai build spec.json --quiet` drops the spec JSON echo;
  `--joinery` now also prints for a project/run.
- Unrecognized fields now print `warning: ignored unknown field '…'` — if you
  set something and nothing changes, check for that line.

## Gotchas

- **Units don't mix.** Everything in one spec uses `units` ("mm" default or
  "in"); inches convert to mm on load. For a cabinet, dims are **overall**, and
  `height` **includes** the toe kick.
- For a `table`/`bench`/`desk`, `width` is the **length** of the top, `depth` is
  its other horizontal dimension.
- `wall` cabinets have **no toe kick** — set `"toe_kick": null`. To set custom
  dimensions use the object form: `"toe_kick": {"height": 100, "setback": 50}`.
- **Override individual sheet thicknesses** with the `material` object, not the
  whole-piece form: `"material": {"shelf": 25}` thickens only the shelves (e.g.
  to kill a sag warning) and leaves carcass/back/door at their defaults. Keys:
  `carcass`, `back`, `door`, `shelf`, `drawer_box`, `door_panel`.
- **Drawers do NOT auto-graduate on a cabinet.** `"drawers": 3` is not valid for
  a cabinet — `drawers` is a *list*, and you give each its own `front_height`
  (e.g. `[{"front_height":150},{"front_height":200},{"front_height":260}]`). On a
  `nightstand`/`desk`, `drawers` is an integer count and every drawer shares
  `drawer_front_height`; to graduate them set `drawer_front_heights` (a list,
  top→bottom). Those types also take a `drawer_corner_joint` (default `rabbet`).
- **Soft-close is implicit** — there is no `soft_close` field. Setting
  `"hardware_brand": "blum"` (or `hettich`/`grass`) selects soft-close BLUMOTION
  slides and CLIP-top hinges. Writing `"soft_close": true` is silently dropped.
- `--joinery` prints a separate "Joinery setup" sheet, but it is **suppressed
  when combined with `--drill`** in one run. Run `woodai build spec.json
  --joinery` on its own to see the dado/rabbet/cope dimensions.
- A solid wood `table`/`bench` top must use `"top_fixing":"floating"`.
- Material make-up is optional but improves the BOM/quote: set
  `material_form`+`species` for the whole piece and override show-wood areas via
  `stock` (e.g. plywood carcass, `stock.front`/`stock.frame` = solid oak). A
  sheet `material_form` never turns legs/aprons/face-frame into plywood — give
  them a `species`.
- Don't invent fields. If a value seems to have no effect, run the build and
  check the lint note for "not recognized" fields.

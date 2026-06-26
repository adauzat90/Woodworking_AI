---
name: furniture-design
description: Design buildable furniture and cabinetry — ergonomic dimensions, sound proportions, joinery selection, wood-movement rules, and material choices. Use BEFORE writing any spec, when deciding what to build, sizing a piece, choosing joints/wood, or sanity-checking a design for strength and human use. Pairs with the woodworking-dsl skill, which turns these decisions into a runnable spec.
---

# Furniture & cabinetmaking design

This skill is the *design judgment* a master cabinetmaker brings before any
drawing happens: what dimensions fit a human, what proportions look right, which
joint survives the loads, and how wood moves. Decide these first, then express
them with the **woodworking-dsl** skill.

Work in this order: **(1) intended use & user → (2) overall dimensions →
(3) proportions → (4) structure & joinery → (5) material & movement →
(6) hardware & finish.** Skipping to dimensions before use is the #1 cause of a
piece that "works" on paper but is unpleasant to live with.

## 1. Standard dimensions (the non-negotiables)

These come from human bodies and appliances; deviate only with a reason.

**Heights (floor to working/sitting surface):**
- Kitchen counter / base cabinet: **900 mm** (≈36") incl. countertop; the box is
  ~720 mm + ~100 mm toe kick + ~38 mm top.
- Dining / writing table & desk: **735–760 mm** (740 typical).
- Bar counter: 1050–1100 mm; kitchen island raised bar: 1060 mm.
- Chair / dining seat: **430–460 mm**. Bench seat: same. Stool: **650–760 mm**
  (counter stool ~650, bar stool ~750).
- Coffee table: 400–460 mm. Nightstand: near mattress top, **550–650 mm**.
- Desk keyboard/writing surface: 720–740 mm; min knee clearance 600 mm high.

**Depths & clearances:**
- Base cabinet: **560–600 mm** deep (610 mm counter with overhang).
- Wall cabinet: **300–350 mm** deep, hung so the bottom is ~1500 mm off the floor
  (≈450 mm above a 900 mm counter).
- Tall/pantry: 560–600 mm deep, 1900–2400 mm tall.
- Dining: allow **600 mm width per place setting**, 300 mm depth of table per
  diner; 900–1000 mm walk space behind a pulled-out chair.
- Bookshelf clear height: paperbacks 200 mm, hardbacks 300 mm, binders 320 mm;
  shelf depth 250–300 mm.
- Toe kick: **≥75 mm high, ≥50 mm deep** (KCMA). Standard 100 × 50–75 mm.
- Knee space under a desk/table apron: ≥600 mm high, ≥500 mm deep.

**Reveals & gaps (frameless/overlay):** 3 mm reveal around doors and drawer
fronts is the default; 2 mm gap between adjacent fronts.

## 2. Proportions

A piece reads as "designed" when its main rectangles share a pleasing ratio.
Defaults that rarely look wrong:
- Favor **1:1.6 (golden) or simple 2:3, 3:5** for door/front faces and overall
  elevation.
- A run of drawers usually **graduates**: shallower at top, deeper at bottom
  (e.g. 150 / 200 / 250 / 300 mm) — both stronger visually and more useful.
- A single door over ~500–550 mm wide will rack/sag and hit adjacent doors —
  **split into a pair** (or add a center mullion) past that width.
- Legs: thicker reads sturdier. Table legs ~1/12 of height square (≈60 mm for a
  740 mm table); fine tables taper the inner faces below the apron.

## 3. Structure & joinery — pick the joint for the load

Match the joint to the force it must resist. Strongest first within each use:

| Where | Good → better → best | Avoid |
|---|---|---|
| Case/carcass corner | screw/pocket → **dado/rabbet** → domino/dowel | butt (no glue surface) |
| Frame (table leg-to-apron, doors) | dowel/pocket → domino → **mortise & tenon** | butt, plain screw |
| Drawer corner | rabbet → locking rabbet → box → **dovetail** | butt (pulls apart) |
| Picture/mirror frame | miter → **splined miter / half-lap** | plain glued miter (end-grain) |
| Solid panel (top, wide board) | — edge-glue narrower boards — | one wide board (cups) |

Rules of thumb:
- **End grain doesn't glue.** Any joint relying on an end-grain glue line (butt
  corners, plain miters) needs mechanical help: a spline, dowel, domino, tenon,
  or interlock.
- **Drawers get pulled open**, so dovetail tails go on the **sides**, not the
  front — tails on the front let it pull off.
- **Racking** (a parallelogram collapse) is what kills legged furniture. Resist
  it with M&T or domino leg joints **and** lower stretchers on tall/narrow bases
  (stools, benches, workbenches).
- Bigger/longer ⇒ stronger joint. A 600 mm stool can dovetail; a 2 m workbench
  needs draw-bored M&T.

## 4. Wood movement (the rule beginners skip)

Wood shrinks/swells **across** the grain with humidity, never along it.
A 600 mm solid panel can move 5–10 mm seasonally.

- **Never trap a wide solid panel.** Frame-and-panel doors float the panel in a
  groove. A solid tabletop fastens with **figure-8s, Z-clips, or slotted
  buttons — "floating," never rigidly screwed** across its width, or it cracks.
- Orient strength along the grain (shelves, rails span with the grain).
- Sheet goods (plywood/MDF) are dimensionally stable — they don't need movement
  allowance, which is why carcasses are usually sheet goods and only the
  *show-wood* (doors, face frame, top, legs) is solid lumber.
- A knock-down bed must come apart to move a house — rails join posts with
  **bed bolts or hook plates, never glue.**

## 5. Material selection

- **Carcass:** plywood (stable, strong, paint/veneer) or MDF (flat, paints well,
  heavy, no moisture). Particleboard/melamine for budget/utility.
- **Show wood:** hardwood for doors, face frames, tops, legs. Oak (open grain,
  tough), maple/birch (tight, pale, paints well), walnut/cherry (fine,
  furniture), pine (soft, cheap, dents).
- **Shelves sag.** Limit deflection to ≈span/360. An 800 mm shelf of 18 mm
  plywood under books is borderline — thicken to 25 mm, add a center support, a
  solid front lip, or shorten the span.
- **Cutting boards:** close-grain food-safe woods (hard maple, walnut, cherry);
  avoid open-pore oak; finish with mineral oil / board butter, never film
  finish. End-grain = butcher block (knife-friendly, two-stage glue-up).
- **Workbench:** hard, heavy, tough (beech, maple, ash); thick laminated top.

## 6. Hardware & finish (brief)

- Concealed (Euro) hinges need a **35 mm cup bore**; door stock ≥16 mm and each
  door ≥~50 mm wide to host the cup. Inset doors need their own clearance.
- Drawer slides: side-mount ball-bearing need **~12.7 mm clearance per side**;
  undermount need a precise box notch. Size the slide to the cabinet depth.
- Anti-tip: tall units and any dresser/chest ≥686 mm tall must ship with a wall
  restraint (ASTM F2057 tip-over) — design in a marked attachment point.
- Finish by use: oil (food/feel, easy repair), clear/poly (durable, tabletops),
  paint (MDF/poplar), stain+clear (color + protection).

## Design review checklist (run before finalizing)

- [ ] Does every height/depth match a human or appliance (§1)?
- [ ] Any single door > ~550 mm? Split it.
- [ ] Will any shelf sag under its real load? Thicken/support/shorten.
- [ ] Any wide solid panel trapped so it can't move? Float it.
- [ ] Does each joint suit its load (drawers dovetail, legs M&T, no glued end grain)?
- [ ] Tall/heavy piece — is anti-tip designed in?
- [ ] Toe kick ≥75×50 mm? Knee space ≥600 mm where someone sits?
- [ ] Do the main faces share a deliberate proportion?

Once these are settled, hand the decisions to the **woodworking-dsl** skill to
write and verify the spec.

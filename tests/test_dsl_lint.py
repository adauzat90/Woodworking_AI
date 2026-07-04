"""Parse-time lint surfaces keys the tolerant loader would silently drop."""

from woodworking_ai.dsl_lint import lint_spec_dict, KNOWN_KINDS


def _keys(issues):
    return {i.key for i in issues}


def test_clean_cabinet_has_no_issues():
    assert lint_spec_dict(
        {"cabinet_type": "base", "width": 600, "height": 720, "depth": 560,
         "doors": 2}) == []


def test_unknown_top_level_field_is_flagged_with_suggestion():
    issues = lint_spec_dict({"cabinet_type": "base", "hieght": 720})
    assert _keys(issues) == {"hieght"}
    assert "did you mean 'height'" in issues[0].message


def test_unknown_field_in_nested_material():
    issues = lint_spec_dict(
        {"cabinet_type": "base", "material": {"carcas": 18}})
    assert _keys(issues) == {"carcas"}
    assert "material" in issues[0].path
    assert "did you mean 'carcass'" in issues[0].message


def test_unknown_field_in_drawer_and_stock():
    issues = lint_spec_dict({
        "cabinet_type": "base",
        "drawers": [{"front_height": 140, "corner_jont": "dovetail"}],
        "stock": {"front": {"speces": "oak"}},
    })
    assert _keys(issues) == {"corner_jont", "speces"}


def test_unknown_key_under_component_spec_is_located():
    issues = lint_spec_dict({"kind": "project", "components": [
        {"label": "B1", "spec": {"cabinet_type": "base", "widht": 600}}]})
    assert _keys(issues) == {"widht"}
    assert issues[0].path == "components[0].spec.widht"


def test_inline_component_spec_allows_placement_keys():
    # A component with no "spec" key carries placement + spec fields together.
    issues = lint_spec_dict({"kind": "project", "components": [
        {"cabinet_type": "base", "width": 600, "x": 0, "y": 0, "label": "B1"}]})
    assert issues == []


def test_runs_items_are_linted():
    issues = lint_spec_dict({"kind": "project", "runs": [
        {"start": [0, 0], "angle": 0, "items": [
            {"spec": {"cabinet_type": "base", "dpeth": 560}}]}]})
    assert _keys(issues) == {"dpeth"}


def test_unknown_accessory_kind_and_field():
    issues = lint_spec_dict({"cabinet_type": "base", "accessories": [
        {"kind": "countertop", "thicknes": 38},
        {"kind": "gadget"}]})
    keys = _keys(issues)
    assert "thicknes" in keys           # bad field on a known accessory
    assert any("unknown accessory kind 'gadget'" in i.message for i in issues)


def test_table_routes_and_lints_table_fields():
    issues = lint_spec_dict({"kind": "table", "width": 1600, "lgs": 4})
    assert _keys(issues) == {"lgs"}


def test_schema_version_is_accepted():
    assert lint_spec_dict(
        {"cabinet_type": "base", "width": 600, "schema_version": "1.0"}) == []


def test_known_kinds_cover_the_loader():
    assert {"cabinet", "table", "wall_shelf", "box", "bench",
            "project", "assembly", "appliance_void"} <= KNOWN_KINDS


def test_lint_covers_legged_and_leaf_kinds():
    # The newer kinds used to mis-route (and even crash) the linter; their own
    # fields must be clean and a genuine unknown field still flagged.
    assert lint_spec_dict(
        {"kind": "desk", "drawers": 2, "modesty_panel": True, "grommet": True,
         "drawer_front_heights": [100, 120], "drawer_corner_joint": "rabbet"}) == []
    assert lint_spec_dict(
        {"kind": "workbench", "dog_holes": 8, "top_fixing": "fixed",
         "vise": True}) == []
    assert lint_spec_dict({"kind": "frame", "opening_w": 400,
                           "corner_joint": "splined_miter"}) == []
    # leg_taper IS a desk field now; a genuine typo is still flagged.
    assert lint_spec_dict({"kind": "desk", "leg_taper": True}) == []
    assert _keys(lint_spec_dict(
        {"kind": "desk", "drawers": 1, "leg_tapr": True})) == {"leg_tapr"}


def test_piece_with_components_routes_as_piece_not_project():
    # A `piece` carries its own `components` (placed sub-components); the
    # linter must mirror the loader's kind-first routing, not shape-infer a
    # project and flag every legitimate piece field as unknown.
    spec = {
        "kind": "piece", "name": "Assembly table", "units": "mm",
        "material_form": "solid", "species": "spf", "finish": "none",
        "parts": [{"name": "Top", "at": [0, 0, 882], "size": [1200, 600, 18],
                   "grain": "x", "material_form": "plywood",
                   "repeat": {"count": 2, "step": [0, 0, 400]}}],
        "joints": [{"parts": ["Top", "Top#2"], "joinery": "screw"}],
        "components": [
            {"component": "legged_base", "name": "Base", "at": [0, 0, 0],
             "width": 1200, "depth": 600, "height": 882, "leg": 89,
             "leg_depth": 38, "joinery": "screw"},
            {"component": "shelf_bank", "name": "Shelves", "at": [100, 0, 100],
             "width": 1000, "depth": 600, "height": 600, "shelves": 2,
             "shelf_thickness": 18, "upright_thickness": 38,
             "load_kg_per_m": 60},
        ],
    }
    assert lint_spec_dict(spec) == []


def test_piece_nested_typos_are_flagged():
    issues = lint_spec_dict({
        "kind": "piece",
        "parts": [{"name": "A", "size": [100, 100, 18], "grian": "x",
                   "repeat": {"count": 3, "stp": [0, 0, 100]}}],
        "joints": [{"parts": ["A", "A#2"], "jonery": "screw"}],
        "components": [{"component": "legged_base", "leg_dpth": 38}],
    })
    assert _keys(issues) == {"grian", "stp", "jonery", "leg_dpth"}
    by_key = {i.key: i for i in issues}
    assert "parts[0]" in by_key["grian"].path
    assert "repeat" in by_key["stp"].path
    assert "did you mean 'leg_depth'" in by_key["leg_dpth"].message


def test_piece_unknown_component_name_is_flagged():
    issues = lint_spec_dict({
        "kind": "piece",
        "components": [{"component": "legged_bse", "width": 900}],
    })
    assert _keys(issues) == {"component"}
    assert "did you mean 'legged_base'" in issues[0].message


def test_piece_alias_kinds_lint_the_same():
    bad = {"kind": "custom",
           "parts": [{"name": "A", "size": [100, 100, 18], "grian": "x"}]}
    assert _keys(lint_spec_dict(bad)) == {"grian"}

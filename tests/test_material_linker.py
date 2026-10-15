# Material Linker flow: geometry merge, MaterialX reference, rule, real USD binding, removal, rebuild.
#
# Revision : 10-10-2026 | Auteur : BSM
import os
from _common import FIXTURES, Checker, base_config, load_tool, scratch_dir

hou, k = load_tool()
t = Checker("material linker")
out_dir = scratch_dir("material_linker")
stage = hou.node("/stage")
mtlx = os.path.join(FIXTURES, "red.mtlx").replace("\\", "/")
logs = []

sph = stage.createNode("sphere", "my_sphere")
box = stage.createNode("cube", "my_cube")
geo = stage.createNode("merge", "user_geo")
geo.setInput(0, sph)
geo.setInput(1, box)

cfg = dict(base_config(out_dir), scene_mode="Studio", env_type="HDRI Image", geo_source=geo.path())
k.setup_karma_environment(cfg, logs.append)
t.check("geometry merged with the environment", [n.name() for n in stage.node("geo_merge").inputs()] == ["studio_key", "user_geo"])
t.check("material library fed by the merge", stage.node("mtlx_materials").input(0).name() == "geo_merge")

linker = k._get_or_create_material_linker(stage)
t.check("linker inserted after the library", k._insert_material_linker_in_chain(stage, linker, logs.append)
        and linker.input(0).name() == "mtlx_materials" and stage.node("standard_aovs").input(0) == linker)

name, prim = k._list_materials_in_file(mtlx)[0]
t.check("material found in the .mtlx", (name, prim) == ("M_red", "/MaterialX/Materials/M_red"), (name, prim))
dst = k._linker_add_reference(linker, mtlx, prim, name)
t.check("reference path", dst == "/materials/M_red", dst)
t.check("identical reference is reused", k._linker_add_reference(linker, mtlx, prim, name) == dst and len(k._linker_references(linker)) == 1)
t.check("target prims listed", [p for p, _, _ in k._stage_target_prims(linker.stage())] == ["/my_sphere", "/my_cube"])

k._linker_assign(linker, dst, ["/my_sphere"])
t.check("sphere bound (real USD binding)", k._bound_material_name(linker.stage(), "/my_sphere") == "M_red")
t.check("cube not bound", k._bound_material_name(linker.stage(), "/my_cube") == "")

k._linker_assign(linker, dst, ["/my_sphere", "/my_cube"])
t.check("one rule holds both prims", k._linker_rules(linker) == [(1, dst, ["/my_sphere", "/my_cube"])], k._linker_rules(linker))
t.check("both bound", k._bound_material_name(linker.stage(), "/my_cube") == "M_red")

other = k._linker_add_reference(linker, mtlx, prim + "2", "Other")
k._linker_assign(linker, other, ["/my_cube"])
rules = {owner: includes for _, owner, includes in k._linker_rules(linker)}
t.check("a prim moves to its new material (one material per prim)", rules.get(dst) == ["/my_sphere"] and rules.get(other) == ["/my_cube"], rules)

t.check("unassign reports the count", k._linker_unassign(linker, ["/my_cube"]) == 1)
t.check("empty rule deleted", len(k._linker_rules(linker)) == 1)
t.check("cube unbound after removal", k._bound_material_name(linker.stage(), "/my_cube") == "")

# --- Edit Material LOP after the linker (nodal view of a material) ---
edit = k._get_or_create_material_edit(stage)
t.check("edit node created and owned", k._material_edit_node(stage) == edit and edit.name() == "material_edit")
k._insert_material_edit_in_chain(linker, edit)
t.check("edit node sits between the linker and the AOVs", edit.input(0) == linker and stage.node("standard_aovs").input(0) == edit)
problems = k._material_edit_load(edit, dst)
print("INFO Edit Material problems: {}".format(problems))
print("INFO Edit Material after load: matpath1={!r} matnode1={!r} children={}".format(
    edit.parm("matpath1").evalAsString(), edit.parm("matnode1").evalAsString(), [c.name() for c in edit.children()]))
t.check("Edit Material takes the material path", edit.parm("matpath1").evalAsString() == dst, edit.parm("matpath1").evalAsString())
t.check("Edit Material loads the material without a problem", problems == [], problems)
user_node = stage.createNode("editmaterial", "user_edit")
stage.node("material_edit").destroy()
user_clash = stage.createNode("editmaterial", "material_edit")
try:
    k._get_or_create_material_edit(stage)
    refused = False
except hou.OperationFailed:
    refused = True
t.check("a user's node named material_edit is refused, not reused", refused and k._material_edit_node(stage) is None)
user_clash.destroy()
user_node.destroy()
edit = k._get_or_create_material_edit(stage)
k._insert_material_edit_in_chain(linker, edit)

k.setup_karma_environment(cfg, logs.append)
t.check("rebuild keeps the edit node wired", edit.input(0) == linker and stage.node("standard_aovs").input(0) == edit)
edit.destroy()
linker.setInput(0, stage.node("mtlx_materials"))
k.setup_karma_environment(cfg, logs.append)
t.check("rebuild keeps the linker wired", linker.input(0).name() == "mtlx_materials" and stage.node("standard_aovs").input(0) == linker)
t.check("rebuild keeps the assignment", k._bound_material_name(stage.node("karma_settings").stage(), "/my_sphere") == "M_red")

k.setup_karma_environment(dict(cfg, geo_source=""), logs.append)
t.check("clearing the geometry source removes the merge", stage.node("geo_merge") is None)
t.check("no warning logged", not [l for l in logs if "WARN" in l], [l for l in logs if "WARN" in l])

# --- robustness of the catalog helpers ---
caught = (ValueError, KeyError, IndexError, TypeError, AttributeError, hou.Error)
for label, payload in (("not JSON", "xx"), ("a list instead of an object", "[1, 2]"),
                       ("a source with no arguments", '{"ids":["a"],"assettypes":["material"],"labels":["a"],"filepaths":["f"],"asset_data":["{}"],"sources":[[]]}')):
    try:
        k._parse_catalog_drop(payload)
        raised = None
    except caught as exc:
        raised = type(exc).__name__
    except Exception as exc:
        raised = "UNCAUGHT " + type(exc).__name__
    t.check("malformed drop ({}) raises something the handler catches".format(label), raised is not None and not raised.startswith("UNCAUGHT"), raised)

t.check("non-material assets in a drop are ignored", k._parse_catalog_drop('{"ids":["a"],"assettypes":["asset"],"labels":["a"],"filepaths":["f"],"asset_data":["{}"],"sources":[["x","y"]]}') == ([], []))

for bad in ("C:/data/a@b/red.mtlx", "C:/data/red\n.mtlx"):
    try:
        k._material_catalog_file(bad)
        rejected = False
    except ValueError:
        rejected = True
    t.check("catalog wrapper refuses a path that would break the USD reference", rejected, repr(bad))
t.check("a USD file is passed through untouched", k._material_catalog_file("C:/data/mats.usda") == "C:/data/mats.usda")

import bsm_karma.catalog as catalog_module
catalog_module.AMD_LIBRARY_URL = "http://127.0.0.1:9/api"  # a closed local port: unreachable at once, no real network involved
ok, reason = k._amd_library_reachable(timeout=3.0)
t.check("unreachable AMD library is reported with a reason, not a hang", ok is False and bool(reason), reason)

t.done()

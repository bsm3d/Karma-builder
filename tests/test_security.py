# Untrusted text (drag payload, remote catalog metadata, a path in a scene) must never reach something that
# evaluates it. hou.text.expandString runs backtick expressions (verified on H22) and so do node parms when the
# node cooks: each test tries the attack and checks that the marker file a command would create is not there.
#
# Revision : 10-10-2026 | Auteur : BSM
import json
import os
import re

from _common import ROOT, Checker, load_tool, scratch_dir

hou, k = load_tool()
t = Checker("security")
work = scratch_dir("security")
marker = os.path.join(work, "pwned.txt").replace("\\", "/")
if os.path.exists(marker):
    os.remove(marker)
attack = '`system("echo x > {}")`'.format(marker)


# --------------------------------------------------------
# Stands in for hou.AssetGalleryDataSource, so no network or real catalog is involved.
class FakeSource:
    built = []

    # --------------------------------------------------------------------------------
    def __init__(self, identifier, args=""):
        FakeSource.built.append((identifier, args))
        self.prepared = []
        self._file = FakeSource.file_for_item

    #------------------------------------------------------------
    def filePath(self, ident):
        return self._file

    # ------------------------------------------------------------------------
    def prepareItemForUse(self, ident):
        self.prepared.append(ident)
        FakeSource.prepared.extend(self.prepared)
        return ""


FakeSource.prepared = []
FakeSource.file_for_item = ""


# ------------------------------------------------------------
def payload(label="mat", file_path="", source=("x", ""), ident="id1", name="mat", prim="/MaterialX/Materials/mat"):
    return json.dumps({"ids": [ident], "types": ["t"], "assettypes": ["material"], "labels": [label], "filepaths": [file_path],
                       "asset_data": [json.dumps({"name": name, "refprimpath": prim})], "sources": [list(source)]})


# --------------------------------------------------
def reset():
    FakeSource.built.clear()
    FakeSource.prepared.clear()


usda = os.path.join(work, "ok.usda").replace("\\", "/")
open(usda, "w").write("#usda 1.0\n")
amd_dir = os.path.join(work, "amd").replace("\\", "/")
os.makedirs(amd_dir, exist_ok=True)

# --- a hostile drag payload ---
for label, kwargs in (
    ("expression in the file path", dict(file_path=attack, source=(usda, "%type:Material"))),
    ("expression in the material name", dict(name=attack, source=(usda, "%type:Material"))),
    ("expression in the prim path", dict(prim=attack, source=(usda, "%type:Material"))),
    ("expression in the item id", dict(ident=attack, source=(usda, "%type:Material"))),
    ("expression in the source identifier", dict(source=(attack, ""))),
    ("expression in the AMD download folder argument", dict(source=(k.AMD_SOURCE_ID, attack))),
):
    reset()
    assets, failures = k._parse_catalog_drop(payload(**kwargs), amd_folder=amd_dir, source_factory=FakeSource)
    t.check("payload refused: " + label, not assets and len(failures) == 1 and not FakeSource.built, failures)
    t.check("no command ran: " + label, not os.path.exists(marker))

problem = k._catalog_source_problem
t.check("a catalog file that exists is accepted", problem(usda, "%type:Material", None) == "")
t.check("a missing file is refused", problem(os.path.join(work, "gone.usda"), "", None) != "")
t.check("an unknown suffix is refused", problem(os.path.join(work, "ok.usda.exe"), "", None) != "")
t.check("a LOP-based source is refused", problem("lop:/stage/x", "", None) != "")
t.check("AMD without a connected folder is refused", "connect" in problem(k.AMD_SOURCE_ID, amd_dir, None))
t.check("AMD with another folder is refused", problem(k.AMD_SOURCE_ID, os.path.join(work, "elsewhere"), amd_dir) != "")
t.check("AMD with the connected folder is accepted", problem(k.AMD_SOURCE_ID, amd_dir, amd_dir) == "")
t.check("AMD folder spelled differently (case, slashes) is the same folder", problem(k.AMD_SOURCE_ID, amd_dir.replace("/", "\\").upper(), amd_dir) == "")

# --- remote metadata and the download folder ---
reset()
FakeSource.file_for_item = os.path.join(work, "outside", "evil", "x.mtlx").replace("\\", "/")
assets, failures = k._parse_catalog_drop(payload(file_path=FakeSource.file_for_item, source=(k.AMD_SOURCE_ID, amd_dir)), amd_folder=amd_dir, source_factory=FakeSource)
t.check("a package path outside the download folder is refused before anything is downloaded", not assets and not FakeSource.prepared, failures)
reset()
FakeSource.file_for_item = amd_dir + "/../../outside/x.mtlx"
assets, failures = k._parse_catalog_drop(payload(file_path=FakeSource.file_for_item, source=(k.AMD_SOURCE_ID, amd_dir)), amd_folder=amd_dir, source_factory=FakeSource)
t.check("a path that climbs out with .. is refused", not assets and not FakeSource.prepared, failures)
reset()
FakeSource.file_for_item = '{}/mat/`system("x")`.mtlx'.format(amd_dir)
assets, failures = k._parse_catalog_drop(payload(file_path=amd_dir + "/mat/x.mtlx", source=(k.AMD_SOURCE_ID, amd_dir)), amd_folder=amd_dir, source_factory=FakeSource)
t.check("an expression in the remote file path is refused", not assets and not FakeSource.prepared, failures)
reset()
FakeSource.file_for_item = amd_dir + "/Aluminum/Aluminum.mtlx"
assets, failures = k._parse_catalog_drop(payload(file_path=FakeSource.file_for_item, source=(k.AMD_SOURCE_ID, amd_dir)), amd_folder=amd_dir, source_factory=FakeSource)
t.check("a path inside the download folder goes through", len(assets) == 1 and FakeSource.prepared == ["id1"], failures)

# --- node parameters never receive an expression ---
stage = hou.node("/stage")
linker = stage.createNode("materiallinker", "material_linker")
for label, args in (("file path", (attack, "/MaterialX/Materials/m", "m")), ("prim path", ("C:/a.mtlx", attack, "m")), ("label", ("C:/a.mtlx", "/MaterialX/Materials/m", attack))):
    try:
        k._linker_add_reference(linker, *args)
        refused = False
    except ValueError:
        refused = True
    t.check("linker refuses an expression in the " + label, refused and linker.parm("num_files").evalAsInt() == 0)

folder = k._private_temp_dir()
t.check("temp files live in a per-session directory", os.path.isdir(folder) and os.path.basename(folder).startswith("bsm_karma_") and folder == k._private_temp_dir(), folder)
t.check("its name is not guessable (random suffix)", re.match(r"^bsm_karma_.{6,}$", os.path.basename(folder)) is not None)
wrapper = k._material_catalog_file(os.path.join(ROOT, "tests", "fixtures", "red.mtlx"))
t.check("the catalog wrapper is written inside it", os.path.dirname(wrapper).replace("\\", "/") == folder.replace("\\", "/"), wrapper)

# --- hscript only ever sees a plain USD path ---
calls = []
real_hscript = hou.hscript
hou.hscript = lambda cmd: calls.append(cmd) or ("", "")


# ------------------------------------------------------------
class FakeViewport:
    def setCamera(self, path):
        raise hou.OperationFailed("not supported")

    # ------------------------------------------------------------
    def name(self):
        return "persp1"


try:
    for path in ('/cameras/a" ; python -c "x', "/cameras/a`b`", "/cameras/a;b", "relative/path"):
        calls.clear()
        locked = k.KarmaBuilderUI._lock_viewport_to_camera(None, None, FakeViewport(), path)
        t.check("no hscript command for {!r}".format(path), locked is False and not calls, calls)
    calls.clear()
    locked = k.KarmaBuilderUI._lock_viewport_to_camera(None, None, FakeViewport(), "/cameras/shot_01")
    t.check("a plain USD path may still use the fallback", locked is True and len(calls) == 1, calls)
finally:
    hou.hscript = real_hscript

# --- static guard: nothing dynamic in the tool itself ---
package_dir = os.path.join(ROOT, "bsm_karma")
source = "\n".join(open(os.path.join(package_dir, name), encoding="utf-8").read()
                   for name in sorted(os.listdir(package_dir)) if name.endswith(".py"))
dangerous = re.findall(r"\beval\(|\bexec\(|os\.system|shell\s*=\s*True|\bpickle\b|__import__|\bmarshal\b", source)
t.check("the bsm_karma package has no eval, exec, os.system, shell=True, pickle or __import__", not dangerous, dangerous)
t.check("subprocess is only called with an argument list", not re.search(r"subprocess\.(run|Popen|call|check_output)\(\s*[\"'f]", source))

t.done()

# Download window logic: the commands built for materialxmaterials, input checks, safe unzip, Python detection.
# The window itself (a process run end to end) is covered by the Qt checks, not here.
#
# Revision : 15-10-2026 | Auteur : BSM
import os
import shutil
import sys
import tempfile
import zipfile
from _common import Checker, load_tool

hou, k = load_tool()
import bsm_karma.mxdownload as mx

t = Checker("material download")
work = tempfile.mkdtemp(prefix="bsm_mx_")

ambient = mx.build_arguments(mx.SOURCE_AMBIENTCG, {"name": "WoodFloor038", "resolution": "2", "fmt": "png"}, "/d")
t.check("ambientCG command", ambient == ["-m", "materialxMaterials", "acg", "-m", "WoodFloor038", "-r", "2", "-f", "PNG", "--output", "/d"], ambient)
poly = mx.build_arguments(mx.SOURCE_POLYHAVEN, {"name": "polystyrene", "resolution": "2k"}, "/d")
t.check("Poly Haven command", poly == ["-m", "materialxMaterials", "polyhaven", "-id", "polystyrene", "-dt", "mtlx", "-res", "2k", "-c", "1", "-x", "-fe", "-df", "/d"], poly)
t.check("PhysicallyBased command", mx.build_arguments(mx.SOURCE_PHYSBASED, {"model": "all"}, "/d") == ["-m", "materialxMaterials", "physbased", "-o", "/d"])

bad = (("a space and a semicolon", mx.SOURCE_AMBIENTCG, {"name": "a b;c", "resolution": "2"}),
       ("a backtick", mx.SOURCE_POLYHAVEN, {"name": "a`b`", "resolution": "2k"}),
       ("an empty name", mx.SOURCE_AMBIENTCG, {"name": " ", "resolution": "2"}),
       ("an option as a name", mx.SOURCE_AMBIENTCG, {"name": "-h", "resolution": "2"}),
       ("a name that is too long", mx.SOURCE_POLYHAVEN, {"name": "a" * 80, "resolution": "2k"}),
       ("a resolution that is not offered", mx.SOURCE_AMBIENTCG, {"name": "x", "resolution": "16"}),
       ("an unknown shading model", mx.SOURCE_PHYSBASED, {"model": "x; rm"}),
       ("an unknown source", "evil", {}))
for label, source, fields in bad:
    try:
        mx.build_arguments(source, fields, "/d")
        refused = False
    except ValueError:
        refused = True
    t.check("refused: {}".format(label), refused)


# ------------------------------------------------------------
def make_zip(name, entries):
    path = os.path.join(work, name)
    with zipfile.ZipFile(path, "w") as archive:
        for entry, data in entries:
            archive.writestr(entry, data)
    return path


target = mx.safe_extract(make_zip("ok.zip", [("a.mtlx", "x"), ("tex/b.png", "y")]), work)
t.check("an archive is unpacked in a folder of its name", target.endswith("ok") and os.path.isfile(os.path.join(target, "tex", "b.png")), target)
for label, entries in (("a path that leaves the folder", [("../evil.txt", "x")]),
                       ("a deep path that leaves the folder", [("a/../../evil.txt", "x")]),
                       ("a backtick in a file name", [("`id`.png", "x")])):
    try:
        mx.safe_extract(make_zip("bad_{}.zip".format(len(label)), entries), work)
        refused = False
    except ValueError:
        refused = True
    t.check("archive refused: {}".format(label), refused and not os.path.exists(os.path.join(work, "evil.txt")))
many = make_zip("many.zip", [("f{}.txt".format(i), "") for i in range(10)])
limit = mx.ZIP_MAX_FILES
mx.ZIP_MAX_FILES = 5
try:
    mx.safe_extract(many, work)
    refused = False
except ValueError:
    refused = True
mx.ZIP_MAX_FILES = limit
t.check("archive refused: too many files", refused)

ok, reason = mx.check_python(["definitely_not_a_python_3"])
t.check("a missing program is reported, not raised", not ok and bool(reason), reason)
t.check("split_command accepts the path of a file", mx.split_command(sys.executable) == [sys.executable])
t.check("split_command refuses a program that does not exist", mx.split_command("nonexistent_prog_xyz -3") == [])

shutil.rmtree(work, ignore_errors=True)
t.done()

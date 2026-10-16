# Download of ambientCG and Poly Haven materials: the requests, the checks on what a server sends, the unzip.
# A fake session stands in for the network, with the answer shapes of the two services; no real download is made
# (that has to be tried by hand once, see todo.txt).
#
# Revision : 15-10-2026 | Auteur : BSM
import io
import os
import shutil
import tempfile
import threading
import zipfile
from _common import Checker, load_tool

hou, k = load_tool()
import bsm_karma.mxsources as mx

t = Checker("material download")
work = tempfile.mkdtemp(prefix="bsm_mx_")


# ------------------------------------------------------------
def zip_bytes(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return buffer.getvalue()


class Response:
    def __init__(self, body, status=200):
        self.body, self.status_code, self.headers = body, status, {"Content-Length": str(len(body))}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise OSError("HTTP {}".format(self.status_code))

    def iter_content(self, chunk_size=65536):
        for start in range(0, len(self.body), chunk_size):
            yield self.body[start:start + chunk_size]


class Session:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, params=None, headers=None, timeout=None, stream=False):
        self.calls.append((url, headers))
        body = self.routes.get(url)
        return Response(body if body is not None else b"", 200 if body is not None else 404)


ZIP_URL = "https://ambientCG.com/get?file=Fake01_2K-PNG.zip"
CSV = ("assetId,downloadAttribute,downloadLink\n"
       "Fake01,1K-PNG,https://ambientCG.com/get?file=Fake01_1K-PNG.zip\n"
       "Fake01,2K-PNG,{}\n"
       "Fake01,2K-JPG,https://ambientCG.com/get?file=Fake01_2K-JPG.zip\n"
       "Evil01,2K-PNG,http://evil.example/x.zip\n"
       "Evil02,2K-PNG,file:///etc/passwd\n"
       "Evil03,2K-PNG,https://ambientcg.com.evil.example/x.zip\n"
       "Odd01,2K-PNG,https://ambientCG.com/get?file=../../x.zip\n").format(ZIP_URL).encode()
good_zip = zip_bytes([("Fake01.mtlx", "<materialx/>"), ("Fake01_Color.png", b"png")])
logs = []
session = Session({mx.AMBIENTCG_LIST_URL: CSV, ZIP_URL: good_zip, "https://ambientCG.com/get?file=Fake01_2K-JPG.zip": good_zip, "https://ambientCG.com/get?file=../../x.zip": good_zip})

rows = mx.ambientcg_catalog(session)
t.check("catalog rows are read", len(rows) == 7 and rows[0]["assetId"] == "Fake01", len(rows))
t.check("names are unique and sorted", mx.ambientcg_names(rows) == ["Evil01", "Evil02", "Evil03", "Fake01", "Odd01"], mx.ambientcg_names(rows))
t.check("the requests carry a user agent", all(h and h.get("User-Agent") for _, h in session.calls))

path = mx.download_ambientcg(session, rows, "Fake01", "2", "PNG", work, logs.append)
t.check("the zip is saved under the name of its link", os.path.basename(path) == "Fake01_2K-PNG.zip" and zipfile.is_zipfile(path), path)
unpacked = mx.safe_extract(path, work)
t.check("and unpacked", os.path.isfile(os.path.join(unpacked, "Fake01.mtlx")), unpacked)
jpg = mx.download_ambientcg(session, rows, "Fake01", "2", "JPEG", os.path.join(work, "jpg"), logs.append)
t.check("JPEG is understood as the JPG variant", os.path.basename(jpg) == "Fake01_2K-JPG.zip", jpg)

for label, call in (
        ("an unknown material", lambda: mx.download_ambientcg(session, rows, "Nothing01", "2", "PNG", work, logs.append)),
        ("a resolution the material lacks", lambda: mx.download_ambientcg(session, rows, "Fake01", "8", "PNG", work, logs.append)),
        ("a link that is plain http", lambda: mx.download_ambientcg(session, rows, "Evil01", "2", "PNG", work, logs.append)),
        ("a file link", lambda: mx.download_ambientcg(session, rows, "Evil02", "2", "PNG", work, logs.append)),
        ("a host that only starts like ambientCG", lambda: mx.download_ambientcg(session, rows, "Evil03", "2", "PNG", work, logs.append)),
        ("a bad name", lambda: mx.download_ambientcg(session, rows, "a b;c", "2", "PNG", work, logs.append)),
        ("a name that is an option", lambda: mx.download_ambientcg(session, rows, "-h", "2", "PNG", work, logs.append)),
        ("a resolution that is not offered", lambda: mx.download_ambientcg(session, rows, "Fake01", "16", "PNG", work, logs.append))):
    try:
        call()
        refused = False
    except (mx.DownloadError, ValueError):
        refused = True
    t.check("ambientCG refused: {}".format(label), refused)

# a link that tries to name the file outside the folder falls back to a safe name
odd = mx.download_ambientcg(session, rows, "Odd01", "2", "PNG", work, logs.append)
t.check("a file name from the server never leaves the folder", os.path.dirname(os.path.realpath(odd)) == os.path.realpath(work), odd)

not_zip = Session({mx.AMBIENTCG_LIST_URL: CSV, ZIP_URL: b"this is not a zip"})
try:
    mx.download_ambientcg(not_zip, rows, "Fake01", "2", "PNG", os.path.join(work, "nz"), logs.append)
    refused = False
except mx.DownloadError:
    refused = True
t.check("what is not a zip is refused", refused)

limit = mx.MAX_FILE_BYTES
mx.MAX_FILE_BYTES = 10
try:
    mx.download_ambientcg(session, rows, "Fake01", "2", "PNG", os.path.join(work, "big"), logs.append)
    refused = False
except mx.DownloadError:
    refused = True
mx.MAX_FILE_BYTES = limit
t.check("a file over the size cap is refused", refused)

cancel = threading.Event()
cancel.set()
try:
    mx.download_ambientcg(session, rows, "Fake01", "2", "PNG", os.path.join(work, "cc"), logs.append, cancel)
    stopped = False
except mx.DownloadCancelled:
    stopped = True
t.check("a stop request ends the download", stopped)

# ------------------------------------------------------------
base = "https://dl.polyhaven.org/file/ph-assets/Textures"
files = {"mtlx": {"2k": {"mtlx": {"url": base + "/mtlx/2k/rock1/rock1.mtlx", "include": {
    "textures/rock1_diff_2k.exr": {"url": base + "/exr/2k/rock1/rock1_diff_2k.exr"},
    "textures/rock1_rough_2k.jpg": {"url": base + "/jpg/2k/rock1/rock1_rough_2k.jpg"}}}}}}
import json
mtlx = '<materialx><image name="d"><input name="file" value="textures/rock1_diff_2k.exr"/></image></materialx>'
routes = {mx.POLYHAVEN_ASSETS_URL: json.dumps({"rock1": {"name": "Rock"}, "a b": {}, "wood": {}}).encode(),
          mx.POLYHAVEN_FILES_URL + "/rock1": json.dumps(files).encode(),
          base + "/mtlx/2k/rock1/rock1.mtlx": mtlx.encode(),
          base + "/png/2k/rock1/rock1_diff_2k.png": b"PNGDATA",
          base + "/jpg/2k/rock1/rock1_rough_2k.jpg": b"JPGDATA"}
poly = Session(routes)
assets = mx.polyhaven_catalog(poly)
t.check("Poly Haven names are listed, a bad one is left out", mx.polyhaven_names(assets) == ["rock1", "wood"], mx.polyhaven_names(assets))
out = mx.download_polyhaven(poly, "rock1", "2k", work, logs.append)
folder = os.path.dirname(out)
t.check("the .mtlx and the textures are written in <id>_materialx", out.endswith("rock1_materialx/rock1.mtlx") or out.endswith("rock1_materialx\\rock1.mtlx"), out)
t.check("the EXR is taken as PNG and the .mtlx follows", os.path.isfile(os.path.join(folder, "textures", "rock1_diff_2k.png")) and "rock1_diff_2k.png" in open(out).read() and ".exr" not in open(out).read())
t.check("other textures are kept as they are", open(os.path.join(folder, "textures", "rock1_rough_2k.jpg"), "rb").read() == b"JPGDATA")

routes2 = dict(routes)
del routes2[base + "/png/2k/rock1/rock1_diff_2k.png"]
routes2[base + "/exr/2k/rock1/rock1_diff_2k.exr"] = b"EXRDATA"
out2 = mx.download_polyhaven(Session(routes2), "rock1", "2k", os.path.join(work, "exr"), logs.append)
t.check("without a PNG the EXR is used and the .mtlx is untouched", ".exr" in open(out2).read() and os.path.isfile(os.path.join(os.path.dirname(out2), "textures", "rock1_diff_2k.exr")))

for label, body, name, res in (
        ("an asset with no MaterialX", {"blend": {}}, "rock1", "2k"),
        ("a resolution it lacks", files, "rock1", "8k"),
        ("a bad name", files, "a b", "2k")):
    routes3 = dict(routes)
    routes3[mx.POLYHAVEN_FILES_URL + "/rock1"] = json.dumps(body).encode()
    try:
        mx.download_polyhaven(Session(routes3), name, res, os.path.join(work, "x"), logs.append)
        refused = False
    except (mx.DownloadError, ValueError):
        refused = True
    t.check("Poly Haven refused: {}".format(label), refused)

for label, include in (("a path that leaves the folder", {"../evil.png": {"url": base + "/jpg/2k/rock1/rock1_rough_2k.jpg"}}),
                       ("an absolute path", {"/etc/evil.png": {"url": base + "/jpg/2k/rock1/rock1_rough_2k.jpg"}}),
                       ("a drive path", {"C:/evil.png": {"url": base + "/jpg/2k/rock1/rock1_rough_2k.jpg"}}),
                       ("a backtick in a path", {"a/`id`.png": {"url": base + "/jpg/2k/rock1/rock1_rough_2k.jpg"}}),
                       ("a texture on another host", {"textures/a.png": {"url": "https://evil.example/a.png"}}),
                       ("a texture at a file address", {"textures/a.png": {"url": "file:///etc/passwd"}})):
    hostile = {"mtlx": {"2k": {"mtlx": {"url": base + "/mtlx/2k/rock1/rock1.mtlx", "include": include}}}}
    routes4 = dict(routes)
    routes4[mx.POLYHAVEN_FILES_URL + "/rock1"] = json.dumps(hostile).encode()
    target = os.path.join(work, "h_" + str(abs(hash(label))))
    try:
        mx.download_polyhaven(Session(routes4), "rock1", "2k", target, logs.append)
        refused = False
    except mx.DownloadError:
        refused = True
    leaked = os.path.exists(os.path.join(work, "evil.png")) or os.path.exists("/etc/evil.png")
    t.check("Poly Haven refused: {}".format(label), refused and not leaked)

# unzip safety
def make_zip(name, entries):
    p = os.path.join(work, name)
    with open(p, "wb") as handle:
        handle.write(zip_bytes(entries))
    return p

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

# --- downloaded materials dragged onto prims: the payload, the checks, the material of a real file ---
import bsm_karma.localmaterials as local
download = os.path.join(work, "dl", "Red")
os.makedirs(download)
fixture = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "red.mtlx")
shutil.copy(fixture, os.path.join(download, "Red.mtlx"))
mtlx = os.path.join(download, "Red.mtlx").replace("\\", "/")
roots = [os.path.join(work, "dl")]
assets, failures = local.local_assets(local.local_payload([mtlx]), roots)
t.check("a downloaded file gives its material (read as text)", len(assets) == 1 and assets[0]["label"] == "M_red"
        and assets[0]["prim_path"] == "/MaterialX/Materials/M_red" and not failures, (assets, failures))
real, why = local.local_assets(local.local_payload([mtlx]), roots, lister=k._list_materials_in_file)
t.check("Houdini's USD reader gives the same prim path as the text reader", len(real) == 1 and real[0]["prim_path"] == assets[0]["prim_path"], (real, why, assets))
outside_file = os.path.join(work, "Outside.mtlx")
shutil.copy(fixture, outside_file)
bad, why = local.local_assets(local.local_payload([outside_file]), roots)
t.check("a file outside the download folder is refused", bad == [] and "outside" in why[0], why)
bad, why = local.local_assets(local.local_payload([mtlx.replace("Red.mtlx", "`x`.mtlx")]), roots)
t.check("a path with a backtick is refused", bad == [] and "expression" in why[0], why)
bad, why = local.local_assets(local.local_payload(["Red.mtlx"]), roots)
t.check("a relative path is refused", bad == [], why)
doctype = os.path.join(download, "Bomb.mtlx")
with open(doctype, "w") as handle:
    handle.write('<!DOCTYPE x [<!ENTITY a "aaaa">]><materialx><surfacematerial name="B"/></materialx>')
t.check("a .mtlx with a DOCTYPE is not read", local.mtlx_materials(doctype) == [])
with open(os.path.join(download, "Red_Color.png"), "wb") as handle:
    handle.write(b"\x89PNG")
with open(os.path.join(download, "Red_NormalGL.png"), "wb") as handle:
    handle.write(b"\x89PNG")
t.check("the thumbnail picture is the color map", local.preview_picture(mtlx).endswith("Red_Color.png"), local.preview_picture(mtlx))

shutil.rmtree(work, ignore_errors=True)
t.done()

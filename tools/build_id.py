# BSM Karma Builder
# Benoît Saint-Moulin
# www.bsm3d.com
# Function : Prints the build id of the bsm_karma folder of this repository
# Houdini : 21 and 22 (plain Python, no Houdini needed)
# Version : 1.0.0
#
# usage: python tools/build_id.py [path/to/bsm_karma]

import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
folder = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(ROOT, "bsm_karma")
spec = importlib.util.spec_from_file_location("buildinfo_standalone", os.path.join(folder, "buildinfo.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
version = ""
with open(os.path.join(folder, "config.py"), encoding="utf-8") as handle:
    for line in handle:
        if line.startswith("SCRIPT_VERSION"):
            version = line.split('"')[1]
            break
print("build {} | version {} | {} modules | {}".format(module.folder_build_id(folder), version, len(module.package_sources(folder)), folder))

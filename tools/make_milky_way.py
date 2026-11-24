# BSM Karma Builder
# © Benoit Saint-Moulin - 2026
# Version du fichier : 1.6.0
# Fonction du fichier : Reduces NASA's Milky Way map to the small linear EXR file that the night sky reads.

# Source: NASA Deep Star Maps 2020 (https://svs.gsfc.nasa.gov/4851/), milkyway_2020_4k.exr, 4096 x 2048, linear, half float.
# Reduced to datas/Sky/milky_way_1k.exr (1024 x 512), gain applied. Bright stars are drawn as points, so they are left out.
# hython tools\make_milky_way.py path\to\milkyway_2020_4k.exr
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np
import OpenImageIO as oiio
from bsm_karma.clouds2d import write_exr_grey

SIZE = (1024, 512)
GAIN = 14.0     # what the picture was tuned with against the emission of the material
if len(sys.argv) < 2:
    raise SystemExit("usage: hython tools\\make_milky_way.py path\\to\\milkyway_2020_4k.exr")
reader = oiio.ImageInput.open(sys.argv[1])
if reader is None:
    raise SystemExit("cannot read {}".format(sys.argv[1]))
spec = reader.spec()
full = np.array(reader.read_image("float")).reshape(spec.height, spec.width, spec.nchannels)[:, :, :3]
reader.close()
width, height = SIZE
fy, fx = spec.height // height, spec.width // width
small = full[:height * fy, :width * fx].reshape(height, fy, width, fx, 3).mean(axis=(1, 3))
target = os.path.join(ROOT, "datas", "Sky", "milky_way_1k.exr")
write_exr_grey(target, small * GAIN)
print("written", target, os.path.getsize(target) // 1024, "KB")

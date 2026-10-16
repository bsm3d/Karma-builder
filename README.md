# BSM Karma Builder

BSM Karma Builder is a procedural Python tool for SideFX Houdini (Solaris/LOPs) that builds and updates Karma render setups from one window: camera, lighting, sky, fog, clouds, materials, render variables and render settings. It provides a PySide interface to generate the node networks without manual wiring.

![The Scene tab](docs/screenshots/scene.png)

## Why ?

This tool was created to reduce the repetitive reconstruction of node networks for Karma renders, which is frequent during testing and lookdev phases. The beauty of this tool lies in its ability to build and incrementally update the LOP node network without destroying your existing setups: it only ever touches the nodes it created itself.

It also serves as a gateway to simplify the learning curve for Karma and the LOP context, especially for students and Houdini beginners. Unlike classic 3D software where rendering is often just a settings window and a "Render" button, Karma's USD-based approach is fundamentally different and requires foundational knowledge before you can easily render "just for fun".

Please note that this is a first version. While it is not perfect, it represents a solid foundation for a comprehensive Version 2 that is already under active development.

## Features

* **Lighting scenarios**: 1-click generators for Environment, Studio, 3-Point and Interior setups.
* **Karma Physical Sky and HDRI**: sky controls with time-of-day presets (Clear Sky, Golden Hour, Overcast, Night...), a basic or volumetric atmosphere, and HDRI dome setups with exposure, rotation, temperature, tint and a thumbnail preview.
* **Fog and clouds**: atmospheric fog (`karmafogbox`), procedural 3D volume clouds, or a fast **2D cloud layer** (a generated picture on a second dome light) for distant backgrounds.
* **Materials**: browse a MaterialX catalog as thumbnails, a list or categories; assign a material to prims by drag and drop (on the prim list or on the Solaris viewport) or with **Assign Material to Selection**; right click a material to edit it in the Material Linker or open it as a MaterialX node network.
* **Material downloads**: a built-in window downloads free MaterialX materials from ambientCG and Poly Haven (the AMD MaterialX Library is a catalog source). Nothing to install.
* **Render settings and quality presets**: Draft to Ultra resolutions and sample counts, Karma CPU and XPU.
* **AOV management**: Standard Render Vars with predefined passes and a multilayer or split output.
* **Live Update**: optionally see value changes in the network without pressing Build. Changes that add or remove nodes wait for the button, so a running Karma viewport is not restarted behind your back.
* **Safe rebuilds**: nodes are marked, updated in place and never deleted or rewired unless the tool created them. Cooking is paused during a build.
* **Debug log**: everything the tool does goes to a text file you can send when something fails.

## Requirements

* SideFX Houdini 21 or 22. Houdini 22 parameter names are the reference and older names are tried as fallbacks; the log lists any parameter that a version does not have. Earlier versions are not supported.
* Solaris (LOPs) context and Karma rendering engine.

## Installation

The full steps (automatic install with the shelf button, the HDA, by hand), the troubleshooting and the material sources are in [`INSTALL.md`](INSTALL.md).

### Option A: the HDA

Install `bsm_karma_builder.hda` (Assets > Install Asset Library), drop a **BSM Karma Builder** node in `/stage` and press **Open Karma Builder**. The tool and its presets travel inside the asset. To rebuild the asset from the sources: `hython build_hda.py`.

### Option B: the script and a shelf button

The quickest way: in the Python Shell of Houdini, point at the folder of the repository and let the tool install itself (it copies the package and creates the shelf button):

```python
import sys
sys.path.insert(0, r"D:/Documents/Coding/Houdini Scripts/Karma-builder")
import bsm_karma
bsm_karma.install()
```

By hand:

1. Copy the whole `bsm_karma` folder (the Python package, presets included) to the `scripts/python` folder of your Houdini user preferences, typically:
   * Windows: `C:\Users\%USERNAME%\Documents\houdini<version>\scripts\python\`
   * Linux: `~/houdini<version>/scripts/python/`
   * Mac: `~/Library/Preferences/houdini/<version>/scripts/python/`
2. Create a shelf tool in Houdini with this Python code (or copy `tools/bsm_karma.shelf` to the `toolbar` folder of your preferences):

```python
import importlib
import bsm_karma
importlib.reload(bsm_karma)
bsm_karma.main()
```

*(Replace `<version>` with your Houdini version, for example `21.0` or `22.0`. The reload also re-reads every module of the package.)*

## Usage

1. Click the shelf tool (or **Open Karma Builder** on the HDA node) to open the window.
2. In the `Scene` tab, define the scene mode, camera, engine, resolution and quality.
3. Use the `Lighting` and `Atmosphere` tabs for the sky or HDRI, the fog and the clouds.
4. Use the `Materials` tab to pick a material (or download one) and assign it to the prims of a Geometry Source.
5. Adjust the `Render` and `Passes` (AOV) tabs as needed.
6. Click **Build Environment Only** to generate the LOP network, or use the render buttons of the `Export` tab to render to MPlay or to disk.

![The Materials tab](docs/screenshots/materials.png)

## Documentation

The full documentation (interface reference with screenshots, what is built, presets, building the HDA, tests, safety checks, troubleshooting) is in [`docs/index.html`](docs/index.html). GitHub shows HTML files as source: download the repository and open the file in a browser, or serve the `docs` folder with GitHub Pages.

## Credits

The material downloads follow the requests of the open source [materialxmaterials](https://pypi.org/project/materialxmaterials/) tool (Bernard Kwok, Apache 2.0), without using its code. The materials come from [AMD GPUOpen](https://matlib.gpuopen.com), [ambientCG](https://ambientcg.com) and [Poly Haven](https://polyhaven.com/textures), under their own terms.

## Author

BSM

## License

Licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE): free for personal, educational and any other noncommercial use. Studios and commercial use need a commercial license, see [Informations/COMMERCIAL_LICENSE.txt](Informations/COMMERCIAL_LICENSE.txt). Versions published before 30 September 2026 were released under GPL-3.0.

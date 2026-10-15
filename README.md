# BSM Karma Builder

BSM Karma Builder is a procedural Python tool for SideFX Houdini (Solaris/LOPs) that automates the creation of Karma render setups and lighting environments. It provides a clean PySide interface to generate node networks for various lighting scenarios, atmospheric effects, and render variables without manual wiring.

## Why ?

This tool was created to reduce the repetitive reconstruction of node networks for Karma renders, which is frequent during testing and lookdev phases. The beauty of this tool lies in its ability to build and incrementally update the LOP node network without destroying your existing setups.

It also serves as a gateway to simplify the learning curve for Karma and the LOP context, especially for students and Houdini beginners. Unlike classic 3D software where rendering is often just a settings window and a "Render" button, Karma's USD-based approach is fundamentally different and requires foundational knowledge before you can easily render "just for fun". 

Please note that this is a first version. While it is not perfect, it represents a solid foundation for a comprehensive Version 2 that is already under active development.

## Features

* **Lighting Scenarios**: 1-click generators for Environment, Studio, 3-Point, and Interior lighting setups.
* **Karma Physical Sky & HDRI**: Integrated physical sky controls with time-of-day presets (Clear Sky, Golden Hour, Overcast, etc.) and HDRI dome setups with dynamic exposure, rotation, and tint adjustments. Includes integrated HDRI thumbnail previews.
* **Volumetrics**: Automated generation of atmospheric fog (using `karmafogbox`) and procedural volumetric clouds generated via SOP networks (`skybox` and `cloudbillowynoise`).
* **Render Settings & Quality Presets**: Pre-configured settings spanning from Draft to Ultra resolutions and sample counts. Supports both Karma CPU and XPU natively.
* **AOV Management**: Standard Render Vars (AOVs) generator with predefined passes (Depth, Normal, Position, Albedo, Emission, etc.) and layout options.

## Requirements

* SideFX Houdini 21 or 22. Houdini 22 parameter names are the reference and older names are tried as fallbacks; the log lists any parameter that a version does not have. Earlier versions are not supported.
* Solaris (LOPs) context and Karma rendering engine.

## Installation

### Option A: the HDA

Install `bsm_karma_builder.hda` (Assets > Install Asset Library), drop a **BSM Karma Builder** node in `/stage` and press **Open Karma Builder**. The tool and its presets travel inside the asset. To rebuild the asset from the sources: `hython build_hda.py`.

### Option B: the script

A step by step version, with the shelf button code and the AMD library address, is in `install.txt`.

1. Copy the whole `bsm_karma` folder (the Python package, presets included) to your Houdini user preferences directory, typically:
   * Windows: `C:\Users\%USERNAME%\Documents\houdini<version>\scripts\python\`
   * Linux: `~/houdini<version>/scripts/python/`
   * Mac: `~/Library/Preferences/houdini/<version>/scripts/python/`
2. Create a new Shelf Tool in Houdini and add the following Python code to launch the interface:

```python
import bsm_karma
import importlib
importlib.reload(bsm_karma)
bsm_karma.main()
```

*(Replace `<version>` with your Houdini version, for example `21.0` or `22.0`. The reload also re-reads every module of the package.)*

## Usage

1. Click the shelf tool to open the BSM Karma Builder UI.
2. In the `Scene` tab, define the scene mode, camera, engine, resolution and quality.
3. Use the `Lighting` and `Atmosphere` tabs for the sky or HDRI, the fog and the clouds.
4. Use the `Materials` tab to drag MaterialX materials onto the prims of a Geometry Source.
5. Adjust the `Render` and `Passes` (AOV) tabs as needed.
6. Click **Build Environment Only** to generate the LOP network, or use the render buttons to output directly to MPlay or Disk.

## Documentation

The full documentation (interface reference, what is built, presets, building the HDA, troubleshooting) is in [`docs/index.html`](docs/index.html). GitHub shows HTML files as source: download the repository and open the file in a browser, or serve the `docs` folder with GitHub Pages.

## Author

BSM

## License

Licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE): free for personal, educational and any other noncommercial use. Studios and commercial use need a commercial license, see [Informations/COMMERCIAL_LICENSE.txt](Informations/COMMERCIAL_LICENSE.txt). Versions published before 30 September 2026 were released under GPL-3.0.

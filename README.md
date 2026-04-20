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

* SideFX Houdini 20.5 or above.
* Solaris (LOPs) context and Karma rendering engine.

## Installation

1. Copy the script to your Houdini user preferences directory, typically:
   * Windows: `C:\Users\%USERNAME%\Documents\houdini20.5\scripts\python\`
   * Linux: `~/houdini20.5/scripts/python/`
   * Mac: `~/Library/Preferences/houdini/20.5/scripts/python/`
2. Create a new Shelf Tool in Houdini and add the following Python code to launch the interface:

```python
import bsm_karma_V1
import importlib
importlib.reload(bsm_karma_V1)
```

*(Note: Adjust the import name depending on what you renamed the script file to).*

## Usage

1. Click the shelf tool to open the BSM Karma Builder UI.
2. Define your basic render parameters (Engine, Focal Length, Resolution, Quality).
3. Switch to the `Lighting & Sky` tab to define the environment type and atmospheric conditions.
4. Adjust `Quality` and `AOV` passes as needed.
5. Click **Build Environment Only** to generate the LOP network, or use the render buttons to output directly to MPlay or Disk.

## Author

Benoît (BSM) Saint-Moulin - bsm3d.com

## License

This project is licensed under the GNU General Public License v3.0 (GPL-3.0).

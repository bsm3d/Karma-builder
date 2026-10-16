# Installing BSM Karma Builder

BSM Karma Builder runs inside SideFX Houdini 21 or 22 (Solaris and Karma). It needs nothing but Houdini: no pip, no extra Python, no download. There are three ways to install it. Pick one.

| Way | Good for | What you get |
|---|---|---|
| [A. Automatic](#a-automatic-recommended) | Most people, and the development setup | The package copied to your Houdini preferences and a **Karma Builder** shelf button |
| [B. The HDA](#b-the-hda) | A single file to hand over | A **BSM Karma Builder** node that opens the window |
| [C. By hand](#c-by-hand) | Control over every step | The same as A, done step by step |

Throughout this page, `$HOUDINI_USER_PREF_DIR` is the preferences folder of your Houdini version. Houdini tells you where it is: open **Windows > Python Shell** and run

```python
print(hou.text.expandString("$HOUDINI_USER_PREF_DIR"))
```

Typical answers: `C:/Users/<you>/Documents/houdini22.0` (Windows), `~/houdini22.0` (Linux), `~/Library/Preferences/houdini/22.0` (macOS). On your machine it may be elsewhere, for example `D:/Documents/houdini22.0`. Houdini 21 uses `houdini21.0`: install once per version you use.

## A. Automatic (recommended)

1. Get the repository: clone it, or download it as a zip and unpack it. You need the folder that holds `bsm_karma/`, `tools/` and `build_hda.py`. Example: `D:\Documents\Coding\Houdini Scripts\Karma-builder`.
2. Start Houdini and open **Windows > Python Shell**.
3. Paste these four lines, with the path of your folder (use `/` or a raw string as shown):

   ```python
   import sys
   sys.path.insert(0, r"D:/Documents/Coding/Houdini Scripts/Karma-builder")
   import bsm_karma
   bsm_karma.install()
   ```

4. A window lists what was done, and the same lines are printed in the Python Shell:
   * the package `bsm_karma` is copied to `$HOUDINI_USER_PREF_DIR/scripts/python/` (a copy that was already there is kept once as `bsm_karma.bak`);
   * the file `$HOUDINI_USER_PREF_DIR/toolbar/bsm_karma.shelf` is written, with the icon copied to `$HOUDINI_USER_PREF_DIR/bsm_karma/`;
   * the shelves are reloaded and the shelf **BSM Karma** is added to your shelf bar. If the bar cannot be reached, the report says so: use the **+** at the right of the shelf tabs and pick **BSM Karma**.
5. Click **Karma Builder** on the shelf. The window opens.

To update, get the new version of the repository and run the four lines again: the copy and the shelf are replaced. The button reloads the code each time it is pressed, so Houdini does not need a restart.

## B. The HDA

An HDA is one file that carries the whole tool.

1. Build it from the repository with Houdini's command-line Python (`hython`). On Windows, in PowerShell, from the folder of the repository:

   ```powershell
   & "C:\Program Files\Side Effects Software\Houdini 22.0.466\bin\hython.exe" .\build_hda.py
   ```

   Replace the Houdini folder with yours. It prints `built ... bsm_karma_builder.hda (tool version ..., ... KB)` and writes `bsm_karma_builder.hda` next to the script. Linux and macOS: run `hython build_hda.py` from a terminal where `houdini_setup` has been sourced. The HDA holds a copy of the code, so build it again after every update. It is built with the Houdini that runs `hython`: to use it in both 21 and 22, build it with 21.
2. Make Houdini load it. Either copy the file to `$HOUDINI_USER_PREF_DIR/otls/` (create the folder if needed): it is then loaded at every start. Or use **Assets > Install Asset Library...** and pick the file. Do not install two copies of the asset.
3. In a `/stage` network, add the node. Press **Tab** and type `karma builder`, or run in the Python Shell:

   ```python
   n = hou.node("/stage").createNode("bsm::karma_builder::1.0")
   ```

4. Press **Open Karma Builder** on the node.
5. Optional: press **Create Shelf Button** on the node. It creates the shelf **BSM Karma** with a button that opens the tool through the asset, so the node is not needed again.

If the node is missing from the Tab menu, restart Houdini (the menu is built at start) and check that the file is in `otls`. In the Python Shell, `hou.nodeType(hou.lopNodeTypeCategory(), "bsm::karma_builder::1.0")` returns `None` when the asset is not loaded.

## C. By hand

1. Copy the whole `bsm_karma` folder, with `presets.json` in it, to `$HOUDINI_USER_PREF_DIR/scripts/python/`, so that this file exists:

   ```
   $HOUDINI_USER_PREF_DIR/scripts/python/bsm_karma/__init__.py
   ```

   Houdini puts `scripts/python` on the Python path by itself. Not `scripts/python/bsm_karma/bsm_karma/`: one level only.
2. Check, in the Python Shell:

   ```python
   import bsm_karma
   print(bsm_karma.SCRIPT_VERSION, bsm_karma.__file__)
   ```

3. Make the button: right click on the shelf tabs, **New Shelf...**, then right click on the empty shelf, **New Tool...**. Name `bsm_karma_builder`, label `Karma Builder`. In the **Script** tab, keep Python and paste:

   ```python
   import importlib
   import bsm_karma
   importlib.reload(bsm_karma)
   bsm_karma.main()
   ```

   Optional: in the **Options** tab, set the icon to `icone_Bsm_Karma.png` of the repository. Once the tool is stable, `import importlib` and the reload line can go.
4. Or skip step 3 and copy `tools/bsm_karma.shelf` of the repository to `$HOUDINI_USER_PREF_DIR/toolbar/`, then restart Houdini.

Working straight from the repository without copying: create `$HOUDINI_USER_PREF_DIR/packages/bsm_karma.json` with the content below (not tried here), then restart Houdini. Do not also keep a copy in `scripts/python`: Houdini would load one of them and you would not know which.

```json
{
    "env": [
        { "PYTHONPATH": "D:/Documents/Coding/Houdini Scripts/Karma-builder" }
    ]
}
```

## First start

1. Click the button (or **Open Karma Builder** on the node). The window **BSM Karma Builder** opens.
2. Press **Build Environment Only**. The nodes appear in `/stage`.
3. Everything the tool does is written in `bsm_karma_debug.log`; the Log tab shows the path. Send that file when something goes wrong.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `ModuleNotFoundError: No module named 'bsm_karma'` | The folder is not in `scripts/python` of the preferences of the Houdini you are running (21 and 22 have separate folders), or it is one level too deep. Check with `print(hou.text.expandString("$HOUDINI_USER_PREF_DIR"))`. |
| The window does not open and the Python Shell shows an error | Copy the error. A missing `presets.json` is a common cause: copy the whole folder, not only the `.py` files. |
| The shelf is not in the shelf bar | **+** at the right of the shelf tabs, then **BSM Karma**. Or restart Houdini. |
| The old version still runs | Two copies exist (for example `scripts/python` and a package file), or an old HDA is installed. Keep one. Rebuild the HDA after an update. |
| `bsm_karma.install()` says the preferences folder is unknown | Houdini could not expand `$HOUDINI_USER_PREF_DIR`. Use the by-hand steps. |
| The HDA node is not in the Tab menu | Restart Houdini, check that the file is in `otls`, and create the node from the Python Shell (B, step 3). |
| Houdini 21 and 22 both used | Install once for each: they do not share a preferences folder. |

More in the [documentation](docs/index.html#troubleshooting).

## Uninstall

Delete, in `$HOUDINI_USER_PREF_DIR`: `scripts/python/bsm_karma` (and `bsm_karma.bak`), `toolbar/bsm_karma.shelf`, `otls/bsm_karma_builder.hda` if you installed the asset, and the folder `bsm_karma` (debug log, 2D cloud pictures, downloaded materials, icon). Restart Houdini.

## Material sources

The Materials tab reads catalogs; the **Download...** button there fetches free MaterialX materials without any extra install. Check the licence of what you use.

| Source | Address | Where in the tool |
|---|---|---|
| AMD MaterialX Library (about 290 materials) | site `https://matlib.gpuopen.com`, API `https://api.matlib.gpuopen.com/api` | Materials tab, Source **AMD MaterialX Library**, then **Connect** |
| ambientCG | `https://ambientcg.com` | **Download...** window |
| Poly Haven | `https://polyhaven.com/textures` | **Download...** window |
| MaterialX project (example materials) | `https://github.com/AcademySoftwareFoundation/MaterialX` | **USD / MaterialX File...** source, or **Assign File...** |

The AMD source asks Houdini for a download folder, not an address (default `$HOUDINI_USER_PREF_DIR/bsm_karma/materials`). The tool checks that the server answers before connecting, so an offline machine does not freeze Houdini.

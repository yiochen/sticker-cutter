# macOS driver installation

Read this reference when installing or repairing `fablabnbg/inkscape-silhouette` on macOS. Keep the sticker-preparation script and the hardware-driver Python separate: the bundled skill runs through `uv`, while Inkscape must use an interpreter that can import its own `inkex` plus the driver's USB/BLE dependencies.

## Dependencies

Install:

- current Inkscape;
- Homebrew `libusb` for USB transport;
- `git` and `uv` for checkout and isolated Python environments;
- the current [fablabnbg/inkscape-silhouette](https://github.com/fablabnbg/inkscape-silhouette) checkout;
- Python packages required by upstream: `numpy`, `pyusb`, `libusb1`, `lxml`, `xmltodict`, `cssselect`, `tinycss2`, and `matplotlib`;
- `bleak` for Bluetooth Low Energy;
- `wxPython` only when using Silhouette Multi Action's GUI.

USB does not need `bleak`. The `sendto_silhouette.py` CLI does not need `wxPython`. Do not install the PyPI `inkex` package by default on macOS; it may try to build Cairo/GObject bindings that Inkscape already bundles.

## Preferred install

Follow current upstream instructions first:

```bash
brew install libusb uv
git clone https://github.com/fablabnbg/inkscape-silhouette.git ~/.local/share/inkscape-silhouette
cd ~/.local/share/inkscape-silhouette
./install_osx.sh
```

The installer creates `~/.local/share/venvs/inkscape`, installs dependencies, copies the extension into Inkscape's user extension directory, and prints the interpreter path to add to Inkscape's `preferences.xml`. It replaces an existing venv at that exact location, so preserve a customized environment before running it.

Add the printed path as the `python-interpreter` attribute on the existing `<group id="extensions" ...>` element in:

```text
~/Library/Application Support/org.inkscape.Inkscape/config/inkscape/preferences.xml
```

Restart Inkscape and confirm **Extensions → Export → Send to Silhouette** exists.

## Embedded-Python failure on newer macOS

Smoke-test the embedded interpreter before blaming missing packages:

```bash
/Applications/Inkscape.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 --version
```

One verified macOS 26/Inkscape 1.4.4 setup killed direct execution with exit 137 even though Inkscape was correctly signed and notarized. Code-sign metadata showed responsible-launch constraints on the embedded helper. Describe this as an embedded-interpreter launch constraint, not as “unnotarized Python.” Do not remove quarantine, alter the signed app bundle, or disable macOS security to work around it.

If the smoke test is killed, use an external Python with the same major/minor version as Inkscape's bundled Python. The following example is for an Inkscape bundle using Python 3.10; inspect the bundle and change every `3.10` path together when its version changes:

```bash
brew install python@3.10 libusb uv
uv venv --python /opt/homebrew/opt/python@3.10/bin/python3.10 ~/.local/share/venvs/inkscape
uv pip install --python ~/.local/share/venvs/inkscape/bin/python \
  -r ~/.local/share/inkscape-silhouette/requirements.txt \
  libusb1 bleak wxPython
```

Make Inkscape's bundled extension modules visible to that matching interpreter by creating:

```text
~/.local/share/venvs/inkscape/lib/python3.10/site-packages/inkscape_bundle_paths.pth
```

with these two lines:

```text
/Applications/Inkscape.app/Contents/Resources/share/inkscape/extensions
/Applications/Inkscape.app/Contents/Resources/lib/python3.10/site-packages
```

Copy the current checkout's `sendto_silhouette.inx`, `sendto_silhouette.py`, `silhouette_multi.inx`, `silhouette_multi.py`, `render_silhouette_regmarks.inx`, `render_silhouette_regmarks.py`, and `silhouette/` directory into:

```text
~/Library/Application Support/org.inkscape.Inkscape/config/inkscape/extensions/
```

Set the existing Inkscape extensions preference to:

```xml
<group id="extensions" python-interpreter="/Users/USERNAME/.local/share/venvs/inkscape/bin/python" />
```

Merge the attribute into the existing element; do not replace the whole preferences file.

## Verify the interpreter before connecting

Run these checks with the exact interpreter configured in Inkscape:

```bash
~/.local/share/venvs/inkscape/bin/python -c \
  'import inkex, usb.core, lxml, matplotlib; print("USB imports OK")'

~/.local/share/venvs/inkscape/bin/python -c \
  'import bleak; print("BLE import OK")'

~/.local/share/venvs/inkscape/bin/python \
  ~/.local/share/inkscape-silhouette/sendto_silhouette.py --help
```

An import/help pass proves only the environment. Run the skill's hardware-free `silhouette-dry-run` next, then perform an explicitly authorized connection query before moving a blade.

## Common failures

- `Killed: 9` or exit 137 while creating the venv: use the matching external-Python fallback above.
- `No package 'cairo' found` while installing `inkex`: stop installing PyPI `inkex`; use the version bundled with Inkscape through the `.pth` bridge.
- `NoBackendError` from `usb.core`: install Homebrew `libusb`, then rerun the import in the configured interpreter.
- `No module named bleak`: install `bleak` into the configured interpreter, not a different system Python.
- Extension appears in the menu but fails immediately: inspect `python-interpreter` and run the three smoke tests above with that exact path.

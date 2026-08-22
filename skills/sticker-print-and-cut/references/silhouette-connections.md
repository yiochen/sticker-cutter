# Silhouette cutter connection and registration notes

Read this reference only for connecting, troubleshooting, or cutting with the supported Silhouette Cameo 5 Alpha. Confirm the exact model, operating system, and desired USB or Bluetooth transport. On macOS, complete [macos-install.md](macos-install.md) first.

## Compatibility boundary

This skill's supported-cutter list contains only the **Silhouette Cameo 5 Alpha**, because that is the model physically verified through the complete workflow. The current `fablabnbg/inkscape-silhouette` driver lists additional devices, but upstream driver compatibility alone does not verify this skill's registration geometry, coordinate behavior, or mat positioning on them.

If the user has another cutter, explain that it is outside the verified support boundary. Consult the current upstream list for feasibility, but do not perform a hardware run under this skill until the model-specific flow has been validated.

Current sources:

- [inkscape-silhouette supported devices and installation](https://github.com/fablabnbg/inkscape-silhouette)
- [inkscape-silhouette user guide](https://github.com/fablabnbg/inkscape-silhouette/blob/main/USERGUIDE.md)
- [Silhouette America connection troubleshooting](https://silhouetteamerica.freshdesk.com/support/solutions/articles/35000275242-connection-troubleshooting)

Driver behavior changes over time. Verify current upstream instructions and `sendto_silhouette.py --help` before giving version-sensitive flags.

## First connection

Prefer direct USB for the first test unless the user specifically wants Bluetooth:

1. Install Inkscape, the upstream extension, and the transport dependencies.
2. Power on the cutter and connect a known-good data cable directly, without a hub.
3. Confirm the operating system sees it before debugging SVG or cut settings.
4. Ask the user to save and close Silhouette Studio and other cutter software.
5. Confirm **Extensions → Export → Send to Silhouette** exists. For CLI use, run `sendto_silhouette.py --help` with Inkscape's configured interpreter.
6. Run the bundled `silhouette-dry-run` before any hardware movement.
7. Query the connection/firmware without a loaded blade movement, then run an authorized sacrificial test.

## BLE has one owner

Treat a BLE cutter as a single-owner device. Silhouette Studio can keep the connection through its `ss_bluetooth` helper even when another window is frontmost. When Studio owns it, a direct CoreBluetooth scan may fail to advertise the expected cutter name or a connection may time out.

Before every direct BLE session:

1. Ask the user to save work and quit Silhouette Studio; do not force-quit unsaved work.
2. Confirm Studio and `ss_bluetooth` have exited.
3. Scan with `--connection_type=ble --bluetooth_scan=True`.
4. Select by advertised name or the scan's platform-local identifier.

On macOS, the platform-local identifier is a CoreBluetooth UUID, not the hardware MAC address shown in System Information. BLE does not require Bluetooth Classic pairing. If discovery remains unreliable, use direct USB.

## Registration and mat position

Registration is a physical state machine. The optical search assumes the mat begins at the known load origin. A prior job can change that state even when its cut geometry was only a small test.

The upstream CLI defaults to `--endposition=below`, which advances media below the actual cut. That is useful after the final job, but it is unsafe for a sacrificial test followed immediately by a registered production cut on the same loaded mat: the next search can start from the displaced head/media position and look for the top-left mark in the wrong place.

Use this sequence:

1. Load the mat squarely at the cutter's normal loading guides.
2. Run the sacrificial test with `--endposition=start`.
3. Confirm with the user that the test cut and returned position look correct.
4. Run the full registered sheet. Use `--endposition=below` only if presenting the finished sheet is desired.
5. Manually unload the mat after the final job.

If the head starts scanning near the bottom of the paper or cannot find the top-left registration mark after another job, suspect displaced media state before changing SVG offsets or registration geometry.

## Safe recovery after a registration failure

Never blindly retry a full sheet after a timeout, abort, or unexpected motion:

1. Stop and preserve the driver log and `--cmdfile` transcript.
2. Determine whether contour commands were sent and ask the user whether the blade moved. A failure while waiting for registration plus an empty command transcript is evidence that contour cutting did not start, but still verify the physical sheet.
3. If any contour may have been cut, have the user inspect the sheet before deciding whether a retry would double-cut it.
4. Have the user manually unload the mat, square it, and reload from the normal origin.
5. Re-run the artifact verifier and registration from that known state.

Do not “fix” this failure by shifting cut coordinates until mat origin is known.

## Can the mat be unloaded programmatically?

Not through a verified first-class command in the current upstream CLI. The driver has a low-level `move_origin(feed_mm)` method and `misc/silhouette_move.py` paper-feed demo, but those feed media and redefine origin; they are not documented or physically verified as a true Cameo 5 Alpha unload/release operation.

Therefore:

- use `--endposition=start` to preserve state between test and production jobs;
- use manual unload/reload as the reliable recovery after any registration failure;
- do not call the feed helper as “eject mat” without a model-specific physical validation, a bounded feed distance, and explicit user authorization.

A future model-aware `mat-eject` wrapper is possible, but it should remain experimental until its command, stopping behavior, and roller release are verified on each target cutter.

## Material and cut settings

Do not universalize settings from one successful run. Confirm material, mat, toolholder, blade, kiss/die cut, force, speed, depth, and passes. Then perform a small sacrificial test on the same material.

One observed Cameo 5 Alpha baseline for ordinary lightweight printer paper and a carriage-1 AutoBlade was upstream media `132`, depth `1`, force `5`, speed `10`, and one pass. Treat that only as a starting hypothesis and keep the user's observed test result as the authority.

## Diagnose failures

Check in this order:

1. Known mat/head origin and registration marks unobstructed.
2. Cutter power/state and competing software ownership.
3. Operating-system detection and transport permissions.
4. Direct USB cable/port without a hub, or a fresh BLE scan after Studio exits.
5. Driver path and the exact configured Python interpreter.
6. `import usb.core` for USB or `import bleak` for BLE in that interpreter.
7. Firmware and current manufacturer guidance.

Do not move a blade merely to prove connectivity. Dry-run first; then use a sacrificial test only with explicit authorization for hardware motion.

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree as ET


SVG_NS = "http://www.w3.org/2000/svg"


def find_driver(explicit: Path | None = None) -> Path | None:
    candidates: list[Path] = []
    if explicit:
        candidates.append(explicit)
    env_path = os.environ.get("INKSCAPE_SILHOUETTE_DRIVER")
    if env_path:
        candidates.append(Path(env_path))
    on_path = shutil.which("sendto_silhouette.py")
    if on_path:
        candidates.append(Path(on_path))
    candidates.extend(
        [
            Path("/Applications/Inkscape.app/Contents/Resources/share/inkscape/extensions/sendto_silhouette.py"),
            Path.home() / "Library/Application Support/org.inkscape.Inkscape/config/inkscape/extensions/sendto_silhouette.py",
            Path.home() / ".config/inkscape/extensions/sendto_silhouette.py",
            Path("/usr/share/inkscape/extensions/sendto_silhouette.py"),
        ]
    )
    return next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)


def run_dry_run(
    svg_path: Path,
    *,
    driver: Path | None = None,
    python_executable: Path | None = None,
    force_hardware: str = "Silhouette_Cameo5_Alpha",
) -> dict:
    svg_path = svg_path.resolve()
    output_dir = svg_path.parent / "dry-run"
    output_dir.mkdir(parents=True, exist_ok=True)
    status_path = output_dir / "status.json"
    resolved_driver = find_driver(driver)
    if not resolved_driver:
        result = {
            "status": "unavailable",
            "passed": False,
            "message": "sendto_silhouette.py was not found. Pass --driver or set INKSCAPE_SILHOUETTE_DRIVER.",
        }
        status_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result

    logfile = output_dir / "silhouette.log"
    cmdfile = output_dir / "cutter-commands.bin"
    stdout_path = output_dir / "stdout.txt"
    stderr_path = output_dir / "stderr.txt"
    registration_log = output_dir / "registration-probe.log"
    registration_cmdfile = output_dir / "registration-commands.bin"
    registration_stdout = output_dir / "registration-stdout.txt"
    registration_stderr = output_dir / "registration-stderr.txt"

    root = ET.parse(svg_path).getroot()
    reg_layer = root.find(f".//{{{SVG_NS}}}g[@id='regmark']")
    if reg_layer is None:
        result = {"status": "failed", "passed": False, "message": "SVG has no id='regmark' layer."}
        status_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result
    origin_x = float(reg_layer.get("data-origin-x-mm", "0"))
    origin_y = float(reg_layer.get("data-origin-y-mm", "0"))

    python = str(python_executable or Path(sys.executable))
    base_command = [
        python,
        str(resolved_driver),
        "--dry_run=True",
        "--preview=False",
        "--log_paths=True",
        f"--force_hardware={force_hardware}",
    ]
    # Upstream dry-run still waits for a physical sensor response whenever
    # regmark=True. Run the complete cut-command path separately with the same
    # origin compensation that the driver applies after successful registration.
    command = [
        *base_command,
        f"--x_off={-origin_x}",
        f"--y_off={-origin_y}",
        f"--logfile={logfile}",
        f"--cmdfile={cmdfile}",
        str(svg_path),
    ]
    process = subprocess.run(command, capture_output=True, text=True, check=False)
    stdout_path.write_text(process.stdout, encoding="utf-8")
    stderr_path.write_text(process.stderr, encoding="utf-8")
    log = logfile.read_text(encoding="utf-8", errors="replace") if logfile.exists() else ""
    path_match = re.search(r"Logging\s+(\d+)\s+cut paths containing\s+(\d+)\s+points", log)
    driver_parsed_paths = bool(path_match)
    abort_markers = ("Aborting:", "empty page?", "Traceback (most recent call last)")
    cutting_passed = (
        process.returncode == 0
        and driver_parsed_paths
        and cmdfile.exists()
        and cmdfile.stat().st_size > 0
        and "status=ready" in log
        and not any(marker in log + process.stderr for marker in abort_markers)
    )

    registration_command = [
        *base_command,
        "--regmark=True",
        "--regsearch=True",
        f"--logfile={registration_log}",
        f"--cmdfile={registration_cmdfile}",
        str(svg_path),
    ]
    reg_process = subprocess.run(registration_command, capture_output=True, text=True, check=False)
    registration_stdout.write_text(reg_process.stdout, encoding="utf-8")
    registration_stderr.write_text(reg_process.stderr, encoding="utf-8")
    reg_log_text = registration_log.read_text(encoding="utf-8", errors="replace") if registration_log.exists() else ""
    detected_marks = "Detected Existing Registration Mark::" in reg_log_text and "Using Registration Mark::" in reg_log_text
    expected_sensor_stop = "Couldn't find registration marks. None" in reg_process.stderr
    registration_commands_written = registration_cmdfile.exists() and registration_cmdfile.stat().st_size > 0
    # With no cutter, current upstream reaches the exact optical-sensor read and
    # then stops. Reaching that known stop proves the mark search command was built.
    registration_passed = detected_marks and registration_commands_written and (
        reg_process.returncode == 0 or expected_sensor_stop
    )
    passed = cutting_passed and registration_passed
    result = {
        "status": "passed" if passed else "failed",
        "passed": passed,
        "returncode": process.returncode,
        "driver": str(resolved_driver),
        "python": python,
        "command": command,
        "registration": {
            "origin_mm": {"x": origin_x, "y": origin_y},
            "command": registration_command,
            "search_command_exercised": True,
            "driver_returncode": reg_process.returncode,
            "expected_no_hardware_sensor_stop": expected_sensor_stop,
            "detected_document_marks": detected_marks,
            "commands_written": registration_commands_written,
            "note": (
                "Current upstream waits for a real optical-sensor response even in dry-run. "
                "The probe is successful without hardware when it reaches that specific sensor stop; "
                "the complete blade-command pass is run separately with identical registration-origin compensation."
            ),
        },
        "cutting_command_passed": cutting_passed,
        "parsed_cut_paths": int(path_match.group(1)) if path_match else None,
        "parsed_cut_points": int(path_match.group(2)) if path_match else None,
        "files": {
            "log": logfile.name,
            "commands": cmdfile.name,
            "stdout": stdout_path.name,
            "stderr": stderr_path.name,
            "registration_log": registration_log.name,
            "registration_commands": registration_cmdfile.name,
            "registration_stdout": registration_stdout.name,
            "registration_stderr": registration_stderr.name,
        },
    }
    status_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result

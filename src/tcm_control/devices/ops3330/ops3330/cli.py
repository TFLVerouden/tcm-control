"""
Command-line interface for the TSI OPS 3330.

Examples
--------
# Read basic instrument info
python -m ops3330.cli --conn profiles/connection.toml info

# Push a profile (channel setup + logging setup, etc.) to the instrument
python -m ops3330.cli --conn profiles/connection.toml apply-profile profiles/default_minimal.toml

# Start / stop a measurement
python -m ops3330.cli --conn profiles/connection.toml start
python -m ops3330.cli --conn profiles/connection.toml stop

# Fully shut the instrument down
python -m ops3330.cli --conn profiles/connection.toml shutdown

# Run a measurement and save the results to a CSV file on this PC
python -m ops3330.cli --conn profiles/connection.toml record --duration 600 --out data/run1.csv
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .client import OPSClient, OPSError
from .profile import load_profile, apply_profile
from .datalogger import record_measurement

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


def _load_connection(path: str) -> dict:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return data["connection"]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Control a TSI OPS 3330 over USB (NDIS) or Ethernet.")
    p.add_argument("--conn", required=True, help="Path to a connection.toml file (ip/port/timeout).")
    p.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging.")

    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="Print model/serial/firmware/status.")
    sub.add_parser("start", help="Start a measurement (MSTART).")
    sub.add_parser("stop", help="Stop the current measurement (MSTOP).")
    sub.add_parser("shutdown", help="Fully power down the instrument (MSHUTDOWN).")

    ap = sub.add_parser("apply-profile", help="Push a profile .toml to the instrument.")
    ap.add_argument("profile", help="Path to a profile .toml file.")

    rec = sub.add_parser("record", help="Run a measurement and save it to CSV.")
    rec.add_argument("--out", required=True, help="Output CSV path.")
    rec.add_argument("--duration", type=float, default=None, help="Max duration in seconds.")
    rec.add_argument("--samples", type=int, default=None, help="Max number of logged samples.")
    rec.add_argument("--poll-interval", type=float, default=1.0, help="Polling interval in seconds.")

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    conn = _load_connection(args.conn)
    client = OPSClient(ip=conn["ip"], port=conn.get("port", 3602), timeout=conn.get("timeout", 5.0))

    try:
        client.connect()

        if args.cmd == "info":
            print("Model:   ", client.read_model_number())
            print("Serial:  ", client.read_serial_number())
            print("Firmware:", client.read_firmware_version())
            print("Status:  ", client.read_status())

        elif args.cmd == "start":
            print(client.start_measurement())

        elif args.cmd == "stop":
            print(client.stop_measurement())

        elif args.cmd == "shutdown":
            print(client.shutdown())

        elif args.cmd == "apply-profile":
            profile = load_profile(args.profile)
            apply_profile(client, profile)
            print("Profile applied and committed (MUPDATE).")

        elif args.cmd == "record":
            out = record_measurement(
                client,
                out_path=Path(args.out),
                max_samples=args.samples,
                max_duration_s=args.duration,
                poll_interval_s=args.poll_interval,
            )
            print(f"Saved measurement data to {out}")

    except OPSError as e:
        print(f"OPS error: {e}", file=sys.stderr)
        return 1
    finally:
        client.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

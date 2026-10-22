from __future__ import annotations

import argparse

# This script assumes an editable install. Install once from repo root: `pip install -e .`

from tcm_control.devices import SprayTec


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Archive the SprayTec append file into an archive folder next to the source file."
    )
    parser.add_argument(
        "--append-file",
        type=str,
        default=None,
        help="Path to SprayTec append file. If omitted, file dialog opens.",
    )
    args = parser.parse_args()

    spraytec = SprayTec(append_file_path=args.append_file)
    archived_path = spraytec.archive_append_file()
    print(f"Archived append file to: {archived_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

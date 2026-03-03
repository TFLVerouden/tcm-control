from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PYTHON = REPO_ROOT / "source_python"
if str(SOURCE_PYTHON) not in sys.path:
    sys.path.insert(0, str(SOURCE_PYTHON))

from tcm_control.devices.spraytec_output import archive_spraytec_append_file


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

    archived_path = archive_spraytec_append_file(args.append_file)
    print(f"Archived append file to: {archived_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

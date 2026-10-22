"""
Example: connect, apply the minimal profile, run a short measurement,
do other host-side work while the OPS logs in the background,
then collect and save the CSV.
"""

from tcm_control.devices.ops3330.ops3330 import OPSClient, OPS
import logging
import sys
import time
from pathlib import Path
import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT.parents[2]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

# <-- set to your OPS's IP (Communications screen)
CONNECTION_IP = "192.168.1.50"
PROFILE_PATH = PROJECT_ROOT / "profiles" / "default_minimal.toml"

OUT_CSV = PROJECT_ROOT / "data" / \
    f"example_run_{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.csv"


def main() -> None:
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)

    with OPSClient(ip=CONNECTION_IP) as client:
        ops = OPS(client)

        print("Model:", client.read_model_number())
        print("Status:", ops.read_status())

        ops.start_standard_recording(
            profile_toml_path=PROFILE_PATH,
            out_csv_path=OUT_CSV,
        )

        # Example: run other host-side code while OPS logging continues.
        for step in range(3):
            print(f"Running other code while OPS records... step {step + 1}/3")
            time.sleep(1)

        recorded_csv = ops.collect_recording()
        print(f"Saved data to {recorded_csv}")


if __name__ == "__main__":
    main()

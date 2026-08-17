"""
Example: connect, apply the minimal profile, run a short measurement,
save it to CSV, then stop.

This can be run two ways:

    # from anywhere, as a script
    python examples/basic_usage.py

    # from the project root, as a module (also works, no path hack needed)
    python -m examples.basic_usage
"""

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ops3330 import OPSClient, load_profile, apply_profile, record_measurement 

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

CONNECTION_IP = "192.168.1.50"   # <-- set to your OPS's USB IP (Communications screen)
PROFILE_PATH = PROJECT_ROOT / "profiles" / "default_minimal.toml"

import datetime
OUT_CSV = PROJECT_ROOT / "data" / f"example_run_{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.csv"

def get_sec(time_str):
    """Get seconds from time."""
    h, m, s = time_str.split(':')
    return int(h) * 3600 + int(m) * 60 + int(s)


def main() -> None:
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)

    with OPSClient(ip=CONNECTION_IP) as client:
        print("Model:", client.read_model_number())
        print("Status:", client.read_status())

        profile = load_profile(PROFILE_PATH)
        
        apply_profile(client, profile)
        print("Profile applied.")
        
        # Currently in hh:mm:ss, convert to seconds for max_duration_s
        sample_interval_s = get_sec(profile["logging"]["sample_interval"])
        number_of_samples = profile["logging"]["number_of_samples"]
        number_of_sets = profile["logging"]["number_of_sets"]
        repeat_interval_s = get_sec(profile["logging"]["repeat_interval"])
        max_duration_s = sample_interval_s * number_of_samples * number_of_sets + repeat_interval_s

        sleeping_time = 10 
        record_measurement(
            client,
            out_path=OUT_CSV,
            max_duration_s=max_duration_s + sleeping_time,
            poll_interval_s=sample_interval_s / 4,
        )
        print(f"Saved data to {OUT_CSV}")

if __name__ == "__main__":
    main()



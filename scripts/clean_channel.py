"""Run the cough-machine channel cleaning routine without a TOML config."""

# This script assumes an editable install. Install once from repo root: `pip install -e .`

from tcm_control.devices import CoughMachine

PRESSURE_BAR = 3
OPEN_DURATION_S = 1
REPEATS = 3


def main() -> None:
    tcm = CoughMachine(debug=False)
    print("Starting channel cleaning routine...")
    tcm.clean(pressure_bar=PRESSURE_BAR,
              open_duration_s=OPEN_DURATION_S, repeats=REPEATS)
    print("Cleaning routine completed.")


if __name__ == "__main__":
    main()

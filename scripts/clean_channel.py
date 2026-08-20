"""Run the cough-machine channel cleaning routine without a TOML config."""

# This script assumes an editable install. Install once from repo root: `pip install -e .`

from tcm_control.devices import CoughMachine

PRESSURE_BAR = 4
OPEN_DURATION_S = 5
DRY_PRESSURE_BAR = 2
DRY_DURATION_S = 0
DRY_VALVE_CURRENT_MA = 13
REPEATS = 1


def main() -> None:
    tcm = CoughMachine(debug=False)
    print("Starting channel cleaning routine...")
    tcm.clean(clean_pressure_bar=PRESSURE_BAR,
              valve_open_duration_s=OPEN_DURATION_S,
              cycle_count=REPEATS,
              dry_pressure_bar=DRY_PRESSURE_BAR,
              dry_duration_s=DRY_DURATION_S,
              dry_valve_current_ma=DRY_VALVE_CURRENT_MA)
    print("Cleaning routine completed.")


if __name__ == "__main__":
    main()

"""Run the cough-machine channel cleaning routine without a TOML config."""

# This script assumes an editable install. Install once from repo root: `pip install -e .`

from tcm_control.devices import CoughMachine

# Strong Cough
PRESSURE_BAR = 5
OPEN_DURATION_S = 3
DRY_PRESSURE_BAR = 2
DRY_DURATION_S = 0
DRY_VALVE_CURRENT_MA = 13
REPEATS = 3

# Dry Cleaning
DRYING_PRESSURE_BAR = 2.5
DRYING_OPEN_DURATION_S = 20
DRYING_DRY_PRESSURE_BAR = 2
DRYING_DURATION_S = 0
DRYING_VALVE_CURRENT_MA = 13
DRYING_REPEATS = 1


def main() -> None:
    tcm = CoughMachine(debug=False)
    print("Starting channel cleaning routine...")
    tcm.clean(clean_pressure_bar=PRESSURE_BAR,
              valve_open_duration_s=OPEN_DURATION_S,
              cycle_count=REPEATS,
              dry_pressure_bar=DRY_PRESSURE_BAR,
              dry_duration_s=DRY_DURATION_S,
              dry_valve_current_ma=DRY_VALVE_CURRENT_MA)

    tcm.clean(clean_pressure_bar=DRYING_PRESSURE_BAR,
              valve_open_duration_s=DRYING_OPEN_DURATION_S,
              cycle_count=DRYING_REPEATS,
              dry_pressure_bar=DRYING_DRY_PRESSURE_BAR,
              dry_duration_s=DRYING_DURATION_S,
              dry_valve_current_ma=DRYING_VALVE_CURRENT_MA)

    print("Cleaning routine completed.")


if __name__ == "__main__":
    main()

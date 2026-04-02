"""Run the cough-machine channel cleaning routine without a TOML config."""

from tcm_control.devices import CoughMachine

PRESSURE_BAR = 4.0
OPEN_DURATION_S = 2.5
REPEATS = 3


def main() -> None:
    tcm = CoughMachine(debug=False)
    print("Starting channel cleaning routine...")
    tcm.clean(pressure_bar=PRESSURE_BAR,
              open_duration_s=OPEN_DURATION_S, repeats=REPEATS)
    print("Cleaning routine completed.")


if __name__ == "__main__":
    main()

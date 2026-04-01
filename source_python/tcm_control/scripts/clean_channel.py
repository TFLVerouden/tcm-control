"""Run the cough-machine channel cleaning routine without a TOML config."""

from tcm_control.devices import CoughMachine


def main() -> None:
    tcm = CoughMachine(debug=False)
    print("Starting channel cleaning routine...")
    tcm.clean()
    print("Cleaning routine completed.")


if __name__ == "__main__":
    main()

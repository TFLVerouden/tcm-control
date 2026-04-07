"""Minimal one-shot trigger script for the cough machine MCU."""

# This script assumes an editable install. Install once from repo root: `pip install -e .`

from tcm_control.devices import CoughMachine


def main() -> None:
    tcm = CoughMachine(debug=False)
    print("Sending trigger pulse...")
    tcm.trigger_once()
    print("Done.")


if __name__ == "__main__":
    main()

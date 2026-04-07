"""Run manual serial control session with the cough machine (no config file)."""

# This script assumes an editable install. Install once from repo root: `pip install -e .`

from tcm_control.devices import CoughMachine


def main() -> None:
    tcm = CoughMachine(debug=False)
    tcm.manual_mode()


if __name__ == "__main__":
    main()

"""Run manual serial control session with the cough machine (no config file)."""

from tcm_control.devices import CoughMachine


def main() -> None:
    tcm = CoughMachine(debug=False)
    tcm.manual_mode()


if __name__ == "__main__":
    main()

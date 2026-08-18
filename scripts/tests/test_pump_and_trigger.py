"""Connect to the pump and cough machine, infuse at 0.5 mL/min, trigger, then stop."""

import time

from tcm_control.devices import CoughMachine, SyringePump


def main() -> None:
    pump = SyringePump()
    tcm = CoughMachine(debug=False)

    print("Infusing at 0.5 mL/min for 5 seconds...")
    pump.infuse(pump_rate_ml_mn=0.5)
    time.sleep(5)

    print("Sending external trigger pulse...")
    tcm.trigger_once()

    print("Continuing infusion for 5 more seconds...")
    time.sleep(5)

    print("Stopping pump.")
    pump.stop()


if __name__ == "__main__":
    main()

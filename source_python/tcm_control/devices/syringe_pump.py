import pumpy3
import time
from tcm_utils.io_utils import prompt_input

# Source code and documentation: https://github.com/Wetenschaap/pumpy3
# First ensure RS-232 settings on the PHD 2000 are configured.
#   Press: Set >  RS-232 (choose PUMP CHAIN) > Enter (set address)
#   > Enter (set baud rate) > Enter (confirm)


class SyringePump(pumpy3.PumpPHD2000_Refill):
    def __init__(
        self,
        port: str | None = None,
        diameter_mm: float | None = None,
        baudrate: int = 19200,
        timeout: float = 0.3,
        pump_address: int = 0
    ):
        # If no port is provided, prompt the user to enter the COM port number
        if port is None:
            # port_number = prompt_input(
            #     "Enter COM port number for syringe pump: COM")
            # port = f"COM{port_number}"
            port = "COM11"

        # Initialise chain
        chain = pumpy3.Chain(port, baudrate=baudrate, timeout=timeout)

        # Flush the serial buffer to prevent issues with leftover data from previous connections
        chain.flush()

        # print(self.get_diameter())

        # Idem for diameter
        if diameter_mm is None:
            # diameter_mm = float(prompt_input("Enter syringe diameter in mm: "))
            diameter_mm = 7.28

        # Initialise PHD 2000
        super().__init__(chain, address=pump_address, name="PHD2000")
        self.set_mode("PMP")  # Set to PuMP mode
        self.set_diameter(diameter_mm)


if __name__ == "__main__":
    pump = SyringePump()
    pump.set_rate(2, "ml/mn")  # Set rate to 0.2 mL/min
    pump.run()
    time.sleep(60)
    pump.stop()

import pumpy3
import time
import serial
from pathlib import Path
from tcm_utils.file_dialogs import read_repo_config_value, write_repo_config_value
from tcm_utils.io_utils import prompt_input, load_two_column_numeric

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

        # TODO: Test connection!!
        connections_filename = "connections.ini"
        com_ports_section = "com_ports"
        port_key = "syringe_pump"

        selected_port = port
        if selected_port is None:
            selected_port = read_repo_config_value(
                port_key,
                filename=connections_filename,
                section=com_ports_section,
            )

        chain = None
        if selected_port is not None:
            chain = self._try_open_chain(selected_port, baudrate, timeout)

        if chain is None:
            prompted_raw = prompt_input(
                "Enter COM port for syringe pump (e.g. 11 or COM11): "
            )
            prompted_text = "" if prompted_raw is None else str(prompted_raw)
            selected_port = self._normalize_com_port(prompted_text)
            chain = self._try_open_chain(selected_port, baudrate, timeout)
            if chain is None:
                raise RuntimeError(
                    f"Could not open syringe pump chain at {selected_port}."
                )

        if selected_port is None:
            raise RuntimeError("No COM port selected for syringe pump.")

        write_repo_config_value(
            port_key,
            selected_port,
            filename=connections_filename,
            section=com_ports_section,
        )

        # print(self.get_diameter())

        # Idem for diameter
        if diameter_mm is None:
            # diameter_mm = float(prompt_input("Enter syringe diameter in mm: "))
            diameter_mm = 7.28

        # Initialise PHD 2000
        super().__init__(chain, address=pump_address, name="PHD2000")
        self.set_mode("PMP")  # Set to PuMP mode
        self.set_diameter(diameter_mm)

    @staticmethod
    def _normalize_com_port(raw_value: str) -> str:
        value = raw_value.strip().upper()
        if value.startswith("COM"):
            return value
        return f"COM{value}"

    @staticmethod
    def _try_open_chain(
        port: str,
        baudrate: int,
        timeout: float,
    ) -> pumpy3.Chain | None:
        try:
            chain = pumpy3.Chain(port, baudrate=baudrate, timeout=timeout)
            chain.flush()
            return chain
        except (serial.SerialException, OSError, ValueError):
            return None

    # TODO: TEST BELOW FUNCTIONS
    @staticmethod
    def get_syringe_diameter(
        volume_ml: float,
        type: str = "hamilton_microliter_gastight",
        lookup_table_path: str | Path = "config/syringe_sizes.csv",
    ) -> float:
        # From the look-up table for in the PHD 2000 manual, as mirrored
        # in /config/syringe_sizes.csv, get the diameter for a syringe of the
        # given volume and type.

        # Only support relevant type
        if type != "hamilton_microliter_gastight":
            raise NotImplementedError(f"Syringe type {type} not implemented.")

        # Read the look-up table and find the diameter for the given volume
        table = load_two_column_numeric(Path(lookup_table_path))
        for row in table:
            row_volume, row_diameter = row
            if row_volume == volume_ml:
                return row_diameter

        # Else, if no match found, raise an error
        raise ValueError(
            f"No diameter found for syringe type {type} and volume {volume_ml} mL.")

    def set_syringe_volume(self, volume_ml: float, type: str = "hamilton_microliter_gastight"):
        diameter_mm = self.get_syringe_diameter(volume_ml, type=type)
        self.set_diameter(diameter_mm)


if __name__ == "__main__":
    pump = SyringePump()
    pump.set_rate(2, "ml/mn")  # Set rate to 0.2 mL/min
    pump.run()
    time.sleep(60)
    pump.stop()

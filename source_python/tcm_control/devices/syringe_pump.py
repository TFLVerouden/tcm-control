import math
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
        syringe_volume_ml: float | None = None,
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
        last_error: Exception | None = None
        # Keep trying until we get a responding pump or the user cancels.
        while True:
            if selected_port is not None:
                # First try any stored/explicit port without prompting.
                chain = self._try_open_chain(selected_port, baudrate, timeout)

            if chain is None:
                # If the stored port failed, ask for a new one and retry.
                prompted_raw = prompt_input(
                    "Enter COM port for syringe pump (e.g. 11 or COM11) or press Enter to quit: "
                )
                prompted_text = "" if prompted_raw is None else str(
                    prompted_raw)
                if not prompted_text:
                    # Allow a clean exit when the user chooses not to retry.
                    selected_port = None
                    break
                selected_port = self._normalize_com_port(prompted_text)
                chain = self._try_open_chain(selected_port, baudrate, timeout)
                if chain is None:
                    # Record the last failure and continue prompting.
                    last_error = RuntimeError(
                        f"Could not open syringe pump chain at {selected_port}."
                    )
                    continue

            if selected_port is None:
                raise RuntimeError("No COM port selected for syringe pump.")

            try:
                # Initialise PHD 2000 (this can raise if the pump is disconnected).
                super().__init__(chain, address=pump_address, name="PHD2000")
            except pumpy3.pump.PumpNoResponseError as exc:
                # Handshake failed; force a new port prompt.
                last_error = exc
                chain = None
                selected_port = None
                continue

            # Only persist the port once a live pump responds.
            write_repo_config_value(
                port_key,
                selected_port,
                filename=connections_filename,
                section=com_ports_section,
            )
            break

        if last_error is not None and chain is None:
            # Surface the last failure if we exit without a working pump.
            raise last_error

        # Get currently set diameter
        current_volume = self.get_syringe_volume(self.get_diameter())

        # If not provided, ask user for syringe volume
        if syringe_volume_ml is None:
            syringe_volume_ml = float(prompt_input(
                f"Enter syringe volume in mL (press Enter to use current volume of {current_volume} mL): ", value_type=float, min_value=0.0005, max_value=50.0))

            if not syringe_volume_ml:
                syringe_volume_ml = current_volume

        # Set to PuMP mode, and set diameter using the syringe volume lookup table.
        self.set_mode("PMP")
        self.set_syringe_volume(syringe_volume_ml)

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
        except (serial.SerialException, OSError, ValueError, pumpy3.pump.PumpNoResponseError):
            return None

    # TODO: TEST BELOW FUNCTIONS
    @staticmethod
    def _load_syringe_table(lookup_table_path: str | Path) -> list[tuple[float, float]]:
        return [(row[0], row[1]) for row in load_two_column_numeric(Path(lookup_table_path))]

    @staticmethod
    def get_syringe_diameter(
        volume_ml: float,
        type: str = "hamilton_microliter_gastight",
        lookup_table_path: str | Path = "config/syringe_sizes.csv",
    ) -> float:
        # Map volume -> diameter from the lookup table.
        if type != "hamilton_microliter_gastight":
            raise NotImplementedError(f"Syringe type {type} not implemented.")
        for row_volume, row_diameter in SyringePump._load_syringe_table(lookup_table_path):
            if row_volume == volume_ml:
                return row_diameter
        raise ValueError(
            f"No diameter found for syringe type {type} and volume {volume_ml} mL.")

    @staticmethod
    def get_syringe_volume(
        diameter_mm: float,
        type: str = "hamilton_microliter_gastight",
        lookup_table_path: str | Path = "config/syringe_sizes.csv",
    ) -> float:
        # Map diameter -> volume from the lookup table.
        if type != "hamilton_microliter_gastight":
            raise NotImplementedError(f"Syringe type {type} not implemented.")
        for row_volume, row_diameter in SyringePump._load_syringe_table(lookup_table_path):
            if math.isclose(row_diameter, diameter_mm, rel_tol=0.0, abs_tol=1e-6):
                return row_volume
        raise ValueError(
            f"No volume found for syringe type {type} and diameter {diameter_mm} mm.")

    def set_syringe_volume(self, volume_ml: float, type: str = "hamilton_microliter_gastight"):
        diameter_mm = self.get_syringe_diameter(volume_ml, type=type)
        self.set_diameter(diameter_mm)


if __name__ == "__main__":
    pump = SyringePump()
    pump.set_rate(2, "ml/mn")  # Set rate to 0.2 mL/min
    pump.run()
    time.sleep(60)
    pump.stop()

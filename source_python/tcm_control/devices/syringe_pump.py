import math
import time
import serial
from pathlib import Path
from pumpy3.pump import Chain, PumpNoResponseError, PumpPHD2000_Refill
from tcm_utils.file_dialogs import read_repo_config_value, write_repo_config_value
from tcm_utils.io_utils import prompt_input


DEFAULT_SYRINGE_TABLE_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "syringe_sizes.csv"
)

# Source code and documentation: https://github.com/Wetenschaap/pumpy3
# First ensure RS-232 settings on the PHD 2000 are configured.
#   Press: Set >  RS-232 (choose PUMP CHAIN) > Enter (set address)
#   > Enter (set baud rate) > Enter (confirm)


class SyringePump(PumpPHD2000_Refill):
    def __init__(
        self,
        port: str | None = None,
        syringe_volume_ml: float | None = None,
        baudrate: int = 19200,
        timeout: float = 0.3,
        pump_address: int = 0
    ):
        """Initialise the syringe pump by connecting to the specified COM port
        using pumpy3, and setting the syringe volume.
        """
        connections_filename = "connections.ini"
        com_ports_section = "com_ports"
        port_key = "syringe_pump"

        self.baudrate = baudrate
        self.timeout_s = timeout
        self.pump_address = pump_address

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
                    "Enter COM port for syringe pump (e.g. 11 or COM11) or press Enter to quit: ",
                    allow_empty=True)
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
            except PumpNoResponseError as exc:
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
            self.port = selected_port
            break

        if last_error is not None and chain is None:
            # Surface the last failure if we exit without a working pump.
            raise last_error

        # Print confirmation of successful connection.
        print(f"Connected to serial device SyringePump at {selected_port}")

        # Get currently set diameter
        current_volume = self.get_syringe_volume(self.get_diameter())

        # If not provided, ask user for syringe volume
        if syringe_volume_ml is None:
            prompted_volume = prompt_input(
                f"Enter syringe volume in mL (press Enter to use current volume of {current_volume} mL): ", value_type="float", min_value=0.0005, max_value=50.0, allow_empty=True)
            syringe_volume_ml = float(
                prompted_volume) if prompted_volume is not None else current_volume
        syringe_volume_ml = float(syringe_volume_ml)
        self.syringe_volume_ml = syringe_volume_ml

        # Set to PuMP mode, and set diameter using the syringe volume lookup table.
        self.set_mode("PMP")
        self.set_syringe_volume(syringe_volume_ml)

    @staticmethod
    def _normalize_com_port(raw_value: str) -> str:
        """Format user input for COM port.

        Accept inputs like "11" or "COM11" and normalize to "COM11".
        """
        value = raw_value.strip().upper()
        if value.startswith("COM"):
            return value
        return f"COM{value}"

    @staticmethod
    def _try_open_chain(
        port: str,
        baudrate: int,
        timeout: float,
    ) -> Chain | None:
        """Try to open a pumpy3 Chain on the specified COM port.

        Returns None on failure, rather than raising errors.
        """
        try:
            chain = Chain(port, baudrate=baudrate, timeout=timeout)
            chain.flush()
            return chain
        except (serial.SerialException, OSError, ValueError, PumpNoResponseError):
            return None

    @staticmethod
    def _load_syringe_table(
        lookup_table_path: str | Path
    ) -> list[tuple[float, float]]:
        """ Load the syringe volume-diameter lookup table from a CSV file."""
        output = []
        with open(lookup_table_path, "r") as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue  # Skip empty lines and comments
                parts = stripped.split(",")
                if len(parts) != 2:
                    continue  # Skip malformed lines
                try:
                    volume = float(parts[0].strip())
                    diameter = float(parts[1].strip())
                    output.append((volume, diameter))
                except ValueError:
                    continue  # Skip lines with non-numeric values

        return output

    @staticmethod
    def get_syringe_diameter(
        volume_ml: float,
        type: str = "hamilton_microliter_gastight",
        lut_path: str | Path = DEFAULT_SYRINGE_TABLE_PATH,
    ) -> float:
        """Map syringe volume to diameter using the lookup table."""
        if type != "hamilton_microliter_gastight":
            raise NotImplementedError(f"Syringe type {type} not implemented.")
        for row_vol, row_diam in SyringePump._load_syringe_table(lut_path):
            if row_vol == volume_ml:
                return row_diam
        raise ValueError(f"No diameter found for syringe type {type}\
                          and volume {volume_ml} mL.")

    @staticmethod
    def get_syringe_volume(
        diameter_mm: float,
        type: str = "hamilton_microliter_gastight",
        lut_path: str | Path = DEFAULT_SYRINGE_TABLE_PATH,
    ) -> float:
        """Map syringe diameter to volume using the lookup table.

        Approximates for floating point comparison."""
        if type != "hamilton_microliter_gastight":
            raise NotImplementedError(f"Syringe type {type} not implemented.")
        for row_vol, row_diam in SyringePump._load_syringe_table(lut_path):
            if math.isclose(row_diam, diameter_mm, rel_tol=0.0, abs_tol=1e-6):
                return row_vol
        raise ValueError(f"No volume found for syringe type {type}\
                          and diameter {diameter_mm} mm.")

    def set_syringe_volume(
        self,
        volume_ml: float,
        type: str = "hamilton_microliter_gastight"
    ):
        """Set the syringe diameter based on volume from the lookup table."""
        diameter_mm = self.get_syringe_diameter(volume_ml, type=type)
        self.set_diameter(diameter_mm)

    def infuse(self,
               pump_rate_ml_mn: float | None = None,
               duration_s: float | None = None
               ):
        """Start infusion at the specified rate and duration.

        If pump_rate_ml_mn is None, will use the currently set rate on the pump.
        If duration_s is None, will infuse indefinitely until stop() is called.
        """
        if pump_rate_ml_mn is not None:
            if pump_rate_ml_mn <= 0:
                raise ValueError(
                    "pump_rate_ml_mn must be positive when provided.")
            self.set_rate(pump_rate_ml_mn, "ml/mn")
            effective_rate_ml_mn = pump_rate_ml_mn
        else:
            current_rate, current_unit = self.get_rate()
            if current_unit == "ml/mn":
                effective_rate_ml_mn = current_rate
            elif current_unit == "ul/mn":
                effective_rate_ml_mn = current_rate / 1000.0
            elif current_unit == "ml/hr":
                effective_rate_ml_mn = current_rate / 60.0
            elif current_unit == "ul/hr":
                effective_rate_ml_mn = current_rate / 60000.0
            else:
                raise ValueError(
                    f"Unknown pump rate unit returned by pump: {current_unit}")

        if duration_s is not None and duration_s <= 0:
            raise ValueError("duration_s must be positive when provided.")

        if duration_s is None:
            print(
                f"SyringePump is infusing at {effective_rate_ml_mn} mL/min indefinitely")
            self.run()
            return
        else:
            print(
                f"SyringePump infusing at {effective_rate_ml_mn} mL/min for {duration_s} s")
            self.run()
            time.sleep(duration_s)
            self.stop()


if __name__ == "__main__":
    # Small testing script
    pump = SyringePump(syringe_volume_ml=2.5)
    pump.infuse(0.2, 2)

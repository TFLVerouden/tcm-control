"""
TCP socket client for the TSI Model 3330 Optical Particle Sizer (OPS).

Protocol summary (from the OPS 3330 manual, Appendix D "Using Serial Data
Commands"):
    - The instrument exposes an ASCII command protocol over a TCP/IP socket
      on port 3602.
    - Over USB this socket is reached through TSI's NDIS virtual-network
      driver (installed from the Aerosol Instrument Manager disc, Windows
      only). Once installed, Windows assigns the OPS a (static) IP address
      that you read off the unit's Communications screen. Over Ethernet the
      same protocol is used directly against the unit's Ethernet IP.
    - Every command is a plain ASCII string terminated with a carriage
      return ("\\r"). The instrument replies with either the requested data,
      "OK", or "ERROR"/"FAIL".
    - There is no remote "power on" command -- the unit must already be
      booted for the socket to exist at all. MSTART/MSTOP start and stop a
      *measurement* (this is what this project uses for "turn on/off").
      MSHUTDOWN fully powers the instrument down and is exposed separately
      as `shutdown()` since it's a more drastic action.

IMPORTANT: If the OPS is already connected to another PC over USB, it must
be power-cycled before it will accept a USB connection from a different PC
(explicitly called out in the manual).
"""

from __future__ import annotations

import socket
import time
import logging
from dataclasses import dataclass
from typing import Optional
from xmlrpc import client

logger = logging.getLogger("ops3330")

DEFAULT_PORT = 3602
DEFAULT_TIMEOUT = 5.0          # seconds, socket connect/recv timeout
DEFAULT_IDLE_GAP = 0.25        # seconds of silence that marks "reply finished"


class OPSError(Exception):
    """Raised when the OPS returns ERROR/FAIL, or a connection problem occurs."""


class OPSClient:
    """A small TCP client implementing the OPS 3330 ASCII command protocol."""

    def __init__(
        self,
        ip: str,
        port: int = DEFAULT_PORT,
        timeout: float = DEFAULT_TIMEOUT,
        idle_gap: float = DEFAULT_IDLE_GAP,
    ):
        self.ip = ip
        self.port = port
        self.timeout = timeout
        self.idle_gap = idle_gap
        self._sock: Optional[socket.socket] = None

    # ------------------------------------------------------------------ #
    # Connection management
    # ------------------------------------------------------------------ #
    def connect(self) -> None:
        logger.info("Connecting to OPS at %s:%s", self.ip, self.port)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect((self.ip, self.port))
        self._sock = sock
        logger.info("Connected.")

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None
            logger.info("Connection closed.")

    def __enter__(self) -> "OPSClient":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    @property
    def connected(self) -> bool:
        return self._sock is not None

    # ------------------------------------------------------------------ #
    # Low-level command / response
    # ------------------------------------------------------------------ #
    def send_raw(self, command: str) -> str:
        """
        Send one command string (CR appended automatically) and return the
        raw decoded reply (whitespace-stripped, CRs preserved internally
        for multi-line replies like RMMEAS).
        """
        if self._sock is None:
            raise OPSError("Not connected. Call connect() first.")

        payload = (command.strip() + "\r").encode("ascii")
        logger.debug("-> %r", payload)
        # print(f">>> SENDING: {payload!r}")
        self._sock.sendall(payload)

        # Read until we hit a gap with no new data -- the manual does not
        # document an explicit reply terminator, so we treat "no more bytes
        # for `idle_gap` seconds" as end-of-reply.
        chunks = []
        self._sock.settimeout(self.timeout)
        try:
            first = self._sock.recv(4096)
        except socket.timeout:
            raise OPSError(f"No response from OPS for command: {command!r}")
        if not first:
            raise OPSError("Connection closed by OPS.")
        chunks.append(first)

        self._sock.settimeout(self.idle_gap)
        while True:
            try:
                more = self._sock.recv(4096)
                if not more:
                    break
                chunks.append(more)
            except socket.timeout:
                break

        self._sock.settimeout(self.timeout)
        reply = b"".join(chunks).decode("ascii", errors="replace").strip()
        logger.debug("<- %r", reply)

        if reply.upper() in ("ERROR", "FAIL") or reply.upper().startswith("ERROR"):
            raise OPSError(f"OPS rejected command {command!r}: {reply!r}")

        return reply

    def command(self, *parts) -> str:
        """
        Build a command from parts (command name + comma-separated
        parameters) and send it. Example:
            client.command("WMODEALARM", 1, 0, 0, 1, 4000.0)
            -> sends "WMODEALARM 1,0,0,1,4000.0\\r"
        """
        if len(parts) == 1:
            return self.send_raw(str(parts[0]))
        name, *params = parts
        param_str = ",".join(_fmt(p) for p in params)
        return self.send_raw(f"{name} {param_str}")

    # ------------------------------------------------------------------ #
    # Instrument info
    # ------------------------------------------------------------------ #
    def read_model_number(self) -> str:
        return self.command("RDMN")

    def read_serial_number(self) -> str:
        return self.command("RDSN")

    def read_firmware_version(self) -> str:
        return self.command("RDBS")

    def read_status(self) -> str:
        """MSTATUS -- returns e.g. 'Idle', 'Running', 'Ready', ..."""
        return self.command("MSTATUS")

    def read_calibration_date(self) -> str:
        return self.command("RSCALDATE")

    def read_datetime(self) -> str:
        return self.command("RSDATETIME")

    def write_datetime(self, dt) -> str:
        """dt: a datetime.datetime instance -> sets the instrument clock."""
        s = f"{dt.month}/{dt.day}/{dt.year},{dt.hour}:{dt.minute}:{dt.second}"
        return self.send_raw(f"WSDATETIME {s}")

    # ------------------------------------------------------------------ #
    # Measurement control ("turn on/off" a measurement)
    # ------------------------------------------------------------------ #
    def start_measurement(self) -> str:
        """MSTART -- begin sampling/logging per the currently loaded setup."""
        # return self.command("MSTART")

        import time

        def wait_until_idle(client, timeout=10, poll_interval=0.3):
            start = time.time()
            while time.time() - start < timeout:
                status = client.command("MSTATUS")  # or however your client exposes this
                if "Idle" in status:
                    return True
                time.sleep(poll_interval)
            return False

        # after MUPDATE:
        if wait_until_idle(self):
            # Let the user start the measurement by pressing Enter
            print("Enter y/n to start/exit the measurement...\n")
            user_input = input()  # Wait for user input
            if user_input.strip().lower() == "y":
                print("Starting the measurement...")
            elif user_input.strip().lower() == "n":
                print("Exiting without starting the measurement.")
                return "Measurement not started."
            else:
                print("Invalid input. Exiting without starting the measurement.")
                return "Measurement not started."            
            return self.command("MSTART")
        else:
            print("Instrument never returned to Idle before timeout")

    def stop_measurement(self) -> str:
        """MSTOP -- stop the current measurement."""
        return self.command("MSTOP")

    def start_pump_only(self) -> str:
        """MSTARTPUMP -- start flow/pump without counting particles."""
        return self.command("MSTARTPUMP")

    def stop_counting(self) -> str:
        """MSTOPBIN -- stop counting but keep pump/flow running."""
        return self.command("MSTOPBIN")

    def start_counting(self) -> str:
        """MBIN -- (re)start counting particles."""
        return self.command("MBIN")

    def buzzer_off(self) -> str:
        return self.command("MBUZZEROFF")

    def lock(self, name: str) -> str:
        """MLOCK <=12-char string> -- lock the unit to this PC only."""
        return self.send_raw(f"MLOCK {name[:12]}")

    def unlock(self) -> str:
        return self.command("MUNLOCK")

    def shutdown(self) -> str:
        """MSHUTDOWN -- fully power down the instrument. Use with care."""
        return self.command("MSHUTDOWN")

    def commit(self) -> str:
        """
        MUPDATE -- apply all pending W... (write) commands. Must be called
        after any WMODE*/WS* command for the change to take effect.
        """
        return self.command("MUPDATE")

    # ------------------------------------------------------------------ #
    # Live / logged measurement data
    # ------------------------------------------------------------------ #
    def read_live_bins(self) -> str:
        return self.command("RMBINS")

    def read_logged_bins(self) -> str:
        return self.command("RMLOGGEDBINS")

    def read_live_measurement(self) -> str:
        return self.command("RMMEAS")

    def read_logged_measurement(self) -> str:
        return self.command("RMLOGGEDMEAS")

    def read_raw_bins(self) -> str:
        return self.command("RMRAWBINS")

    def read_unit_measurements(self) -> str:
        return self.command("RMUNITMEAS")

    def read_messages(self) -> str:
        return self.command("RMMESSAGES")

    def read_log_info(self) -> str:
        return self.command("RMLOGINFO")

    def read_memory_info(self) -> str:
        return self.command("RMMEMORY")

    def read_control(self) -> str:
        return self.command("RMCONTROL")

    # ------------------------------------------------------------------ #
    # Setup: channels / bins
    # ------------------------------------------------------------------ #
    def read_channel_setup(self) -> str:
        return self.command("RMODECHSETUP")

    def write_channel_setup(self, cut_points_um: list[float]) -> str:
        """
        cut_points_um: N+1 cut points defining N channels (N = 1..16), e.g.
        the factory-default 16-channel table has 17 cut points from 0.3 to
        10.0 um. Sends WMODECHSETUP <n_channels>,<cut1>,...,<cutN+1>.
        """
        n_channels = len(cut_points_um) - 1
        if not (1 <= n_channels <= 16):
            raise ValueError("cut_points_um must define between 1 and 16 channels")
        return self.command("WMODECHSETUP", n_channels, *cut_points_um)

    # ------------------------------------------------------------------ #
    # Setup: logging
    # ------------------------------------------------------------------ #
    def read_log_setup(self) -> str:
        return self.command("RMODELOG")

    def write_log_setup(
        self,
        start_time: str,
        start_date: str,
        sample_interval: str,
        number_of_samples: int,
        number_of_sets: int,
        repeat_interval: str,
        use_start_time: bool,
        use_start_date: bool,
        logging_enabled: bool,
        log_to_single_file: bool,
        survey_mode: bool,
        keep_pump_running: bool,
    ) -> str:
        """
        start_time: "H:M"; start_date: "M/D/Y"; sample_interval: "H:M:S"
        (1-86400 sec total); repeat_interval: "D:H:M" (1-144000 min total).
        """
        return self.send_raw(
            "WMODELOG "
            f"{start_time},{start_date},{sample_interval},"
            f"{int(number_of_samples)},{int(number_of_sets)},{repeat_interval},"
            f"{_fmt(use_start_time)},{_fmt(use_start_date)},{_fmt(logging_enabled)},"
            f"{_fmt(log_to_single_file)},{_fmt(survey_mode)},{_fmt(keep_pump_running)}"
        )

    # ------------------------------------------------------------------ #
    # Setup: alarm
    # ------------------------------------------------------------------ #
    def read_alarm_setup(self) -> str:
        return self.command("RMODEALARM")

    def write_alarm_setup(
        self, visible: bool, audible: bool, relay: bool, measurement_is_dn: bool, threshold: float
    ) -> str:
        return self.command("WMODEALARM", visible, audible, relay, measurement_is_dn, threshold)

    # ------------------------------------------------------------------ #
    # Setup: analog output
    # ------------------------------------------------------------------ #
    def read_analog_setup(self) -> str:
        return self.command("RMODEANALOG")

    def write_analog_setup(self, state: int, measurement_is_dn: bool, minimum: float, maximum: float) -> str:
        """state: 0=off, 1=0-5V, 2=4-20mA"""
        return self.command("WMODEANALOG", state, measurement_is_dn, minimum, maximum)

    # ------------------------------------------------------------------ #
    # Setup: user calibration
    # ------------------------------------------------------------------ #
    def read_user_cal(self) -> str:
        return self.command("RMODEUSERCAL")

    def write_user_cal(
        self,
        enabled: bool,
        dead_time_correction: bool,
        density: float,
        refractive_index_real: float,
        refractive_index_imag: float,
        shape_correction_factor: float,
    ) -> str:
        return self.command(
            "WMODEUSERCAL",
            enabled,
            dead_time_correction,
            density,
            refractive_index_real,
            refractive_index_imag,
            shape_correction_factor,
        )

    # ------------------------------------------------------------------ #
    # Setup: flow calibration
    # ------------------------------------------------------------------ #
    def read_flow_cal(self) -> str:
        return self.command("RMODEFLOWCAL")

    def write_flow_cal(self, user_flow_cal: float, external_flow_control: bool) -> str:
        return self.command("WMODEFLOWCAL", user_flow_cal, external_flow_control)

    # ------------------------------------------------------------------ #
    # Protocols (named setting sets stored on the instrument)
    # ------------------------------------------------------------------ #
    def read_protocol(self, index: int) -> str:
        return self.command("RMODEPROTOCOL", index)

    def save_current_as_protocol(self, name: str) -> str:
        return self.send_raw(f"WMODEPROTOCOL {name[:12]}")

    def read_current_protocol(self) -> str:
        return self.command("RMODECURPROTOCOL")

    def select_protocol(self, index: int) -> str:
        return self.command("WMODECURPROTOCOL", index)

    def read_protocol_names(self, start_index: int) -> str:
        return self.command("RMODENAMESPROTOCOL", start_index)

    def delete_protocol(self, index: int) -> str:
        if not (7 <= index <= 16):
            raise ValueError("Only protocol slots 7-16 are user-deletable per the manual")
        return self.command("WMODEDELETEPROTOCOL", index)


def _fmt(value) -> str:
    """Format a Python value the way the OPS expects it on the wire."""
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)

import contextlib
import os
import time
from pathlib import Path
from typing import Optional

from dvg_devices.BaseDevice import SerialDevice
from tcm_utils.file_dialogs import (
    read_repo_config_value,
    write_repo_config_value,
)

CONNECTIONS_FILENAME = "connections.ini"
COM_PORTS_SECTION = "com_ports"


class PoFSerialDevice(SerialDevice):
    def __init__(
        self,
        name: str,
        long_name: str,
        expected_id: str,
        baudrate: int = 115200,
        timeout: float = 1,
        debug: bool = False,
        echo: bool = False,
    ):
        super().__init__(name=name, long_name=long_name)
        self._debug = debug
        self._echo_default = echo
        self.serial_settings["baudrate"] = baudrate
        self.serial_settings["timeout"] = timeout

        def id_query() -> tuple[str, None]:
            _success, reply = self.query("id?")
            if isinstance(reply, str):
                reply_broad = reply.strip()
            else:
                reply_broad = ""
            return reply_broad, None

        self.set_ID_validation_query(
            ID_validation_query=id_query,
            valid_ID_broad=expected_id,
        )

        # Auto connect to device; suppress print of connection attempts
        if debug:
            connected = self.auto_connect(
                filepath_last_known_port=CONNECTIONS_FILENAME
            )
        else:
            with (
                open(os.devnull, "w") as devnull,
                contextlib.redirect_stdout(devnull),
                contextlib.redirect_stderr(devnull),
            ):
                connected = self.auto_connect(
                    filepath_last_known_port=CONNECTIONS_FILENAME
                )

        if not connected:
            raise SystemError(
                f"Serial device {name} not found via auto_connect")
        else:
            # Drain any boot/session leftovers before issuing new commands.
            pending = self._read_lines(timeout=0.5)
            if pending:
                if self._debug:
                    for line in pending:
                        print(f"[{self.name}] {line}")
                self._check_errors(pending, raise_on_error=True)
            print(f"Connected to serial device {name} at {self.ser.port}")

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------
    def _read_lines(self, timeout: float = 0.2) -> list[str]:
        # Drain any pending serial lines within the timeout window.
        lines: list[str] = []
        start = time.time()
        while (time.time() - start) < timeout:
            if self.ser is not None and self.ser.in_waiting > 0:
                success, line = self.readline()
                if success and isinstance(line, str):
                    lines.append(line)
            else:
                time.sleep(0.02)
        return lines

    def _check_errors(self, lines: list[str], raise_on_error: bool) -> bool:
        # Detect MCU error lines and optionally raise.
        for line in lines:
            if line.startswith("ERROR"):
                if raise_on_error and not self._debug:
                    raise RuntimeError(line)
                return False
        return True

    def _resolve_echo(self, echo: Optional[bool]) -> bool:
        return self._echo_default if echo is None else echo

    def _query_and_drain(
        self,
        cmd: Optional[str],
        expected: Optional[str] = None,
        expected_prefix: Optional[str] = None,
        raise_on_error: bool = True,
        echo: Optional[bool] = None,
        extra_timeout: float = 0.2,
    ) -> tuple[Optional[str], list[str]]:
        # Issue a query (optional), collect additional lines, and validate responses.
        reply: Optional[str] = None
        lines: list[str] = []
        echo = self._resolve_echo(echo)
        if cmd:
            success, reply = self.query(cmd, raises_on_timeout=True)
            if not success:
                raise RuntimeError(f"Query failed: {cmd}")
            if isinstance(reply, str):
                lines.append(reply)
        lines.extend(self._read_lines(timeout=extra_timeout))

        if echo:
            for line in lines:
                print(f"[{self.name}] {line}")

        self._check_errors(lines, raise_on_error=raise_on_error)

        if not self._debug:
            matched: Optional[str] = None
            if expected is not None:
                for line in lines:
                    if line == expected:
                        matched = line
                        break
            elif expected_prefix is not None:
                for line in lines:
                    if line.startswith(expected_prefix):
                        matched = line
                        break

            if matched is not None:
                reply = matched

            if expected is not None and reply != expected:
                raise RuntimeError(
                    f"Unexpected reply to {cmd}: {reply!r} (expected {expected!r})"
                )
            if expected_prefix is not None and (
                not isinstance(reply, str) or not reply.startswith(
                    expected_prefix)
            ):
                raise RuntimeError(
                    f"Unexpected reply to {cmd}: {reply!r} "
                    f"(expected prefix {expected_prefix!r})"
                )

        return reply if isinstance(reply, str) else None, lines

    # ------------------------------------------------------------------
    # SerialDevice storage customization
    # ------------------------------------------------------------------
    def _get_last_known_port(self, path: Path):
        return read_repo_config_value(
            self.name,
            filename=CONNECTIONS_FILENAME,
            section=COM_PORTS_SECTION,
        )

    def _store_last_known_port(self, path: Path, port_str: str) -> bool:
        write_repo_config_value(
            self.name,
            port_str,
            filename=CONNECTIONS_FILENAME,
            section=COM_PORTS_SECTION,
        )
        return True

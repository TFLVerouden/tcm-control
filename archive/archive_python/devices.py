from __future__ import annotations

import time
from typing import Iterable, Optional

import serial
import serial.tools.list_ports

from dvg_devices.BaseDevice import SerialDevice
from tcm_utils.file_dialogs import repo_config_path


def find_serial_device(description: str, continue_on_error: bool = False) -> str | None:
    ports = list(serial.tools.list_ports.comports())
    ports.sort(key=lambda port: int(port.device.replace("COM", "")))

    matching_ports = [
        port.device for port in ports if description in port.description
    ]

    if len(matching_ports) == 1:
        return matching_ports[0]
    if len(matching_ports) > 1:
        print(f'Multiple matching devices found for "{description}":')
        for idx, port in enumerate(ports):
            print(f"{idx + 1}. {port.device} - {port.description}")
        choice = input(f'Select the device number for "{description}": ')
        return matching_ports[int(choice) - 1]

    if continue_on_error:
        return None

    print(f'No matching devices found for "{description}". Available devices:')
    for port in ports:
        print(f"{port.device} - {port.description}")
    choice = input(f'Enter the COM port number for "{description}": COM')
    return f"COM{choice}"


def create_serial_device(
    baudrate: int,
    timeout: float,
    name: str,
    expected_id: str,
    display_name: Optional[str] = None,
    id_query_cmds: str | Iterable[str] = "id?",
    boot_delay_sec: float = 0.5,
    status_flush_sec: float = 0.5,
    query_wait_time: float = 0.2,
) -> SerialDevice:
    device = SerialDevice(name=name, long_name=display_name or expected_id)
    device.serial_settings["baudrate"] = baudrate
    device.serial_settings["timeout"] = timeout
    device.set_read_termination(None, query_wait_time=query_wait_time)

    def id_query() -> tuple[str, Optional[str]]:
        time.sleep(boot_delay_sec)
        if device.ser is not None:
            device.ser.reset_input_buffer()
            time.sleep(status_flush_sec)
            device.ser.read_all()

        commands = [id_query_cmds] if isinstance(
            id_query_cmds, str) else list(id_query_cmds)
        for cmd in commands:
            try:
                _success, reply = device.query(cmd)
            except Exception:
                reply = None

            if isinstance(reply, str):
                reply_clean = reply.strip()
                if expected_id in reply_clean:
                    return expected_id, None
                return reply_clean, None

        return "", None

    device.set_ID_validation_query(
        ID_validation_query=id_query,
        valid_ID_broad=expected_id,
        valid_ID_specific=None,
    )

    return device


def connect_serial_device(
    device: SerialDevice,
    com_port: Optional[str] = None,
    last_port_key: Optional[str] = None,
    debug: bool = False,
) -> None:
    if com_port:
        if debug:
            print(f"Connecting to {device.name} on {com_port}...")
        if not device.connect_at_port(com_port):
            raise SystemError(f"Device not found at {com_port}")
        return

    if last_port_key is not None:
        last_port_path = repo_config_path(last_port_key)
        if device.auto_connect(filepath_last_known_port=str(last_port_path)):
            return
    if debug:
        ports = list(serial.tools.list_ports.comports())
        ports.sort(key=lambda port: int(port.device.replace("COM", "")))
        print(
            "Available ports: "
            + ", ".join(f"{port.device} ({port.description})" for port in ports)
        )
    if not device.scan_ports():
        raise SystemError("Device not found via scan")


def read_ser_response(device: SerialDevice, timeout=1.0):
    """Read all available serial responses with timeout."""
    responses = []
    start_time = time.time()

    while (time.time() - start_time) < timeout:
        if device.ser.in_waiting > 0:
            try:
                success, line = device.readline()
                if success:
                    responses.append(line)
            except Exception as e:
                print(f"Error reading response: {e}")
                break
        time.sleep(0.05)  # Small delay to prevent busy-waiting

    return responses if responses else ["(no response)"]


class SprayTecLift:
    def __init__(self, ser: serial.Serial):
        self.ser = ser
        print(f"Connected to SprayTec lift on {ser.port}")

    def get_height(self) -> float | None:
        try:
            self.ser.write(b"?\n")
            response = self.ser.readlines()
            for line in response:
                if line.startswith(b"  Platform height [mm]: "):
                    height = line.split(b": ")[1].strip().decode(
                        "utf-8", errors="ignore"
                    )
                    return float(height)
            print(
                'Warning: No valid response containing "Platform height [mm]" was found.'
            )
            return None
        except Exception as exc:
            print(f"Error while reading lift height: {exc}")
            return None

    def close_connection(self) -> None:
        self.ser.close()
        print("Lift connection closed.")

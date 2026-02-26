from typing import Optional

from .base import PoFSerialDevice


class SprayTecLift(PoFSerialDevice):
    def __init__(
        self,
        name: str = "SprayTec_Lift",
        long_name: str = "SprayTec lift controller",
        expected_id: str = "Arduino_MEGA_2560",
        baudrate: int = 9600,
        boot_drain_s: float = 2,
        **kwargs,
    ):
        super().__init__(
            name=name,
            long_name=long_name,
            expected_id=expected_id,
            baudrate=baudrate,
            boot_drain_s=boot_drain_s,
            **kwargs,
        )

    def get_height(
        self, *, echo: Optional[bool] = None, timeout: float = 2.0
    ) -> Optional[float]:
        _reply, lines = self._query_and_drain(
            "?", echo=echo, extra_timeout=timeout)
        prefix = "Platform height [mm]: "
        for line in lines:
            if line.startswith(prefix):
                try:
                    return float(line.split(": ", 1)[1].strip())
                except (IndexError, ValueError):
                    return None
        return None

    def read_status(
        self, *, echo: Optional[bool] = None, timeout: float = 2.0
    ) -> list[str]:
        _reply, lines = self._query_and_drain(
            "?", echo=echo, extra_timeout=timeout)
        return lines

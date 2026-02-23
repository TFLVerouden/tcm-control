from typing import Optional

from .base import PoFSerialDevice


class SprayTecLift(PoFSerialDevice):
    def __init__(
        self,
        name: str = "SprayTecLift",
        long_name: str = "SprayTec lift controller",
        expected_id: str = "Arduino_MEGA_2560",
        **kwargs,
    ):
        super().__init__(
            name=name,
            long_name=long_name,
            expected_id=expected_id,
            **kwargs,
        )

    def get_height(self) -> Optional[float]:
        reply, _lines = self._query_and_drain(
            "?", expected_prefix="  Platform height [mm]: ", echo=False
        )
        if reply is None:
            return None
        try:
            return float(reply.split(": ")[1].strip())
        except (IndexError, ValueError):
            return None

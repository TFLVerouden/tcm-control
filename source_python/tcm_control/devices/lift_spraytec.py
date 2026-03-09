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

    def get_lift_height(
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

    def get_spraytec_height(self,
                            tcm_trachea_bottom_z_mm: float,
                            tcm_trachea_height_mm: float,
                            lift_zero_z_mm: float,
                            table_height_mm: float,
                            spraytec_to_lift_z_mm: float) -> tuple[Optional[float], Optional[float]]:
        """Calculate the height of the SprayTec measurement volume based on the lift height and known geometry.
        The height is calculated as:
            SprayTec height = lift height + lift zero + spraytec offset
                            - trachea bottom - (trachea height / 2)
        """
        # Get the height of the measurement volume of the SprayTec
        lift_height = self.get_lift_height()
        if lift_height is None:
            raise RuntimeError(
                "Failed to get lift height, cannot calculate SprayTec height.")

        return ((lift_height + lift_zero_z_mm + spraytec_to_lift_z_mm
                - table_height_mm - tcm_trachea_bottom_z_mm - tcm_trachea_height_mm), lift_height)

    def read_status(
        self, *, echo: Optional[bool] = None, timeout: float = 2.0
    ) -> list[str]:
        _reply, lines = self._query_and_drain(
            "?", echo=echo, extra_timeout=timeout)
        return lines

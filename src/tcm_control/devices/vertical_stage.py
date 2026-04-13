import time
from typing import Optional

from .base import PoFSerialDevice


class VerticalStage(PoFSerialDevice):
    def __init__(
        self,
        name: str = "vertical_stage",
        long_name: str = "SprayTec vertical stage controller",
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

    def set_lift_height(
        self,
        height_mm: float,
        *,
        wait_for_target: bool = True,
        tolerance_mm: float = 0.1,
        timeout_s: float = 15.0,
        poll_interval_s: float = 0.2,
        echo: Optional[bool] = None,
    ) -> Optional[float]:
        """Move lift to absolute height in mm via command syntax ``m#.###``.

        Returns the final measured height when available. If ``wait_for_target`` is
        False, this performs a fire-and-forget command and returns ``None``.
        """
        if height_mm < 0:
            raise ValueError("height_mm must be >= 0")
        if tolerance_mm < 0:
            raise ValueError("tolerance_mm must be >= 0")
        if timeout_s <= 0:
            raise ValueError("timeout_s must be > 0")
        if poll_interval_s <= 0:
            raise ValueError("poll_interval_s must be > 0")

        cmd = f"m{float(height_mm):.3f}"
        self._query_and_drain(cmd, echo=echo, extra_timeout=0.4)

        if not wait_for_target:
            return None

        start = time.time()
        last_height: Optional[float] = None
        while (time.time() - start) < timeout_s:
            measured = self.get_lift_height(echo=echo, timeout=poll_interval_s)
            if measured is None:
                continue

            last_height = measured
            if abs(measured - height_mm) <= tolerance_mm:
                return measured

        raise RuntimeError(
            "Lift did not reach target height within timeout. "
            f"Target={height_mm:.3f} mm, "
            f"last_measured={last_height!r} mm"
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

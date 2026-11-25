"""Coordinate the pump and camera while creating a thin film."""

import time

from tcm_control.devices.camera import Camera
from tcm_control.devices.cough_machine import CoughMachine
from tcm_control.devices.syringe_pump import SyringePump
from tcm_control.imaging import LayerPreview, take_snapshot, wait_with_preview
from tcm_utils.io_utils import wait_with_progress


def make_liquid_film(
    pump: SyringePump,
    camera: Camera,
    tcm: CoughMachine,
    infuse_volume_ml: float,
    infuse_rate_ml_min: float,
    withdraw_volume_ml: float,
    withdraw_rate_ml_min: float,
    settling_time_s: float,
    *,
    filename_prefix: str = "film",
    preview: LayerPreview | None = None,
) -> None:
    """Infuse, settle and withdraw, saving a snapshot after each step."""
    update = preview.update if preview is not None else None

    # Helper function to create snapshot with specific name
    def snapshot(step: str) -> None:
        take_snapshot(
            camera, tcm, filename=f"{filename_prefix}_after_{step}",
            leave_light_on=preview is not None and preview.active,
        )

    # Infuse
    if not pump.infuse(
        volume_ml=infuse_volume_ml,
        rate_ml_min=infuse_rate_ml_min,
        update=update,
    ):
        raise RuntimeError("Layer creation aborted: infusion failed.")
    snapshot("infusion")

    # Wait for layer to settle
    if preview is None:
        wait_with_progress(wait_s=settling_time_s,
                           label="Waiting for layer to settle...",
                           )
    else:
        wait_with_preview(settling_time_s, preview)
    snapshot("settling")

    # Withdraw
    if not pump.withdraw(
        volume_ml=withdraw_volume_ml,
        rate_ml_min=withdraw_rate_ml_min,
        update=update,
    ):
        raise RuntimeError("Layer creation aborted: withdrawal failed.")
    snapshot("withdrawal")

    # Settle again
    if preview is None:
        wait_with_progress(wait_s=settling_time_s,
                           label="Waiting for layer to settle...",
                           )
    else:
        wait_with_preview(settling_time_s, preview)

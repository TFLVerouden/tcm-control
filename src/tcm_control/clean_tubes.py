"""Tube-cleaning protocol combining syringe-pump and cough-machine steps."""

from typing import Any

from tcm_control.devices.camera import Camera
from tcm_control.devices.cough_machine import CoughMachine
from tcm_control.devices.syringe_pump import SyringePump
from tcm_control.clean_channel import clean_channel
from tcm_control.liquid_film import make_liquid_film
from tcm_utils.io_utils import prompt_yes_no


def clean_tubes(
    pump: SyringePump,
    camera: Camera,
    tcm: CoughMachine,
    tube_cleaning_inputs: dict[str, Any],
    layer_inputs: dict[str, Any],
    cleaning_inputs: dict[str, Any],
) -> None:
    """Run the configured syringe-pump and cough-machine tube-cleaning steps."""
    # If no cleaning cycles are configured, there is no use for this
    if cleaning_inputs["cycle_count"] == 0:
        print("No cleaning cycles configured, skipping tube cleaning.")
        return

    try:
        volume_ml_layer = tube_cleaning_inputs["volume_ml_layer"]
        rate_ml_min_layer = tube_cleaning_inputs["rate_ml_min_layer"]
        volume_ml_repetition = tube_cleaning_inputs["volume_ml_repetition"]
        rate_ml_min_repetition = tube_cleaning_inputs["rate_ml_min_repetition"]
        repetitions = tube_cleaning_inputs["repetitions"]

        if repetitions > 0 and (
            volume_ml_repetition is None or rate_ml_min_repetition is None
        ):
            raise ValueError(
                "Repetition volume and rate are required when cleaning repetitions are enabled.")

        required_volume_ml = max(
            volume_ml_layer, volume_ml_repetition or 0)
        if prompt_yes_no(
            "Press ENTER to confirm the syringe is filled with > "
            f"{required_volume_ml} mL...",
            default=True,
        ):
            print(
                f"Infusing {volume_ml_layer} mL at {rate_ml_min_layer} mL/min to create fluid layer")
            pump.infuse(
                volume_ml=volume_ml_layer,
                rate_ml_min=rate_ml_min_layer,
                log_info=False,
            )

            if repetitions > 0:
                assert volume_ml_repetition is not None
                assert rate_ml_min_repetition is not None
                try:
                    for i in range(repetitions):
                        print(
                            f"{'\r' if i else ''}Infuse/withdraw at {volume_ml_repetition} mL and "
                            f"{rate_ml_min_repetition} mL/min, repetition "
                            f"{i + 1}/{repetitions}",
                            end="",
                            flush=True,
                        )
                        pump.withdraw(
                            volume_ml=volume_ml_repetition,
                            rate_ml_min=rate_ml_min_repetition,
                            log_info=False,
                        )
                        pump.infuse(
                            volume_ml=volume_ml_repetition,
                            rate_ml_min=rate_ml_min_repetition,
                            log_info=False,
                        )
                finally:
                    print()
            else:
                print("SyringePump config has no clean_tube steps")
    except Exception as exc:
        print(f"SyringePump ERROR: {exc}")
        raise

    # Clear residual liquid from the plate
    clean_channel(
        tcm,
        clean_pressure_bar=cleaning_inputs["clean_pressure_bar"],
        clean_valve_open_duration_s=cleaning_inputs["valve_open_duration_s"],
        clean_cycle_count=1,
        redo_on_request=False,
    )

    # Form a layer to level the liquid in the tubes before the first run
    make_liquid_film(
        pump,
        camera,
        tcm,
        infuse_volume_ml=layer_inputs["infuse_volume_ml"],
        infuse_rate_ml_min=layer_inputs["infuse_rate_ml_min"],
        withdraw_volume_ml=layer_inputs["withdraw_volume_ml"],
        withdraw_rate_ml_min=layer_inputs["withdraw_rate_ml_min"],
        settling_time_s=layer_inputs["film_settling_time_s"],
        save_snapshots=False,
    )

    # Clean and dry the channel after leveling the liquid.
    clean_channel(
        tcm,
        camera=camera,
        clean_pressure_bar=cleaning_inputs["clean_pressure_bar"],
        clean_valve_open_duration_s=cleaning_inputs["valve_open_duration_s"],
        clean_cycle_count=cleaning_inputs["cycle_count"],
        dry_pressure_bar=cleaning_inputs["dry_pressure_bar"],
        dry_duration_s=cleaning_inputs["dry_duration_s"],
        dry_valve_current_ma=cleaning_inputs["dry_valve_current_ma"],
        redo_on_request=False
    )

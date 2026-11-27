"""Channel cleaning, drying and optional operator inspection."""

import time
from typing import Optional, TYPE_CHECKING

from tcm_control.devices.cough_machine import (
    CoughMachine, MAX_PRESSURE_BAR, DEFAULT_CLEAN_PRESSURE_BAR,
    DEFAULT_CLEAN_VALVE_OPEN_DURATION_S, DEFAULT_CLEAN_CYCLE_COUNT,
    DEFAULT_CLEAN_DRY_DURATION_S, DEFAULT_CLEAN_DRY_VALVE_CURRENT_MA,
    DEFAULT_SETTLE_TIMEOUT_S, DEFAULT_SETTLE_AVG_WINDOW_S,
    DEFAULT_SETTLE_TOLERANCE_BAR, DEFAULT_SETTLE_POLL_INTERVAL_S,
)
from tcm_utils.io_utils import countdown_beep, make_minimal_progress_bar, prompt_yes_no

if TYPE_CHECKING:
    from tcm_control.devices.camera import Camera


def clean_channel(
    tcm: CoughMachine,
    *,
    clean_pressure_bar: float = DEFAULT_CLEAN_PRESSURE_BAR,
    clean_valve_open_duration_s: float = DEFAULT_CLEAN_VALVE_OPEN_DURATION_S,
    clean_cycle_count: int = DEFAULT_CLEAN_CYCLE_COUNT,
    dry_pressure_bar: float | None = None,
    dry_duration_s: float = DEFAULT_CLEAN_DRY_DURATION_S,
    dry_valve_current_ma: float = DEFAULT_CLEAN_DRY_VALVE_CURRENT_MA,
    settle_timeout_s: float = DEFAULT_SETTLE_TIMEOUT_S,
    settle_avg_window_s: float = DEFAULT_SETTLE_AVG_WINDOW_S,
    settle_tolerance_bar: float = DEFAULT_SETTLE_TOLERANCE_BAR,
    settle_poll_interval_s: float = DEFAULT_SETTLE_POLL_INTERVAL_S,
    echo: Optional[bool] = None,
    camera: Optional["Camera"] = None,
    redo_on_request: bool = True,
) -> None:
    """Clean and dry the channel, optionally showing images and repeating."""
    attempt = 0
    while True:
        _clean_once(
            tcm,
            clean_pressure_bar=clean_pressure_bar,
            clean_valve_open_duration_s=clean_valve_open_duration_s,
            clean_cycle_count=clean_cycle_count,
            dry_pressure_bar=dry_pressure_bar,
            dry_duration_s=dry_duration_s,
            dry_valve_current_ma=dry_valve_current_ma,
            settle_timeout_s=settle_timeout_s,
            settle_avg_window_s=settle_avg_window_s,
            settle_tolerance_bar=settle_tolerance_bar,
            settle_poll_interval_s=settle_poll_interval_s,
            echo=echo,
        )
        if clean_cycle_count == 0 and dry_duration_s == 0:
            return
        attempt += 1
        if camera is not None:
            _show_cleaned_channel(camera, tcm, attempt)
        if not redo_on_request or prompt_yes_no(
            "Is the channel clean? [y/N] (no repeats cleaning):", default=False
        ):
            return


def _show_cleaned_channel(camera: "Camera", tcm: CoughMachine, attempt: int) -> None:
    import matplotlib.pyplot as plt
    import tifffile

    from tcm_control.imaging import take_snapshot

    image_path = take_snapshot(camera, tcm, filename=f"cleaned_channel_{attempt}")
    fig, ax = plt.subplots()
    try:
        ax.imshow(tifffile.imread(image_path), cmap="gray")
        ax.set_title("Cleaned channel - close window to continue")
        ax.axis("off")
        plt.show(block=True)
    finally:
        plt.close(fig)


def _clean_once(
    tcm: CoughMachine,
    *,
    clean_pressure_bar: float = DEFAULT_CLEAN_PRESSURE_BAR,
    clean_valve_open_duration_s: float = DEFAULT_CLEAN_VALVE_OPEN_DURATION_S,
    clean_cycle_count: int = DEFAULT_CLEAN_CYCLE_COUNT,
    dry_pressure_bar: float | None = None,
    dry_duration_s: float = DEFAULT_CLEAN_DRY_DURATION_S,
    dry_valve_current_ma: float = DEFAULT_CLEAN_DRY_VALVE_CURRENT_MA,
    settle_timeout_s: float = DEFAULT_SETTLE_TIMEOUT_S,
    settle_avg_window_s: float = DEFAULT_SETTLE_AVG_WINDOW_S,
    settle_tolerance_bar: float = DEFAULT_SETTLE_TOLERANCE_BAR,
    settle_poll_interval_s: float = DEFAULT_SETTLE_POLL_INTERVAL_S,
    echo: Optional[bool] = None,
) -> None:
    """Run a tank/valve cleaning routine and restore prior pressure setpoint.

    The routine repeats:
    1) set tank pressure to `clean_pressure_bar`
    2) open the valve for `valve_open_duration_s`
    3) close the valve and return to the idle valve current

    `cycle_count` may be zero. In that case, cleaning cycles are skipped and
    only the optional drying phase is executed.

    If `dry_duration_s` is greater than zero, a final drying phase is run at
    `dry_pressure_bar` when provided, otherwise at `clean_pressure_bar`, with
    the valve held slightly open at `dry_valve_current_ma` for the requested
    duration.

    After all cycles (or on failure), the previous pressure setpoint is
    restored automatically using `set_pressure`. When no host-side
    setpoint is known, the current sensor readback is used as the fallback
    restore target.
    """
    if clean_pressure_bar < 0 or clean_pressure_bar > MAX_PRESSURE_BAR:
        raise ValueError(
            f"pressure_bar must be between 0 and {MAX_PRESSURE_BAR} bar")
    if clean_valve_open_duration_s <= 0:
        raise ValueError("valve_open_duration_s must be > 0")
    if dry_duration_s < 0:
        raise ValueError("dry_duration_s must be >= 0")
    if clean_cycle_count < 0:
        raise ValueError("cycle_count must be >= 0")
    if dry_pressure_bar is None:
        dry_pressure_bar = clean_pressure_bar
    elif dry_pressure_bar < 0 or dry_pressure_bar > MAX_PRESSURE_BAR:
        raise ValueError(
            f"dry_pressure_bar must be between 0 and {MAX_PRESSURE_BAR} bar")

    # Record the effective settling parameters rather than just their defaults
    tcm._cleaning_settling_settings = {
        "timeout_s": settle_timeout_s,
        "avg_window_s": (settle_timeout_s / 2 if settle_timeout_s <= settle_avg_window_s
                         else settle_avg_window_s),
        "tolerance_bar": settle_tolerance_bar,
        "poll_interval_s": settle_poll_interval_s,
    }

    # Nothing to do: no cleaning cycles requested and no drying duration set.
    if clean_cycle_count == 0 and dry_duration_s == 0:
        return

    original_setpoint_bar = tcm._target_pressure_bar
    if original_setpoint_bar is None:
        print(
            "Warning: No prior pressure setpoint known; will restore to current sensor readback.")
        original_setpoint_bar = tcm.read_pressure(echo=False)
    restore_original_setpoint = original_setpoint_bar is not None

    try:
        for cycle_idx in range(1, clean_cycle_count + 1):
            tcm.set_pressure(
                clean_pressure_bar,
                timeout_s=settle_timeout_s,
                avg_window_s=settle_avg_window_s,
                tolerance_bar=settle_tolerance_bar,
                poll_interval_s=settle_poll_interval_s,
                status_prefix=(
                    f"{tcm.name} cleaning cycle {cycle_idx}/{clean_cycle_count} "
                    "(pressure"
                ),
                status_suffix=")",
                echo=echo,
            )

            opening_msg = f"{tcm.name} cleaning cycle {cycle_idx}/{clean_cycle_count} (opening valves)"
            pressure_msg_len = len(
                f"{tcm.name} cleaning cycle {cycle_idx}/{clean_cycle_count} "
                f"(pressure -.--/{clean_pressure_bar:.2f} bar)"
            )
            clear_tail = max(0, pressure_msg_len - len(opening_msg))
            print(f"\r{opening_msg}{' ' * clear_tail}", end="", flush=True)

            countdown_beep()
            try:
                tcm.set_valve_current(20, echo=echo)
                tcm.open_solenoid(echo=echo)
                time.sleep(clean_valve_open_duration_s)
                tcm.close_solenoid(echo=echo)
            finally:
                tcm.set_valve_current(12, echo=echo)

        if dry_duration_s > 0:
            tcm.set_pressure(
                dry_pressure_bar,
                timeout_s=settle_timeout_s,
                avg_window_s=settle_avg_window_s,
                tolerance_bar=settle_tolerance_bar,
                poll_interval_s=settle_poll_interval_s,
                status_prefix=f"{tcm.name} drying pressure (pressure",
                status_suffix=")",
                print_newline_on_exit=False,
                echo=echo,
            )
            dry_msg = (
                f"{tcm.name} drying at {dry_pressure_bar:.2f} bar "
                f"(valve {dry_valve_current_ma:.1f} mA)"
            )
            print(f"\r{dry_msg}")
            tcm.set_valve_current(dry_valve_current_ma, echo=echo)
            try:
                tcm.open_solenoid(echo=echo)
                wait_step_s = min(settle_poll_interval_s, dry_duration_s)
                with make_minimal_progress_bar(
                    total=dry_duration_s,
                    label=f"{tcm.name} drying",
                    unit_label="s",
                    postfix_width=20,
                    leave=False,
                ) as pbar:
                    elapsed_s = 0.0
                    while elapsed_s < dry_duration_s:
                        sleep_s = min(
                            wait_step_s, dry_duration_s - elapsed_s)
                        time.sleep(sleep_s)
                        elapsed_s += sleep_s

                        pressure = tcm.read_pressure(echo=False)
                        if pressure is None:
                            pressure_text = "-.-- bar"
                        else:
                            pressure_text = f"{pressure:.2f} bar"

                        pbar.update(sleep_s)
                        pbar.set_postfix_str(f"pressure {pressure_text}")
                tcm.close_solenoid(echo=echo)
            finally:
                tcm.set_valve_current(12, echo=echo)
    finally:
        if restore_original_setpoint:
            tcm.set_pressure(
                original_setpoint_bar,
                timeout_s=settle_timeout_s,
                avg_window_s=settle_avg_window_s,
                tolerance_bar=settle_tolerance_bar,
                poll_interval_s=settle_poll_interval_s,
                status_prefix=f"{tcm.name} restoring pressure (pressure",
                status_suffix=")",
                show_status=True,
                print_newline_on_exit=False,
                echo=echo,
            )
        print()


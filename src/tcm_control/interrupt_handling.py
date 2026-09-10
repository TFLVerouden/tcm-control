"""Interrupt handling helpers for safe experiment shutdown."""

import shutil
from pathlib import Path
from typing import Any

from tcm_utils.io_utils import prompt_yes_no

# References to currently active devices, used by Ctrl+C cleanup.
_ACTIVE_TCM: Any = None
_ACTIVE_NEBULISER: Any = None
_ACTIVE_PUMP: Any = None
_ACTIVE_OUTPUT_DIR: Path | None = None
_INTERRUPT_CLEANED_UP = False


def set_active_tcm(tcm: Any | None) -> None:
    """Register the active cough machine controller for interrupt cleanup."""
    global _ACTIVE_TCM
    _ACTIVE_TCM = tcm


def set_active_nebuliser(nebuliser: Any | None) -> None:
    """Register the active nebuliser controller for interrupt cleanup."""
    global _ACTIVE_NEBULISER
    _ACTIVE_NEBULISER = nebuliser


def set_active_pump(pump: Any | None) -> None:
    """Register the active syringe pump for interrupt cleanup."""
    global _ACTIVE_PUMP
    _ACTIVE_PUMP = pump


def set_active_output_dir(output_dir: Path | None) -> None:
    """Register the current experiment output directory for optional deletion."""
    global _ACTIVE_OUTPUT_DIR
    _ACTIVE_OUTPUT_DIR = output_dir


def reset_interrupt_cleanup_state() -> None:
    """Allow a new cleanup pass for a new run in the same Python process."""
    global _INTERRUPT_CLEANED_UP
    _INTERRUPT_CLEANED_UP = False


def cleanup_on_interrupt(*, ask_before_delete_output_dir: bool = False) -> None:
    """Stop active devices once after Ctrl+C.

    Args:
        ask_before_delete_output_dir: When True, prompt before deleting the output
            directory. Keep this False in signal handlers to avoid re-entrant input.
    """
    global _INTERRUPT_CLEANED_UP
    # Prevent duplicate cleanup attempts if SIGINT is received more than once.
    if _INTERRUPT_CLEANED_UP:
        return
    _INTERRUPT_CLEANED_UP = True

    if _ACTIVE_PUMP is not None:
        try:
            pump_state = _ACTIVE_PUMP.get_state()
            if pump_state in getattr(_ACTIVE_PUMP, "stopped_status", (":",)):
                print("Syringe pump already stopped")
            else:
                _ACTIVE_PUMP.stop(already_stopped_ok=True)
                print("Syringe pump stopped")
        except Exception as exc:
            print(f"Warning: Failed to stop syringe pump: {exc}")

    if _ACTIVE_TCM is not None:
        try:
            _ACTIVE_TCM.quit()
            print("Cough machine returned to idle")
        except Exception as exc:
            print(f"Warning: Failed to quit cough machine: {exc}")

    # TODO(merge nebuliser MCU): once both functions share one controller,
    # remove the separate registration and fold these commands into the TCM
    # shutdown sequence, avoiding duplicate commands to the same connection.
    if _ACTIVE_NEBULISER is not None:
        try:
            _ACTIVE_NEBULISER.set_nebuliser(False)
            print("Nebuliser turned off")
        except Exception as exc:
            print(f"Warning: Failed to turn off nebuliser: {exc}")
        try:
            _ACTIVE_NEBULISER.set_nebuliser_pressure(0.0)
            print("Nebuliser pressure returned to 0")
        except Exception as exc:
            print(f"Warning: Failed to reset nebuliser pressure: {exc}")

    if _ACTIVE_OUTPUT_DIR is not None and _ACTIVE_OUTPUT_DIR.exists():
        output_dir_full = _ACTIVE_OUTPUT_DIR.resolve()
        if ask_before_delete_output_dir:
            delete_output_dir = prompt_yes_no(
                "Remove created experiment directory? "
                f"{output_dir_full} "
                "(press ENTER to cancel, type 'y' to delete)",
                default=False,
            )
        else:
            delete_output_dir = False
            print(
                "Skipping output-directory deletion prompt during Ctrl+C cleanup "
                "to avoid re-entrant stdin access."
            )

        if delete_output_dir:
            try:
                shutil.rmtree(output_dir_full)
                print(f"Removed experiment directory: {output_dir_full}")
            except Exception as exc:
                print(
                    f"Warning: Failed to remove experiment directory {output_dir_full}: {exc}"
                )
        print("Exiting")


def handle_sigint(_signum, _frame) -> None:
    """Handle Ctrl+C by raising KeyboardInterrupt.

    Keep signal-handler work minimal and non-interactive; cleanup is performed
    in regular exception handling flow.
    """
    print("\nCtrl+C detected; stopping experiment...")
    raise KeyboardInterrupt

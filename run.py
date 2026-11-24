"""Top-level entry script for running a cough experiment from a config file."""

from tcm_control.interrupt_handling import (
    cleanup_on_interrupt,
    handle_sigint,
)
from tcm_control.cough import cough
import argparse
from pathlib import Path
import signal

def main(config_path: Path | None = None) -> int:
    # Save any existing Ctrl+C handler and install project-specific cleanup handling.
    previous_sigint_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, handle_sigint)
    try:
        # Run one experiment from the selected config.
        cough(config_path)
    except KeyboardInterrupt:
        # User-initiated stop: run safe cleanup and return standard SIGINT code.
        cleanup_on_interrupt(ask_before_delete_output_dir=True)
        return 130
    except Exception:
        # Unexpected error: still clean up devices/resources, then re-raise.
        cleanup_on_interrupt(ask_before_delete_output_dir=False)
        raise
    finally:
        # Always restore the previous signal handler to avoid global side effects.
        signal.signal(signal.SIGINT, previous_sigint_handler)

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a cough experiment.")
    parser.add_argument("config", nargs="?", type=Path,
                        help="experiment TOML file (opens a file picker if omitted)")
    args = parser.parse_args()
    raise SystemExit(main(args.config))

"""Top-level entry script for running a cough experiment from a config file."""

from tcm_control.interrupt_handling import (
    cleanup_on_interrupt,
    handle_sigint,
)
from tcm_control.cough import cough
from pathlib import Path
import signal

# This runner assumes an editable install so `tcm_control` resolves from `src/`.
# Install once from the repository root with: `pip install -e .`
REPO_ROOT = Path(__file__).resolve().parent

# Hardcode the path here to run experiment multiple times with the same config
# CONFIG_PATH = REPO_ROOT / "src" / "tcm_control" / "config" / "config.toml"


def main() -> int:
    # Save any existing Ctrl+C handler and install project-specific cleanup handling.
    previous_sigint_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, handle_sigint)
    try:
        # Run one experiment from the selected config.
        # cough(CONFIG_PATH)
        cough()
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
    raise SystemExit(main())

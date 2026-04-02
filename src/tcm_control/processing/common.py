from pathlib import Path


PROCESSED_SUBDIR_NAME = "processed"


def get_processed_dir(experiment_dir: Path) -> Path:
    """Return (and create) the processed output directory for an experiment."""
    processed_dir = Path(experiment_dir) / PROCESSED_SUBDIR_NAME
    processed_dir.mkdir(parents=True, exist_ok=True)
    return processed_dir


#
import json
from pathlib import Path

from tcm_control.devices.spraytec import SprayTec
from tcm_utils.file_dialogs import ask_open_file

# Ask user for metadata.json
selected_metadata = ask_open_file(
    key="gather_spraytec_data_from_append_file_metadata",
    title="Select metadata JSON file",
    filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
)

# From metadata, get experiment_dir, time.start, and spraytec.append_file_path
metadata_path = Path(selected_metadata).expanduser().resolve()
with metadata_path.open("r", encoding="utf-8") as fh:
    payload = json.load(fh)
experiment_dir = payload.get("experiment_dir")
time_start = payload.get("time", {}).get("start")
spraytec_append_file_path = payload.get("spraytec", {}).get("append_file_path")

# Make spraytec object
spraytec = SprayTec(
    append_file_path=spraytec_append_file_path,
    experiment_dir=experiment_dir,
)
# Save spraytec data
spraytec.save_data(append_file_path=spraytec_append_file_path,
                   start_time=time_start,
                   offer_archive_if_large=True,
                   )

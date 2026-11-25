# cough-machine-control

How to install tcm-utils to a virtual environment[^1]?
- Make sure to activate your virtual environment[^2], this is succesful if, at the start of each line in the terminal, it says `(.venv)`. If this is not the case, enter `source .venv/bin/activate` into the terminal;
- Clone [`tcm-utils`](https://github.com/TFLVerouden/tcm-utils) to the same folder that `tcm-control` is located in;
- Into the terminal, enter `pip install -e ../tcm-utils`, or, when you are using the full [twente-cough-machine](https://github.com/TFLVerouden/twente-cough-machine) repository, enter `pip install -e ../utils`.

[^1] The reason it is not included in [pyproject.toml](/pyproject.toml), is that editable installs on a relative path are [not allowed by `setuptools`](https://github.com/pypa/setuptools/discussions/2951).
[^2] On Windows, one might have issues activating this virtual environment because the terminal in VS Code is not allowed to run scripts. We tried to mitigate this using the default profile specified in [settings.json](/.vscode/settings.json), but the error and how to fix it are described [here on StackOverflow](https://stackoverflow.com/questions/56199111/visual-studio-code-cmd-error-cannot-be-loaded-because-running-scripts-is-disabl).

## Run an experiment from VS Code

`python run.py path\to\experiment.toml` runs the specified configuration.
Without an argument, `run.py` opens a file picker for the experiment TOML.

The optional extension in `vscode-extension` adds a play button to open TOML
files. Cloning the repository does not install it: install it once in each
VS Code installation or profile where you want the button. First install
Node.js 22 or newer and the Microsoft Python extension, then run these commands
from the repository root:

```shell
cd vscode-extension
npx --yes @vscode/vsce package --no-dependencies --skip-license
code --install-extension tcm-config-runner-0.0.1.vsix
```

Reload VS Code, open this repository as a workspace, and select the project's
Python interpreter, with this project and its dependencies installed. Open an
experiment TOML and click **Run TCM experiment**. The file is saved first,
and the experiment runs interactively in a terminal. The button appears on all
TOML files, including files that are not experiment configs; select the intended
experiment file before clicking it.

The generated `.vsix` file can be deleted after installation. If the extension
source changes, package and install it again to update the installed copy.

## Versioning policy

This project uses two separate version numbers:

1. Python package version in pyproject.toml (project/app release tracking).
2. Host-MCU protocol version (serial communication compatibility).

The protocol should be a single integer: host and MCU protocol versions must match exactly. The version number is increased when communication changes in a breaking way.

## Syringe pump connection

The Harvard PHD Ultra must be configured as a standalone pump at address 0,
with a baud rate of 9600 by default. The pump is discovered by sending `ver`
and checking for a PHD Ultra version response; discovery may open and probe
other serial ports. The last successful port is saved in `connections.ini`.
The software checks the pump address without changing it and stops setup if
the address is not 0. Syringe dimensions and force remain configured in the
experiment TOML. If one or more syringe properties are omitted in a film
configuration, startup prompts for a profile from `syringes.toml`; the selected
profile fills only the omitted properties.

Commands use carriage-return termination. Quick Start mode is needed for
parameter commands; after using the touchscreen, communication may need to be
re-established with a carriage return. See the [PHD Ultra manual](https://www.harvardapparatus.com/media/manuals/Product%20Manuals/PHD%20ULTRA%20Manual-70-3xxx_5419-002REV1.0.pdf)
for connection and command details.

## Pressure sensor calibration

Run `src/tcm_control/calibration/pressure_calibration.py` in VS Code with the
cough machine and an external pressure gauge connected. Configure the settings
at the top of the file: choose `P` for the tank or `M` for the nebuliser, and
adjust the setpoints, settling time and output directories if needed.

The script connects in debug mode and waits after each setting. Enter the gauge
pressure at the prompt; the matching sensor current is read when you submit it.
The sensor's reported pressure is not yet calibrated. Readings are saved
incrementally in the raw-data directory, then fitted and plotted in the
calibration directory. After completing the readings, the selected pressure
setting is returned to 0 bar. An interrupted or failed run leaves the last
setting in place.

To analyze existing measurements instead, set `INPUT_FILE` to their path.
Input files contain gauge pressure in bar and sensor current in mA, in that
order; select the appropriate `PRESSURE_COMMAND` for the output filenames.

## Film and PIV output

Set `[devices.spraytec].enabled` and `[devices.ops].enabled` to enable either
instrument; both default to `false` and are disabled in PIV mode. Older
recording flags under `[inputs.cough]` are no longer accepted.

Each saved experiment contains `run` for one run, or `run1`, `run2`, etc. for
multiple runs. Experiment-wide metadata, the config copy, flow curve, comments,
and console log remain in the experiment folder. Each run folder contains its
run log and plot, and `temperature_humidity.csv` with the reading taken just
before the cough. An unavailable sensor value is left empty and a warning is
printed; the experiment start and finish readings remain in `metadata.json`.
Metadata has `schema_version`, `configuration` (resolved settings) and
`runtime` (measurements, device details and experiment status). It is written
when the experiment directory is created, after device setup, and on successful
completion; interrupted experiments may retain an `in_progress` snapshot.
Device `metadata()` methods contribute operational settings such as pump
timings and the vertical stage's last move parameters. Settings for devices not
used by the run are not reported as active; cleaning settling parameters appear
after cleaning has been attempted. Configured values remain in `configuration`.
For direct device use, `read_temperature_humidity(save_csv=path)` saves the
reading in the same CSV format; omit `save_csv` to read without saving.

Film runs also contain camera images and `film_measurement.csv`, and OPS data
when OPS recording is enabled. Automatic OPS plotting is deferred. Film
measurements are no longer duplicated in the experiment metadata. SprayTec
measurements are exported after the experiment and matched
chronologically to run folders only if the counts agree and the timestamps
are unambiguous. Otherwise, new measurements are saved in
`spraytec_unmatched` in the experiment folder and a warning is printed.

### Optical particle sizer

The TSI 3330 OPS uses TCP, including over USB via TSI's Windows NDIS driver.
Set the connection defaults in `OpticalParticleSizer.__init__` to match the
address shown on the instrument. The instrument must already be powered on.
After moving a USB connection from another PC, it may need a power cycle.

Set `[devices.ops]` for the 17 boundaries of the 16 size channels, the
number-concentration alarm threshold, and the pre- and post-run recording times.
The defaults in the example config are 10 seconds on either side. Recording
starts once the instrument reports it is running; the post-run interval starts
at the cough machine's completion event. One-second samples are written to
`ops.csv` in each run folder, and device identity, settings and connection
information go in experiment metadata. Set `[geometry.ops].position` to a description or
leave it empty to be prompted once. The description is saved in the metadata.
The instrument's humidity field is a
placeholder and is not an ambient humidity measurement. Unit measurements in
the CSV are read after each bin sample and are not necessarily simultaneous.

The instrument is configured for at most 60 seconds per recording. A longer
recording, missing samples, or communication errors abort the run rather than
silently producing incomplete data. Instrument logging consumes its internal
storage. The previous user-calibration values, including shape correction 0.0,
are retained with user calibration disabled; the manual documents 0.1-3.0
for shape correction, so verify that the instrument accepts this setting.
See the [OPS manual](https://kenelec.com.au/wp-content/uploads/2016/06/TSI_3330_Opticle_Particle_Sizer_Manual.pdf).

## Config and metadata extension guide

Define each setting in its Pydantic model in
`src/tcm_control/initialise_config.py`, including its description, default,
validation and optional `required_for` condition. The entire resolved config
is automatically included in metadata. Read the value where it is used in
`cough.py`; runtime measurements still belong in `build_run_metadata`.
Existing prompt conditions are `mode`, `always`, `film`, `ops`, `spraytec`,
`clean_tube`, and `clean_repetition`. Use an optional field with a default of
`None` for a value that should be prompted when its condition applies.

Settings are grouped under `experiment`, `run`, `film`, `piv`, `droplet`,
`devices`, and `geometry`. Older config and metadata paths must be updated to
match this layout. `[run.cleaning]` controls the cleaning cycles and the
optional drying phase that follows them. Vertical-stage motion defaults are
defined in `devices/vertical_stage.py`, rather than the experiment config.

The documented `src/tcm_control/config/config_template.toml` is generated from
the models. Regenerate it after changing the schema (this overwrites the
template). Entries marked optional with a default use that value when omitted;
other entries describe prompting or optional behavior:

```shell
python -m tcm_control.config.regenerate_template
```

To generate a separate template without overwriting an existing file:

```shell
python -m tcm_control.initialise_config path/to/new_config.toml
```

To create a config without comments, run
`python -m tcm_control.config.generate_empty_config` and enter a filename. It
is saved in the config directory, with `.toml` added if needed. The template
preserves defaults and sections, writes unset fields as empty strings, and does
not overwrite an existing file.

Missing tank pressure and other required values are prompted only when needed.
Leave the series directory empty to select it, or set it to `"None"` to disable
saving. If tube cleaning is selected, missing cleaning volumes and rates are
prompted then. Invalid configured values fail validation; prompted values are
validated again before use.

### Camera ROI

Set `[devices.camera].camera_gain_db` to a number to configure gain in
dB, or omit it to leave the camera's gain unchanged. The configured value is
included in run metadata. For direct use, pass `gain_db=...` to `Camera` or
call `camera.set_gain(...)`. Supported gain limits depend on the camera.

Set `[devices.camera].roi` to `[y_start, y_end, x_start, x_end]` in
pixels. End coordinates are exclusive; `0` means the full extent, and negative
coordinates count from the image edge. The default `[0, 0, 0, 0]` saves the
full frame. The image is cropped after capture, and the configured ROI is saved
in metadata under `configuration.devices.camera.roi`.

Set `[devices.camera].flip` to `"vertical"`, `"horizontal"`, or `"both"`
to flip the image after cropping. The default is `"vertical"`; set it to an
empty string for no flip. The selected setting is also saved in metadata.

Camera snapshots are saved as TIFF files. Explicit `output_path` values must
end in `.tif` or `.tiff`.

Live preview defaults to enabled. Set `[devices.camera].live_preview`
to `false` to disable the local window during
film infusion, withdrawal and settling. The light stays on while the window is
open when the preview is enabled. Close the window or press `q` to continue without the preview. The
background and final snapshots and saved final measurement are unchanged.
Live thickness and contact angle use the background plate and camera scale;
they are provisional and may be unavailable or inaccurate while the contour
is forming. Preview frames are not saved. A desktop display is required.
Omit `scale_mm_per_px` to use the camera module's default calibration.


## VS Code workspace settings
This repository tracks only `.vscode/settings.json` for shared Python run/interpreter behavior.
Keep other `.vscode` files local (they are ignored by `.gitignore`) unless the team explicitly decides to share them.

## Troubleshooting
### How to change the display name of a COM port on Windows?
Source: https://superuser.com/questions/1511278/how-to-change-com-port-name-in-device-manager-while-inserting-external-device
1. Open Device Manager
2. Browse to the COM Port or device you're interested in changing
3. Right click the device and select "Properties"
4. Select the "Details" tab
5. In the "Property" box, select "Container ID"
6. Copy the "Value" presented
7. Open the Registry editor a. MUST now back up the registry in case you boff something and need a road home.
8. Select the "Edit" menu once your registry is loaded
9. Select "Find" a. insert the copied value into the "Find What?" box. b. select the "Find Next" button. c. You may have to select "Find Next" several times until you find the registry entry you're looking for. You'll know you have the correct registry entry when you come across one that contains the REG_SZ value Name of "Friendly Name."
10. Double-click the "Friendly Name" icon. This will open an editable box for you to change the name of the item. In my case, when I change the friendly name of a COM port I only change the name and not the COM port number. This does have the potential to get gummed up if you aren't careful with what you do.
11. After you make your change, exit the registry editor and close the Device Manager.
12. Open the Device Manager and you should see that device's friendly name changed to what you desired. Hope this helps...

### Trouble with pressure sensor readout?
See https://github.com/Dennis-van-Gils/MIKROE_4_20mA_RT_Click/tree/main/docs

### Aspect ratio
Scale= Distance_pixels_x/ known_length_x
Aspect_ratio = known_length_y/ distpix_y (with scale conversion)
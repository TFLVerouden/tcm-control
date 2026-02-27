from pathlib import Path
import csv
from typing import Optional
from tcm_utils.file_dialogs import ask_open_file
from tcm_utils.plot_style import use_tcm_poster_style, append_unit_to_last_ticklabel
from tcm_utils.cvd_check import set_cvd_friendly_colors, get_color

import numpy as np
import matplotlib.pyplot as plt


def plot_run_log(run_log_path: Path | None = None, experiment_dir: Path | None = None):
    # If no path provided, ask the user to select a run log CSV file.
    if run_log_path is None:
        run_log_path = ask_open_file(
            key="plot_run_log_csv",
            title="Select run log CSV file",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
    if run_log_path is None:
        print("No file selected, aborting.")
        return

    # Read the run log and extract metadata and data columns
    (trigger_t0_us, run_nr, time_us, sol_valve_action,
     prop_valve_ma, press_bar) = _read_run_log(run_log_path)

    # Process the time column to be relative to the trigger time and convert to milliseconds
    time_ms = (time_us - trigger_t0_us) / 1000.0

    # Get the solenoid valve start and open times
    sol_open_start_ms = time_ms[sol_valve_action == 1][0]
    sol_open_end_ms = time_ms[sol_valve_action == 0][0]

    use_tcm_poster_style()
    set_cvd_friendly_colors()

    # Plot time on the x-axis, with vertical shading indicating the moments when the solenoid valve is open (sol_valve_action == 1) and a vertical line indicating the trigger time (time_ms == 0).
    # On the left y-axis, plot the pressure in bar, and on the right y-axis, plot the proportional valve current in mA.=
    fig, ax1 = plt.subplots(figsize=(10, 6))
    # ax1.set_xlabel("Time (ms)")
    ax1.set_ylabel("Pressure (bar)", color=get_color(0))
    ax1.plot(time_ms, press_bar, color=get_color(
        0), label="Pressure (bar)", linewidth=2)
    ax1.tick_params(axis="y", labelcolor=get_color(0))
    ax1.set_ylim(bottom=1, top=2)

    ax2 = ax1.twinx()
    ax2.set_ylabel("Proportional valve setpoint (mA)", color=get_color(1))
    ax2.plot(time_ms[prop_valve_ma > 0], prop_valve_ma[prop_valve_ma > 0], color=get_color(
        1), label="Proportional valve setpoint (mA)", linewidth=2)
    ax2.tick_params(axis="y", labelcolor=get_color(1))
    ax2.set_ylim(bottom=11.1, top=20.9)

    # Add vertical shading for solenoid open times
    ax1.axvspan(sol_open_start_ms, sol_open_end_ms, linestyle="",
                color="#000000", alpha=0.2, label="Solenoid open")

    # Add vertical line for trigger time
    ax1.axvline(0, color="#000000", linestyle="--",
                linewidth=2, label="Trigger time")

    # Add legends
    # lines_labels = [ax.get_legend_handles_labels() for ax in [ax1, ax2]]
    # lines, labels = [sum(lol, []) for lol in zip(*lines_labels)]
    # ax1.legend(loc="upper right")

    append_unit_to_last_ticklabel(ax1, axis="x", unit="ms")

    plt.show()
    # Export to pdf in experiment directory/plots
    if experiment_dir is not None:
        plot_path = experiment_dir / f"run_log_{run_nr}.pdf"
        plt.savefig(plot_path)
        print(f"Plot saved to {plot_path}")


def _read_run_log(run_log_path: Path) -> tuple[
        int,
        int,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
]:
    """Read a run log and return metadata plus the four numeric data columns.

    Returns:
            (trigger_t0_us, run_nr, time_us,
             sol_valve_action, prop_valve_ma, press_bar)
    """
    run_nr: Optional[int] = None
    trigger_t0_us: Optional[int] = None
    header_found = False

    time_us: list[int] = []
    sol_valve_action: list[int] = []
    prop_valve_ma: list[float] = []
    press_bar: list[float] = []

    with run_log_path.open("r", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue

            key = row[0].strip()
            if key == "run_nr" and len(row) > 1:
                run_nr = int(row[1])
                continue

            if key == "trigger_t0_us" and len(row) > 1:
                trigger_t0_us = int(row[1])
                continue

            if key == "time_us":
                header_found = True
                continue

            if not header_found or len(row) < 4:
                continue

            time_us.append(int(row[0]))
            sol_valve_action.append(int(row[1]))
            prop_valve_ma.append(float(row[2]))
            press_bar.append(float(row[3]))

    if run_nr is None:
        raise ValueError(f"Missing 'run_nr' in run log: {run_log_path}")

    if trigger_t0_us is None:
        raise ValueError(f"Missing 'trigger_t0_us' in run log: {run_log_path}")

    return (
        trigger_t0_us,
        run_nr,
        np.asarray(time_us, dtype=np.int64),
        np.asarray(sol_valve_action, dtype=np.int8),
        np.asarray(prop_valve_ma, dtype=np.float64),
        np.asarray(press_bar, dtype=np.float64),
    )


if __name__ == "__main__":
    plot_run_log(Path(
        r"C:\CoughMachineData\260226_tests\260227_174547_firmware_test\run_260227_174605.csv"))

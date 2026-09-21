from tcm_control.devices import CoughMachine
from tcm_control.processing.run_log_processing import plot_run_log
from pathlib import Path


def main() -> None:
    flow_curve_csv_path = "src/tcm_control/flow_curves/from_model/gupta_71kg_1-94m.csv"
    tank_pressure_bar = 2.5  # bar
    tcm = CoughMachine(debug=True)
    tcm.clear_logs()
    # time_arr, Lps_arr, sol_enable_arr, trig_enable_arr = tcm._extract_csv(
    #     flow_curve_csv_path)

    # serial_command = tcm._format_dataset(
    #     time_arr,
    #     Lps_arr,
    #     sol_enable_arr,
    #     trig_enable_arr,
    # )

    # print(serial_command)
    tcm.set_pressure(tank_pressure_bar, avg_window_s=0.5)
    tcm.load_flowcurve(
        # Load the configured flow curve and optionally copy it into output_dir
        csv_path=flow_curve_csv_path,
        tank_pressure_bar=tank_pressure_bar)

    run_log_path = tcm.run(output_dir=".logs")

    # Plot the run log
    plot_run_log(run_log_path, show=True, experiment_dir=Path("temp"))


if __name__ == "__main__":
    main()

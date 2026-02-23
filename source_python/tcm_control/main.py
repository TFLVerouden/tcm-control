from pathlib import Path

from importlib import resources

from tcm_control.devices import CoughMachine


def main() -> None:
    cough_machine = CoughMachine(debug=False)
    # cough_machine.clear_memory()
    cough_machine.set_pressure(1.5, timeout_s=10.0)

    flow_curve = resources.files(
        "tcm_control").joinpath("flow_curves/step.csv")
    output_dir = Path.cwd() / "CoughMachineData" / "Tests"

    cough_machine.load_flowcurve(csv_path=flow_curve)
    # cough_machine.detect_droplet(runs=2, output_dir=output_dir)
    cough_machine.manual_mode()


if __name__ == "__main__":
    main()

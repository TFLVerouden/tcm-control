import propar
import time
import datetime
import os
import numpy as np
import matplotlib.pyplot as plt
import sys
import pumpy3
import json

from devices import find_serial_device, SprayTecLift, create_serial_device, connect_serial_device, read_ser_response
from flow_profile import extract_flow_profile, format_flow_profile, resolve_flow_curve_path
from tcm_utils.file_dialogs import ask_open_file, find_repo_root, repo_config_path


# TODO: Consider: add config options for droplet detection delay (PRE) and
#       detection mode (single/continuous) in config.json.
# TODO: Should trigger time also go to Log file separately?
# TODO: Split this up into functions and classes for better readability, turn into module

# from functions import Gupta2009 as Gupta

cwd = os.path.abspath(os.path.dirname(__file__))

parent_dir = os.path.dirname(cwd)
print(parent_dir)
# function_dir = os.path.join(parent_dir, 'cough-machine-control')
function_dir = os.path.join(parent_dir, 'functions')
print(function_dir)
sys.path.append(function_dir)

# Finished loading Modules

mcu_device = None
lift_device = None
lift = None


def split_array_by_header_marker(arr, marker='Date-Time'):
    arr = np.array(arr)
    header = arr[:, 0]
    rows = arr[:, 1:]

    # Find indices where header has the marker
    split_indices = [i for i, val in enumerate(header) if val == marker]
    split_indices.append(len(header))  # include end boundary

    result = []
    for i in range(len(split_indices) - 1):
        start = split_indices[i]
        end = split_indices[i+1]
        section = arr[start:end]
        result.append(section)

    return result


def Spraytec_data_saved_check():
    """
    This function saves the last spraytec measurement of the previous run to a .txt
    in the folder individual_data_files. Do not touch this if you do not know waht you are doing!
    """
    # current_dir = os.path.dirname(os.path.abspath(__file__))
    # parent_path = os.path.dirname(current_dir)  # one level up
    spraytec_path = os.path.join("C:\\CoughMachineData\\SprayTec\\")
    path = os.path.join(spraytec_path, "SPRAYTEC_APPEND_FILE.txt")
    save_path = os.path.join(spraytec_path, "individual_data_files")
    file = np.loadtxt(path, dtype=str, delimiter=',')
    split_sections = split_array_by_header_marker(file)
    last_file = split_sections[-1]
    time_created = last_file[1, 0]
    filename = last_file[1, 1]
    dt = datetime.datetime.strptime(time_created, '%d %b %Y %H:%M:%S.%f')
    # Format as YYYY_MM_DD_HH_MM
    file_name_time = dt.strftime('%Y_%m_%d_%H_%M')
    save_path = os.path.join(
        save_path, file_name_time + "_" + filename + ".txt")
    if not os.path.exists(save_path):
        np.savetxt(save_path, last_file, fmt='%s', delimiter=',')
        print(f"Saved spraytec_data of {file_name_time}")


def reading_temperature(verbose=False):
    ser.reset_input_buffer()
    ser.write('T?\n'.encode())
    time.sleep(0.1)  # wait for the response
    Temperature = ser.readline().decode('utf-8', errors='ignore').rstrip()
    RH = ser.readline().decode('utf-8', errors='ignore').rstrip()
    Temperature = Temperature.lstrip('T')
    RH = RH.lstrip('RH')

    if verbose:
        print(f'Temperature: {Temperature} °C; relative humidity: {RH} %')
    return RH, Temperature


def reading_pressure(verbose=False):
    ser.reset_input_buffer()
    ser.write('P?\n'.encode())
    time.sleep(0.1)  # wait for the response
    pressure = ser.readline().decode('utf-8', errors='ignore').rstrip()
    pressure_value = pressure.lstrip('P')

    if verbose:
        print(f'Pressure: {pressure_value} mbar')
    return pressure_value


def manual_mode():
    print("\n=== MANUAL MODE ===")
    print("Enter commands to send to MCU (type 'exit' to return to main menu)\n")

    ser.write('B 1\n'.encode())
    time.sleep(0.05)

    while True:
        cmd = input("Enter command: ").strip()

        if cmd.lower() == 'exit':
            answer = input(
                "Are you sure you want to exit manual mode? (y/n): ").strip().lower()
            if answer == 'y':
                print("Exiting program.")
                if mcu_device is not None:
                    mcu_device.close()
                if spraytech_lift_com_port:
                    lift.close_connection()
                exit()
            else:
                continue
        else:
            mcu_device.write(cmd)
            time.sleep(0.1)  # Allow MCU to start responding

            responses = read_ser_response(mcu_device, timeout=0.2)
            for response in responses:
                print(f"Response: {response}")


def send_dataset(mcu, delimiter=',', file_path=None):

    # Defining defaul file path
    flow_curve_path = resolve_flow_curve_path(file_path)
    print("Preparing to send dataset from file.")

    data = extract_flow_profile(flow_curve_path, delimiter)
    print(f"Sending dataset from file: {flow_curve_path}")

    serial_command = format_flow_profile(data[0], data[1], data[2])
    if not serial_command:
        raise ValueError("Flow profile formatting failed; no data sent.")

    mcu.write(serial_command.encode('utf-8'))


def verify_mcu_dataset_received_with_timeout(expected_msg="DATASET_RECEIVED", timeout_sec=5):
    start_time = time.time()

    while (time.time() - start_time) < timeout_sec:
        if ser.in_waiting > 0:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if line == expected_msg:
                print("MCU confirmed dataset receipt.")
                return True
        time.sleep(0.1)  # Small sleep to reduce CPU usage

    print("Error: MCU confirmation timed out.")
    return False


def retreive_experiment_data(filename, experiment_name, start_time, end_time, Temperature, RH, height):

    started = False

    directory = save_path
    os.makedirs(directory, exist_ok=True)
    full_path = os.path.join(directory, filename)

    with open(full_path, "w") as f:
        f.write(f"Experiment Name,{experiment_name}\n")
        f.write(f"Start Time (UTC),{start_time.isoformat()}\n")
        f.write(f"End Time (UTC),{end_time.isoformat()}\n")
        f.write(f"Temperature (C),{Temperature}\n")
        f.write(f"Relative Humidity (%),{RH}\n")
        f.write(f"Lift Height (mm),{height}\n")

        ser.write('F\n'.encode())

        while True:
            raw_line = ser.readline()
            try:
                line = raw_line.decode('utf-8')
            except UnicodeDecodeError:
                continue

            clean_line = line.strip()

            if "START_OF_FILE" in clean_line:
                started = True
                continue
            elif "END_OF_FILE" in clean_line:
                break
            if started:
                f.write(line)
    print(
        f"Experiment data saved to {filename} in {full_path}")


def initialize_pump(pump_com_port=None, pump_baudrate=19200, pump_timeout=0.3, pump_diameter=10.3, pump_mode="PMP"):
    # Initialize pump
    print("Initializing pump...")
    if not pump_com_port:
        pump_com_port = find_serial_device(
            description=pump_description, continue_on_error=False)

    try:
        chain = pumpy3.Chain(
            pump_com_port,
            baudrate=pump_baudrate,
            timeout=pump_timeout
        )

        pump = pumpy3.PumpPHD2000_Refill(chain, address=0, name="PHD2000")

        print("Flushing pump...")

        pump.set_diameter(pump_diameter)
        pump.set_mode(pump_mode)
        pump.set_rate(1, "ml/mn")
        pump.run()
        time.sleep(1)
        pump.stop()
        print("Pump initialized and flushed.")

        return pump

    except Exception as e:
        print(f"Error initializing pump: {e}")
        return None


def configure_settings():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, 'config', 'config.json')

    try:
        with open(config_path, 'r') as config_file:
            config = json.load(config_file)
            print("Configuration file succesfully loaded.")
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading configuration: {e}")
        exit()

    return config


def set_pressure(pressure_bar):
    ser.write(f'P {pressure_bar}\n'.encode())


if __name__ == '__main__':
    """
    LOAD ALL SETTINGS FROM CONFIG FILE
    """
    config = configure_settings()

    # Load serial variables
    arduino_com_port = config['serial']['arduino_com_port']
    arduino_baudrate = config['serial']['arduino_baudrate']
    arduino_timeout = config['serial']['arduino_timeout']
    arduino_description = config['serial']['arduino_description']
    spraytech_lift_com_port = config['serial']['spraytech_lift_com_port']
    spraytech_lift_baud_rate = config['serial']['spraytech_lift_baudrate']
    spraytech_lift_timeout = config['serial']['spraytech_lift_timeout']
    spraytech_description = config['serial']['spraytech_description']
    pump_com_port = config['serial']['pump_com_port']
    pump_baudrate = config['serial']['pump_baudrate']
    pump_timeout = config['serial']['pump_timeout']
    pump_description = config['serial']['pump_description']
    # Load dataset variables
    dataset_file_path = config['dataset']['dataset_file_path']
    delimiter = config['dataset']['delimiter']
    upload_dataset = config['dataset']['upload_dataset']
    # Load pump variables
    use_pump = config['pump']['use_pump']
    pump_diameter = config['pump']['diameter']
    pump_flow_rate = config['pump']['flow_rate']
    pump_mode = config['pump']['mode']
    # Load run details
    mode = config['run']['mode']
    save_output = config['run']['save_output']
    save_name = config['run']['save_name']
    save_path = config['run']['save_path']
    run_type = config['run']['type']
    duration = config['run']['duration']
    tank_pressure = config['run']['tank_pressure']
    pre_trigger_delay_us = config['run'].get('pre_trigger_delay_us', 0)

    # Set up the Arduino serial connection
    mcu_device = create_serial_device(
        arduino_baudrate,
        arduino_timeout,
        name="MCU_1",
        expected_id="TCM_control",
        display_name="TCM_control",
    )
    connect_serial_device(mcu_device, com_port=arduino_com_port,
                          last_port_key=repo_config_path("MCU_1_port.txt"))

    ser = mcu_device.ser
    if ser is None:
        raise SystemError("Arduino connection failed; serial port unavailable")

    time.sleep(1)
    print(f"Connected to Arduino on {ser.port}")

    # Initialize pump if required
    if use_pump == True:
        pump = initialize_pump(pump_com_port, pump_baudrate,
                               pump_timeout, pump_diameter, pump_mode)

    # Connect to SprayTec lift if available
    lift_device = create_serial_device(
        spraytech_lift_baud_rate,
        spraytech_lift_timeout,
        name="SprayTec_lift",
        expected_id="Arduino_MEGA_2560",
        display_name="SprayTec lift",
        id_query_cmds=["id?", "ID?", "*IDN?"],
        boot_delay_sec=1.0,
        query_wait_time=0.5,
    )
    connect_serial_device(
        lift_device,
        com_port=spraytech_lift_com_port,
        last_port_key=repo_config_path("SprayTec_lift_port.txt")
    )
    if spraytech_lift_com_port and lift_device.ser is not None:
        lift = SprayTecLift(lift_device.ser)
    else:
        lift = None

    # Create the data directory if it doesn't exist
    if spraytech_lift_com_port:
        Spraytec_data_saved_check()
        # Create the data directory if it doesn't exist
        data_dir = 'data'
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)

    if mode == "manual":
        manual_mode()
    elif mode == "experimental":
        print("\n=== EXPERIMENT MODE ===")

    if run_type == "profile" and upload_dataset == True:

        send_dataset(mcu_device, delimiter, dataset_file_path)

        if verify_mcu_dataset_received_with_timeout():
            print("Proceeding to valve control phase.")
        else:
            print("Failed to send dataset to MCU. Aborting.")
            sys.exit(1)

    set_pressure(tank_pressure)
    ser.write(f'W {pre_trigger_delay_us}\n'.encode())

    while True:
        default_ready = "n"
        ready = (input(
            f"Ready to start experiment (press ENTER for {default_ready})? (y/n): ").strip().lower() or default_ready)
        if ready == 'y':
            break

    # Take humidity, temprature, pressure readings and lift height readings
    RH, Temperature = reading_temperature()

    if spraytech_lift_com_port and lift is not None:
        height = lift.get_height()
    else:
        height = np.nan

    start_time = datetime.datetime.now(datetime.timezone.utc)
    loop_start_time = time.time()
    print('Starting experiment...')

    starting_experiment = True
    finished_experiment = False

    if run_type == 'profile':
        ser.write("R\n".encode())
        time.sleep(0.1)  # wait for response
        while ser.in_waiting > 0:
            response = ser.readline().decode('utf-8', errors='ignore').rstrip()
            if response == "EXECUTING_DATASET":
                print("MCU has started executing the dataset.")
            else:
                print(f"Something went wrong, response: {response}")
    elif run_type == 'square':
        print(
            "Square runs are now expected to be encoded in the dataset. "
            "Please provide a dataset with the enable column instead of using O/C."
        )
        sys.exit(1)

    # while True:
    #     experiment_type_default = "1"
    #     experiment_type = (input(
    #         f'Select experiment type - 1: Flow profile, 0: Square profile (press ENTER for {experiment_type_default}): ').strip()
    #         or experiment_type_default)

    #     if experiment_type == "0":
    #         duration_default = 500
    #         duration = int((input(
    #             f'Enter valve open duration in ms (press ENTER for {duration_default} ms): ')).strip() or duration_default)
    #         break
    #     elif experiment_type == "1":
    #         # Ask if the user wants to load a dataset
    #         load_dataset_default = "n"
    #         load_dataset = (input(
    #             f'Do you want to upload a flow curve (press ENTER for {load_dataset_default})? (y/n): ').strip().lower() or load_dataset_default)
    #         if load_dataset == 'y':
    #             send_dataset(delimiter, dataset_file_path)

    #             # Immediately check for the confirmation
    #             if verify_mcu_dataset_received_with_timeout():
    #                 print("Proceeding to valve control phase.")
    #                 break
    #             else:
    #                 print("Failed to sync with MCU. Aborting.")
    #                 sys.exit(1)
    #         elif load_dataset == 'n':
    #             print("Proceeding without loading a dataset.")
    #             break

    # default_pressure = 1
    # pressure = (input(f'Enter target tank pressure in bar (press ENTER for {default_pressure} bar): ').strip(
    # ) or str(default_pressure))
    # ser.write(f'SP {pressure}\n'.encode())

    # # Ask if ready to execute experiment
    # while True:
    #     ready_default = "n"
    #     ready = (input(
    #         f'Ready to start the experiment (press ENTER for {ready_default})? (y/n): ').strip().lower() or ready_default)
    #     if ready == 'y':
    #         if experiment_type == '1':
    #             ser.write("RUN\n".encode())
    #             time.sleep(0.1)  # wait for response
    #             while ser.in_waiting > 0:
    #                 response = ser.readline().decode('utf-8', errors='ignore').rstrip()
    #                 if response == "EXECUTING_DATASET":
    #                     print("MCU has started executing the dataset.")
    #                 else:
    #                     print(f"Something went wrong, response: {response}")
    #             break
    #         elif experiment_type == '0':
    #             ser.write("SV 20\n".encode())
    #             time.sleep(0.2)  # wait for proportional valve to open
    #             ser.write(f"O {duration}\n".encode())
    #             break
    #     else:
    #         print('Take your time. Press y when ready.')

    # # Take humidity, temprature, pressure readings and lift height readings
    # RH, Temperature = reading_temperature()

    # if spraytech_lift_com_port:
    #     height = lift.get_height()
    # else:
    #     height = np.nan

    # start_time = datetime.datetime.now(datetime.timezone.utc)
    # loop_start_time = time.time()
    # print('Starting experiment...')

    # starting_experiment = True
    # finished_experiment = False

    while True:

        if ser.in_waiting > 0:
            response = ser.readline().decode('utf-8', errors='ignore').rstrip()

            if response == "DONE_SAVING_TO_FLASH":
                end_time = datetime.datetime.now(datetime.timezone.utc)
                starting_experiment = False
                finished_experiment = True

                if save_output == True:
                    print("Saved experiment detected. Starting file retrieval...")

                    timestamp = time.strftime("%Y%m%d-%H%M%S")
                    filename = f"{save_name}_{timestamp}.csv"

                    retreive_experiment_data(
                        filename, save_name, start_time, end_time, Temperature, RH, height)
                else:
                    print("Experiment completed. Data not saved as per user choice.")

        # Break the loop if experiment is finished
        if finished_experiment:
            if mcu_device is not None:
                mcu_device.close()
            if spraytech_lift_com_port and lift is not None:
                lift.close_connection()

            print("Serial connections closed")
            break

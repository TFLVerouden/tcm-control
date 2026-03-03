import propar
import serial
import time
import serial.tools.list_ports
import datetime
import csv
import os
import numpy as np
import matplotlib.pyplot as plt
import sys


cwd = os.path.abspath(os.path.dirname(__file__))

parent_dir = os.path.dirname(cwd)
print(parent_dir)
#function_dir = os.path.join(parent_dir, 'cough-machine-control')
function_dir = os.path.join(parent_dir,'functions')
print(function_dir)
sys.path.append(function_dir)
from functions import Gupta2009 as Gupta
import pumpy 
# from Ximea import Ximea #not needed anymore


####Finished loading Modules
def split_array_by_header_marker(arr, marker='Date-Time'):
    arr = np.array(arr)
    header = arr[:,0]
    rows = arr[:,1:]

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
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_path = os.path.dirname(current_dir)  # one level up
    spraytec_path = os.path.join(parent_path,"spraytec")
    path = os.path.join(spraytec_path,"SPRAYTEC_APPEND_FILE.txt")
    save_path = os.path.join(spraytec_path, "individual_data_files")
    file = np.loadtxt(path,dtype=str,delimiter=',')
    split_sections = split_array_by_header_marker(file)
    last_file = split_sections[-1]
    time_created= last_file[1,0]
    filename= last_file[1,1]
    dt = datetime.datetime.strptime(time_created, '%d %b %Y %H:%M:%S.%f')
    # Format as YYYY_MM_DD_HH_MM
    file_name_time = dt.strftime('%Y_%m_%d_%H_%M')
    save_path = os.path.join(save_path,file_name_time +"_" +filename + ".txt")
    if not os.path.exists(save_path):
        np.savetxt(save_path,last_file,fmt='%s',delimiter=',')
        print(f"Saved spraytec_data of {file_name_time}")

    




def find_serial_device(description, continue_on_error=False):
    ports = list(serial.tools.list_ports.comports())
    ports.sort(key=lambda port: int(port.device.replace('COM', '')))

    # Filter ports where the description contains the provided keyword
    matching_ports = [port.device for port in ports if description in port.description]

    if len(matching_ports) == 1:
        return matching_ports[0]
    elif len(matching_ports) > 1:
        print('Multiple matching devices found:')
        for idx, port in enumerate(ports):
            print(f'{idx+1}. {port.device} - {port.description}')
        choice = input(f'Select the device number for "{description}": ')
        return matching_ports[int(choice) - 1]
    else:
        if continue_on_error:
            return None
        print('No matching devices found. Available devices:')
        for port in ports:
            print(f'{port.device} - {port.description}')
        choice = input(f'Enter the COM port number for "{description}": COM')
        return f'COM{choice}'

def reading_temperature(verbose=False):
    ser.write('T?\n'.encode())
    time.sleep(0.1) #wait for the response
    Temperature = ser.readline().decode('utf-8').rstrip()
    RH= ser.readline().decode('utf-8').rstrip()
    Temperature = Temperature.lstrip('T')
    RH = RH.lstrip('RH')

    if verbose:
        print(f'Temperature: {Temperature} °C; relative humidity: {RH} %')
    return RH, Temperature

def reading_pressure(verbose=False):
    ser.write('P?\n'.encode())
    time.sleep(0.1) #wait for the response
    pressure = ser.readline().decode('utf-8').rstrip()
    pressure_value = pressure.lstrip('P')

    if verbose:
        print(f'Pressure: {pressure_value} mbar')
    return pressure_value

class SprayTecLift(serial.Serial):
    def __init__(self, port, baudrate=9600, timeout=1):
        super().__init__(port=port, baudrate=baudrate, timeout=timeout)
        time.sleep(1)  # Allow time for the connection to establish
        print(f"Connected to SprayTec lift on {port}")

    def get_height(self):
        """Send a command to get the platform height and parse the response."""
        try:
            self.write(b'?\n')  # Send the status command
            response = self.readlines()
            for line in response:
                if line.startswith(b'  Platform height [mm]: '):
                    height = line.split(b': ')[1].strip().decode('utf-8')
                    return float(height)
            print('Warning: No valid response containing "Platform height [mm]" was found.')
            return None
        except Exception as e:
            print(f"Error while reading lift height: {e}")
            return None

    def close_connection(self):
        """Close the serial connection."""
        self.close()
        # print("Lift connection closed.")


if __name__ == '__main__':

    Spraytec_data_saved_check()
    # Create the data directory if it doesn't exist
    data_dir = 'data'
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)

    # Show Ximea cam live
    #try:
    #    cam = Ximea(export_folder = data_dir)
    #    cam.set_param(exposure=1000)
    #    cam.live_view(before=True)
    #except Exception as e:
    #    print("Ximea not found")
    
    # Ask if the user wants to save the data

    save_default = "n"
    save = (input('Do you want to save the data? (y/n): ').strip().lower()
            or save_default)

    # TODO: No need to contact the flow meter and lift if no

    # Get the experiment name
    experiment_name_default = "test"
    if save == "y":
        experiment_name = (input(f'Enter experiment name (press ENTER for '
                                f'"{experiment_name_default}"): ').strip()
                        or experiment_name_default)

    # Get the duration of the valve opening
    duration_ms_default = 80
    duration_ms = int(input(f'Enter valve opening duration (press ENTER for '
                            f'{duration_ms_default} ms): ').strip()
                      or duration_ms_default)
    #Processing compare to model
    if save == "y":
        model_default = "n"
        model = (input('Do you want to include the model in the data? (y/n): ').strip().lower()
                or model_default)

    # Set the before and after times
    before_time_ms = 0
    after_time_ms = 1000

    # Set up the Arduino serial connection
    arduino_port = find_serial_device(description='ItsyBitsy')
    arduino_baudrate = 115200

    if arduino_port:
        ser = serial.Serial(arduino_port, arduino_baudrate,
                            timeout=0)  # Non-blocking mode
        time.sleep(1)  # Wait for the connection to establish
        print(f'Connected to Arduino on {arduino_port}')
    else:
        raise SystemError('Arduino not found')
    
    # Set up the flow meter serial connection
    flow_meter_port = find_serial_device(description='Bronkhorst')
    flow_meter_baudrate = 115200
    flow_meter_node = 3

    if flow_meter_port:
        flow_meter = propar.instrument(comport=flow_meter_port,
                                       address=flow_meter_node,
                                       baudrate=flow_meter_baudrate)
        flow_meter_serial_number = flow_meter.readParameter(92)
        time.sleep(1)  # Wait for the connection to establish
        print(
                f'Connected to flow meter {flow_meter_serial_number} '
                f'on {flow_meter_port}')
    else:
        raise SystemError('Flow meter not found')

    # Readout SprayTec lift height; if not found, give warning message but continue
    lift_port = find_serial_device(description='Mega', continue_on_error=True)
    if lift_port:
        lift = SprayTecLift(lift_port)
    else:
        print('Warning: SprayTec lift not found; height will not be recorded.')


    ready = (input('Ready to cough?'))

    
    #We are going to send a command to the Arduino to measure the temperature
    #and relative humidity of the environment.
    #These lines send the command to read Temperature to arduino
    #It receives two responses. To make sure that we are not interfering anything
    #we are going to lstrip with their signature characters
    RH, Temperature = reading_temperature(verbose=True)

    # Read out the lift height
    if lift_port:
        height = lift.get_height()
    else:
        height = np.nan

    # Set up the readings array
    readings = np.array([],dtype=float)

    # Start the while loop
    valve_opened = False
    finished_received = False
    start_time = datetime.datetime.now(datetime.timezone.utc)

    loop_start_time = time.time()
    print('Starting experiment...')

    while True:
        current_time = time.time()
        elapsed_time = current_time - loop_start_time

        ### Probably the before time makes it less reliable, then just immediately starting it
        # Ask the Arduino for a single pressure readout
        ser.write('P?\n'.encode())
        # Listen for commands from the Arduino
        if ser.in_waiting > 0:
            response = ser.readline().decode('utf-8').rstrip()
            if response == "":
                continue
            elif response == "!":
                print('Valve closed')
                finished_received = True
                finished_time = current_time
            elif response[0] == "P":
                # Assume it's a pressure value
                if response[1:] == '':
                    pressure_value = np.nan
                else:
                    pressure_value = float(response[1:])

                # Read the flow meter value
                flow_meter_value = float(flow_meter.readParameter(8))
                readings = np.append(readings, [current_time,
                                                pressure_value, flow_meter_value])



        # After a set time, send a command to the Arduino to open the valve
        if not valve_opened and elapsed_time >= (before_time_ms / 1000):
            print('Opening valve...')
            ser.write(f'O {duration_ms}\n'.encode())
            valve_opening_time = time.time()
            valve_opened = True

        # Continue the loop for an additional time after receiving "!"
        if finished_received and (current_time - finished_time) >= (
                after_time_ms / 1000):

            print('Experiment finished')
            break
        if (elapsed_time) >= 5*(before_time_ms/1000 + after_time_ms/1000):
            #If, for whatever reason, no "!" is received, the loop
            #  will continue indefinitely
            #fixed after 5 times the before and after time it stops anyway
            print('Experiment finished as the code seems to be in a loop')
            break

# Close the serial connections
    ser.close()
    if lift_port:
        lift.close_connection()
    # Todo: close serial port of flow_meter
    # if flow_meter_port:
    #     flow_meter.close()
    print('Connections closed')

if save == "y":
    # Save the readings to a CSV file
    print('Saving data...')
    flow_meter_calibration_value = float(10 / 30000) #L/s at maximum capacity: 30.000 a.u.
    readings = readings.reshape(-1,3)
    readings[:,0] = readings[:,0] -valve_opening_time #time since the valve opened
    readings[:,2] = readings[:,2] * flow_meter_calibration_value  #now in L/s
    timestamp = datetime.datetime.now().strftime('%y%m%d_%H%M')
    filename = os.path.join(data_dir, f'{timestamp}_{experiment_name}.csv')
    with open(filename, 'w', newline='') as csvfile:
        csvwriter = csv.writer(csvfile)
        # Write the header
        csvwriter.writerow(['Experiment name', experiment_name])
        csvwriter.writerow(['Start time (UTC)', start_time])
        csvwriter.writerow(['Opening duration (ms)', duration_ms])
        csvwriter.writerow(['Time before opening (ms)', before_time_ms])
        csvwriter.writerow(['Time after closing (ms)', after_time_ms])
        csvwriter.writerow(['Ambient temperature (°C)', Temperature])
        csvwriter.writerow(['Relative humidity (%)', RH])
        csvwriter.writerow(['SprayTec lift height (mm)', height])
        csvwriter.writerow([])
        csvwriter.writerow(
                ['Elapsed time (s)', 'Pressure (bar)', 'Flow rate (L/s)'])

        # Write the readings
        for reading in readings:
            csvwriter.writerow(reading)
#### plotting
    plotname = os.path.join(data_dir, f'{timestamp}_{experiment_name}.png')
    plotdata= readings
    print(readings)
    print(readings.shape)
    dt = np.diff(plotdata[:,0])
    mask = plotdata[:,2]>0 #finds the first time the flow rate is above 0
    if np.sum(mask) == 0:
        print("No flow rate data found. Exiting.")
        sys.exit(1)
    mask_opening = plotdata[:,0]>0 #finds the first time the valve is opened
    t0 = plotdata[mask,0][0]
    peak_ind = np.argmax(plotdata[:,2])
    PVT = plotdata[peak_ind,0] - t0 #Peak velocity time
    CFPR = plotdata[peak_ind,2] #Critical flow pressure rate (L/s)
    CEV = np.sum(dt * plotdata[1:,2]) #Cumulative expired volume
    plotdata = plotdata[mask_opening,:]
    t = plotdata[:,0] -t0
    fig, ax1 = plt.subplots()
    ax1.plot(t, plotdata[:,2], 'b-',label= "Measurement",marker= "o",markeredgecolor= "k")
    if model == "y":
        #person E, me based on Gupta et al
        Tau = np.linspace(0,10,101)

        PVT_E, CPFR_E, CEV_E = Gupta.estimator("Male",70, 1.89)

        cough_E = Gupta.M_model(Tau,PVT_E,CPFR_E,CEV_E)
        ax1.plot(Tau*PVT_E,cough_E* CPFR_E, 'r:',label= "Model")
    ax1.set_xlabel('Time (s)')
    ax1.legend()
    ax1.set_ylabel('Flow rate (L/s)')
    ax1.set_title(f'Exp: {experiment_name}, open: {duration_ms} ms \n'
                  f' CFPR: {CFPR:.1f} L/s, PVT: {PVT:.2f} s, CEV: {CEV:.1f} L\n'
                  f'T: {Temperature} °C, RH: {RH} %, lift: {height} mm')
    ax1.grid()

    ax2 = ax1.twinx()
    ax2.plot(t, plotdata[:,1], 'g-',label= "Pressure")
    ax2.set_ylabel('Pressure (bar)')
    ax2.tick_params(axis='y', labelcolor='g')
    ax2.set_ylim(bottom=0)

    plt.tight_layout()
    plt.savefig(plotname)

# try:
#     cam.live_view(before=False)
# except Exception as e:
#         print("Ximea not found")
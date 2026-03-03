import pumpy3
import serial
import time
import serial.tools.list_ports
import numpy as np
import matplotlib.pyplot as plt

# FUNCTIONS THAT NEED TO BE MOVED ELSEWHERE AT SOME POINT


def find_serial_device(description, continue_on_error=False):
    ports = list(serial.tools.list_ports.comports())
    ports.sort(key=lambda port: int(port.device.replace('COM', '')))

    # Filter ports where the description contains the provided keyword
    matching_ports = [
        port.device for port in ports if description in port.description]

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


def read_temperature(verbose=False):
    ser_mcu.write('T?\n'.encode())
    time.sleep(0.1)  # wait for the response
    Temperature = ser_mcu.readline().decode('utf-8').rstrip()
    RH = ser_mcu.readline().decode('utf-8').rstrip()
    Temperature = Temperature.lstrip('T')
    RH = RH.lstrip('H')

    if verbose:
        print(f'Temperature: {Temperature} °C; relative humidity: {RH} %')
    return RH, Temperature


# INITIALISE VALVE CONTROLLER
mcu_port = find_serial_device('ItsyBitsy')
mcu_baudrate = 115200

if mcu_port is None:
    raise Exception(
        "MCU port not found. Please connect the device and try again.")

ser_mcu = serial.Serial(mcu_port, mcu_baudrate, timeout=0)
time.sleep(1)
print(f"Connected to MCU on {mcu_port} at {mcu_baudrate} baud.")


# INITIALISE PUMP
# Initialise chain and PHD 2000
chain = pumpy3.Chain(
    "COM11",        # Manually specified, no way to auto-detect (yet)
    baudrate=19200,  # Set to match pump
    timeout=0.3     # 300 ms timeout, increase if unstable
)
pump = pumpy3.PumpPHD2000_Refill(chain, address=0, name="PHD2000")

# Configure pump
pump.set_diameter(10.3)     # 5 mL Hamilton gastight nr 1005
pump.set_mode("PMP")        # Set to PuMP mode

input("Press Enter to start flushing the pump...")

# Set MCU delay to 0 us, make sure it is not in droplet detection mode
ser_mcu.write('W 0\n'.encode())
# ser_mcu.write('C'.encode())  # Close valve

# Flush pump for a bit
pump.set_rate(1, "ml/mn")   # Flow rate
pump.run()
time.sleep(1)

# Set MCU to droplet detection mode without opening valve
ser_mcu.write('D 1\n'.encode())

# When a droplet is detected, stop pump
while True:
    if ser_mcu.in_waiting > 0:
        response = ser_mcu.readline().decode('utf-8').rstrip()
        if response == "FINISHED":
            pump.stop()
            ser_mcu.write('C'.encode())  # Disable droplet detection
            break
        else:
            print(f"Unknown response: {response}")
            continue

print("Droplet detected, pump stopped.")

nr_droplets = 50
input(f"Press Enter to record {nr_droplets} droplets...")

# Read all serial commands that may be in the buffer
while ser_mcu.in_waiting > 0:
    ser_mcu.readline()

# First print the temperature and humidity
temperature, humidity = read_temperature(verbose=True)

# Set pump and MCU parameters
pump.set_rate(0.3, "ml/mn")   # Flow rate
ser_mcu.write('W 59500\n'.encode())  # Set valve opening delay to 59.5 ms

# Setup readings array
readings = np.array([], dtype=float)

# Start recording droplets
droplet_times = []
# Enable droplet detection, without opening valve
ser_mcu.write('D 1\n'.encode())
pump.run()

loop_start = time.time()
while len(droplet_times) < nr_droplets:
    tick = time.time()
    elapsed = tick - loop_start

    # Ask MCU for a single pressure readout
    ser_mcu.write('P?\n'.encode())

    # Listen to commands
    if ser_mcu.in_waiting > 0:
        response = ser_mcu.readline().decode('utf-8').rstrip()
        if response == "FINISHED":
            droplet_times.append(elapsed)
            print(
                f"Droplet {len(droplet_times)} detected at {elapsed:.3f} s")
        elif response.startswith("P"):
            pressure = response.lstrip("P")
            if pressure != "":
                readings = np.append(readings, [elapsed, float(pressure)])
        else:
            print(f"Unknown response: {response}")
            continue


ser_mcu.write('C'.encode())  # Disable droplet detection
pump.stop()

# # Make a quick plot of pressure in time, with vertical lines indicating the droplets
# plt.figure()
# plt.plot(readings[0::2] - readings[0], readings[1::2], label='Pressure (bar)')
# for dt in droplet_times:
#     plt.axvline(x=dt - readings[0], color='r', linestyle='--',
#                 label='Droplet detected' if dt == droplet_times[0] else "")
# plt.xlabel('Time (s)')
# plt.ylabel('Pressure (bar)')
# plt.title(
#     f'Dripping drops (T: {temperature} °C, RH: {humidity} %)')
# plt.legend()
# plt.show()

# # Save droplet times to npz file
# np.savez('droplet_times.npz', droplet_times=np.array(droplet_times),
#          temperature=float(temperature), humidity=float(humidity))

import serial
import time


class LightSwitchController:
    def __init__(self, port="COM16", baudrate=115200, timeout=1):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None
        self.light_on = False

    def connect(self):
        if self.ser and self.ser.is_open:
            return True

        try:
            self.ser = serial.Serial(
                self.port,
                self.baudrate,
                timeout=self.timeout
            )

            # Arduino boards often reset when the serial port opens.
            time.sleep(2)
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
            # Force known startup state.
            self.ser.write(b'0')
            self.ser.flush()
            self.light_on = False
            return True
        except serial.SerialException:
            self.ser = None
            return False

    def is_connected(self):
        return self.ser is not None and self.ser.is_open

    def send_command(self, cmd):
        if not self.is_connected():
            return False

        ser = self.ser
        if ser is None:
            return False

        try:
            ser.write(cmd)
            ser.flush()
            return True
        except serial.SerialException:
            return False

    def set_light(self, on):
        cmd = b'1' if on else b'0'
        ok = self.send_command(cmd)
        if ok:
            self.light_on = on
        return ok

    def toggle_light(self):
        return self.set_light(not self.light_on)

    def close(self):
        if not self.is_connected():
            return

        ser = self.ser
        if ser is None:
            return

        try:
            ser.write(b'0')
            ser.flush()
            ser.close()
        except serial.SerialException:
            pass
        finally:
            self.ser = None
            self.light_on = False


if __name__ == "__main__":
    controller = LightSwitchController()
    if not controller.connect():
        print(f"Could not open serial port {controller.port}")
    else:
        print("Connected. Press Enter to toggle light, type q and press Enter to quit.")
        try:
            while True:
                user_input = input().strip().lower()
                if user_input == "q":
                    break
                if controller.toggle_light():
                    print("LIGHT ON" if controller.light_on else "LIGHT OFF")
                else:
                    print("Failed to send command")
        finally:
            controller.close()

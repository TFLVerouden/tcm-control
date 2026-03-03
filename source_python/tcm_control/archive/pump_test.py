import pumpy3
import time

# Source code and documentation: https://github.com/Wetenschaap/pumpy3
# First ensure RS-232 settings on the PHD 2000 are configured. Press: Set >  RS-232 (choose PUMP CHAIN) > Enter (set address) > Enter (set baud rate) > Enter (confirm)

# Initialise chain
chain = pumpy3.Chain(
    "COM10",        # Manually specified, no way to auto-detect (yet)
    baudrate=19200,  # Set to match pump
    timeout=0.3     # 300 ms timeout, increase if unstable
)

# Initialise PHD 2000 with address = 0
pump = pumpy3.PumpPHD2000_Refill(chain, address=0, name="PHD2000")

# Configure pump
# Set syringe diameter in mm (10.3 mm <> 5 mL Hamilton
# gastight #1005, see app. A in manual)
pump.set_diameter(10.3)
pump.set_mode("PMP")        # Set to PuMP mode
pump.set_rate(0.2, "ml/mn")  # Set rate to 0.2 mL/min

pump.run()
time.sleep(2)
pump.stop()

# # import class
# from functions import pumpy
# # from archive import pumpy_orig as pumpy

# # Initialise chain
# chain = pumpy.Chain("COM10", baudrate=19200)

# # Initialise PHD 2000 with address = 0
# # pump = pumpy.Pump2000(chain, address=0)
# pump = pumpy.Pump(chain, address=0, name='PHD2000')

# # # pump.cvolume()
# # pump.clear_accumulated_volume()
# # # pump.setdiameter(3.26)
# # # pump.setdiameter(10000)
# # pump.setdiameter(7.28)
# # # pump.setinfusionrate(100, "u/m")
# # # pump.setwithdrawrate(100, "u/m")
# # pump.set_rate(100, "u/m")
# # # pump.settargetvolume(100, "u")
# # pump.settargetvolume(0.01)
# # # pump.infuse()
# pump.infuse()
# # pump.waituntilfinished()
# pump.waituntilfinished()

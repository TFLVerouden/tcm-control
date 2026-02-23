*To do in this document:*
- [ ] Check and add laser safety label/regulations here.
- [ ] Add link to (micro)rheology repo(s) once applicable.
- [ ] Add link to SprayTec lift (and other) class(es) once properly sorted.


# Component list
## Airflow
Connected by means of, among other components, Swagelok male connector fittings and tube adapters (see [catalogue & installation instructions](/docs/airflow/Swagelok_fittings_ms-01-140_catalogue.pdf)). Advantage of connecting via these tubes is that the parts can be turned in any desired direction, rather than the angle being limited to keeping seals tight.

[![Cough machine airflow diagram](/docs/schematics/cough_machine_airflow.jpg)](https://github.com/TFLVerouden/cough-machine-control/blob/main/docs/cough_machine_airflow.pdf?raw=true)

### Pressure regulator
*FESTO VPPE-3-1-1/8-10-420-E1*
- [Website manufacturer](https://www.festo.com/nl/nl/a/557776)
- [Datasheet](/docs/airflow/FESTO_pressureregulator_VPPE-3-1-18-10-420-E1_datasheet.pdf)
- [Installation manual](/docs/airflow/FESTO_pressureregulator_VPPE-3-1-18-10-420-E1_manual.pdf)
- [Catalogue/info](/docs/airflow/FESTO_pressureregulator_info.pdf)

The pressure regulator has three parameter presets that range from slow (Pr1) to fast with overshoot (Pr3). Preset 2 seems to suit our needs. Note that any inputs below 4.16 mA are interpreted as 4.00 mA.

Connected using a *Pepperl+Fuchs V15-W-2M-PVC* female M12 to 5-way unterminated cable.
- [Website manufacturer](https://nl.rs-online.com/web/p/sensor-actuator-cables/8919448)
- [Datasheet](/docs/electronics/PepperlFuchs_cable_pressureregulator_V15-W-2M-PVC_datasheet.pdf)

Device-side front view of connector:

![Pressure regulator connector](/docs/electronics/screenshots/FESTO_pressureregulator_cable_pins.png)

On breadboard left-to-right:

| Pin | Cable colour | Assignment                    |
| --- | ------------ | ----------------------------- |
| 1   | Brown (BN)   | 24 V power supply             |
| 2   | White (WH)   | −, 0 mA setpoint current      |
| 3   | Blue (BU)    | Ground (0 V)                  |
| 4   | Black (BK)   | +, 4-20 mA setpoint current   |
| 5   | Gray (GY)    | 4-20 mA analog out            |
| 6   |              | N.C. for 180° turn protection |


### Air reservoir
*FESTO CRVZS-10*
- [Website manufacturer](https://www.festo.com/nl/nl/a/160237)
- [Catalogue/info/specifications](/docs/airflow/FESTO_reservoir_CRVS10.pdf)

### Valve #1 (solenoid valve)
*FESTO VUVS-LT25-M32C-MZD-G14-F8-1C1*
- [Website manufacturer](https://www.festo.com/nl/nl/a/8035170/)
- [Datasheet](/docs/airflow/FESTO_valve1_VUVS-LT25-M32C-MZD-G14-F8-1C1%20datasheet.pdf)

### Valve #2 (proportional valve)
*FESTO MPYE-5-1/4-420-B*
- [Website manufacturer](https://www.festo.com/nl/nl/a/161980/)
- [Datasheet](/docs/airflow/FESTO_valve2_MPYE-5-14-420-B_datasheet.pdf)
- [Installation manual](/docs/airflow/FESTO_valve2_manual.pdf)
- [Catalogue/info](/docs/airflow/FESTO_valve2_info.pdf)

Connected using *Pepperl+Fuchs V1-G-2M-PUR* 4-way M12 to 4-way unterminated cable.
- [Website manufacturer](https://nl.rs-online.com/web/p/sensor-actuator-cables/8171585)
- [Datasheet](/docs/electronics/PepperlFuchs_cable_valve2_V1-G-2M-PUR_datasheet.pdf)

Device-side front view of connector:

![Valve 2 connector](/docs/electronics/screenshots/FESTO_valve2_cable_pins.png)

On breadboard left-to-right:
| Pin | Cable colour | Assignment                    |
| --- | ------------ | ----------------------------- |
| 1   | Brown (BN)   | 24 V power supply             |
| 2   | White (WH)   | Ground/- (0 V)                |
| 3   | Blue (BU)    | +, 12-20 mA setpoint current  |
| 4   | Black (BK)   | −, 0 mA setpoint current      |
| 5   |              | N.C. for 180° turn protection |

### Obsolete
- ~~Bronkhorst EL-FLOW Select F-113AC flow meter~~

## Electronics
[![Cough machine wiring diagram](/docs/schematics/cough_machine_wiring.png)](https://github.com/TFLVerouden/cough-machine-control/blob/main/docs/cough_machine_wiring.pdf?raw=true)

Note: when making any physical changes to the current loop of R-click or T-click, reset the microcontroller because the current will be incorrect (~ 2 mA) otherwise.

Breadboard top view:
![Cough machine control breadboard top view](/docs/breadboard_top_view.jpeg)

Breadboard bottom view:
![Cough machine control breadboard bottom view](/docs/breadboard_bottom_view.jpeg)

### Power supplies
*TracoPower TBLC-06-105* 5 V power supply unit (PSU)
- [Data sheet](/docs/electronics/TracoPower_tblc06_datasheet.pdf)
- [Manual](/docs/electronics/TracoPower_tblc06_installation.pdf)
- [Website manufacturer](https://www.tracopower.com/int/series/tblc)

*TracoPower TBLC-15-124* 24 V power supply unit (PSU)
- [Data sheet](/docs/electronics/TracoPower_tblc15_datasheet.pdf)
- [Manual](/docs/electronics/TracoPower_tblc15_installation.pdf)
- [Website manufacturer](https://www.tracopower.com/int/series/tblc)

### Control board
*Adafruit ItsyBitsy M4 Express* microcontroller unit (MCU)
- [Website manufacturer](https://learn.adafruit.com/introducing-adafruit-itsybitsy-m4/pinouts)
- [Website manufacturer Microchip ATSAMD51G19A](https://www.microchip.com/en-us/product/ATSAMD51G19A)
- [Data sheet Microchip ATSAMD51G19A](/docs/electronics/Adafruit_ItsyBitsy_M4_Express_datasheet_SAM-D5x-E5x.pdf)

The MCU handles communication between the PC and other components, as well as precise timing. 

### Current regulation
*MIKROE 4-20 mA T-click* current transmitter
- [Website manufacturer](https://www.mikroe.com/4-20ma-t-click)
- [Schematic](/docs/electronics/MIKROE_4-20mA_T_click_schematic.pdf)
- [Data sheet Texas Instruments XTR116 current loop transmitter](/docs/electronics/MIKROE_4-20mA_T_click_XTR116_datasheet.pdf)
- [Data sheet Microchip MCP4921 DAC/SPI interface](/docs/electronics/MIKROE_4-20mA_T_click_MCP4921_datasheet.pdf)
- [Data sheet Analog Devices ADuM1411 digital isolator](/docs/electronics/MIKROE_4-20mA_T_click_ADuM1411_datasheet.pdf)
- [Recommended control library](https://github.com/Dennis-van-Gils/MIKROE_4_20mA_RT_Click/tree/main)

Two T-click 4-20 mA current regulators are used. One to control the proportional valve (12 mA to close, 20 mA to 100% open; 4-12 mA range is not used), and another to control the pressure regulator (4 mA for 0.1 bar up to, theoretically, 20 mA for 10 bar). The calibration values for both T-click boards are:
| Bit value | Current (mA) |
|-----------|--------------|
| 796       | 3.97         |
| 3982      | 19.90        |


*MIKROE 4-20 mA R-click* current receiver
- [Website manufacturer](https://www.mikroe.com/4-20ma-r-click)
- [Schematic](/docs/electronics/MIKROE_4-20mA_R_click_schematic.pdf)
- [Data sheet Texas Instruments IN196 current shunt monitor](/docs/electronics/MIKROE_4-20mA_R_click_INA196_datasheet.pdf)
- [Data sheet Microchip MCP3201 ADC/SPI interface](/docs/electronics/MIKROE_4-20mA_R_click_MCP3201_datasheet.pdf)
- [Data sheet Maxim 6106 voltage reference](/docs/electronics/MIKROE_4-20mA_R_click_MAX6106_datasheet.pdf)
- [Data sheet Texas Instruments TPS61041 boost converter](/docs/electronics/MIKROE_4-20mA_R_click_TPS61041_datasheet.pdf)
- [Recommended control library](https://github.com/Dennis-van-Gils/MIKROE_4_20mA_RT_Click/tree/main)

The R-click 4-20 mA current receiver is used to read out the pressure on the tank. It is modified to act as passive current receiver (not supplying any voltage), see notes in the [MIKROE_4_20mA_RT_Click library](https://github.com/Dennis-van-Gils/MIKROE_4_20mA_RT_Click/tree/main/active_to_passive_R_click_modification). The calibration values are:
| Bit value | Current (mA) |
|-----------|--------------|
| 806       | 4.04         |
| 2191      | 10.98        |


### MOSFET driver
*Adafruit MOSFET driver*
- [Website manufacturer](https://learn.adafruit.com/adafruit-mosfet-driver)
- [Data sheet Alpha & Omega AO3406 MOSFET](/docs/electronics/Adafruit_MOSFET_driver_datasheet_AO3406.pdf)

Used to control the solenoid valve.

### Temperature & relative humidity sensor
*Adafruit SHT45 temperature \& humidity sensor*
- [Website manufacturer](https://learn.adafruit.com/adafruit-sht40-temperature-humidity-sensor)
- [Website manufacturer Sensirion SHT4X](https://sensirion.com/products/catalog/SHT45)
- [Data sheet Sensirion SHT4X](/docs/electronics/Adafruit_SHT45_datasheet_SHT4x.pdf)

### Trigger circuit
*Isocom 6N138 optocoupler*
- [Website supplier](https://nl.rs-online.com/web/p/optocouplers/1610989?srsltid=AfmBOopHfB2N8esy3AUzJydobraa8phtpUnF_R_vVBQSlnlFK72Xo9mU)
- [Data sheet](/docs/electronics/Isocom_optocoupler_6N138_datasheet.pdf)

The SprayTec and any other peripherals, like high-speed cameras, can be triggered with a 5 V signal that is pulled down to GND. The circuit uses an optocoupler to isolate the power supplies from "peripheral ground".


## PIV add-on
### Manual pressure regulator
*SMC IR2000-F02*
- [Website manufacturer](https://www.smcpneumatics.com/IR2000-F02.html)
- [Manual](/docs/piv_addon/SMC_pressureregulator_IR2000-F02_manual.pdf)

Pressure at the output is read out by *FESTO SPAB-P10R-F-PB-L1*
- [Website manufacturer](https://www.festo.com/nl/nl/a/8035539/)
- [Datasheet](/docs/piv_addon/FESTO_pressuresensor_SPAB-P10R-F-PB-L1_datasheet.pdf)
- [Manual](/docs/piv_addon/FESTO_pressuresensor_SPAB-P10R-F-PB-L1_manual.pdf)
- [Catalogue/info](/docs/piv_addon/FESTO_pressuresensor_info.pdf)

This is connected using the *FESTO NEBS-L1G4-K-2.5-LE4* cable.
- [Website manufacturer](https://www.festo.com/nl/nl/a/572576/)

Device-side front view of connector:

![Pressure sensor connector](/docs/electronics/screenshots/FESTO_pressuresensor_cable_pins.png)

On breadboard left-to-right:

| Breadboard pin | Device pin | Cable colour | Assignment         |
| -------------- | ---------- | ------------ | ------------------ |
| N.C. or 1      | 2          | Black (BK)   | N.C. (digital out) |
| 2              | 4          | Blue (BU)    | Ground (0 V)       |
| 3              | 3          | White (WH)   | 4-20 mA analog out |
| 4              | 1          | Brown (BN)   | 24 V power supply  |

### Laser
*Thorlabs CPS635R*
- [Website manufacturer](https://www.thorlabs.com/thorproduct.cfm?partnumber=CPS635R)
- [Datasheet](/docs/piv_addon/Thorlabs_laser_CPS635R-specsheet.pdf)


Mounted using a [Thorlabs MK11F/M laser diode mount](https://www.thorlabs.com/thorproduct.cfm?partnumber=MK11F/M)

### Photodiode
*Thorlabs PDA36A2*
- [Website manufacturer](https://www.thorlabs.com/thorproduct.cfm?partnumber=PDA36A2)
- [Manual](/docs/piv_addon/Thorlabs_photodiode_PDA36A2-manual.pdf)

Gain is set to 35 dB.


## Peripherals
### Syringe pump
*Harvard Apparatus PHD 2000*
- [Manual](/docs/peripherals/Harvard_PHD2000_syringe_pump_manual.pdf)
- [Recommended Python serial control code](https://github.com/WetenSchaap/pumpy3)

The pump is connected using a custom RJ12 to DB9 cable, which consists of an [Assmann AT-S-26-6-6-S-7](/docs/peripherals/pump_cable/Assmann_AT-S-26-6-6-S-7_RJ12_straight_through_cable.pdf) RJ12 straight-through cable[^1] and an [L-COM RBA096F](/docs/peripherals/pump_cable/L-COM_RBA096F_adaptor_DB9F-RJ12.pdf) RJ12 to DB9 female adapter. They are connected as follows:

| Pump pin | Cable conn. | Wire colour | Adapter conn. | Assignment |
|----------|-------------|-------------|---------------|------------|
| 1        | 1 - 1       | White (WH)  | 1 - 9         | N.C.       |
| 2        | 2 - 2       | Black (BK)  | **2 - 3**     | Ground     |
| 3        | 3 - 3       | Red (RD)    | **3 - 2**     | Ground     |
| 4        | 4 - 4       | Green (GN)  | **4 - 5**     | Transmit   |
| 5        | 5 - 5       | Yellow (YL) | **5 - 4**     | Receive    |
| 6        | 6 - 6       | Blue (BL)   | 6 - 1         | N.C.       |

RS-232 IN port pin numbering on the pump (front view):
![Pump RS-232 pinout](/docs/peripherals/pump_cable/Harvard_PHD2000_RS232_RJ12_pins.png)

RJ12 to DB9 adapter pin numbering (front views):
![RJ12 to DB9 adapter](/docs/peripherals/pump_cable/L-COM_adapter_pinout.png)

In the pump settings, make sure to set the correct syringe diameter. Commonly used Hamilton-Microliter Series Gastight syringes. Table also callable by cough machine control software in [syringe_sizes.csv](/source_python/tcm_control/config/syringe_sizes.csv)[^2]:
| Volume (mL) | Diameter (mm) |
| ----------- | ------------- |
| 1.0         | 4.61          |
| 2.5         | 7.28          |
| 5.0         | 10.3          |

[^1]: "[A straight cord] is principally used for data, while reverse cords are for voice services. Straight cords feature an exactly duplicated arrangement of wires to pin connections on either side of the cable, while in reverse cables, the order of connections is mirrored i.e. in reverse order on the second side", from [RS-online](https://uk.rs-online.com/web/content/discovery/ideas-and-advice/telephone-cable-guide).
[^2]: Adapted from page 50 [in the manual](/docs/peripherals/Harvard_PHD2000_syringe_pump_manual.pdf): "Syringe Diameters in mm", section "Hamilton-Microliter Series Gastight".

### USB-RS232 hub
*StarTech ICUSB2324I*
- [Website manufacturer](https://www.startech.com/nl-nl/kaarten-peripherals/icusb2324i?srsltid=AfmBOopFQCteDwa-6x80QMKLGdYEHS63esR50nsnaFysBw_U2jR4mku1)
- [Manual](/docs/electronics/StarTech_ICUSB2324I_manual.pdf)
- [Schematic](/docs/electronics/StarTech_ICUSB2324I_diagram.pdf)
- [Data sheet](/docs/electronics/StarTech_ICUSB2324I_datasheet.pdf)

Currently only used to communicate with the syringe pump. 

### Laser diffraction particle sizer
*Malvern SprayTec*
- [Website manufacturer](https://www.malvernpanalytical.com/en/products/product-range/spraytec)
- [Manual](/docs/peripherals/Malvern_SprayTec_manual.pdf)
- [Presentation before installation](/docs/peripherals/Malvern_SprayTec_installation_slides.pdf)
- [Brochure](/docs/peripherals/Malvern_SprayTec_brochure.pdf)
- [Troubleshooting: set trigger for dilute sprays](/docs/peripherals/spraytec/SprayTec_support_set_trigger_dilute_spray.pdf)
- [Troubleshooting: ambient light](/docs/peripherals/spraytec/SprayTec_support_ambient_light.pdf)
- [Troubleshooting: alarms at low signal](/docs/peripherals/spraytec/SprayTec_support_alarm_at_low_signal.pdf)
    
The SprayTec sits on top of a lift that can be controlled over serial.

### Optics
The distortion targets we use in our lab for calibrating high-speed video recordings are the [Thorlabs R2L2S3P3 (500 μm)](https://www.thorlabs.com/thorproduct.cfm?partnumber=R2L2S3P3) and [R2L2S3P4 (1 mm)](https://www.thorlabs.com/thorproduct.cfm?partnumber=R2L2S3P4) glass targets. They are positioned using the [B3C/M](https://www.thorlabs.com/thorproduct.cfm?partnumber=B3C/M) platform and [FFM1](https://www.thorlabs.com/thorproduct.cfm?partnumber=FFM1) holder. 

### Rheometry
Characterisation of the liquids is done using an Anton Paar rheometer.
- [Software quickstart](/docs/peripherals/AntonPaar_RheoCompass_quickstart.pdf)
- [Software manual](/docs/peripherals/AntonPaar_RheoCompass_manual.pdf)
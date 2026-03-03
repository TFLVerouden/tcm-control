# cough-machine-control

Install tcm-utilities:
pip install -e ../tcm-utils

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
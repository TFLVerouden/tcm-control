import os
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
import sys
plot_path = r"C:\Users\sikke\Documents\GitHub\cough-machine-control\valve_control\data"
files = [os.path.join(plot_path, f) for f in os.listdir(plot_path) if f.endswith('.csv')]

filtered_files  =  [f for f in files if "PEO0dot03" in f]
print(filtered_files)
fig, ax1 = plt.subplots()
ax1.set_xlabel('Time (s)')
ax1.legend()
ax1.set_ylabel('Flow rate (L/s)')
ax2 = ax1.twinx()
for file in filtered_files:
    #plotname = os.path.join(data_dir, f'{timestamp}_{experiment_name}.png')
    plot_info =pd.read_csv(file,delimiter=",",nrows=7,encoding='latin')
    readings = pd.read_csv(file,delimiter=",",skiprows=8,encoding='latin')

    plotdata= np.array(readings)
    print(plotdata)
    print(np.shape(plotdata))
   
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

    ax1.plot(t, plotdata[:,2], 'b-',label= "Measurement",marker= "",markeredgecolor= "k")
   

    # ax1.set_title(f'Exp: {experiment_name}, open: {duration_ms} ms \n'
    #                 f' CFPR: {CFPR:.1f} L/s, PVT: {PVT:.2f} s, CEV: {CEV:.1f} L\n'
    #                 f'T: {Temperature} °C, RH: {RH} %, lift: {height} mm')
    # ax1.grid()


    ax2.plot(t, plotdata[:,1], 'g-',label= "Pressure")

    #plt.savefig(plotname)
ax2.set_ylabel('Pressure (bar)')
ax2.tick_params(axis='y', labelcolor='g')
ax2.set_ylim(bottom=0)

plt.tight_layout()
plt.show()
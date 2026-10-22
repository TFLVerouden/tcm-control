import numpy as np
import matplotlib.pyplot as plt
import matplotlib.tri as tri
from scipy.stats import gaussian_kde
import matplotlib.cm as cm
from mpl_toolkits.mplot3d import Axes3D

#all thresholded at cv<1000, t<80 ms

t_283 = {'30mm': np.float64(40.03), '20mm': np.float64(38.16), '10mm': np.float64(31.27777777777778), 
         '0mm': np.float64(28.277777777777782), '-10mm': np.float64(31.78), '-20mm': np.float64(32.0),
           '-30mm': np.float64(32.31), '-40mm': np.float64(30.22222222222222), '-50mm': np.float64(31.833333333333332)}
std_283 = {'30mm': np.float64(3.9174098585672654), '20mm': np.float64(4.436935879635855),
            '10mm': np.float64(4.231831171222264), '0mm': np.float64(3.3425797681091822), 
            '-10mm': np.float64(2.973482806407328), '-20mm': np.float64(4.050678955434508), 
            '-30mm': np.float64(3.3995440870799136), '-40mm': np.float64(9.662272308977816), 
            '-50mm': np.float64(7.581556568409946)}

t_258 = {'30mm': np.float64(32.22), '20mm': np.float64(32.56), '10mm': np.float64(28.540000000000003), 
         '0mm': np.float64(29.630000000000006), '-10mm': np.float64(29.166666666666668), 
         '-20mm': np.float64(33.63333333333333), '-30mm': np.float64(29.610000000000003), '-40mm': np.float64(32.41), 
         '-50mm': np.float64(35.05555555555555)}
std_258 = {'30mm': np.float64(4.96382916708462), '20mm': np.float64(6.887408801574073), '10mm': np.float64(5.0507821176526715), 
           '0mm': np.float64(3.3460573814565695), '-10mm': np.float64(4.2026446699931945), '-20mm': np.float64(4.330511901996498),
             '-30mm': np.float64(2.7380467490530553), '-40mm': np.float64(3.890102826404464), '-50mm': np.float64(2.669627985365546)}

t_233 ={'30mm': np.float64(40.79), '20mm': np.float64(32.6), '10mm': np.float64(26.620000000000005), 
        '0mm': np.float64(22.09), '-10mm': np.float64(29.419999999999998), '-20mm': np.float64(27.74), 
        '-30mm': np.float64(29.49), '-40mm': np.float64(30.555555555555557)}
std_233 = {'30mm': np.float64(2.72119459061641), '20mm': np.float64(4.905507109361884), '10mm': np.float64(3.145409353327481), 
           '0mm': np.float64(6.163351361069723), '-10mm': np.float64(3.8829885397719113), '-20mm': np.float64(3.0858386218336173), 
           '-30mm': np.float64(2.1856120424265604), '-40mm': np.float64(3.6585094448456306)}

t_208 ={'30mm': np.float64(34.870000000000005), '20mm': np.float64(35.62), '10mm': np.float64(29.1), 
        '0mm': np.float64(24.690000000000005), '-10mm': np.float64(21.439999999999998), '-20mm': np.float64(21.6), 
        '-30mm': np.float64(21.099999999999998), '-40mm': np.float64(24.049999999999997)}

std_208 = {'30mm': np.float64(3.7215722483918006), '20mm': np.float64(3.0317651624095157), '10mm': np.float64(3.868074456367146), 
           '0mm': np.float64(3.7128021762544803), '-10mm': np.float64(2.715216381800905), '-20mm': np.float64(2.8206382256503577),
             '-30mm': np.float64(2.05815451315007), '-40mm': np.float64(2.365375234502975)}
t_183={'30mm': np.float64(28.899999999999995), '20mm': np.float64(28.380000000000003), '10mm': np.float64(23.799999999999994),
        '0mm': np.float64(24.979999999999997), '-10mm': np.float64(24.31), '-20mm': np.float64(24.720000000000002),
          '-30mm': np.float64(26.380000000000003), '-40mm': np.float64(24.69)}
std_183 = {'30mm': np.float64(4.982770313791315), '20mm': np.float64(4.64581532134027), '10mm': np.float64(1.26095202129185), '0mm': np.float64(3.386384502681289),
            '-10mm': np.float64(1.7311556833514423), '-20mm': np.float64(1.754308980767071), 
            '-30mm': np.float64(3.620441961970941), '-40mm': np.float64(1.821235844145397)}
t_158 = {'30mm': np.float64(20.95), '20mm': np.float64(12.3125), '10mm': np.float64(24.11), '0mm': np.float64(15.87),
          '-10mm': np.float64(26.54), '-20mm': np.float64(17.9), '-30mm': np.float64(18.544444444444444)}
std_158={'30mm': np.float64(11.11721637821267), '20mm': np.float64(2.230155543902712), '10mm': np.float64(2.552821967940576), 
         '0mm': np.float64(6.005339290997637), '-10mm': np.float64(4.015519891620511), '-20mm': np.float64(3.81051177665153),
           '-30mm': np.float64(2.942452156171451)}

t_133={'20mm': np.float64(21.88), '10mm': np.float64(10.39), '0mm': np.float64(20.955555555555556), '-10mm': np.float64(17.06), '-20mm': np.float64(19.071428571428573), '-30mm': np.float64(12.67)}
std_133={'20mm': np.float64(8.318509481872338), '10mm': np.float64(3.1239238146920294), '0mm': np.float64(6.551693777797058), '-10mm': np.float64(7.601868191438207), '-20mm': np.float64(7.801412744902461), '-30mm': np.float64(3.7100000000000004)}

t_108={'20mm': np.float64(15.220000000000002), '10mm': np.float64(24.9), '0mm': np.float64(24.76), '-10mm': np.float64(25.32), '-20mm': np.float64(18.130000000000003)}
std_108={'20mm': np.float64(3.1083114387075184), '10mm': np.float64(1.1331372379372238), '0mm': np.float64(1.6438978070427621), '-10mm': np.float64(0.8195120499419152), '-20mm': np.float64(8.280948013361755)}

t_83={'20mm': np.float64(26.410000000000004), '10mm': np.float64(23.32), '0mm': np.float64(14.169999999999998), '-10mm': np.float64(20.25)}
std_83={'20mm': np.float64(13.810318606027884), '10mm': np.float64(0.6462197768561407), '0mm': np.float64(3.008670802862952), '-10mm': np.float64(4.2131342252532145)}

t_58={'10mm': np.float64(18.1), '0mm': np.float64(12.180000000000001)}
std_58={'10mm': np.float64(3.424324750954559), '0mm': np.float64(3.3943482437722854)}

t_33={'0mm': np.float64(13.720000000000002)}
std_33={'0mm': np.float64(4.930476650385843)}

data = {
    283: t_283, 208: t_208, 183: t_183, 158: t_158, 133: t_133, 108: t_108, 83: t_83, 58: t_58, 33: t_33}

std_data = {
    283: std_283, 208: std_208, 183: std_183, 158: std_158, 133: std_133, 108: std_108, 83: std_83, 58: std_58, 33: std_33}

y_coor, z_coor, t_vals = [],[],[]
for y, z in data.items():
    for z_key, t in z.items():
        z_coord = int(z_key.replace("mm", ""))
        y_coor.append(y)
        z_coor.append(z_coord)
        t_vals.append(t)

y =np.array(y_coor)
z = np.array(z_coor)
t = np.array(t_vals)

##3d plot of t values:
fig = plt.figure()
ax = fig.add_subplot(111, projection='3d')
sc = ax.scatter(y, z, t, c=t, cmap='viridis', s=100)
plt.colorbar(sc, ax=ax, label='Peak time (ms)')
ax.set_xlabel('y (mm)')
ax.set_ylabel('z (mm)')
ax.set_zlabel('Peak time (ms)')
plt.tight_layout()
plt.show()

#z-t plot

items = list(data.items())
half = len(items) // 2
splits = [items[:half], items[half:]]

for i, split in enumerate(splits):
    fig, axes = plt.subplots(len(split), 1, figsize=(6, 3*len(split)), sharex=True)
    if len(split) == 1:
        axes = [axes]  # ensure iterable if only one subplot


    for ax, (y_coord, z_dict) in zip(axes, split):
              z_coords = [int(k.replace("mm", "")) for k in z_dict.keys()]
              t_values = list(z_dict.values())
              std_values = list(std_data.get(y_coord, {}).values())
              
              ax.plot(z_coords, t_values , marker='o')
              ax.errorbar(z_coords, t_values, yerr=std_values/np.sqrt(10), fmt='o', ecolor='red', capsize=5)
              ax.set_title(f'y = {y_coord} mm')
              ax.set_ylabel('Peak time (ms)')
    axes[-1].set_xlabel('z (mm)')
    plt.tight_layout()
    plt.show()
    plt.close(fig)


fig, ax = plt.subplots()
colors = cm.tab20(np.linspace(0, 1, len(data)))  # up to 20 distinct colors
for (y_coord, z_dict), color in zip(data.items(), colors):
    z_coords = [int(k.replace("mm", "")) for k in z_dict.keys()]
    t_values = list(z_dict.values())
    ax.plot(z_coords, t_values, marker='o', label=f'y = {y_coord} mm', color=color)
    ax.errorbar(z_coords, t_values, yerr=std_values/np.sqrt(10), fmt='o', capsize=5, color=color)
ax.set_xlabel('z (mm)')
ax.set_ylabel('Peak time (ms)')
ax.legend()
plt.tight_layout()
plt.show()
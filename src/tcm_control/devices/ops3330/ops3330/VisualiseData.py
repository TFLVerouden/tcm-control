import os
from pathlib import Path

path = Path(__file__).parent.parent / "data" # / "Sprayer_tests"
os.chdir(path)

from tsitools import ParticleData
import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
import matplotlib.ticker as ticker

# Apply seaborn style
sns.set_style('darkgrid')

# Read the data
data1 = []
for suffix in ['33']:
# for suffix in ['21', '22', '23', '24', '25', '27', '28', '29']:
    data1.append(ParticleData(directory='./', suffix=suffix, oversize_bin_cutoff=12.4))

# data2 = []
# for suffix in ['21', '22', '23', '24', '25', '26', '27', '28', '29', '30']:
#     data2.append(ParticleData(directory='./', suffix=suffix, oversize_bin_cutoff=12.4, use_volume=True))
    
# -----------------------
# Count vs Diameter Plot
# -----------------------

for data in [data1]:
    # Stack the arrays, calculate the average and standard deviation for each bin

    # for d in data:
    #     counts = []
    #     for index, row in d._data.iterrows():
    #         counts.append(row[1:d._num_bins+1].values)  # Ensure to extract values as a list
    #     background = np.mean(counts[-5:], axis=0)
    #     # # print(background)
    #     # print(counts)
    #     # stacked_sums = np.sum(counts[0], axis=0)  # - background  # Subtract the background from each sum_counts array

    #     length = len(d.time_points)
    #     # print(background)
    #     stacked_sums = np.stack([d.sum_counts], axis=0) # - length * background # Subtract the background from each sum_counts array
        # print(stacked_sums)
        # print(stacked_sums)



    stacked_sums = np.stack([d.sum_counts for d in data], axis=0)
    average_sums = np.mean(stacked_sums, axis=0)
    std_sums = np.std(stacked_sums, axis=0)

    # Convert the width from log scale to linear scale for each bar center
    widths = data[0].calculate_bar_plot_widths(log_base=10, bar_width=0.25)

    # Create a bar plot with adjusted widths and error bars
    plt.figure(figsize=(7, 5))
    bars = plt.bar(
        data[0].mean_diameters,
        average_sums,
        width=widths,
        align='center',
        yerr=std_sums,
        capsize=5,
        color='skyblue',
        edgecolor='black',
        linewidth=1
    )

# Add grid lines
plt.grid(True, which='both', linestyle='--', linewidth=0.5)

# Use scientific notation for the y-axis
plt.gca().yaxis.set_major_formatter(ticker.ScalarFormatter(useMathText=True))
plt.ticklabel_format(style='sci', axis='y', scilimits=(0, 0))

# Customize axes and title
plt.xscale('log')
plt.xlabel('Diameter (μm)', fontsize=12)
plt.ylabel('Count (#)', fontsize=12)
plt.title('Count vs Diameter', fontsize=14)

# Show plot
plt.tight_layout()
plt.show()


# -----------------------
# Volume vs Diameter Plot
# -----------------------

# Stack the arrays, calculate the average and standard deviation for each bin
stacked_sums = np.stack([d.sum_volumes for d in data], axis=0)
average_sums = np.mean(stacked_sums, axis=0)
std_sums = np.std(stacked_sums, axis=0)

# Convert the width from log scale to linear scale for each bar center
widths = data[0].calculate_bar_plot_widths(log_base=10, bar_width=0.25)

# Enhance the plot with additional styling
plt.figure(figsize=(7, 5))

# Create a bar plot with adjusted widths and error bars
bars = plt.bar(
    data[0].mean_diameters,
    average_sums,
    width=widths,
    align='center',
    yerr=std_sums,
    capsize=5,
    color='coral',
    edgecolor='black',
    linewidth=1
)

# Add grid lines
plt.grid(True, which='both', linestyle='--', linewidth=0.5)

# Use scientific notation for the y-axis
plt.gca().yaxis.set_major_formatter(ticker.ScalarFormatter(useMathText=True))
plt.ticklabel_format(style='sci', axis='y', scilimits=(0, 0))

# Customize axes and title
plt.xscale('log')
plt.xlabel('Diameter (μm)', fontsize=12)
plt.ylabel('Average Volume (fL)', fontsize=12)
plt.title('Averaged Volume vs Diameter', fontsize=14)

# Show plot
plt.tight_layout()
plt.show()






# -----------------------
# Counts over Time
# -----------------------

colors = ['indianred', 'forestgreen', 'deepskyblue']

# Extract the time points from one of the files
time_points = data1[0].time_points

time_data = []
for d in data:
    time_data.append(d.get_count_over_time())
    if d.get_count_over_time().shape[0] != len(time_points):
        print(f"Warning: Time points mismatch for suffix {d.suffix}. Expected {len(time_points)}, got {d.get_count_over_time().shape[0]}.")

# Stack the arrays along a new dimension and obtain average and standard deviation
stacked_total = np.stack(time_data, axis=0)
average_total = np.mean(stacked_total, axis=0)
std_total = np.std(stacked_total, axis=0)

# Plot counts over time for all bins combined as well as bins 1 and 6
plt.figure(figsize=(7, 5))
plt.errorbar(time_points, average_total, yerr=std_total, fmt='o--', markerfacecolor='white', markersize=8, color='skyblue', label='Total Count', capsize=5)

# Use scientific notation for the y-axis
plt.gca().yaxis.set_major_formatter(ticker.ScalarFormatter(useMathText=True))
plt.ticklabel_format(style='sci', axis='y', scilimits=(0, 0))

plt.xlabel('Time (s)', fontsize=12)
plt.ylabel('Particle Count (#)', fontsize=12)
plt.title('Particle Count Over Time', fontsize=14)
plt.legend()
plt.tight_layout()
plt.show()
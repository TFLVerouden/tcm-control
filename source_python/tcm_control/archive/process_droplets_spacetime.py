import numpy as np

# Open droplet_times.npz
data = np.load('dripping_droplets_tests/droplet_times.npz')
droplet_times = data['droplet_times']

# Calculate inter-droplet intervals
intervals = np.diff(droplet_times)
mean_interval = np.mean(intervals)
std_interval = np.std(intervals)

print(f"Mean inter-droplet interval: {mean_interval:.3f} s")
print(f"Standard deviation of inter-droplet intervals: {std_interval:.3f} s")

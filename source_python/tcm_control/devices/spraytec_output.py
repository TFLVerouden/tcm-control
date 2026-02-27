from datetime import datetime
import os
import numpy as np


# ------------------------------------------------------------------------------
# LEGACY FUNCTIONS
# ------------------------------------------------------------------------------


def split_array_by_header_marker(arr, marker='Date-Time'):
    arr = np.array(arr)
    header = arr[:, 0]
    rows = arr[:, 1:]

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
    # current_dir = os.path.dirname(os.path.abspath(__file__))
    # parent_path = os.path.dirname(current_dir)  # one level up
    spraytec_path = os.path.join("C:\\CoughMachineData\\SprayTec\\")
    path = os.path.join(spraytec_path, "SPRAYTEC_APPEND_FILE.txt")
    save_path = os.path.join(spraytec_path, "individual_data_files")
    file = np.loadtxt(path, dtype=str, delimiter=',')
    split_sections = split_array_by_header_marker(file)
    last_file = split_sections[-1]
    time_created = last_file[1, 0]
    filename = last_file[1, 1]
    dt = datetime.strptime(time_created, '%d %b %Y %H:%M:%S.%f')
    # Format as YYYY_MM_DD_HH_MM
    file_name_time = dt.strftime('%Y_%m_%d_%H_%M')
    save_path = os.path.join(
        save_path, file_name_time + "_" + filename + ".txt")
    if not os.path.exists(save_path):
        np.savetxt(save_path, last_file, fmt='%s', delimiter=',')
        print(f"Saved spraytec_data of {file_name_time}")

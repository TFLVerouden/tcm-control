import tkinter as tk
from tkinter import filedialog
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
import numpy as np
import warnings

# Uncomment if you have cvd_check available
from tcm_utils import cvd_check as cvd
cvd.set_cvd_friendly_colors

warnings.filterwarnings('ignore')


def _combined_legend(ax1, ax2=None, loc='upper left', fontsize=9):
    """Create a combined legend from ax1 and (optionally) ax2."""
    handles1, labels1 = ax1.get_legend_handles_labels()
    handles = list(handles1)
    labels = list(labels1)

    if ax2 is not None:
        handles2, labels2 = ax2.get_legend_handles_labels()
        for h, l in zip(handles2, labels2):
            if l not in labels:
                handles.append(h)
                labels.append(l)

    ax1.legend(handles, labels, loc=loc, fontsize=fontsize)


def select_file(title):
    """Open file dialog to select a CSV file."""
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    file_path = filedialog.askopenfilename(
        parent=root,
        title=title,
        filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
    )
    root.destroy()
    return file_path


def read_piv_data(file_path):
    """
    Read PIV data CSV file (needs clean single header row).
    """
    try:
        # PIV data has a simple single header row, read directly
        df = pd.read_csv(file_path, skipinitialspace=True)

        # Clean up whitespace in column names
        df.columns = df.columns.str.strip()

        print(f"\nPIV Data Columns: {df.columns.tolist()}")
        print(f"Number of rows: {len(df)}")
        print("First few rows:")
        print(df.head())

        return df
    except Exception as e:
        print(f"Error reading PIV data CSV: {e}")
        return None


def read_valve_data(file_path):
    """
    Read valve data CSV file with all metadata rows at top.
    """
    try:
        # Find the header row and extract T0
        t0 = None
        header_row_idx = None

        with open(file_path, 'r') as f:
            lines = f.readlines()

        for i, line in enumerate(lines):
            # Extract Trigger T0
            if 'Trigger T0' in line and '(us)' in line:
                try:
                    parts = line.split(',')
                    if len(parts) > 1:
                        t0 = float(parts[1].strip())
                except:
                    pass

            # Find the header row (contains 'us,v1 action' etc.)
            stripped = line.strip()
            if stripped.startswith('us,') or stripped.startswith('us '):
                header_row_idx = i
                print(f"Found header at line {i}: {stripped[:60]}")
                break

        if header_row_idx is None:
            raise ValueError(
                "Could not find data header row starting with 'us'")

        # Read CSV with the header at the correct position
        rows_to_skip = list(range(header_row_idx))

        df = pd.read_csv(
            file_path,
            skiprows=rows_to_skip,
            on_bad_lines='skip'
        )

        # Process the data
        df.columns = df.columns.str.strip()
        print(f"Columns found: {df.columns.tolist()}")

        # Remove empty rows
        df = df.dropna(how='all').reset_index(drop=True)

        # Convert to numeric
        df['us'] = pd.to_numeric(df['us'], errors='coerce')
        df['v1 action'] = pd.to_numeric(df['v1 action'], errors='coerce')

        # Remove rows where conversion failed
        df = df.dropna(subset=['us', 'v1 action']).reset_index(drop=True)

        print(f"Data shape after cleaning: {df.shape}")
        print(f"First few rows:\n{df.head()}")

        # Extract valve times
        closing = df['v1 action'] == 0
        opening = df['v1 action'] == 1

        if not closing.any():
            raise ValueError("No closing action (v1 action = 0) found")
        if not opening.any():
            raise ValueError("No opening action (v1 action = 1) found")

        closing_time = df.loc[closing, 'us'].iloc[0]
        opening_time = df.loc[opening, 'us'].iloc[0]

        df.attrs['t0'] = t0

        print(f"\nTrigger T0: {t0} µs")
        print(f"Opening: {opening_time} µs")
        print(f"Closing: {closing_time} µs")
        print(f"Final data shape: {df.shape}")

        return df, opening_time, closing_time

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return None, None, None


def get_valve_opening(setpoint_mA):
    if setpoint_mA == -1.0:
        return None
    dict = {12.0: 0.0, 12.1: 0.00261, 12.2: 0.004617, 12.3: 0.006223, 12.4: 0.007629, 12.5: 0.009038, 12.6: 0.010651, 12.7: 0.01267, 12.8: 0.015298, 12.9: 0.018737, 13.0: 0.023187, 13.1: 0.028852, 13.2: 0.035892, 13.3: 0.04405, 13.4: 0.052834, 13.5: 0.061749, 13.6: 0.070547, 13.7: 0.079887, 13.8: 0.090635, 13.9: 0.103656, 14.0: 0.119699, 14.1: 0.138445, 14.2: 0.159008, 14.3: 0.180494, 14.4: 0.2021, 14.5: 0.223325, 14.6: 0.243735, 14.7: 0.262907, 14.8: 0.28105, 14.9: 0.299249, 15.0: 0.318644, 15.1: 0.339537, 15.2: 0.36084, 15.3: 0.381332, 15.4: 0.399795, 15.5: 0.415417, 15.6: 0.428971, 15.7: 0.44161, 15.8: 0.454487, 15.9: 0.468757,
            16.0: 0.485531, 16.1: 0.504894, 16.2: 0.525887, 16.3: 0.547501, 16.4: 0.568727, 16.5: 0.588557, 16.6: 0.606221, 16.7: 0.621993, 16.8: 0.636433, 16.9: 0.650103, 17.0: 0.663563, 17.1: 0.677362, 17.2: 0.691708, 17.3: 0.706415, 17.4: 0.721278, 17.5: 0.736089, 17.6: 0.750649, 17.7: 0.764894, 17.8: 0.778882, 17.9: 0.792673, 18.0: 0.806331, 18.1: 0.819916, 18.2: 0.833476, 18.3: 0.846996, 18.4: 0.860448, 18.5: 0.873805, 18.6: 0.887038, 18.7: 0.90012, 18.8: 0.913022, 18.9: 0.925717, 19.0: 0.938176, 19.1: 0.950373, 19.2: 0.962278, 19.3: 0.973864, 19.4: 0.985103, 19.5: 0.995967, 19.6: 1.0, 19.7: 1.0, 19.8: 1.0, 19.9: 1.0, 20.0: 1.0, 20.1: 1.0}
    return dict.get(setpoint_mA)


def identify_columns(piv_df, valve_df):
    """
    Identify columns by known indices.
    PIV data: time_s is column [1], flow_rate is column [3]
    Valve data: time (us) is column [0], setpoint mA is column [2], pressure is column [3]
    """
    # Get columns by index
    piv_cols = piv_df.columns.tolist()
    valve_cols = valve_df.columns.tolist()

    # Use known indices
    time_col_piv = piv_cols[1]
    flow_rate_col = piv_cols[3]
    time_col_valve = valve_cols[0]
    action_col = valve_cols[1]
    setpoint_col = valve_cols[2]
    pressure_col = valve_cols[3]

    return {
        'piv_time_col': time_col_piv,
        'flow_rate_col': flow_rate_col,
        'valve_time_col': time_col_valve,
        'action_col': action_col,
        'setpoint_col': setpoint_col,
        'pressure_col': pressure_col
    }


def get_iso_flow_rate(P_upstream, P_downstream, T_upstream, C, b):
    """
    Calculates flow rate Q according to ISO 6358 standards.
    P_upstream, P_downstream: Absolute pressure (bar)
    C: Sonic Conductance (L/s/bar)
    b: Critical pressure ratio
    """
    if P_downstream >= P_upstream:
        return 0.0

    T0 = 293.15
    pressure_ratio = P_downstream / P_upstream

    if pressure_ratio <= b:
        Q = C * P_upstream * np.sqrt(T0 / T_upstream)
    else:
        Q = C * P_upstream * np.sqrt(T0 / T_upstream) * \
            np.sqrt(1 - ((pressure_ratio - b) / (1 - b))**2)

    return Q


def new_calculate_theoretical_flow(valve_df, pressure_col, opening_time, closing_time):
    """Calculate theoretical flow rate using ISO 6358 standards."""

    # THESE VALUES ARE NOT USED ANYMORE. HAVE NOT BEEN USED FOR A WHILE FOR THE FLOW GOAL COMPARISON. WILL NOT DISTINGUISH BETWEEN PROP AND SOL
    C = 6.25  # Sonic Conductance (L/s/bar)
    b = 0.23   # Critical pressure ratio
    T_upstream = 293.15  # Temperature in Kelvin
    P_downstream = 1.01325  # Atmospheric pressure in bar

    valve_df = valve_df.copy()
    valve_df['theoretical_flow_L_s'] = 0.0

    for idx, row in valve_df.iterrows():
        time_us = row['us']
        P_upstream = row[pressure_col]

        if time_us < opening_time or time_us > closing_time:
            valve_df.at[idx, 'theoretical_flow_L_s'] = 0.0
            continue

        setpoint_mA = row.get('setpoint/mA', -1.0)
        valve_opening = get_valve_opening(setpoint_mA)

        if valve_opening is None or valve_opening == 0:
            valve_df.at[idx, 'theoretical_flow_L_s'] = 0.0
        else:
            C_effective = C * valve_opening
            flow_rate = get_iso_flow_rate(
                P_upstream, P_downstream, T_upstream, C_effective, b)
            valve_df.at[idx, 'theoretical_flow_L_s'] = flow_rate

    return valve_df


def synchronize_data(piv_df, valve_df, columns, opening_time, closing_time):
    """
    Synchronize PIV and valve data to a common time base.
    """
    # Configuration
    calibration_image_size_px = 1280
    video_image_size_px = 896
    cropping_factor_px = 72
    piv_scaling_factor = (video_image_size_px - 2 *
                          cropping_factor_px) / calibration_image_size_px
    piv_trigger_delay_s = 0.01
    piv_flow_delay = 0.0074

    time_col_piv = columns['piv_time_col']
    flow_rate_col = columns['flow_rate_col']
    time_col_valve = columns['valve_time_col']
    setpoint_col = columns['setpoint_col']
    pressure_col = columns['pressure_col']
    action_col = columns['action_col']

    # Get the T0 trigger time from valve data metadata
    t0_us = valve_df.attrs.get('t0')

    if t0_us is None:
        print(
            "Warning: Trigger T0 not found in metadata, using first valve time as reference")
        t0_us = valve_df[time_col_valve].iloc[0]

    # PIV data processing
    piv_df_sync = piv_df.copy()
    piv_df_sync['time_s'] = piv_df_sync[time_col_piv] + piv_trigger_delay_s

    # Scale the PIV flow rate
    if piv_scaling_factor != 1.0:
        piv_df_sync[flow_rate_col] = piv_df_sync[flow_rate_col] * \
            piv_scaling_factor

    # Valve data processing
    valve_df_sync = valve_df.copy()
    valve_df_sync['time_s'] = (valve_df_sync[time_col_valve] - t0_us) / 1e6

    # Calculate theoretical flow
    valve_df_sync = new_calculate_theoretical_flow(
        valve_df_sync, pressure_col, opening_time, closing_time)

    # Clean data
    piv_df_sync = piv_df_sync.dropna(subset=[flow_rate_col])
    valve_df_sync = valve_df_sync.dropna(subset=[setpoint_col])

    # Sort by time
    piv_df_sync = piv_df_sync.sort_values('time_s').reset_index(drop=True)
    valve_df_sync = valve_df_sync.sort_values('time_s').reset_index(drop=True)

    return piv_df_sync, valve_df_sync, flow_rate_col, setpoint_col, action_col


def synchronize_piv_like(piv_like_df, piv_time_col, flow_rate_col):
    """
    Apply the SAME time and flow adjustments used for the PIV stream to a PIV-like file
    (this is the external Goal flow CSV which has the same format as the PIV CSV).
    Returns a copy with a 'time_s' column and adjusted flow column.
    """
    # Configuration (must match synchronize_data) ---
    calibration_image_size_px = 1280
    video_image_size_px = 896
    cropping_factor_px = 72
    piv_scaling_factor = (video_image_size_px - 2 *
                          cropping_factor_px) / calibration_image_size_px
    # This is the delay caused by the solenoid opening 10ms before executing the flow profile series! There is of course no piv trigger delay, because it is no measurement
    solenoid_execution_delay_s = 0.01

    df = piv_like_df.copy()

    # Time sync (same rule as PIV)
    # trigger-aligned time without any FRL (flow-response-lag) correction.

    df['time_s_base'] = df[piv_time_col] + solenoid_execution_delay_s

    # time_s: time used for plotting/analysis (optionally FRL-corrected)
    df['time_s'] = df['time_s_base']

    # if subtract_FRL:
    #     df['time_s'] = df['time_s_base'] - piv_flow_delay

    # Flow scaling / leakage subtraction (same rule as PIV)
    # if piv_scaling_factor != 1.0 and piv_flow_leakage != 0.0:
    #     df[flow_rate_col] = (df[flow_rate_col] * piv_scaling_factor)
    #     if subtract_nebulizer_flowrate:
    #         df[flow_rate_col] = df[flow_rate_col] - piv_flow_leakage

    df[flow_rate_col] = df[flow_rate_col]

    df = df.dropna(subset=[flow_rate_col]).sort_values(
        'time_s').reset_index(drop=True)
    return df


def compute_cough_segment(time_s: np.ndarray,
                          flow_L_s: np.ndarray,
                          eps: float = 1e-6,
                          segment_window_s: tuple[float, float] | None = None):
    """
    Determine cough segment indices (i0, i1) inclusive.

    If segment_window_s=(t_start, t_end) is provided, the segment is defined strictly by that time window.
    Otherwise, it falls back to the contiguous positive-flow segment around the global peak (flow > eps).

    Returns (i0, i1). If no segment found, returns full range.
    """
    n = len(time_s)
    if n < 2:
        return 0, max(0, n - 1)

    # Explicit window mode (goal-file driven)
    if segment_window_s is not None:
        t_start, t_end = segment_window_s
        if t_end < t_start:
            t_start, t_end = t_end, t_start

        mask = (time_s >= t_start) & (time_s <= t_end)
        if np.any(mask):
            idx = np.where(mask)[0]
            return int(idx[0]), int(idx[-1])

        # If no points fall inside the window, fall back to nearest indices
        i0 = int(np.clip(np.searchsorted(time_s, t_start, side='left'), 0, n - 1))
        i1 = int(np.clip(np.searchsorted(
            time_s, t_end, side='right') - 1, 0, n - 1))
        if i1 < i0:
            i0, i1 = i1, i0
        return i0, i1

    # Automatic mode
    mask = flow_L_s > eps
    if not np.any(mask):
        return 0, n - 1

    peak_idx = int(np.nanargmax(flow_L_s))

    if not mask[peak_idx]:
        pos_idx = np.where(mask)[0]
        return int(pos_idx[0]), int(pos_idx[-1])

    i0 = peak_idx
    while i0 > 0 and mask[i0 - 1]:
        i0 -= 1

    i1 = peak_idx
    while i1 < n - 1 and mask[i1 + 1]:
        i1 += 1

    return i0, i1


def compute_piv_curve_properties(piv_df: pd.DataFrame,
                                 time_col: str,
                                 flow_col: str,
                                 eps: float = 1e-6,
                                 segment_window_s: tuple[float, float] | None = None):
    """
    Computes 3 properties for a flow curve:
      1) Peak flow (L/s)
      2) Cough duration (s)
      3) Total expired volume (L) = integral of flow over time

    Segment definition:
      - If segment_window_s is provided, that window is used (goal-file driven, preferred).
      - Otherwise, uses the positive-flow segment around the peak (legacy).

    NOTE: Using an explicit segment window prevents any post-curve drift from affecting the trapezoid integration.
    """
    df = piv_df[[time_col, flow_col]].dropna().copy()
    df = df.sort_values(time_col)

    t = df[time_col].to_numpy(dtype=float)
    f = df[flow_col].to_numpy(dtype=float)

    # Ensure increasing time for integration
    order = np.argsort(t)
    t = t[order]
    f = f[order]

    # Identify segment
    i0, i1 = compute_cough_segment(
        t, f, eps=eps, segment_window_s=segment_window_s)

    t_seg = t[i0:i1 + 1]
    f_seg = f[i0:i1 + 1]

    peak_flow = float(np.nanmax(f_seg)) if len(f_seg) else float(np.nanmax(f))
    t_peak = float(t_seg[np.nanargmax(f_seg)]) if len(
        f_seg) else float(t[np.nanargmax(f)])

    duration = float(t_seg[-1] - t_seg[0]) if len(t_seg) >= 2 else 0.0

    # Total expired volume (L): integrate flow (L/s) over time (s)
    volume_L = float(np.trapezoid(f_seg, t_seg)) if len(t_seg) >= 2 else 0.0

    return {
        "peak_flow_L_s": peak_flow,
        "t_peak_s": t_peak,
        "duration_s": duration,
        "volume_L": volume_L,
        "segment_start_s": float(t_seg[0]) if len(t_seg) else float(t[0]),
        "segment_end_s": float(t_seg[-1]) if len(t_seg) else float(t[-1]),
    }


def plot_single_dataset_accuracy(ds, plot_config, goal_df=None, goal_flow_col=None, goal_label='Goal flow'):
    """
    Plot ONE dataset showing:
      - Valve mA setpoint (right axis, step plot)
      - Goal/theoretical flow rate (left axis)
      - PIV measured flow rate (left axis)
    """
    piv_df = ds['piv_df']
    valve_df = ds['valve_df']
    flow_col = ds['flow_col']
    setpoint_col = ds['setpoint_col']
    label = ds.get('label', 'Dataset')

    fig, ax1 = plt.subplots(figsize=(8, 6))

    ax1.set_xlabel('Time (s)', fontsize=14, fontweight='bold')
    ax1.set_ylabel('Flow Rate (L/s)', color='black',
                   fontsize=14, fontweight='bold')
    ax1.tick_params(axis='y', labelcolor='black', direction='inout')
    ax1.grid(True, alpha=0.4)

    # Measured flow (PIV)
    ax1.plot(
        piv_df['time_s'], piv_df[flow_col],
        linewidth=2.0, label=f'{label} - PIV measured'
    )

    # Goal flow: prefer external goal file if provided, otherwise use theoretical_flow_L_s
    if plot_config.get('plot_theoretical', True):
        if goal_df is not None and goal_flow_col is not None and goal_flow_col in goal_df.columns:
            ax1.plot(
                goal_df['time_s'], goal_df[goal_flow_col],
                linewidth=2.5, linestyle='--', color='black', alpha=0.9,
                label=goal_label
            )
        elif 'theoretical_flow_L_s' in valve_df.columns:
            ax1.plot(
                valve_df['time_s'], valve_df['theoretical_flow_L_s'],
                linewidth=2.0, linestyle='--', alpha=0.8,
                label=f'{label} - Goal flow'
            )
        else:
            print("Warning: No goal flow available (external goal file missing and 'theoretical_flow_L_s' not found).")

    # Valve open/close markers (optional)
    if plot_config.get('plot_open_close', False):
        opening_time = ds['opening_time']
        closing_time = ds['closing_time']
        t0_us = valve_df.attrs.get('t0', 0.0)
        time_closed = (closing_time - t0_us) / 1E6
        time_opened = (opening_time - t0_us) / 1E6
        ax1.axvline(x=float(time_opened), color='green', linestyle='--',
                    linewidth=1.5, alpha=0.7, label='Solenoid Open')
        ax1.axvline(x=float(time_closed), color='orange', linestyle='--',
                    linewidth=1.5, alpha=0.7, label='Solenoid Close')

    ax2 = None
    if plot_config.get('plot_mA', True):
        ax2 = ax1.twinx()
        ax2.set_ylabel('Setpoint (mA)', color='tab:red',
                       fontsize=12, fontweight='bold')
        ax2.set_ylim([12, 20])
        ax2.tick_params(axis='y', labelcolor='tab:red')

        valve_df_filtered = valve_df[valve_df[setpoint_col] != -1]
        ax2.plot(
            valve_df_filtered['time_s'], valve_df_filtered[setpoint_col],
            color='tab:red', linewidth=2, linestyle=':', drawstyle='steps-post',
            label='Valve setpoint (mA)'
        )

    plt.title(f'Flow Rate Goal vs. Measured',
              fontsize=16, fontweight='bold', pad=20)

    _combined_legend(ax1, ax2=ax2, loc='upper left', fontsize=9)

    fig.tight_layout()
    print("\nAccuracy plot displayed. Close the window to continue.")
    plt.show()


def plot_triple_datasets(datasets, plot_config):
    """
    Plot three datasets on the same figure with dual y-axes.

    datasets: list of dicts, each containing:
        - 'piv_df': synchronized PIV dataframe
        - 'valve_df': synchronized valve dataframe
        - 'flow_col': flow rate column name
        - 'setpoint_col': setpoint column name
        - 'opening_time': valve opening time
        - 'closing_time': valve closing time
        - 'label': label for this dataset (e.g., 'Dataset 1', 'Trial A', etc.)

    plot_config: dict with boolean flags:
        - 'plot_theoretical': whether to plot theoretical flow
        - 'plot_mA': whether to plot setpoint mA
        - 'plot_open_close': whether to plot valve action lines
    """

    fig, ax1 = plt.subplots(figsize=(8, 6))

    # Define colors and line styles for the three datasets
    colors = ["#0072B2", "#E69F00", "#009E73"]
    theoretical_colors = ['tab:cyan', 'gold', 'lightgreen']
    linestyles = ['-', '-', '-']
    theoretical_linestyles = ['--', '--', '--']
    alphas = [0.9, 0.8, 0.7]

    # Calculate max flow rate across all datasets
    max_flow_rate = 0
    for i, ds in enumerate(datasets):
        piv_df = ds['piv_df']
        valve_df = ds['valve_df']
        flow_col = ds['flow_col']

        max_flow_measured = piv_df[flow_col].max()
        max_flow_rate = max(max_flow_rate, max_flow_measured)

        if plot_config['plot_theoretical']:
            max_flow_theoretical = valve_df['theoretical_flow_L_s'].max()
            max_flow_rate = max(max_flow_rate, max_flow_theoretical)

    flow_rate_max_limit = max_flow_rate + 1

    # Setup left y-axis (flow rate)
    ax1.set_xlabel('Time (s)', fontsize=14, fontweight='bold')
    ax1.set_ylabel('Flow Rate (L/s)', color='black',
                   fontsize=14, fontweight='bold')
    ax1.set_ylim([0, flow_rate_max_limit])
    ax1.tick_params(axis='y', labelcolor='black', direction='inout')
    ax1.grid(True, alpha=0.4)

    all_lines = []

    # Plot each dataset
    for i, ds in enumerate(datasets):
        piv_df = ds['piv_df']
        valve_df = ds['valve_df']
        flow_col = ds['flow_col']
        setpoint_col = ds['setpoint_col']
        label = ds.get('label', f'Dataset {i+1}')

        # Plot measured flow rate
        line = ax1.plot(piv_df['time_s'], piv_df[flow_col],
                        color=colors[i], linewidth=2.0,
                        linestyle=linestyles[i], alpha=alphas[i],
                        label=f'{label} - Measured')
        all_lines.extend(line)

        # Plot theoretical flow rate
        if plot_config['plot_theoretical']:
            line_th = ax1.plot(valve_df['time_s'], valve_df['theoretical_flow_L_s'],
                               color=theoretical_colors[i], linewidth=2.0,
                               linestyle=theoretical_linestyles[i],
                               alpha=0.7,
                               label=f'{label} - Theoretical')
            all_lines.extend(line_th)

    # Setup right y-axis for setpoint (only if requested)
    ax2 = None
    if plot_config['plot_mA']:
        ax2 = ax1.twinx()
        color_setpoint = 'tab:red'
        ax2.set_ylabel('Setpoint (mA)', color=color_setpoint,
                       fontsize=12, fontweight='bold')
        ax2.set_ylim([12, 20])
        ax2.tick_params(axis='y', labelcolor=color_setpoint)

        # Plot setpoint for first dataset (assuming all are similar)
        valve_df = datasets[0]['valve_df']
        setpoint_col = datasets[0]['setpoint_col']
        valve_df_filtered = valve_df[valve_df[setpoint_col] != -1]
        line_setpoint = ax2.plot(valve_df_filtered['time_s'], valve_df_filtered[setpoint_col],
                                 color=color_setpoint, linewidth=2,
                                 label=f'Setpoint ({setpoint_col})',
                                 linestyle=':', drawstyle='steps-post')
        all_lines.extend(line_setpoint)

    # Plot valve actions (using first dataset as reference)
    if plot_config['plot_open_close']:
        ds0 = datasets[0]
        valve_df = ds0['valve_df']
        opening_time = ds0['opening_time']
        closing_time = ds0['closing_time']

        time_closed = (closing_time - valve_df.attrs['t0']) / 1E6
        time_opened = (opening_time - valve_df.attrs['t0']) / 1E6

        ax1.axvline(x=float(time_closed), color='orange', linestyle='--',
                    linewidth=1.5, alpha=0.7, label='Solenoid Valve Closed')
        ax1.axvline(x=float(time_opened), color='green', linestyle='--',
                    linewidth=1.5, alpha=0.7, label='Solenoid Valve Opened')

    # Title
    title_parts = []
    if plot_config['plot_theoretical']:
        title_parts.append('Measured vs. Theoretical Flow Rates')
    else:
        title_parts.append('Measured Flow Rates')

    if plot_config['plot_mA']:
        title_parts.append('Valve Setpoint')

    title = ' & '.join(title_parts) + ' - Triple Measurement Comparison'
    plt.title(title, fontsize=16, fontweight='bold', pad=20)

    # Combined legend
    _combined_legend(
        ax1, ax2=ax2 if plot_config['plot_mA'] else None, loc='upper left', fontsize=9)

    fig.tight_layout()
    print("\nPlot displayed. Close the plot window to exit.")
    plt.show()
    print("Plot closed. Exiting.")


def main():
    """Main execution function for triple dataset comparison (two plots)."""
    print("="*70)
    print("Triple Dataset Flow Rate Comparison Tool")
    print("="*70)

    datasets = []

    # First we load and handle the goal flow datafile

    # Select external GOAL flow file (same format as PIV CSV)
    print("Select GOAL flow CSV file (same format as a PIV datafile):")
    goal_file = select_file("Select GOAL Flow CSV File")
    if not goal_file:
        print("No goal flow file selected. Exiting.")
        return
    print(f"Selected goal file: {goal_file}")

    goal_df_raw = read_piv_data(goal_file)
    if goal_df_raw is None:
        print("Error reading goal flow file. Exiting.")
        return

    # Determine columns for goal file using the same indices as PIV
    goal_cols = goal_df_raw.columns.tolist()
    if len(goal_cols) < 4:
        print("Goal flow file does not have enough columns (expected >= 4). Exiting.")
        return

    goal_time_col = goal_cols[1]
    goal_flow_col = goal_cols[3]

    # Synchronize goal flow using the same PIV rules
    goal_df = synchronize_piv_like(goal_df_raw, goal_time_col, goal_flow_col)

    # Goal-determined cough segment for PIV analysis:
    #   start = start of goal file (trigger-aligned) + FRL timing
    #   end   = end of goal file (trigger-aligned) + FRL timing
    if 'time_s_base' in goal_df.columns:
        goal_t0 = float(goal_df['time_s_base'].min())
        goal_t1 = float(goal_df['time_s_base'].max())
    else:
        # Fallback (should not happen): use time_s, but this will include all measured values and will mess with integrated CEV because of leakage flow
        goal_t0 = float(goal_df['time_s'].min())
        goal_t1 = float(goal_df['time_s'].max())
    goal_segment_window_piv = (
        goal_t0 + float(piv_flow_delay), goal_t1 + float(piv_flow_delay))
    goal_segment_window_goal = (
        float(goal_df['time_s'].min()), float(goal_df['time_s'].max()))

    print("\n" + "="*70)
    print("GOAL FLOW CURVE PROPERTIES")
    print("="*70)

    goal_props = compute_piv_curve_properties(
        goal_df,
        time_col='time_s',
        flow_col=goal_flow_col,
        eps=1e-6,
        segment_window_s=goal_segment_window_goal
    )

    print(
        f"  1) Peak flow        : {goal_props['peak_flow_L_s']:.3f} L/s at t = {goal_props['t_peak_s']:.4f} s")
    print(f"  2) Cough duration   : {goal_props['duration_s']:.4f} s "
          f"(segment {goal_props['segment_start_s']:.4f} → {goal_props['segment_end_s']:.4f} s)")
    print(f"  3) Total volume exp.: {goal_props['volume_L']:.4f} L")
    print("="*70 + "\n")

    # Then we plot and calculate the three overlapping runs

    # Load 3 dataset pairs
    for i in range(n_datasets):
        print(f"\n{'='*70}")
        print(f"DATASET {i+1}")
        print(f"{'='*70}")

        # Get custom label for this dataset
        print(
            f"\nEnter a label for Dataset {i+1} (or press Enter for default):")
        label = input(f"Label (default: 'Dataset {i+1}'): ").strip()
        if not label:
            label = f'Dataset {i+1}'

        # Select PIV file
        print(f"\nSelect PIV data CSV file for {label}:")
        piv_file = select_file(f"Select PIV Data CSV File - {label}")
        if not piv_file:
            print(f"No PIV data file selected for {label}. Exiting.")
            return
        print(f"Selected: {piv_file}")

        # Select Valve file
        print(f"\nSelect valve data CSV file for {label}:")
        valve_file = select_file(f"Select Valve Data CSV File - {label}")
        if not valve_file:
            print(f"No valve data file selected for {label}. Exiting.")
            return
        print(f"Selected: {valve_file}")

        # Read files
        print(f"\nReading {label} files...")
        piv_df = read_piv_data(piv_file)
        valve_df, opening_time, closing_time = read_valve_data(valve_file)

        if piv_df is None or valve_df is None:
            print(f"Error reading files for {label}. Exiting.")
            return

        # Identify columns
        columns = identify_columns(piv_df, valve_df)

        # Synchronize data
        piv_sync, valve_sync, flow_col, setpoint_col, action_col = synchronize_data(
            piv_df, valve_df, columns, opening_time, closing_time)

        # Store dataset
        datasets.append({
            'piv_df': piv_sync,
            'valve_df': valve_sync,
            'flow_col': flow_col,
            'setpoint_col': setpoint_col,
            'opening_time': opening_time,
            'closing_time': closing_time,
            'label': label
        })

        # Compute & print 3 properties for THIS PIV curve (the cough)
        props = compute_piv_curve_properties(
            piv_sync,
            time_col='time_s',
            flow_col=flow_col,
            eps=1e-6,
            segment_window_s=goal_segment_window_piv
        )

        print("\n" + "-"*70)
        print(f"PIV curve properties for {label}:")
        print(
            f"  1) Peak flow        : {props['peak_flow_L_s']:.3f} L/s at t = {props['t_peak_s']:.4f} s")
        print(f"  2) Cough duration   : {props['duration_s']:.4f} s "
              f"(segment {props['segment_start_s']:.4f} → {props['segment_end_s']:.4f} s)")
        print(f"  3) Total volume exp.: {props['volume_L']:.4f} L")
        print("-"*70 + "\n")

        print(f"✓ {label} loaded and synchronized successfully!")

    # Plot 1: accuracy for ONE dataset
    print("\n" + "="*70)
    print("ACCURACY PLOT (ONE DATASET)")
    print("="*70)
    print("Which dataset do you want to use for the accuracy plot?")
    print("Enter 1, 2, or 3 (default: 1)")
    choice = input("Dataset number: ").strip()
    try:
        idx = int(choice) - 1 if choice else 0
    except ValueError:
        idx = 0
    idx = max(0, min(2, idx))

    accuracy_config = {
        'plot_theoretical': True,   # goal flow
        'plot_mA': True,            # valve setpoint
        'plot_open_close': PLOT_OPEN_CLOSE
    }
    plot_single_dataset_accuracy(datasets[idx], accuracy_config, goal_df=goal_df,
                                 goal_flow_col=goal_flow_col, goal_label='Goal flow (external)')

    # Plot 2: overlap/similarity plot for all runs
    print("\n" + "="*70)
    print("OVERLAY PLOT (ALL 3 DATASETS)")
    print("="*70)

    plot_config = {
        'plot_theoretical': PLOT_THEORETICAL,
        'plot_mA': PLOT_MA,
        'plot_open_close': PLOT_OPEN_CLOSE
    }

    print("\nCreating overlay plot...")
    plot_triple_datasets(datasets, plot_config)


if __name__ == "__main__":
    # Configuration flags
    PLOT_MA = False

    # PLOT THEORETICAL DOES NOT WORK ANYMORE!!!!! Keep turned off! Wrong values and calculations
    PLOT_THEORETICAL = False

    PLOT_OPEN_CLOSE = False
    subtract_FRL = True
    subtract_nebulizer_flowrate = False
    piv_flow_leakage = 0.19
    piv_flow_delay = 0.0078

    # Nuber of datasets to compare; minimum is 1. These will also be used to plot the goal flow rate file against
    n_datasets = 1

    main()

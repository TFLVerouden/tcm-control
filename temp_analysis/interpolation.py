import tkinter as tk
from tkinter import filedialog, simpledialog
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from matplotlib.ticker import MaxNLocator
import numpy as np
import warnings
import cvd_check as cvd
from scipy.interpolate import interp1d, PchipInterpolator



cvd.set_cvd_friendly_colors

warnings.filterwarnings('ignore')


def select_file(title):
    """Open file dialog to select a CSV file."""
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(
        title=title,
        filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
    )
    return file_path

def read_piv_data(file_path):
    """
    Read PIV data CSV file (has clean single header row).
    Expects columns: 'time_s', 'flow_rate_m3_s' or similar.
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
    Read valve data CSV file with metadata rows at top.
    """
    try:
        # Step 1: Find the header row and extract T0
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
            raise ValueError("Could not find data header row starting with 'us'")
        
        # Read CSV with the header at the correct position
        # skiprows should be a list of row indices to skip (all rows except the header)
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
        
        # Remove valve action rows
        df.attrs['t0'] = t0
        
        print(f"\n✓ Trigger T0: {t0} µs")
        print(f"Opening: {opening_time} µs")
        print(f"Closing: {closing_time} µs")
        print(f"Final data shape: {df.shape}")
        
        return df, opening_time, closing_time
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return None, None, None
    
def get_user_pressure():
    """Ask user for pressure value via input dialog. Pressure is used for plot title"""
    root = tk.Tk()
    root.withdraw()

    pressure = simpledialog.askfloat(
        "Pressure Input", 
        "Enter Pressure (bar):",
        minvalue=0.0,
        parent=root
    )
    root.destroy()
    return pressure

def get_time_range():
    """Ask user for start/end time (s) via input dialog. Returns (t_start, t_end) or (None, None) if cancelled."""
    root = tk.Tk()
    root.withdraw()

    t_start = simpledialog.askfloat("Time Range", "Enter START time (s):", minvalue=0.0, parent=root)
    if t_start is None:
        root.destroy()
        return None, None

    t_end = simpledialog.askfloat("Time Range", "Enter END time (s):", minvalue=0.0, parent=root)
    root.destroy()

    if t_end is None:
        return None, None

    if t_end <= t_start:
        print("Invalid time range: end time must be > start time.")
        return None, None

    return t_start, t_end

def get_mA_range():
    """Ask user for min/max mA. Returns (mA_min, mA_max) or (None, None) if cancelled."""
    root = tk.Tk()
    root.withdraw()

    mA_min = simpledialog.askfloat("mA Range", "Enter MIN setpoint (mA):", initialvalue=12.0, parent=root)
    if mA_min is None:
        root.destroy()
        return None, None

    mA_max = simpledialog.askfloat("mA Range", "Enter MAX setpoint (mA):", initialvalue=17.5, parent=root)
    root.destroy()

    if mA_max is None:
        return None, None

    if mA_max <= mA_min:
        print("Invalid mA range: max must be > min.")
        return None, None

    return mA_min, mA_max

def identify_columns(piv_df, valve_df):
    """
    Identify columns by known indices.
    PIV data: time_s is column [1], flow_rate is column [3]
    Valve data: time (us) is column [0], setpoint mA is column [2], pressure is column [3]
    """
    print("\n" + "="*60)
    print("COLUMN IDENTIFICATION")
    print("="*60)
    
    # Get columns by index
    piv_cols = piv_df.columns.tolist()
    valve_cols = valve_df.columns.tolist()
    
    print("\nPIV Data Columns:")
    for i, col in enumerate(piv_cols):
        print(f"  [{i}]: {col}")
    
    print("\nValve Data Columns:")
    for i, col in enumerate(valve_cols):
        print(f"  [{i}]: {col}")
    
    # Use known indices
    time_col_piv = piv_cols[1]
    flow_rate_col = piv_cols[3]
    time_col_valve = valve_cols[0]
    action_col = valve_cols[1]
    setpoint_col = valve_cols[2]
    pressure_col = valve_cols[3]
    
    print("\n" + "-"*60)
    print("Using known column indices:")
    print("-"*60)
    print(f"PIV time column [1]: {time_col_piv}")
    print(f"Flow rate column [3]: {flow_rate_col}")
    print(f"Valve time column [0]: {time_col_valve}")
    print(f"Action column [1]: {action_col}")
    print(f"Setpoint/mA column [2]: {setpoint_col}")
    print(f"Pressure column [3]: {pressure_col}")
    
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
    # 1. Reject impossible physics (Reverse flow not modeled here)
    if P_downstream >= P_upstream:
        return 0.0

    # 2. Constants
    T0 = 293.15  # Reference Temp (Kelvin)
    
    # 3. Calculate Ratio
    r = P_downstream / P_upstream
    
    # 4. Check for Choked (Sonic) vs Subsonic
    if r <= b:
        # Choked (Sonic) Flow - Constant max speed
        flow = C * P_upstream * ((T0 / T_upstream) ** 0.5)
    else:
        # Subsonic Flow - Depends on pressure difference
        term = (r - b) / (1 - b)
        if term >= 1.0: 
            sf = 0.0
        else:
            sf = (1 - term**2) ** 0.5
            
        flow = C * P_upstream * ((T0 / T_upstream) ** 0.5) * sf
        
    return flow

def new_calculate_theoretical_flow(valve_df, pressure_col, opening_time, closing_time):
    # Solenoid Valve (Valve 1)
    C_sol = 4.4
    b_sol = 0.4
    # Proportional Valve (Valve 2)
    C_prop = 6.25
    b_prop = 0.23

    P_ambient = 1.01325     # Absolute Ambient Pressure
    Temp = 295.15           # Temperature upstream

    theoretical_flow = []

    piv_flow_leakage = 0.
    p_tank_begin = valve_df[pressure_col].iloc[0] + P_ambient
    p_tank_end = valve_df[pressure_col].iloc[-1] + P_ambient
    p_tank_range = np.linspace(p_tank_begin, p_tank_end, len(valve_df))
    
    for idx, row in valve_df.iterrows():
        # Get tank pressure (gauge) and convert to absolute
        p_tank_gauge_bar = row[pressure_col]
        p_tank_abs = p_tank_gauge_bar + 1.01325

        # Calculate the final outflow using that pipe pressure
        flow_sol = get_iso_flow_rate(p_tank_abs, P_ambient, Temp, C_sol, b_sol)
        flow_prop = get_iso_flow_rate(p_tank_abs, P_ambient, Temp, C_prop, b_prop)

        if flow_sol < flow_prop:
            flow = flow_sol
        elif flow_sol > flow_prop:
            flow = flow_prop
        else:
            flow = flow_sol

        theoretical_flow.append(flow)

    valve_df['theoretical_flow_L_s'] = theoretical_flow
    
    return valve_df


def synchronize_data(piv_df, valve_df, columns, opening_time, closing_time):
    """
    Synchronize PIV and valve data based on T0 trigger time.
    
    PIV data: time is already in seconds, with 0 being the T0 trigger
    Valve data: time is in microseconds (us), converted to seconds relative to T0
    """
    # Configuration 
    calibration_image_size_px = 1280  # Calibration image size in pixels
    video_image_size_px = 896    # Video image size in pixels
    cropping_factor_px = 72  # Cropping factor in pixels
    piv_scaling_factor = (video_image_size_px - 2*cropping_factor_px) / calibration_image_size_px # Factor to scale the PIV flow rate
    piv_trigger_delay_s = 0.01  # PIV trigger delay time in seconds between t0 and frame 0 of camera


    time_col_piv = columns['piv_time_col']
    flow_rate_col = columns['flow_rate_col']
    time_col_valve = columns['valve_time_col']
    setpoint_col = columns['setpoint_col']
    pressure_col = columns['pressure_col']
    action_col = columns['action_col']
    
    # Get the T0 trigger time from valve data metadata
    t0_us = valve_df.attrs.get('t0')
    
    if t0_us is None:
        print("Warning: Trigger T0 not found in metadata, using first valve time as reference")
        t0_us = valve_df[time_col_valve].iloc[0]
    else:
        print(f"\nT0 Trigger time: {t0_us} microseconds")
    
    # PIV data processing
    piv_df_sync = piv_df.copy()
    piv_df_sync['time_s'] = piv_df_sync[time_col_piv] + piv_trigger_delay_s
    if subtract_FRL:
        piv_df_sync['time_s'] = piv_df_sync[time_col_piv] - piv_flow_delay
    
    # Scale the PIV flow rate
    if piv_scaling_factor != 1.0 and piv_flow_leakage != 0.0:
        print(f"Scaling PIV flow rate by a factor of {piv_scaling_factor}")
        piv_df_sync[flow_rate_col] = (piv_df_sync[flow_rate_col] * piv_scaling_factor)
        if subtract_nebulizer_flowrate:
            piv_df_sync[flow_rate_col] = piv_df_sync[flow_rate_col] - piv_flow_leakage
    
    # Valve data processing
    valve_df_sync = valve_df.copy()
    valve_df_sync['time_s'] = (valve_df_sync[time_col_valve] - t0_us) / 1e6
    
    # Calculate theoretical flow before cleaning data
    print("\nCalculating theoretical flow rates...")
    valve_df_sync = new_calculate_theoretical_flow(valve_df_sync, pressure_col, opening_time, closing_time)
    
    # Clean data - remove NaN values for plotting
    piv_df_sync = piv_df_sync.dropna(subset=[flow_rate_col])
    valve_df_sync = valve_df_sync.dropna(subset=[setpoint_col])
    
    # Sort by time
    piv_df_sync = piv_df_sync.sort_values('time_s').reset_index(drop=True)
    valve_df_sync = valve_df_sync.sort_values('time_s').reset_index(drop=True)
    
    print(f"\nPIV time data range: {piv_df_sync['time_s'].min():.3f}s to {piv_df_sync['time_s'].max():.3f}s")
    print(f"Valve time data range: {valve_df_sync['time_s'].min():.3f}s to {valve_df_sync['time_s'].max():.3f}s")
    print(f"Starting pressure: {valve_df_sync[pressure_col].iloc[0]:.3f} bar, Ending pressure: {valve_df_sync[pressure_col].iloc[-1]:.3f} bar")
    
    return piv_df_sync, valve_df_sync, flow_rate_col, setpoint_col, action_col


def calculate_interpolation(valve_df, piv_df, flow_rate_col, setpoint_col):
    """
    1. Matches PIV data to the active Valve interval using 'backward' search.
       (Logic: Flow at time t belongs to the most recent Valve setpoint t_valve <= t)
    2. Averages the dense PIV flow rates for each Valve step.
    3. Generates an interpolated calibration curve of flow rate to mA
    """
    print("\n" + "="*60)
    print("CALCULATING INTERPOLATION (Interval Matching)")
    print("="*60)


    # merge_asof requires strictly sorted data
    valve_df_filtered = valve_df[valve_df[setpoint_col] != -1]
    valve_sorted = valve_df_filtered.sort_values('time_s').reset_index(drop=True)
    piv_sorted = piv_df.sort_values('time_s').reset_index(drop=True)

    # Ask user for time range and filter both datasets
    t_start, t_end = get_time_range()
    if t_start is None or t_end is None:
        print("Time range selection cancelled. Aborting interpolation.")
        return None, None

    valve_sorted = valve_sorted[(valve_sorted["time_s"] >= t_start) & (valve_sorted["time_s"] <= t_end)]
    piv_sorted   = piv_sorted[(piv_sorted["time_s"] >= t_start) & (piv_sorted["time_s"] <= t_end)]

    if valve_sorted.empty or piv_sorted.empty:
        print("No data left after time filtering. Check the selected range.")
        return None, None

    # Rename valve time so we can track it after merging
    valve_sorted = valve_sorted.rename(columns={'time_s': 'valve_time_s'})

    # This effectively implements: "t_valve <= t_piv < t_next_valve"
    # It assigns every PIV point to the valve setting that was active at that moment.
    merged_df = pd.merge_asof(
        piv_sorted, 
        valve_sorted[['valve_time_s', setpoint_col]], 
        left_on='time_s', 
        right_on='valve_time_s', 
        direction='backward' 
    )

    # Remove PIV points that happened before the experiment started (before first valve log)
    merged_df = merged_df.dropna(subset=[setpoint_col])

    # Ask user for mA range and filter merged result (safe: avoids merge_asof carry-forward artifacts)
    # This is to prevent the saturation that happens near 20.0 mA to mess with interpolation curve and values if wanted
    mA_min, mA_max = get_mA_range()
    if mA_min is None or mA_max is None:
        print("mA range selection cancelled. Aborting interpolation.")
        return None, None

    # convert mA stepoints to numeric and drop all NaN and outside selected mA values range rows
    merged_df[setpoint_col] = pd.to_numeric(merged_df[setpoint_col], errors="coerce")
    merged_df = merged_df.dropna(subset=[setpoint_col])
    merged_df = merged_df[(merged_df[setpoint_col] >= mA_min) & (merged_df[setpoint_col] <= mA_max)]

    if merged_df.empty:
        print("No data left after mA filtering. Check the selected range.")
        return None, None

    # Group by the specific Valve Timestamp. 
    # This combines the PIV points that occurred during that specific step.
    calibration_data = merged_df.groupby(['valve_time_s', setpoint_col]).agg({
        flow_rate_col: ['mean', 'std', 'count']
    }).reset_index()

    # Flatten columns
    calibration_data.columns = ['valve_time_s', 'mA', 'flow_mean', 'flow_std', 'count']

    print(f"Aggregated {len(piv_df)} PIV measurements into {len(calibration_data)} unique valve steps.")

    # Sort by Flow (X-axis for inverse interpolation)
    cal_curve = calibration_data.sort_values('flow_mean')

    # Need a strictly increasing function (Bijective) for X=Flow, Y=mA. Otherwise we get error
    # If the flow flattens out (saturates), we keep the first occurrence (lowest mA) for that flow.
    cal_curve = cal_curve.drop_duplicates(subset=['flow_mean'], keep='first')

    x_flow = cal_curve['flow_mean'].values
    y_mA = cal_curve['mA'].values
    # Fill NaN std (happens if a step had only 1 PIV point)
    y_err = cal_curve['flow_std'].fillna(0).values 

    # Either use interp1d or PchipInterpolator based on preference
    try:
        f_flow_to_mA = interp1d(x_flow, y_mA, kind='linear', bounds_error=False, fill_value=(y_mA[0], y_mA[-1]))
        # f_flow_to_mA = PchipInterpolator(x_flow, y_mA, y_mA, extrapolate=False)
    except Exception as e:
        print(f"Spline failed ({e}), using linear fallback.")
        f_flow_to_mA = interp1d(x_flow, y_mA, kind='linear', bounds_error=False, fill_value=(y_mA[0], y_mA[-1]))

    fig, ax = plt.subplots(figsize=(10, 6), dpi=100)

    # Plot 1: The cloud of raw data 
    ax.scatter(merged_df[flow_rate_col], merged_df[setpoint_col], 
               alpha=0.1, color='gray', s=1, label='Raw PIV Points')

    # Plot 2: The averaged points (The ~300 steps) and the error bars in measured average flow rates
    ax.errorbar(x_flow, y_mA, xerr=y_err, fmt='none', ecolor='black', alpha=0.3)
    ax.plot(x_flow, y_mA, 'ko', markersize=3, label='Averaged Steps')

    # Plot 3: The interpolation
    flow_range = np.linspace(x_flow.min(), x_flow.max(), 500)
    mA_pred = f_flow_to_mA(flow_range)
    ax.plot(flow_range, mA_pred, 'r-', linewidth=2, label='Linear Interpolation')

    ax.set_xlabel('Flow Rate (L/s)')
    ax.set_ylabel('Valve Setpoint (mA)')
    ax.set_title('Calibration Curve (Averaged per Valve Step)')
    ax.legend()
    ax.grid(True, alpha=0.5)
    
    plt.tight_layout()
    plt.show()

    def get_mA_for_flow(target_flow):
        return float(f_flow_to_mA(target_flow))

    return calibration_data, get_mA_for_flow


def plot_synchronized_data(piv_df, valve_df, flow_rate_col, setpoint_col, opening_time, closing_time, pressure_val=None,):
    """
    Plot both datasets on the same figure with dual y-axes.
    Left y-axis: flow rate in L/s (measured and theoretical)
    Right y-axis: setpoint in mA
    Overlay valve action events (opening/closing) as vertical lines.
    """
    fig, ax1 = plt.subplots(figsize=(10, 6), dpi=100, layout='constrained')
    
    # Calculate max flow rate and set y-axis range
    max_flow_measured = piv_df[flow_rate_col].max()
    if plot_theoretical:
        max_flow_theoretical = valve_df['theoretical_flow_L_s'].max()
    else:
        max_flow_theoretical = 0.0
    max_flow_rate = max(max_flow_measured, max_flow_theoretical)
    flow_rate_max_limit = max_flow_rate * 1.1  # Add 10% headroom
    
    # Plot flow rate on left y-axis
    color_flow = '#1f77b4'  # Matplotlib default blue
    color_theoretical = 'tab:cyan'
    ax1.set_xlabel('Time (s)')
    ax1.set_ylabel('Flow Rate (L/s)')
    ax1.set_ylim([0, flow_rate_max_limit])
    
    # Plot measured flow rate
    line1 = ax1.plot(piv_df['time_s'], piv_df[flow_rate_col], 
                     color=color_flow, linewidth=1.5, label='Measured Flow Rate')
    
    if plot_smoothed:
        ax1.plot(piv_df['time_s'], piv_df[flow_rate_col].rolling(window=50).mean(), color='darkblue', linewidth=1, label='Smoothed (win=50)')
    
    # Plot theoretical flow rate
    if plot_theoretical:
        line2 = ax1.plot(valve_df['time_s'], valve_df['theoretical_flow_L_s'],
                        color=color_theoretical, linewidth=2.5, linestyle='--', 
                        label='Theoretical Flow Rate', alpha=0.8)
    
    ax1.tick_params(axis='y', labelcolor='black', direction='inout')
    ax1.grid(True, alpha=0.4)
    
    if plot_mA:
        # Create right y-axis for setpoint
        ax2 = ax1.twinx()
        color_setpoint = '#d62728' # Professional red
        ax2.set_ylabel('Valve Setpoint (mA)')
        
        # We want the 20mA line to align visually with the max flow rate peak.
        # 1. Determine the fraction of the left axis occupied by the flow data
        #    (e.g., if max flow is 8 and limit is 10, it uses 80% of height)
        flow_data_fraction = max_flow_measured / flow_rate_max_limit
        setpoint_min = 12.0
        setpoint_target_max = 20.0
        setpoint_data_span = setpoint_target_max - setpoint_min
        
        #    We scale the span so that 20mA sits at the 'flow_data_fraction' height
        new_right_axis_span = setpoint_data_span / flow_data_fraction
        right_axis_max = setpoint_min + new_right_axis_span
        
        ax2.set_ylim([setpoint_min, right_axis_max])
        # ---------------------------
        
        # Filter out -1 values for setpoint line plot
        valve_df_filtered = valve_df[valve_df[setpoint_col] != -1]
        line3 = ax2.plot(valve_df_filtered['time_s'], valve_df_filtered[setpoint_col], 
                         color=color_setpoint, linewidth=2, label=f'Prop Valve Setpoint', 
                         linestyle=':', drawstyle='steps-post')
        
        ax2.tick_params(axis='y', labelcolor=color_setpoint, direction='in')
    
    # Plot valve actions as vertical lines
    time_closed = (closing_time - valve_df.attrs['t0']) / 1E6
    time_opened = (opening_time - valve_df.attrs['t0']) / 1E6

    if plot_open_close:
        ax1.axvline(x=float(time_opened), color='green', linestyle='--', label='Sol Valve Opened')
        ax1.axvline(x=float(time_closed), color='orange', linestyle='--', label='Sol Valve Closed')

    if plot_theoretical and plot_mA:
        base_title = 'Synchronized Flow Rates & Valve Setpoint'
    elif plot_theoretical:
        base_title = 'Synchronized Flow Rates'
    elif plot_mA:
        base_title = 'Synchronized Flow Rate & Valve Setpoint Data'
    else:
        base_title = 'Measured Flow Rate'

    if pressure_val is not None:
        final_title = f"{base_title} (p$_1$: {pressure_val:.2f} bar)"
    else:
        final_title = base_title

    ax1.set_title(final_title, fontstyle='italic')

    # Get handles and labels from the primary axis (Flow Rate & Valve Events)
    handles1, labels1 = ax1.get_legend_handles_labels()
    
    # Get handles and labels from the secondary axis (Setpoint), if it exists
    handles2, labels2 = [], []
    if plot_mA:
        handles2, labels2 = ax2.get_legend_handles_labels()
    
    # Combine
    final_handles = handles1 + handles2
    final_labels = labels1 + labels2
    
    ax1.legend(final_handles, final_labels, loc='upper left', framealpha=0.6, frameon=True, edgecolor='white')
    
    print("\nPlot displayed. Close the plot window to exit.")
    plt.show()
    print("Plot closed. Exiting.")


def main():
    """Main execution function."""
    print("="*60)
    print("CSV Data Synchronization and Flow Rate Comparison Tool")
    print("="*60)
    
    # Select files
    print("\nSelect the PIV data CSV file:")
    piv_file = select_file("Select PIV Data CSV File")
    if not piv_file:
        print("No PIV data file selected. Exiting.")
        return
    
    print(f"\nSelected PIV data file: {piv_file}")
    
    print("\nSelect the valve data CSV file:")
    valve_file = select_file("Select Valve Data CSV File")
    if not valve_file:
        print("No valve data file selected. Exiting.")
        return
    
    print(f"Selected valve data file: {valve_file}")
    
    # Read files
    piv_df = read_piv_data(piv_file)
    valve_df, opening_time, closing_time = read_valve_data(valve_file)
    
    if piv_df is None or valve_df is None:
        print("Error reading files. Exiting.")
        return
    
    # Identify columns
    columns = identify_columns(piv_df, valve_df)

    # Ask for pressure for plot title
    print("\nRequesting pressure input...")
    pressure = get_user_pressure()
    if pressure is not None:
        print(f"Pressure entered: {pressure:.2f} bar")
    
    # Synchronize data and calculate theoretical flow
    piv_sync, valve_sync, flow_col, setpoint_col, action_col = synchronize_data(
        piv_df, valve_df, columns, opening_time, closing_time)
    
    # Plot
    plot_synchronized_data(piv_sync, valve_sync, flow_col, setpoint_col, opening_time, closing_time, pressure_val=pressure)

    # Interpolate valve setpoints and measured flowrates if asked

    # TURN ON FRL SUBTRACTION IF INTERPOLATING
    if interpolate:
        calculate_interpolation(valve_sync, piv_sync, columns['flow_rate_col'],columns['setpoint_col'])


if __name__ == "__main__":

    # Options for calculations and plot generation
    plot_smoothed = False   #Dark blue smooth curve to visualise average flow rate (sample size is currently 50)
    plot_mA = False
    interpolate = False     #Calculate the interpolation of the valve setpoint mA and measured flow rate and plot this
    plot_theoretical = False    #Use ISO 6358 to calculate theoretical flow as sanity check
    plot_open_close = False     # Plot the solenoid valve open and close time as vertical bars
    subtract_nebulizer_flowrate = False     # Subtract the default flow rate with valves closed due to nebulizer
    subtract_FRL = True     # Subtract the FRL, value can be set below

    piv_flow_delay = 0.0078  # FRL VALUE: piv flow delay time in seconds between valve action and measurable flow change
    piv_flow_leakage = 0.1948  # Leakage flow rate in L/s from nebulizer to subtract from scaled PIV flow

    # Plot layout and visual options
    plt.rcParams.update({
    "font.family": "serif",
    "font.size": 18,
    "axes.labelsize": 19,
    "xtick.labelsize": 18,
    "ytick.labelsize": 18,
    "legend.fontsize": 16,
    "figure.titlesize": 20,
    "axes.titlesize": 22,
    "axes.titleweight": "normal",
    "axes.titlepad": 15
    })

    main()

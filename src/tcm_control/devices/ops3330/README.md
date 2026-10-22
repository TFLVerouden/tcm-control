# ops3330 — Python control for the TSI Model 3330 OPS

Talks to the TSI Optical Particle Sizer (OPS) 3330 using the ASCII
command protocol documented in Appendix D of the instrument manual.

## How the connection actually works (important)

The OPS 3330 does **not** expose a normal serial (COM) port over USB.
Per the manual:

- All commands go over a **TCP/IP socket on port 3602**.
- Over **USB**, that socket is reached through TSI's **NDIS** virtual
  network driver, installed from the Aerosol Instrument Manager disc.
  This is **Windows-only**. Once installed, plugging in the OPS creates
  a virtual network adapter and the unit gets a static IP address, shown
  on the unit's touchscreen: **Setup tab → Communications screen → "USB
  IP Address"**.
- Over **Ethernet**, you talk to the same protocol directly at the
  instrument's Ethernet IP — no NDIS driver needed.
- If the OPS was last connected to a *different* PC over USB, you must
  power-cycle the unit before it will accept a USB connection from a new
  PC (explicitly noted in the manual).

So: install the NDIS driver, plug in over USB, read the IP off the
touchscreen, and put it in `profiles/connection.toml`. This code is then
a plain TCP client — no `pyserial` involved.

**No remote power-on.** The protocol has no command to power the
instrument on remotely (it has to already be booted for the socket to
exist). `MSTART`/`MSTOP` start and stop a *measurement* — that's what
`start()`/`stop()` do here. `MSHUTDOWN` (`shutdown()`) fully powers the
unit down; there's no software way to power it back on afterward.

**No file download command.** The instrument's own CSV export goes to a
USB flash drive plugged into *the OPS itself*, not back over this
command socket. To get data onto your PC, `record_measurement()` instead
starts a measurement and polls `RMLOGGEDBINS`/`RMUNITMEAS`/`RMMESSAGES`
once per completed sample, writing a CSV modeled on the column layout in
Appendix B of the manual (elapsed time, per-bin counts, deadtime, temp,
humidity, pressure, alarm/error flags).

## Install

```bash
pip install tomli   # only needed if you're on Python < 3.11
```

No other dependencies — everything else is Python standard library
(`socket`, `csv`, `argparse`).

## Setup

1. Edit `profiles/connection.toml` with the IP shown on the OPS's
   Communications screen.
2. Edit `profiles/default_minimal.toml` if you want anything other than
   the factory-standard 16-channel (0.3–10 µm) bin table, or add optional
   `[alarm]` / `[analog_output]` / `[user_cal]` / `[flow_cal]` sections.

## Command line

```bash
# Basic info + status
python -m ops3330.cli --conn profiles/connection.toml info

# Push a profile (bins, logging setup, etc.)
python -m ops3330.cli --conn profiles/connection.toml apply-profile profiles/default_minimal.toml

# Start / stop a measurement
python -m ops3330.cli --conn profiles/connection.toml start
python -m ops3330.cli --conn profiles/connection.toml stop

# Full power-down
python -m ops3330.cli --conn profiles/connection.toml shutdown

# Run + save a measurement to CSV (Ctrl+C stops early and still saves)
python -m ops3330.cli --conn profiles/connection.toml record --out data/run1.csv --duration 600
```

## Programmatic use

See `examples/basic_usage.py` for a full connect → apply profile →
record → save flow.

```python
from ops3330 import OPSClient, load_profile, apply_profile, record_measurement

with OPSClient(ip="192.168.1.1") as client:
    profile = load_profile("profiles/default_minimal.toml")
    apply_profile(client, profile)   # sends WMODECHSETUP, WMODELOG, ..., then MUPDATE

    client.start_measurement()       # MSTART
    record_measurement(client, "data/run1.csv", max_duration_s=600)
    # record_measurement() calls MSTOP for you when it finishes
```

## Profile file format

`profiles/default_minimal.toml` is the "minimal" profile: it only sets
the factory-standard bin table and a basic logging schedule, and leaves
alarm / analog-output / calibration settings as whatever is already on
the instrument. Any section you omit from a profile TOML is left
untouched on the device — only the sections present get written.

## Notes / things worth double-checking on real hardware

- The manual doesn't spell out an explicit reply terminator for the
  socket protocol, so `OPSClient.send_raw()` treats "no more bytes for
  `idle_gap` seconds (default 0.25s)" as end-of-reply. If you see
  truncated or merged replies on your setup, try raising `idle_gap` when
  constructing `OPSClient`.
- `record_measurement()`'s "new sample" detection is based on the
  documented "Valid Sample" flag in the `RMLOGGEDBINS` reply. Confirm
  against a known-good run (e.g. compare sample counts / timing against
  a CSV the instrument itself saves to a USB stick) before relying on it
  for real data collection.
- Protocol slots 1–6 are factory-reserved per the manual (delete is only
  allowed for slots 7–16); `save_current_as_protocol()` writes to
  whatever slot the instrument's firmware assigns next.

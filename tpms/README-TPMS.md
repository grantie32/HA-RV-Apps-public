# ATOTO AC-UTP1 serial decoder

The receiver appears in Windows as `USB-SERIAL CH340`. The decoder expects the
receiver at 19200 baud, 8 data bits, no parity, one stop bit, with no flow
control.

## Test on Windows

Install the only Python dependency:

```powershell
py -m pip install pyserial
```

Run the readable decoder, replacing `COM4` with the port shown in Device
Manager:

```powershell
py .\tpms_serial_decoder.py COM4
```

For JSON lines suitable for a later MQTT bridge:

```powershell
py .\tpms_serial_decoder.py COM4 --json
```

The decoder validates the `55 AA 08` frame header and XOR checksum. Tested
pressure values use half-PSI increments, so a raw pressure byte of `0x33`
becomes `25.5 PSI`. Status `00` with a non-zero pressure is treated as a
valid reading; status `08` is treated as inactive/no pressure.

Sensor ID `05` is excluded by default because it duplicated ID `10` in the
initial captures. Use `--include-duplicates` while investigating the remaining
sensor mapping.

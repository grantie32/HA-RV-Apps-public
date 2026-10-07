# HA RV Apps — public TPMS repository

Public Home Assistant app repository for the motorhome TPMS receiver.

## Apps

- [`tpms/`](tpms/) — ATOTO AC-UTP1 TPMS decoder, MQTT bridge, Home Assistant dashboard, and add-on.

The private Venus OS dashboard and temporary packet capture/work files are intentionally not included.

## Add to Home Assistant

In Home Assistant, open **Settings → Apps → App store**, choose the repository menu,
and add:

`https://github.com/grantie32/HA-RV-Apps-public`

The repository contains the **Motorhome TPMS** app. The Venus OS dashboard remains in
the private source repository because it installs static files into Home Assistant's
`www` directory and registers a custom panel; it is not a Supervisor app.

# Famiclean Protocol Notes

## Scope

These notes summarize the real-device UDP protocol captured in `logs/famiclean-real.pcap` (original source capture path: `D:\faminclean-ghome\famiclean-real.pcap`).
The device currently listens on UDP port `9999`.

## Discovery

- Request payload: `request_mac `
- Typical flow:
  - client sends broadcast to `192.168.10.255:9999`
  - device responds from `device-ip:9999`
- Example response:

```text
{'mac':'345F455F1C98','control':'waterheater','_macback':'macback'}
```

## Usage Query

- Request payload: `request_usage `
- Example response:

```text
{'waterflow_count':22.91,'heatvalue_count':414.52,'waterflow_total':37198.39,'heatvalue_total':741727.88,'usageback':'end'}
```

### Important quirk

The real device replied to `request_usage ` on the UDP source port previously used by `request_mac `.
Do not send discovery and usage on unrelated one-shot sockets if you want reliable reads. Keep one socket alive for the whole session.

## Status Query

- Request payload: `request_data `
- Example response:

```text
{'hottemp':41,'coldtemp':20,'settemp':41,'waterflow':0.00,'errorcode':'','waterflow_count':0.00,'waterflow_total':37198.39,'heatvalue_count':0.00,'heatvalue_total':741727.88,'motor_steps':68,'ventilator_steps':20,'power':'on','mac':'345F455F1C98','control':'waterheater','_messageback':'msgback__eco0rssi-692','lock':'0','notice_bath':0}
```

## Temperature Control

- Request template:

```text
control_type:waterheatersettemp:<TEMP>power:onmac:<MAC>min_flow:0wifi_reset:0lock:0bath_qty:0bath_qty_timer:0fcm_token:platform:androidpro_mode:0 
```

- The real device did not emit an immediate direct ACK in the capture.
- Confirm changes by sending `request_data ` after the control packet.

## Field Mapping

- `heatvalue_total`
  Raw cumulative value from the device.
- `heatvalue_count`
  Raw current-cycle gas value from the device.
- `gas_total_m3`
  App-aligned live display value. In idle captures this is `round(heatvalue_total / 9100, 2)`. During active heating the skill aligns to the phone app by using `round((request_usage.heatvalue_total + request_data.heatvalue_count) / 9100, 2)`.
- `gas_count_m3`
  Live current-cycle display value from `request_data.heatvalue_count`, i.e. `round(heatvalue_count / 9100, 2)`.
- `settemp`
  Current target water temperature.

## Safety Rules For This Skill

- Never set a target temperature above `50°C`.
- Do not auto-correct a device that reports more than `50°C`; only block new set requests above the configured maximum.

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **Home Assistant custom component** that provides centralized heating demand management. It monitors multiple Thermostatic Radiator Valve (TRV) climate entities and aggregates their heating requests into a single binary sensor (`binary_sensor.central_heating_demand`).

The integration is designed for multi-zone heating systems and supports:
- OpenTherm thermostats with modulation control
- Direct boiler/heater control via climate entities
- Away Mode detection for energy savings
- Hysteresis to prevent rapid on/off cycling
- Real-time, event-driven updates (no polling)

## Architecture

### Component Structure

```
custom_components/central_heating_demand/
├── __init__.py          # Minimal async component setup (domain registration)
├── binary_sensor.py     # Core logic - CentralHeatingDemandBinarySensor class
└── manifest.json        # Component metadata (version, dependencies)
```

### Key Class: `CentralHeatingDemandBinarySensor`

Located in [binary_sensor.py](custom_components/central_heating_demand/binary_sensor.py), this is the heart of the integration.

**Initialization ([binary_sensor.py:110-147](custom_components/central_heating_demand/binary_sensor.py#L110-L147))**:
- Accepts list of TRV climate entity IDs to monitor
- Optional heater entity ID for direct control
- Away Mode configuration (zone entity + away temperature)
- Hysteresis value for demand threshold
- Stores state: `_is_heating_demanded`, max demand calculations, last sent commands
- Includes `asyncio.Lock()` for thread-safe heater control

**Event Listeners ([binary_sensor.py:158-177](custom_components/central_heating_demand/binary_sensor.py#L158-L177))**:
- Uses `async_track_state_change_event` for real-time TRV monitoring
- Separate listener for zone entity (Away Mode detection)
- Triggers on `hvac_action`, `current_temperature`, or `temperature` attribute changes
- Validates TRV entities at startup and logs warnings for missing ones

**Demand Calculation ([binary_sensor.py:210-310](custom_components/central_healing_demand/binary_sensor.py#L210-L310))**:
The `_async_update_heating_demand()` method:
1. Checks Away Mode: If zone state is "0", override all TRV targets with `away_temp`
2. Iterates through all TRV entities:
   - Validates temperature values are finite numbers
   - Reads `hvac_action`, `current_temperature`, `temperature` attributes
   - Calculates `delta = effective_target_temperature - current_temperature`
   - Counts TRVs with `hvac_action == "heating"` OR `state == "heat"` AND `delta > hysteresis`
3. Identifies "max demand" TRV (largest positive delta)
4. Sets binary sensor state to `on` if any TRV is demanding heat
5. Logs state transitions at INFO level for easier debugging

**Heater Control ([binary_sensor.py:312-350](custom_components/central_heating_demand/binary_sensor.py#L312-L350))**:
If `heater_entity_id` is configured, the integration calls Home Assistant services:
- Uses `asyncio.Lock()` to prevent race conditions from rapid state changes
- `climate.set_temperature`: Sets target to max demand target temp (or minimum_temperature if no demand)
- `climate.set_hvac_mode`: Sets to "heat" when demand exists, "off" when satisfied
- Tracks last sent values to avoid redundant service calls

### Exposed Attributes

The binary sensor exposes these attributes for OpenTherm integration:
- `max_demand_current_temperature`: Current temp of the room with highest deficit
- `max_demand_target_temperature`: Target temp of that room
- `max_demand_delta`: Gap between target and current (clamped to 0 if negative)
- `max_demand_trv_entity_id`: Entity ID of the TRV driving demand
- `max_demand_trv_name`: Friendly name of that TRV
- `away_mode`: Boolean indicating if Away Mode is active
- `away_temperature`: The configured away_temp value
- `hysteresis`: The configured hysteresis value

## Development Workflow

### Installation for Testing

This component must be tested within a Home Assistant instance:

1. Copy the `custom_components/central_heating_demand/` directory to your Home Assistant config directory
2. Restart Home Assistant
3. Add configuration to `configuration.yaml`:

```yaml
binary_sensor:
  - platform: central_heating_demand
    trv_climate_entities:
      - climate.trv_living_room
      - climate.trv_bedroom
    zone_entity_id: zone.home  # Optional: for Away Mode
    away_temp: 12.0            # Optional: default 12.0
    heater_entity_id: climate.my_boiler  # Optional: for direct control
    minimum_temperature: 5.0   # Optional: default 5.0
    hysteresis: 0.5            # Optional: default 0.5, prevents rapid cycling
```

### No Automated Tests

This repository does not currently have automated tests. Testing requires:
- A running Home Assistant development environment
- Mock or real TRV climate entities
- Manual state verification via Developer Tools

### Making Changes

**When modifying the demand calculation logic**:
- Focus on [binary_sensor.py:210-310](custom_components/central_heating_demand/binary_sensor.py#L210-L310) (`_async_update_heating_demand`)
- Remember Away Mode overrides target temperatures before calculating deltas
- The `max_demand_delta` is clamped to 0 if negative (user requirement)
- Hysteresis applies to the demand check: `delta > hysteresis` turns ON demand

**When modifying heater control**:
- See [binary_sensor.py:312-350](custom_components/central_heating_demand/binary_sensor.py#L312-L350) (`_async_control_heater`)
- Always use `async with self._heater_lock` to prevent race conditions
- Check `_last_sent_target_temperature` and `_last_sent_hvac_mode` to avoid unnecessary service calls
- Use `blocking=False` for async service calls to prevent blocking the event loop

**When adding new configuration options**:
1. Add to `PLATFORM_SCHEMA` validation ([binary_sensor.py:55-67](custom_components/central_heating_demand/binary_sensor.py#L55-L67))
2. Extract in `async_setup_platform` ([binary_sensor.py:70-97](custom_components/central_heating_demand/binary_sensor.py#L70-L97))
3. Pass to `__init__` and store as instance variable
4. Update `manifest.json` version number

## Important Implementation Notes

- **Event-driven architecture**: The sensor uses `async_track_state_change_event` and `@callback` decorators. All state updates must call `self.async_write_ha_state()` to persist changes.

- **No polling**: `_attr_should_poll = False` means the sensor only updates when TRV or zone states change.

- **Service calls are idempotent**: The heater control logic tracks last sent values to avoid sending duplicate commands to the climate entity.

- **Race condition prevention**: An `asyncio.Lock()` prevents multiple concurrent heater control operations when TRV states change rapidly.

- **Away Mode priority**: When Away Mode is active (zone state == "0"), the `away_temp` overrides all TRV target temperatures before calculating demand.

- **Delta clamping**: The max demand delta is clamped to 0 if negative per user requirement. This ensures the exposed attribute never shows a negative deficit.

- **Hysteresis**: Prevents rapid on/off cycling by requiring `delta > hysteresis` to turn ON demand (default 0.5°C).

- **Entity validation**: Missing TRV entities are logged as warnings at startup. Invalid temperature values (NaN/infinity) are logged and skipped.

## Git Repository

Repository: https://github.com/Kingo71/multi-room-heating.git

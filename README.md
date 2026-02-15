# Home Assistant Central Heating Demand Integration

This custom component for Home Assistant provides a sensor to monitor the heating demand from multiple Thermostatic Radiator Valves (TRVs) and centrally control a boiler or other heating source.

## Features

-   **Centralized Demand Calculation:** Aggregates heating requests from multiple TRV `climate` entities into a single, easy-to-use `on`/`off` sensor.
-   **Event-Driven:** Updates instantly when TRV states change, without the need for polling.
-   **Flexible Boiler Control:** Allows you to create powerful automations to control your boiler based on real heating demand, potentially saving energy.
-   **Easy Configuration:** Simple setup via `configuration.yaml`.

## Installation

1.  **Copy the Custom Component:**
    Place the `central_heating_demand` folder (containing `manifest.json`, `__init__.py`, and `sensor.py`) into your Home Assistant `custom_components` directory. If you do not have a `custom_components` directory, you will need to create it in your main configuration directory.

    Your directory structure should look like this:
    ```
    <config_directory>/
    ├── custom_components/
    │   └── central_heating_demand/
    │       ├── __init__.py
    │       ├── manifest.json
    │       └── sensor.py
    └── ... (your other configuration files)
    ```

2.  **Restart Home Assistant:**
    After copying the files, you must restart Home Assistant to load the new integration.
    -   Go to `Developer Tools` -> `YAML`.
    -   Click `Check Configuration`. If it's valid, proceed.
    -   Go to `Developer Tools` -> `Control` and click `Restart`.

## Configuration

To use this integration, add the following to your `configuration.yaml` file (or a file included by it, such as `sensors.yaml`):

```yaml
# configuration.yaml or sensors.yaml
sensor:
  - platform: central_heating_demand
    trv_climate_entities:
      - climate.trv_living_room   # Replace with your first TRV entity ID
      - climate.trv_bedroom       # Replace with your second TRV entity ID
      # Add all your TRV climate entity IDs here
```

-   **`trv_climate_entities` (Required):** A list of the `entity_id`s for all the TRV `climate` entities you want to monitor.

## Usage

After restarting, you will have a new sensor called `sensor.central_heating_demand`. This sensor's state will be:
-   `on`: When at least one of the monitored TRVs is demanding heat.
-   `off`: When none of the monitored TRVs are demanding heat.

### Automation Example

You can use this sensor to create an automation that controls your main boiler thermostat (`climate.thermostat_boiler` in this example).

Here is a sample automation. You can add this to your `automations.yaml` file or create it using the Automation Editor in the UI.

```yaml
# automations.yaml
- alias: Control Boiler based on Central Heating Demand
  trigger:
    - platform: state
      entity_id: sensor.central_heating_demand
      to: "on"
      id: "demand_on"
    - platform: state
      entity_id: sensor.central_heating_demand
      to: "off"
      id: "demand_off"
  action:
    - choose:
        - conditions:
            - condition: trigger
              id: "demand_on"
          sequence:
            - service: climate.set_temperature
              target:
                entity_id: climate.thermostat_boiler
              data:
                temperature: 30 # Set a high temperature to force the boiler on
      default: # This runs when the trigger ID is "demand_off"
        - service: climate.set_temperature
          target:
            entity_id: climate.thermostat_boiler
          data:
            temperature: 5 # Set a low temperature to force the boiler off
```

**Important:** Adjust the `temperature` values (`30` and `5`) to suitable settings for your boiler. `30` should be high enough to always trigger a call for heat, and `5` should be low enough to reliably stop it.

## OpenTherm / Modulation Support

This integration is designed to work with OpenTherm thermostats (via ESPHome or similar) that require a target temperature input rather than a simple on/off switch.

The sensor exposes additional attributes representing the "Maximum Demand" (the room with the largest gap between current and target temperature):

-   `max_demand_current_temperature`: The current temperature of the room with the highest heating deficit.
-   `max_demand_target_temperature`: The target temperature of that same room.
-   `max_demand_delta`: The difference between target and current temperature.
-   `max_demand_trv_entity_id`: The entity ID of the TRV driving the demand.

### ESPHome Configuration Example

You can use these attributes to feed your OpenTherm PID regulator or thermostat component in ESPHome. Here is an example of how to import these values:

```yaml
sensor:
  - platform: homeassistant
    id: central_current_temp
    entity_id: sensor.central_heating_demand
    attribute: max_demand_current_temperature

  - platform: homeassistant
    id: central_target_temp
    entity_id: sensor.central_heating_demand
    attribute: max_demand_target_temperature
```

### Direct Boiler Control

You can also configure this integration to directly control your boiler/heater entity (e.g., an OpenTherm thermostat connected via ESPHome).

If you add the `heater_entity_id` to your configuration, the integration will automatically:
1.  **Set Target Temp**: When heating is needed, it sets the heater's target temperature to match the room with the highest demand.
2.  **Frost Protection**: When no heating is needed, it sets the heater's target temperature to a minimum value (default 5°C).

**Configuration Example:**

```yaml
sensor:
  - platform: central_heating_demand
    trv_climate_entities:
      - climate.living_room
      - climate.bedroom
    
    # Optional: Automatically control this heater entity
    heater_entity_id: climate.my_boiler
    
    # Optional: Temperature to set when no heat is needed (default: 5.0)
    minimum_temperature: 15
```

## Troubleshooting

-   **Sensor not appearing:**
    -   Double-check that the directory structure is correct (`custom_components/central_heating_demand/...`).
    -   Ensure you have correctly configured the sensor in `configuration.yaml` and provided a valid list of TRV entity IDs.
    -   Check the Home Assistant logs (`Settings` -> `System` -> `Logs`) for any errors related to the `central_heating_demand` component.

## Contributing

Contributions are welcome! If you have ideas for improvements or find any issues, please open an issue or submit a pull request on the GitHub repository.

## License

This project is licensed under the MIT License.

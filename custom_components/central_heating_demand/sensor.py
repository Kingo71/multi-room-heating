"""Sensor platform for the central heating demand integration."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.components.sensor import (
    PLATFORM_SCHEMA,
    SensorEntity,
)
from homeassistant.const import EVENT_HOMEASSISTANT_START
from homeassistant.core import (
    Event,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.event import async_track_state_change_event

_LOGGER = logging.getLogger(__name__)

DOMAIN = "central_heating_demand"

CONF_TRV_CLIMATE_ENTITIES = "trv_climate_entities"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_TRV_CLIMATE_ENTITIES): vol.All(
            vol.EnsureSquareBracketedString(), [str]
        ),
    }
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the Central Heating Demand sensor platform."""
    trv_climate_entities: list[str] = config[CONF_TRV_CLIMATE_ENTITIES]

    async_add_entities([CentralHeatingDemandSensor(hass, trv_climate_entities)])


class CentralHeatingDemandSensor(SensorEntity):
    """Representation of a Central Heating Demand Sensor."""

    _attr_name = "Central Heating Demand"
    _attr_icon = "mdi:radiator"
    _attr_should_poll = False  # We'll use event listeners

    def __init__(self, hass: HomeAssistant, trv_climate_entities: list[str]) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self._trv_climate_entities = trv_climate_entities
        self._is_heating_demanded = False

    async def async_added_to_hass(self) -> None:
        """Register callbacks when entity is added."""
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, self._trv_climate_entities, self._async_trv_state_listener
            )
        )

        # Initial state update when Home Assistant starts
        self.hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_START, self._async_update_on_start
        )

    @callback
    def _async_update_on_start(self, event: Event) -> None:
        """Update state when Home Assistant starts."""
        self._async_update_heating_demand()
        self.async_write_ha_state()

    @callback
    def _async_trv_state_listener(self, event: Event) -> None:
        """Handle TRV state changes."""
        old_state: State | None = event.data.get("old_state")
        new_state: State | None = event.data.get("new_state")

        # Only proceed if there's a meaningful state change for hvac_action or temperature
        if (
            old_state
            and new_state
            and (
                old_state.attributes.get("hvac_action")
                != new_state.attributes.get("hvac_action")
                or old_state.attributes.get("current_temperature")
                != new_state.attributes.get("current_temperature")
                or old_state.attributes.get("temperature")
                != new_state.attributes.get("temperature")
            )
        ):
            self._async_update_heating_demand()
            self.async_write_ha_state()
        elif not old_state and new_state: # Initial state set
            self._async_update_heating_demand()
            self.async_write_ha_state()


    @callback
    def _async_update_heating_demand(self) -> None:
        """Calculate if any TRV is currently demanding heating."""
        demanding_trvs = 0
        for entity_id in self._trv_climate_entities:
            state = self.hass.states.get(entity_id)
            if not state:
                _LOGGER.debug("TRV entity %s not found", entity_id)
                continue

            hvac_action = state.attributes.get("hvac_action")
            current_temperature = state.attributes.get("current_temperature")
            target_temperature = state.attributes.get("temperature")
            trv_state = state.state

            # Logic copied from user's template sensor
            if hvac_action == "heating" or (
                trv_state == "heat"
                and current_temperature is not None
                and target_temperature is not None
                and current_temperature < target_temperature
            ):
                demanding_trvs += 1
                # If at least one TRV demands heating, we can stop checking
                break

        self._is_heating_demanded = demanding_trvs > 0

    @property
    def state(self):
        """Return the state of the sensor."""
        return "on" if self._is_heating_demanded else "off"

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return {"trv_climate_entities": self._trv_climate_entities}

# Helper function for vol.All(vol.EnsureSquareBracketedString(), [str])
# This is to handle cases where the user might pass a single string instead of a list
# or a string that should be parsed as a list.
def EnsureSquareBracketedString():
    def validate(value):
        if isinstance(value, str):
            try:
                # Attempt to parse as a JSON list (e.g., '["climate.trv1", "climate.trv2"]')
                import json
                parsed_value = json.loads(value)
                if isinstance(parsed_value, list):
                    return parsed_value
            except json.JSONDecodeError:
                pass
            # If it's a single string, treat it as a list with one item
            return [value]
        elif isinstance(value, list):
            return value
        raise vol.Invalid("Expected a string or a list of strings")
    return validate


"""Binary sensor platform for the central heating demand integration."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.components.binary_sensor import (
    PLATFORM_SCHEMA,
    BinarySensorEntity,
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

CONF_TRV_CLIMATE_ENTITIES = "trv_climate_entities"
CONF_HEATER_ENTITY_ID = "heater_entity_id"
CONF_MINIMUM_TEMPERATURE = "minimum_temperature"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_TRV_CLIMATE_ENTITIES): vol.All(
            EnsureSquareBracketedString(), [str]
        ),
        vol.Optional(CONF_HEATER_ENTITY_ID): str,
        vol.Optional(CONF_MINIMUM_TEMPERATURE, default=5.0): vol.Coerce(float),
        vol.Optional("away_temp", default=12.0): vol.Coerce(float),
        vol.Optional("zone_entity_id"): str,
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
    heater_entity_id: str | None = config.get(CONF_HEATER_ENTITY_ID)
    minimum_temperature: float = config[CONF_MINIMUM_TEMPERATURE]
    away_temp: float = config["away_temp"]
    zone_entity_id: str | None = config.get("zone_entity_id")

    async_add_entities(
        [
            CentralHeatingDemandBinarySensor(
                hass,
                trv_climate_entities,
                heater_entity_id,
                minimum_temperature,
                away_temp,
                zone_entity_id,
            )
        ]
    )


class CentralHeatingDemandBinarySensor(BinarySensorEntity):
    """Representation of a Central Heating Demand Binary Sensor."""

    _attr_name = "Central Heating Demand"
    _attr_icon = "mdi:radiator"
    _attr_should_poll = False  # We'll use event listeners

    def __init__(
        self,
        hass: HomeAssistant,
        trv_climate_entities: list[str],
        heater_entity_id: str | None,
        minimum_temperature: float,
        away_temp: float,
        zone_entity_id: str | None,
    ) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self._trv_climate_entities = trv_climate_entities
        self._heater_entity_id = heater_entity_id
        self._minimum_temperature = minimum_temperature
        self._away_temp = away_temp
        self._zone_entity_id = zone_entity_id
        self._is_heating_demanded = False
        self._max_demand_delta = 0.0
        self._max_demand_current_temperature = None
        self._max_demand_target_temperature = None
        self._max_demand_trv_entity_id = None
        self._last_sent_target_temperature = None
        self._last_sent_hvac_mode = None
        self._max_demand_trv_name = None
        self._is_away = False

    async def async_added_to_hass(self) -> None:
        """Register callbacks when entity is added."""
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, self._trv_climate_entities, self._async_trv_state_listener
            )
        )

        if self._zone_entity_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [self._zone_entity_id], self._async_zone_state_listener
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
    def _async_zone_state_listener(self, event: Event) -> None:
        """Handle Zone state changes."""
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
        """Calculate if any TRV is currently demanding heating and find the max demand."""
        demanding_trvs = 0
        max_delta = -100.0  # Initialize with a very low value
        leader_entity_id = None
        leader_current_temp = None
        leader_target_temp = None
        leader_friendly_name = None
        
        
        # Track if we found at least one valid TRV to report on
        valid_trv_found = False

        # Check Away Mode
        self._is_away = False
        if self._zone_entity_id:
            zone_state = self.hass.states.get(self._zone_entity_id)
            if zone_state and zone_state.state == "0":
                self._is_away = True


        for entity_id in self._trv_climate_entities:
            state = self.hass.states.get(entity_id)
            if not state:
                _LOGGER.debug("TRV entity %s not found", entity_id)
                continue

            hvac_action = state.attributes.get("hvac_action")
            current_temperature = state.attributes.get("current_temperature")
            target_temperature = state.attributes.get("temperature")
            trv_state = state.state
            friendly_name = state.attributes.get("friendly_name")

            # Ensure we have valid numbers to work with
            if current_temperature is None or target_temperature is None:
                continue
                
            valid_trv_found = True
            
            # Calculate demand delta (Target - Current)
            # A positive delta means heat is needed.
            # Implement Away Mode Logic: override target with away_temp if away
            effective_target_temperature = target_temperature
            if self._is_away:
                effective_target_temperature = self._away_temp

            delta = effective_target_temperature - current_temperature

            # Check for binary demand (existing logic + check)
            is_demanding = False
            if hvac_action == "heating" or (
                trv_state == "heat"
                and delta > 0
            ):
                is_demanding = True
                demanding_trvs += 1

            # Determine if this TRV has the highest demand (largest deficit)
            # We track the max delta even if it's negative (closest to target) 
            # so we always report *something* reasonable to the OpenTherm thermostat.
            if delta > max_delta:
                max_delta = delta
                leader_entity_id = entity_id
                leader_current_temp = current_temperature
                leader_target_temp = target_temperature
                leader_friendly_name = friendly_name

        self._is_heating_demanded = demanding_trvs > 0
        
        if valid_trv_found and leader_entity_id:
             # User Request: If demand delta is negative, show it as zero.
             self._max_demand_delta = max(0.0, max_delta)
             self._max_demand_current_temperature = leader_current_temp
             self._max_demand_target_temperature = leader_target_temp
             self._max_demand_trv_entity_id = leader_entity_id
             self._max_demand_trv_name = leader_friendly_name
        else:
             # Fallback if no valid TRVs found
             self._max_demand_delta = 0.0
             self._max_demand_current_temperature = None
             self._max_demand_target_temperature = None
             self._max_demand_trv_entity_id = None
             self._max_demand_trv_name = None

        # Control the heater if configured
        if self._heater_entity_id:
            target_hvac_mode = "off"
            target_to_set = self._minimum_temperature

            if self._is_heating_demanded:
                target_hvac_mode = "heat"
                if self._max_demand_target_temperature is not None:
                     target_to_set = self._max_demand_target_temperature

            self.hass.async_create_task(
                self._async_control_heater(target_to_set, target_hvac_mode)
            )

    async def _async_control_heater(self, target_temp: float, target_hvac_mode: str) -> None:
        """Send command to heater if configuration has changed."""
        
        # 1. Handle Temperature Change
        if self._last_sent_target_temperature != target_temp:
            _LOGGER.debug(
                "Setting heater %s temperature to %s", self._heater_entity_id, target_temp
            )
            try:
                await self.hass.services.async_call(
                    "climate",
                    "set_temperature",
                    {
                        "entity_id": self._heater_entity_id,
                        "temperature": target_temp,
                    },
                    blocking=False,
                )
                self._last_sent_target_temperature = target_temp
            except Exception as e:
                _LOGGER.error("Failed to set heater temperature: %s", e)

        # 2. Handle HVAC Mode Change
        # We check a new instance variable _last_sent_hvac_mode (need to init it)
        if getattr(self, "_last_sent_hvac_mode", None) != target_hvac_mode:
            _LOGGER.debug(
                "Setting heater %s hvac_mode to %s", self._heater_entity_id, target_hvac_mode
            )
            try:
                await self.hass.services.async_call(
                    "climate",
                    "set_hvac_mode",
                    {
                        "entity_id": self._heater_entity_id,
                        "hvac_mode": target_hvac_mode,
                    },
                    blocking=False,
                )
                self._last_sent_hvac_mode = target_hvac_mode
            except Exception as e:
                _LOGGER.error("Failed to set heater hvac_mode: %s", e)


    @property
    def is_on(self) -> bool:
        """Return true if the binary sensor is on."""
        return self._is_heating_demanded

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return {
            "trv_climate_entities": self._trv_climate_entities,
            "max_demand_delta": self._max_demand_delta,
            "max_demand_current_temperature": self._max_demand_current_temperature,
            "max_demand_target_temperature": self._max_demand_target_temperature,
            "max_demand_trv_entity_id": self._max_demand_trv_entity_id,
            "max_demand_trv_name": self._max_demand_trv_name,
            "heater_entity_id": self._heater_entity_id,
            "away_mode": self._is_away,
            "away_temperature": self._away_temp,
        }


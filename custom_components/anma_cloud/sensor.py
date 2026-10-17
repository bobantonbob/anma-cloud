from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers import entity_registry as er
from .const import DOMAIN, FIELDS, BOOLEAN_FIELDS, INVERTABLE
from .mapping import normalized_value

async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([AnmaSensor(entry, key) for key in FIELDS if key not in BOOLEAN_FIELDS and entry.options.get(key)])

class AnmaSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry, key):
        self.entry = entry
        self.key = key
        label, device_class, unit, state_class = FIELDS[key]
        self._attr_name = label
        self._attr_unique_id = f'{entry.entry_id}_{key}'
        self._attr_suggested_object_id = f'anma_{key}'
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name='ANMA Cloud')
        self._attr_native_unit_of_measurement = unit
        if device_class:
            self._attr_device_class = SensorDeviceClass(device_class)
        if state_class:
            self._attr_state_class = SensorStateClass(state_class)
        self._attr_available = False
        self._attr_native_value = None

    @property
    def entity_registry_enabled_default(self):
        return True

    async def async_added_to_hass(self):
        self.async_on_remove(async_track_state_change_event(self.hass, [self.entry.options[self.key]], self._on_state_change))
        self._sync()

    @callback
    def _on_state_change(self, event):
        self._sync()

    @callback
    def _sync(self):
        source = self.hass.states.get(self.entry.options[self.key])
        self._attr_native_value = normalized_value(
            source, self.key, self.key in INVERTABLE and self.entry.options.get(f'invert_{self.key}', False))
        self._attr_available = self._attr_native_value is not None
        self.async_write_ha_state()

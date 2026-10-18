from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN, FIELDS, BOOLEAN_FIELDS
from .mapping import normalized_value

async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([AnmaBinary(entry, key) for key in BOOLEAN_FIELDS if entry.options.get(key)])

class AnmaBinary(BinarySensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True
    def __init__(self, entry, key):
        self.entry = entry
        self.key = key
        self._attr_name = FIELDS[key][0]
        self._attr_unique_id = f'{entry.entry_id}_{key}'
        self._attr_suggested_object_id = f'anma_{key}'
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name=entry.title)
        self._attr_available = False
        self._attr_is_on = None

    async def async_added_to_hass(self):
        self.async_on_remove(async_track_state_change_event(self.hass, [self.entry.options[self.key]], self._changed))
        self._sync()

    @callback
    def _changed(self, event):
        self._sync()

    @callback
    def _sync(self):
        source = self.hass.states.get(self.entry.options[self.key])
        self._attr_is_on = normalized_value(source, self.key)
        self._attr_available = self._attr_is_on is not None
        self.async_write_ha_state()

"""Bounded, read-only Recorder history for the mapped sources only."""
from datetime import timedelta
from functools import partial
from aiohttp import web
from homeassistant.util import dt as dt_util
from homeassistant.components.recorder import get_instance, history
from .const import FIELDS, INVERTABLE, BOOLEAN_FIELDS
from .mapping import normalized_value

KEYS = ('pv_power','load_power','grid_power','battery_soc','battery_power','battery_state','pv_energy_today')

async def read_history(hass, entry):
    end = dt_util.utcnow()
    start = end - timedelta(hours=26)  # Covers local today, including DST days.
    sources = {key:entry.options[key] for key in KEYS if entry.options.get(key)}
    try:
        recorded = await get_instance(hass).async_add_executor_job(partial(
            history.get_significant_states, hass, start, end,
            list(set(sources.values())), include_start_time_state=True,
            significant_changes_only=False, minimal_response=False)) if sources else {}
    except Exception as exc:
        raise web.HTTPServiceUnavailable(reason='Recorder history unavailable') from exc
    groups = []
    for key, entity_id in sources.items():
        group = []
        for state in recorded.get(entity_id, []):
            value = normalized_value(state, key, key in INVERTABLE and entry.options.get(f'invert_{key}', False))
            domain = 'binary_sensor' if key in BOOLEAN_FIELDS else 'sensor'
            group.append({'entity_id':f'{domain}.anma_{key}',
                          'state':'unavailable' if value is None else ('on' if value else 'off') if isinstance(value,bool) else str(value),
                          'attributes':{'unit_of_measurement':FIELDS[key][2]},
                          'last_updated':state.last_updated.isoformat()})
        groups.append(group)
    return {'installation_id':entry.data['installation_id'], 'history':groups,
            'start':start.isoformat(), 'end':end.isoformat()}

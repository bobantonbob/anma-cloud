"""Read-only source selection and previews, shared with sensor normalization."""
import html
import math

from .const import BOOLEAN_FIELDS, FIELDS

NONE = "__anma_unmapped__"
UNITS = {"W": {"w": 1, "kw": 1000}, "kWh": {"kwh": 1, "wh": .001},
         "V": {"v": 1, "kv": 1000}, "%": {"%": 1}}
MISSING = {"unknown", "unavailable", "none", ""}


def normalized_value(state, key, invert=False):
    if state is None or str(state.state).lower() in MISSING:
        return None
    raw = str(state.state)
    if key == "inverter_status":
        return raw.strip()[:120]
    if key in BOOLEAN_FIELDS:
        return {"on": True, "off": False, "true": True, "false": False,
                "1": True, "0": False}.get(raw.lower())
    if key == "battery_state":
        return {"charge":"charge", "charging":"charge", "discharge":"discharge", "discharging":"discharge", "idle":"idle", "standby":"idle", "not charging":"idle"}.get(raw.strip().lower())
    unit = str(state.attributes.get("unit_of_measurement") or "").strip().lower()
    factor = UNITS[FIELDS[key][2]].get(unit)
    try:
        value = float(raw.replace(",", "."))
    except (TypeError, ValueError):
        return None
    if factor is None or not math.isfinite(value):
        return None
    return round(value * factor * (-1 if invert else 1), 3)


def compatible(state, key):
    domain = state.entity_id.split(".", 1)[0]
    if key == "inverter_status":
        return domain in ("sensor", "binary_sensor", "input_text")
    if key in BOOLEAN_FIELDS:
        return domain in ("binary_sensor", "sensor", "input_boolean") and (
            domain != "sensor" or str(state.state).lower() in
            ("on", "off", "true", "false", "1", "0", "unknown", "unavailable"))
    if domain not in ("sensor", "input_number"):
        return False
    if key == "battery_state":
        return domain == "sensor"
    unit = str(state.attributes.get("unit_of_measurement") or "").strip().lower()
    return unit in UNITS[FIELDS[key][2]]


def source_label(state, entity_id, language="en"):
    unavailable = "немає даних" if language == "uk" else "no data"
    if state is None:
        return f"{entity_id} · {unavailable}"
    name = str(state.attributes.get("friendly_name") or entity_id)
    value = str(state.state)
    if value.lower() in MISSING:
        value = f"{unavailable} ({value})"
    unit = str(state.attributes.get("unit_of_measurement") or "")
    return f"{name} · {value} {unit} · {entity_id}".replace("  ·", " ·")


def source_options(states, key, current=None, excluded=(), language="en"):
    choices = [{"value": s.entity_id, "label": source_label(s, s.entity_id, language)}
               for s in states.values() if s.entity_id not in excluded and compatible(s, key)]
    if current and current not in excluded and current not in {c["value"] for c in choices}:
        choices.append({"value": current, "label": source_label(states.get(current), current, language)})
    choices.sort(key=lambda c: c["label"].casefold())
    return [{"value": NONE, "label": "— Не використовувати —" if language == "uk" else "— Not mapped —"}, *choices]


def validate_mapping(values, states, existing, excluded):
    errors = {}
    for key in FIELDS:
        entity_id = values.get(key)
        if not entity_id or entity_id == NONE:
            continue
        if entity_id in excluded:
            errors[key] = "self_reference"
        elif entity_id not in states:
            if entity_id != existing.get(key):
                errors[key] = "entity_not_found"
        elif not compatible(states[entity_id], key) and entity_id != existing.get(key):
            errors[key] = "incompatible_source"
    return errors


def clean_options(values, existing):
    result = {k:v for k,v in existing.items() if k not in ("battery_charge_power", "battery_discharge_power", "inverter_fault_code")}
    for key in FIELDS:
        if values.get(key) and values[key] != NONE:
            result[key] = values[key]
        else:
            result.pop(key, None)
    for key in ("battery_power", "grid_power"):
        result[f"invert_{key}"] = bool(values.get(f"invert_{key}", False))
    return result


def markdown_cell(value):
    value = html.escape(str(value)).replace("\n", " ").replace("\r", " ")
    for char in ("\\", "|", "*", "_", "`", "[", "]"):
        value = value.replace(char, "\\" + char)
    return value


def system_summary(values, states, language="en"):
    """Describe only measured states; never infer grid presence from power."""
    uk = language == "uk"
    def value(key):
        return normalized_value(states.get(values.get(key)), key, values.get(f"invert_{key}", False))
    def power(number):
        return f"{abs(number) / 1000:.2f} kW" if abs(number) >= 1000 else f"{abs(number):g} W"
    unknown = "немає даних" if uk else "no data"
    pv, load, battery, soc, grid, available = (value(k) for k in
        ("pv_power", "load_power", "battery_power", "battery_soc", "grid_power", "grid_available"))
    if values.get('battery_state'):
        direction = value('battery_state')
        if battery is not None and direction in ('charge','discharge'):
            battery = abs(battery) * (1 if direction == 'charge' else -1)
        elif direction == 'idle':
            battery = 0
        else:
            battery = None
    solar = unknown if pv is None else (("генерація " if uk else "generating ") + power(pv) if pv > 0 else ("немає генерації" if uk else "no generation"))
    bat = unknown if battery is None else (("заряджається" if uk else "charging") if battery > 0 else
        ("розряджається" if uk else "discharging") if battery < 0 else ("без потоку" if uk else "idle"))
    if battery is not None:
        bat += f" · {power(battery)}"
    if soc is not None:
        bat += f" · {soc:g}%"
    network = unknown if grid is None else (("імпорт" if uk else "import") if grid > 0 else
        ("експорт" if uk else "export") if grid < 0 else ("без обміну" if uk else "no exchange")) + f" · {power(grid)}"
    if available is False:
        network = "відсутня" if uk else "offline"
        if grid is not None and grid != 0:
            network += " · ⚠ " + ("потужність суперечить статусу; перевірте джерела" if uk else "power conflicts with status; check sources")
    elif available is True:
        network = ("доступна · " if uk else "online · ") + network
    rows = [("☀️", "Сонце" if uk else "Solar", solar),
            ("🏠", "Будинок" if uk else "Home", unknown if load is None else power(load)),
            ("🔋", "Батарея" if uk else "Battery", bat),
            ("⚡", "Мережа" if uk else "Grid", network)]
    return "\n\n".join(f"{icon} **{label}:** {text}" for icon, label, text in rows)


def preview_table(values, states, labels, language="en"):
    headings = ("Показник", "Джерело та його значення", "Результат ANMA") if language == "uk" else ("Metric", "Source and current value", "ANMA result")
    rows = [" | ".join(headings), "--- | --- | ---"]
    for key in FIELDS:
        entity_id = values.get(key)
        if not entity_id or entity_id == NONE:
            continue
        state = states.get(entity_id)
        value = normalized_value(state, key, values.get(f"invert_{key}", False))
        if value is None:
            display = "Немає даних" if language == "uk" else "No data"
        elif isinstance(value, bool):
            display = "on" if value else "off"
        else:
            display = f"{value} {FIELDS[key][2] or ''}".strip()
        rows.append(" | ".join(markdown_cell(x) for x in
                    (labels.get(key, FIELDS[key][0]), source_label(state, entity_id, language), display)))
    if len(rows) == 2:
        return "Жодного джерела не вибрано." if language == "uk" else "No sources selected."
    return "\n".join(rows)

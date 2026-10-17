DOMAIN = 'anma_cloud'
FIELDS = {
    'pv_power': ('PV power', 'power', 'W', 'measurement'),
    'load_power': ('Load power', 'power', 'W', 'measurement'),
    'battery_soc': ('Battery SOC', 'battery', '%', 'measurement'),
    'battery_power': ('Battery power', 'power', 'W', 'measurement'),
    'grid_power': ('Grid power', 'power', 'W', 'measurement'),
    'grid_voltage': ('Grid voltage', 'voltage', 'V', 'measurement'),
    'pv_energy_today': ('PV energy today', 'energy', 'kWh', None),
    'load_energy_today': ('Load energy today', 'energy', 'kWh', None),
    'grid_import_today': ('Grid import today', 'energy', 'kWh', None),
    'grid_export_today': ('Grid export today', 'energy', 'kWh', None),
    'battery_charge_today': ('Battery charge today', 'energy', 'kWh', None),
    'battery_discharge_today': ('Battery discharge today', 'energy', 'kWh', None),
    'grid_available': ('Grid available', None, None, None),
    'inverter_fault': ('Inverter fault', None, None, None),
    'inverter_status': ('Inverter status', None, None, None),
    'battery_state': ('Battery state', None, None, None),
    'pv_forecast_today': ('PV forecast today', 'energy', 'kWh', None),
    'pv_forecast_tomorrow': ('PV forecast tomorrow', 'energy', 'kWh', None),
}
BOOLEAN_FIELDS = {'grid_available', 'inverter_fault'}
INVERTABLE = {'battery_power', 'grid_power'}

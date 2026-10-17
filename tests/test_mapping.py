"""Regression tests with real voluptuous and stubbed Home Assistant boundaries."""
import importlib
import json
from pathlib import Path
import sys
import types
import unittest
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.test-deps'))
import voluptuous as vol

package = types.ModuleType('anma_test_component')
package.__path__ = [str(ROOT / 'custom_components/anma_cloud')]
sys.modules[package.__name__] = package
mapping = importlib.import_module('anma_test_component.mapping')

def state(eid, value='100', unit='W', name='Battery power'):
    return types.SimpleNamespace(entity_id=eid,state=value,attributes={'unit_of_measurement':unit,'friendly_name':name})

class SourceTests(unittest.TestCase):
    def test_battery_state_source(self):
        for raw,expected in [('charge','charge'),('Discharging','discharge'),('idle','idle'),('unknown',None),('fault',None)]:
            self.assertEqual(mapping.normalized_value(state('sensor.status',raw,None),'battery_state'),expected)
        self.assertTrue(mapping.compatible(state('sensor.status','charge',None),'battery_state'))
        sources={'sensor.power':state('sensor.power','400'),'sensor.status':state('sensor.status','discharge',None)}
        text=mapping.system_summary({'battery_power':'sensor.power','battery_state':'sensor.status'},sources,'en')
        self.assertIn('discharging',text)

    def test_summary_directions_and_inversion(self):
        states={'sensor.bat':state('sensor.bat','1500'), 'sensor.grid':state('sensor.grid','-200')}
        values={'battery_power':'sensor.bat','grid_power':'sensor.grid'}
        text=mapping.system_summary(values,states,'uk')
        self.assertIn('заряджається · 1.50 kW',text);self.assertIn('експорт · 200 W',text)
        values['invert_battery_power']=True;values['invert_grid_power']=True
        text=mapping.system_summary(values,states,'uk')
        self.assertIn('розряджається',text);self.assertIn('імпорт',text)

    def test_summary_missing_is_not_zero_or_grid_outage(self):
        text=mapping.system_summary({}, {}, 'uk')
        self.assertEqual(text.count('немає даних'),4);self.assertNotIn('відсутня',text)
        s=state('sensor.grid','0')
        text=mapping.system_summary({'grid_power':s.entity_id},{s.entity_id:s},'uk')
        self.assertIn('без обміну',text);self.assertNotIn('відсутня',text)

    def test_summary_offline_conflict_and_solar_zero(self):
        states={s.entity_id:s for s in [state('sensor.pv','0'),state('sensor.grid','100'),state('binary_sensor.grid','off',None)]}
        text=mapping.system_summary({'pv_power':'sensor.pv','grid_power':'sensor.grid','grid_available':'binary_sensor.grid'},states,'uk')
        self.assertIn('немає генерації',text);self.assertIn('відсутня',text);self.assertIn('суперечить',text)

    def test_search_label(self):
        s=state('sensor.bat','-0.743','kW')
        label=mapping.source_options({s.entity_id:s},'battery_power')[1]['label']
        for text in ['Battery power','sensor.bat','-0.743','kW']:self.assertIn(text,label)

    def test_filter_and_self_exclusion(self):
        states={s.entity_id:s for s in [state('sensor.pv'),state('sensor.soc','70','%'),state('switch.load'),state('sensor.own')]}
        choices=mapping.source_options(states,'pv_power',excluded={'sensor.own'})
        self.assertEqual([c['value'] for c in choices],[mapping.NONE,'sensor.pv'])

    def test_missing_existing_mapping_retained(self):
        choices=mapping.source_options({},'battery_power','sensor.missing',language='uk')
        self.assertEqual(choices[1]['value'],'sensor.missing');self.assertIn('немає даних',choices[1]['label'])
        self.assertEqual(mapping.validate_mapping({'battery_power':'sensor.missing'},{},{'battery_power':'sensor.missing'},set()),{})

    def test_typed_non_entity_and_wrong_units_rejected(self):
        self.assertEqual(mapping.validate_mapping({'pv_power':'bat'},{},{},set()),{'pv_power':'entity_not_found'})
        self.assertEqual(mapping.validate_mapping({'pv_power':'sensor.soc'},{'sensor.soc':state('sensor.soc','70','%')},{},set()),{'pv_power':'incompatible_source'})

    def test_clear_preserves_unrelated_options(self):
        old={'pv_power':'sensor.pv','future':42}
        new=mapping.clean_options({'pv_power':mapping.NONE},old)
        self.assertNotIn('pv_power',new);self.assertEqual(new['future'],42);self.assertIn('pv_power',old)

    def test_units_sign_and_unavailable(self):
        self.assertEqual(mapping.normalized_value(state('sensor.bat','0.743','kW'),'battery_power',True),-743)
        self.assertEqual(mapping.normalized_value(state('sensor.energy','1234','Wh'),'pv_energy_today'),1.234)
        self.assertIs(mapping.normalized_value(state('binary_sensor.grid','off',None),'grid_available'),False)
        for value in ['unknown','unavailable','nan','inf','bad']:
            self.assertIsNone(mapping.normalized_value(state('sensor.bat',value),'battery_power'))

    def test_preview_escaped_and_normalized(self):
        s=state('sensor.bat','1','kW','<img> [link](url) | name')
        text=mapping.preview_table({'battery_power':s.entity_id,'invert_battery_power':True},{s.entity_id:s},{},'uk')
        self.assertIn('-1000.0 W',text);self.assertNotIn('<img>',text);self.assertIn('\\|',text)

class FlowBase:
    def __init_subclass__(cls,**kwargs):return super().__init_subclass__()
    def async_show_form(self,**kwargs):return {'type':'form',**kwargs}
    def async_show_menu(self,**kwargs):return {'type':'menu',**kwargs}
    def async_create_entry(self,**kwargs):return {'type':'create_entry',**kwargs}

class Selector:
    def __init__(self,config):self.config=config
    def __call__(self,value):
        if self.config.get('custom_value') and isinstance(value,str):return value
        if value not in [x['value'] if isinstance(x,dict) else x for x in self.config['options']]:raise vol.Invalid('not an option')
        return value

for name in ['homeassistant','homeassistant.config_entries','homeassistant.core','homeassistant.helpers',
             'homeassistant.helpers.entity_registry','homeassistant.helpers.selector',
             'homeassistant.helpers.translation','homeassistant.util','homeassistant.util.dt']:
    sys.modules[name]=types.ModuleType(name)
entries=sys.modules['homeassistant.config_entries'];entries.ConfigFlow=FlowBase;entries.OptionsFlow=FlowBase
sys.modules['homeassistant.core'].callback=lambda fn:fn
sys.modules['homeassistant.helpers.entity_registry'].async_get=lambda hass:hass.registry
selector=sys.modules['homeassistant.helpers.selector'];selector.SelectSelector=Selector;selector.SelectSelectorConfig=dict
selector.SelectSelectorMode=types.SimpleNamespace(DROPDOWN='dropdown')
async def translations(*args,**kwargs):return {}
sys.modules['homeassistant.helpers.translation'].async_get_translations=translations
sys.modules['homeassistant.util.dt'].now=datetime.now
flow_module=importlib.import_module('anma_test_component.config_flow')

class FlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.source=state('sensor.bat','743');self.states={self.source.entity_id:self.source}
        self.flow=flow_module.AnmaOptionsFlow();self.flow.context={'language':'uk'}
        self.flow.config_entry=types.SimpleNamespace(options={'battery_power':'sensor.bat','invert_battery_power':True,'future':42})
        self.flow.hass=types.SimpleNamespace(config=types.SimpleNamespace(language='en'),
            states=types.SimpleNamespace(async_all=lambda:list(self.states.values())),
            registry=types.SimpleNamespace(entities={'own':types.SimpleNamespace(entity_id='sensor.own',platform='anma_cloud')}))

    async def test_refresh_preserves_draft_and_updates_values(self):
        form=await self.flow.async_step_init()
        self.assertIn('розряджається',form['description_placeholders']['summary'])
        payload=form['data_schema']({'battery_power':'sensor.bat','form_action':'refresh'})
        self.source.state='950';refreshed=await self.flow.async_step_init(payload)
        selectors={str(key):value for key,value in refreshed['data_schema'].schema.items()}
        self.assertTrue(selectors['battery_power'].config['custom_value'])
        self.assertIn('950 W',selectors['battery_power'].config['options'][1]['label'])
        self.assertTrue(self.flow._draft['invert_battery_power'])

    async def test_review_refresh_save(self):
        review=await self.flow.async_step_init({'battery_power':'sensor.bat','invert_battery_power':True})
        self.assertEqual(review['type'],'menu');self.assertIn('-743.0 W',review['description_placeholders']['preview'])
        self.source.state='800';refreshed=await self.flow.async_step_refresh()
        self.assertIn('-800.0 W',refreshed['description_placeholders']['preview'])
        saved=await self.flow.async_step_save()
        self.assertEqual(saved['type'],'create_entry');self.assertEqual(saved['data']['future'],42)
        self.assertEqual(saved['data']['battery_power'],'sensor.bat');self.assertNotIn('form_action',saved['data'])

    async def test_new_source_disappearing_before_save(self):
        self.states['sensor.new']=state('sensor.new')
        await self.flow.async_step_init({'battery_power':'sensor.new'})
        del self.states['sensor.new'];result=await self.flow.async_step_save()
        self.assertEqual(result['errors']['battery_power'],'entity_not_found')

    async def test_self_reference_rejected(self):
        result=await self.flow.async_step_init({'battery_power':'sensor.own'})
        self.assertEqual(result['errors']['battery_power'],'self_reference')

    async def test_clear_survives_edit(self):
        await self.flow.async_step_init({'battery_power':mapping.NONE});await self.flow.async_step_edit()
        saved=await self.flow.async_step_save();self.assertNotIn('battery_power',saved['data'])

class PackagingTests(unittest.TestCase):
    def test_translations_and_brand(self):
        folder=ROOT/'custom_components/anma_cloud'
        en=json.loads((folder/'translations/en.json').read_text(encoding='utf-8'))
        uk=json.loads((folder/'translations/uk.json').read_text(encoding='utf-8'))
        self.assertEqual(set(en['options']['step']['init']['data']),set(uk['options']['step']['init']['data']))
        for data in [en,uk]:self.assertEqual(set(data['options']['step']['review']['menu_options']),{'save','edit','refresh'})
        for name in ['icon.png','icon@2x.png','dark_icon.png','dark_icon@2x.png']:
            self.assertTrue((folder/'brand'/name).read_bytes().startswith(b'\x89PNG\r\n\x1a\n'))

if __name__=='__main__':unittest.main()

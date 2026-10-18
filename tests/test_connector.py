"""Exercise actual connector handlers over aiohttp; only HA host services are stubbed."""
import hashlib
import hmac
import importlib
import sys
import time
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

ROOT=Path(__file__).resolve().parents[1]
package=types.ModuleType('anma_connector_test');package.__path__=[str(ROOT/'custom_components/anma_cloud')]
sys.modules[package.__name__]=package
for name in ['homeassistant','homeassistant.components','homeassistant.components.http']:
    sys.modules[name]=types.ModuleType(name)
class View:
    def json(self,data,headers=None):return web.json_response(data,headers=headers)
sys.modules['homeassistant.components.http'].HomeAssistantView=View
sys.modules['homeassistant.components.http'].KEY_HASS=web.AppKey('hass')
module=importlib.import_module(package.__name__+'.pairing')


class ConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.entry=types.SimpleNamespace(entry_id='entry',data={'installation_id':'a'*32},options={'battery_power':'sensor.bat','invert_battery_power':True})
        source=types.SimpleNamespace(state='2',attributes={'unit_of_measurement':'kW'},last_updated=datetime.now(timezone.utc))
        self.hass=types.SimpleNamespace(data={},states=types.SimpleNamespace(get=lambda _:source))
        self.hass.config_entries=types.SimpleNamespace(async_entries=lambda _:[self.entry],
            async_update_entry=lambda entry,data:setattr(entry,'data',data))
        self.app=web.Application();self.app[module.KEY_HASS]=self.hass
        view=module.AnmaConnectorView()
        async def post(request):return await view.post(request,request.match_info['action'])
        async def get(request):return await view.get(request,request.match_info['action'])
        self.app.router.add_post('/api/anma_cloud/{action}',post)
        self.app.router.add_get('/api/anma_cloud/{action}',get)
        self.client=TestClient(TestServer(self.app));await self.client.start_server()
        self.window=module.window(self.hass,'entry')
        self.code=self.window.generate().replace('-','')
        self.token='test-scoped-credential'

    async def asyncTearDown(self):await self.client.close()

    def payload(self,code=None,nonce='b'*32):
        value={'nonce':nonce,'timestamp':int(time.time()),'credential_hash':hashlib.sha256(self.token.encode()).hexdigest()}
        text=f"{value['nonce']}\n{value['timestamp']}\n{value['credential_hash']}"
        value['proof']=hmac.new((code or self.code).encode(),text.encode(),hashlib.sha256).hexdigest()
        return value

    async def test_pair_read_and_single_use(self):
        proof=self.payload()
        verify=await self.client.post('/api/anma_cloud/verify',json=proof)
        self.assertEqual(verify.status,200);self.assertNotIn('connector_hash',self.entry.data)
        claim=await self.client.post('/api/anma_cloud/pair',json=proof)
        self.assertTrue((await claim.json())['paired']);self.assertIsNone(self.window.code)
        self.assertNotIn(self.token,str(self.entry.data))
        retry=await self.client.post('/api/anma_cloud/pair',json=proof)
        self.assertEqual(retry.status,200)
        second=await self.client.post('/api/anma_cloud/pair',json=self.payload(nonce='c'*32))
        self.assertEqual(second.status,401)
        states=await self.client.get('/api/anma_cloud/states',headers={'Authorization':'Bearer '+self.token})
        payload=await states.json()
        self.assertEqual(payload['states'][0]['state'],'-2000.0')
        self.assertEqual(payload['states'][0]['entity_id'],'sensor.anma_battery_power')
        self.assertNotIn(self.code,str(payload));self.assertNotIn(self.token,str(payload))

    async def test_multiple_entries_are_isolated(self):
        second = types.SimpleNamespace(entry_id='second', data={'installation_id':'d'*32},
                                       options={'battery_soc':'sensor.soc'})
        self.hass.config_entries.async_entries = lambda _: [self.entry, second]
        second_window = module.window(self.hass, 'second')
        second_code = second_window.generate().replace('-', '')
        first_token = self.token
        await self.client.post('/api/anma_cloud/pair', json=self.payload())
        self.token = 'second-credential'
        proof = self.payload(second_code)
        # Repeated valid verification of one entry must not lock out another.
        for _ in range(21):
            response = await self.client.post('/api/anma_cloud/verify', json=proof)
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())['installation_id'], 'd'*32)
        self.assertEqual(self.window.failures, 0)
        self.assertEqual((await self.client.post('/api/anma_cloud/pair', json=proof)).status, 200)
        self.assertEqual((await self.client.post('/api/anma_cloud/pair', json=proof)).status, 200)
        for token, installation, field in [(first_token, 'a'*32, 'battery_power'),
                                           (self.token, 'd'*32, 'battery_soc')]:
            response = await self.client.get('/api/anma_cloud/states', headers={'Authorization':'Bearer '+token})
            data = await response.json()
            self.assertEqual(data['installation_id'], installation)
            self.assertEqual([item['entity_id'] for item in data['states']], ['sensor.anma_'+field])
        history_module = types.ModuleType(package.__name__+'.history')
        async def history(hass, entry):
            return {'installation_id':entry.data['installation_id'], 'history':[]}
        history_module.read_history = history
        from unittest.mock import patch
        with patch.dict(sys.modules, {history_module.__name__: history_module}):
            for token, installation in [(first_token, 'a'*32), (self.token, 'd'*32)]:
                response = await self.client.get('/api/anma_cloud/history', headers={'Authorization':'Bearer '+token})
                self.assertEqual((await response.json())['installation_id'], installation)
        second.data.pop('connector_hash')
        self.assertEqual((await self.client.get('/api/anma_cloud/states', headers={'Authorization':'Bearer '+self.token})).status, 401)
        self.assertEqual((await self.client.get('/api/anma_cloud/states', headers={'Authorization':'Bearer '+first_token})).status, 200)
        self.hass.config_entries.async_entries = lambda _: [second]
        self.assertEqual((await self.client.get('/api/anma_cloud/states', headers={'Authorization':'Bearer '+first_token})).status, 401)

    async def test_wrong_expired_malformed_and_unauthed(self):
        for payload in [self.payload('0'*32),{},[],{'timestamp':'bad'}]:
            response=await self.client.post('/api/anma_cloud/pair',json=payload)
            self.assertEqual(response.status,401)
        self.window.expires=time.time()-1
        self.assertEqual((await self.client.post('/api/anma_cloud/pair',json=self.payload())).status,401)
        self.assertEqual((await self.client.get('/api/anma_cloud/states')).status,401)
        self.assertEqual((await self.client.get('/api/anma_cloud/not-supported')).status,404)

    async def test_revoke_and_regenerate(self):
        await self.client.post('/api/anma_cloud/pair',json=self.payload())
        self.entry.data.pop('connector_hash')
        response=await self.client.get('/api/anma_cloud/states',headers={'Authorization':'Bearer '+self.token})
        self.assertEqual(response.status,401)
        old=self.code;self.code=self.window.generate().replace('-','')
        self.assertNotEqual(self.code,old)
        self.assertEqual((await self.client.post('/api/anma_cloud/verify',json=self.payload(old))).status,401)

if __name__=='__main__':unittest.main()

"""Short-lived setup proof and a separate read-only ANMA credential.

Pairing codes exist only in memory, never in entities, logs, or recorder.
Transport must be restricted to the operator's Tailscale network with ACLs.
"""
import hashlib
import hmac
import re
import secrets
import time
from aiohttp import web
from homeassistant.components.http import HomeAssistantView, KEY_HASS
from .const import DOMAIN, FIELDS, BOOLEAN_FIELDS, INVERTABLE
from .mapping import normalized_value


class PairingWindow:
    def __init__(self):
        self.code = None
        self.expires = 0
        self.used_proof = None
        self.failures = 0

    def generate(self):
        self.code = secrets.token_hex(16).upper()
        self.expires = time.time() + 900
        self.used_proof = None
        self.failures = 0
        return '-'.join(self.code[i:i+4] for i in range(0,32,4))

    def valid(self, data, retry=False, count_failure=True):
        if not isinstance(data, dict) or time.time() > self.expires or self.failures >= 20:
            return False
        nonce, stamp, digest, proof = (data.get(k) for k in ('nonce','timestamp','credential_hash','proof'))
        if (not isinstance(nonce,str) or not re.fullmatch(r'[a-f0-9]{32}',nonce)
                or type(stamp) is not int or abs(time.time()-stamp)>120
                or not isinstance(digest,str) or not re.fullmatch(r'[a-f0-9]{64}',digest)
                or not isinstance(proof,str) or not re.fullmatch(r'[a-f0-9]{64}',proof)):
            return False
        if retry and self.used_proof:
            return hmac.compare_digest(self.used_proof, proof)
        if not self.code or self.used_proof:
            return False
        expected = hmac.new(self.code.encode(), f'{nonce}\n{stamp}\n{digest}'.encode(), hashlib.sha256).hexdigest()
        valid = hmac.compare_digest(expected, proof)
        if not valid and count_failure:
            self.failures += 1
        return valid


def window(hass, entry_id):
    return hass.data.setdefault(DOMAIN, {}).setdefault('pairing', {}).setdefault(entry_id, PairingWindow())


class AnmaConnectorView(HomeAssistantView):
    url = '/api/anma_cloud/{action}'
    name = 'api:anma_cloud:connector'
    requires_auth = False  # Custom scoped credential, never an HA administrative token.

    async def post(self, request, action):
        if action not in ('verify','pair'):
            raise web.HTTPNotFound()
        if request.content_length is None or request.content_length > 2048:
            raise web.HTTPBadRequest()
        try:
            data = await request.json()
        except (ValueError, UnicodeError):
            raise web.HTTPBadRequest() from None
        hass = request.app[KEY_HASS]
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            raise web.HTTPNotFound()
        matches = [(candidate, window(hass, candidate.entry_id)) for candidate in entries
                   if window(hass, candidate.entry_id).valid(
                       data, retry=action == 'pair', count_failure=False)]
        if len(matches) != 1:
            for candidate in entries:
                window(hass, candidate.entry_id).valid(data, retry=action == 'pair')
            raise web.HTTPUnauthorized()
        entry, pairing = matches[0]
        if action == 'pair' and not pairing.used_proof:
            # No await between validation/consumption: concurrent claims cannot both succeed.
            hass.config_entries.async_update_entry(entry, data={**entry.data, 'connector_hash':data['credential_hash']})
            pairing.used_proof = data['proof']
            pairing.code = None
        return self.json({'protocol':1, 'installation_id':entry.data['installation_id'], 'paired':action=='pair'},
                         headers={'Cache-Control':'no-store'})

    async def get(self, request, action):
        if action not in ('states', 'history'):
            raise web.HTTPNotFound()
        hass = request.app[KEY_HASS]
        entries = hass.config_entries.async_entries(DOMAIN)
        header = request.headers.get('Authorization','')
        if not header.startswith('Bearer ') or len(header)>256:
            raise web.HTTPUnauthorized()
        digest = hashlib.sha256(header[7:].encode()).hexdigest()
        matches = [candidate for candidate in entries
                   if candidate.data.get('connector_hash') and
                   hmac.compare_digest(digest, candidate.data['connector_hash'])]
        if len(matches) != 1:
            raise web.HTTPUnauthorized()
        entry = matches[0]
        if action == 'history':
            from .history import read_history
            return self.json(await read_history(hass, entry), headers={'Cache-Control':'no-store'})
        states = []
        for key in FIELDS:
            source_id = entry.options.get(key)
            if not source_id:
                continue
            source = hass.states.get(source_id)
            value = normalized_value(source,key,key in INVERTABLE and entry.options.get(f'invert_{key}',False))
            raw = 'unavailable' if value is None else ('on' if value else 'off') if isinstance(value,bool) else str(value)
            domain = 'binary_sensor' if key in BOOLEAN_FIELDS else 'sensor'
            states.append({'entity_id':f'{domain}.anma_{key}', 'state':raw,
                           'attributes':{'unit_of_measurement':FIELDS[key][2]},
                           'last_updated':source.last_updated.isoformat() if source else None})
        return self.json({'installation_id':entry.data['installation_id'], 'states':states},headers={'Cache-Control':'no-store'})

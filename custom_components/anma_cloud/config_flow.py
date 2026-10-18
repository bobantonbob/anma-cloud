import secrets
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, SelectSelectorMode
from homeassistant.helpers.translation import async_get_translations
from homeassistant.util import dt as dt_util
from .const import DOMAIN, FIELDS, INVERTABLE
from .mapping import clean_options, preview_table, source_options, validate_mapping, system_summary

class AnmaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            await self.async_set_unique_id(secrets.token_hex(16))
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=user_input['name'].strip() or 'ANMA Cloud', data={'installation_id': secrets.token_hex(16)})
        return self.async_show_form(step_id='user', data_schema=vol.Schema({vol.Required('name', default='ANMA Cloud'): str}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return AnmaOptionsFlow()

class AnmaOptionsFlow(config_entries.OptionsFlow):
    def __init__(self):
        self._draft = None

    @property
    def _language(self):
        return self.context.get('language') or self.hass.config.language or 'en'

    def _states(self):
        return {s.entity_id: s for s in self.hass.states.async_all()}

    def _excluded(self):
        registry = er.async_get(self.hass)
        return {entry.entity_id for entry in registry.entities.values() if entry.platform == DOMAIN}

    async def async_step_init(self, user_input=None):
        if self._draft is None:
            self._draft = dict(self.config_entry.options)
        states = self._states()
        excluded = self._excluded()
        errors = {}
        if user_input is not None:
            if user_input.get('form_action') == 'pairing':
                self._draft = clean_options(user_input, self._draft)
                return await self.async_step_pairing()
            errors = validate_mapping(user_input, states, self.config_entry.options, excluded)
            self._draft = clean_options(user_input, self._draft)
            if not errors and user_input.get('form_action', 'review') == 'review':
                return await self.async_step_review()
        schema = {}
        for key in FIELDS:
            suggested = {'suggested_value': self._draft[key]} if self._draft.get(key) else {}
            # custom_value enables HA's searchable picker; typed values are
            # checked against actual states before anything is saved.
            schema[vol.Optional(key, description=suggested)] = SelectSelector(SelectSelectorConfig(
                options=source_options(states, key, self._draft.get(key), excluded, self._language),
                mode=SelectSelectorMode.DROPDOWN, custom_value=True))
        for key in sorted(INVERTABLE):
            flag = f'invert_{key}'
            schema[vol.Optional(flag, default=self._draft.get(flag, False))] = bool
        schema[vol.Required('form_action', default='review')] = SelectSelector(SelectSelectorConfig(
            options=['review', 'refresh', 'pairing'], translation_key='form_action', mode=SelectSelectorMode.DROPDOWN))
        return self.async_show_form(step_id='init', data_schema=vol.Schema(schema), errors=errors,
            description_placeholders={'updated': dt_util.now().strftime('%H:%M:%S'),
                                      'summary': system_summary(self._draft, states, self._language)})

    async def async_step_review(self, user_input=None):
        translations = await async_get_translations(self.hass, self._language, 'options', {DOMAIN})
        labels = {key: translations.get(f'component.{DOMAIN}.options.step.init.data.{key}', FIELDS[key][0]) for key in FIELDS}
        states = self._states()
        return self.async_show_menu(step_id='review', menu_options=['save', 'edit', 'refresh'],
            description_placeholders={'preview': preview_table(self._draft, states, labels, self._language),
                                      'summary': system_summary(self._draft, states, self._language),
                                      'updated': dt_util.now().strftime('%H:%M:%S')})

    async def async_step_edit(self, user_input=None):
        return await self.async_step_init()

    async def async_step_refresh(self, user_input=None):
        return await self.async_step_review()

    async def async_step_save(self, user_input=None):
        errors = validate_mapping(self._draft, self._states(), self.config_entry.options, self._excluded())
        if errors:
            return await self.async_step_init({**self._draft, 'form_action': 'review'})
        return self.async_create_entry(title='', data=self._draft)

    async def async_step_pairing(self, user_input=None):
        return self.async_show_menu(step_id='pairing', menu_options=['generate_code','revoke','edit'])

    async def async_step_generate_code(self, user_input=None):
        from .pairing import window
        if user_input is not None:
            return await self.async_step_pairing()
        code = window(self.hass, self.config_entry.entry_id).generate()
        return self.async_show_form(step_id='generate_code', data_schema=vol.Schema({}),
                                    description_placeholders={'code':code})

    async def async_step_revoke(self, user_input=None):
        if user_input is not None:
            from .pairing import window
            data = dict(self.config_entry.data)
            data.pop('connector_hash', None)
            self.hass.config_entries.async_update_entry(self.config_entry, data=data)
            current = window(self.hass, self.config_entry.entry_id)
            current.code = None
            current.expires = 0
            return await self.async_step_pairing()
        return self.async_show_form(step_id='revoke', data_schema=vol.Schema({}))

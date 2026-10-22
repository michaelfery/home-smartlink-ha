"""Config flow for Home-SmartLink."""

from __future__ import annotations

import logging
from typing import Any

import probatio
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from homesmartlink import (
    AuthenticationError,
    CannotConnectError,
    HomeSmartLinkClient,
    HomeSmartLinkError,
    Invitation,
)

from .const import CONF_HOME_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_EMAIL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="username")
        ),
        probatio.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
        ),
    }
)


class HomeSmartLinkConfigFlow(ConfigFlow, domain=DOMAIN):
    """Sign in with the Home-SmartLink app credentials."""

    VERSION = 1

    def __init__(self) -> None:
        self._credentials: dict[str, str] = {}
        self._invitations: list[Invitation] = []

    async def _sign_in(self, email: str, password: str) -> tuple[list[Invitation], str | None]:
        """Return the account's homes, or an error key for the form."""
        client = HomeSmartLinkClient(async_get_clientsession(self.hass), email, password)
        try:
            invitations = await client.login()
            if not invitations:
                invitations = await client.get_invitations()
        except AuthenticationError:
            return [], "invalid_auth"
        except CannotConnectError:
            return [], "cannot_connect"
        except HomeSmartLinkError:
            _LOGGER.exception("Unexpected response while signing in")
            return [], "unknown"
        if not invitations:
            return [], "no_home"
        return invitations, None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            invitations, error = await self._sign_in(email, user_input[CONF_PASSWORD])
            if error:
                errors["base"] = error
            else:
                self._credentials = {CONF_EMAIL: email, CONF_PASSWORD: user_input[CONF_PASSWORD]}
                self._invitations = invitations
                if len(invitations) == 1:
                    return await self._create_entry(invitations[0].home_id)
                return await self.async_step_home()

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_home(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Pick a home when the account has access to several."""
        if user_input is not None:
            return await self._create_entry(user_input[CONF_HOME_ID])

        home_ids = [i.home_id for i in self._invitations]
        return self.async_show_form(
            step_id="home",
            data_schema=probatio.Schema(
                {
                    probatio.Required(CONF_HOME_ID): SelectSelector(
                        SelectSelectorConfig(options=home_ids)
                    )
                }
            ),
        )

    async def _create_entry(self, home_id: str) -> ConfigFlowResult:
        await self.async_set_unique_id(home_id)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=f"Home-SmartLink ({self._credentials[CONF_EMAIL]})",
            data={**self._credentials, CONF_HOME_ID: home_id},
        )

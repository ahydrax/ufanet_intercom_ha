"""Config flow for the Ufanet Intercom integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant import config_entries

if TYPE_CHECKING:
    from homeassistant.data_entry_flow import FlowResult

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .api import UfanetApiAuthError, UfanetApiClient, UfanetApiError
from .const import CONF_CONTRACT, CONF_PASSWORD, DOMAIN

STORAGE_KEY = f"{DOMAIN}_credentials"
STORAGE_VERSION = 1

_LOGGER = logging.getLogger(__name__)


def _is_auth_error(error_msg: str, exception_name: str) -> bool:
    """Check if error message or exception name indicates authentication failure."""
    error_msg_lower = error_msg.lower()
    exception_name_lower = exception_name.lower()

    # Explicit auth errors
    if "unauthorized" in exception_name_lower:
        return True

    # Auth-related keywords
    auth_keywords = [
        "невозможно войти",
        "учетными данными",
        "неверный",
        "неправильный",
        "invalid",
        "auth",
        "login",
        "password",
        "unauthorized",
        "forbidden",
        "401",
        "403",
        "decoding signature",
        "error decoding",
    ]

    return any(keyword in error_msg_lower for keyword in auth_keywords)


def _extract_error_message(err: Exception) -> str:
    """Extract error message from exception."""
    error_msg = str(err)

    if isinstance(err.args[0] if err.args else None, dict):
        # Try to extract message from dict
        error_dict = err.args[0]
        if "non_field_errors" in error_dict:
            error_list = error_dict["non_field_errors"]
            if error_list:
                return " ".join(str(e) for e in error_list)
        if "detail" in error_dict:
            return str(error_dict["detail"])
        return str(error_dict)

    if err.args:
        return str(err.args[0])

    return error_msg


class UfanetIntercomConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Ufanet Intercom."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step: ask for credentials and validate them."""
        errors: dict[str, str] = {}

        if user_input is not None:
            contract = user_input[CONF_CONTRACT]
            password = user_input[CONF_PASSWORD]

            _LOGGER.debug("Starting authentication for contract: %s", contract)

            await self.async_set_unique_id(contract)
            self._abort_if_unique_id_configured()

            session = async_get_clientsession(self.hass)
            client = UfanetApiClient(session, contract, password=password)

            # Store for saving token
            store = Store(self.hass, STORAGE_VERSION, STORAGE_KEY)
            stored_data = await store.async_load() or {}
            refresh_token = None
            token_exp = None

            async def save_token(token: str, exp: int) -> None:
                nonlocal refresh_token, token_exp
                refresh_token = token
                token_exp = exp
                if contract not in stored_data:
                    stored_data[contract] = {}
                stored_data[contract]["refresh_token"] = token
                stored_data[contract]["refresh_exp"] = exp
                # Also save password for re-authentication if refresh token expires
                stored_data[contract]["password"] = password
                await store.async_save(stored_data)

            try:
                errors = await self._validate_and_create_entry(
                    client, save_token, contract
                )
                if not errors:
                    return errors  # This is actually FlowResult from create_entry
            except UfanetApiAuthError as err:
                _LOGGER.warning("Authentication failed: %s", err)
                errors["base"] = "auth"
            except UfanetApiError:
                _LOGGER.exception("API error during authentication")
                errors["base"] = "unknown"
            except Exception:
                errors = self._handle_generic_exception()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CONTRACT): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def _validate_and_create_entry(
        self,
        client: UfanetApiClient,
        save_token: callable,
        contract: str,
    ) -> dict[str, str] | FlowResult:
        """Validate credentials and create config entry."""
        _LOGGER.debug("Requesting intercom list")
        intercoms = await client.async_get_intercoms(on_token_update=save_token)
        _LOGGER.debug("Fetched %s intercoms", len(intercoms))

        if not intercoms:
            return {"base": "no_intercoms"}

        # Save all intercoms as a list
        intercoms_data = [
            {
                "id": intercom.id,
                "name": intercom.role_name
                or intercom.string_view
                or intercom.custom_name
                or f"Intercom {intercom.id}",
            }
            for intercom in intercoms
        ]

        # Create entry with contract and intercoms
        # (no password/token in entry.data)
        data = {
            CONF_CONTRACT: contract,
            "intercoms": intercoms_data,
        }

        return self.async_create_entry(title=contract, data=data)

    def _handle_generic_exception(self) -> dict[str, str]:
        """Handle generic exceptions and determine error type."""
        import sys

        err = sys.exc_info()[1]

        _LOGGER.exception("Error validating credentials")
        _LOGGER.error(
            "Exception type: %s, message: %s", type(err).__name__, str(err)
        )

        # Extract error message
        error_msg = _extract_error_message(err)
        exception_name = type(err).__name__

        # Check if it's an auth error
        if _is_auth_error(error_msg, exception_name):
            _LOGGER.warning("Authentication failed: %s", error_msg)
            return {"base": "auth"}

        return {"base": "unknown"}

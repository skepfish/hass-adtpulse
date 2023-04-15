"""ADT Pulse for Home Assistant.

See https://github.com/rsnodgrass/hass-adtpulse
"""
from __future__ import annotations

from typing import Optional, Any, Mapping
from aiohttp.client_exceptions import ClientConnectionError
from asyncio import gather
from homeassistant.config_entries import ConfigEntry, SOURCE_IMPORT
from homeassistant.const import (
    CONF_DEVICE_ID,
    CONF_PASSWORD,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.check_config import ConfigType
from pyadtpulse import PyADTPulse

from .config_flow import validate_input, CannotConnect, InvalidAuth
from .const import ADTPULSE_DOMAIN, LOG, CONF_FINGERPRINT, CONF_HOSTNAME
from .coordinator import ADTPulseDataUpdateCoordinator

NOTIFICATION_TITLE = "ADT Pulse"
NOTIFICATION_ID = "adtpulse_notification"

SUPPORTED_PLATFORMS = ["alarm_control_panel", "binary_sensor"]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Start up the ADT Pulse HA integration.

    Args:
        hass (HomeAssistant): Home Assistant Object
        config (ConfigType): Configuration type

    Returns:
        bool: True if successful
    """
    hass.data.setdefault(ADTPULSE_DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Initialize the ADTPulse integration."""
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    fingerprint = entry.data[CONF_FINGERPRINT]
    # share reference to the service with other components/platforms
    # running within HASS

    host = entry.data[CONF_HOSTNAME]
    if host:
        LOG.debug(f"Using ADT Pulse API host {host}")
    service = PyADTPulse(
        username,
        password,
        fingerprint,
        service_host=host,
        websession=async_create_clientsession(hass),
        do_login=False,
    )

    hass.data[ADTPULSE_DOMAIN][entry.entry_id] = service
    try:
        if not await service.async_login():
            LOG.error(f"{ADTPULSE_DOMAIN} could not log in as user {username}")
            raise ConfigEntryAuthFailed(
                f"{ADTPULSE_DOMAIN} could not login using supplied credentials"
            )
    except ClientConnectionError as ex:
        LOG.error(f"Unable to connect to ADT Pulse: {str(ex)}")
        hass.components.persistent_notification.create(
            f"Error: {ex}<br />You will need to restart Home Assistant after fixing.",
            title=NOTIFICATION_TITLE,
            notification_id=NOTIFICATION_ID,
        )
        raise ConfigEntryNotReady(
            f"{ADTPULSE_DOMAIN} could not log in due to a protocol error"
        )

    if service.sites is None:
        LOG.error(f"{ADTPULSE_DOMAIN} could not retrieve any sites")
        raise ConfigEntryNotReady(f"{ADTPULSE_DOMAIN} could not retrieve any sites")

    coordinator = ADTPulseDataUpdateCoordinator(hass, service)
    hass.data.setdefault(ADTPULSE_DOMAIN, {})
    hass.data[ADTPULSE_DOMAIN][entry.entry_id] = coordinator
    for platform in SUPPORTED_PLATFORMS:
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, platform)
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    # This is called when an entry/configured device is to be removed. The class
    # needs to unload itself, and remove callbacks. See the classes for further
    # details
    unload_ok = all(
        await gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, component)
                for component in SUPPORTED_PLATFORMS
            ]
        )
    )

    if unload_ok:
        pulse: PyADTPulse = hass.data[ADTPULSE_DOMAIN][entry.entry_id].adtpulse
        await pulse.async_logout()
        hass.data[ADTPULSE_DOMAIN].pop(entry.entry_id)

    return unload_ok

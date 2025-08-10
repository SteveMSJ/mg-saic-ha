# File: __init__.py

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .api import SAICMGAPIClient
from .coordinator import SAICMGDataUpdateCoordinator
from .message_handler import SAICMGMessageHandler
from .const import DOMAIN, LOGGER, PLATFORMS, UPDATE_INTERVAL_MESSAGES
from .services import async_setup_services, async_unload_services
from datetime import timedelta
from homeassistant.helpers.event import async_track_time_interval


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up MG SAIC from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    username = entry.data["username"]
    password = entry.data["password"]
    vin = entry.data.get("vin")
    region = entry.data.get("region")
    username_is_email = entry.data.get("country_code") is None

    client = SAICMGAPIClient(
        username,
        password,
        vin,
        username_is_email,
        region,
        entry.data.get("country_code"),
    )

    try:
        await client.login()

        # Fetch vehicle info to get the VIN
        if not vin:
            LOGGER.error("No VIN specified in Config Entry")
            return False

        # Verify the VIN belongs to the account
        vehicles = await client.get_vehicle_info()
        if not any(v.vin == vin for v in vehicles):
            LOGGER.error("VIN %s not found in account vehicles", vin)
            return False

        hass.data[DOMAIN][entry.entry_id] = client

        # Setup vehicle coordinator
        coordinator = SAICMGDataUpdateCoordinator(hass, client, entry)
        await coordinator.async_setup()

        hass.data[DOMAIN][f"{entry.entry_id}_coordinator"] = coordinator

        # Store coordinator by VIN for data refresh after service calls
        hass.data[DOMAIN].setdefault("coordinators_by_vin", {})
        hass.data[DOMAIN]["coordinators_by_vin"][vin] = coordinator

        # Register an update listener to handle options updates
        entry.async_on_unload(entry.add_update_listener(update_listener))

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        # Register Services
        await async_setup_services(hass, client, coordinator)

        LOGGER.info("MG SAIC integration setup completed successfully.")

        # Setup message handler if one not already setup
        if not (hass.data[DOMAIN].get("message_handler", None)):
            message_handler = SAICMGMessageHandler(hass, client)

            async def _check_messages(_now):
                await message_handler.check_for_new_messages()

            # Setup track_time_interval to regularly check for new vehicle start messages
            message_handler_cancel = async_track_time_interval(
                hass, _check_messages, UPDATE_INTERVAL_MESSAGES
            )
            LOGGER.info("MG SAIC Vehicle Start Message Handler created.")
            # Mark that a handler has been set up as only one is required per account
            # Don't want multiple handlers set up if more than one vehicle registered
            hass.data[DOMAIN].setdefault("message_handler", message_handler_cancel)

        return True
    except Exception as e:
        LOGGER.error("Failed to set up MG SAIC integration: %s", e)
        return False


async def update_listener(hass: HomeAssistant, entry: ConfigEntry):
    """Handle options update."""
    coordinator = hass.data[DOMAIN][f"{entry.entry_id}_coordinator"]
    await coordinator.async_update_options(entry.options)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

        # If there are no more entries, unload services
        if not hass.data[DOMAIN]:
            await async_unload_services(hass)

    return unload_ok

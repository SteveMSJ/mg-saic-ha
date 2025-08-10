from datetime import datetime
from .api import SAICMGAPIClient
from saic_ismart_client_ng.api.message.schema import MessageEntity

from .const import (
    DOMAIN,
    LOGGER,
)


class SAICMGMessageHandler:
    """Class to manage fetching messages from the MG SAIC API."""

    def __init__(
        self,
        hass,
        client: SAICMGAPIClient,
    ) -> None:
        self.hass = hass
        self.client = client
        self.last_message_ts = datetime.min
        self.last_message_id: str | int | None = None
        self.first_call = True

    async def check_for_new_messages(self):
        """Fetch new Vehicale Start messages from the API."""
        try:
            LOGGER.info("check_for_new_messages called")

            all_messages = await self.get_all_alarm_messages()

            new_messages = [m for m in all_messages if m.read_status != "read"]

            for message in new_messages:
                LOGGER.info(message.details)
                await self.read_message(message)

            latest_message = self.__get_latest_message(all_messages)
            if (
                latest_message is not None
                and latest_message.messageId != self.last_message_id
                and latest_message.message_time > self.last_message_ts
            ):
                self.last_message_id = latest_message.messageId
                self.last_message_ts = latest_message.message_time
                if not self.first_call:
                    LOGGER.info(
                        f"{latest_message.title} detected at {latest_message.message_time}"
                    )
                    coordinators_by_vin = self.hass.data[DOMAIN].get(
                        "coordinators_by_vin", {}
                    )
                    coordinator = coordinators_by_vin.get(latest_message.vin)
                    if coordinator:
                        try:
                            await coordinator.async_request_refresh()
                            LOGGER.info(
                                "Data update triggered for VIN: %s", latest_message.vin
                            )
                        except Exception as e:
                            LOGGER.error(
                                "Error triggering data update for VIN %s: %s",
                                latest_message.vin,
                                e,
                            )
                    else:
                        LOGGER.error("No coordinator found!")

            # Delete vehicle start messages unless they are the latest
            vehicle_start_messages = [
                m
                for m in all_messages
                if m.messageType == "323" and m.messageId != self.last_message_id
            ]
            for vehicle_start_message in vehicle_start_messages:
                await self.__delete_message(vehicle_start_message)

            self.first_call = False

        except Exception as e:
            LOGGER.error("Error retrieving message list: %s", e)

    async def get_all_alarm_messages(self) -> list[MessageEntity]:
        """Retrieve alarm message list."""
        idx = 1
        all_messages = []
        while True:
            try:
                message_list = await self.client.get_alarm_list(
                    page_num=idx, page_size=1
                )
                if (
                    message_list is not None
                    and message_list.messages
                    and len(message_list.messages) > 0
                ):
                    all_messages.extend(message_list.messages)
                else:
                    LOGGER.debug("Message Limit reached idx: %i", idx)
                    return all_messages
                oldest_message = self.__get_oldest_message(all_messages)
                if (
                    oldest_message is not None
                    and oldest_message.message_time < self.last_message_ts
                ):
                    LOGGER.debug("Oldest Message reached idx: %i", idx)
                    return all_messages
            except Exception as e:
                LOGGER.error("Error retrieving message list: %s", e)
                return None
            finally:
                idx = idx + 1

    async def read_message(self, message: MessageEntity) -> None:
        """Mark message as read."""
        try:
            message_id = message.messageId
            if message_id is not None:
                await self.client.read_message(message_id)
                LOGGER.info(
                    f"{message.title} message with ID {message_id} marked as read"
                )
            else:
                LOGGER.warning(
                    "Could not mark message '%s' as read as it has not ID", message
                )
        except Exception as e:
            LOGGER.exception("Could not mark message as read from server", exc_info=e)

    async def __delete_message(self, message: MessageEntity) -> None:
        """Delete message."""
        try:
            message_id = message.messageId
            if message_id is not None:
                await self.client.delete_message(message_id)
                LOGGER.info(f"{message.title} message with ID {message_id} deleted")
            else:
                LOGGER.warning("Could not delete message '%s' as it has no ID", message)
        except Exception as e:
            LOGGER.exception("Could not delete message from server", exc_info=e)

    @staticmethod
    def __get_latest_message(
        vehicle_start_messages: list[MessageEntity],
    ) -> MessageEntity | None:
        if len(vehicle_start_messages) == 0:
            return None
        return max(vehicle_start_messages, key=lambda m: m.message_time)

    @staticmethod
    def __get_oldest_message(
        vehicle_start_messages: list[MessageEntity],
    ) -> MessageEntity | None:
        if len(vehicle_start_messages) == 0:
            return None
        return min(vehicle_start_messages, key=lambda m: m.message_time)

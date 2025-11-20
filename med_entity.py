from __future__ import annotations
from typing import Any
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.core import callback
from .const import DOMAIN


class MedStoreMedicationEntity(SensorEntity):
    """One entity per medication — index based entity id + attributes come from med data."""

    def __init__(self, medstore, index: int):
        self._medstore = medstore
        self._index = index
        self._attr_name = f"Medstore med {index}"
        self._attr_unique_id = f"{DOMAIN}_med_{index}"

    async def async_added_to_hass(self) -> None:
        """Register for updates from MedStore (dispatcher)."""
        self.async_on_remove(
            async_dispatcher_connect(self.hass, "medstore_update", self._update_callback)
        )

    @callback
    def _update_callback(self) -> None:
        # If med was removed, ensure state becomes unavailable
        meds = self._medstore.data.get("meds", [])
        if self._index >= len(meds):
            # state becomes None/unavailable
            self.async_write_ha_state()
            return
        # Update state/attributes
        self.async_write_ha_state()

    @property
    def should_poll(self) -> bool:
        return False

    @property
    @property
    def native_value(self) -> Any:
        """Return True if this index has a medication, False otherwise."""
        meds = self._medstore.data.get("meds", [])
        return self._index < len(meds)


    @property
    def extra_state_attributes(self):
        """Return med data as attributes (safe copy)."""
        meds = self._medstore.data.get("meds", [])
        if self._index >= len(meds):
            return {}
        # Expose all med fields as attributes
        return {"index": self._index, **meds[self._index]}


class MedStoreDataSensor(SensorEntity):
    """Master sensor exposing entire data blob for templating."""

    def __init__(self, medstore):
        self._medstore = medstore
        self._attr_name = "Medstore Data"
        self._attr_unique_id = f"{DOMAIN}_master"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, "medstore_update", self._update_callback)
        )

    @callback
    def _update_callback(self) -> None:
        self.async_write_ha_state()

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def native_value(self) -> str:
        # Changing this to number of meds. Is it wrong?
        return len(self._medstore.data.get("meds", []))

    @property
    def extra_state_attributes(self):
        # Expose the full stored dict under attributes
        return self._medstore.data

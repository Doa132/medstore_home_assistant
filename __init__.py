import logging
from datetime import datetime, timedelta
from typing import Any
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.storage import Store
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_change
from .const import DOMAIN, STORAGE_KEY, STORAGE_VERSION
from .sensor import async_setup_platform

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict):
    """
    YAML-only setup for MedStore.
    - Loads saved data
    - Registers services
    - Sets up sensors (per-med + master) by calling async_setup_platform
    """
    medstore = MedStore(hass)
    hass.data[DOMAIN] = medstore

    await medstore.async_load()

    # Register services
    hass.services.async_register(DOMAIN, "add", medstore.add)
    hass.services.async_register(DOMAIN, "delete", medstore.delete)
    hass.services.async_register(DOMAIN, "update", medstore.update)
    hass.services.async_register(DOMAIN, "toggle_active", medstore.toggle_active)
    hass.services.async_register(DOMAIN, "add_refill", medstore.add_refill)
    hass.services.async_register(DOMAIN, "take_dose", medstore.take_dose)

    # Setup sensors via platform function (we pass an add_entities callback internally)
    # Note: in most HA environments this pattern is acceptable for YAML-only integrations.
    async def _add_entities_callback(entities):
        # platform.async_add_entities is normally provided by HA. We get the current platform and add.
        platform = hass.helpers.entity_platform.async_get_current_platform()
        platform.async_add_entities(entities)

    await async_setup_platform(hass, config, _add_entities_callback)

    # Schedule midnight reset (local time)
    async_track_time_change(
        hass, medstore.async_midnight_reset, hour=0, minute=0, second=0
    )

    _LOGGER.info("MedStore loaded (YAML-only)")
    return True


class MedStore:
    """Main class that holds meds data and service handlers."""

    def __init__(self, hass: HomeAssistant):
        self.hass = hass
        self.store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        # Meds is a list of dicts with fields like: name, strength, dose, doses_per_day, timing (list), doses_available, refills_available, doses_per_refill, taken_count_per_dose, all_taken, active
        self.data: dict[str, Any] = {"meds": []}

        # Entities mapping for sync/removal: index -> entity
        self._med_entities: dict[int, object] = {}
        self._master_entity = None

    # -------------------------
    # Persistence
    # -------------------------
    async def async_load(self):
        loaded = await self.store.async_load()
        if loaded:
            self.data = loaded
            _LOGGER.info("MedStore loaded from storage with %d meds", len(self.data.get("meds", [])))
        else:
            _LOGGER.info("MedStore storage empty; starting fresh")

    async def async_save(self):
        await self.store.async_save(self.data)

    # -------------------------
    # Entity sync (deletion + reindex)
    # -------------------------
    async def _sync_med_entities(self):
        """Remove entities for deleted meds, reindex existing entities to keep indices consistent."""
        current_indices = set(range(len(self.data.get("meds", []))))
        existing_indices = set(self._med_entities.keys())

        # Entities to remove
        removed = existing_indices - current_indices
        for idx in sorted(removed, reverse=True):
            entity = self._med_entities.pop(idx, None)
            if entity is not None:
                try:
                    # If entity has async_remove, call it
                    remove_coro = getattr(entity, "async_remove", None)
                    if remove_coro:
                        await remove_coro()
                except Exception as exc:
                    _LOGGER.exception("Error removing entity for index %s: %s", idx, exc)

        # Reindex remaining entities
        new_map = {}
        for new_index, old_index in enumerate(sorted(self._med_entities.keys())):
            entity = self._med_entities[old_index]
            # update entity index & unique id if present
            try:
                setattr(entity, "_index", new_index)
                unique = f"{DOMAIN}_med_{new_index}"
                setattr(entity, "_attr_unique_id", unique)
                # friendly name attribute remains index-based; attributes show med.name
                new_map[new_index] = entity
            except Exception:
                # If any entity doesn't support direct attribute edits, skip silently
                new_map[new_index] = entity

        self._med_entities = new_map

        # notify entities/clients
        async_dispatcher_send(self.hass, "medstore_update")

    # -------------------------
    # Services
    # -------------------------
    async def add(self, call: ServiceCall):
        """Add a new med. Expects 'med_data' dict in service call."""
        med_data = call.data.get("med_data") or {}
        # Normalize and set defaults
        name = med_data.get("name", f"Med {len(self.data['meds']) + 1}")
        timing = med_data.get("timing", [])
        med = {
            "name": name,
            "strength": med_data.get("strength", ""),
            "dose": int(med_data.get("dose", 1)),
            "doses_per_day": int(med_data.get("doses_per_day", len(timing) if timing else 1)),
            "timing": timing,
            "doses_available": int(med_data.get("doses_available", 0)),
            "refills_available": int(med_data.get("refills_available", 0)),
            "doses_per_refill": int(med_data.get("doses_per_refill", 0)),
            "next_refill": med_data.get("next_refill", ""),
            "taken_count_per_dose": med_data.get("taken_count_per_dose", [0] * (len(timing) or 1)),
            "all_taken": med_data.get("all_taken", False),
            "active": med_data.get("active", True),
        }

        self.data["meds"].append(med)
        await self._recalc_next_refill_for_entry(med)
        await self.async_save()
        async_dispatcher_send(self.hass, "medstore_update")

    async def delete(self, call: ServiceCall):
        index = call.data.get("index")
        if index is None:
            _LOGGER.warning("delete service called without index")
            return
        try:
            index = int(index)
        except (TypeError, ValueError):
            _LOGGER.warning("delete service invalid index: %s", index)
            return

        meds = self.data.get("meds", [])
        if index < 0 or index >= len(meds):
            _LOGGER.warning("delete service index out of range: %s", index)
            return

        meds.pop(index)
        await self.async_save()
        await self._sync_med_entities()

    async def update(self, call: ServiceCall):
        index = call.data.get("index")
        updates = call.data.get("updates") or {}
        if index is None:
            _LOGGER.warning("update service called without index")
            return
        try:
            index = int(index)
        except (TypeError, ValueError):
            _LOGGER.warning("update service invalid index: %s", index)
            return
        meds = self.data.get("meds", [])
        if 0 <= index < len(meds):
            meds[index].update(updates)
            await self._recalc_next_refill_for_entry(meds[index])
            await self.async_save()
            async_dispatcher_send(self.hass, "medstore_update")

    async def toggle_active(self, call: ServiceCall):
        index = call.data.get("index")
        if index is None:
            return
        try:
            index = int(index)
        except (TypeError, ValueError):
            return
        meds = self.data.get("meds", [])
        if 0 <= index < len(meds):
            meds[index]["active"] = not meds[index].get("active", True)
            await self.async_save()
            async_dispatcher_send(self.hass, "medstore_update")

    async def add_refill(self, call: ServiceCall):
        index = call.data.get("index")
        amount = call.data.get("amount", 0)
        if index is None:
            return
        try:
            index = int(index)
        except (TypeError, ValueError):
            return
        meds = self.data.get("meds", [])
        if 0 <= index < len(meds):
            meds[index]["doses_available"] = meds[index].get("doses_available", 0) + int(amount)
            # Decrease refills_available if applicable
            if meds[index].get("refills_available", 0) > 0:
                meds[index]["refills_available"] = max(0, meds[index].get("refills_available", 0) - 1)
            await self._recalc_next_refill_for_entry(meds[index])
            await self.async_save()
            async_dispatcher_send(self.hass, "medstore_update")

    async def take_dose(self, call: ServiceCall):
        index = call.data.get("index")
        dose_index = call.data.get("dose_index")
        if index is None or dose_index is None:
            _LOGGER.warning("take_dose requires index and dose_index")
            return
        try:
            index = int(index)
            dose_index = int(dose_index)
        except (TypeError, ValueError):
            _LOGGER.warning("take_dose invalid index/dose_index")
            return

        meds = self.data.get("meds", [])
        if 0 <= index < len(meds):
            med = meds[index]
            timing = med.get("timing", [])
            taken = med.get("taken_count_per_dose", [0] * len(timing))

            if 0 <= dose_index < len(timing):
                # Ensure taken list is the correct length
                if len(taken) < len(timing):
                    taken = taken + [0] * (len(timing) - len(taken))
                    med["taken_count_per_dose"] = taken

                # Only increment if not yet counted
                taken[dose_index] = min(99999, taken[dose_index] + 1)
                med["doses_available"] = max(0, med.get("doses_available", 0) - med.get("dose", 1))
                med["all_taken"] = all(c >= 1 for c in med["taken_count_per_dose"])

                await self._recalc_next_refill_for_entry(med)
                await self.async_save()
                async_dispatcher_send(self.hass, "medstore_update")

    # -------------------------
    # Refill calc helper
    # -------------------------
    async def _recalc_next_refill_for_entry(self, med: dict):
        doses_available = int(med.get("doses_available", 0))
        dose_per_time = int(med.get("dose", 1))
        daily_need = int(med.get("doses_per_day", 1)) * dose_per_time
        days_left = doses_available // daily_need if daily_need > 0 else 0
        med["next_refill"] = (datetime.now() + timedelta(days=days_left)).strftime("%Y-%m-%d")

    # -------------------------
    # Midnight reset
    # -------------------------
    async def async_midnight_reset(self, *args):
        changed = False
        for med in self.data.get("meds", []):
            if med.get("active", True) and med.get("doses_per_day", 0) > 0:
                timing = med.get("timing", [])
                med["taken_count_per_dose"] = [0] * len(timing)
                med["all_taken"] = False
                changed = True
        if changed:
            await self.async_save()
            async_dispatcher_send(self.hass, "medstore_update")

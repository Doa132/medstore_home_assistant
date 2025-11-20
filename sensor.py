# custom_components/medstore/sensor.py
# =======================================
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import DOMAIN
from .med_entity import MedStoreMedicationEntity, MedStoreDataSensor


async def async_setup_platform(hass: HomeAssistant, config, async_add_entities: AddEntitiesCallback, discovery_info=None):
    """YAML-only platform setup: create per-med entities and master entity."""
    if DOMAIN not in hass.data:
        return

    medstore = hass.data[DOMAIN]
    meds = medstore.data.get("meds", [])

    entities = []

    # create per-med entities by index and register them in medstore._med_entities
    for i in range(len(meds)):
        entity = MedStoreMedicationEntity(medstore, i)
        entities.append(entity)
        # store reference for sync/delete purposes
        medstore._med_entities[i] = entity

    # Add master data sensor
    master = MedStoreDataSensor(medstore)
    entities.append(master)
    medstore._master_entity = master

    async_add_entities(entities)


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback):
    """Support config entry path as well (behaves same as YAML mode)."""
    await async_setup_platform(hass, None, async_add_entities)

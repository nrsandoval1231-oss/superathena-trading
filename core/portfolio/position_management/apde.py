"""Trading-specific APDE state contract."""
from enum import StrEnum

class APDEState(StrEnum):
    EXPLORE = "EXPLORE"
    PROTECT = "PROTECT"
    HARVEST = "HARVEST"
    DEFEND = "DEFEND"
    EXIT = "EXIT"

ORDER = (APDEState.EXPLORE, APDEState.PROTECT, APDEState.HARVEST, APDEState.DEFEND, APDEState.EXIT)

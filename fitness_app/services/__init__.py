"""Domain services that sit between the importers, the routes and the database.

Each module here holds the logic for one area of the domain, kept out of both
the HTTP routes and the importer classes so it can be reused and tested
independently. Importers stay focused on parsing and storing; routes stay
focused on HTTP.

Modules:
    measurements: Body measurement conflict detection and resolution. This is
        where the "two sources disagree about the same day" problem lives, along
        with the rules for deciding which reading counts as current.
"""

from .measurements import (
    CONFLICT_TYPES,
    Conflict,
    Reading,
    clear_superseded,
    current_measurement,
    current_values,
    find_conflicts,
    resolve_conflict,
    series,
    supersede_mismatches_within_day,
)

__all__ = [
    "CONFLICT_TYPES",
    "Conflict",
    "Reading",
    "clear_superseded",
    "current_measurement",
    "current_values",
    "find_conflicts",
    "resolve_conflict",
    "series",
    "supersede_mismatches_within_day",
]
"""Abstract base class for data source importers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ImportResult:
    """Result of an import operation.

    Attributes:
        errors: Things that went wrong. A non-empty list means the import did
            not fully succeed.
        notes: Informational messages that are *not* failures - a data file the
            importer deliberately ignored, for example. These must not be shown
            as errors, otherwise routine runs always look broken.
        conflicts: Messages about imported data that contradicts another source
            for the same day. These are warnings, not errors: every reading is
            stored, and the user decides which to believe. See
            ``services/measurements.py``.
        label: How to describe this source to a human, e.g. ``"Wii Fit"``.
            Set by the runner rather than the importer, because two importers
            can legitimately share one ``source`` key (the live mywellness API
            and the manual JSON export both report ``"technogym"``) and their
            messages still need to be distinguishable.
    """
    source: str
    records_found: int = 0
    records_created: int = 0
    records_skipped: int = 0
    records_updated: int = 0
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    label: str = ""

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


class BaseImporter(ABC):
    """Abstract base class for all data source importers."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Human-readable source name."""
        pass

    @abstractmethod
    def import_data(self, **kwargs) -> ImportResult:
        """Import data from the source. Returns an ImportResult."""
        pass

    @abstractmethod
    def check_already_imported(self, source_id: str, record_type: str) -> bool:
        """Check if a record has already been imported."""
        pass

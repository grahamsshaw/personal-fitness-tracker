"""Wii Fit Plus save data importer.

Parses decrypted Wii Fit Plus .dat files (FitPlus0.dat, FitPlus1.dat, FitPlus2.dat)
and extracts weight, BMI, and balance measurements.

File format (verified against real save files from an NVIDIA Shield Pro;
see debug/debug_wii_verify.py):

- The file begins with the 8-byte signature "RPHE0000".
- It is then a fixed sequence of Mii/profile records, each exactly 0x9281
  bytes long. Only the FIRST record carries the "RPHE" signature - later
  records do not, so the file must be walked by record length rather than by
  looking for a header on every record.
- Profile record layout:
    +0x00  8 bytes   file signature (first record only)
    +0x08  22 bytes  Mii name, UTF-16BE, may be blank for unused slots
    +0x1E  2 bytes  height in cm, big-endian
    +0x38A1 Body Test entries, 21 bytes each:
             +0  4 bytes  packed date (see _parse_date)
             +4  2 bytes  weight, big-endian, kg x 10
             +6  2 bytes  BMI, big-endian, x 100
             +8  2 bytes  balance, big-endian, percent x 10
           Entries run until one has a year of zero.

Two things that are easy to get wrong, and were:

1. The packed date uses ``year = (value >> 20) & 0x7FF`` - bits 20-30, *not*
   bits 21-31. Getting that wrong yields a year in the 1000s, every date
   raises ValueError, and the entry loop stops immediately, so the file looks
   as though it holds no measurements at all.
2. Unused profile slots have a blank Mii name. Real save files can hold data
   in a later slot than the first, so every slot must be visited instead of
   stopping at the first blank name.
"""

import os
import struct
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from .base import BaseImporter, ImportResult
from ..models import db, BodyMeasurement, ImportLog, Person
from ..services.measurements import (
    describe_conflict,
    supersede_mismatches_within_day,
)


# Record length for Wii Fit Plus profiles
RECORD_LENGTH = 0x9281

# Offset to body test data within each profile record
BODY_TEST_OFFSET = 0x38A1

# Size of each body test data row
ROW_LENGTH = 21

# Safety bound on how many body test entries to read from a single profile.
# Real save files hold a few dozen; this only stops a corrupt table from
# producing an unbounded list.
MAX_BODY_TEST_ENTRIES = 256


@dataclass
class BodyTestRecord:
    """A single body test measurement from Wii Fit."""
    measured_at: datetime
    weight_kg: float
    bmi: float
    balance_percent: float
    mii_name: str
    height_cm: int | None = None


class NotAProfileFileError(ValueError):
    """Raised when a .dat file is a valid Wii Fit save file but not a profile file.

    A Wii Fit Plus save is split across three files. FitPlus0.dat and
    FitPlus1.dat hold the Mii/profile block and start with the "RPHE"
    signature; FitPlus2.dat starts with "RFP" and holds a different kind of
    data that has no body tests in it.

    That is a normal, expected outcome rather than a failure, so it gets its
    own exception type and is reported as an informational note. Genuinely
    unrecognised files still raise plain ``ValueError`` and are reported as
    errors.
    """


class WiiFitImporter(BaseImporter):
    """Importer for Wii Fit Plus save data files."""

    @property
    def source_name(self) -> str:
        return "wii_fit"

    #: Where the save files live when nothing else is configured.
    #: This is the Dolphin/Wii Fit Plus folder on the NVIDIA Shield Pro,
    #: reachable from the dev PC over SMB.
    DEFAULT_NETWORK_PATH = (
        r"\\192.168.0.57\internal\Android\data\org.dolphinemu.dolphinemu"
        r"\files\Wii\title\00010004\52465050\data"
    )

    def __init__(self, data_dir: str | None = None):
        """Initialize the importer and work out which folder to read.

        Resolution order (first match wins):

        1. ``data_dir`` argument, if given (used by the upload/import routes).
        2. ``WII_FIT_SOURCE_PATH`` environment variable (set in ``.env``).
           This is how the Raspberry Pi build is pointed at a mounted copy of
           the Shield's save folder.
        3. The hard-coded SMB path to the NVIDIA Shield Pro.
        4. Local fallback: ``<project>/data/wii_fit``.

        A path that does not exist is *not* an error - it falls through to the
        next candidate, and ``is_available()`` reports what was actually found.

        Args:
            data_dir: Explicit override for the save-file folder.
        """
        self.requested_path: Path | None = None

        if data_dir is not None:
            self.data_dir = Path(data_dir)
            self.requested_path = self.data_dir
            return

        candidates = [
            os.environ.get("WII_FIT_SOURCE_PATH", "").strip(),
            self.DEFAULT_NETWORK_PATH,
            # Local fallback: files copied into the project by hand
            str(
                Path(__file__).resolve().parents[2] / "data" / "wii_fit"
            ),
        ]

        for candidate in candidates:
            if not candidate:
                continue
            path = Path(candidate)
            if path.is_dir():
                self.data_dir = path
                return

        # Nothing exists yet - keep the first real candidate so the error
        # message points somewhere sensible.
        self.data_dir = Path(
            candidates[0] or candidates[1] or candidates[2]
        )

    def is_available(self) -> bool:
        """Return True when the configured folder exists on this machine."""
        return self.data_dir.is_dir()

    def _parse_date(self, packed_date: int) -> datetime | None:
        """Parse the packed Body Test date bitfield.

        Layout (32 bits, big-endian), matching
        ``Resources_Archive/wiifit-master/wiifit.py``:

        - year:   bits 20-30 (11 bits)
        - month:  bits 16-19 (4 bits, 0-based, so add 1)
        - day:    bits 11-15 (5 bits)
        - hour:   bits  6-10 (5 bits)
        - minute: bits  0-5  (6 bits)

        The year starting at bit 20 rather than bit 21 is the crucial detail.
        Shifting by 21 yields a year around 1000, every date then raises
        ValueError, and the entry loop stops on the first row - which makes the
        whole file look as though it contains no measurements.

        Args:
            packed_date: The raw 32-bit value.

        Returns:
            A datetime, or None when the field is blank or out of range.
        """
        year = (packed_date >> 20) & 0x7FF
        month = ((packed_date >> 16) & 0xF) + 1
        day = (packed_date >> 11) & 0x1F
        hour = (packed_date >> 6) & 0x1F
        minute = packed_date & 0x3F

        # A year of zero marks the end of the populated entries.
        if year == 0:
            return None

        try:
            return datetime(year, month, day, hour, minute)
        except ValueError:
            return None

    def _parse_mii_name(self, data: bytes) -> str:
        """Parse Mii name from UTF-16BE bytes."""
        try:
            name = data.decode("utf-16-be").replace("\0", "").strip()
            return name
        except (UnicodeDecodeError, ValueError):
            return ""

    def _parse_profile(self, fh: BinaryIO, record_start: int) -> list[BodyTestRecord]:
        """Parse a single Mii profile record.

        The Mii name is allowed to be blank: unused profile slots have no name,
        and stopping at the first blank slot would skip real data stored in a
        later slot. An unused slot simply has a year of zero in its first Body
        Test entry, so the entry loop stops by itself.

        Args:
            fh: Open binary file handle, positioned anywhere.
            record_start: Byte offset of this profile record.

        Returns:
            List of Body Test records found in this profile (may be empty).
        """
        # Read the header area: 8 signature + 22 name + height at +0x1E
        fh.seek(record_start)
        header = fh.read(0x20)
        if len(header) < 0x20:
            return []

        mii_name = self._parse_mii_name(header[8:0x1E])
        height_cm = struct.unpack_from(">H", header, 0x1E)[0] or None

        # Read body test entries until one is blank
        fh.seek(record_start + BODY_TEST_OFFSET)
        records: list[BodyTestRecord] = []

        # Bound the loop so a corrupt table cannot spin forever.
        for _ in range(MAX_BODY_TEST_ENTRIES):
            row = fh.read(ROW_LENGTH)
            if len(row) < 10:
                break

            packed_date, weight_raw, bmi_raw, balance_raw = struct.unpack(
                ">i3H", row[0:10]
            )

            measured_at = self._parse_date(packed_date)
            if measured_at is None:
                break

            records.append(
                BodyTestRecord(
                    measured_at=measured_at,
                    weight_kg=weight_raw / 10.0,
                    bmi=bmi_raw / 100.0,
                    balance_percent=balance_raw / 10.0,
                    mii_name=mii_name,
                    height_cm=height_cm,
                )
            )

        return records

    def parse_file(self, filepath: str | Path) -> list[BodyTestRecord]:
        """Parse a Wii Fit Plus .dat file and return all body test records.

        Walks the file in fixed 0x9281-byte profile records. Only the first
        record carries the "RPHE" signature, so the signature is checked once
        at the start of the file rather than per record.

        Args:
            filepath: Path to a FitPlus*.dat file.

        Returns:
            Every Body Test record found, in file order.

        Raises:
            NotAProfileFileError: If this is a Wii Fit save file that does not
                hold Mii profiles (for example FitPlus2.dat).
            ValueError: If the file is not a recognised Wii Fit save at all.
        """
        records: list[BodyTestRecord] = []
        file_size = Path(filepath).stat().st_size

        with open(filepath, "rb") as fh:
            # Check file header. The Wii Fit Plus save uses two signatures:
            # "RPHE" for the profile block and "RFP" for the other data block.
            header = fh.read(8)
            if header[:4] != b"RPHE":
                if header[:3] == b"RFP":
                    raise NotAProfileFileError(
                        f"{Path(filepath).name} holds Wii Fit's non-profile data "
                        f"block and contains no body tests."
                    )
                raise ValueError(f"Invalid Wii Fit file header: {header[:4]}")

            # Every 0x9281-byte slot is a profile, used or not.
            profile_count = file_size // RECORD_LENGTH + 1
            for index in range(profile_count):
                record_start = index * RECORD_LENGTH
                if record_start + BODY_TEST_OFFSET >= file_size:
                    break
                records.extend(self._parse_profile(fh, record_start))

        return records

    def check_already_imported(self, source_id: str, record_type: str) -> bool:
        """Check if a record has already been imported."""
        return ImportLog.query.filter_by(
            source=self.source_name,
            source_id=source_id,
            record_type=record_type,
        ).first() is not None

    def find_save_files(self) -> list[str]:
        """Return the Wii Fit save files present in the resolved source folder.

        Kept on the importer so that everything which needs to know "are there
        any save files, and what are they called" uses the same rule, rather than
        each caller re-implementing the ``FitPlus*.dat`` pattern.

        Returns:
            Sorted file names. Empty when the folder is missing or holds none.
        """
        if not self.data_dir.is_dir():
            return []

        try:
            return sorted(
                entry.name
                for entry in self.data_dir.iterdir()
                if entry.is_file()
                and entry.name.startswith("FitPlus")
                and entry.suffix == ".dat"
            )
        except OSError:
            # Unreachable network share, or permissions problem. Treated as "no
            # files" so callers report something actionable rather than crashing.
            return []

    def import_data(self, file_path: str | Path | None = None, **kwargs) -> ImportResult:
        """Import Wii Fit data into the database.

        Args:
            file_path: Path to a specific .dat file. If None, imports all FitPlus*.dat files.
        """
        result = ImportResult(source=self.source_name)

        # Get or create person
        person = Person.query.first()
        if not person:
            person = Person(first_name="Graham", last_name="Shaw")
            db.session.add(person)
            db.session.flush()

        files_to_import = []
        if file_path:
            files_to_import = [Path(file_path)]
        else:
            files_to_import = sorted(self.data_dir.glob("FitPlus*.dat"))

        if not files_to_import:
            result.errors.append(f"No Wii Fit .dat files found in {self.data_dir}")
            return result

        # Wii Fit keeps two copies of the profile block: FitPlus0.dat and
        # FitPlus1.dat normally hold identical Body Test entries, and FitPlus2.dat
        # holds unrelated data. The database unique constraint stops the second
        # copy being stored twice, but tracking what this run has already handled
        # keeps the counts honest and avoids raising the error in the first place.
        handled_source_ids: set[str] = set()

        for filepath in files_to_import:
            # Each file gets its own SAVEPOINT rather than a blanket rollback.
            # A blanket rollback would also throw away rows that earlier files
            # in this same run had already inserted but not yet committed - so a
            # failure in the last file would silently discard the good data from
            # the first. A savepoint rolls back only this file's work.
            savepoint = db.session.begin_nested()
            try:
                records = self.parse_file(filepath)
                result.records_found += len(records)

                for record in records:
                    # Create unique source ID for deduplication
                    source_id = f"{record.mii_name}_{record.measured_at.isoformat()}"

                    # Each Body Test entry produces one weight row and one BMI row,
                    # each with its own suffixed source ID. The weight row's ID is
                    # used as the de-duplication key because it is always written
                    # alongside the BMI row.
                    weight_source_id = f"{source_id}_weight"

                    # Already imported in a previous run, or earlier in this one?
                    if (weight_source_id in handled_source_ids
                            or self.check_already_imported(
                                weight_source_id, "body_measurement"
                            )):
                        handled_source_ids.add(weight_source_id)
                        result.records_skipped += 2  # weight + BMI already stored
                        continue

                    # Import weight measurement
                    weight = BodyMeasurement(
                        person_id=person.id,
                        measured_at=record.measured_at,
                        measurement_type="weight",
                        value=record.weight_kg,
                        unit="kg",
                        source=self.source_name,
                        source_id=weight_source_id,
                    )
                    db.session.add(weight)
                    db.session.flush()

                    # Log import
                    log = ImportLog(
                        source=self.source_name,
                        source_id=weight_source_id,
                        record_type="body_measurement",
                        record_id=weight.id,
                        action="created",
                    )
                    db.session.add(log)

                    # Import BMI measurement
                    bmi = BodyMeasurement(
                        person_id=person.id,
                        measured_at=record.measured_at,
                        measurement_type="bmi",
                        value=record.bmi,
                        unit="",
                        source=self.source_name,
                        source_id=f"{source_id}_bmi",
                    )
                    db.session.add(bmi)
                    db.session.flush()

                    log_bmi = ImportLog(
                        source=self.source_name,
                        source_id=f"{source_id}_bmi",
                        record_type="body_measurement",
                        record_id=bmi.id,
                        action="created",
                    )
                    db.session.add(log_bmi)

                    handled_source_ids.add(weight_source_id)

                    # Update person height if available
                    if record.height_cm and not person.height_cm:
                        person.height_cm = record.height_cm

                    result.records_created += 2  # weight + BMI

                    # Check whether this reading contradicts another source for
                    # the same day. This reports only - nothing is overwritten or
                    # hidden. The user settles any disagreement on the profile
                    # page, because neither source is reliably right.
                    for other_id in supersede_mismatches_within_day(weight):
                        result.conflicts.append(
                            describe_conflict(
                                weight,
                                db.session.get(BodyMeasurement, other_id),
                                new_label="Wii Fit",
                            )
                        )

                savepoint.commit()

            except NotAProfileFileError as note:
                # Expected: this file simply has no body tests. Not an error.
                savepoint.rollback()
                result.notes.append(str(note))

            except Exception as e:
                # Roll back only this file's work, then carry on with the rest.
                savepoint.rollback()
                result.errors.append(f"Error importing {filepath}: {str(e)}")

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            result.errors.append(f"Error saving imported data: {str(e)}")

        return result

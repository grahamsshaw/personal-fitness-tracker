"""Technogym / Mywellness live API importer.

Uses the new mywellness.com API:
- Login: POST https://core.mywellness.com/v2/enduser/authentication/login
- ActivityHistory: POST https://services.mywellness.com/Training/User/{user_id}/ActivityHistory
- Session details: POST https://services.mywellness.com/Training/User/{user_id}/GetPerformedWorkoutSessionByIdCr

Headers required:
- Content-Type: application/json
- X-MWAPPS-APPID: EC1D38D7-D359-48D0-A60C-D8C0B8FB9DF9
- X-MWAPPS-CLIENT: enduserweb
- Authorization: Bearer {token}
"""

import os
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from .base import BaseImporter, ImportResult
from ..models import db, Activity, Workout, WorkoutExercise, Exercise, Equipment, ImportLog, Person


# API endpoints
_LOGIN_URL = "https://core.mywellness.com/v2/enduser/authentication/login"
_SERVICES_URL = "https://services.mywellness.com"

# API headers
_API_HEADERS = {
    "Content-Type": "application/json",
    "X-MWAPPS-APPID": "EC1D38D7-D359-48D0-A60C-D8C0B8FB9DF9",
    "X-MWAPPS-CLIENT": "enduserweb",
}


@dataclass
class ExerciseData:
    """An exercise performed in a workout."""
    name: str
    machine: str
    duration: str = ""
    calories: str = ""
    moves: str = ""
    resistance_type: str = ""
    compliance: str = ""
    total_weight_kg: str = ""
    sets: list[dict] = field(default_factory=list)


@dataclass
class WorkoutSession:
    """A workout session from Technogym."""
    session_id: str
    id_cr: int
    date: str  # YYYYMMDD
    name: str
    total_moves: str
    duration: str = ""
    calories: str = ""
    exercises: list[ExerciseData] = field(default_factory=list)


class LoginError(Exception):
    """Raised when login fails."""
    pass


class TechnogymImporter(BaseImporter):
    """Importer for Technogym mywellness.com workout data using the live API."""

    @property
    def source_name(self) -> str:
        return "technogym"

    def __init__(self, email: str | None = None, password: str | None = None):
        """Initialize the importer.

        Args:
            email: mywellness.com email. If None, reads from environment.
            password: mywellness.com password. If None, reads from environment.
        """
        self._email = email or os.environ.get("MYWELLNESS_EMAIL")
        self._password = password or os.environ.get("MYWELLNESS_PASSWORD")
        self._http: httpx.Client | None = None
        self._user_id: str | None = None
        self._token: str | None = None

    def _get_client(self) -> httpx.Client:
        """Get or create HTTP client."""
        if self._http is None:
            self._http = httpx.Client(
                follow_redirects=True,
                timeout=30.0,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                },
            )
        return self._http

    def close(self):
        """Close HTTP client."""
        if self._http:
            self._http.close()
            self._http = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _get_auth_headers(self) -> dict[str, str]:
        """Get headers with authorization token."""
        return {**_API_HEADERS, "Authorization": f"Bearer {self._token}"}

    def login(self) -> str:
        """Authenticate and return user ID."""
        client = self._get_client()

        try:
            r = client.post(
                _LOGIN_URL,
                headers=_API_HEADERS,
                json={
                    "username": self._email,
                    "password": self._password,
                    "keepMeLoggedIn": True,
                },
            )
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise LoginError(f"Login request failed: {exc}") from exc

        data = r.json()
        user_context = data.get("userContext", {})
        user_id = user_context.get("id")
        token = data.get("token")

        if not user_id:
            raise LoginError("Login failed — no user ID in response")
        if not token:
            raise LoginError("Login failed — no token in response")

        self._user_id = user_id
        self._token = token
        return user_id

    def _refresh_token(self, data: dict) -> dict:
        """Refresh token from response if available."""
        new_token = data.get("token")
        if new_token:
            self._token = new_token
        return data

    def get_activity_history(self) -> list[dict]:
        """Get workout session history."""
        if not self._user_id or not self._token:
            raise LoginError("Not authenticated. Call login() first.")

        client = self._get_client()
        r = client.post(
            f"{_SERVICES_URL}/Training/User/{self._user_id}/ActivityHistory",
            headers=self._get_auth_headers(),
            json={},
        )
        r.raise_for_status()

        data = r.json()
        self._refresh_token(data)

        return data.get("data", {}).get("items", [])

    def get_session_details(self, id_cr: int, partition_date: int) -> dict:
        """Get full details for a workout session."""
        if not self._user_id or not self._token:
            raise LoginError("Not authenticated. Call login() first.")

        client = self._get_client()
        r = client.post(
            f"{_SERVICES_URL}/Training/User/{self._user_id}/GetPerformedWorkoutSessionByIdCr",
            headers=self._get_auth_headers(),
            json={"idCr": id_cr, "partitionDate": partition_date},
        )
        r.raise_for_status()

        data = r.json()
        self._refresh_token(data)

        return data.get("data", {})

    def check_already_imported(self, source_id: str, record_type: str) -> bool:
        """Check if a record has already been imported."""
        return ImportLog.query.filter_by(
            source=self.source_name,
            source_id=source_id,
            record_type=record_type,
        ).first() is not None

    def import_data(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
        **kwargs,
    ) -> ImportResult:
        """Import Technogym data into the database.

        Args:
            from_date: Start date. Defaults to 30 days ago.
            to_date: End date. Defaults to today.
        """
        result = ImportResult(source=self.source_name)

        if not from_date:
            from_date = date.today() - timedelta(days=30)
        if not to_date:
            to_date = date.today()

        # Get or create person
        person = Person.query.first()
        if not person:
            person = Person(first_name="Graham", last_name="Shaw")
            db.session.add(person)
            db.session.flush()

        try:
            self.login()
        except LoginError as e:
            result.errors.append(str(e))
            return result

        try:
            # Get activity history
            items = self.get_activity_history()
        except Exception as e:
            result.errors.append(f"Failed to fetch activity history: {e}")
            return result

        result.records_found = len(items)

        for item in items:
            # Parse date
            partition_date = item.get("partitionDate")
            if not partition_date:
                continue

            try:
                started_at = datetime.strptime(str(partition_date), "%Y%m%d")
            except ValueError:
                continue

            # Filter by date range
            if started_at.date() < from_date or started_at.date() > to_date:
                continue

            session_id = item.get("id")
            id_cr = item.get("idCr")

            if not session_id or not id_cr:
                continue

            # Check if already imported
            if self.check_already_imported(str(id_cr), "workout"):
                result.records_skipped += 1
                continue

            try:
                # Get full session details
                session_data = self.get_session_details(id_cr, partition_date)
            except Exception as e:
                result.errors.append(f"Failed to fetch session {id_cr}: {e}")
                continue

            # Create activity
            duration_str = session_data.get("displayDurationDone", "0")
            duration_minutes = self._parse_duration(duration_str)
            calories_str = session_data.get("displayCaloriesDoneShort", "0")
            calories = self._parse_calories(calories_str)
            moves_str = session_data.get("displayMoveDoneShort", "0")
            moves = self._parse_moves(moves_str)

            activity = Activity(
                person_id=person.id,
                activity_type="gym",
                started_at=started_at,
                duration_seconds=duration_minutes * 60 if duration_minutes else None,
                calories=calories,
                source=self.source_name,
                source_id=str(id_cr),
            )
            db.session.add(activity)
            db.session.flush()

            # Create workout
            workout = Workout(
                person_id=person.id,
                activity_id=activity.id,
                workout_name=session_data.get("displayName", "Workout"),
                started_at=started_at,
                duration_seconds=duration_minutes * 60 if duration_minutes else None,
                total_moves=moves,
                source=self.source_name,
                source_id=str(id_cr),
            )
            db.session.add(workout)
            db.session.flush()

            # Log import
            log = ImportLog(
                source=self.source_name,
                source_id=str(id_cr),
                record_type="workout",
                record_id=workout.id,
                action="created",
            )
            db.session.add(log)

            # Create exercises
            physical_activities = session_data.get("physicalActivities", [])
            for order, pa in enumerate(physical_activities):
                ex_data = pa.get("performedPhysicalActivity", {})
                ex_name = pa.get("physicalActivityName", "")
                machine = pa.get("equipmentName", "")

                if not ex_name:
                    continue

                # Get or create exercise
                exercise = Exercise.query.filter_by(name=ex_name).first()
                if not exercise:
                    exercise = Exercise(name=ex_name, category="strength")
                    db.session.add(exercise)
                    db.session.flush()

                # Get or create equipment
                equipment = None
                if machine:
                    equipment = Equipment.query.filter_by(name=machine).first()
                    if not equipment:
                        equipment = Equipment(
                            name=machine,
                            manufacturer="Technogym",
                            category="machine",
                        )
                        db.session.add(equipment)
                        db.session.flush()

                # Parse exercise metrics
                perf_data = {
                    d["physicalProperty"]: d.get("formattedValue", "")
                    for d in (ex_data.get("data") or {}).get("data", [])
                }

                duration = perf_data.get("Duration", "")
                calories = perf_data.get("Calories", "")
                moves = perf_data.get("Move", "")
                compliance = perf_data.get("ExerciseCompliance", "")
                total_weight = perf_data.get("TotalIsoWeight", "")

                we = WorkoutExercise(
                    workout_id=workout.id,
                    exercise_id=exercise.id,
                    equipment_id=equipment.id if equipment else None,
                    exercise_name=ex_name,
                    equipment_name=machine,
                    machine=machine,
                    resistance_type=perf_data.get("ExecutionMode", ""),
                    duration_seconds=self._parse_duration(duration) * 60 if self._parse_duration(duration) else None,
                    calories=self._parse_calories(calories),
                    moves=self._parse_moves(moves),
                    compliance=self._parse_float(compliance),
                    total_weight_kg=self._parse_float(total_weight),
                    exercise_order=order,
                    source=self.source_name,
                    source_id=f"{id_cr}_{order}",
                )
                db.session.add(we)

            result.records_created += 1

        db.session.commit()
        return result

    def _parse_duration(self, duration_str: str) -> int:
        """Parse duration string like '49 minutes' to minutes."""
        if not duration_str:
            return 0
        match = re.search(r"(\d+)", duration_str)
        return int(match.group(1)) if match else 0

    def _parse_calories(self, calories_str: str) -> float | None:
        """Parse calories string like '519 kcal' to float."""
        if not calories_str:
            return None
        match = re.search(r"(\d+)", calories_str)
        return float(match.group(1)) if match else None

    def _parse_moves(self, moves_str: str) -> int | None:
        """Parse moves string like '816 MOVEs' to int."""
        if not moves_str:
            return None
        match = re.search(r"(\d+)", moves_str)
        return int(match.group(1)) if match else None

    def _parse_float(self, value: str) -> float | None:
        """Parse a float value, return None if invalid."""
        if not value:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

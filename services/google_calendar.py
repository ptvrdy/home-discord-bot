"""Google Calendar integration via a service account.

No per-user OAuth flow lives in this bot - no browser consent screen, no
refresh tokens to store or rotate. Instead, the bot has its own Google
identity (the service account) and each calendar owner does a one-time
manual step: share their calendar with that identity's email address, the
same way you'd share a calendar with another person. The bot then reads and
writes using that one set of credentials for as long as access is granted.

Setup (see README's Google Calendar section for the full walkthrough):
1. Create a Google Cloud project and enable the Calendar API.
2. Create a service account, download its JSON key.
3. Share each calendar with the service account's email, with
   "Make changes to events" permission.
4. Point GOOGLE_SERVICE_ACCOUNT_FILE at the downloaded key and set
   PEYTON_CALENDAR_ID / PARTNER_CALENDAR_ID / FAMILY_CALENDAR_ID /
   DISCORD_CALENDAR_ID in .env.
"""

import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from google.oauth2 import service_account
from googleapiclient.discovery import build

from services.schedule import deduplicate_events, normalize_event


SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Label -> env var holding that calendar's ID. Personal is one household member's
# personal calendar; Partner is theirs (added once they set one up); Family
# is the shared household calendar; Discord is the separate calendar used to
# schedule gaming nights (Minecraft Mondays, BG3, movie nights) for the
# friends' Discord server - not household chores/tasks, but still useful to
# show alongside everything else on #this-week.
CALENDAR_ENV_VARS = {
    "Personal": "PERSONAL_CALENDAR_ID",
    "Partner": "PARTNER_CALENDAR_ID",
    "Family": "FAMILY_CALENDAR_ID",
    "Discord (Gaming)": "DISCORD_CALENDAR_ID",
}


def _household_timezone():
    timezone_name = os.getenv("HOUSEHOLD_TIMEZONE", "America/New_York")
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        # Windows has no built-in IANA timezone database; fall back to the
        # system's local offset rather than retrying the same failed lookup.
        return datetime.now().astimezone().tzinfo


HOUSEHOLD_TZ = _household_timezone()


def _credentials_path() -> str:
    return os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "google-service-account.json")


def get_service():
    """Build an authenticated Calendar API client from the service account key."""
    credentials = service_account.Credentials.from_service_account_file(
        _credentials_path(), scopes=SCOPES
    )
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def get_configured_calendars() -> dict[str, str]:
    """Return {label: calendar_id} for whichever of the 4 household calendars
    have an ID set in .env - lets setup proceed incrementally rather than
    requiring all 4 at once."""
    calendars = {
        label: os.getenv(env_var) for label, env_var in CALENDAR_ENV_VARS.items()
    }
    return {label: calendar_id for label, calendar_id in calendars.items() if calendar_id}


def check_calendar_access(service=None) -> dict[str, dict]:
    """For each configured calendar, confirm the service account can actually
    read it (i.e. it's been shared). Returns, per label:
    {"ok": True, "summary": <calendar display name>} or
    {"ok": False, "error": <what went wrong>}."""
    service = service or get_service()
    results = {}
    for label, calendar_id in get_configured_calendars().items():
        try:
            info = service.calendars().get(calendarId=calendar_id).execute()
            results[label] = {"ok": True, "summary": info.get("summary", calendar_id)}
        except Exception as error:
            results[label] = {"ok": False, "error": str(error)}
    return results


def list_events(
    calendar_id: str,
    time_min: datetime,
    time_max: datetime,
    service=None,
) -> list[dict]:
    """Return raw event resources from one calendar in [time_min, time_max).
    Expands recurring events into individual instances (singleEvents=True) so
    a weekly event like "Minecraft Mondays" shows up on each Monday it
    covers, rather than as one unexpanded recurring master."""
    service = service or get_service()
    response = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=time_min.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    return response.get("items", [])


def get_week_events(monday: date, service=None) -> list[dict]:
    """Fetch this week's events (Monday 00:00 through the following Monday
    00:00, household time) from every configured calendar, deduplicated
    across calendars and tagged with which calendar(s) each one came from."""
    service = service or get_service()
    time_min = datetime.combine(monday, datetime.min.time(), tzinfo=HOUSEHOLD_TZ)
    time_max = time_min + timedelta(days=7)

    raw_events = []
    for label, calendar_id in get_configured_calendars().items():
        for item in list_events(calendar_id, time_min, time_max, service=service):
            if item.get("status") == "cancelled":
                continue
            raw_events.append(normalize_event(item, label))

    return deduplicate_events(raw_events, source_order=list(CALENDAR_ENV_VARS.keys()))

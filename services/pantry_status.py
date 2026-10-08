"""Pieces of /pantry_status - one line per moving part of the pantry, so
something broken on the home server shows up in Discord without reading
logs. Pure helpers here (ages, backup lookups, the embed); the checks that
call Grocy/OurGroceries/Discord live in commands/pantry_commands.py."""

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import discord

OK = "ok"
WARN = "warn"
FAIL = "fail"
OFF = "off"  # not configured - fine if intentional

ICONS = {OK: "✅", WARN: "⚠️", FAIL: "❌", OFF: "➖"}

# Rosie writes this at the end of every 10-minute pantry pass.
UPKEEP_STATE_KEY = "pantry_upkeep_at"

CATALOG_STALE_DAYS = 40      # monthly sync, plus slack
BACKUP_STALE_HOURS = 36      # nightly, plus slack
UPKEEP_STALE_MINUTES = 30    # every 10 minutes, plus slack

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Check:
    label: str
    status: str
    detail: str

    def line(self) -> str:
        return f"{ICONS[self.status]} **{self.label}** — {self.detail}"


def age_label(then: datetime | None, now: datetime) -> str:
    if then is None:
        return "never"
    seconds = max((now - then).total_seconds(), 0)
    if seconds < 90:
        return "just now"
    minutes = seconds / 60
    if minutes < 90:
        return f"{minutes:.0f} min ago"
    hours = minutes / 60
    if hours < 36:
        return f"{hours:.0f} hours ago"
    return f"{hours / 24:.0f} days ago"


def parse_time(value: str | None) -> datetime | None:
    """bot_state timestamps are ISO strings, with or without a timezone."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def grocy_backup_dir() -> Path:
    """Where the grocy-backup container writes: the repo's grocy/backups by
    default (right on the home server), or GROCY_BACKUP_DIR for a Grocy that
    runs from somewhere else."""
    return Path(os.getenv("GROCY_BACKUP_DIR") or REPO_ROOT / "grocy" / "backups")


def latest_backup(directory: Path, pattern: str) -> datetime | None:
    """Modified time of the newest backup in a folder, or None if there are none."""
    if not directory.is_dir():
        return None
    times = [path.stat().st_mtime for path in directory.glob(pattern)]
    return datetime.fromtimestamp(max(times)) if times else None


def backup_check(label: str, directory: Path, pattern: str, now: datetime) -> Check:
    newest = latest_backup(directory, pattern)
    if newest is None:
        if not directory.is_dir():
            return Check(label, WARN, f"no backup folder at `{directory}`")
        return Check(label, WARN, "no backups yet")
    hours = (now - newest).total_seconds() / 3600
    status = OK if hours <= BACKUP_STALE_HOURS else WARN
    return Check(label, status, f"newest {age_label(newest, now)}")


def overall_status(checks: list[Check]) -> str:
    statuses = {check.status for check in checks}
    if FAIL in statuses:
        return FAIL
    if WARN in statuses:
        return WARN
    return OK


def build_status_embed(checks: list[Check], numbers: str | None = None) -> discord.Embed:
    overall = overall_status(checks)
    title = {
        OK: "🥫 Pantry status — all good",
        WARN: "🥫 Pantry status — mostly working",
        FAIL: "🥫 Pantry status — something's broken",
    }[overall]
    color = {OK: 0x2E8B57, WARN: 0xE0A100, FAIL: 0xC8102E}[overall]
    embed = discord.Embed(title=title, description="\n".join(check.line() for check in checks)[:4096], color=color)
    if numbers:
        embed.add_field(name="In the pantry", value=numbers[:1024], inline=False)
    return embed

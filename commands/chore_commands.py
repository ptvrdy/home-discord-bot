import os
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from discord import app_commands
from discord.ext import commands, tasks

from services.chore_stats_embed import build_chore_stats_embed
from services.chores import (
    chore_stats,
    chores_needing_nudge,
    count_completions_by_person,
    days_since,
    fairness_callout,
    filter_person_completions,
    format_nudge_message,
    mention_for_person,
    random_overdue_chore,
)
from services.database import (
    get_all_chores,
    get_chore_completions_between,
    get_chore_completions_by_person,
    get_chore_log_entries,
    get_chore_names,
    get_completed_tasks_between,
    get_state,
    mark_chore_done,
    mark_nudge_sent,
    set_state,
    undo_last_done,
)
from services.schedule import previous_week_start
from services.weekly_digest_embed import build_weekly_digest_embed


def _household_timezone():
    timezone_name = os.getenv("HOUSEHOLD_TIMEZONE", "America/New_York")
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        # Windows has no built-in IANA timezone database; fall back to the
        # system's local offset rather than retrying the same failed lookup.
        return datetime.now().astimezone().tzinfo


HOUSEHOLD_TZ = _household_timezone()
NUDGE_TIMES = [time(9, 0, tzinfo=HOUSEHOLD_TZ), time(17, 0, tzinfo=HOUSEHOLD_TZ)]
WEEKLY_DIGEST_TIME = time(20, 0, tzinfo=HOUSEHOLD_TZ)  # checked daily, only posts on Sunday
WEEKLY_DIGEST_WEEKDAY = 6  # Sunday, per date.weekday() (Monday=0 ... Sunday=6)
WEEKLY_DIGEST_MESSAGE_STATE_KEY = "weekly_digest_message_id"


async def chore_name_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    current_lower = current.lower()
    matches = [name for name in get_chore_names() if current_lower in name.lower()]
    return [app_commands.Choice(name=name, value=name) for name in matches[:25]]


async def post_weekly_digest(bot: commands.Bot) -> None:
    """Rebuild and post/edit the single weekly digest message (chores done
    last week, still overdue) in the same channel #this-week lives in -
    edited in place every week, never a new message, exactly like #this-week
    itself. Shared by the scheduled Sunday-night post and the manual
    /weekly_digest command so both paths can never drift out of sync."""
    channel_id = os.getenv("THIS_WEEK_CHANNEL_ID")
    if not channel_id:
        return

    channel = bot.get_channel(int(channel_id))
    if not isinstance(channel, discord.abc.Messageable):
        return

    now = datetime.now(HOUSEHOLD_TZ)
    last_week_start = previous_week_start(now.date())

    range_start = datetime.combine(last_week_start, datetime.min.time(), tzinfo=HOUSEHOLD_TZ)
    range_end = range_start + timedelta(days=7)

    completions = get_chore_completions_between(range_start, range_end)
    tasks = get_completed_tasks_between(range_start, range_end)
    chores = get_all_chores()
    embed = build_weekly_digest_embed(last_week_start, completions, chores, now, tasks=tasks)

    message_id = get_state(WEEKLY_DIGEST_MESSAGE_STATE_KEY)
    if message_id:
        try:
            message = await channel.fetch_message(int(message_id))
            await message.edit(embed=embed)
            return
        except discord.NotFound:
            pass  # the message was deleted; fall through and repost it

    message = await channel.send(embed=embed)
    set_state(WEEKLY_DIGEST_MESSAGE_STATE_KEY, str(message.id))


class Chores(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        nudges_channel_id = os.getenv("NUDGES_CHANNEL_ID")
        self.nudges_channel_id = int(nudges_channel_id) if nudges_channel_id else None
        self.nudge_check.start()
        self.weekly_digest_task.start()

    def cog_unload(self):
        self.nudge_check.cancel()
        self.weekly_digest_task.cancel()

    @tasks.loop(time=WEEKLY_DIGEST_TIME)
    async def weekly_digest_task(self):
        if datetime.now(HOUSEHOLD_TZ).weekday() != WEEKLY_DIGEST_WEEKDAY:
            return
        await post_weekly_digest(self.bot)

    @weekly_digest_task.before_loop
    async def before_weekly_digest(self):
        await self.bot.wait_until_ready()

    @tasks.loop(time=NUDGE_TIMES)
    async def nudge_check(self):
        if self.nudges_channel_id is None:
            return

        channel = self.bot.get_channel(self.nudges_channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            return

        now = datetime.now(HOUSEHOLD_TZ)
        chores = get_all_chores()
        personal_name = os.getenv("PERSONAL_NAME")
        partner_name = os.getenv("PARTNER_NAME")
        personal_discord_id = os.getenv("PERSONAL_DISCORD_ID")
        partner_discord_id = os.getenv("PARTNER_DISCORD_ID")
        for chore in chores_needing_nudge(chores, now):
            entries = get_chore_log_entries(chore["name"])
            next_person = fairness_callout(entries, personal_name, partner_name)
            next_mention = (
                mention_for_person(next_person, personal_name, partner_name, personal_discord_id, partner_discord_id)
                if next_person
                else None
            )
            await channel.send(format_nudge_message(chore, now, next_mention))
            mark_nudge_sent(chore["name"], now)

    @nudge_check.before_loop
    async def before_nudge_check(self):
        await self.bot.wait_until_ready()

    @app_commands.command(
        name="done",
        description="Mark a household chore as completed",
    )
    @app_commands.describe(
        chore="Which chore you completed",
        completed_by="Optional: attribute this to someone else instead of yourself",
        days_ago="Optional: backdate this (e.g. 3 for \"3 days ago\") instead of just now",
    )
    @app_commands.autocomplete(chore=chore_name_autocomplete)
    async def done(
        self,
        interaction: discord.Interaction,
        chore: str,
        completed_by: discord.Member | None = None,
        days_ago: app_commands.Range[int, 0, 3650] = 0,
    ):
        member = completed_by or interaction.user
        done_at = datetime.now(HOUSEHOLD_TZ) - timedelta(days=days_ago)
        updated = mark_chore_done(chore, member.display_name, done_at)

        if updated is None:
            await interaction.response.send_message(
                f'❌ No chore named "{chore}" — pick a suggestion from the '
                "autocomplete list so the name matches exactly.",
                ephemeral=True,
            )
            return

        when = f"{days_ago} day{'s' if days_ago != 1 else ''} ago" if days_ago else "just now"
        await interaction.response.send_message(
            f"✅ **{updated['name']}** marked done by {member.display_name} ({when})."
        )

        # Deferred import: schedule_commands imports chore_name_autocomplete
        # from this module at load time, so importing it back at module
        # level here would be a circular import. By call time both modules
        # are already fully loaded, so a local import works fine.
        from commands.schedule_commands import refresh_this_week

        await refresh_this_week(self.bot)

    @app_commands.command(
        name="chore_stats",
        description="See household chore stats: overdue, coming up, and who's been keeping up",
    )
    async def chore_stats_command(self, interaction: discord.Interaction):
        now = datetime.now(HOUSEHOLD_TZ)
        chores = get_all_chores()
        stats = chore_stats(chores, now)
        raw_by_person = {row["done_by"]: row["entry_count"] for row in get_chore_completions_by_person()}
        stats["by_person"] = filter_person_completions(raw_by_person)

        month_start = now - timedelta(days=30)
        recent_completions = get_chore_completions_between(month_start, now + timedelta(seconds=1))
        stats["by_person_month"] = count_completions_by_person(recent_completions)

        personal_name = os.getenv("PERSONAL_NAME")
        partner_name = os.getenv("PARTNER_NAME")
        personal_discord_id = os.getenv("PERSONAL_DISCORD_ID")
        partner_discord_id = os.getenv("PARTNER_DISCORD_ID")
        fairness_callouts = []
        for chore in chores:
            entries = get_chore_log_entries(chore["name"])
            next_person = fairness_callout(entries, personal_name, partner_name)
            if next_person:
                next_mention = mention_for_person(
                    next_person, personal_name, partner_name, personal_discord_id, partner_discord_id
                )
                fairness_callouts.append({"chore": chore["name"], "next_person": next_mention})
        stats["fairness_callouts"] = fairness_callouts

        await interaction.response.send_message(embed=build_chore_stats_embed(stats))

    @app_commands.command(
        name="undo_done",
        description="Undo the most recent /done you logged for a chore",
    )
    @app_commands.describe(chore="Which chore to undo the last completion for")
    @app_commands.autocomplete(chore=chore_name_autocomplete)
    async def undo_done(self, interaction: discord.Interaction, chore: str):
        result = undo_last_done(chore)

        if result is None:
            await interaction.response.send_message(
                f'❌ No logged completion to undo for "{chore}" — either the '
                "chore name doesn't match exactly, or it has no history yet.",
                ephemeral=True,
            )
            return

        updated_chore = result["chore"]
        removed = result["removed"]
        if updated_chore["last_done_at"]:
            new_state = f"now last logged as done by {updated_chore['last_done_by']}"
        else:
            new_state = "now has no logged history at all"

        await interaction.response.send_message(
            f"↩️ Undid **{updated_chore['name']}**'s completion by {removed['done_by']} — {new_state}."
        )

    @app_commands.command(
        name="weekly_digest",
        description="Manually post the weekly recap instead of waiting for Sunday night",
    )
    async def weekly_digest_command(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        if not os.getenv("THIS_WEEK_CHANNEL_ID"):
            await interaction.followup.send(
                "❌ THIS_WEEK_CHANNEL_ID isn't set in .env.", ephemeral=True
            )
            return

        await post_weekly_digest(self.bot)
        await interaction.followup.send("✅ Weekly digest posted.", ephemeral=True)

    @app_commands.command(
        name="random_chore",
        description="Suggest what to do today, weighted toward whatever's most overdue",
    )
    async def random_chore(self, interaction: discord.Interaction):
        now = datetime.now(HOUSEHOLD_TZ)
        chore = random_overdue_chore(get_all_chores(), now)

        if chore is None:
            await interaction.response.send_message(
                "✅ Nothing's overdue right now — you're all caught up!"
            )
            return

        days = days_since(chore["last_done_at"], now)
        if days is None:
            history = "never been logged as done"
        else:
            day_word = "day" if days == 1 else "days"
            history = f"last done {days} {day_word} ago"

        await interaction.response.send_message(
            f"🎲 How about **{chore['name']}**? ({history})"
        )


async def setup(bot):
    await bot.add_cog(Chores(bot))

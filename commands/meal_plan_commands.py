from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from commands.recipe_commands import recipe_title_autocomplete
from commands.schedule_commands import refresh_this_week
from services.database import add_meal_plan_item, clear_meal_plan
from services.google_calendar import HOUSEHOLD_TZ
from services.schedule import get_week_start

MEAL_CHOICES = [
    app_commands.Choice(name="🍳 Breakfast", value="breakfast"),
    app_commands.Choice(name="🥪 Lunch", value="lunch"),
    app_commands.Choice(name="🍽️ Dinner", value="dinner"),
]


class MealPlan(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="plan_meal",
        description="Add a recipe to this week's breakfast/lunch/dinner list (not tied to a day)",
    )
    @app_commands.describe(
        meal="Which meal",
        recipe="Recipe name (autocomplete suggests saved recipes, but you can type anything)",
    )
    @app_commands.choices(meal=MEAL_CHOICES)
    @app_commands.autocomplete(recipe=recipe_title_autocomplete)
    async def plan_meal(
        self,
        interaction: discord.Interaction,
        meal: app_commands.Choice[str],
        recipe: str,
    ):
        now = datetime.now(HOUSEHOLD_TZ)
        week_start = get_week_start(now.date())

        add_meal_plan_item(week_start, meal.value, recipe, interaction.user.display_name, now)

        await interaction.response.send_message(f"✅ Added **{recipe}** to this week's {meal.name}.")
        await refresh_this_week(self.bot)

    @app_commands.command(
        name="clear_meal_plan",
        description="Clear this week's breakfast/lunch/dinner list",
    )
    async def clear_meal_plan_command(self, interaction: discord.Interaction):
        now = datetime.now(HOUSEHOLD_TZ)
        week_start = get_week_start(now.date())

        removed = clear_meal_plan(week_start)

        if removed:
            await interaction.response.send_message(f"🧹 Cleared {removed} item(s) from this week's food plan.")
        else:
            await interaction.response.send_message("🧹 Nothing to clear — this week's food plan is already empty.")
        await refresh_this_week(self.bot)


async def setup(bot):
    await bot.add_cog(MealPlan(bot))

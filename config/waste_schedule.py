"""Weekly trash/recycling/compost pickup schedule shown on #this-week, as an
emoji row per day - same visual idea as the office/home status line, but
driven by a fixed weekly schedule instead of calendar events.

Keys are weekday indices matching date.weekday() (Monday=0 ... Sunday=6).
Edit this to match your own household's actual pickup days. Leave it empty
(or remove entries) to turn the row off entirely for days without pickup -
there's no separate on/off setting, an empty schedule just never shows a line.
"""

WASTE_SCHEDULE: dict[int, str] = {
    1: "🗑️ Trash · ♻️ Recycling · 🌱 Compost",  # Tuesday
    3: "🗑️ Trash · 🛋️ Large Items",  # Thursday
    5: "🗑️ Trash · 🛋️ Large Items",  # Saturday
}

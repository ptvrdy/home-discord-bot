"""Default household chores and their nudge thresholds (in days). Seeded into
the chores table on first run; editing this list after that only affects
brand-new installs — existing rows aren't touched, so a household's chore
history is never silently reset."""

DEFAULT_CHORES = [
    ("Wash bed sheets", 7),
    ("Vacuum downstairs", 14),
    ("Vacuum upstairs", 14),
    ("Vacuum stairs", 14),
    ("Vacuum couch", 14),
    ("Clean upstairs bathroom", 14),
    ("Clean downstairs bathroom", 14),
    ("Mop", 14),
    ("Wipe out fridge", 30),
    ("Clean microwave", 35),
    ("Litter box full clean", 60),
    ("Clean oven", 75),
    ("Vacuum behind furniture", 105),
    ("Wipe baseboards", 75),
]

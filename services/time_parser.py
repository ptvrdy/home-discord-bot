import re


def parse_minutes(time_value):
    if not time_value:
        return None

    # Already a number
    if isinstance(time_value, int):
        return time_value

    time_string = str(time_value).lower()

    minutes = 0

    # ISO format from Schema.org: PT2H30M
    hours = re.search(r"(\d+)h", time_string)
    mins = re.search(r"(\d+)m", time_string)

    if hours:
        minutes += int(hours.group(1)) * 60

    if mins:
        minutes += int(mins.group(1))

    # Normal text: "2 hours 30 minutes"
    hours = re.search(r"(\d+)\s*hour", time_string)
    mins = re.search(r"(\d+)\s*minute", time_string)

    if hours:
        minutes += int(hours.group(1)) * 60

    if mins:
        minutes += int(mins.group(1))

    return minutes if minutes > 0 else None
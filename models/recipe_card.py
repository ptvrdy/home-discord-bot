from dataclasses import dataclass, field


@dataclass
class Recipe:
    title: str

    ingredients: list[str]

    instructions: str | None = None

    prep_time: str | None = None
    cook_time: str | None = None
    total_time: str | None = None
    yields: str | None = None

    image_url: str | None = None
    source_url: str | None = None
    
    tags: list[str] = field(default_factory=list)
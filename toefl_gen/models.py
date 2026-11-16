from dataclasses import dataclass, field

LETTERS = "ABCD"


@dataclass
class Item:
    section: str
    part: str
    family_id: str
    topic: str
    level: str
    stem: str
    options: list
    key: str
    pembahasan: str
    frame_id: str
    fingerprint: str
    number: int = 0
    meta: dict = field(default_factory=dict)

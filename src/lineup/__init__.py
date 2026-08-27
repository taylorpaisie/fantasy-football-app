"""Future start/sit optimization contracts."""

from enum import Enum


class LineupStrategy(str, Enum):
    UPSIDE = "Need upside"
    FLOOR = "Need floor"
    NEUTRAL = "Neutral"


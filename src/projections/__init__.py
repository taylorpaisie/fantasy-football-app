"""Projection provider interfaces."""

from typing import Protocol

import pandas as pd


class ProjectionProvider(Protocol):
    def load(self, season: int) -> pd.DataFrame: ...


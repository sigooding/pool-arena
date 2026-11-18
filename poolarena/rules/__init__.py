"""Game modes. Importing this package registers every built-in game."""
from .base import Game, ShotContext, ShotResult, available, get_game, register  # noqa: F401
from . import cutthroat, drills, eightball, hotspots, killer, nineball, roulette  # noqa: F401

__all__ = ["Game", "ShotContext", "ShotResult", "available", "get_game", "register"]

"""One banner at a time.

Two banners drawn at the same place on the cloth interleave into something
neither legible nor obviously broken — every word is there, just on top of
another word. It happened because a game added its own banner to the one the
base class already emits, which is an easy mistake to repeat.
"""
import re
from pathlib import Path

from helpers import TABLE

from poolarena.ballset import AMERICAN, ENGLISH
from poolarena.rules import available, get_game


def banners(effects):
    return [e for e in effects if e.name == "banner"]


def test_no_game_starts_with_more_than_one_banner():
    for entry in available(AMERICAN):
        cls = get_game(entry["name"])
        players = ["A", "B", "C"][:cls.min_players] or ["A", "B"]
        game = cls(players=players, table=TABLE)
        found = banners(game.on_start())
        assert len(found) <= 1, f"{entry['name']} starts with {len(found)} banners"


def test_the_start_banner_carries_the_game_specific_note():
    """The second banner existed to say "10 shots"; that has to survive."""
    drill = get_game("position")(players=["A"], table=TABLE, options={"shots": 7})
    sub = banners(drill.on_start())[0].args["subtitle"]
    assert "7 shots" in sub
    assert "ring" in sub, "and the description is still there"

    hot = get_game("hotspots")(players=["A"], table=TABLE, options={"target": 40})
    assert "40" in banners(hot.on_start())[0].args["subtitle"]


def test_the_start_banner_names_the_game():
    for name in ("uk8", "hotspots", "position", "killer"):
        game = get_game(name)(players=["A", "B"], table=TABLE)
        b = banners(game.on_start())[0]
        assert b.args["text"], name
        assert b.args["text"] == b.args["text"].upper(), "titles are set in caps"


def test_english_eight_ball_still_reads_in_colours():
    game = get_game("uk8")(players=["A", "B"], table=TABLE, ball_set=ENGLISH)
    b = banners(game.on_start())[0]
    assert "ENGLISH 8-BALL" in b.args["text"]


def test_no_turn_start_emits_two_banners_either():
    from poolarena.types import TableState
    from helpers import state
    table_state = state(b0=(400, 600), b3=(1800, 300), b11=(900, 200), b8=(1200, 500))
    for entry in available(AMERICAN):
        cls = get_game(entry["name"])
        players = ["A", "B", "C"][:cls.min_players] or ["A", "B"]
        game = cls(players=players, table=TABLE)
        found = banners(game.on_turn_start(table_state))
        assert len(found) <= 1, f"{entry['name']} turn start has {len(found)} banners"


def test_the_renderer_queues_banners_rather_than_stacking_them():
    """Belt and braces: even if a game sends two, the overlay must not draw
    them on top of each other."""
    src = (Path(__file__).resolve().parent.parent
           / "overlay" / "src" / "main.js").read_text()
    assert "function queueBanner" in src
    assert re.search(r"queueBanner\(fx\)", src), "it has to actually be called"
    fx = (Path(__file__).resolve().parent.parent
          / "overlay" / "src" / "effects.js").read_text()
    assert "if (this.waiting) return;" in fx, "a queued banner must not paint"

"""No game running is a state, not an absence.

The scoreboard shows a splash screen until somebody picks a game, and that
only works if "there is no game" is something the server says out loud. A
page that has not heard yet and a table nobody has racked up look identical
otherwise, and one of them should show a picker while the other shows
nothing at all.
"""
import pytest
from helpers import TABLE

from poolarena.engine import Engine


class RecordingHub:
    def __init__(self):
        self.sent = []
        self.sticky = {}
        self.on_message = None

    def broadcast(self, msg, sticky_key=None):
        self.sent.append(msg)
        if sticky_key:
            self.sticky[sticky_key] = msg


@pytest.fixture
def engine():
    e = Engine(table=TABLE, hub=RecordingHub(), idle_after=0)
    yield e
    e.close()


def boards(hub):
    return [m for m in hub.sent if m.get("type") == "scoreboard"]


def test_an_engine_with_no_game_says_so(engine):
    engine.push_scoreboard()
    msgs = boards(engine.hub)
    assert msgs, "it has to say something, or the page cannot tell"
    assert msgs[-1]["scoreboard"] is None


def test_the_null_is_replayed_to_a_late_joiner(engine):
    """Sticky, like every other state: open the page an hour later and it
    still knows there is no game on."""
    engine.push_scoreboard()
    assert "scoreboard" in engine.hub.sticky
    assert engine.hub.sticky["scoreboard"]["scoreboard"] is None


def test_starting_a_game_replaces_the_null(engine):
    engine.start_game("8ball", ["A", "B"])
    last = boards(engine.hub)[-1]["scoreboard"]
    assert last is not None
    assert last["title"] == "8-Ball"


def test_a_game_can_be_started_from_nothing(engine):
    """The whole point: the splash has to be able to begin a game."""
    engine.push_scoreboard()
    assert engine.game is None
    engine.start_game("timebomb", ["Sam"])
    assert engine.game is not None
    assert engine.hub.sticky["scoreboard"]["scoreboard"]["title"] == "Time Bomb"


def test_feeding_frames_with_no_game_scores_nothing(engine):
    """A table nobody has started a game on is not mid-frame, so watching it
    must not quietly accumulate anything."""
    from helpers import state
    for _ in range(5):
        engine.feed(state(b0=(400, 500), b3=(900, 300), b8=(1200, 600)))
    assert engine.game is None
    assert engine.history == []


# --- the page itself ------------------------------------------------------
from pathlib import Path

OVERLAY = Path(__file__).resolve().parent.parent / "overlay"


def test_the_splash_is_in_the_page():
    html = (OVERLAY / "scoreboard.html").read_text()
    assert 'id="splash"' in html
    assert 'id="splash-games"' in html
    assert 'id="splash-options"' in html


def test_the_splash_carries_no_title_of_its_own():
    """The artwork has one. Two stacked is one too many, and anything else
    lands on the rack of balls painted underneath it."""
    html = (OVERLAY / "scoreboard.html").read_text()
    splash = html.split('id="splash"', 1)[1].split("</section>", 1)[0]
    assert "<h1" not in splash


def test_the_picker_is_built_for_both_places():
    js = (OVERLAY / "src" / "board.js").read_text()
    assert "renderGamesInto" in js
    assert "'games', 'splash-games'" in js, "both grids come from one list"


def test_the_splash_hides_once_a_board_arrives():
    js = (OVERLAY / "src" / "board.js").read_text()
    assert "showSplash(!board)" in js


def test_the_table_is_hidden_with_no_game():
    css = (OVERLAY / "src" / "board.css").read_text()
    assert "body.no-game .grid" in css
    assert "display: none" in css.split("body.no-game .grid", 1)[1][:200]


def test_the_splash_uses_the_full_artwork_and_the_game_view_does_not():
    """Two backdrops on purpose: the picture is the point on the splash and
    a texture behind a working instrument during a game."""
    css = (OVERLAY / "src" / "board.css").read_text()
    assert "img/splash.webp" in css
    assert "img/backdrop.webp" in css
    assert (OVERLAY / "img" / "splash.webp").exists()
    assert (OVERLAY / "img" / "backdrop.webp").exists()


def test_tapping_a_card_on_the_splash_asks_who_is_playing():
    """Tap a game and it asks the names, then starts. Not because a step is
    wanted for its own sake — the names matter more often than they do not,
    and typing them after the break means racking up again."""
    js = (OVERLAY / "src" / "board.js").read_text()
    assert "const startsOnTap = containerId === 'splash-games'" in js
    assert "if (startsOnTap) askWho()" in js
    assert "function askWho()" in js


def test_the_player_sheet_can_be_backed_out_of():
    """It covers the games, so there has to be a way back to them."""
    js = (OVERLAY / "src" / "board.js").read_text()
    assert "el('who-back').onclick" in js
    assert "'Escape'" in js.split("function askWho", 1)[1]
    html = (OVERLAY / "scoreboard.html").read_text()
    assert 'id="who-back"' in html and 'id="who-start"' in html


def test_the_splash_has_no_start_button():
    html = (OVERLAY / "scoreboard.html").read_text()
    splash = html.split('id="splash"', 1)[1].split("</section>", 1)[0]
    assert "splash-start" not in splash
    assert 'id="splash-options"' in splash, "Options stays, though"


def test_the_setup_tab_still_only_selects():
    """There you have the roster and the options in front of you already, so
    a tap must not open a sheet or commit you to anything."""
    js = (OVERLAY / "src" / "board.js").read_text()
    body = js.split("function renderGamesInto", 1)[1].split("\n}", 1)[0]
    assert body.count("askWho()") == 1, "only ever behind the splash guard"
    assert "if (startsOnTap)" in body


# --- quitting -------------------------------------------------------------
def test_there_is_a_way_out_of_a_game():
    """Without one, leaving a game means restarting the program."""
    html = (OVERLAY / "scoreboard.html").read_text()
    assert 'id="quit"' in html
    js = (OVERLAY / "src" / "board.js").read_text()
    assert "el('quit').onclick" in js
    assert "type: 'end_game'" in js


def test_quitting_mid_frame_asks_first():
    js = (OVERLAY / "src" / "board.js").read_text()
    body = js.split("el('quit').onclick", 1)[1][:400]
    assert "confirm(" in body, "it throws away the frame in progress"
    assert "board.over" in body, "but a finished game needs no confirming"


def test_quit_is_hidden_on_the_splash():
    js = (OVERLAY / "src" / "board.js").read_text()
    assert "el('quit').hidden = !!on" in js


def test_ending_a_game_returns_the_engine_to_nothing(engine):
    engine.start_game("8ball", ["A", "B"])
    engine.handle_client_message({"type": "end_game"})
    assert engine.game is None
    assert engine.hub.sticky["scoreboard"]["scoreboard"] is None


def test_ending_a_game_clears_the_cloth(engine):
    """A dead frame's guides left lit on a table nobody is playing on is how
    a projector ends up stuck showing the last game all evening."""
    engine.start_game("hotspots", ["A"])
    engine.hub.sent.clear()
    engine.end_game()
    batches = [m for m in engine.hub.sent if m.get("type") == "effects"]
    assert any(m.get("clear") == "all" for m in batches)


def test_ending_a_game_drops_its_history(engine):
    engine.start_game("8ball", ["A", "B"])
    engine.history.append({"shot": 0})
    engine.end_game()
    assert engine.history == []
    assert not engine.can_undo


def test_a_new_game_can_be_started_after_quitting(engine):
    engine.start_game("8ball", ["A", "B"])
    engine.end_game()
    engine.start_game("timebomb", ["Sam"])
    assert engine.game is not None and engine.game.name == "timebomb"

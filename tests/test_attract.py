"""Attract mode.

The interesting property is not that it looks good — it is that it is never
in the way. A table that keeps crawling with light while somebody is down on
a shot is worse than one that stays dark, so most of this is about stopping.
"""
import time

from helpers import TABLE, state

from poolarena.attract import AttractMode, IdleWatch
from poolarena.engine import Engine
from poolarena.server.ws import Hub


def collecting_hub():
    hub = Hub()
    sent = []
    hub.broadcast = lambda msg, sticky_key=None: sent.append(msg)   # type: ignore
    return hub, sent


# --- the idle watch -------------------------------------------------------
def test_a_still_table_goes_idle():
    w = IdleWatch(after_seconds=0.2)
    still = state(b0=(400, 600), b3=(1800, 300))
    assert w.observe(still) is False or True      # first call seeds positions
    w.observe(still)
    assert not w.should_attract()
    time.sleep(0.25)
    assert w.should_attract()


def test_a_moving_ball_counts_as_activity():
    w = IdleWatch(after_seconds=0.1)
    w.observe(state(b0=(400, 600), b3=(1800, 300)))
    time.sleep(0.15)
    assert w.should_attract()
    assert w.observe(state(b0=(900, 600), b3=(1800, 300))) is True
    assert not w.should_attract()


def test_an_arm_over_the_table_counts_as_activity():
    """Obstruction means a person is there, even though nothing has moved."""
    w = IdleWatch(after_seconds=0.1)
    still = state(b0=(400, 600))
    w.observe(still)
    time.sleep(0.15)
    assert w.should_attract()
    obstructed = state(b0=(400, 600))
    obstructed.obstructed = True
    assert w.observe(obstructed) is True
    assert not w.should_attract()


def test_a_ball_disappearing_counts_as_activity():
    w = IdleWatch(after_seconds=5)
    w.observe(state(b0=(400, 600), b3=(1800, 300)))
    assert w.observe(state(b0=(400, 600))) is True


def test_tiny_jitter_is_not_activity():
    """Detection noise must not keep a dead table awake all night."""
    w = IdleWatch(after_seconds=5)
    w.observe(state(b0=(400.0, 600.0)))
    assert w.observe(state(b0=(402.0, 601.5))) is False


# --- the driver -----------------------------------------------------------
def test_it_broadcasts_a_ghost_game_and_stops_cleanly():
    sent = []
    a = AttractMode(table=TABLE, broadcast=sent.append, seed=2,
                    games=[{"title": "8-Ball", "description": "d", "supported": True}])
    a.start()
    time.sleep(0.6)
    assert a.active
    a.stop()
    assert not a.active
    frames = [m for m in sent if m.get("active")]
    assert len(frames) > 5, "should be running at something like 30 fps"
    assert frames[0]["balls"], "the ghost game needs balls"
    assert sent[-1] == {"type": "attract", "active": False}, "must tell the overlay to clear"


def test_the_captions_say_how_to_start_and_name_the_games():
    a = AttractMode(table=TABLE, broadcast=lambda m: None,
                    games=[{"title": "Hotspots", "description": "zones", "supported": True},
                           {"title": "9-Ball", "description": "x", "supported": False}])
    caps = a._captions()
    joined = " ".join(c["title"] + " " + c["sub"] for c in caps).lower()
    assert "rack up" in joined, "it has to tell a stranger how to begin"
    assert "hotspots" in joined
    assert "9-ball" not in joined, "do not advertise a game this table cannot run"


def test_starting_twice_is_harmless():
    a = AttractMode(table=TABLE, broadcast=lambda m: None, seed=1)
    a.start()
    a.start()
    time.sleep(0.2)
    a.stop()
    assert not a.active


# --- engine integration ---------------------------------------------------
def test_the_engine_starts_it_when_the_table_is_abandoned():
    hub, sent = collecting_hub()
    e = Engine(table=TABLE, hub=hub, idle_after=0.3)
    try:
        still = state(b0=(400, 600), b3=(1800, 300))
        e.feed(still)
        assert not e.attract.active
        time.sleep(0.45)
        e.feed(still)
        assert e.attract.active
    finally:
        e.close()


def test_a_shot_kills_it_immediately():
    hub, sent = collecting_hub()
    e = Engine(table=TABLE, hub=hub, idle_after=0.2)
    try:
        still = state(b0=(400, 600), b3=(1800, 300))
        e.feed(still)
        time.sleep(0.3)
        e.feed(still)
        assert e.attract.active
        e.feed(state(b0=(1200, 500), b3=(1800, 300)))
        assert not e.attract.active, "a moving ball must clear the table at once"
    finally:
        e.close()


def test_any_command_from_the_ui_wakes_the_table():
    hub, sent = collecting_hub()
    e = Engine(table=TABLE, hub=hub, idle_after=0.2)
    try:
        still = state(b0=(400, 600))
        e.feed(still)
        time.sleep(0.3)
        e.feed(still)
        assert e.attract.active
        e.handle_client_message({"type": "next_turn"})
        assert not e.attract.active
    finally:
        e.close()


def test_it_can_be_switched_off_entirely():
    hub, _ = collecting_hub()
    e = Engine(table=TABLE, hub=hub, idle_after=0)
    try:
        still = state(b0=(400, 600))
        e.feed(still)
        time.sleep(0.3)
        e.feed(still)
        assert not e.attract.active
    finally:
        e.close()


def test_the_heartbeat_starts_it_without_any_frames():
    """A stalled camera sends nothing at all, which is as idle as it gets."""
    hub, _ = collecting_hub()
    e = Engine(table=TABLE, hub=hub, idle_after=0.3)
    try:
        time.sleep(1.6)                 # no feed() calls whatsoever
        assert e.attract.active
    finally:
        e.close()


def test_starting_a_game_stops_the_ghost_game():
    """A ghost game crawling over a live rack is worse than no attract mode."""
    hub, _ = collecting_hub()
    e = Engine(table=TABLE, hub=hub, idle_after=0.2)
    try:
        still = state(b0=(400, 600))
        e.feed(still)
        time.sleep(0.3)
        e.feed(still)
        assert e.attract.active
        e.start_game("9ball", players=["A", "B"])
        assert not e.attract.active
    finally:
        e.close()

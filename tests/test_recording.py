"""Recording games, and the figures drawn from them.

The point of a recording is not an archive, it is that a player can watch
their own shots back and see where frames are being lost. So these check
both that the data survives and that the numbers say something true.
"""
import json

from helpers import TABLE, events, state

from poolarena import recording as rec
from poolarena.engine import Engine
from poolarena.rules.base import ShotContext
from poolarena.server.ws import Hub
from poolarena.types import ShotEvents


def engine(tmp_path, game="9ball", players=("Sam", "Alex")):
    e = Engine(table=TABLE, hub=Hub(), recordings=tmp_path, idle_after=0)
    e.start_game(game, players=list(players))
    return e


def shoot(e, before, after, ev):
    snap = e._snapshot(e.game)
    ctx = ShotContext(before=before, after=after, events=ev, table=TABLE,
                      shooter=e.game.turn)
    res = e.game.apply(ctx)
    record = {"shot": e.game.shot_number - 1, "shooter": ctx.shooter,
              "events": ev.to_json(), "result": res.to_json(),
              "before": before.to_json(), "after": after.to_json()}
    e.history.append(record)
    e._undo.append((snap, record))
    e.recorder.add_shot(record, ev)
    return res


BEFORE = state(b0=(400, 600), b2=(1800, 300), b9=(900, 200))
AFTER = state(b0=(1600, 350), b9=(900, 200))


def test_a_game_is_written_as_it_is_played(tmp_path):
    """Not at the end: a session that stops because someone shut the laptop
    is still worth watching back."""
    e = engine(tmp_path)
    try:
        assert rec.list_sessions(tmp_path), "the file exists from the start"
        shoot(e, BEFORE, AFTER, events(pocketed=[2], pockets={2: "TR"}, first=2))
        sid = rec.list_sessions(tmp_path)[0]["id"]
        assert len(rec.load_session(tmp_path, sid)["shots"]) == 1
    finally:
        e.close()


def test_ball_paths_are_kept_because_they_are_the_point(tmp_path):
    e = engine(tmp_path)
    try:
        ev = events(pocketed=[2], pockets={2: "TR"}, first=2)
        ev.trace = {2: [(1800, 300), (1900, 250), (2100, 120)],
                    0: [(400, 600), (900, 500), (1600, 350)]}
        shoot(e, BEFORE, AFTER, ev)
        sid = rec.list_sessions(tmp_path)[0]["id"]
        shot = rec.load_session(tmp_path, sid)["shots"][0]
        assert "trace" in shot and shot["trace"], "no paths, nothing to replay"
        assert all(len(p) >= 2 for p in shot["trace"].values())
    finally:
        e.close()


def test_undo_also_retracts_the_recording(tmp_path):
    """A shot that officially did not happen must not appear in the review."""
    e = engine(tmp_path)
    try:
        shoot(e, BEFORE, AFTER, events(pocketed=[2], pockets={2: "TR"}, first=2))
        sid = rec.list_sessions(tmp_path)[0]["id"]
        assert len(rec.load_session(tmp_path, sid)["shots"]) == 1
        e.undo()
        assert len(rec.load_session(tmp_path, sid)["shots"]) == 0
    finally:
        e.close()


def test_starting_a_new_game_closes_the_old_recording(tmp_path):
    e = engine(tmp_path)
    try:
        shoot(e, BEFORE, AFTER, events(pocketed=[2], pockets={2: "TR"}, first=2))
        e.start_game("8ball", players=["A", "B"])
        assert len(rec.list_sessions(tmp_path)) == 2
    finally:
        e.close()


def test_recording_can_be_switched_off(tmp_path):
    e = Engine(table=TABLE, hub=Hub(), recordings=None, idle_after=0)
    try:
        e.start_game("9ball", players=["A", "B"])
        assert e.recorder is None
        assert rec.list_sessions(tmp_path) == []
    finally:
        e.close()


# --- the figures ----------------------------------------------------------
def session(shots, players=("Sam", "Alex")):
    return {"players": list(players), "shots": shots}


def shot(shooter, potted=(), foul=None, cue=None):
    s = {"shooter": shooter,
         "events": {"pocketed": list(potted)},
         "result": {"foul": foul} if foul else {},
         "before": {"balls": []}, "after": {"balls": []}}
    if cue:
        s["before"]["balls"] = [{"number": 0, "x": cue[0][0], "y": cue[0][1]}]
        s["after"]["balls"] = [{"number": 0, "x": cue[1][0], "y": cue[1][1]}]
    return s


def test_pot_rate_counts_shots_not_balls():
    """Two balls on one shot is one successful shot, not two."""
    st = rec.analyse(session([shot(0, [1, 2]), shot(0), shot(0, [3]), shot(0)]))
    p = st["players"][0]
    assert p["shots"] == 4 and p["pots"] == 2
    assert p["balls_potted"] == 3
    assert p["pot_rate"] == 0.5


def test_a_run_is_broken_by_a_miss_or_a_foul():
    st = rec.analyse(session([shot(0, [1]), shot(0, [2]), shot(0),
                              shot(0, [3]), shot(0, [4]), shot(0, [5])]))
    assert st["players"][0]["best_run"] == 3


def test_the_commonest_foul_is_singled_out():
    st = rec.analyse(session([shot(0, foul="in off"), shot(0, foul="in off"),
                              shot(0, foul="no rail after contact")]))
    p = st["players"][0]
    assert p["fouls"] == 3
    assert p["worst_foul"] == "in off"


def test_cue_ball_travel_is_measured_as_position_play():
    st = rec.analyse(session([shot(0, [1], cue=((0, 0), (300, 400))),
                              shot(0, [2], cue=((0, 0), (600, 800)))]))
    assert st["players"][0]["avg_cue_travel_mm"] == 750


def test_the_insight_names_the_weaker_player_and_stays_quiet_on_thin_data():
    thin = rec.analyse(session([shot(0, [1])]))
    assert "not enough" in thin["insight"].lower()

    full = rec.analyse(session(
        [shot(0, foul="in off") for _ in range(4)]
        + [shot(1, [1]) for _ in range(4)]))
    assert "Sam" in full["insight"]
    assert "in off" in full["insight"]


def test_a_missing_session_is_not_an_exception(tmp_path):
    assert rec.load_session(tmp_path, "nope") is None
    assert rec.delete_session(tmp_path, "nope") is False


def test_a_session_id_cannot_escape_the_recordings_directory(tmp_path):
    secret = tmp_path.parent / "secret.json"
    secret.write_text(json.dumps({"id": "secret", "shots": []}))
    assert rec.load_session(tmp_path, "../secret") is None


# --- across sessions ------------------------------------------------------
def finished_game(tmp_path, players, pots_each, winner=None):
    e = engine(tmp_path, players=players)
    try:
        for _ in range(pots_each):
            shoot(e, BEFORE, AFTER, events(pocketed=[2], pockets={2: "TR"}, first=2))
        e.recorder.finish(winner=winner)
    finally:
        e.close()


def test_career_totals_span_every_recording(tmp_path):
    finished_game(tmp_path, ("Sam", "Alex"), 2, winner=0)
    finished_game(tmp_path, ("Sam", "Alex"), 3, winner=1)
    c = rec.career(tmp_path)
    assert c["games"] == 2
    sam = next(p for p in c["players"] if p["name"] == "Sam")
    assert sam["games"] == 2 and sam["shots"] == 5
    assert sam["wins"] == 1 and sam["win_rate"] == 0.5


def test_career_matches_names_case_insensitively(tmp_path):
    """Nobody types their name the same way twice all night."""
    finished_game(tmp_path, ("Sam", "Alex"), 2, winner=0)
    finished_game(tmp_path, ("sam", "Alex"), 2, winner=0)
    c = rec.career(tmp_path)
    names = [p["name"] for p in c["players"]]
    assert len(names) == len(set(n.lower() for n in names)), names
    sam = next(p for p in c["players"] if p["name"].lower() == "sam")
    assert sam["games"] == 2


def test_career_ignores_empty_recordings(tmp_path):
    e = engine(tmp_path)                 # started, never played
    e.close()
    assert rec.career(tmp_path)["games"] == 0


def test_an_interrupted_game_is_found_and_a_finished_one_is_not(tmp_path):
    finished_game(tmp_path, ("Sam", "Alex"), 2, winner=0)
    assert rec.unfinished(tmp_path) is None

    e = engine(tmp_path, players=("Jo", "Kit"))
    shoot(e, BEFORE, AFTER, events(pocketed=[2], pockets={2: "TR"}, first=2))
    e.close()
    u = rec.unfinished(tmp_path)
    assert u is not None and u["players"] == ["Jo", "Kit"]


def test_resuming_restores_the_scores(tmp_path):
    e = engine(tmp_path, players=("Jo", "Kit"))
    for _ in range(3):
        shoot(e, BEFORE, AFTER, events(pocketed=[2], pockets={2: "TR"}, first=2))
    e.close()

    e2 = Engine(table=TABLE, hub=Hub(), recordings=tmp_path, idle_after=0)
    try:
        info = e2.resume_last()
        assert info is not None and info["shots"] == 3
        assert [p.name for p in e2.game.players] == ["Jo", "Kit"]
        assert e2.game.players[0].score == 3
    finally:
        e2.close()


def test_resuming_with_nothing_to_resume_is_not_an_error(tmp_path):
    e = Engine(table=TABLE, hub=Hub(), recordings=tmp_path, idle_after=0)
    try:
        assert e.resume_last() is None
    finally:
        e.close()


def test_resume_does_not_restore_the_table_only_the_score(tmp_path):
    """The balls are wherever they physically are now — same reasoning as undo."""
    e = engine(tmp_path, players=("Jo", "Kit"))
    shoot(e, BEFORE, AFTER, events(pocketed=[2], pockets={2: "TR"}, first=2))
    e.close()
    e2 = Engine(table=TABLE, hub=Hub(), recordings=tmp_path, idle_after=0)
    try:
        e2.resume_last()
        assert e2.detector.resting is None, "the detector must start from now"
    finally:
        e2.close()

"""Two cameras over one table.

The claim being tested is narrow and worth stating: a second camera buys
seeing past people and around glare, not better numbers. These tests check
that the fusion delivers that, and that it does not quietly invent balls or
merge two real ones into one.
"""
import math

from helpers import TABLE

from poolarena.types import Ball, Kind, TableState
from poolarena.vision.multi import MERGE_MM, CameraView, MultiPipeline


class FakePipeline:
    """Stands in for a real pipeline: just reports whatever we hand it."""

    def __init__(self, nadir):
        self.nadir = nadir
        self.cloth_learned = 0

    def process(self, color, depth=None):
        return color            # the "frame" IS the state, for the test

    def learn_cloth(self, frame):
        self.cloth_learned += 1


class FakeSource:
    def __init__(self, states):
        self.states = list(states)
        self.closed = False

    def read(self):
        if not self.states:
            return None
        return (self.states.pop(0), None)

    def close(self):
        self.closed = True


def state(balls, settled=True, obstructed=False, ts=1.0):
    return TableState(balls=balls, ts=ts, settled=settled, obstructed=obstructed)


def ball(n, x, y, conf=0.9, kind=Kind.SOLID):
    return Ball(number=n, x=x, y=y, kind=kind, radius=28.6, confidence=conf)


def rig(left_states, right_states):
    left = CameraView("left", FakeSource(left_states),
                      FakePipeline((TABLE.length * 0.25, TABLE.width / 2)))
    right = CameraView("right", FakeSource(right_states),
                       FakePipeline((TABLE.length * 0.75, TABLE.width / 2)))
    return MultiPipeline(TABLE, [left, right]), left, right


# --- the point of the exercise -------------------------------------------
def test_one_blocked_camera_does_not_blind_the_table():
    """A player leaning over one camera's view is the whole reason for two."""
    seen = [ball(3, 1800, 300), ball(0, 500, 600)]
    multi, _, _ = rig([state([], obstructed=True)], [state(seen)])
    out = multi.read()
    assert out.obstructed is False
    assert len(out.balls) == 2


def test_the_table_is_only_obstructed_when_nothing_can_see_it():
    multi, _, _ = rig([state([], obstructed=True)], [state([], obstructed=True)])
    out = multi.read()
    assert out.obstructed is True
    assert out.balls == []


def test_a_ball_only_one_camera_can_see_is_still_reported():
    """Glare, or a body in the way: one view loses it, the other does not."""
    multi, _, _ = rig([state([ball(0, 500, 600)])],
                      [state([ball(0, 500, 600), ball(7, 2000, 900)])])
    out = multi.read()
    assert sorted(b.number for b in out.balls) == [0, 7]


# --- fusion must not invent or destroy balls -----------------------------
def test_the_same_ball_from_two_views_becomes_one():
    multi, _, _ = rig([state([ball(3, 1000, 500)])],
                      [state([ball(3, 1012, 508)])])
    out = multi.read()
    assert len(out.balls) == 1
    b = out.balls[0]
    assert b.number == 3
    assert 1000 <= b.x <= 1012 and 500 <= b.y <= 508


def test_two_touching_balls_are_not_merged():
    """Balls in a rack are 57 mm apart, so the merge radius must stay under
    that or a cluster collapses into one ball."""
    assert MERGE_MM < 57.2
    multi, _, _ = rig([state([ball(1, 1000, 500), ball(2, 1058, 500)])],
                      [state([ball(1, 1002, 501), ball(2, 1060, 502)])])
    out = multi.read()
    assert len(out.balls) == 2


def test_one_camera_seeing_double_is_not_self_merged():
    """Two detections from the SAME camera are two balls, however close."""
    multi, _, _ = rig([state([ball(1, 1000, 500), ball(2, 1030, 500)])],
                      [state([])])
    out = multi.read()
    assert len(out.balls) == 2


# --- weighting ------------------------------------------------------------
def test_the_nearer_camera_pulls_the_merged_position():
    """A ball at the left end should be placed mostly by the left camera."""
    multi, _, _ = rig([state([ball(3, 500, 560, conf=0.9)])],
                      [state([ball(3, 540, 560, conf=0.9)])])
    out = multi.read()
    assert out.balls[0].x < 520, "the camera above it should dominate"


def test_agreement_raises_confidence_and_disagreement_does_not():
    multi, _, _ = rig([state([ball(3, 1000, 500, conf=0.6)])],
                      [state([ball(3, 1005, 502, conf=0.6)])])
    agreed = multi.read().balls[0]
    assert agreed.confidence > 0.6, "two cameras agreeing is worth something"

    multi2, _, _ = rig([state([ball(3, 1000, 500, conf=0.6)])],
                       [state([ball(9, 1005, 502, conf=0.5)])])
    mixed = multi2.read().balls[0]
    assert mixed.number == 3, "the more confident, better-placed camera names it"
    assert mixed.confidence <= 0.75


def test_weight_falls_off_with_distance_from_the_camera():
    _, left, _ = rig([], [])
    near = left.weight_at(*left.pipeline.nadir)
    far = left.weight_at(TABLE.length, TABLE.width)
    assert near > far * 2


# --- robustness -----------------------------------------------------------
def test_a_dead_camera_does_not_stop_the_table():
    multi, _, _ = rig([], [state([ball(3, 1000, 500)])])      # left returns None
    out = multi.read()
    assert len(out.balls) == 1
    assert multi.views[0].failures == 1


def test_every_camera_dead_reports_obstructed_rather_than_an_empty_table():
    """An empty table and a broken rig must not look the same: reporting no
    balls would score every ball as potted."""
    multi, _, _ = rig([], [])
    out = multi.read()
    assert out.obstructed is True
    assert out.settled is False


def test_settled_needs_every_working_camera_to_agree():
    multi, _, _ = rig([state([ball(3, 1000, 500)], settled=False)],
                      [state([ball(3, 1000, 500)], settled=True)])
    assert multi.read().settled is False


def test_status_and_close_cover_every_camera():
    multi, left, right = rig([state([ball(3, 1000, 500)])], [state([])])
    multi.read()
    st = multi.status()
    assert [s["name"] for s in st] == ["left", "right"]
    multi.close()
    assert left.source.closed and right.source.closed


def test_a_single_camera_still_works_through_the_same_path():
    one = CameraView("only", FakeSource([state([ball(3, 1000, 500)])]),
                     FakePipeline((1117.0, 559.0)))
    multi = MultiPipeline(TABLE, [one])
    assert len(multi.read().balls) == 1


# --- parallax -------------------------------------------------------------
# The maths is exact; whether it helps on your table is a question only your
# table can answer, which is why it ships off by default. See docs/HARDWARE.md.
class _Geom:
    """Just enough of a pipeline to exercise correct_parallax."""

    def __init__(self, height, nadir, table=TABLE):
        from poolarena.vision.pipeline import VisionPipeline
        self.correct = VisionPipeline.correct_parallax.__get__(self)
        self.camera_height_mm = height
        self.table = table
        self._nadir = nadir

    @property
    def nadir(self):
        return self._nadir


def test_parallax_is_exactly_undone():
    """Shift a point the way a camera does, then correct it, and it must land
    back where it started."""
    h, nadir = 2200.0, (1117.5, 559.0)
    g = _Geom(h, nadir)
    k = h / (h - TABLE.ball_radius)
    for true in [(300, 250), (2000, 180), (1117.5, 559.0), (2200, 1100)]:
        apparent = (nadir[0] + (true[0] - nadir[0]) * k,
                    nadir[1] + (true[1] - nadir[1]) * k)
        back = g.correct(*apparent)
        assert math.dist(back, true) < 1e-9, true


def test_a_ball_under_the_camera_is_not_moved():
    nadir = (1117.5, 559.0)
    g = _Geom(2200.0, nadir)
    assert g.correct(*nadir) == nadir


def test_correction_always_pulls_inward():
    g = _Geom(2200.0, (1117.5, 559.0))
    before = math.dist((2000.0, 180.0), (1117.5, 559.0))
    after = math.dist(g.correct(2000.0, 180.0), (1117.5, 559.0))
    assert after < before


def test_it_is_off_unless_a_height_is_configured():
    """Guessing a camera height would make positions worse, not better."""
    assert _Geom(0.0, (1117.5, 559.0)).correct(2000.0, 180.0) == (2000.0, 180.0)
    assert _Geom(40.0, (1117.5, 559.0)).correct(2000.0, 180.0) == (2000.0, 180.0)


def test_a_higher_camera_needs_less_correction():
    low = _Geom(1800.0, (1117.5, 559.0)).correct(2000.0, 180.0)
    high = _Geom(3000.0, (1117.5, 559.0)).correct(2000.0, 180.0)
    assert math.dist(low, (2000.0, 180.0)) > math.dist(high, (2000.0, 180.0))

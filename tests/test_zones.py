from poolarena.geometry import Table
from poolarena.zones import Zone, random_zones


def test_contains_circle_and_rect():
    c = Zone("a", x=1000, y=500, r=150)
    assert c.contains(1000, 500) and c.contains(1100, 500)
    assert not c.contains(1200, 500)
    r = Zone("b", shape="rect", x=1000, y=500, w=400, h=200)
    assert r.contains(1150, 560)
    assert not r.contains(1250, 500)


def test_crossed_by_catches_a_gap_between_samples():
    """A 30 fps trace jumps 100 mm a frame; the test must interpolate."""
    z = Zone("a", x=1000, y=500, r=60)
    coarse = [(500, 500), (1500, 500)]        # no sample inside the zone
    assert z.crossed_by(coarse)
    assert not z.crossed_by([(500, 100), (1500, 100)])


def test_random_zones_avoid_balls_and_each_other():
    t = Table("8ft")
    balls = [(500, 500), (1200, 300)]
    zs = random_zones(t, 3, radius=150, avoid=balls)
    assert len(zs) == 3
    for z in zs:
        assert 0 < z.x < t.length and 0 < z.y < t.width
        for bx, by in balls:
            assert ((z.x - bx) ** 2 + (z.y - by) ** 2) ** 0.5 >= 150 + 90 - 1e-6
    for i, a in enumerate(zs):
        for b in zs[i + 1:]:
            assert ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5 >= 150 * 2.2 - 1e-6

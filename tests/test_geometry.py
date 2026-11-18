import math

from poolarena.geometry import (Calibration, Table, cut_angle, ghost_ball,
                                homography, apply_h, path_blocked, shot_candidates)


def test_table_sizes():
    assert Table("9ft").length == 2540
    assert Table("8ft").width == 1118
    assert Table(size="custom", length=2000, width=1000).length == 2000


def test_homography_roundtrip():
    t = Table("8ft")
    corners = [(120, 80), (1800, 95), (1830, 980), (100, 960)]
    c = Calibration.from_corners(corners, t)
    assert c.error_mm < 1e-6
    # the four corners map to the four table corners
    got = c.to_table(corners)
    for (gx, gy), (ex, ey) in zip(got, [(0, 0), (t.length, 0), (t.length, t.width), (0, t.width)]):
        assert abs(gx - ex) < 1e-6 and abs(gy - ey) < 1e-6
    # and the inverse comes back
    back = c.to_image(got)
    for (bx, by), (ex, ey) in zip(back, corners):
        assert abs(bx - ex) < 1e-6 and abs(by - ey) < 1e-6


def test_homography_is_not_affine():
    """A real camera sees a trapezoid; the solver must handle perspective."""
    H = homography([(0, 0), (10, 0), (10, 10), (0, 10)],
                   [(0, 0), (100, 0), (80, 90), (20, 90)])
    mid = apply_h(H, [(5, 5)])[0]
    assert mid != (50, 45)              # affine would give exactly the centroid
    assert 40 < mid[0] < 60


def test_pocket_capture():
    t = Table("8ft")
    assert t.in_pocket(0, 0) == "TL"
    assert t.in_pocket(t.length, t.width) == "BR"
    assert t.in_pocket(t.length / 2, 0) == "TM"
    assert t.in_pocket(t.length / 2, t.width / 2) is None
    # a ball sitting in the jaws counts; one a foot away does not
    assert t.in_pocket(60, 40) == "TL"
    assert t.in_pocket(400, 300) is None


def test_ghost_ball_sits_behind_the_object_ball():
    target, pocket = (1000.0, 500.0), (2235.0, 0.0)
    g = ghost_ball((200, 900), target, pocket, r=28.6)
    # the ghost is one ball diameter from the target, away from the pocket
    assert abs(math.dist(g, target) - 57.2) < 1e-6
    assert math.dist(g, pocket) > math.dist(target, pocket)


def test_cut_angle_straight_and_square():
    assert cut_angle((0, 500), (1000, 500), (2000, 500)) < 1e-6
    assert abs(cut_angle((1000, 0), (1000, 500), (2000, 500)) - 90) < 1e-6


def test_path_blocked():
    assert path_blocked((0, 500), (1000, 500), [(500, 500)])
    assert path_blocked((0, 500), (1000, 500), [(500, 540)])      # clipping it
    assert not path_blocked((0, 500), (1000, 500), [(500, 700)])


def test_shot_candidates_ranks_the_easy_pot_first():
    t = Table("8ft")
    cue, target = (400.0, 600.0), (1800.0, 300.0)
    cands = shot_candidates(cue, target, t, blockers=[cue, target])
    assert cands, "a ball near the top rail must have at least one pot"
    assert cands[0]["pocket"] == "TR"
    assert cands[0]["cut_angle"] < 45
    assert all(c["cut_angle"] < 85 for c in cands)


def test_shot_candidates_marks_blockers():
    t = Table("8ft")
    cue, target = (400.0, 600.0), (1800.0, 300.0)
    blocker = (2000.0, 180.0)        # parked on the line to the top-right
    cands = shot_candidates(cue, target, t, blockers=[cue, target, blocker])
    tr = next(c for c in cands if c["pocket"] == "TR")
    assert tr["blocked"]

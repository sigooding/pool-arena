from helpers import TABLE, events, state

from poolarena.rules import get_game
from poolarena.rules.base import ShotContext


def play(game, before, after, ev):
    ctx = ShotContext(before=before, after=after, events=ev, table=TABLE,
                      shooter=game.turn)
    return game.apply(ctx)


def eight_ball(**kw):
    g = get_game("8ball")(players=["A", "B"], table=TABLE, options=kw)
    g.broken = True            # skip the break for rule tests
    return g


# --- 8-ball ---------------------------------------------------------------
def test_open_table_first_pot_assigns_groups():
    g = eight_ball()
    before = state(b0=(400, 600), b3=(1800, 300), b11=(900, 200), b8=(1200, 500))
    after = state(b0=(1600, 350), b11=(900, 200), b8=(1200, 500))
    res = play(g, before, after, events(pocketed=[3], pockets={3: "TR"}, first=3))
    assert g.players[0].group == "solids"
    assert g.players[1].group == "stripes"
    assert not res.turn_passes
    assert not res.foul


def test_hitting_the_wrong_group_is_a_foul_with_ball_in_hand():
    g = eight_ball()
    g.assign(0, "solids")
    before = state(b0=(400, 600), b3=(1800, 300), b11=(900, 200), b8=(1200, 500))
    res = play(g, before, before, events(first=11, rails=1))
    assert res.foul and "11" in res.foul
    assert res.turn_passes and res.ball_in_hand
    assert g.turn == 1


def test_no_rail_and_no_pot_is_a_foul():
    g = eight_ball()
    g.assign(0, "solids")
    before = state(b0=(400, 600), b3=(1800, 300), b8=(1200, 500))
    res = play(g, before, before, events(first=3, rails=0))
    assert res.foul == "no rail after contact"


def test_eight_early_loses():
    g = eight_ball()
    g.assign(0, "solids")
    before = state(b0=(400, 600), b3=(1800, 300), b8=(1200, 500))
    after = state(b0=(400, 600), b3=(1800, 300))
    res = play(g, before, after, events(pocketed=[8], pockets={8: "BM"}, first=8))
    assert res.game_over and res.winner == 1


def test_eight_when_on_it_wins_in_the_called_pocket():
    g = eight_ball(call_pocket=True)
    g.assign(0, "solids")
    g.call("TR")
    before = state(b0=(400, 600), b8=(1800, 300), b11=(900, 200))
    after = state(b0=(1600, 350), b11=(900, 200))
    res = play(g, before, after, events(pocketed=[8], pockets={8: "TR"}, first=8))
    assert res.game_over and res.winner == 0


def test_eight_in_the_wrong_pocket_loses():
    g = eight_ball(call_pocket=True)
    g.assign(0, "solids")
    g.call("TR")
    before = state(b0=(400, 600), b8=(1800, 300), b11=(900, 200))
    after = state(b0=(1600, 350), b11=(900, 200))
    res = play(g, before, after, events(pocketed=[8], pockets={8: "BL"}, first=8))
    assert res.game_over and res.winner == 1


def test_scratch_passes_the_turn_with_ball_in_hand():
    g = eight_ball()
    g.assign(0, "solids")
    before = state(b0=(400, 600), b3=(1800, 300), b8=(1200, 500))
    after = state(b3=(1800, 300), b8=(1200, 500))
    res = play(g, before, after, events(scratch=True, first=3, pockets={0: "BM"}))
    assert res.foul == "scratch"
    assert res.ball_in_hand and g.turn == 1


def test_illegal_break_needs_four_rails():
    g = get_game("8ball")(players=["A", "B"], table=TABLE)
    before = state(b0=(400, 600), b1=(1800, 300))
    res = play(g, before, before, events(first=1, rails=2))
    assert res.foul and "break" in res.foul


# --- 9-ball ---------------------------------------------------------------
def test_nine_ball_must_hit_the_lowest():
    g = get_game("9ball")(players=["A", "B"], table=TABLE)
    before = state(b0=(400, 600), b2=(1800, 300), b9=(900, 200))
    res = play(g, before, before, events(first=9, rails=1))
    assert res.foul and "needed the 2" in res.foul
    assert g.turn == 1


def test_nine_ball_combo_on_the_nine_wins():
    g = get_game("9ball")(players=["A", "B"], table=TABLE)
    before = state(b0=(400, 600), b2=(1800, 300), b9=(1900, 200))
    after = state(b0=(1000, 400), b2=(1800, 300))
    res = play(g, before, after, events(pocketed=[9], pockets={9: "TR"}, first=2))
    assert res.game_over and res.winner == 0


def test_nine_ball_on_a_foul_does_not_win():
    g = get_game("9ball")(players=["A", "B"], table=TABLE)
    before = state(b0=(400, 600), b2=(1800, 300), b9=(1900, 200))
    after = state(b0=(400, 600), b2=(1800, 300))
    res = play(g, before, after, events(pocketed=[9], pockets={9: "TR"}, first=9))
    assert not res.game_over
    assert res.foul


def test_nine_ball_pot_keeps_the_turn():
    g = get_game("9ball")(players=["A", "B"], table=TABLE)
    before = state(b0=(400, 600), b2=(1800, 300), b9=(900, 200))
    after = state(b0=(1600, 350), b9=(900, 200))
    res = play(g, before, after, events(pocketed=[2], pockets={2: "TR"}, first=2))
    assert not res.turn_passes and g.turn == 0


# --- cut-throat -----------------------------------------------------------
def test_cutthroat_eliminates_and_ends():
    g = get_game("cutthroat")(players=["A", "B", "C"], table=TABLE)
    before = state(b0=(400, 600), b5=(1800, 300), b11=(900, 200))
    after = state(b0=(1600, 350), b11=(900, 200))
    res = play(g, before, after, events(pocketed=[5], pockets={5: "TR"}, first=5))
    # A owns 1-5; only the 5 was left of A's group on the table, so A is out
    assert g.players[0].out
    assert res.game_over is False or res.winner is not None


def test_cutthroat_hitting_your_own_ball_is_a_foul():
    g = get_game("cutthroat")(players=["A", "B", "C"], table=TABLE)
    before = state(b0=(400, 600), b3=(1800, 300), b11=(900, 200))
    res = play(g, before, before, events(first=3, rails=1))
    assert res.foul and "your own" in res.foul


# --- projection-native ----------------------------------------------------
def test_hotspots_scores_a_zone_the_ball_rolled_through():
    g = get_game("hotspots")(players=["A"], table=TABLE, options={"seed": 1})
    before = state(b0=(400, 600), b3=(1200, 600))
    g.on_turn_start(before)                       # lights the zones
    z = g.zones[0]
    z.x, z.y, z.points = 1500.0, 600.0, 3         # park a zone on the ball's path
    after = state(b0=(900, 600))
    trace = {3: [(1200, 600), (1500, 600), (2235, 600)]}
    res = play(g, before, after, events(pocketed=[3], pockets={3: "BR"}, first=3,
                                        trace=trace))
    assert g.players[0].score == 4                # 1 for the pot + 3 for the zone
    assert any(e.name == "zone_hit" for e in res.effects)


def test_hotspots_ignores_a_zone_the_ball_missed():
    g = get_game("hotspots")(players=["A"], table=TABLE, options={"seed": 1})
    before = state(b0=(400, 600), b3=(1200, 600))
    g.on_turn_start(before)
    for z in g.zones:
        z.x, z.y = 300.0, 150.0                   # nowhere near the path
        z.r = 80.0
    after = state(b0=(900, 600))
    trace = {3: [(1200, 600), (2235, 600)]}
    res = play(g, before, after, events(pocketed=[3], pockets={3: "BR"}, first=3,
                                        trace=trace))
    assert g.players[0].score == 1
    assert not any(e.name == "zone_hit" for e in res.effects)


def test_roulette_only_scores_the_named_pocket():
    g = get_game("roulette")(players=["A"], table=TABLE, options={"seed": 3})
    g.on_start()
    g.pocket = "TR"
    before = state(b0=(400, 600), b3=(1800, 300))
    after = state(b0=(1600, 350))
    res = play(g, before, after, events(pocketed=[3], pockets={3: "BL"}, first=3))
    assert g.players[0].score == 0
    assert "wrong pocket" in res.message

    g.pocket = "TR"
    res = play(g, before, after, events(pocketed=[3], pockets={3: "TR"}, first=3))
    assert g.players[0].score == 1


def test_killer_costs_a_life_on_a_miss():
    g = get_game("killer")(players=["A", "B"], table=TABLE, options={"lives": 2})
    before = state(b0=(400, 600), b3=(1800, 300))
    play(g, before, before, events(first=3, rails=1))
    assert g.players[0].lives == 1
    assert g.turn == 1


def test_position_drill_grades_distance():
    g = get_game("position")(players=["A"], table=TABLE,
                             options={"seed": 2, "shots": 5, "show_aim": False})
    before = state(b0=(400, 600), b3=(1800, 300))
    g.on_turn_start(before)
    g.zone.x, g.zone.y, g.zone.r = 1000.0, 600.0, 170.0
    after = state(b0=(1010, 605))                 # stopped dead in the ring
    res = play(g, before, after, events(pocketed=[3], pockets={3: "TR"}, first=3))
    assert g.players[0].score >= 9
    assert "in the ring" in res.message

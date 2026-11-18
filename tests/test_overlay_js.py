"""The overlay's effect timings, checked by actually running the JavaScript.

Worth the awkwardness of shelling out to node: the bug these guard against
was invisible to any amount of reading. Subclasses declare

    defaultDuration = 2400;

as a class field, and class fields are installed *after* super() returns, so
the base constructor read `undefined` and every effect in the file — a 400ms
table flash, a 4-second firework — quietly ran for exactly one second. The
source looked completely correct. Only construction shows it.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "overlay" / "src" / "effects.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node is not installed")


def effect_durations() -> dict[str, dict]:
    """Construct one of every exported effect and report dur/persist."""
    script = """
    const scene = {
      pockets: () => ({ tl: [0, 0], tr: [2540, 0], bl: [0, 1270], br: [2540, 1270] }),
      balls: [], prevBalls: [], table: { L: 2540, W: 1270 },
    };
    import(process.argv[1]).then((m) => {
      const out = {};
      for (const [name, Cls] of Object.entries(m)) {
        if (typeof Cls !== 'function' || !/^[A-Z]/.test(name)) continue;
        let fx;
        try { fx = new Cls({}, scene); } catch { continue; }
        if (!('dur' in fx)) continue;
        out[name] = { dur: fx.dur, persist: fx.persist };
      }
      process.stdout.write(JSON.stringify(out));
    });
    """
    done = subprocess.run(["node", "-e", script, str(SRC)],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_effects_do_not_all_last_exactly_one_second():
    """The symptom of the field-ordering bug, stated as its own test.

    One second is the base class's fallback. If everything lands on it, the
    per-effect numbers are being read too early again.
    """
    durs = effect_durations()
    assert durs, "no effects were constructed — the harness itself is broken"
    timed = [v["dur"] for v in durs.values() if not v["persist"]]
    assert len(timed) > 5, "expected a good number of timed effects to check"
    # Counting rather than just asking for variety: when the bug was live one
    # effect still differed, because it happened to pass its duration as an
    # argument. Everything else had collapsed onto the fallback.
    fallback = [d for d in timed if d == 1.0]
    assert len(fallback) < len(timed) / 2, (
        f"{len(fallback)} of {len(timed)} effects sit on the 1s fallback; "
        "defaultDuration is being read before the subclass sets it")


@pytest.mark.parametrize("name,seconds", [
    ("TableFlash", 0.4),
    ("Lightning", 0.6),
    ("PocketReject", 0.7),
    ("PocketGlow", 0.9),
    ("Explosion", 1.4),
    ("Banner", 2.4),
    ("Spotlight", 2.6),
    ("Fireworks", 4.0),
])
def test_each_effect_runs_for_the_length_it_declares(name, seconds):
    durs = effect_durations()
    assert name in durs, f"{name} is no longer exported"
    assert durs[name]["dur"] == pytest.approx(seconds), \
        f"{name} runs {durs[name]['dur']}s, declared {seconds}s"


def test_a_zero_duration_effect_waits_to_be_cleared():
    """dur 0 means "until something clears it" — it must not expire at once."""
    durs = effect_durations()
    zero = {k: v for k, v in durs.items() if v["dur"] == 0}
    assert zero, "expected the guide effects (aim line, zones, ...) to be open-ended"
    for name, v in zero.items():
        assert v["persist"], f"{name} has no duration and no persist: it dies on frame one"

"""Pre-flight: does this table, this camera and this light actually work?

Everything above the vision layer is tested to death and none of it is the
reason a first setup fails. What fails is the chain from the lens to a list
of balls, and when it does the symptom is always the same — "it isn't
scoring" — with no clue which link broke.

So this walks the chain in order and puts a number on each link. The numbers
matter more than the verdicts: run it once with the Kinect and once without
and the two reports say which camera to keep, rather than leaving it to how
it felt.
"""
from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .geometry import Table
from .types import TableState

OK, WARN, FAIL, SKIP = "ok", "warn", "fail", "skip"
MARK = {OK: "ok  ", WARN: "warn", FAIL: "FAIL", SKIP: "--  "}


@dataclass
class Check:
    name: str
    status: str
    detail: str
    #: what to do about it, printed only when it is not ok
    remedy: str = ""
    numbers: dict[str, Any] = field(default_factory=dict)


def _fmt(v: Any) -> str:
    return f"{v:.1f}" if isinstance(v, float) else str(v)


class Doctor:
    """Runs the checks against an already-built rig.

    Takes the rig rather than building one so it can be pointed at a live
    camera, a recorded video, or a synthetic source in a test.
    """

    def __init__(self, table: Table, rig, expected_balls: int,
                 frames: int = 60) -> None:
        self.table = table
        self.rig = rig
        self.expected = expected_balls
        self.frames = frames
        self.checks: list[Check] = []

    # --- the run -----------------------------------------------------------
    def run(self) -> list[Check]:
        states, elapsed, failures = self._sample()
        self.checks.append(self._check_source(states, elapsed, failures))
        if not states:
            # Nothing downstream can be judged without frames, and saying
            # "no balls found" when the camera never opened is a lie that
            # sends people tuning the wrong thing.
            for name in ("calibration", "cloth", "ball size", "balls",
                         "stability", "colour separation", "view"):
                self.checks.append(Check(name, SKIP, "no frames to judge"))
            return self.checks
        self.checks.append(self._check_calibration())
        self.checks.append(self._check_cloth())
        self.checks.append(self._check_ball_size())
        self.checks.append(self._check_balls(states))
        self.checks.append(self._check_stability(states))
        self.checks.append(self._check_separation(states))
        self.checks.append(self._check_view(states))
        return self.checks

    def _sample(self) -> tuple[list[TableState], float, int]:
        states: list[TableState] = []
        failures = 0
        t0 = time.time()
        for _ in range(self.frames):
            try:
                st = self.rig.read()
            except Exception:
                failures += 1
                continue
            if st is None:
                failures += 1
                continue
            states.append(st)
        return states, time.time() - t0, failures

    # --- the links ---------------------------------------------------------
    def _check_source(self, states, elapsed, failures) -> Check:
        got = len(states)
        if not got:
            return Check("source", FAIL,
                         f"no frames at all ({failures} failed reads)",
                         "Check the camera is plugged in and not held open by "
                         "another program, and that --source names it. "
                         "`run --source cam:0` for the first USB camera.")
        fps = got / elapsed if elapsed > 0 else 0.0
        nums = {"frames": got, "fps": fps, "dropped": failures}
        if fps > 120:
            # A file or a synthetic source hands frames over as fast as they
            # can be read, so the rate says nothing about a camera. Better to
            # say that than to print six figures and look broken.
            return Check("source", OK,
                         f"{got} frames, faster than real time "
                         f"(a file or simulated source, not a camera)",
                         numbers=nums)
        if fps < 10:
            return Check("source", FAIL, f"{fps:.1f} fps over {got} frames",
                         "Under about 10 fps the detector cannot tell a shot "
                         "from a jump. Drop the resolution, or use a USB 3 "
                         "port if this is the Kinect.", nums)
        if fps < 24 or failures:
            return Check("source", WARN,
                         f"{fps:.1f} fps, {failures} dropped",
                         "Workable but not comfortable. 30 fps is what the "
                         "shot detector was tuned against.", nums)
        return Check("source", OK, f"{fps:.1f} fps, {got} frames, none dropped",
                     numbers=nums)

    def _pipelines(self) -> list:
        """The colour pipelines, unwrapped.

        ColourAndDepth wraps a VisionPipeline rather than subclassing it, so
        the thing holding the calibration and the cloth model is one level
        down when depth is in use.
        """
        out = []
        for v in getattr(self.rig, "views", []):
            pipe = getattr(v, "pipeline", None)
            seen = 0
            while pipe is not None and not hasattr(pipe, "calib") and seen < 4:
                pipe = getattr(pipe, "colour", None) or getattr(pipe, "inner", None)
                seen += 1
            if pipe is not None:
                out.append(pipe)
        return out

    def _check_calibration(self) -> Check:
        """A homography that does not match the table's shape is the single
        most common silent failure: everything works, every position is
        wrong, and nothing says so."""
        worst = None
        for pipe in self._pipelines():
            calib = getattr(pipe, "calib", None)
            err = getattr(calib, "error_mm", None)
            if err is None:
                continue
            if worst is None or err > worst[1]:
                worst = (getattr(pipe, "name", "camera"), err)
        if worst is None:
            return Check("calibration", SKIP, "no calibration to inspect")
        name, err = worst
        if len(name) > 24:                      # a video: path, not a camera
            name = "..." + name[-21:]
        nums = {"worst_rms_mm": err, "camera": name}
        if err > 15:
            return Check("calibration", FAIL,
                         f"{name}: {err:.1f} mm rms corner error",
                         "That is a third of a ball. Re-run `calibrate`, and "
                         "print the ArUco markers (`markers`) rather than "
                         "clicking corners — they land around 1 mm against "
                         "8-12 mm by eye.", nums)
        if err > 6:
            return Check("calibration", WARN, f"{name}: {err:.1f} mm rms",
                         "Good enough to play. The printed markers would "
                         "take it under 2 mm if pots near the jaws read "
                         "wrong.", nums)
        return Check("calibration", OK, f"{name}: {err:.1f} mm rms",
                     numbers=nums)

    def _check_cloth(self) -> Check:
        """How much of the warped table reads as cloth.

        This is the number that decides whether anything else can work: the
        detector finds balls as the holes in the cloth, so if the cloth model
        is wrong there are no holes to find — or the whole table is one.
        """
        fracs = []
        for pipe in self._pipelines():
            warped = getattr(pipe, "last_warped", None)
            det = getattr(pipe, "detector", None)
            if warped is None or det is None or not hasattr(det, "cloth_mask"):
                continue
            try:
                mask = det.cloth_mask(warped)
            except Exception:
                continue
            # cloth_mask marks what is NOT cloth — it is the ball-finding
            # mask. Reading it the other way up called a perfectly healthy
            # table (16 balls, about 1% of the surface) "only 1% reads as
            # cloth" and sent you tuning a thing that was already right.
            fracs.append(1.0 - float(np.count_nonzero(mask)) / mask.size)
        if not fracs:
            return Check("cloth", SKIP, "detector does not model the cloth "
                                        "(YOLO finds balls directly)")
        frac = min(fracs)
        nums = {"cloth_fraction": frac}
        if frac < 0.55:
            return Check("cloth", FAIL, f"only {frac * 100:.0f}% reads as cloth",
                         "The cloth colour in config/detector.json does not "
                         "match what the camera sees — usually the lighting, "
                         "not the cloth. Point `--cloth` at the colour the "
                         "camera reports, or use `run --learn-cloth` on an "
                         "empty table.", nums)
        if frac < 0.75:
            return Check("cloth", WARN, f"{frac * 100:.0f}% reads as cloth",
                         "Some of the table is being read as not-cloth — "
                         "usually shadow under the light. Expect phantom "
                         "balls in the dark patches.", nums)
        return Check("cloth", OK, f"{frac * 100:.0f}% reads as cloth",
                     numbers=nums)

    def _check_ball_size(self) -> Check:
        """Are the balls on the table the size the config thinks they are?

        Measured here from the mask directly rather than asked of the
        detector, because the detector does not measure: it is told how big a
        ball is and takes each one's colour from a patch that size. Tell it
        28.6 mm when the balls are 25.4 and every patch picks up a ring of
        cloth around the ball, which drags the hue about and can push a solid
        over the white threshold that means "cue ball". Nothing errors. The
        scoring just gets worse.

        Easy to get wrong with two sets in the cupboard: American balls are
        2.25 inches and English are 2, which is a tenth off the diameter.
        """
        best = None
        for pipe in self._pipelines():
            warped = getattr(pipe, "last_warped", None)
            det = getattr(pipe, "detector", None)
            ppm = float(getattr(pipe, "px_per_mm", 0.5)) or 0.5
            if warped is None or det is None or not hasattr(det, "cloth_mask"):
                continue
            try:
                import cv2
                mask = det.cloth_mask(warped)
                n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
            except Exception:
                continue
            radii = []
            for i in range(1, n):
                area = float(stats[i, cv2.CC_STAT_AREA])
                r_mm = (area / np.pi) ** 0.5 / ppm
                # Plausible single balls only: smaller is speckle, larger is
                # two balls touching and would drag the median up.
                if 12.0 < r_mm < 40.0:
                    radii.append(r_mm)
            if len(radii) >= 4:
                best = (getattr(pipe, "name", "camera"), radii)
                break
        if best is None:
            return Check("ball size", SKIP, "not enough clean blobs to measure")

        name, radii = best
        radii.sort()
        # The mask is opened and closed with a 5x5 kernel before anything
        # counts it, which shaves a pixel or so off every blob — about 4% of
        # a ball's radius at the default warp. Measured on rendered balls of
        # a known size; see tests/test_doctor.py.
        seen = radii[len(radii) // 2] * 1.04
        want = float(self.table.ball_radius)

        # Which standard set this is, rather than how many millimetres it is.
        # The two sets differ by 13%, comfortably more than this measurement
        # is out by, so "are you on the wrong set?" is answerable even though
        # "is it exactly 25.4?" is not — and the wrong set is what actually
        # costs you.
        STANDARD = {25.4: "English (2 in)", 28.6: "American (2.25 in)"}
        nearest = min(STANDARD, key=lambda r: abs(seen - r))
        nums = {"measured_radius_mm": round(seen, 1), "configured_mm": want,
                "looks_like": STANDARD[nearest], "blobs": len(radii)}

        if abs(nearest - want) > 0.5:
            return Check("ball size", FAIL,
                         f"balls measure about {seen:.1f} mm radius; the "
                         f"config says {want:.1f} mm",
                         f"That is a set of {STANDARD[nearest]} balls against "
                         f"a config for the other one. Set \"ball_radius\" in "
                         f"config/table.json to {nearest}. Left wrong, every "
                         f"ball's colour is read from a patch the wrong size, "
                         f"which quietly makes the scoring worse without "
                         f"anything looking broken.", nums)
        if abs(seen - want) / want > 0.10:
            return Check("ball size", WARN,
                         f"balls measure about {seen:.1f} mm radius against "
                         f"{want:.1f} mm configured",
                         "The right set, but further out than expected. Worth "
                         "a caliper on one ball, and the real number in "
                         '"ball_radius".', nums)
        return Check("ball size", OK,
                     f"about {seen:.1f} mm radius — {STANDARD[nearest]}, "
                     f"as configured", numbers=nums)

    def _check_balls(self, states) -> Check:
        counts = [len(s.balls) for s in states]
        if not counts:
            return Check("balls", FAIL, "no readings")
        typical = int(statistics.median(counts))
        conf = [b.confidence for s in states for b in s.balls
                if b.confidence is not None]
        mean_conf = statistics.fmean(conf) if conf else 1.0
        nums = {"found": typical, "expected": self.expected,
                "spread": f"{min(counts)}-{max(counts)}",
                "mean_confidence": mean_conf}
        if typical == 0:
            return Check("balls", FAIL, "no balls found at all",
                         "If the cloth check passed, the ball radius is "
                         "probably wrong for this camera height. Check "
                         "`ball_radius_mm` and the table size.", nums)
        miss = self.expected - typical
        if miss > 1:
            return Check("balls", FAIL,
                         f"{typical} of {self.expected}, "
                         f"range {min(counts)}-{max(counts)}",
                         "Missing balls get scored as potted. Which ones are "
                         "missing matters: if it is always the same ones, it "
                         "is colour; if it moves around, it is shadow.", nums)
        # min(), not just the median: a rack that reads 16, 16, 15, 16 is
        # the exact condition that scores a phantom pot. The median hides it.
        if (miss or min(counts) < self.expected or max(counts) > self.expected
                or mean_conf < 0.6):
            steady = min(counts) == max(counts)
            why = ("One ball is never found. It is the same one every frame, "
                   "so it is colour, not shadow — find which and look at it "
                   "under the light."
                   if steady and miss == 1 else
                   "A frame that reads short is a frame that could score a "
                   "phantom pot. The detector guards against it, but it will "
                   "refuse to score the shot rather than get it wrong, so "
                   "this costs you shots either way.")
            return Check("balls", WARN,
                         f"{typical} of {self.expected}"
                         + ("" if steady
                            else f", range {min(counts)}-{max(counts)}")
                         + f", confidence {mean_conf:.2f}",
                         why, nums)
        return Check("balls", OK,
                     f"all {typical}, confidence {mean_conf:.2f}", numbers=nums)

    def _check_stability(self, states) -> Check:
        """How far a still ball wanders between frames.

        The number that decides whether a quiet table looks quiet. Jitter
        above the detector's movement threshold means phantom shots all
        evening; well under it means the table reads as settled and the
        scoring works.
        """
        if len(states) < 5:
            return Check("stability", SKIP, "too few frames")
        tracks: dict[int, list[tuple[float, float]]] = {}
        for s in states:
            for b in s.balls:
                tracks.setdefault(b.number, []).append((b.x, b.y))
        spreads = []
        for pts in tracks.values():
            if len(pts) < 5:
                continue
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            cx, cy = statistics.fmean(xs), statistics.fmean(ys)
            spreads.append(max(((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                               for x, y in zip(xs, ys)))
        if not spreads:
            return Check("stability", SKIP, "no ball seen for long enough")
        worst = max(spreads)
        typical = statistics.fmean(spreads)
        nums = {"worst_mm": worst, "mean_mm": typical}
        if worst > 8:
            return Check("stability", FAIL,
                         f"a still ball wanders {worst:.1f} mm "
                         f"(mean {typical:.1f})",
                         "The table will never read as settled, so shots will "
                         "not resolve. More light is the usual answer; a "
                         "longer exposure or lower gain is the next one.",
                         nums)
        if worst > 3:
            return Check("stability", WARN,
                         f"a still ball wanders {worst:.1f} mm "
                         f"(mean {typical:.1f})",
                         "Playable, but close enough to the movement "
                         "threshold to be worth more light.", nums)
        return Check("stability", OK,
                     f"a still ball holds within {worst:.1f} mm", numbers=nums)

    def _check_separation(self, states) -> Check:
        """Can the colours actually be told apart under this light?"""
        # Across every frame, not just the last: a ball that is read wrong
        # one frame in five is still a ball that will be read wrong during
        # somebody's shot, and the last frame alone would call that clean.
        kinds: dict[str, int] = {}
        for b in states[-1].balls:
            k = getattr(b.kind, "value", str(b.kind))
            kinds[k] = kinds.get(k, 0) + 1
        worst_unknown = 0
        for st in states:
            n = sum(1 for b in st.balls
                    if getattr(b.kind, "value", str(b.kind)) == "unknown")
            worst_unknown = max(worst_unknown, n)
        unknown = worst_unknown
        nums = {"kinds": kinds, "worst_unidentified": unknown}
        if unknown > 1:
            return Check("colour separation", FAIL,
                         f"up to {unknown} balls could not be identified",
                         "Under this light the colours are not far enough "
                         "apart. More even light helps most; failing that, "
                         "the YOLO detector identifies by shape and marking "
                         "rather than colour.", nums)
        if unknown:
            return Check("colour separation", WARN,
                         "one ball could not be identified in some frames",
                         "Usually the one sitting in the light's own shadow.",
                         nums)
        return Check("colour separation", OK,
                     ", ".join(f"{v} {k}" for k, v in sorted(kinds.items())),
                     numbers=nums)

    def _check_view(self, states) -> Check:
        obstructed = sum(1 for s in states if s.obstructed)
        frac = obstructed / len(states)
        nums = {"obstructed_frames": obstructed, "of": len(states)}
        if frac > 0.5:
            return Check("view", FAIL,
                         f"{frac * 100:.0f}% of frames read as obstructed",
                         "Something is over the table in most frames — if "
                         "nobody is standing there, the light itself is "
                         "probably in shot. Move the camera or raise the "
                         "light.", nums)
        if frac > 0.1:
            return Check("view", WARN,
                         f"{frac * 100:.0f}% of frames read as obstructed",
                         "Fine if someone was leaning over the table while "
                         "this ran. Worth a second look if not.", nums)
        return Check("view", OK, "clear", numbers=nums)


# --- reporting ------------------------------------------------------------
def report(checks: list[Check], title: str = "") -> str:
    lines = []
    if title:
        lines += [title, "=" * len(title), ""]
    width = max(len(c.name) for c in checks)
    for c in checks:
        lines.append(f"  [{MARK[c.status]}] {c.name.ljust(width)}  {c.detail}")
        if c.status in (FAIL, WARN) and c.remedy:
            for para in _wrap(c.remedy, 66):
                lines.append(f"           {' ' * width}  {para}")
    worst = (FAIL if any(c.status == FAIL for c in checks)
             else WARN if any(c.status == WARN for c in checks) else OK)
    lines.append("")
    lines.append({
        FAIL: "  Not ready. Fix the FAIL lines above — the rest cannot be "
              "trusted until they pass.",
        WARN: "  Playable. The warnings are worth an hour before a night of "
              "it, but nothing here stops a game.",
        OK: "  Ready. Nothing to fix.",
    }[worst])
    return "\n".join(lines)


def _wrap(text: str, width: int) -> list[str]:
    out, line = [], ""
    for word in text.split():
        if len(line) + len(word) + 1 > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        out.append(line)
    return out

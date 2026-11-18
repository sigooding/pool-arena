"""Command line entry point.

    python -m poolarena demo                 # no hardware: simulated table
    python -m poolarena run --source kinect  # the real thing
    python -m poolarena calibrate --source kinect
    python -m poolarena games
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
import webbrowser
from pathlib import Path

from .engine import Engine
from .geometry import Calibration, Table
from .rules import available
from .server.ws import Hub, serve
from .types import TableState

ROOT = Path(__file__).resolve().parent.parent
OVERLAY = ROOT / "overlay"
CONFIG = ROOT / "config"


def load_table(args) -> Table:
    cfg_path = Path(args.config) if args.config else CONFIG / "table.json"
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text())
        t = Table(size=cfg.get("size", "8ft"),
                  length=cfg.get("length", 0), width=cfg.get("width", 0),
                  ball_radius=cfg.get("ball_radius", 28.6),
                  pocket_capture=cfg.get("pocket_capture", 70.0))
    else:
        t = Table(size=args.size)
    if getattr(args, "size", None) and args.size != t.size and not args.config:
        t = Table(size=args.size)
    return t


def start_server(engine_hub: Hub, table: Table, port: int, open_browser: bool):
    routes = {
        "/api/games": lambda: {"games": available()},
        "/api/table": lambda: table.to_json(),
    }
    httpd = serve(engine_hub, OVERLAY, port=port, http_routes=routes)
    url = f"http://localhost:{port}/"
    print(f"  projector   {url}")
    print(f"  scoreboard  {url}scoreboard.html")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    return httpd


# --- demo ----------------------------------------------------------------
def cmd_demo(args) -> int:
    """Run the whole stack against the simulator.

    This is the development loop: every effect, every rule and the whole
    websocket path get exercised with no camera, no projector and no table.
    """
    from .sim import FakeTable, auto_shot

    table = load_table(args)
    hub = Hub()
    engine = Engine(table=table, hub=hub,
                    log_path=Path(args.log) if args.log else None)
    start_server(hub, table, args.port, not args.no_browser)

    sim = FakeTable(table=table, rng=random.Random(args.seed))
    sim.rack("9ball" if args.game == "9ball" else "8ball")
    engine.detector.reset(sim.state())
    engine.start_game(args.game, players=[p.strip() for p in args.players.split(",")])

    print(f"\n  demo running: {args.game}, {args.fps} fps, skill {args.skill}")
    print("  ctrl-c to stop\n")

    frame_time = 1.0 / args.fps

    def rack_for(game_name: str) -> None:
        sim.rack("9ball" if game_name == "9ball" else "8ball")

    def current_game() -> str:
        # Whatever is live, which may have been chosen from the tablet rather
        # than on the command line.
        return engine.game.name if engine.game else args.game

    def current_players() -> list[str]:
        if engine.game:
            return [p.name for p in engine.game.players]
        return [p.strip() for p in args.players.split(",")]

    try:
        # Give a browser a moment to connect so the opening effects are seen.
        deadline = time.time() + args.warmup
        while time.time() < deadline:
            engine.feed(sim.state())
            time.sleep(frame_time)

        shots = 0
        while args.shots == 0 or shots < args.shots:
            if sim.cue() is None:
                sim.spot_cue()
                engine.feed(sim.state())
            if len(sim.balls) <= 1:
                rack_for(current_game())
                engine.feed(sim.state())

            info = auto_shot(sim, skill=args.skill)
            if info.get("shot") == "none":
                rack_for(current_game())
                continue
            while sim.moving():
                engine.feed(sim.step_frame())
                time.sleep(frame_time)
            for _ in range(10):
                engine.feed(sim.step_frame())
                time.sleep(frame_time)
            shots += 1
            if engine.game and engine.game.over:
                print(f"  game over after {shots} shots")
                time.sleep(5)
                name, players = current_game(), current_players()
                rack_for(name)
                sim.spot_cue()
                engine.detector.reset(sim.state())
                engine.start_game(name, players=players)
            time.sleep(args.pause)
    except KeyboardInterrupt:
        print("\n  stopped")
    return 0


# --- live ----------------------------------------------------------------
def cmd_run(args) -> int:
    """Real camera, real table."""
    from .vision import open_source
    from .vision.detect import build_detector
    from .vision.pipeline import VisionPipeline

    table = load_table(args)
    calib_path = Path(args.calibration)
    if not calib_path.exists():
        print(f"no calibration at {calib_path}\n"
              f"run: python -m poolarena calibrate --source {args.source}", file=sys.stderr)
        return 2
    calib = Calibration.load(calib_path)
    print(f"  calibration {calib.label}, rms {calib.error_mm:.1f} mm")

    det_cfg = {}
    det_path = CONFIG / "detector.json"
    if det_path.exists():
        det_cfg = json.loads(det_path.read_text())
    if args.weights:
        det_cfg = {"detector": "yolo", "weights": args.weights}
    detector = build_detector(det_cfg)

    hub = Hub()
    engine = Engine(table=table, hub=hub,
                    log_path=Path(args.log) if args.log else None)
    start_server(hub, table, args.port, not args.no_browser)

    source = open_source(args.source)
    pipeline = VisionPipeline(table, calib, detector)
    print(f"  source      {source.name}")
    print(f"  game        {args.game}\n")

    engine.start_game(args.game, players=[p.strip() for p in args.players.split(",")])

    learned = False
    try:
        for color, depth in source.frames():
            if color is None:
                time.sleep(0.005)
                continue
            if not learned and args.learn_cloth:
                pipeline.learn_cloth(color)
                learned = True
                print("  learned the empty cloth")
            state = pipeline.process(color, depth)
            engine.feed(state)
    except KeyboardInterrupt:
        print("\n  stopped")
    finally:
        source.close()
    return 0


# --- calibrate -----------------------------------------------------------
def cmd_calibrate(args) -> int:
    from .vision import open_source
    from .vision.calibrate import calibrate_from_frame

    table = load_table(args)
    source = open_source(args.source)
    frame = None
    for _ in range(30):            # let auto-exposure settle before grabbing
        got = source.read()
        if got and got[0] is not None:
            frame = got[0]
    source.close()
    if frame is None:
        print("no frame from source", file=sys.stderr)
        return 2

    out = Path(args.calibration)
    out.parent.mkdir(parents=True, exist_ok=True)
    calib = calibrate_from_frame(frame, table, out)
    print(f"saved {out}  rms {calib.error_mm:.2f} mm")
    if calib.error_mm > 15:
        print("warning: over 15 mm — re-click the corners, and check the camera "
              "is not moving between frames")
    return 0


# --- replay --------------------------------------------------------------
def cmd_replay(args) -> int:
    """Replay a shot log through a game, which is how rules get regression-tested."""
    table = load_table(args)
    hub = Hub()
    engine = Engine(table=table, hub=hub)
    start_server(hub, table, args.port, not args.no_browser)
    engine.start_game(args.game, players=[p.strip() for p in args.players.split(",")])

    records = [json.loads(l) for l in Path(args.log).read_text().splitlines() if l.strip()]
    print(f"  replaying {len(records)} shots")
    for rec in records:
        for key in ("before", "after"):
            st = rec[key]
            from .types import Ball, Kind
            state = TableState(
                balls=[Ball(b["number"], b["x"], b["y"], Kind(b.get("kind", "unknown")),
                            b.get("r", 28.6), b.get("confidence", 1.0))
                       for b in st["balls"]],
                ts=st["ts"], settled=st.get("settled", True),
                obstructed=st.get("obstructed", False))
            engine.feed(state)
        time.sleep(args.pause)
    return 0


def cmd_games(args) -> int:
    for g in available():
        print(f"  {g['name']:<10} {g['title']:<18} {g['min_players']}-{g['max_players']}p  "
              f"{g['description']}")
    return 0


def cmd_effects(args) -> int:
    src = (OVERLAY / "src" / "effects.js").read_text()
    block = src.split("export const EFFECTS = {", 1)[1].split("};", 1)[0]
    for line in block.strip().splitlines():
        name = line.strip().split(":")[0]
        if name:
            print(f"  {name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Shared options live on a parent parser so they work on either side of the
    # subcommand: "demo --port 9000" and "--port 9000 demo" both run.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", help="table config json")
    common.add_argument("--size", default="8ft", help="7ft|8ft|8ft-pro|9ft|10ft|snooker")
    common.add_argument("--port", type=int, default=8777)
    common.add_argument("--no-browser", action="store_true")
    common.add_argument("--game", default="8ball")
    common.add_argument("--players", default="Player 1, Player 2")
    common.add_argument("--log", help="append shot records here (jsonl)")

    p = argparse.ArgumentParser(prog="poolarena", description=__doc__,
                                parents=[common],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("demo", parents=[common],
                       help="run against the simulator, no hardware")
    d.add_argument("--fps", type=float, default=30.0)
    d.add_argument("--skill", type=float, default=0.78)
    d.add_argument("--shots", type=int, default=0, help="0 = forever")
    d.add_argument("--pause", type=float, default=1.6, help="seconds between shots")
    d.add_argument("--warmup", type=float, default=2.0)
    d.add_argument("--seed", type=int, default=None)
    d.set_defaults(func=cmd_demo)

    r = sub.add_parser("run", parents=[common], help="live camera")
    r.add_argument("--source", default="kinect", help="kinect|cam:0|video:path")
    r.add_argument("--calibration", default=str(CONFIG / "calibration.json"))
    r.add_argument("--weights", help="YOLO weights, switches the detector")
    r.add_argument("--learn-cloth", action="store_true",
                   help="treat the first frame as an empty table")
    r.set_defaults(func=cmd_run)

    c = sub.add_parser("calibrate", parents=[common], help="click the four cushion corners")
    c.add_argument("--source", default="kinect")
    c.add_argument("--calibration", default=str(CONFIG / "calibration.json"))
    c.set_defaults(func=cmd_calibrate)

    rp = sub.add_parser("replay", parents=[common], help="replay a shot log")
    rp.add_argument("log")
    rp.add_argument("--pause", type=float, default=0.8)
    rp.set_defaults(func=cmd_replay)

    sub.add_parser("games", parents=[common], help="list game modes").set_defaults(func=cmd_games)
    sub.add_parser("effects", parents=[common], help="list projector effects").set_defaults(func=cmd_effects)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

"""The Windows launchers, checked as far as Linux can check them.

These cannot be executed here — there is no cmd.exe — so this does not prove
they run. What it does prove is the things that would break them silently:
a subcommand that no longer exists, a `goto` with no label to land on, a
file that lost its carriage returns, and an error path that closes the
window before anybody can read why.

That last one is the whole reason these scripts exist. A double-clicked
batch file that fails and vanishes tells the person nothing at all.
"""
import re
from pathlib import Path

import pytest

WINDOWS = Path(__file__).resolve().parent.parent / "windows"
SCRIPTS = sorted(WINDOWS.glob("*.bat"))
LAUNCHERS = [p for p in SCRIPTS if p.name != "_env.bat"]


def text(p: Path) -> str:
    return p.read_bytes().decode("ascii")


def test_there_are_scripts_to_check():
    assert SCRIPTS, "no .bat files found"


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_line_endings_are_crlf(script):
    """A label read without its carriage return can send `goto` somewhere
    unintended, and it looks like the script doing nothing."""
    raw = script.read_bytes()
    assert b"\n" in raw
    assert raw.count(b"\r\n") == raw.count(b"\n"), "a line is missing its CR"


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_every_goto_has_somewhere_to_land(script):
    body = text(script)
    labels = set(re.findall(r"^\s*:([A-Za-z_][\w]*)", body, re.M))
    for target in re.findall(r"goto\s+:?([A-Za-z_][\w]*)", body):
        assert target in labels, f"goto :{target} has no :{target}"


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_only_ascii(script):
    """cmd.exe renders a UTF-8 em dash as mojibake in the default code page,
    and a help message full of rubbish is worse than a plain one."""
    script.read_bytes().decode("ascii")


@pytest.mark.parametrize("script", LAUNCHERS, ids=lambda p: p.name)
def test_a_failure_cannot_close_the_window_before_it_is_read(script):
    """Every path that ends badly has to pause. This is the single thing a
    double-clicked batch file most often gets wrong."""
    body = text(script)
    assert "pause" in body, "nothing stops the window closing"
    # Each failure label must reach a pause before the script exits. Match
    # the label where it is *defined* — at the start of a line — not where
    # a `goto` mentions it, and let labels fall through to one another the
    # way cmd does.
    for m in re.finditer(r"^[ \t]*:(stop|failed)[ \t]*$", body, re.M):
        tail = body[m.end():]
        upto_exit = tail.split("exit /b", 1)[0]
        assert "pause" in upto_exit, f":{m.group(1)} exits without pausing"


@pytest.mark.parametrize("script", LAUNCHERS, ids=lambda p: p.name)
def test_every_launcher_finds_python_the_same_way(script):
    body = text(script)
    assert "_env.bat" in body, "must use the shared Python lookup"
    assert "%PY%" in body or "PY=" in body


def test_the_env_script_moves_to_the_repo_root():
    """Double-clicked from the desktop, a batch file starts in System32."""
    body = text(WINDOWS / "_env.bat")
    assert 'cd /d "%~dp0.."' in body


def test_a_venv_beats_whatever_python_is_on_the_path():
    body = text(WINDOWS / "_env.bat")
    venv = body.index(".venv")
    launcher = body.index("where py")
    assert venv < launcher, "the private environment has to be preferred"


# --- the part that would really ruin a setup night ------------------------
def subcommands() -> set[str]:
    """Every subcommand the CLI actually has."""
    import poolarena.__main__ as m

    found = set()
    src = Path(m.__file__).read_text()
    for name in re.findall(r'sub\.add_parser\(\s*"([a-z_]+)"', src):
        found.add(name)
    assert found, "could not read the subcommand list"
    return found


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_the_commands_the_scripts_run_all_exist(script):
    """A renamed subcommand would leave these failing on the night, with an
    argparse error nobody reading a batch file would connect to a rename."""
    have = subcommands()
    for used in re.findall(r"-m poolarena\s+([a-z_]+)", text(script)):
        assert used in have, f"{script.name} runs `poolarena {used}`, which is gone"


def test_the_scripts_cover_what_a_setup_actually_needs():
    names = {p.stem for p in LAUNCHERS}
    for needed in ("setup", "demo", "start", "check", "calibrate"):
        assert needed in names, f"no {needed}.bat"


def test_there_is_a_way_to_ask_what_cameras_exist():
    """The first thing you need when the wrong camera opens — and the thing
    that was missing when a phone-as-webcam setup went looking for cam:1 and
    got a stack trace."""
    assert (WINDOWS / "cameras.bat").is_file()
    assert "poolarena cameras" in text(WINDOWS / "cameras.bat")


def test_no_launcher_still_blames_another_program_for_a_missing_camera():
    """It does not mean that, and it sent somebody hunting for a program
    holding a camera that was never there."""
    for script in LAUNCHERS:
        body = text(script)
        assert "another program has it" not in body, script.name

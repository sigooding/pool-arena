"""A full-screen overlay must not share a class name with anything else.

This is here because of a real one. The player sheet was given
`class="who"`, and the shot feed had been using `.who` for the player's name
on each row since long before. The sheet's rule —

    .who { position: fixed; inset: 0; backdrop-filter: blur(6px); ... }

— therefore applied to every feed row's name span as well. Nothing looked
wrong until somebody potted the cue ball: that adds a foul row, the row's
name span became a full-screen blurred overlay, and the whole scoreboard
disappeared behind the words "Player 1".

Nothing caught it. The page loaded fine, the tests passed, and the fault
only appeared several minutes into a game.
"""
import re
from pathlib import Path

import pytest

OVERLAY = Path(__file__).resolve().parent.parent / "overlay"
SHEETS = sorted((OVERLAY / "src").glob("*.css"))


def rules(css: str):
    """(selector, body) for every top-level rule, @media contents included."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return re.findall(r"([^{}]+)\{([^{}]*)\}", css)


def overlay_classes(css: str) -> set[str]:
    """Classes whose rule makes the element cover the whole viewport."""
    found = set()
    for sel, body in rules(css):
        flat = " ".join(body.split())
        fixed = re.search(r"position:\s*fixed", flat)
        covering = ("inset: 0" in flat or
                    re.search(r"(top|left):\s*0", flat) and
                    re.search(r"(right|bottom|width|height):", flat))
        if not (fixed and covering):
            continue
        for part in sel.split(","):
            part = part.strip()
            # a bare single-class selector is the dangerous shape
            m = re.fullmatch(r"\.([A-Za-z][\w-]*)", part)
            if m:
                found.add(m.group(1))
    return found


def used_elsewhere(css: str, name: str) -> list[str]:
    """Other rules that target this class as part of something larger — a
    sign it also means something that is not an overlay."""
    out = []
    for sel, _ in rules(css):
        for part in sel.split(","):
            part = part.strip()
            if f".{name}" not in part:
                continue
            if re.fullmatch(rf"\.{name}(\[[^\]]*\])?", part):
                continue              # the overlay's own rule
            if part.startswith(f".{name}-") or part.startswith(f".{name} "):
                continue              # its own children
            out.append(part)
    return out


@pytest.mark.parametrize("sheet", SHEETS, ids=lambda p: p.name)
def test_no_overlay_class_is_also_used_for_something_inline(sheet):
    css = sheet.read_text()
    for name in overlay_classes(css):
        others = used_elsewhere(css, name)
        assert not others, (
            f".{name} covers the viewport, and is also targeted by "
            f"{others} — anything given that class anywhere else becomes a "
            f"full-screen overlay")


@pytest.mark.parametrize("sheet", SHEETS, ids=lambda p: p.name)
def test_overlay_classes_are_not_handed_out_by_the_scripts(sheet):
    """The feed row was given its class in JS, not in the HTML, which is why
    reading the page never showed the clash."""
    css = sheet.read_text()
    names = overlay_classes(css)
    if not names:
        pytest.skip("no full-screen overlays in this sheet")
    js = "\n".join(p.read_text() for p in (OVERLAY / "src").glob("*.js"))
    for name in names:
        for pattern in (rf"className\s*=\s*['\"]{name}['\"]",
                        rf"classList\.add\(['\"]{name}['\"]\)"):
            hit = re.search(pattern, js)
            assert not hit, (
                f"something is given class {name!r} in a script, and "
                f".{name} is a full-screen overlay")


def test_the_one_that_got_through_stays_fixed():
    """Named outright, because this is the bug that prompted the file."""
    css = (OVERLAY / "src" / "board.css").read_text()
    js = (OVERLAY / "src" / "board.js").read_text()
    assert "className = 'who'" in js, "the feed still names its rows this way"
    assert not re.search(r"^\.who\s*\{", css, re.M), \
        "so a bare .who rule must never come back"
    assert ".who-sheet {" in css

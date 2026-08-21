"""Keep scripts/*.ps1 parseable by Windows PowerShell 5.1.

The dev box runs Windows PowerShell 5.1 (the `powershell` command), not
PowerShell 7 (`pwsh`). 5.1 is stricter in two ways that are easy to trip
without noticing, because 7 accepts both:

1. It reads a .ps1 with no UTF-8 BOM using the system ANSI codepage, so any
   non-ASCII character is silently mangled into different characters.
2. Its parser is less forgiving of `$(...)` subexpressions inside
   double-quoted strings when those contain braces, quotes and parens.

Both shipped in update_install.ps1 and produced a parse error on the user's
machine that no CI check could see. There is no PowerShell on the CI runner,
so these are byte-level checks rather than a real parse.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
# deploy/portable/*.ps1.tmpl is copied verbatim onto a cartridge and run by
# whatever PowerShell the host has - which on a stock Windows box is 5.1. The
# templates are subject to exactly the same two hazards as scripts/*.ps1, and
# are further from view, so they are checked here too rather than separately.
PS_SCRIPTS = sorted(
    (REPO / "scripts").glob("*.ps1")
) + sorted((REPO / "deploy" / "portable").glob("*.ps1.tmpl"))


def test_there_are_powershell_scripts_to_check():
    assert PS_SCRIPTS, "expected at least one .ps1 under scripts/"
    assert any(p.name.endswith(".ps1.tmpl") for p in PS_SCRIPTS), (
        "expected the portable launcher template to be covered too"
    )


@pytest.mark.parametrize("script", PS_SCRIPTS, ids=lambda p: p.name)
def test_powershell_script_is_ascii_only(script: Path):
    """Non-ASCII needs a UTF-8 BOM to survive 5.1; plain ASCII needs nothing."""
    raw = script.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        return  # explicit BOM: 5.1 will decode UTF-8 correctly
    offenders = []
    for lineno, line in enumerate(raw.split(b"\n"), 1):
        try:
            line.decode("ascii")
        except UnicodeDecodeError:
            offenders.append(lineno)
    assert not offenders, (
        f"{script.name} has non-ASCII on line(s) {offenders} and no UTF-8 BOM. "
        "Windows PowerShell 5.1 would decode those bytes as ANSI. "
        "Use ASCII (e.g. '-' not an em dash), or save with a BOM."
    )


@pytest.mark.parametrize("script", PS_SCRIPTS, ids=lambda p: p.name)
def test_powershell_script_avoids_if_in_string_interpolation(script: Path):
    """`"...$(if ($x) { 'a' } else { 'b' })..."` parses on 7, not reliably on 5.1.

    Assign to a variable first and interpolate the variable.
    """
    offenders = []
    in_block_comment = False
    for lineno, line in enumerate(script.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("<#"):
            in_block_comment = True
        if in_block_comment:
            if "#>" in stripped:
                in_block_comment = False
            continue
        if stripped.startswith("#"):
            continue
        if "$(if" in line.replace("$( if", "$(if"):
            offenders.append(lineno)
    assert not offenders, (
        f"{script.name} uses $(if ...) string interpolation on line(s) {offenders}. "
        "Windows PowerShell 5.1 mis-parses this; compute the value into a "
        "variable and interpolate that instead."
    )

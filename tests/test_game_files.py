"""M2: custom games written as TOML files."""

import tomllib
from dataclasses import replace
from pathlib import Path

import pytest

from busride.engine.builtins import BUILTIN_GAMES, load_game
from busride.engine.game import RulesError
from busride.engine.rules import dump_rules, load_rules, parse_rules, static_warnings

HI_LO_FILE = """
[game]
name = "My Hi-Lo"
forced_first_bet = false
description = "A short hi-lo ladder"

[deck]
model = "fresh_52"
ace = "low"

[ties]
higher_lower = "push"

[[stage]]
type = "reveal"

[[stage]]
type = "higher_lower"

[[stage]]
type = "inside_outside"
between = [1, 2]

[payout]
ladder = [1.4, 2.6]
"""


def test_a_custom_game_file(tmp_path: Path) -> None:
    path = tmp_path / "my-hi-lo.toml"
    path.write_text(HI_LO_FILE, encoding="utf-8")
    spec = load_game(str(path))
    assert spec.name == "My Hi-Lo"
    assert [s.kind for s in spec.stages] == ["reveal", "higher_lower", "inside_outside"]
    assert spec.stages[1].refs == (0,) and spec.stages[2].refs == (0, 1)
    assert spec.returns == (1.4, 2.6)
    assert spec.forced_first_bet is False and spec.ace == "low" and spec.tie_higher_lower == "push"
    assert spec.description == "A short hi-lo ladder"


@pytest.mark.parametrize("name", list(BUILTIN_GAMES))
def test_every_built_in_round_trips_through_toml(name: str) -> None:
    spec = BUILTIN_GAMES[name]
    back = parse_rules(tomllib.loads(dump_rules(spec)), source=spec.source)
    assert back == spec


def test_ride_the_bus_keeps_the_original_file_format() -> None:
    text = dump_rules(BUILTIN_GAMES["ride-the-bus"])
    assert "return_after_stage" in text and "[[stage]]" not in text


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        ("ladder = [1.4, 2.6, 3.0]", "2 guessing stages"),
        ('[[stage]]\ntype = "pair"', "stage type"),
        ('[[stage]]\ntype = "inside_outside"\nbetween = [3, 9]', "earlier cards"),
    ],
)
def test_bad_game_files_name_the_problem(tmp_path: Path, edit: str, message: str) -> None:
    text = HI_LO_FILE
    if edit.startswith("ladder"):
        text = text.replace("ladder = [1.4, 2.6]", edit)
    else:
        text = text.replace("[payout]", f"{edit}\n\n[payout]")
    path = tmp_path / "bad.toml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(RulesError, match=message):
        load_rules(path)


def test_unknown_stage_keys_are_warned_about(tmp_path: Path) -> None:
    path = tmp_path / "typo.toml"
    path.write_text(HI_LO_FILE.replace("between = [1, 2]", "betwen = [1, 2]"), encoding="utf-8")
    spec = load_rules(path)
    assert any("stage[3].betwen" in w for w in static_warnings(spec))


def test_built_ins_do_not_nag_about_capture_dates() -> None:
    for spec in BUILTIN_GAMES.values():
        assert static_warnings(spec) == []
    assert static_warnings(replace(BUILTIN_GAMES["ride-the-bus"], game_version="fill in"))

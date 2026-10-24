import tomllib
from dataclasses import replace
from pathlib import Path

import pytest

from busride.engine.rules import (
    Rules,
    RulesError,
    dump_rules,
    load_rules,
    parse_ladder,
    parse_rules,
    static_warnings,
)

ROOT = Path(__file__).resolve().parents[1]


def test_shipped_rules_file_loads() -> None:
    rules = load_rules(ROOT / "examples" / "ride-the-bus-rules.toml")
    assert rules.deck_model == "fresh_52"
    assert rules.ace == "high"
    assert (rules.tie_higher_lower, rules.tie_range_edge) == ("lose", "lose")


def test_dump_and_parse_round_trip() -> None:
    rules = Rules(
        game_version="0.4.1",
        captured_on="2026-10-23",
        deck_model="shoe",
        decks=6,
        ace="either",
        tie_higher_lower="push",
        tie_range_edge="win",
        returns=(1.9, 2.7625, 4.2, 15.857142857142858),
        min_stake=10.0,
        max_stake=1000.0,
        timeout="lose",
    )
    back = parse_rules(tomllib.loads(dump_rules(rules)), source="x")
    assert back == replace(rules, source="x")


@pytest.mark.parametrize(
    ("section", "key", "value", "message"),
    [
        ("deck", "ace", "middle", "deck.ace"),
        ("deck", "model", "two_decks", "deck.model"),
        ("deck", "decks", 0, "deck.decks"),
        ("ties", "higher_lower", "draw", "ties.higher_lower"),
        ("payout", "return_after_stage", [1, 2, 3], "4 guessing stages"),
        ("payout", "return_after_stage", [1, 2, -3, 4], "negative"),
    ],
)
def test_bad_values_name_the_field(section: str, key: str, value: object, message: str) -> None:
    data = tomllib.loads(dump_rules(Rules()))
    data[section][key] = value
    with pytest.raises(RulesError, match=message):
        parse_rules(data)


def test_missing_file_points_to_init(tmp_path: Path) -> None:
    with pytest.raises(RulesError, match="busride init"):
        load_rules(tmp_path / "nope.toml")


def test_warnings_for_odd_values() -> None:
    assert any("empty" in w for w in static_warnings(Rules()))
    assert not any("empty" in w for w in static_warnings(Rules(), include_ladder=False))
    down = static_warnings(Rules(returns=(2.0, 3.0, 2.5, 10.0), game_version="1", captured_on="x"))
    assert any("goes down" in w for w in down)
    data = tomllib.loads(dump_rules(Rules()))
    data["ties"]["higer_lower"] = "push"
    assert any("ties.higer_lower" in w for w in static_warnings(parse_rules(data)))


def test_parse_ladder() -> None:
    assert parse_ladder("2, 2.7, 4.1, 15") == (2.0, 2.7, 4.1, 15.0)
    assert parse_ladder("2x 2.7x 4.1x 15x") == (2.0, 2.7, 4.1, 15.0)
    with pytest.raises(RulesError):
        parse_ladder("2,3")

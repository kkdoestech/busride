import pytest

from busride.engine.cards import (
    FULL_DECK,
    Card,
    CardError,
    deal_conflict,
    parse_card,
    parse_cards,
    remaining,
)


@pytest.mark.parametrize(
    ("text", "card"),
    [
        ("9h", Card(9, "h")),
        ("Ks", Card(13, "s")),
        ("10d", Card(10, "d")),
        ("Td", Card(10, "d")),
        ("Ad", Card(14, "d")),
        (" qS ", Card(12, "s")),
        ("9♥", Card(9, "h")),
        ("J♣", Card(11, "c")),
        ("\ufeff7h", Card(7, "h")),
    ],
)
def test_parse_card(text: str, card: Card) -> None:
    assert parse_card(text) == card


@pytest.mark.parametrize(
    ("text", "hint"),
    [("1h", "rank"), ("9x", "suit"), ("11h", "rank"), ("", "empty"), ("K", "suit")],
)
def test_bad_cards_explain_themselves(text: str, hint: str) -> None:
    with pytest.raises(CardError, match=hint):
        parse_card(text)


def test_card_text_round_trips() -> None:
    for card in FULL_DECK:
        assert parse_card(str(card)) == card
    assert str(Card(10, "d")) == "10d"
    assert parse_cards("9h, Ks 10d") == [Card(9, "h"), Card(13, "s"), Card(10, "d")]


def test_remaining_weights() -> None:
    seen = [Card(9, "h"), Card(13, "s")]
    fresh = remaining(seen, "fresh_52")
    assert sum(w for _, w in fresh) == 50
    assert Card(9, "h") not in dict(fresh)
    shoe = dict(remaining([Card(9, "h"), Card(9, "h")], "shoe", 2))
    assert Card(9, "h") not in shoe
    assert sum(shoe.values()) == 102
    assert sum(w for _, w in remaining(seen, "with_replacement")) == 52


def test_deal_conflict() -> None:
    twice = [Card(9, "h"), Card(9, "h")]
    assert deal_conflict(twice, "fresh_52") == Card(9, "h")
    assert deal_conflict(twice, "shoe", 2) is None
    assert deal_conflict(twice, "with_replacement") is None

from pathlib import Path

import pytest

from busride.engine.cards import CardError
from busride.store import Store


def test_add_undo_and_read_back(tmp_path: Path) -> None:
    with Store(tmp_path / "r.db") as store:
        first = store.add(["9h", "Ks", "Td"], 10.0, 42.0, "0.4.1")
        store.add(["2c", "5h"], 10.0, None, "0.4.1")
        assert first.cards == ("9h", "Ks", "10d")
        assert store.count() == 2
        gone = store.undo()
        assert gone is not None and gone.cards == ("2c", "5h") and gone.return_paid is None
        again = store.add(["Ah"], 10.0, None)
        assert again.id == 2  # an undone number is reused, so the running count stays honest
    with Store(tmp_path / "r.db") as store:
        rounds = store.rounds()
    assert [r.cards for r in rounds] == [("9h", "Ks", "10d"), ("Ah",)]
    assert rounds[0].return_paid == 42.0 and rounds[0].game_version == "0.4.1"


def test_bad_rounds_are_refused(tmp_path: Path) -> None:
    with Store(tmp_path / "r.db") as store:
        with pytest.raises(CardError):
            store.add(["9x"], 1.0, None)
        with pytest.raises(ValueError, match="1 to 4"):
            store.add(["2h", "3h", "4h", "5h", "6h"], 1.0, None)
        assert store.undo() is None

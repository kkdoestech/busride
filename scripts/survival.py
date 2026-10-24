"""M1 check: print the four exact survival probabilities and the cold solve time.

uv run python scripts/survival.py [rules.toml]
"""

import sys
import time

from busride.engine.rules import Rules, load_rules
from busride.engine.solver import clear_cache, solve, survival


def main() -> None:
    rules = load_rules(sys.argv[1]) if len(sys.argv) > 1 else Rules()
    clear_cache()
    started = time.perf_counter()
    odds = survival(rules)
    solve(rules)
    elapsed = time.perf_counter() - started
    ties = f"{rules.tie_higher_lower}/{rules.tie_range_edge}"
    print(f"deck {rules.deck_model}, ace {rules.ace}, ties {ties}")
    for k, s in enumerate(odds, start=1):
        print(f"  survive through stage {k}: {s:.5f}   fair return {1 / s:6.2f}x")
    print(f"full solve: {elapsed:.3f} s")


if __name__ == "__main__":
    main()

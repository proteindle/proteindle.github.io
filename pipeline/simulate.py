"""
Play the game thousands of times and report how hard it actually is.

    python pipeline/simulate.py
    python pipeline/simulate.py --trials 500 --pool freeplay
    python pipeline/simulate.py --strategy greedy

Bit counts tell you what information is theoretically present. They do not
tell you whether a player wins in six guesses, because columns overlap and
nobody plays optimally. This does: it runs real rounds with real feedback
and reports the distribution of guesses needed.

Strategies, roughly worst to best:

  famous    Always guess the most-cited protein still consistent with the
            feedback so far. This is closest to how a person plays — you
            reach for the gene you know, not the one that splits the space.
  random    Guess uniformly at random from the consistent candidates. A
            reasonable floor for "playing sensibly but without insight".
  greedy    Pick the guess that minimises the expected number of remaining
            candidates. Near-optimal, and an upper bound on how well anyone
            could possibly do.

If `famous` mostly finishes inside the guess limit and `greedy` finishes in
two or three, the game is well tuned: solvable by knowledge, rewarding of
strategy, not trivially brute-forceable.
"""

import argparse
import json
import random
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scoring  # noqa: E402
from config import WEB_DATA  # noqa: E402

MAX_GUESSES = 8
# Cap on how many candidate guesses `greedy` evaluates per turn. Scoring
# every candidate against every candidate is quadratic; at a few hundred
# remaining that is fine, beyond it the sample is indistinguishable.
GREEDY_WIDTH = 140


def consistent(candidates, guess, feedback, meta):
    """Candidates that would have produced the same feedback."""
    return [c for c in candidates
            if scoring.signature(guess, c, meta) == feedback]


def pick_famous(candidates, _pool, _meta, _rng):
    return min(candidates, key=lambda c: c["rank"])


def pick_random(candidates, _pool, _meta, rng):
    return rng.choice(candidates)


def pick_greedy(candidates, _pool, meta, rng):
    """Minimise the expected size of the surviving candidate set."""
    if len(candidates) <= 2:
        return candidates[0]

    trials = candidates
    if len(trials) > GREEDY_WIDTH:
        trials = rng.sample(trials, GREEDY_WIDTH)

    best, best_score = None, float("inf")
    n = len(candidates)
    for guess in trials:
        buckets = Counter()
        for target in candidates:
            buckets[scoring.signature(guess, target, meta)] += 1
        # Expected remaining = sum(size^2) / n
        score = sum(v * v for v in buckets.values()) / n
        # Break ties toward the more famous protein: a human would.
        if score < best_score - 1e-9 or (
            abs(score - best_score) < 1e-9 and best is not None
            and guess["rank"] < best["rank"]
        ):
            best, best_score = guess, score
    return best or candidates[0]


STRATEGIES = {
    "famous": pick_famous,
    "random": pick_random,
    "greedy": pick_greedy,
}


def play(target, pool, meta, strategy, rng, max_guesses):
    candidates = list(pool)
    for turn in range(1, max_guesses + 1):
        if not candidates:
            return None, turn          # feedback was contradictory
        guess = strategy(candidates, pool, meta, rng)
        if guess["a"] == target["a"]:
            return turn, len(candidates)
        fb = scoring.signature(guess, target, meta)
        candidates = consistent(candidates, guess, fb, meta)
        candidates = [c for c in candidates if c["a"] != guess["a"]]
    return None, len(candidates)


def report(name, results, max_guesses, pool_size):
    solved = [r for r in results if r is not None]
    dist = Counter(solved)
    n = len(results)

    print(f"\n  {name}")
    print(f"  {'-' * 62}")
    if not solved:
        print("    never solved within the limit")
        return

    for k in range(1, max_guesses + 1):
        c = dist.get(k, 0)
        if c == 0 and k > max(solved):
            continue
        bar = "#" * round(46 * c / n)
        print(f"    {k:>2}  {c / n:>6.1%}  {bar}")
    fails = n - len(solved)
    if fails:
        print(f"    >{max_guesses}  {fails / n:>6.1%}  "
              f"{'#' * round(46 * fails / n)}")

    print(f"\n    solved within {max_guesses}: {len(solved) / n:.1%}"
          f"    mean {statistics.mean(solved):.2f}"
          f"    median {statistics.median(solved):.0f}"
          f"    worst {max(solved)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=300)
    ap.add_argument("--pool", choices=["daily", "freeplay", "hard"],
                    default="daily")
    ap.add_argument("--strategy", choices=list(STRATEGIES) + ["all"],
                    default="all")
    ap.add_argument("--max-guesses", type=int, default=None,
                    help="override the limit baked into proteins.json")
    ap.add_argument("--seed", type=int, default=3)
    args = ap.parse_args()

    path = WEB_DATA / "proteins.json"
    if not path.exists():
        print(f"\n{path} not found. Run pipeline/build.py first.\n")
        return 1

    data = json.loads(path.read_text(encoding="utf-8"))
    meta = scoring.meta_from(data)
    allp = data["proteins"]

    if args.max_guesses is None:
        # v2 databases store a per-mode map; the simulator plays the daily.
        limits = data.get("maxGuesses", MAX_GUESSES)
        if isinstance(limits, dict):
            limits = limits.get("daily") or MAX_GUESSES
        args.max_guesses = limits

    tiers = {"daily": {"daily"},
             "freeplay": {"daily", "freeplay"},
             "hard": {"daily", "freeplay", "hard"}}[args.pool]
    pool = [p for p in allp if p["t"] in tiers]

    print(f"\n{'=' * 66}")
    print(f"  Simulated play — {args.pool} pool, {len(pool)} answers, "
          f"{args.trials} rounds each")
    print(f"  Guess limit: {args.max_guesses}")
    print(f"{'=' * 66}")

    names = list(STRATEGIES) if args.strategy == "all" else [args.strategy]

    for name in names:
        rng = random.Random(args.seed)
        targets = [rng.choice(pool) for _ in range(args.trials)]
        strategy = STRATEGIES[name]
        results = []
        for i, t in enumerate(targets):
            if name == "greedy" and i % 25 == 0:
                print(f"    greedy {i}/{args.trials}...", end="\r", flush=True)
            turns, _left = play(t, pool, meta, strategy, rng,
                                args.max_guesses)
            results.append(turns)
        report(name, results, args.max_guesses, len(pool))

    print(f"\n  Reading this: `famous` is the human-like floor and should")
    print(f"  mostly finish inside the limit. `greedy` is the ceiling — if")
    print(f"  it solves in 2, the columns are highly informative. A large")
    print(f"  gap between them means skill matters, which is what you want.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

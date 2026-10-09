"""Console entry point for the `interview` script declared in pyproject.toml.

The simulation itself lives in the top-level modules (`run_flashing.py`,
`exercises.py`), which are run directly rather than imported as a package —
so this points at them instead of pretending to be them.
"""


def main() -> None:
    print("UDS diagnostic simulation")
    print()
    print("  python run_flashing.py          full flashing sequence + negative tests")
    print("  python run_flashing.py --quiet  hide the frame trace")
    print("  python exercises.py             all six exercises")
    print("  python exercises.py 3           just exercise 3")

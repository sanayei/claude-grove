"""Command-line entry point."""
from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog="grove",
        description="Keep Claude Code sessions alive in tmux, organised as a tree.",
    )


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    return 0

from __future__ import annotations

from cli_commands import COMMANDS
from cli_parser import build_parser
from config import load_config


def run_cli(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        return -1
    config = load_config()
    return COMMANDS[args.command](args, config)

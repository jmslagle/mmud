from __future__ import annotations
import argparse
import pathlib
from mmud.config.loader import load_config
from mmud.tui.app import MegaMudApp


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m mmud.tui",
        description="MegaMud TUI — terminal MUD bot client",
    )
    parser.add_argument("--host", default=None, help="MUD server hostname")
    parser.add_argument("--port", type=int, default=None, help="MUD server port")
    parser.add_argument(
        "--char",
        metavar="PATH",
        default=None,
        help="Path to character .toml config file",
    )
    args = parser.parse_args()

    char_path = pathlib.Path(args.char) if args.char else None
    config = load_config(char_path)

    host = args.host or config.server.host
    port = args.port or config.server.port

    app = MegaMudApp(config=config, host=host, port=port, config_path=char_path)
    app.run()


if __name__ == "__main__":
    main()

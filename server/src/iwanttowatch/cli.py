import argparse
import json
import sys
import tempfile
from pathlib import Path

import uvicorn

from iwanttowatch.config import Settings
from iwanttowatch.main import create_app


def main() -> None:
    parser = argparse.ArgumentParser(prog="iwanttowatch")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="run the web server")
    commands.add_parser("openapi", help="print the OpenAPI schema as JSON")
    args = parser.parse_args()

    if args.command == "serve":
        settings = Settings()
        uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
    elif args.command == "openapi":
        with tempfile.TemporaryDirectory() as data_dir:
            app = create_app(Settings(data_dir=Path(data_dir), static_dir=None))
            json.dump(app.openapi(), sys.stdout, indent=2)
            sys.stdout.write("\n")

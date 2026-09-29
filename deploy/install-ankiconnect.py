"""Install a downloaded official AnkiConnect .ankiaddon into one new profile."""

import json
import sys
import zipfile
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("Usage: install-ankiconnect.py ARCHIVE ANKI_BASE PORT")
    archive, base, port_text = sys.argv[1:]
    port = int(port_text)
    if not 1024 <= port <= 65535:
        raise SystemExit("Port must be between 1024 and 65535")
    destination = Path(base) / "addons21" / "2055492159"
    if destination.exists():
        raise SystemExit(f"AnkiConnect already exists at {destination}; configure it in Anki.")
    with zipfile.ZipFile(archive) as package:
        names = package.namelist()
        if not names or any(
            name.startswith("/") or ".." in Path(name).parts for name in names
        ):
            raise SystemExit("Unsafe add-on archive")
        if "__init__.py" not in names or "config.json" not in names:
            raise SystemExit("This is not an AnkiConnect add-on archive")
        destination.mkdir(parents=True)
        package.extractall(destination)
    (destination / "meta.json").write_text(json.dumps({
        "name": "AnkiConnect",
        "config": {"webBindAddress": "127.0.0.1", "webBindPort": port},
    }))
    print(f"Installed AnkiConnect for {base} on loopback port {port}.")


if __name__ == "__main__":
    main()

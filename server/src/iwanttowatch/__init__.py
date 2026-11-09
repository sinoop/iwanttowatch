"""iWantToWatch: self-hosted movie recommendations."""

import os
from importlib.metadata import version

__version__ = os.environ.get("IWANTTOWATCH_VERSION") or version("iwanttowatch")

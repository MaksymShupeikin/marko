"""Compatibility facade for the Metis-owned pricing kernel.

New Marko application code imports ``metis.pricing`` directly. This facade
keeps the former public import path working during the ownership migration.
"""

from metis.pricing import *  # noqa: F403
from metis.pricing import __all__ as __all__

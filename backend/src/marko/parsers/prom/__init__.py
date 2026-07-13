"""prom.ua integration."""

from .config import ScrapeConfig
from .gateway import PromGateway

__all__ = ["PromGateway", "ScrapeConfig"]

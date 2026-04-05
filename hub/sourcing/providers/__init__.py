"""Provider registry for Hub sourcing."""

from .github import GitHubProvider
from .itch import ItchProvider
from .steam import SteamProvider

PROVIDER_TYPES = {
    "github": GitHubProvider,
    "itch": ItchProvider,
    "steam": SteamProvider,
}

__all__ = ["GitHubProvider", "ItchProvider", "SteamProvider", "PROVIDER_TYPES"]

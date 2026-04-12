"""Provider registry for Hub software-project sourcing."""

from .github import GithubSoftwareProjectProvider

PROVIDER_TYPES = {
    "github": GithubSoftwareProjectProvider,
}

__all__ = ["GithubSoftwareProjectProvider", "PROVIDER_TYPES"]

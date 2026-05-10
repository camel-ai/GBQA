"""Compatibility wrapper for GBQA Harbor artifact export."""

from gbqa.reporting.export import export_harbor_artifacts, main

__all__ = ["export_harbor_artifacts", "main"]


if __name__ == "__main__":
    main()

"""MCP server for Milton's analyst agents."""

import importlib.metadata

# pyproject.toml is the one place the version is set; the release workflow checks the tag against it.
try:
    __version__ = importlib.metadata.version("milton-mcp")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0+unknown"

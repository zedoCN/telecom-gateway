"""Model-specific China Telecom gateway client and CLI."""

__version__ = "0.2.0"

from .client import GatewayClient, GatewayError

__all__ = ["GatewayClient", "GatewayError", "__version__"]

import logging

from composio import Composio
from src.config import settings

logger = logging.getLogger(__name__)

# Auth config IDs from Composio dashboard
GMAIL_AUTH_CONFIG_ID = "ac_oJWdJcmo-SHT"
GCAL_AUTH_CONFIG_ID = "ac_Z7mVPMZUjnsm"


def get_sdk() -> Composio:
    """Get Composio SDK instance."""
    return Composio(api_key=settings.composio_api_key)


def initiate_oauth(entity_id: str, redirect_url: str) -> str:
    """Start OAuth flow for Gmail + Calendar. Returns auth URL."""
    sdk = get_sdk()
    try:
        # Connect Gmail first (includes email scopes)
        result = sdk.connected_accounts.initiate(
            user_id=entity_id,
            auth_config_id=GMAIL_AUTH_CONFIG_ID,
            callback_url=redirect_url,
        )
        return result.redirect_url
    except Exception as e:
        logger.error(f"OAuth initiation failed: {e}")
        raise


def initiate_gcal_oauth(entity_id: str, redirect_url: str) -> str:
    """Start OAuth flow for Google Calendar."""
    sdk = get_sdk()
    try:
        result = sdk.connected_accounts.initiate(
            user_id=entity_id,
            auth_config_id=GCAL_AUTH_CONFIG_ID,
            callback_url=redirect_url,
        )
        return result.redirect_url
    except Exception as e:
        logger.error(f"GCal OAuth initiation failed: {e}")
        raise


def check_connection(entity_id: str) -> bool:
    """Check if entity has active Google connection."""
    try:
        sdk = get_sdk()
        accounts = sdk.connected_accounts.list()
        return any(
            getattr(a, 'entity_id', None) == entity_id or
            getattr(a, 'user_id', None) == entity_id
            for a in getattr(accounts, 'items', accounts)
        )
    except Exception:
        return False

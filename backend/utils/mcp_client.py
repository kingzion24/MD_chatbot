# backend/utils/mcp_client.py
import httpx
import logging
from typing import Dict

from tenacity import (
    retry,
    retry_if_exception,
    RetryError,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


def _is_retryable_log_error(exc: BaseException) -> bool:
    """
    Return True only for exceptions that are worth retrying.

    - httpx.RequestError  — network-level failures (connection refused, timeout,
                            DNS error).  The MCP server may just be temporarily
                            unreachable; retry makes sense.
    - httpx.HTTPStatusError with 5xx status — server-side transient fault.
    - httpx.HTTPStatusError with 4xx status — bad payload; retrying will never
                            succeed (e.g. 422 Unprocessable Entity), so we skip
                            retries and discard immediately.
    """
    if isinstance(exc, httpx.RequestError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


class MCPClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        # Single persistent client — reused across all requests to avoid
        # the overhead of opening a new TCP connection on every call.
        self._client = httpx.AsyncClient()

    async def execute_query(
        self, sql: str, params: list = None, business_id: str = None
    ) -> Dict:
        """Execute SQL query via MCP server.

        Passes X-Business-ID as a request header when provided so the MCP
        server's rate limiter can apply per-tenant quotas instead of a single
        shared quota keyed on the backend container's IP.
        """
        headers = {"X-Business-ID": business_id} if business_id else {}
        try:
            response = await self._client.post(
                f"{self.base_url}/query",
                json={"sql": sql, "params": params or []},
                headers=headers,
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"MCP HTTP error: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"MCP execution error: {str(e)}")
            raise

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception(_is_retryable_log_error),
        reraise=False,  # raises RetryError on exhaustion; caught by log_interaction
    )
    async def _post_log_with_retry(self, payload: dict) -> None:
        """Internal: single POST attempt, decorated for automatic retry."""
        response = await self._client.post(
            f"{self.base_url}/log-interaction",
            json=payload,
            timeout=5.0,
        )
        response.raise_for_status()

    async def log_interaction(self, payload: dict) -> None:
        """Post an interaction log record to the MCP server.

        Retries up to 4 attempts (initial + 3 retries) with exponential
        backoff (2 s → 4 s → 8 s, capped at 10 s) on transient network
        errors and 5xx responses.  4xx responses are not retried.

        This method never raises — failures are absorbed so that a logging
        outage cannot disrupt the chat flow (it is called as a background task).
        """
        try:
            await self._post_log_with_retry(payload)
        except RetryError as exc:
            last = exc.last_attempt.exception()
            logger.error(
                "⚠️  [MCP] Interaction log permanently failed after all retries "
                "— data loss has occurred. "
                f"Last error: {type(last).__name__}: {last}"
            )
        except Exception as exc:
            # Non-retryable error (e.g. 4xx bad payload) — log and discard.
            logger.warning(f"Failed to log interaction to MCP (non-retryable): {exc}")

    async def verify_business_owner(self, user_id: str, business_id: str) -> bool:
        """Return True if user_id holds the 'owner' role for business_id."""
        try:
            response = await self._client.post(
                f"{self.base_url}/internal/verify-owner",
                json={"user_id": user_id, "business_id": business_id},
                timeout=10.0,
            )
            response.raise_for_status()
            return response.json().get("is_owner", False)
        except Exception as e:
            logger.error(f"verify_business_owner error: {e}")
            return False

    async def health_check(self) -> bool:
        """Check MCP server health"""
        try:
            response = await self._client.get(
                f"{self.base_url}/health",
                timeout=5.0
            )
            return response.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        """Close the underlying HTTP client, releasing all connections."""
        await self._client.aclose()

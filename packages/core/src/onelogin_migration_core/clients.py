"""HTTP client abstractions for source providers and OneLogin."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from collections.abc import Generator, Iterable
from typing import Any, Protocol, runtime_checkable

import requests
from requests.utils import parse_header_links

from .config import MigrationSettings, OneLoginApiSettings, SourceApiSettings

LOGGER = logging.getLogger(__name__)
REQUEST_TIMEOUT = 30


class RateLimiter:
    """Simple token bucket style limiter for API calls."""

    def __init__(self, max_calls: int, interval_seconds: float) -> None:
        self.max_calls = max_calls
        self.interval = interval_seconds
        self._events: deque[float] = deque()
        self._lock = threading.Lock()

    def wait(self) -> None:
        """Block until it is safe to perform the next call."""

        if not self.max_calls:
            return
        while True:
            with self._lock:
                now = time.monotonic()
                while self._events and now - self._events[0] > self.interval:
                    self._events.popleft()
                if len(self._events) < self.max_calls:
                    self._events.append(now)
                    return
                sleep_for = self.interval - (now - self._events[0])
            if sleep_for > 0:
                time.sleep(sleep_for)


class OktaSourceClient:
    """Source client implementation for the Okta Admin API."""

    def __init__(self, settings: SourceApiSettings, session: requests.Session | None = None) -> None:
        self.settings = settings

        if session is None:
            from requests.adapters import HTTPAdapter

            session = requests.Session()

            # Configure connection pool for better performance with concurrent requests
            adapter = HTTPAdapter(
                pool_connections=20,  # Cache 20 connection pools
                pool_maxsize=20,  # Max 20 connections per pool
                pool_block=False,  # Don't block when pool exhausted
            )

            session.mount("https://", adapter)
            session.mount("http://", adapter)

        self.session = session
        self.rate_limiter = RateLimiter(settings.rate_limit_per_minute, 60)

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        url = self._build_url(path)
        headers = kwargs.pop("headers", {})
        headers.setdefault("Accept", "application/json")
        headers.setdefault("Content-Type", "application/json")
        headers.setdefault("Authorization", f"SSWS {self.settings.token}")

        while True:
            self.rate_limiter.wait()
            try:
                response = self.session.request(
                    method, url, headers=headers, timeout=REQUEST_TIMEOUT, **kwargs
                )
            except requests.Timeout as exc:
                LOGGER.error(
                    "%s API timeout on %s %s: %s",
                    self.settings.provider_display_name,
                    method.upper(),
                    url,
                    exc,
                )
                raise
            except requests.RequestException as exc:
                LOGGER.error(
                    "%s API request error on %s %s: %s",
                    self.settings.provider_display_name,
                    method.upper(),
                    url,
                    exc,
                )
                raise
            if response.status_code == 429:
                reset = response.headers.get("X-Rate-Limit-Reset")
                if reset:
                    try:
                        reset_time = float(reset)
                        sleep_for = max(reset_time - time.time(), 1)
                    except ValueError:
                        sleep_for = 1
                else:
                    sleep_for = 1
                LOGGER.warning(
                    "%s rate limit exceeded, sleeping for %.2f seconds",
                    self.settings.provider_display_name,
                    sleep_for,
                )
                time.sleep(sleep_for)
                continue
            response.raise_for_status()
            return response

    def _build_url(self, path: str) -> str:
        base = self.settings.api_base_url().rstrip("/")
        if path.startswith("http"):
            return path
        normalized = path.lstrip("/")
        if not normalized.startswith("api/v1"):
            normalized = f"api/v1/{normalized}"
        return f"{base}/{normalized}"

    def _paginate(
        self, path: str, params: dict[str, Any] | None = None
    ) -> Generator[dict[str, Any], None, None]:
        url = self._build_url(path)
        query = params or {}
        query.setdefault("limit", self.settings.page_size)
        while url:
            response = self._request("GET", url, params=query)
            data = response.json()
            if isinstance(data, list):
                for item in data:
                    yield item
            else:
                yield data
            url = self._next_link(response)
            query = None

    @staticmethod
    def _next_link(response: requests.Response) -> str | None:
        link_header = response.headers.get("link")
        if not link_header:
            return None
        links = parse_header_links(link_header.rstrip(">").replace(">,", ">, "))
        for link in links:
            if link.get("rel") == "next":
                return link.get("url")
        return None

    def test_connection(self) -> tuple[bool, str]:
        """Verify API connectivity and credentials."""
        try:
            url = f"{self.settings.api_base_url()}/api/v1/users?limit=1"
            response = self.session.get(
                url,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"SSWS {self.settings.token}",
                },
                timeout=15,
            )
            name = self.settings.provider_display_name
            if response.ok:
                return True, f"Successfully validated {name} API token."
            if response.status_code == 401:
                return False, f"{name} API token is invalid or lacks required scopes."
            return (
                False,
                f"{name} connection failed: {response.status_code} {response.text.strip()[:200]}",
            )
        except requests.Timeout:
            return False, f"{self.settings.provider_display_name} connection timed out."
        except requests.RequestException as exc:
            return False, f"Connection error: {exc}"

    def list_users(self) -> list[dict[str, Any]]:
        LOGGER.info("Fetching users from Okta")
        return list(self._paginate("users"))

    def list_groups(self) -> list[dict[str, Any]]:
        LOGGER.info("Fetching groups from Okta")
        return list(self._paginate("groups"))

    def list_group_memberships(
        self, groups: Iterable[dict[str, Any]] | None = None
    ) -> list[dict[str, Any]]:
        LOGGER.info("Fetching group memberships from Okta")
        memberships: list[dict[str, Any]] = []
        group_iterable: Iterable[dict[str, Any]]
        if groups is None:
            group_iterable = self.list_groups()
        else:
            group_iterable = groups

        for group in group_iterable:
            group_id = group.get("id") if isinstance(group, dict) else None
            if not group_id:
                continue
            for member in self._paginate(f"groups/{group_id}/users"):
                if not isinstance(member, dict):
                    continue
                user_id = member.get("id")
                if not user_id:
                    continue
                memberships.append({"group_id": str(group_id), "user_id": str(user_id)})
        return memberships

    def list_applications(self) -> list[dict[str, Any]]:
        LOGGER.info("Fetching applications from Okta")
        # Note: expand=group parameter causes 400 errors on some Okta instances
        # Fetch apps without expand, then fetch groups separately if needed
        applications = list(self._paginate("apps"))

        for app in applications:
            embedded = app.get("_embedded") or {}
            raw_groups = embedded.get("group")

            if isinstance(raw_groups, dict):
                # Some Okta APIs return a mapping with an "items" key when expanded.
                raw_groups = raw_groups.get("items", [])

            if isinstance(raw_groups, list):
                groups = raw_groups
            elif raw_groups:
                groups = raw_groups  # type: ignore[assignment]
            else:
                app_id = app.get("id")
                groups = list(self._paginate(f"apps/{app_id}/groups")) if app_id else []

            embedded["group"] = list(groups)
            app["_embedded"] = embedded

        return applications

    def list_policies(self) -> list[dict[str, Any]]:
        """Fetch all policies from Okta (sign-on, password, MFA, etc.).

        Note: Returns empty list if API access is restricted.
        """
        LOGGER.info("Fetching policies from Okta")
        try:
            # Fetch all policy types
            all_policies = []
            policy_types = ["OKTA_SIGN_ON", "PASSWORD", "MFA_ENROLL", "OAUTH_AUTHORIZATION_POLICY"]

            for policy_type in policy_types:
                try:
                    policies = list(self._paginate(f"policies?type={policy_type}"))
                    all_policies.extend(policies)
                except requests.HTTPError as exc:
                    if exc.response.status_code in (400, 401, 403, 404):
                        LOGGER.debug(f"Policy type {policy_type} not accessible")
                        continue
                    raise

            return all_policies
        except requests.HTTPError as exc:
            if exc.response.status_code in (400, 401, 403, 404):
                LOGGER.warning("Policies API not accessible (may require additional permissions)")
                return []
            raise

    def list_authenticators(self) -> list[dict[str, Any]]:
        """Fetch configured MFA authenticators from Okta.

        Note: Returns empty list if API access is restricted.
        """
        LOGGER.info("Fetching authenticators from Okta")
        candidate_paths: tuple[tuple[str, bool], ...] = (
            ("org/authenticators", False),
            ("authenticators", False),
            ("org/factors", True),
        )
        last_error: requests.HTTPError | None = None

        for path, normalize_factor in candidate_paths:
            try:
                records = list(self._paginate(path))
                if normalize_factor:
                    records = [
                        {
                            "id": factor.get("id"),
                            "name": factor.get("name") or factor.get("factorType"),
                            "type": factor.get("factorType"),
                            "provider": factor.get("provider"),
                            "status": factor.get("status"),
                            "raw_factor": factor,
                        }
                        for factor in records
                        if isinstance(factor, dict)
                    ]
                if records:
                    LOGGER.info(
                        "Fetched %s authenticators using endpoint '%s'",
                        len(records),
                        path,
                    )
                else:
                    LOGGER.info("Authenticator endpoint '%s' returned no records", path)
                return records
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status in (400, 401, 403, 404, 405):
                    LOGGER.debug(
                        "Authenticators endpoint '%s' not accessible (status %s), trying next option",
                        path,
                        status,
                    )
                    last_error = exc
                    continue
                raise

        if last_error is not None:
            LOGGER.warning(
                "Authenticators API not accessible on any known endpoint (last status %s)",
                last_error.response.status_code if last_error.response is not None else "unknown",
            )
            return []

        return []

    def list_identity_providers(self) -> list[dict[str, Any]]:
        """Fetch identity providers (directories) from Okta.

        Note: Returns empty list if API access is restricted.
        """
        LOGGER.info("Fetching identity providers from Okta")
        try:
            return list(self._paginate("idps"))
        except requests.HTTPError as exc:
            if exc.response.status_code in (400, 401, 403, 404):
                LOGGER.warning(
                    "Identity Providers API not accessible (may require additional permissions)"
                )
                return []
            raise

    def list_group_rules(self) -> list[dict[str, Any]]:
        """Fetch dynamic group rules from Okta.

        Note: Returns empty list if API access is restricted.
        """
        LOGGER.info("Fetching group rules from Okta")
        try:
            return list(self._paginate("groups/rules"))
        except requests.HTTPError as exc:
            if exc.response.status_code in (400, 401, 403, 404):
                LOGGER.warning(
                    "Group Rules API not accessible (may require additional permissions)"
                )
                return []
            raise

    def export_all(
        self, categories: dict[str, bool] | None = None
    ) -> dict[str, list[dict[str, Any]]]:
        """Retrieve selected resources from Okta in a single pass.

        Parameters
        ----------
        categories:
            Optional mapping of migration categories to a boolean flag
            indicating whether the category should be included in the
            export. When omitted all categories are exported.
        """

        categories = categories or {}
        include_users = categories.get("users", True)
        include_groups = categories.get("groups", True)
        include_applications = categories.get("applications", True)

        users = self.list_users() if include_users else []
        groups = self.list_groups() if include_groups else []
        if include_groups and include_users:
            memberships = self.list_group_memberships(groups)
        else:
            memberships = []
        applications = self.list_applications() if include_applications else []

        return {
            "users": users,
            "groups": groups,
            "memberships": memberships,
            "applications": applications,
        }


class OneLoginClient:
    """Minimal client for interacting with the OneLogin API."""

    def __init__(
        self,
        settings: OneLoginApiSettings,
        session: requests.Session | None = None,
        dry_run: bool = False,
    ) -> None:
        self.settings = settings

        if session is None:
            from requests.adapters import HTTPAdapter

            session = requests.Session()

            # Configure connection pool for better performance with concurrent requests
            adapter = HTTPAdapter(
                pool_connections=20,  # Cache 20 connection pools
                pool_maxsize=20,  # Max 20 connections per pool
                pool_block=False,  # Don't block when pool exhausted
            )

            session.mount("https://", adapter)
            session.mount("http://", adapter)

        self.session = session

        # Calculate per-minute rate limit from configured hourly limit
        # Use 90% of the limit to provide safety buffer
        max_calls_per_minute = int((settings.rate_limit_per_hour * 0.9) / 60)
        self.rate_limiter = RateLimiter(max_calls_per_minute, 60)

        self.dry_run = dry_run
        self._token: str | None = None
        self._token_expiration: float = 0
        self._custom_attribute_cache: set[str] = set()
        self._custom_attribute_cache_loaded = False
        self._token_lock = threading.Lock()
        self._custom_attribute_lock = threading.Lock()
        self._rate_limit_remaining: int | None = None
        self._rate_limit_lock = threading.Lock()

    @staticmethod
    def _first_entity(payload: Any) -> dict[str, Any] | None:
        """Return the first dict-like entity containing an ``id`` field."""

        if isinstance(payload, dict):
            if isinstance(payload.get("id"), (int, str)):
                return payload
            for key in ("data", "role", "user", "app", "application"):
                if key in payload:
                    entity = OneLoginClient._first_entity(payload[key])
                    if entity:
                        return entity
        elif isinstance(payload, list):
            for item in payload:
                entity = OneLoginClient._first_entity(item)
                if entity:
                    return entity
        return None

    def _build_url(self, path: str) -> str:
        base = self.settings.api_base_url().rstrip("/")
        if path.startswith("http"):
            return path
        normalized = path.lstrip("/")
        return f"{base}/{normalized}"

    def _refresh_token(self) -> None:
        url = self.settings.token_url()
        payload = {
            "grant_type": "client_credentials",
            "client_id": self.settings.client_id,
            "client_secret": self.settings.client_secret,
        }
        response = self.session.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        self._token = data["access_token"]
        expires_in = data.get("expires_in", 3600)
        self._token_expiration = time.time() + expires_in - 30
        LOGGER.debug("Obtained OneLogin access token valid for %s seconds", expires_in)

    def _get_token(self) -> str:
        with self._token_lock:
            if not self._token or time.time() >= self._token_expiration:
                self._refresh_token()
            return self._token  # type: ignore[return-value]

    def _update_rate_limit_from_headers(self, headers: dict[str, Any]) -> None:
        """Track rate limit info from response headers for adaptive throttling."""
        remaining_str = headers.get("X-RateLimit-Remaining")
        if remaining_str:
            try:
                remaining = int(remaining_str)
                with self._rate_limit_lock:
                    self._rate_limit_remaining = remaining

                # Log warnings when approaching rate limit
                if remaining < 100:
                    LOGGER.warning("OneLogin rate limit low: %d requests remaining", remaining)
                elif remaining < 500:
                    LOGGER.info("OneLogin rate limit status: %d requests remaining", remaining)

                # Proactive slowdown when rate limit is getting low
                if remaining < 50:
                    slowdown = 2.0  # 2 second pause
                    LOGGER.warning(
                        "Rate limit critically low (%d remaining). Pausing %.1fs to avoid 429 errors...",
                        remaining,
                        slowdown,
                    )
                    time.sleep(slowdown)
                elif remaining < 200:
                    slowdown = 0.5  # 500ms pause
                    LOGGER.info(
                        "Rate limit low (%d remaining). Pausing %.1fs...", remaining, slowdown
                    )
                    time.sleep(slowdown)
            except (ValueError, TypeError):
                pass

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        url = self._build_url(path)
        headers = kwargs.pop("headers", {})
        headers.setdefault("Content-Type", "application/json")

        self._log_request_payload(method, url, kwargs)

        # Track if we've already retried with token refresh (prevent infinite loop)
        token_refresh_attempted = False
        retry_count = 0

        while True:
            # Get fresh token and set authorization header
            headers["Authorization"] = f"Bearer {self._get_token()}"

            self.rate_limiter.wait()

            # Log before making request
            if retry_count > 0:
                LOGGER.info(
                    "OneLogin API request (retry %d): %s %s", retry_count, method.upper(), url
                )
            else:
                LOGGER.info("OneLogin API request: %s %s", method.upper(), url)

            request_start = time.time()
            try:
                response = self.session.request(
                    method, url, headers=headers, timeout=REQUEST_TIMEOUT, **kwargs
                )
                request_duration = time.time() - request_start
                LOGGER.info(
                    "OneLogin API response received in %.2fs: %s %s -> %d",
                    request_duration,
                    method.upper(),
                    url,
                    response.status_code,
                )
            except requests.Timeout as exc:
                request_duration = time.time() - request_start
                LOGGER.warning(
                    "OneLogin API timeout after %.2fs on %s %s: %s",
                    request_duration,
                    method.upper(),
                    url,
                    exc,
                )

                # Retry timeout errors with exponential backoff (up to 3 retries)
                max_retries = 3
                if retry_count <= max_retries:
                    backoff_delay = min(2**retry_count, 30)  # Cap at 30 seconds
                    LOGGER.warning(
                        "Retrying after %.2fs (attempt %d of %d)...",
                        backoff_delay,
                        retry_count,
                        max_retries,
                    )
                    time.sleep(backoff_delay)
                    continue
                else:
                    LOGGER.error(
                        "Max retries (%d) exceeded for %s %s", max_retries, method.upper(), url
                    )
                    LOGGER.error(
                        "Timeout details - Method: %s, URL: %s, Timeout setting: %ds",
                        method.upper(),
                        url,
                        REQUEST_TIMEOUT,
                    )
                    raise
            except requests.RequestException as exc:
                request_duration = time.time() - request_start
                LOGGER.error(
                    "OneLogin API request error after %.2fs on %s %s: %s",
                    request_duration,
                    method.upper(),
                    url,
                    exc,
                )
                raise

            retry_count += 1

            # Track rate limit from response headers
            self._update_rate_limit_from_headers(response.headers)

            # Handle 502 Bad Gateway (API overload) with exponential backoff
            if response.status_code == 502:
                max_retries = 3
                if retry_count <= max_retries:
                    backoff_delay = min(2**retry_count * 5, 60)  # 5s, 10s, 20s, cap at 60s
                    LOGGER.warning(
                        "OneLogin API returned 502 Bad Gateway (API overloaded). "
                        "Retrying after %.2fs (attempt %d of %d)...",
                        backoff_delay,
                        retry_count,
                        max_retries,
                    )
                    time.sleep(backoff_delay)
                    continue
                else:
                    LOGGER.error(
                        "Max retries (%d) exceeded for 502 errors on %s %s",
                        max_retries,
                        method.upper(),
                        url,
                    )

            # Handle rate limiting
            if response.status_code == 429:
                reset = response.headers.get("X-RateLimit-Reset")
                sleep_for = 60
                if reset:
                    try:
                        reset_ts = float(reset)
                        sleep_for = max(reset_ts - time.time(), 1)
                    except ValueError:
                        pass
                LOGGER.warning("OneLogin rate limit exceeded, sleeping for %.2f seconds", sleep_for)
                time.sleep(sleep_for)
                continue

            # Handle token expiration (401 Unauthorized)
            if response.status_code == 401 and not token_refresh_attempted:
                LOGGER.warning("OneLogin API returned 401, refreshing token and retrying")
                # Force token refresh
                with self._token_lock:
                    self._token = None
                    self._token_expiration = 0
                token_refresh_attempted = True
                continue

            try:
                response.raise_for_status()
            except requests.HTTPError:
                # Check if this is a duplicate user error (422 with unique constraint violation)
                # These are expected during migration and should be logged as INFO, not ERROR
                if response.status_code == 422 and self._is_duplicate_user_error(response):
                    err_snippet = self._summarize_error_response(response)
                    # Extract just the validation message, not the full error details
                    try:
                        data = response.json()
                        message = data.get("message", err_snippet)
                    except Exception:
                        message = err_snippet

                    LOGGER.info(
                        "User already exists (will update existing record): %s",
                        message,
                    )
                    # Don't log full error details for duplicate users - it's expected behavior
                else:
                    # Provide detailed context about the failure to aid debugging
                    err_snippet = self._summarize_error_response(response)
                    LOGGER.error("OneLogin API error on %s %s: %s", method, url, err_snippet)

                    # Log detailed debugging information for all HTTP errors
                    self._log_error_details(method, url, kwargs, response, level=logging.ERROR)

                raise
            return response

    def _log_request_payload(self, method: str, url: str, kwargs: dict[str, Any]) -> None:
        if not LOGGER.isEnabledFor(logging.DEBUG):
            return
        if method.upper() not in {"POST", "PUT", "PATCH"}:
            return
        body: Any | None = None
        if "json" in kwargs:
            body = kwargs["json"]
        elif "data" in kwargs:
            body = kwargs["data"]
        if body is None:
            return
        try:
            serialized = json.dumps(body, default=str)
        except TypeError:
            serialized = str(body)
        LOGGER.debug("OneLogin %s %s payload: %s", method.upper(), url, serialized[:1000])

    @staticmethod
    def _summarize_error_response(response: requests.Response) -> str:
        try:
            data = response.json()
            # Common OneLogin error envelope
            status = data.get("status") if isinstance(data, dict) else None
            msg = status.get("message") if isinstance(status, dict) else None
            code = status.get("code") if isinstance(status, dict) else None
            # Include field-level errors if present
            details = data.get("errors") if isinstance(data, dict) else None
            parts = []
            if msg:
                parts.append(str(msg))
            if code:
                parts.append(f"code={code}")
            if details:
                parts.append(f"errors={str(details)[:300]}")
            if parts:
                return f"{response.status_code} {response.reason} - " + "; ".join(parts)
            return f"{response.status_code} {response.reason} - {json.dumps(data)[:300]}"
        except Exception:
            text = (response.text or "").strip().replace("\n", " ")
            return f"{response.status_code} {response.reason} - {text[:300]}"

    def _log_error_details(
        self,
        method: str,
        url: str,
        kwargs: dict[str, Any],
        response: requests.Response,
        level: int = logging.ERROR,
    ) -> None:
        """Log detailed information for HTTP errors to aid debugging.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Request URL
            kwargs: Request keyword arguments
            response: HTTP response object
            level: Logging level (default: logging.ERROR)
        """
        LOGGER.log(level, "=" * 80)
        LOGGER.log(level, "HTTP ERROR DETAILS")
        LOGGER.log(level, "=" * 80)

        # Log request details
        LOGGER.log(level, "Request: %s %s", method.upper(), url)

        # Log request payload if present
        body: Any | None = None
        if "json" in kwargs:
            body = kwargs["json"]
        elif "data" in kwargs:
            body = kwargs["data"]

        if body is not None:
            try:
                serialized = json.dumps(body, indent=2, default=str)
                LOGGER.log(level, "Request Payload:\n%s", serialized)
            except Exception as e:
                LOGGER.log(level, "Request Payload (could not serialize): %s", str(body)[:2000])
                LOGGER.log(level, "Serialization error: %s", e)
        else:
            LOGGER.log(level, "Request Payload: (none)")

        # Log query parameters if present
        params = kwargs.get("params")
        if params:
            LOGGER.log(level, "Query Parameters: %s", params)

        # Log response details
        LOGGER.log(level, "Response Status: %s %s", response.status_code, response.reason)
        LOGGER.log(level, "Response Headers: %s", dict(response.headers))

        # Log response body
        try:
            response_json = response.json()
            LOGGER.log(level, "Response Body (JSON):\n%s", json.dumps(response_json, indent=2))
        except Exception:
            response_text = response.text or ""
            # For HTML responses, log the first 2000 characters
            if response_text:
                LOGGER.log(
                    level, "Response Body (Text, first 2000 chars):\n%s", response_text[:2000]
                )
            else:
                LOGGER.log(level, "Response Body: (empty)")

        LOGGER.log(level, "=" * 80)

    def _dry_run_log(self, action: str, payload: dict[str, Any]) -> None:
        LOGGER.info("[DRY-RUN] %s: %s", action, json.dumps(payload, default=str)[:400])

    def ensure_role(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        action = "ensure_role"
        if self.dry_run:
            self._dry_run_log(action, payload)
            return None

        try:
            raw = self._request("POST", "api/2/roles", json=payload).json()
            entity = self._first_entity(raw)
            return entity or raw
        except requests.HTTPError as e:
            # Provide enhanced error context for role creation failures
            if e.response is not None and e.response.status_code == 422:
                try:
                    error_data = e.response.json()
                    role_name = payload.get("name", "Unknown")

                    # Log detailed error information
                    LOGGER.error(
                        "Failed to create role '%s': Validation error from OneLogin API",
                        role_name,
                    )
                    LOGGER.error("Role payload: %s", json.dumps(payload, indent=2, default=str))
                    LOGGER.error(
                        "OneLogin validation errors: %s",
                        json.dumps(error_data, indent=2, default=str),
                    )

                    # Create a more informative error message
                    error_details = json.dumps(error_data, default=str)[:500]
                    payload_str = json.dumps(payload, default=str)
                    new_message = (
                        f"422 Unprocessable Entity for role '{role_name}'. "
                        f"Payload: {payload_str}. "
                        f"OneLogin error: {error_details}"
                    )

                    # Create new exception with enhanced message
                    new_exc = requests.HTTPError(new_message, response=e.response)
                    raise new_exc from e
                except json.JSONDecodeError:
                    # If we can't parse the error response, just re-raise original
                    pass
            raise

    def ensure_user(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        action = "ensure_user"
        if self.dry_run:
            self._dry_run_log(action, payload)
            return None
        custom_attrs = payload.get("custom_attributes")
        if isinstance(custom_attrs, dict) and custom_attrs:
            self.ensure_custom_attribute_definitions(custom_attrs)
        username = payload.get("username") or payload.get("email")
        email = payload.get("email")

        # Optimized approach: Try to create first, handle duplicate on 422 error
        # This reduces API calls from 2-3 per user to just 1 for new users
        try:
            raw = self._request("POST", "api/2/users", json=payload).json()
            entity = self._first_entity(raw)
            return entity or raw
        except requests.HTTPError as exc:
            resp = getattr(exc, "response", None)
            if resp is not None and resp.status_code == 422:
                # Check if this is a duplicate user error (email or username already exists)
                if self._is_duplicate_user_error(resp):
                    # User already exists - find and update them
                    user_id = self._find_user_id(username=username, email=email)
                    if user_id:
                        try:
                            raw = self._request(
                                "PUT", f"api/2/users/{user_id}", json=payload
                            ).json()
                            entity = self._first_entity(raw)
                            return entity or raw
                        except requests.HTTPError as update_exc:
                            update_resp: requests.Response | None = getattr(
                                update_exc, "response", None
                            )
                            if update_resp is not None and self._is_account_owner_update_error(
                                update_resp
                            ):
                                LOGGER.warning(
                                    "Skipping update for OneLogin account owner (user id %s); continuing without modification.",
                                    user_id,
                                )
                                return {"id": user_id}
                            raise
            raise

    def _find_user_id(self, *, username: str | None, email: str | None) -> int | None:
        """Find a user id by email (preferred) or username.

        Email is the primary unique identifier in OneLogin, so we check that first.
        Only falls back to username if email is not provided.
        """
        # Prefer email lookup - it's unique and required in OneLogin
        if email:
            try:
                response = self._request("GET", "api/2/users", params={"email": email})
                data = response.json()
                if data and isinstance(data, list) and data[0].get("id"):
                    return int(data[0]["id"])  # type: ignore[index]
            except requests.HTTPError:
                # Email lookup failed, but don't try username - email should be definitive
                return None

        # Fallback to username only if no email provided
        if username:
            try:
                response = self._request("GET", "api/2/users", params={"username": username})
                data = response.json()
                if data and isinstance(data, list) and data[0].get("id"):
                    return int(data[0]["id"])  # type: ignore[index]
            except requests.HTTPError:
                pass

        return None

    def find_app_by_name(self, name: str) -> dict[str, Any] | None:
        """Find an existing app by exact name match.

        Args:
            name: The exact name of the app to find

        Returns:
            The app object if found, None otherwise
        """
        if self.dry_run:
            return None

        try:
            # Use exact name filter (no wildcard)
            response = self._request("GET", "api/2/apps", params={"name": name})
            apps = response.json()

            # OneLogin API returns an array; find exact match
            if isinstance(apps, list):
                for app in apps:
                    if isinstance(app, dict) and app.get("name") == name:
                        return app
            return None
        except Exception as e:
            LOGGER.debug("Error checking for existing app '%s': %s", name, e)
            return None

    def ensure_application(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        action = "ensure_application"
        if self.dry_run:
            self._dry_run_log(action, payload)
            return None

        app_name = payload.get("name", "unknown")

        # Check if app with this name already exists
        existing_app = self.find_app_by_name(app_name)
        if existing_app:
            LOGGER.warning(
                "App '%s' already exists in OneLogin (id=%s); skipping creation and reusing existing app.",
                app_name,
                existing_app.get("id"),
            )
            return existing_app

        # Log if we're attempting to pass parameters
        parameters = payload.get("parameters")
        if parameters:
            LOGGER.debug(
                "Creating app '%s' with %d parameters (connector_id=%s)",
                app_name,
                len(parameters),
                payload.get("connector_id", "unknown"),
            )

        try:
            # Log the full payload for debugging 422 errors
            LOGGER.debug(
                "Creating app '%s' with payload: %s",
                payload.get("name", "unknown"),
                json.dumps(payload, indent=2, default=str)[:2000],  # Truncate to 2000 chars
            )
            raw = self._request("POST", "api/2/apps", json=payload).json()
            entity = self._first_entity(raw)
            return entity or raw
        except requests.HTTPError as e:
            # Enhanced error logging for validation errors
            if e.response is not None:
                status_code = e.response.status_code
                # 400/422 typically indicate validation errors
                if status_code in (400, 422):
                    LOGGER.error(
                        "App creation failed with status %d for app '%s' (connector_id=%s)",
                        status_code,
                        payload.get("name", "unknown"),
                        payload.get("connector_id", "unknown"),
                    )
                    # Log the full error response from OneLogin
                    try:
                        error_data = e.response.json()
                        LOGGER.error(
                            "OneLogin API error response: %s",
                            json.dumps(error_data, indent=2, default=str)[:1000],
                        )
                    except Exception:
                        # Log raw response text if JSON parsing fails
                        try:
                            LOGGER.error("OneLogin API error (raw): %s", e.response.text[:1000])
                        except Exception:
                            pass
                    # Log parameters if present
                    if parameters:
                        LOGGER.error(
                            "This may indicate that some parameters are not supported by this connector."
                        )
                        LOGGER.error(
                            "Attempted parameters: %s",
                            list(parameters.keys()),
                        )

                    # Provide actionable suggestions for common 422 causes
                    LOGGER.error("Possible causes for 422 error:")
                    LOGGER.error(
                        "  1. Connector ID %s may not exist or may not be available in your OneLogin instance",
                        payload.get("connector_id"),
                    )
                    LOGGER.error(
                        "     → Check the OneLogin admin console under Applications > Catalog"
                    )
                    LOGGER.error("     → Search for the app and verify the connector ID matches")
                    LOGGER.error(
                        "  2. An app with name '%s' may already exist (but duplicate check passed)",
                        payload.get("name"),
                    )
                    LOGGER.error(
                        "  3. The signon_mode '%s' may not be compatible with this connector",
                        payload.get("signon_mode"),
                    )
                    LOGGER.error(
                        "  4. The connector may require specific parameters that are missing"
                    )
                    LOGGER.error("  5. Your OneLogin plan may not include this connector type")

                    # Retry without signon_mode if it was present
                    if status_code == 422 and "signon_mode" in payload:
                        LOGGER.warning("Retrying app creation without signon_mode field...")
                        retry_payload = {k: v for k, v in payload.items() if k != "signon_mode"}
                        try:
                            LOGGER.debug(
                                "Retry payload for '%s': %s",
                                retry_payload.get("name", "unknown"),
                                json.dumps(retry_payload, indent=2, default=str)[:2000],
                            )
                            raw = self._request("POST", "api/2/apps", json=retry_payload).json()
                            entity = self._first_entity(raw)
                            LOGGER.info(
                                "App '%s' created successfully after removing signon_mode",
                                payload.get("name", "unknown"),
                            )
                            return entity or raw
                        except requests.HTTPError as retry_e:
                            LOGGER.error("Retry without signon_mode also failed: %s", retry_e)
                            # Fall through to re-raise original error

            # Re-raise to let normal error handling proceed
            raise

    def list_connectors(self, limit: int = 1000) -> list[dict[str, Any]]:
        """Retrieve all available OneLogin application connectors."""

        if self.dry_run:
            LOGGER.info("[DRY-RUN] Skipping OneLogin connector fetch.")
            return []

        LOGGER.info("Fetching OneLogin connectors (batch size=%s)", limit)
        connectors: list[dict[str, Any]] = []
        cursor: str | None = None

        while True:
            params: dict[str, Any] = {"limit": limit}
            if cursor:
                params["cursor"] = cursor

            response = self._request("GET", "api/2/connectors", params=params)
            payload = response.json() or {}

            if isinstance(payload, list):
                connectors.extend(payload)
                pagination = {}
            else:
                data = payload.get("data") or []
                if isinstance(data, list):
                    connectors.extend(data)
                elif isinstance(data, dict):
                    connectors.append(data)
                pagination = payload.get("pagination") or {}

            cursor = pagination.get("cursor") or pagination.get("next_cursor")
            has_more = bool(pagination.get("has_more"))

            if not has_more or not cursor:
                break

        LOGGER.info("Retrieved %d OneLogin connectors", len(connectors))
        return connectors

    def list_roles(self) -> list[dict[str, Any]]:
        if self.dry_run:
            return []
        response = self._request("GET", "api/2/roles")
        data = response.json()
        if isinstance(data, dict):
            items = data.get("data")
            if isinstance(items, list):
                return items
            return []
        if isinstance(data, list):
            return data
        return []

    def delete_role(self, role_id: int) -> None:
        if self.dry_run:
            self._dry_run_log(f"delete_role({role_id})", {})
            return
        self._request("DELETE", f"api/2/roles/{role_id}")

    @staticmethod
    def _is_duplicate_user_error(response: requests.Response) -> bool:
        """Check if a 422 error indicates the user already exists (duplicate email/username).

        Example error: {'message': 'Validation failed: Email must be unique within jbudde-dev',
                       'statusCode': 422, 'name': 'UnprocessableEntityError'}
        """
        try:
            data = response.json()
        except ValueError:
            data = {}

        message_parts: list[str] = []
        if isinstance(data, dict):
            for key in ("message", "description", "error"):
                value = data.get(key)
                if isinstance(value, str):
                    message_parts.append(value)
            status = data.get("status")
            if isinstance(status, dict):
                value = status.get("message")
                if isinstance(value, str):
                    message_parts.append(value)

        text = " ".join(message_parts).lower() or response.text.lower() or ""
        # Check for OneLogin's duplicate user error pattern
        return (
            "must be unique within" in text
            or "email must be unique" in text
            or "username must be unique" in text
        )

    @staticmethod
    def _is_account_owner_update_error(response: requests.Response) -> bool:
        try:
            data = response.json()
        except ValueError:
            data = {}
        message_parts: list[str] = []
        if isinstance(data, dict):
            for key in ("message", "description"):
                value = data.get(key)
                if isinstance(value, str):
                    message_parts.append(value)
            status = data.get("status")
            if isinstance(status, dict):
                value = status.get("message")
                if isinstance(value, str):
                    message_parts.append(value)
            name = data.get("name")
            if isinstance(name, str):
                message_parts.append(name)
        text = " ".join(message_parts) or response.text or ""
        return "account owner" in text.lower()

    def get_role_apps(self, role_id: int) -> list[int]:
        """Get list of app IDs currently assigned to a role."""
        if self.dry_run:
            return []
        try:
            response = self._request("GET", f"api/2/roles/{role_id}/apps")
            data = response.json()
            # API returns an array of app IDs
            if isinstance(data, list):
                return [int(app_id) for app_id in data if app_id is not None]
            return []
        except Exception as e:
            LOGGER.warning("Failed to get apps for role %d: %s", role_id, e)
            return []

    def assign_role_to_app(self, app_id: int, role_id: int) -> None:
        """Assign an app to a role using the correct OneLogin API endpoint.

        Note: OneLogin requires sending the complete list of app IDs for a role,
        not individual assignments. This method fetches current apps, adds the new
        app, and updates the complete list.
        """
        if self.dry_run:
            self._dry_run_log(f"assign_role_to_app({app_id}, {role_id})", {"app_id": app_id})
            return

        # Get current apps for this role
        current_apps = self.get_role_apps(role_id)

        # Add new app if not already present
        if app_id not in current_apps:
            current_apps.append(app_id)
            # OneLogin API requires PUT with complete list of app IDs
            self._request("PUT", f"api/2/roles/{role_id}/apps", json=current_apps)
        else:
            LOGGER.debug("App %d already assigned to role %d, skipping", app_id, role_id)

    def assign_user_to_role(self, user_id: int, role_id: int) -> None:
        payload = {"role_id": role_id}
        if self.dry_run:
            self._dry_run_log(f"assign_user_to_role({user_id})", payload)
            return
        self._request("POST", f"api/2/users/{user_id}/roles", json=payload)

    def assign_users_to_role_bulk(self, role_id: int, user_ids: Iterable[int]) -> None:
        unique_ids = sorted({int(user_id) for user_id in user_ids if user_id is not None})
        if not unique_ids:
            return

        def _chunk(items: list[int], size: int = 50) -> Iterable[list[int]]:
            for index in range(0, len(items), size):
                yield items[index : index + size]

        for chunk in _chunk(unique_ids):
            # OneLogin API expects a plain array, not {"user_ids": [...]}
            # API docs: POST /api/2/roles/{role_id}/users expects array of user IDs
            if self.dry_run:
                self._dry_run_log(f"assign_users_to_role_bulk({role_id})", chunk)
                continue
            try:
                self._request("POST", f"api/2/roles/{role_id}/users", json=chunk)
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code == 404:
                    # Provide helpful context for 404 errors
                    LOGGER.error(
                        "Cannot assign users to role %s: Role or users not found. "
                        "This may indicate:\n"
                        "  1. Role %s doesn't exist in OneLogin (check if role creation failed)\n"
                        "  2. One or more users don't exist: %s\n"
                        "  3. Stale migration state from a previous run\n"
                        "  Suggestion: Clear migration state or verify role/users exist in OneLogin",
                        role_id,
                        role_id,
                        chunk,
                    )
                raise

    # ------------------------------------------------------------------
    # Custom attribute helpers
    # ------------------------------------------------------------------
    def ensure_custom_attribute_definitions(self, custom_attributes: dict[str, Any]) -> None:
        """Ensure custom attribute definitions exist before assigning values."""

        if not custom_attributes:
            return
        names = [
            name for name in custom_attributes.keys() if isinstance(name, str) and name.strip()
        ]
        if not names:
            return
        with self._custom_attribute_lock:
            self._load_custom_attribute_cache()
            for name in names:
                if name in self._custom_attribute_cache:
                    continue
                self._create_custom_attribute(name)
                self._custom_attribute_cache.add(name)

    def _load_custom_attribute_cache(self) -> None:
        if self._custom_attribute_cache_loaded:
            return
        if self.dry_run:
            self._custom_attribute_cache_loaded = True
            return
        try:
            response = self._request("GET", "api/2/users/custom_attributes")
        except requests.HTTPError:
            # If we cannot load existing attributes, bubble the error up so the caller is aware.
            raise
        data = response.json()
        items: Iterable[dict[str, Any]] = []
        if isinstance(data, dict):
            raw_items = data.get("data")
            if isinstance(raw_items, list):
                items = [item for item in raw_items if isinstance(item, dict)]
            elif isinstance(raw_items, dict):
                items = [raw_items]
            elif all(isinstance(k, str) for k in data.keys()):
                items = [data]
        elif isinstance(data, list):
            items = [item for item in data if isinstance(item, dict)]
        cache: set[str] = set()
        for item in items:
            for key in ("shortname", "name"):
                value = item.get(key)
                if isinstance(value, str):
                    trimmed = value.strip()
                    if trimmed:
                        cache.add(trimmed)
        self._custom_attribute_cache = cache
        self._custom_attribute_cache_loaded = True

    def _create_custom_attribute(self, name: str) -> None:
        label = self._derive_custom_attribute_label(name)
        payload = {
            # Per https://developers.onelogin.com/api-docs/2/users/create-custom-attribute
            # the payload must wrap the new field definition under ``user_field``
            # with the human readable ``name`` and API ``shortname`` values.
            "user_field": {
                "name": label,
                "shortname": name,
            }
        }
        if self.dry_run:
            self._dry_run_log("create_custom_attribute", payload)
            self._custom_attribute_cache.add(name)
            return
        try:
            response = self._request("POST", "api/2/users/custom_attributes", json=payload)
        except requests.HTTPError as exc:
            resp = getattr(exc, "response", None)
            if resp is not None:
                status = resp.status_code
                duplicate_error = status in (409, 422) or (
                    status == 400 and self._custom_attribute_already_exists(resp)
                )
                if duplicate_error:
                    # Someone else may have created the attribute between our cache check and POST.
                    self._custom_attribute_cache_loaded = False
                    self._load_custom_attribute_cache()
                    if name in self._custom_attribute_cache:
                        return
            raise
        data = response.json()
        if isinstance(data, dict):
            created = data.get("data")
            if isinstance(created, dict):
                created_name = created.get("shortname") or created.get("name")
                if isinstance(created_name, str) and created_name.strip():
                    self._custom_attribute_cache.add(created_name)
                    return
            if isinstance(created, list):
                for item in created:
                    if not isinstance(item, dict):
                        continue
                    created_name = item.get("shortname") or item.get("name")
                    if isinstance(created_name, str) and created_name.strip():
                        self._custom_attribute_cache.add(created_name)
                        return
            created_name = data.get("shortname") or data.get("name")
            if isinstance(created_name, str) and created_name.strip():
                self._custom_attribute_cache.add(created_name)

    def _custom_attribute_already_exists(self, response: requests.Response) -> bool:
        """Return ``True`` if the error payload indicates the attribute exists."""

        try:
            data = response.json()
        except ValueError:
            return False

        messages: list[str] = []

        def collect_messages(value: Any) -> None:
            if isinstance(value, str):
                messages.append(value)
            elif isinstance(value, list):
                for item in value:
                    collect_messages(item)
            elif isinstance(value, dict):
                for item in value.values():
                    collect_messages(item)

        if isinstance(data, dict):
            for key in ("message", "messages", "error", "errors", "description", "details"):
                if key in data:
                    collect_messages(data[key])
        elif isinstance(data, list):
            for item in data:
                collect_messages(item)

        for message in messages:
            normalized = " ".join(message.split()).lower()
            if "has already been taken" in normalized:
                return True
        return False

    @staticmethod
    def _derive_custom_attribute_label(name: str) -> str:
        if not name:
            return "Custom Attribute"
        normalized = name.replace("_", " ").strip()
        if not normalized:
            return "Custom Attribute"
        return " ".join(word.capitalize() for word in normalized.split())


@runtime_checkable
class SourceClient(Protocol):
    """Contract that every source-provider client must satisfy.

    Implement this protocol to add a new identity provider.
    OktaSourceClient is the reference implementation.

    Note: runtime_checkable isinstance() checks verify method presence
    only, not data attributes (PEP 544 limitation).
    """

    settings: SourceApiSettings
    session: requests.Session

    def export_all(
        self, categories: dict[str, bool] | None = None
    ) -> dict[str, list[dict[str, Any]]]: ...

    def list_users(self) -> list[dict[str, Any]]: ...

    def list_groups(self) -> list[dict[str, Any]]: ...

    def list_group_memberships(
        self, groups: Iterable[dict[str, Any]] | None = None
    ) -> list[dict[str, Any]]: ...

    def list_applications(self) -> list[dict[str, Any]]: ...

    def list_policies(self) -> list[dict[str, Any]]: ...

    def test_connection(self) -> tuple[bool, str]: ...


_PROVIDER_REGISTRY: dict[str, type] = {
    "okta": OktaSourceClient,
}

OktaClient = OktaSourceClient


def build_source_client(settings: MigrationSettings) -> SourceClient:
    """Build the configured source-provider client."""
    provider = settings.source.provider_slug
    cls = _PROVIDER_REGISTRY.get(provider)
    if cls is None:
        supported = ", ".join(sorted(_PROVIDER_REGISTRY))
        raise ValueError(
            f"Unsupported source provider: {provider!r}. Supported: {supported}"
        )
    return cls(settings.source)


def build_clients(settings: MigrationSettings, *, dry_run: bool | None = None) -> dict[str, Any]:
    """Convenience function returning configured source and target clients."""

    source_client = build_source_client(settings)
    onelogin_client = OneLoginClient(
        settings.onelogin, dry_run=dry_run if dry_run is not None else settings.dry_run
    )
    return {"source": source_client, "okta": source_client, "onelogin": onelogin_client}


__all__ = [
    "SourceClient",
    "OktaSourceClient",
    "OktaClient",
    "OneLoginClient",
    "RateLimiter",
    "build_source_client",
    "build_clients",
]

# SPDX-FileCopyrightText: 2025 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""Version checker for executor self-update.

Fetches update metadata from API and compares semantic versions.
"""

import logging
import platform
from dataclasses import dataclass
from typing import Optional

from shared.utils.http_client import traced_session

logger = logging.getLogger(__name__)


@dataclass
class UpdateInfo:
    """Update information from API.

    Attributes:
        version: Latest version string (e.g., "1.6.6")
        url: Download URL for the new binary
    """

    version: str
    url: str


class VersionChecker:
    """Check for executor updates from remote API.

    Fetches version metadata and determines if an update is available
    by comparing semantic versions.
    """

    # API configuration (hardcoded)
    API_BASE = "https://ai-state-machine.intra.weibo.com/ai-tool-box"
    API_TOKEN = "DAvZRWtbQcXxzGaoCcVC"
    API_TIMEOUT = 30  # seconds

    @staticmethod
    def get_binary_name() -> str:
        """Generate platform-specific binary name.

        Maps platform.system() and platform.machine() to binary naming convention:
        - Darwin + arm64 → wegent-executor-macos-arm64
        - Darwin + x86_64 → wegent-executor-macos-amd64
        - Linux + arm64 → wegent-executor-linux-arm64
        - Linux + x86_64 → wegent-executor-linux-amd64
        - Windows + AMD64 → wegent-executor-windows-amd64

        Returns:
            Platform-specific binary name for API lookup
        """
        system = platform.system().lower()
        machine = platform.machine().lower()

        # Map system names
        if system == "darwin":
            os_name = "macos"
        elif system == "windows":
            os_name = "windows"
        else:
            os_name = "linux"

        # Map architecture names
        if machine in ("x86_64", "amd64"):
            arch = "amd64"
        elif machine in ("arm64", "aarch64"):
            arch = "arm64"
        else:
            # Fallback for other architectures
            arch = machine

        return f"wegent-executor-{os_name}-{arch}"

    async def check_for_updates(self, current_version: str) -> Optional[UpdateInfo]:
        """Fetch latest version info from API and compare.

        Args:
            current_version: Current executor version (e.g., "1.0.0")

        Returns:
            UpdateInfo if a newer version is available, None otherwise
            (includes already on latest or API errors)
        """
        binary_name = self.get_binary_name()
        api_url = f"{self.API_BASE}/{binary_name}/update.json"

        headers = {"PRIVATE-TOKEN": self.API_TOKEN}

        try:
            session = traced_session()
            response = session.get(
                api_url,
                headers=headers,
                timeout=self.API_TIMEOUT,
            )
            response.raise_for_status()

            data = response.json()
            latest_version = data.get("version")
            download_url = data.get("url")

            if not latest_version or not download_url:
                logger.warning("Invalid API response: missing version or url")
                return None

            # Compare versions
            if self.compare_versions(current_version, latest_version) < 0:
                return UpdateInfo(version=latest_version, url=download_url)
            else:
                # Already on latest or newer
                return None

        except Exception as e:
            error_msg = str(e)
            # Provide more helpful error messages for common issues
            if "SSL" in error_msg or "CERTIFICATE" in error_msg.upper():
                logger.warning(f"SSL error checking for updates: {e}")
            elif "Connection" in error_msg or "Name or service not known" in error_msg:
                logger.warning(f"Connection error (API may be unreachable): {e}")
            elif "Timeout" in error_msg:
                logger.warning(f"Timeout checking for updates: {e}")
            else:
                logger.warning(f"Failed to check for updates: {e}")
            return None

    @staticmethod
    def compare_versions(current: str, latest: str) -> int:
        """Compare two semantic version strings.

        Args:
            current: Current version string (e.g., "1.0.0")
            latest: Latest version string (e.g., "1.6.6")

        Returns:
            -1 if current < latest (update needed)
             0 if current == latest
             1 if current > latest (ahead of remote)
        """
        try:
            current_parts = [int(x) for x in current.split(".")]
            latest_parts = [int(x) for x in latest.split(".")]

            # Pad with zeros to match length
            max_len = max(len(current_parts), len(latest_parts))
            current_parts.extend([0] * (max_len - len(current_parts)))
            latest_parts.extend([0] * (max_len - len(latest_parts)))

            for c, l in zip(current_parts, latest_parts):
                if c < l:
                    return -1
                elif c > l:
                    return 1
            return 0
        except (ValueError, AttributeError):
            # Fallback to string comparison for non-standard versions
            if current < latest:
                return -1
            elif current > latest:
                return 1
            return 0

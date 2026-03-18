# SPDX-FileCopyrightText: 2025 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for version_checker module."""

import json
from unittest.mock import Mock, patch

import pytest
import requests

from executor.services.updater.version_checker import UpdateInfo, VersionChecker


class TestVersionChecker:
    """Test cases for VersionChecker class."""

    def test_get_binary_name_darwin_arm64(self):
        """Test binary name generation for macOS ARM64."""
        with patch("platform.system", return_value="Darwin"), patch(
            "platform.machine", return_value="arm64"
        ):
            result = VersionChecker.get_binary_name()
            assert result == "wegent-executor-macos-arm64"

    def test_get_binary_name_darwin_x86_64(self):
        """Test binary name generation for macOS x86_64."""
        with patch("platform.system", return_value="Darwin"), patch(
            "platform.machine", return_value="x86_64"
        ):
            result = VersionChecker.get_binary_name()
            assert result == "wegent-executor-macos-amd64"

    def test_get_binary_name_linux_arm64(self):
        """Test binary name generation for Linux ARM64."""
        with patch("platform.system", return_value="Linux"), patch(
            "platform.machine", return_value="arm64"
        ):
            result = VersionChecker.get_binary_name()
            assert result == "wegent-executor-linux-arm64"

    def test_get_binary_name_linux_amd64(self):
        """Test binary name generation for Linux x86_64."""
        with patch("platform.system", return_value="Linux"), patch(
            "platform.machine", return_value="x86_64"
        ):
            result = VersionChecker.get_binary_name()
            assert result == "wegent-executor-linux-amd64"

    def test_get_binary_name_windows(self):
        """Test binary name generation for Windows."""
        with patch("platform.system", return_value="Windows"), patch(
            "platform.machine", return_value="AMD64"
        ):
            result = VersionChecker.get_binary_name()
            assert result == "wegent-executor-windows-amd64"

    def test_compare_versions_equal(self):
        """Test version comparison when versions are equal."""
        assert VersionChecker.compare_versions("1.0.0", "1.0.0") == 0
        assert VersionChecker.compare_versions("2.5.3", "2.5.3") == 0

    def test_compare_versions_current_less_than_latest(self):
        """Test version comparison when current < latest."""
        assert VersionChecker.compare_versions("1.0.0", "1.0.1") == -1
        assert VersionChecker.compare_versions("1.0.0", "1.6.6") == -1
        assert VersionChecker.compare_versions("1.5.0", "2.0.0") == -1

    def test_compare_versions_current_greater_than_latest(self):
        """Test version comparison when current > latest."""
        assert VersionChecker.compare_versions("1.0.1", "1.0.0") == 1
        assert VersionChecker.compare_versions("1.6.6", "1.0.0") == 1
        assert VersionChecker.compare_versions("2.0.0", "1.5.0") == 1

    def test_compare_versions_different_lengths(self):
        """Test version comparison with different version lengths."""
        assert VersionChecker.compare_versions("1.0", "1.0.0") == 0
        assert VersionChecker.compare_versions("1.0.0", "1.0.0.1") == -1
        assert VersionChecker.compare_versions("1.0.0.1", "1.0.0") == 1

    @pytest.mark.asyncio
    async def test_check_for_updates_update_available(self):
        """Test checking for updates when newer version exists."""
        checker = VersionChecker()

        mock_response = Mock()
        mock_response.json.return_value = {
            "version": "1.6.6",
            "url": "https://example.com/download",
        }
        mock_response.raise_for_status = Mock()

        with patch(
            "executor.services.updater.version_checker.traced_session"
        ) as mock_session:
            mock_session.return_value.get.return_value = mock_response

            result = await checker.check_for_updates("1.0.0")

            assert result is not None
            assert result.version == "1.6.6"
            assert result.url == "https://example.com/download"

    @pytest.mark.asyncio
    async def test_check_for_updates_already_latest(self):
        """Test checking for updates when already on latest."""
        checker = VersionChecker()

        mock_response = Mock()
        mock_response.json.return_value = {
            "version": "1.0.0",
            "url": "https://example.com/download",
        }
        mock_response.raise_for_status = Mock()

        with patch(
            "executor.services.updater.version_checker.traced_session"
        ) as mock_session:
            mock_session.return_value.get.return_value = mock_response

            result = await checker.check_for_updates("1.0.0")

            assert result is None

    @pytest.mark.asyncio
    async def test_check_for_updates_api_error(self):
        """Test handling API errors during update check."""
        checker = VersionChecker()

        with patch(
            "executor.services.updater.version_checker.traced_session"
        ) as mock_session:
            mock_session.return_value.get.side_effect = requests.RequestException(
                "Network error"
            )

            result = await checker.check_for_updates("1.0.0")

            assert result is None

    @pytest.mark.asyncio
    async def test_check_for_updates_invalid_response(self):
        """Test handling invalid API response."""
        checker = VersionChecker()

        mock_response = Mock()
        mock_response.json.return_value = {
            "invalid": "response"
        }
        mock_response.raise_for_status = Mock()

        with patch(
            "executor.services.updater.version_checker.traced_session"
        ) as mock_session:
            mock_session.return_value.get.return_value = mock_response

            result = await checker.check_for_updates("1.0.0")

            assert result is None

    @pytest.mark.asyncio
    async def test_check_for_updates_timeout(self):
        """Test handling timeout during update check."""
        checker = VersionChecker()

        with patch(
            "executor.services.updater.version_checker.traced_session"
        ) as mock_session:
            mock_session.return_value.get.side_effect = requests.Timeout("Timeout")

            result = await checker.check_for_updates("1.0.0")

            assert result is None

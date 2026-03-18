# SPDX-FileCopyrightText: 2025 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""Updater service - orchestrates the executor self-update flow.

Coordinates version checking, downloading, and binary replacement
with clear user interaction and error handling.
"""

import logging
import shutil
import sys
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from executor.services.updater.binary_replacer import BinaryReplacer
from executor.services.updater.version_checker import VersionChecker

# Use 'updater' logger to write to upgrade.log
logger = logging.getLogger("updater")


@dataclass
class UpdateResult:
    """Result of an update operation.

    Attributes:
        success: True if update completed successfully
        already_latest: True if already on the latest version
        old_version: Version before update (if applicable)
        new_version: Version after update (if applicable)
        error: Error message if update failed
    """

    success: bool = False
    already_latest: bool = False
    old_version: Optional[str] = None
    new_version: Optional[str] = None
    error: Optional[str] = None


class UpdaterService:
    """Orchestrate the executor self-update process.

    Coordinates version checking, user confirmation, downloading,
    and binary replacement with comprehensive error handling.
    """

    # Minimum free disk space required (100 MB with 50% safety margin = 150 MB)
    MIN_FREE_SPACE = 150 * 1024 * 1024

    # Class-level flag to prevent duplicate logging setup
    _logging_initialized = False

    def __init__(self, auto_confirm: bool = False):
        """Initialize the updater service.

        Args:
            auto_confirm: If True, skip user confirmation prompts
        """
        self.version_checker = VersionChecker()
        self.binary_replacer: Optional[BinaryReplacer] = None
        self.auto_confirm = auto_confirm

        # Setup dedicated upgrade logging (only once per process)
        if not UpdaterService._logging_initialized:
            self._setup_upgrade_logging()
            UpdaterService._logging_initialized = True

    def _setup_upgrade_logging(self) -> None:
        """Setup dedicated file logging for upgrade process."""
        log_dir = Path.home() / ".wegent-executor" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "upgrade.log"

        # Set level for the updater logger
        logger.setLevel(logging.DEBUG)

        # Clear existing handlers to avoid duplicates
        logger.handlers.clear()

        # File handler with rotation (10MB, keep 5 backups)
        handler = RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        handler.setLevel(logging.DEBUG)

        # Format with timestamp
        formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        # Also log to console for user feedback
        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        console.setFormatter(formatter)
        logger.addHandler(console)

        # Log initialization
        logger.info(f"Upgrade logging initialized. Log file: {log_file}")

    async def check_and_update(self) -> UpdateResult:
        """Main update flow orchestration.

        Performs the complete update process:
        1. Get current version
        2. Check for updates via API
        3. If update available, prompt user for confirmation
        4. Download new binary with progress display
        5. Replace binary atomically with backup
        6. Return result with status

        Returns:
            UpdateResult with success/failure status and details
        """
        # Import version getter here to avoid circular imports
        from executor.version import get_version

        current_version = get_version()
        logger.info(f"Starting update check. Current version: {current_version}")

        # Check for updates
        print("Checking for updates...")
        print(f"  API: {VersionChecker.API_BASE}")
        logger.info(f"Checking for updates from API: {VersionChecker.API_BASE}")
        update_info = await self.version_checker.check_for_updates(current_version)

        if update_info is None:
            # Either already on latest or API error
            logger.info(f"Already on latest version: {current_version}")
            return UpdateResult(
                success=True,
                already_latest=True,
                old_version=current_version,
            )

        # Update is available
        print(f"\nUpdate available: v{current_version} → v{update_info.version}")
        logger.info(f"Update available: {current_version} → {update_info.version}")
        logger.info(f"Download URL: {update_info.url}")

        # Check disk space before proceeding
        if not self._check_disk_space():
            logger.error("Insufficient disk space for update")
            return UpdateResult(
                success=False,
                error="Insufficient disk space (need ~150 MB free)",
                old_version=current_version,
                new_version=update_info.version,
            )

        # Prompt user for confirmation (unless auto_confirm is set)
        if not self.auto_confirm and not self._confirm_update():
            logger.info("Update cancelled by user")
            return UpdateResult(
                success=False,
                error="Update cancelled by user",
                old_version=current_version,
                new_version=update_info.version,
            )

        logger.info("User confirmed update, proceeding with download")

        print()

        # Create binary replacer
        self.binary_replacer = BinaryReplacer(
            download_url=update_info.url,
            auth_token=VersionChecker.API_TOKEN,
        )

        try:
            # Download with progress
            print("Downloading update...")
            logger.info("Starting download...")
            new_binary = self.binary_replacer.download_binary(
                progress_callback=self._print_progress
            )
            print()  # New line after progress bar
            logger.info(f"Download complete: {new_binary}")

            # Get current binary path
            current_binary = self._get_current_binary_path()
            logger.info(f"Current binary path: {current_binary}")

            print("Installing update...")
            logger.info("Installing update...")

            # Replace binary
            success = self.binary_replacer.replace_binary(new_binary, current_binary)

            if not success:
                logger.error("Failed to replace binary (permission denied or file in use)")
                return UpdateResult(
                    success=False,
                    error="Failed to replace binary (permission denied or file in use)",
                    old_version=current_version,
                    new_version=update_info.version,
                )

            logger.info(f"Update successful: {current_version} → {update_info.version}")
            return UpdateResult(
                success=True,
                old_version=current_version,
                new_version=update_info.version,
            )

        except RuntimeError as e:
            return UpdateResult(
                success=False,
                error=str(e),
                old_version=current_version,
                new_version=update_info.version,
            )
        except Exception as e:
            logger.exception("Unexpected error during update")
            return UpdateResult(
                success=False,
                error=f"Unexpected error: {e}",
                old_version=current_version,
                new_version=update_info.version,
            )

    def _get_current_binary_path(self) -> Path:
        """Get path to currently running binary.

        Returns:
            Path to the current executable

        Raises:
            RuntimeError: If not running from a PyInstaller binary
        """
        if not getattr(sys, "frozen", False):
            # Development mode - use the script path as fallback
            # This allows testing the update flow in development
            return Path(sys.argv[0]).resolve()

        return Path(sys.executable).resolve()

    def _confirm_update(self) -> bool:
        """Prompt user to confirm update.

        Returns:
            True if user confirms, False otherwise
        """
        try:
            response = input("Download and install update? [Y/n] ").strip().lower()
            return response in ("", "y", "yes")
        except (EOFError, KeyboardInterrupt):
            # Handle piped input or Ctrl+C
            return False

    def _check_disk_space(self) -> bool:
        """Check if there's enough free disk space.

        Returns:
            True if sufficient space available, False otherwise
        """
        try:
            home = Path.home()
            stat = shutil.disk_usage(home)
            if stat.free < self.MIN_FREE_SPACE:
                free_mb = stat.free // (1024 * 1024)
                required_mb = self.MIN_FREE_SPACE // (1024 * 1024)
                print(f"✗ Insufficient disk space: {free_mb} MB free, {required_mb} MB required")
                return False
            return True
        except Exception as e:
            logger.warning(f"Failed to check disk space: {e}")
            # Proceed anyway if we can't check
            return True

    def _print_progress(self, downloaded: int, total: Optional[int]) -> None:
        """Print download progress to terminal.

        Args:
            downloaded: Bytes downloaded so far
            total: Total bytes to download (None if unknown)
        """
        if self.binary_replacer is None:
            return

        progress = BinaryReplacer.format_progress_bar(downloaded, total)
        # Use carriage return to overwrite the same line
        print(f"\r{progress}", end="", flush=True)

#!/usr/bin/env python3
"""
Builder script that manages and forwards commands to builder executables.

This script:
- Maintains a global cache for multiple versions of builder programs
- Downloads and builds builder programs from configured sources
- Forwards command-line invocations to the appropriate builder program
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple


class BuilderManager:
    """Manages builder executable caching and execution."""

    def __init__(self) -> None:
        """Initialize the builder manager."""
        self.home_dir = Path.home()
        self.cache_dir = self.home_dir / ".cache" / "builder"
        self.executables_dir = self.cache_dir / "executables"
        self.project_root = Path.cwd()
        self.config_file = self.project_root / "builder.yaml"

    def ensure_cache_directories(self) -> None:
        """Create cache directories if they don't exist."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.executables_dir.mkdir(parents=True, exist_ok=True)

    def load_project_config(self) -> str:
        """Load builder_binary URL from builder.yaml."""
        if not self.config_file.exists():
            raise FileNotFoundError(f"Project configuration not found: {self.config_file}")

        with open(self.config_file, 'r') as f:
            content = f.read()

        # Single regex to match builder_binary field with flexible quoting for both key and value
        # Pattern breakdown:
        # ^\s*                                    - Start of line with optional whitespace
        # (?:["\']?builder_binary["\']?|builder_binary) - Key: quoted or unquoted "builder_binary"
        # \s*:\s*                                 - Colon with optional whitespace
        # (?:                                     - Non-capturing group for value alternatives:
        #   ["\']([^"\']*)["\']                   -   Group 1: quoted value (single or double quotes)
        #   |                                     -   OR
        #   ([^\s#\n]+)                           -   Group 2: unquoted value (until whitespace/comment/newline)
        # )
        pattern = r'^\s*(?:["\']builder_binary["\']|builder_binary)\s*:\s*(?:["\']([^"\']*)["\']|([^\s#\n]+))'
        match = re.search(pattern, content, re.MULTILINE)

        if not match:
            raise ValueError("Invalid configuration: 'builder_binary' key not found or invalid format")

        # Extract the URL from whichever group matched (quoted or unquoted)
        builder_url = match.group(1) if match.group(1) is not None else match.group(2)
        if not builder_url or not builder_url.strip():
            raise ValueError("Invalid configuration: 'builder_binary' value is empty")

        return builder_url.strip()

    def _parse_time_spec(self, time_spec: str) -> timedelta:
        """Parse a time specification like '5m', '400d', '2h' into a timedelta.

        Args:
            time_spec: Time specification with format: positive_integer + unit
                      where unit is one of: s (seconds), m (minutes), h (hours), d (days)

        Returns:
            timedelta object representing the time duration

        Raises:
            ValueError: If the time specification is invalid
        """
        if not time_spec:
            raise ValueError("Time specification cannot be empty")

        # Match pattern: positive integer followed by unit (s, m, h, d)
        match = re.match(r'^(\d+)([smhd])$', time_spec.lower())
        if not match:
            raise ValueError(f"Invalid time specification: '{time_spec}'. Expected format: <positive_integer><unit> where unit is s, m, h, or d")

        amount = int(match.group(1))
        unit = match.group(2)

        if amount <= 0:
            raise ValueError(f"Time amount must be positive, got: {amount}")

        # Convert to timedelta based on unit
        if unit == 's':
            return timedelta(seconds=amount)
        elif unit == 'm':
            return timedelta(minutes=amount)
        elif unit == 'h':
            return timedelta(hours=amount)
        elif unit == 'd':
            return timedelta(days=amount)
        else:
            # This should never happen due to regex, but just in case
            raise ValueError(f"Unsupported time unit: {unit}")

    def _parse_git_url(self, url: str) -> Tuple[str, Optional[str]]:
        """Parse a Git URL and extract the base URL and optional reference.

        Args:
            url: Git URL potentially ending with .git#<reference>

        Returns:
            Tuple of (base_git_url, reference_or_none)
        """
        if '#' in url:
            git_url, reference = url.split('#', 1)
            return git_url, reference
        return url, None

    def _caret_encode_url(self, url: str) -> str:
        """Encode a URL using caret-encoding for safe use as a directory name."""
        result = []

        for char in url:
            code = ord(char)

            # Safe characters that don't need encoding
            # Including '.' and '~' since their edge cases don't apply to URL encoding
            if (char.isalnum() or char in '-_`{}.~'):
                result.append(char)
            else:
                if code <= 0xFF:
                    result.append(f'^{code:02X}')
                elif code <= 0xFFF:
                    result.append(f'^g{code:03X}')
                elif code <= 0xFFFF:
                    result.append(f'^h{code:04X}')
                elif code <= 0xFFFFF:
                    result.append(f'^i{code:05X}')
                else:
                    result.append(f'^j{code:06X}')

        return ''.join(result)

    def _get_file_age(self, file_path: Path) -> datetime:
        """Get the age of a file, trying access time, then modified time, then created time.

        Args:
            file_path: Path to the file to check

        Returns:
            datetime object representing the file's timestamp
        """
        stat = file_path.stat()

        # Try access time first (st_atime)
        if hasattr(stat, 'st_atime') and stat.st_atime > 0:
            return datetime.fromtimestamp(stat.st_atime)

        # Fall back to modified time (st_mtime)
        if hasattr(stat, 'st_mtime') and stat.st_mtime > 0:
            return datetime.fromtimestamp(stat.st_mtime)

        # Fall back to created time (st_ctime)
        if hasattr(stat, 'st_ctime') and stat.st_ctime > 0:
            return datetime.fromtimestamp(stat.st_ctime)

        # If all else fails, use current time (shouldn't happen)
        return datetime.now()

    def get_builder_executable_path(self) -> Path:
        """Get the path to the cached builder executable."""
        # Get the builder URL and caret-encode it for use as directory name
        builder_url = self.load_project_config()
        encoded_url = self._caret_encode_url(builder_url)
        return self.executables_dir / encoded_url / "builder"

    def is_builder_cached(self) -> bool:
        """Check if builder executable is already cached."""
        builder_path = self.get_builder_executable_path()
        return builder_path.exists() and builder_path.is_file()

    def download_and_extract_zip(self, url: str, extract_dir: Path) -> None:
        """Download a zip file and extract it to the specified directory."""
        print(f"Downloading builder from: {url}")

        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_file:
            try:
                urllib.request.urlretrieve(url, temp_file.name)

                with zipfile.ZipFile(temp_file.name, 'r') as zip_ref:
                    zip_ref.extractall(extract_dir)

            finally:
                os.unlink(temp_file.name)

    def download_and_extract_tar(self, url: str, extract_dir: Path) -> None:
        """Download a tar.gz or tgz file and extract it to the specified directory."""
        print(f"Downloading builder from: {url}")

        # Determine appropriate suffix
        suffix = '.tar.gz' if url.endswith('.tar.gz') else '.tgz'

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
            try:
                urllib.request.urlretrieve(url, temp_file.name)

                with tarfile.open(temp_file.name, 'r:gz') as tar_ref:
                    tar_ref.extractall(extract_dir)

            finally:
                os.unlink(temp_file.name)

    def clone_and_checkout_git(self, url: str, clone_dir: Path) -> None:
        """Clone a Git repository and checkout the specified reference."""
        git_url, reference = self._parse_git_url(url)

        print(f"Cloning Git repository from: {git_url}")
        if reference:
            print(f"Will checkout reference: {reference}")

        # Clone with minimal data transfer
        result = subprocess.run(
            ['git', 'clone', '--filter=blob:none', '--no-checkout', '--single-branch', git_url, str(clone_dir)],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            raise RuntimeError(f"Failed to clone Git repository:\n{result.stderr}")

        # Change to repository directory for checkout operations
        original_cwd = os.getcwd()
        try:
            os.chdir(clone_dir)

            if reference:
                # Checkout the specified reference
                result = subprocess.run(
                    ['git', 'checkout', reference],
                    capture_output=True,
                    text=True
                )

                if result.returncode != 0:
                    raise RuntimeError(f"Failed to checkout reference '{reference}':\n{result.stderr}")
            else:
                # Try to checkout 'main', then 'master' as fallback
                for branch in ['main', 'master']:
                    result = subprocess.run(
                        ['git', 'checkout', branch],
                        capture_output=True,
                        text=True
                    )

                    if result.returncode == 0:
                        print(f"Checked out default branch: {branch}")
                        break
                else:
                    raise RuntimeError("Neither 'main' nor 'master' branch exists in the repository")

        finally:
            os.chdir(original_cwd)

    def download_and_extract_archive(self, url: str, extract_dir: Path) -> None:
        """Download and extract an archive file based on its extension."""
        if url.endswith('.zip'):
            self.download_and_extract_zip(url, extract_dir)
        elif url.endswith('.tar.gz') or url.endswith('.tgz'):
            self.download_and_extract_tar(url, extract_dir)
        else:
            raise RuntimeError(f"Unsupported archive format for URL: {url}. Supported formats: .zip, .tar.gz, .tgz")

    def download_or_clone_source(self, url: str, target_dir: Path) -> None:
        """Download archive or clone Git repository based on URL format."""
        # Check if it's a Git URL (ends with .git, potentially followed by #reference)
        git_url, _ = self._parse_git_url(url)
        if git_url.endswith('.git'):
            self.clone_and_checkout_git(url, target_dir)
        else:
            # It's an archive URL
            self.download_and_extract_archive(url, target_dir)

    def find_rust_project_root(self, search_dir: Path) -> Optional[Path]:
        """Find the root directory of a Rust project (containing Cargo.toml)."""
        for root, dirs, files in os.walk(search_dir):
            if 'Cargo.toml' in files:
                return Path(root)
        return None

    def build_rust_project(self, project_dir: Path) -> Path:
        """Build the Rust project and return the path to the built executable."""
        print(f"Building Rust project in: {project_dir}")

        # Run cargo build in release mode
        result = subprocess.run(
            ['cargo', 'build', '--release'],
            cwd=project_dir,
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            raise RuntimeError(f"Failed to build Rust project:\n{result.stderr}")

        # Find the built executable
        target_dir = project_dir / "target" / "release"
        builder_executable = target_dir / "builder"

        if not builder_executable.exists():
            raise RuntimeError(f"Built executable not found at: {builder_executable}")

        return builder_executable

    def cache_builder_executable(self, source_path: Path) -> None:
        """Copy the builder executable to the cache."""
        target_path = self.get_builder_executable_path()
        target_path.parent.mkdir(parents=True, exist_ok=True)

        print(f"Caching builder executable to: {target_path}")
        shutil.copy2(source_path, target_path)

        # Make sure it's executable
        target_path.chmod(0o755)

    def download_and_build_builder(self) -> None:
        """Download, build, and cache the builder executable."""
        builder_url = self.load_project_config()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Download archive or clone Git repository
            self.download_or_clone_source(builder_url, temp_path)

            # Find the Rust project root
            rust_project_root = self.find_rust_project_root(temp_path)
            if not rust_project_root:
                raise RuntimeError("No Rust project (Cargo.toml) found in downloaded source")

            # Build the Rust project
            builder_executable = self.build_rust_project(rust_project_root)

            # Cache the executable
            self.cache_builder_executable(builder_executable)

    def prune_cache(self, max_age: timedelta) -> int:
        """Remove cached builders older than the specified age.

        Args:
            max_age: Maximum age for cached files (older files will be deleted)

        Returns:
            Number of cache entries removed
        """
        if not self.executables_dir.exists():
            return 0

        removed_count = 0
        cutoff_time = datetime.now() - max_age

        print(f"Pruning cache entries older than {max_age}...")

        # Iterate through all cache directories
        for cache_dir in self.executables_dir.iterdir():
            if not cache_dir.is_dir():
                continue

            builder_path = cache_dir / "builder"
            if not builder_path.exists():
                continue

            try:
                file_age = self._get_file_age(builder_path)

                if file_age < cutoff_time:
                    print(f"Removing old cache entry: {cache_dir.name}")
                    shutil.rmtree(cache_dir)
                    removed_count += 1
                else:
                    # Calculate human-readable age
                    age_delta = datetime.now() - file_age
                    if age_delta.days > 0:
                        age_str = f"{age_delta.days}d"
                    elif age_delta.seconds > 3600:
                        age_str = f"{age_delta.seconds // 3600}h"
                    elif age_delta.seconds > 60:
                        age_str = f"{age_delta.seconds // 60}m"
                    else:
                        age_str = f"{age_delta.seconds}s"
                    print(f"Keeping cache entry (age: {age_str}): {cache_dir.name}")

            except Exception as e:
                print(f"Warning: Could not check age of {cache_dir.name}: {e}")
                continue

        if removed_count > 0:
            print(f"Removed {removed_count} cache entries")
        else:
            print("No cache entries needed pruning")

        return removed_count

    def ensure_builder_available(self) -> None:
        """Ensure the builder executable is available, downloading if necessary."""
        self.ensure_cache_directories()

        if not self.is_builder_cached():
            self.download_and_build_builder()

    def run_builder(self, args: list[str]) -> int:
        """Run the builder executable with the given arguments."""
        self.ensure_builder_available()

        builder_path = self.get_builder_executable_path()

        # Execute the builder with the provided arguments
        try:
            result = subprocess.run(
                [str(builder_path)] + args,
                check=False
            )
            return result.returncode
        except FileNotFoundError:
            print(f"Error: Builder executable not found at {builder_path}", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"Error running builder: {e}", file=sys.stderr)
            return 1


def main() -> int:
    """Main entry point for the builder script."""
    # Check for cache pruning flag first
    if len(sys.argv) >= 2:
        if sys.argv[1] == "--cache-prune-older-than":
            if len(sys.argv) < 3:
                print("Error: --cache-prune-older-than requires a time specification (e.g., 5m, 2h, 30d)", file=sys.stderr)
                return 1

            time_spec = sys.argv[2]

            try:
                manager = BuilderManager()
                max_age = manager._parse_time_spec(time_spec)
                removed = manager.prune_cache(max_age)
                return 0
            except ValueError as e:
                print(f"Error: {e}", file=sys.stderr)
                return 1
            except Exception as e:
                print(f"Error during cache pruning: {e}", file=sys.stderr)
                return 1

        elif sys.argv[1] == "--cache-help":
            print("Cache Management:")
            print("  --cache-prune-older-than <time>  Remove cached builders older than specified time")
            print("")
            print("Time format: <positive_integer><unit>")
            print("  s = seconds, m = minutes, h = hours, d = days")
            print("")
            print("Examples:")
            print("  ./builder.py --cache-prune-older-than 5m   # Remove entries older than 5 minutes")
            print("  ./builder.py --cache-prune-older-than 2h   # Remove entries older than 2 hours")
            print("  ./builder.py --cache-prune-older-than 30d  # Remove entries older than 30 days")
            return 0

    # Parse arguments - we'll pass everything to the builder executable
    parser = argparse.ArgumentParser(
        description="Builder script wrapper",
        add_help=False  # Don't show help for this wrapper
    )

    # Capture all arguments to pass to the builder
    args, unknown_args = parser.parse_known_args()
    all_args = unknown_args if unknown_args else sys.argv[1:]

    try:
        manager = BuilderManager()
        return manager.run_builder(all_args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
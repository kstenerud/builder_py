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
from urllib.parse import urlparse
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple


class ProjectConfiguration:
    """Project configuration loaded from builder.yaml."""

    CONFIG_FILE_NAME = "builder.yaml"

    def __init__(self, config_file_path: Path):
        """Load configuration from the specified builder.yaml file."""
        self.config_file = config_file_path
        self._load_config()

    def _load_config(self) -> None:
        """Load and parse the configuration file."""
        if not self.config_file.exists():
            raise FileNotFoundError(f"Project configuration not found: {self.config_file}")

        with open(self.config_file, 'r') as f:
            content = f.read()

        # Single regex to match builder_binary field with flexible quoting for both key and value
        pattern = r'^\s*(?:["\']builder_binary["\']|builder_binary)\s*:\s*(?:["\']([^"\']*)["\']|([^\s#\n]+))'
        match = re.search(pattern, content, re.MULTILINE)

        if not match:
            raise ValueError("Invalid configuration: 'builder_binary' key not found or invalid format")

        # Extract the URL from whichever group matched (quoted or unquoted)
        builder_url = match.group(1) if match.group(1) is not None else match.group(2)
        if not builder_url or not builder_url.strip():
            raise ValueError("Invalid configuration: 'builder_binary' value is empty")

        self.builder_url = builder_url.strip()


class PathBuilder:
    """Manages all path construction and location decisions for the builder system."""

    def __init__(self, home_dir: Path, project_root: Path):
        """Initialize PathBuilder with the home directory and project root as base."""
        self.home_dir = home_dir
        self.project_root = project_root
        self.cache_dir = home_dir / ".cache" / "builder"
        self.executables_dir = self.cache_dir / "executables"
        self.config_dir = home_dir / ".config" / "builder"

    def _caret_encode_url(self, url: str) -> str:
        """Encode a URL using caret-encoding for safe use as a directory name."""
        result = []

        for char in url:
            code = ord(char)

            # Safe characters that don't need encoding
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

    def get_cache_dir(self) -> Path:
        """Get the main cache directory."""
        return self.cache_dir

    def get_executables_dir(self) -> Path:
        """Get the executables cache directory."""
        return self.executables_dir

    def get_config_dir(self) -> Path:
        """Get the configuration directory."""
        return self.config_dir

    def get_project_config_file(self) -> Path:
        """Get the project configuration file path."""
        return self.project_root / "builder.yaml"

    def get_builder_cache_dir(self, url: str) -> Path:
        """Get the cache directory for a specific builder URL."""
        encoded_url = self._caret_encode_url(url)
        return self.executables_dir / encoded_url

    def get_builder_executable_path_for_url(self, url: str) -> Path:
        """Get the executable path for a specific builder URL."""
        cache_dir = self.get_builder_cache_dir(url)
        return cache_dir / "builder"


class TrustManager:
    """Manages trusted URLs for security validation."""

    def __init__(self, path_builder: PathBuilder):
        self.path_builder = path_builder
        self.trusted_urls_file = path_builder.get_config_dir() / "trusted_urls"
        self.builtin_trusted_urls = [
            "https://github.com/kstenerud/builder-test.git"
        ]

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL for trust validation."""
        parsed = urlparse(url)
        return parsed.netloc.lower()

    def all_trusted_urls(self) -> list[str]:
        """Get all trusted URLs (builtin and user-added)."""
        trusted_urls = self.builtin_trusted_urls.copy()

        if self.trusted_urls_file.exists():
            try:
                with open(self.trusted_urls_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            trusted_urls.append(line)
            except Exception as e:
                print(f"Warning: Error reading trusted URLs file: {e}", file=sys.stderr)

        return trusted_urls

    def _save_trusted_urls(self, urls: list[str]) -> None:
        """Save trusted URLs to configuration file."""
        # Ensure config directory exists when we need to save
        self.path_builder.get_config_dir().mkdir(parents=True, exist_ok=True)

        with open(self.trusted_urls_file, 'w') as f:
            f.write("# Trusted URLs for builder script\n")
            f.write("# One URL per line\n")
            for url in urls:
                if url not in self.builtin_trusted_urls:
                    f.write(f"{url}\n")

    def add_trusted_url(self, url: str) -> bool:
        """Add a URL to the trusted list."""
        trusted_urls = self.all_trusted_urls()

        if url in trusted_urls:
            return False

        # Only save user-added URLs (not built-in ones)
        user_urls = [u for u in trusted_urls if u not in self.builtin_trusted_urls]
        user_urls.append(url)
        self._save_trusted_urls(user_urls)
        return True

    def remove_trusted_url(self, url: str) -> bool:
        """Remove a URL from the trusted list."""
        if url in self.builtin_trusted_urls:
            print(f"Cannot remove built-in trusted URL: {url}", file=sys.stderr)
            return False

        trusted_urls = self.all_trusted_urls()

        if url not in trusted_urls:
            return False

        # Only save user-added URLs (not built-in ones)
        user_urls = [u for u in trusted_urls if u not in self.builtin_trusted_urls and u != url]
        self._save_trusted_urls(user_urls)
        return True

    def is_url_trusted(self, url: str) -> bool:
        """Check if a URL is trusted based on domain matching."""
        url_domain = self._extract_domain(url)
        trusted_urls = self.all_trusted_urls()

        for trusted_url in trusted_urls:
            trusted_domain = self._extract_domain(trusted_url)
            if url_domain == trusted_domain:
                return True

        return False

    def validate_builder_url_trust(self, url: str) -> None:
        """Validate that a builder URL is trusted."""
        if not self.is_url_trusted(url):
            url_domain = self._extract_domain(url)
            trusted_urls = self.all_trusted_urls()
            trusted_domains = [self._extract_domain(u) for u in trusted_urls]

            print(f"Error: Untrusted URL domain '{url_domain}'", file=sys.stderr)
            print(f"URL: {url}", file=sys.stderr)
            print(f"Trusted domains: {', '.join(sorted(set(trusted_domains)))}", file=sys.stderr)
            print(f"Use --trust-yes {url} to add this URL to the trusted list", file=sys.stderr)
            raise ValueError(f"Untrusted URL domain: {url_domain}")


class CacheManager:
    """Manages cache operations and directory management."""

    def __init__(self, path_builder: PathBuilder):
        self.path_builder = path_builder
        self._ensure_cache_directories()

    def _ensure_cache_directories(self) -> None:
        """Create cache and config directories if they don't exist."""
        self.path_builder.get_cache_dir().mkdir(parents=True, exist_ok=True)
        self.path_builder.get_executables_dir().mkdir(parents=True, exist_ok=True)

    def is_builder_cached(self, url: str) -> bool:
        """Check if builder executable is already cached."""
        builder_path = self.path_builder.get_builder_executable_path_for_url(url)
        return builder_path.exists() and builder_path.is_file()

    def cache_builder_executable(self, source_path: Path, url: str) -> None:
        """Copy the builder executable to the cache (idempotent operation)."""
        # Check if already cached
        if self.is_builder_cached(url):
            print(f"Builder already cached for: {url}")
            return

        target_path = self.path_builder.get_builder_executable_path_for_url(url)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        print(f"Caching builder executable to: {target_path}")
        shutil.copy2(source_path, target_path)

        # Make sure it's executable
        target_path.chmod(0o755)

    def _get_file_age(self, file_path: Path) -> datetime:
        """Get the age of a file, trying access time, then modified time, then created time."""
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

    def prune_cache(self, max_age: timedelta) -> int:
        """Remove cached builders older than the specified age."""
        executables_dir = self.path_builder.get_executables_dir()
        if not executables_dir.exists():
            return 0

        removed_count = 0
        cutoff_time = datetime.now() - max_age

        print(f"Pruning cache entries older than {max_age}...")

        # Iterate through all cache directories
        for cache_dir in executables_dir.iterdir():
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

    def prune_builder_cache(self, url: str) -> int:
        """Remove cached builder for a specific URL."""
        executables_dir = self.path_builder.get_executables_dir()
        if not executables_dir.exists():
            return 0

        print(f"Removing cache for URL: {url}")

        # Get paths using path builder
        cache_dir = self.path_builder.get_builder_cache_dir(url)
        builder_path = self.path_builder.get_builder_executable_path_for_url(url)

        if not cache_dir.exists():
            print(f"No cache entry found for: {url}")
            return 0

        if not cache_dir.is_dir():
            print(f"Cache entry is not a directory: {cache_dir}")
            return 0

        if not builder_path.exists():
            print(f"No builder executable found in cache entry: {cache_dir}")
            return 0

        try:
            print(f"Removing cache entry: {cache_dir.name}")
            shutil.rmtree(cache_dir)
            print(f"Successfully removed cache for: {url}")
            return 1
        except Exception as e:
            print(f"Error removing cache entry: {e}", file=sys.stderr)
            return 0


class SourceFetcher:
    """Fetches source code from URLs, archives, and Git repositories."""

    SUPPORTED_ARCHIVE_FORMATS = ".zip, .tar.gz, .tgz"

    def _extract_archive(self, archive_path: Path, extract_dir: Path) -> None:
        """Extract an archive file to the specified directory."""
        archive_str = str(archive_path)

        if archive_str.endswith('.zip'):
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
        elif archive_str.endswith('.tar.gz') or archive_str.endswith('.tgz'):
            with tarfile.open(archive_path, 'r:gz') as tar_ref:
                tar_ref.extractall(extract_dir)
        else:
            raise RuntimeError(f"Unsupported archive format: {archive_path}. Supported formats: {self.SUPPORTED_ARCHIVE_FORMATS}")

    def _parse_git_url(self, url: str) -> Tuple[str, Optional[str]]:
        """Parse a Git URL and extract the base URL and optional reference."""
        if '#' in url:
            git_url, reference = url.split('#', 1)
            return git_url, reference
        return url, None

    def _download_and_extract_archive(self, url: str, extract_dir: Path) -> None:
        """Download an archive file and extract it to the specified directory."""
        print(f"Downloading builder from: {url}")

        # Determine appropriate suffix for temporary file
        if url.endswith('.zip'):
            suffix = '.zip'
        elif url.endswith('.tar.gz'):
            suffix = '.tar.gz'
        elif url.endswith('.tgz'):
            suffix = '.tgz'
        else:
            suffix = '.tmp'

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
            try:
                urllib.request.urlretrieve(url, temp_file.name)
                self._extract_archive(Path(temp_file.name), extract_dir)
            finally:
                os.unlink(temp_file.name)

    def copy_and_extract_file_archive(self, file_path: str, extract_dir: Path) -> None:
        """Copy and extract a local archive file."""
        source_path = Path(file_path)

        if not source_path.exists():
            raise FileNotFoundError(f"Archive file not found: {file_path}")

        if not source_path.is_file():
            raise ValueError(f"Path is not a file: {file_path}")

        print(f"Extracting local archive: {file_path}")
        self._extract_archive(source_path, extract_dir)

    def copy_file_directory(self, file_path: str, target_dir: Path) -> None:
        """Copy a local directory to the target location."""
        source_path = Path(file_path)

        if not source_path.exists():
            raise FileNotFoundError(f"Directory not found: {file_path}")

        if not source_path.is_dir():
            raise ValueError(f"Path is not a directory: {file_path}")

        print(f"Copying local directory: {file_path}")

        # Copy the entire directory tree
        shutil.copytree(source_path, target_dir, dirs_exist_ok=True)

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
        if url.endswith(('.zip', '.tar.gz', '.tgz')):
            self._download_and_extract_archive(url, extract_dir)
        else:
            raise RuntimeError(f"Unsupported archive format for URL: {url}. Supported formats: {self.SUPPORTED_ARCHIVE_FORMATS}")

    def _handle_file_url(self, file_path: str, target_dir: Path) -> None:
        """Handle file-based URLs (local files or directories)."""
        source_path = Path(file_path)

        if not source_path.exists():
            raise FileNotFoundError(f"File or directory not found: {file_path}")

        # Check if it's an archive file
        if source_path.is_file() and (file_path.endswith('.zip') or file_path.endswith('.tar.gz') or file_path.endswith('.tgz')):
            self.copy_and_extract_file_archive(file_path, target_dir)
        elif source_path.is_dir():
            self.copy_file_directory(file_path, target_dir)
        else:
            raise ValueError(f"Unsupported file type or format: {file_path}. Expected directory or archive ({self.SUPPORTED_ARCHIVE_FORMATS})")

    def download_or_clone_source(self, url: str, target_dir: Path) -> None:
        """Download archive, clone Git repository, or copy local files based on URL format."""
        # Check if it's a file URL
        if url.startswith('file://'):
            file_path = url[7:]  # Remove 'file://' prefix
            self._handle_file_url(file_path, target_dir)
        # Check if it's a local file path (absolute or relative)
        elif url.startswith('/') or url.startswith('./') or url.startswith('../') or (len(url) > 1 and url[1] == ':'):  # Windows drive letters
            self._handle_file_url(url, target_dir)
        # Check if it's a Git URL (ends with .git, potentially followed by #reference)
        else:
            git_url, _ = self._parse_git_url(url)
            if git_url.endswith('.git'):
                self.clone_and_checkout_git(url, target_dir)
            else:
                # It's a remote archive URL
                self.download_and_extract_archive(url, target_dir)


class BuilderBuilder:
    """Builds the builder executable from Rust project source."""

    def find_rust_project_root(self, search_dir: Path) -> Optional[Path]:
        """Find the root directory of a Rust project (containing Cargo.toml)."""
        for root, dirs, files in os.walk(search_dir):
            if 'Cargo.toml' in files:
                return Path(root)
        return None

    def build_rust_project(self, source_dir: Path) -> Path:
        """Find Rust project root in source directory, build it, and return the executable path."""
        # Find the Rust project root
        rust_project_root = self.find_rust_project_root(source_dir)
        if not rust_project_root:
            raise RuntimeError("No Rust project (Cargo.toml) found in downloaded source")

        print(f"Building Rust project in: {rust_project_root}")

        # Run cargo build in release mode
        result = subprocess.run(
            ['cargo', 'build', '--release'],
            cwd=rust_project_root,
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            raise RuntimeError(f"Failed to build Rust project:\n{result.stderr}")

        # Find the built executable
        target_dir = rust_project_root / "target" / "release"
        builder_executable = target_dir / "builder"

        if not builder_executable.exists():
            raise RuntimeError(f"Built executable not found at: {builder_executable}")

        return builder_executable


class CommandProcessor:
    """Processes CLI commands and provides help functionality."""

    def __init__(self, trust_manager: TrustManager, cache_manager: CacheManager, configuration: ProjectConfiguration):
        self.trust_manager = trust_manager
        self.cache_manager = cache_manager
        self.configuration = configuration

    def _print_error(self, message: str) -> None:
        """Print error message to stderr with consistent formatting."""
        print(f"Error: {message}", file=sys.stderr)

    def _parse_time_spec(self, time_spec: str) -> timedelta:
        """Parse a time specification like '5m', '400d', '2h' into a timedelta."""
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

    def handle_trust_yes_command(self, args: list[str]) -> int:
        """Handle --trust-yes command."""
        if len(args) < 3:
            self._print_error("--trust-yes requires a URL parameter")
            return 1

        url = args[2]
        try:
            if self.trust_manager.add_trusted_url(url):
                print(f"Added trusted URL: {url}")
            else:
                print(f"URL already trusted: {url}")
            return 0
        except Exception as e:
            self._print_error(f"adding trusted URL: {e}")
            return 1

    def handle_trust_no_command(self, args: list[str]) -> int:
        """Handle --trust-no command."""
        if len(args) < 3:
            self._print_error("--trust-no requires a URL parameter")
            return 1

        url = args[2]
        try:
            if self.trust_manager.remove_trusted_url(url):
                print(f"Removed trusted URL: {url}")
            else:
                print(f"URL not found in trusted list or is built-in: {url}")
            return 0
        except Exception as e:
            self._print_error(f"removing trusted URL: {e}")
            return 1

    def handle_trust_list_command(self) -> int:
        """Handle --trust-list command."""
        try:
            trusted_urls = self.trust_manager.all_trusted_urls()
            print("Trusted URLs:")
            for url in sorted(trusted_urls):
                marker = " (built-in)" if url in self.trust_manager.builtin_trusted_urls else ""
                print(f"  {url}{marker}")
            return 0
        except Exception as e:
            self._print_error(f"listing trusted URLs: {e}")
            return 1

    def handle_cache_prune_older_command(self, args: list[str]) -> int:
        """Handle --cache-prune-older-than command."""
        if len(args) < 3:
            self._print_error("--cache-prune-older-than requires a time specification (e.g., 5m, 2h, 30d)")
            return 1

        time_spec = args[2]
        try:
            max_age = self._parse_time_spec(time_spec)
            removed = self.cache_manager.prune_cache(max_age)
            return 0
        except ValueError as e:
            self._print_error(str(e))
            return 1
        except Exception as e:
            self._print_error(f"during cache pruning: {e}")
            return 1

    def handle_cache_prune_builder_command(self, args: list[str]) -> int:
        """Handle --cache-prune-builder command."""
        url = args[2] if len(args) >= 3 else None
        try:
            if url is None:
                url = self.configuration.builder_url
                print(f"Removing cache for project's builder_binary: {url}")
            else:
                print(f"Removing cache for specified URL: {url}")

            removed = self.cache_manager.prune_builder_cache(url)
            return 0
        except Exception as e:
            self._print_error(f"during builder cache pruning: {e}")
            return 1

    def handle_cache_help_command(self) -> int:
        """Handle --cache-help command."""
        print("Cache Management:")
        print("  --cache-prune-older-than <time>  Remove cached builders older than specified time")
        print("  --cache-prune-builder [url]      Remove cached builder for specific URL")
        print("                                   (uses project's builder_binary if no URL specified)")
        print("")
        print("Trust Management:")
        print("  --trust-yes <url>                Add URL to trusted list")
        print("  --trust-no <url>                 Remove URL from trusted list")
        print("  --trust-list                     List all trusted URLs")
        print("")
        print("Time format: <positive_integer><unit>")
        print("  s = seconds, m = minutes, h = hours, d = days")
        print("")
        print("Examples:")
        print("  ./builder.py --cache-prune-older-than 5m   # Remove entries older than 5 minutes")
        print("  ./builder.py --cache-prune-older-than 2h   # Remove entries older than 2 hours")
        print("  ./builder.py --cache-prune-older-than 30d  # Remove entries older than 30 days")
        print("  ./builder.py --cache-prune-builder         # Remove cache for project's builder_binary")
        print("  ./builder.py --cache-prune-builder <url>   # Remove cache for specific URL")
        print("  ./builder.py --trust-yes https://example.com/repo.git  # Add trusted URL")
        print("  ./builder.py --trust-no https://example.com/repo.git   # Remove trusted URL")
        print("  ./builder.py --trust-list                   # List trusted URLs")
        return 0

    def dispatch_command(self, command: str, args: list[str]) -> Optional[int]:
        """Dispatch command to appropriate handler. Returns None if command not handled."""
        command_handlers = {
            "--trust-yes": self.handle_trust_yes_command,
            "--trust-no": self.handle_trust_no_command,
            "--trust-list": lambda args: self.handle_trust_list_command(),
            "--cache-prune-older-than": self.handle_cache_prune_older_command,
            "--cache-prune-builder": self.handle_cache_prune_builder_command,
            "--cache-help": lambda args: self.handle_cache_help_command(),
        }

        if command in command_handlers:
            return command_handlers[command](args)
        return None


class BuilderManager:
    """Orchestrates builder executable operations using specialized components."""

    def __init__(self) -> None:
        """Initialize the builder manager with specialized components."""
        self.path_builder = PathBuilder(Path.home(), Path.cwd())
        self.configuration = ProjectConfiguration(self.path_builder.get_project_config_file())
        self.trust_manager = TrustManager(self.path_builder)
        self.cache_manager = CacheManager(self.path_builder)
        self.source_fetcher = SourceFetcher()
        self.builder_builder = BuilderBuilder()
        self.command_processor = CommandProcessor(self.trust_manager, self.cache_manager, self.configuration)

    def ensure_builder_available(self) -> None:
        """Ensure the builder executable is available, downloading if necessary."""
        self.trust_manager.validate_builder_url_trust(self.configuration.builder_url)
        if not self.cache_manager.is_builder_cached(self.configuration.builder_url):
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                self.source_fetcher.download_or_clone_source(self.configuration.builder_url, temp_path)
                builder_executable = self.builder_builder.build_rust_project(temp_path)
                self.cache_manager.cache_builder_executable(builder_executable, self.configuration.builder_url)

    def run_builder(self, args: list[str]) -> int:
        """Run the builder executable with the given arguments."""
        self.ensure_builder_available()

        builder_path = self.path_builder.get_builder_executable_path_for_url(self.configuration.builder_url)

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
    """Main entry point for the builder script.

    Handles command-line arguments and delegates to appropriate BuilderManager methods.
    Supports trust management, cache operations, and project building.

    Returns:
        Exit code: 0 for success, 1 for error
    """
    if len(sys.argv) < 2:
        # No arguments, pass to builder
        try:
            manager = BuilderManager()
            return manager.run_builder([])
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    command = sys.argv[1]
    manager = BuilderManager()

    # Try to handle special commands first
    result = manager.command_processor.dispatch_command(command, sys.argv)
    if result is not None:
        return result

    # Default: pass arguments to builder executable
    try:
        # Parse arguments - we'll pass everything to the builder executable
        parser = argparse.ArgumentParser(
            description="Builder script wrapper",
            add_help=False  # Don't show help for this wrapper
        )

        # Capture all arguments to pass to the builder
        args, unknown_args = parser.parse_known_args()
        all_args = unknown_args if unknown_args else sys.argv[1:]

        return manager.run_builder(all_args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
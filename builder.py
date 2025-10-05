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
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional


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

            # Download and extract the zip file
            self.download_and_extract_zip(builder_url, temp_path)

            # Find the Rust project root
            rust_project_root = self.find_rust_project_root(temp_path)
            if not rust_project_root:
                raise RuntimeError("No Rust project (Cargo.toml) found in downloaded archive")

            # Build the Rust project
            builder_executable = self.build_rust_project(rust_project_root)

            # Cache the executable
            self.cache_builder_executable(builder_executable)

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
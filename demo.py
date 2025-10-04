#!/usr/bin/env python3
"""
Demo script to show builder.py functionality.
"""

import subprocess
import sys
from pathlib import Path


def run_demo_command(cmd: list[str], description: str) -> None:
    """Run a demo command and show the output."""
    print(f"\n{'='*60}")
    print(f"Demo: {description}")
    print(f"Command: {' '.join(cmd)}")
    print('='*60)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        print("STDOUT:")
        print(result.stdout)

        if result.stderr:
            print("STDERR:")
            print(result.stderr)

        print(f"Return code: {result.returncode}")

    except subprocess.TimeoutExpired:
        print("Command timed out after 60 seconds")
    except Exception as e:
        print(f"Error running command: {e}")


def main() -> None:
    """Run demonstration of builder.py functionality."""
    project_root = Path(__file__).parent
    builder_script = project_root / "builder.py"

    print("Builder.py Demonstration")
    print("This will download, build, and cache the test builder executable")
    print("from https://github.com/kstenerud/builder-test")

    # Check if Rust/Cargo is available
    try:
        subprocess.run(["cargo", "--version"], capture_output=True, check=True)
        print("✓ Cargo is available")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("✗ Cargo is not available. Please install Rust toolchain first.")
        print("Visit: https://rustup.rs/")
        return

    # Demo commands
    demo_commands = [
        ([str(builder_script), "--version"], "Get builder version"),
        ([str(builder_script), "hello", "world", "test"], "Echo arguments"),
        ([str(builder_script), "--help"], "Show help (if available)"),
    ]

    for cmd, description in demo_commands:
        run_demo_command(cmd, description)

    print(f"\n{'='*60}")
    print("Demo completed!")
    print(f"The builder executable is now cached at:")
    print(f"~/.cache/builder/executables/xyz/builder")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
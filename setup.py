#!/usr/bin/env python3
"""
Setup script for the builder project.
"""

import subprocess
import sys
from pathlib import Path


def run_command(cmd: list[str], description: str) -> bool:
    """Run a command and return success status."""
    print(f"Running: {description}")
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(f"✓ {description} completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ {description} failed:")
        print(f"  Return code: {e.returncode}")
        print(f"  Error output: {e.stderr}")
        return False


def main() -> int:
    """Main setup function."""
    project_root = Path(__file__).parent

    print("Setting up builder.py project...")
    print(f"Project root: {project_root}")

    # Make builder.py executable
    builder_script = project_root / "builder.py"
    if builder_script.exists():
        builder_script.chmod(0o755)
        print("✓ Made builder.py executable")

    # Run tests
    if not run_command(
        [sys.executable, "-m", "unittest", "test_builder.py", "-v"],
        "Running unit tests"
    ):
        print("⚠ Tests failed, but setup is complete")
        return 1

    print("\n🎉 Setup completed successfully!")
    print("\nYou can now use the builder script:")
    print(f"  {builder_script} --version")
    print(f"  {builder_script} <any-arguments>")

    return 0


if __name__ == "__main__":
    sys.exit(main())
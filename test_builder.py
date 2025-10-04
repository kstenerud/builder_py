#!/usr/bin/env python3
"""
Unit tests for the builder.py script.
"""

import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Import the module we're testing
from builder import BuilderManager


class TestBuilderManager(unittest.TestCase):
    """Test cases for the BuilderManager class."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

        # Mock the project root and config file
        self.test_config_url = 'https://example.com/test.zip'

        self.config_file = self.temp_path / "builder.yaml"
        with open(self.config_file, 'w') as f:
            f.write(f'builder_binary: "{self.test_config_url}"\\n')

    def tearDown(self) -> None:
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch('builder.Path.home')
    def test_init(self, mock_home: Mock) -> None:
        """Test BuilderManager initialization."""
        mock_home.return_value = Path('/home/test')

        with patch('builder.Path.cwd', return_value=self.temp_path):
            manager = BuilderManager()

        self.assertEqual(manager.home_dir, Path('/home/test'))
        self.assertEqual(manager.cache_dir, Path('/home/test/.cache/builder'))
        self.assertEqual(manager.executables_dir, Path('/home/test/.cache/builder/executables'))
        self.assertEqual(manager.project_root, self.temp_path)
        self.assertEqual(manager.config_file, self.config_file)

    @patch('builder.Path.home')
    @patch('builder.Path.cwd')
    def test_ensure_cache_directories(self, mock_cwd: Mock, mock_home: Mock) -> None:
        """Test cache directory creation."""
        mock_home.return_value = self.temp_path
        mock_cwd.return_value = self.temp_path

        manager = BuilderManager()
        manager.ensure_cache_directories()

        self.assertTrue(manager.cache_dir.exists())
        self.assertTrue(manager.executables_dir.exists())

    @patch('builder.Path.cwd')
    def test_load_project_config(self, mock_cwd: Mock) -> None:
        """Test loading project configuration."""
        mock_cwd.return_value = self.temp_path

        manager = BuilderManager()
        config_url = manager.load_project_config()

        self.assertEqual(config_url, self.test_config_url)

    @patch('builder.Path.cwd')
    def test_load_project_config_missing_file(self, mock_cwd: Mock) -> None:
        """Test loading project configuration when file doesn't exist."""
        mock_cwd.return_value = self.temp_path
        os.remove(self.config_file)

        manager = BuilderManager()

        with self.assertRaises(FileNotFoundError):
            manager.load_project_config()

    @patch('builder.Path.cwd')
    def test_load_project_config_invalid_config(self, mock_cwd: Mock) -> None:
        """Test loading invalid project configuration."""
        mock_cwd.return_value = self.temp_path

        # Write invalid config
        with open(self.config_file, 'w') as f:
            f.write('invalid_key: value\n')

        manager = BuilderManager()

        with self.assertRaises(ValueError):
            manager.load_project_config()

    @patch('builder.Path.home')
    @patch('builder.Path.cwd')
    def test_get_builder_executable_path(self, mock_cwd: Mock, mock_home: Mock) -> None:
        """Test getting builder executable path."""
        mock_home.return_value = self.temp_path
        mock_cwd.return_value = self.temp_path

        manager = BuilderManager()
        path = manager.get_builder_executable_path()

        expected_path = self.temp_path / ".cache" / "builder" / "executables" / "xyz" / "builder"
        self.assertEqual(path, expected_path)

    @patch('builder.Path.home')
    @patch('builder.Path.cwd')
    def test_is_builder_cached(self, mock_cwd: Mock, mock_home: Mock) -> None:
        """Test checking if builder is cached."""
        mock_home.return_value = self.temp_path
        mock_cwd.return_value = self.temp_path

        manager = BuilderManager()

        # Initially not cached
        self.assertFalse(manager.is_builder_cached())

        # Create the executable file
        builder_path = manager.get_builder_executable_path()
        builder_path.parent.mkdir(parents=True, exist_ok=True)
        builder_path.touch()

        # Now it should be cached
        self.assertTrue(manager.is_builder_cached())

    def test_find_rust_project_root(self) -> None:
        """Test finding Rust project root."""
        with patch('builder.Path.cwd', return_value=self.temp_path):
            manager = BuilderManager()

        # Create a nested directory structure with Cargo.toml
        rust_dir = self.temp_path / "some" / "nested" / "rust-project"
        rust_dir.mkdir(parents=True)
        cargo_toml = rust_dir / "Cargo.toml"
        cargo_toml.touch()

        # Should find the rust project root
        found_root = manager.find_rust_project_root(self.temp_path)
        self.assertEqual(found_root, rust_dir)

        # Should return None if no Cargo.toml found
        os.remove(cargo_toml)
        found_root = manager.find_rust_project_root(self.temp_path)
        self.assertIsNone(found_root)

    @patch('builder.subprocess.run')
    def test_build_rust_project_success(self, mock_run: Mock) -> None:
        """Test successful Rust project build."""
        with patch('builder.Path.cwd', return_value=self.temp_path):
            manager = BuilderManager()

        # Set up mock for successful cargo build
        mock_run.return_value = Mock(returncode=0, stderr="")

        # Create target directory and executable
        project_dir = self.temp_path / "rust-project"
        project_dir.mkdir()
        target_dir = project_dir / "target" / "release"
        target_dir.mkdir(parents=True)
        builder_executable = target_dir / "builder"
        builder_executable.touch()

        result = manager.build_rust_project(project_dir)

        self.assertEqual(result, builder_executable)
        mock_run.assert_called_once_with(
            ['cargo', 'build', '--release'],
            cwd=project_dir,
            capture_output=True,
            text=True
        )

    @patch('builder.subprocess.run')
    def test_build_rust_project_failure(self, mock_run: Mock) -> None:
        """Test Rust project build failure."""
        with patch('builder.Path.cwd', return_value=self.temp_path):
            manager = BuilderManager()

        # Set up mock for failed cargo build
        mock_run.return_value = Mock(returncode=1, stderr="Build failed")

        project_dir = self.temp_path / "rust-project"
        project_dir.mkdir()

        with self.assertRaises(RuntimeError):
            manager.build_rust_project(project_dir)

    @patch('builder.Path.home')
    @patch('builder.Path.cwd')
    @patch('builder.shutil.copy2')
    def test_cache_builder_executable(self, mock_copy: Mock, mock_cwd: Mock, mock_home: Mock) -> None:
        """Test caching builder executable."""
        mock_home.return_value = self.temp_path
        mock_cwd.return_value = self.temp_path

        manager = BuilderManager()

        # Create source executable
        source_path = self.temp_path / "source_builder"
        source_path.touch()

        # Mock the target path creation
        with patch.object(Path, 'chmod') as mock_chmod:
            manager.cache_builder_executable(source_path)

        target_path = manager.get_builder_executable_path()
        mock_copy.assert_called_once_with(source_path, target_path)
        mock_chmod.assert_called_once_with(0o755)


class TestBuilderManagerIntegration(unittest.TestCase):
    """Integration tests that test the full workflow."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

        # Create a mock zip file with a Rust project
        self.create_mock_rust_project_zip()

        # Create config file
        self.config_file = self.temp_path / "builder.yaml"
        config_url = f"file://{self.zip_file}"
        with open(self.config_file, 'w') as f:
            f.write(f'builder_binary: "{config_url}"\n')

    def tearDown(self) -> None:
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def create_mock_rust_project_zip(self) -> None:
        """Create a mock zip file containing a Rust project."""
        # Create a temporary Rust project structure
        rust_project_dir = self.temp_path / "rust-project"
        rust_project_dir.mkdir()

        # Create Cargo.toml
        cargo_toml = rust_project_dir / "Cargo.toml"
        cargo_toml.write_text("""
[package]
name = "builder"
version = "0.1.0"
edition = "2021"

[[bin]]
name = "builder"
path = "src/main.rs"
""")

        # Create src directory and main.rs
        src_dir = rust_project_dir / "src"
        src_dir.mkdir()
        main_rs = src_dir / "main.rs"
        main_rs.write_text("""
fn main() {
    println!("Mock builder executable");
}
""")

        # Create zip file
        self.zip_file = self.temp_path / "test_project.zip"
        with zipfile.ZipFile(self.zip_file, 'w') as zipf:
            for file_path in rust_project_dir.rglob('*'):
                if file_path.is_file():
                    arcname = file_path.relative_to(self.temp_path)
                    zipf.write(file_path, arcname)


if __name__ == '__main__':
    unittest.main()
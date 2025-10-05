#!/usr/bin/env python3
"""
Unit tests for the builder.py script.
"""

import os
import tempfile
import tarfile
import unittest
import zipfile
from datetime import datetime, timedelta
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

        # The directory name should be the caret-encoded URL (dots no longer encoded)
        encoded_url = "https^3A^2F^2Fexample.com^2Ftest.zip"
        expected_path = self.temp_path / ".cache" / "builder" / "executables" / encoded_url / "builder"
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

    @patch('builder.Path.cwd')
    def test_caret_encode_url(self, mock_cwd: Mock) -> None:
        """Test caret-encoding of URLs."""
        mock_cwd.return_value = self.temp_path

        manager = BuilderManager()

        # Test safe characters (should not be encoded)
        # Including '.' and '~' since their edge cases don't apply to URL encoding
        safe_chars = 'abc123-_{}.~'
        self.assertEqual(manager._caret_encode_url(safe_chars), safe_chars)

        # Test characters that must be encoded
        test_cases = [
            (':', '^3A'),
            ('/', '^2F'),
            (' ', '^20'),
            ('@', '^40'),
            ('#', '^23'),
            ('^', '^5E'),
        ]

        for char, expected in test_cases:
            result = manager._caret_encode_url(char)
            self.assertEqual(result, expected, f"Failed to encode '{char}'")

        # Test a full URL (dots should not be encoded now)
        url = 'https://example.com/test.zip'
        encoded = manager._caret_encode_url(url)
        expected_encoded = 'https^3A^2F^2Fexample.com^2Ftest.zip'
        self.assertEqual(encoded, expected_encoded)

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

    def test_download_and_extract_archive_zip(self) -> None:
        """Test archive format detection for ZIP files."""
        with patch('builder.Path.cwd', return_value=self.temp_path):
            manager = BuilderManager()

        # Mock the download_and_extract_zip method
        with patch.object(manager, 'download_and_extract_zip') as mock_zip:
            url = "https://example.com/test.zip"
            target_dir = self.temp_path / "test"
            target_dir.mkdir()

            manager.download_and_extract_archive(url, target_dir)
            mock_zip.assert_called_once_with(url, target_dir)

    def test_download_and_extract_archive_tar_gz(self) -> None:
        """Test archive format detection for TAR.GZ files."""
        with patch('builder.Path.cwd', return_value=self.temp_path):
            manager = BuilderManager()

        # Mock the download_and_extract_tar method
        with patch.object(manager, 'download_and_extract_tar') as mock_tar:
            for url in ["https://example.com/test.tar.gz", "https://example.com/test.tgz"]:
                with self.subTest(url=url):
                    target_dir = self.temp_path / "test"
                    target_dir.mkdir(exist_ok=True)

                    manager.download_and_extract_archive(url, target_dir)
                    mock_tar.assert_called_with(url, target_dir)

    def test_download_and_extract_archive_unsupported(self) -> None:
        """Test archive format detection for unsupported formats."""
        with patch('builder.Path.cwd', return_value=self.temp_path):
            manager = BuilderManager()

        target_dir = self.temp_path / "test"
        target_dir.mkdir()

        with self.assertRaises(RuntimeError) as cm:
            manager.download_and_extract_archive("https://example.com/test.rar", target_dir)

        self.assertIn("Unsupported archive format", str(cm.exception))
        self.assertIn(".zip, .tar.gz, .tgz", str(cm.exception))

    def test_parse_git_url_with_reference(self) -> None:
        """Test parsing Git URLs with references."""
        with patch('builder.Path.cwd', return_value=self.temp_path):
            manager = BuilderManager()

        # Test URL with branch reference
        git_url, ref = manager._parse_git_url("https://github.com/user/repo.git#main")
        self.assertEqual(git_url, "https://github.com/user/repo.git")
        self.assertEqual(ref, "main")

        # Test URL with tag reference
        git_url, ref = manager._parse_git_url("https://github.com/user/repo.git#v1.0.0")
        self.assertEqual(git_url, "https://github.com/user/repo.git")
        self.assertEqual(ref, "v1.0.0")

        # Test URL with commit reference
        git_url, ref = manager._parse_git_url("https://github.com/user/repo.git#abc123")
        self.assertEqual(git_url, "https://github.com/user/repo.git")
        self.assertEqual(ref, "abc123")

    def test_parse_git_url_without_reference(self) -> None:
        """Test parsing Git URLs without references."""
        with patch('builder.Path.cwd', return_value=self.temp_path):
            manager = BuilderManager()

        git_url, ref = manager._parse_git_url("https://github.com/user/repo.git")
        self.assertEqual(git_url, "https://github.com/user/repo.git")
        self.assertIsNone(ref)

    @patch('builder.subprocess.run')
    def test_clone_and_checkout_git_with_reference(self, mock_run: Mock) -> None:
        """Test Git cloning with a specific reference."""
        with patch('builder.Path.cwd', return_value=self.temp_path):
            manager = BuilderManager()

        # Mock successful clone and checkout
        mock_run.side_effect = [
            Mock(returncode=0),  # clone
            Mock(returncode=0)   # checkout
        ]

        target_dir = self.temp_path / "test_repo"
        url = "https://github.com/user/repo.git#v1.0.0"

        with patch('builder.os.chdir') as mock_chdir, patch('builder.os.getcwd', return_value='/original'):
            manager.clone_and_checkout_git(url, target_dir)

        # Verify clone command
        mock_run.assert_any_call(
            ['git', 'clone', '--filter=blob:none', '--no-checkout', '--single-branch',
             'https://github.com/user/repo.git', str(target_dir)],
            capture_output=True,
            text=True
        )

        # Verify checkout command
        mock_run.assert_any_call(
            ['git', 'checkout', 'v1.0.0'],
            capture_output=True,
            text=True
        )

    @patch('builder.subprocess.run')
    def test_clone_and_checkout_git_default_branch_main(self, mock_run: Mock) -> None:
        """Test Git cloning with default branch (main)."""
        with patch('builder.Path.cwd', return_value=self.temp_path):
            manager = BuilderManager()

        # Mock successful clone and main checkout
        mock_run.side_effect = [
            Mock(returncode=0),  # clone
            Mock(returncode=0)   # checkout main
        ]

        target_dir = self.temp_path / "test_repo"
        url = "https://github.com/user/repo.git"

        with patch('builder.os.chdir') as mock_chdir, patch('builder.os.getcwd', return_value='/original'):
            manager.clone_and_checkout_git(url, target_dir)

        # Verify checkout tried main first
        mock_run.assert_any_call(
            ['git', 'checkout', 'main'],
            capture_output=True,
            text=True
        )

    @patch('builder.subprocess.run')
    def test_clone_and_checkout_git_fallback_to_master(self, mock_run: Mock) -> None:
        """Test Git cloning falls back to master when main doesn't exist."""
        with patch('builder.Path.cwd', return_value=self.temp_path):
            manager = BuilderManager()

        # Mock successful clone, failed main checkout, successful master checkout
        mock_run.side_effect = [
            Mock(returncode=0),  # clone
            Mock(returncode=1),  # checkout main (fails)
            Mock(returncode=0)   # checkout master (succeeds)
        ]

        target_dir = self.temp_path / "test_repo"
        url = "https://github.com/user/repo.git"

        with patch('builder.os.chdir') as mock_chdir, patch('builder.os.getcwd', return_value='/original'):
            manager.clone_and_checkout_git(url, target_dir)

        # Verify both branches were tried
        mock_run.assert_any_call(
            ['git', 'checkout', 'main'],
            capture_output=True,
            text=True
        )
        mock_run.assert_any_call(
            ['git', 'checkout', 'master'],
            capture_output=True,
            text=True
        )

    @patch('builder.subprocess.run')
    def test_clone_and_checkout_git_no_default_branches(self, mock_run: Mock) -> None:
        """Test Git cloning fails when neither main nor master exist."""
        with patch('builder.Path.cwd', return_value=self.temp_path):
            manager = BuilderManager()

        # Mock successful clone but failed checkouts for both branches
        mock_run.side_effect = [
            Mock(returncode=0),  # clone
            Mock(returncode=1),  # checkout main (fails)
            Mock(returncode=1)   # checkout master (fails)
        ]

        target_dir = self.temp_path / "test_repo"
        url = "https://github.com/user/repo.git"

        with patch('builder.os.chdir') as mock_chdir, patch('builder.os.getcwd', return_value='/original'):
            with self.assertRaises(RuntimeError) as cm:
                manager.clone_and_checkout_git(url, target_dir)

        self.assertIn("Neither 'main' nor 'master' branch exists", str(cm.exception))

    def test_download_or_clone_source_git_url(self) -> None:
        """Test source download dispatcher chooses Git for .git URLs."""
        with patch('builder.Path.cwd', return_value=self.temp_path):
            manager = BuilderManager()

        target_dir = self.temp_path / "test"
        target_dir.mkdir()

        with patch.object(manager, 'clone_and_checkout_git') as mock_git:
            manager.download_or_clone_source("https://github.com/user/repo.git", target_dir)
            mock_git.assert_called_once_with("https://github.com/user/repo.git", target_dir)

    def test_download_or_clone_source_git_url_with_reference(self) -> None:
        """Test source download dispatcher chooses Git for .git URLs with references."""
        with patch('builder.Path.cwd', return_value=self.temp_path):
            manager = BuilderManager()

        target_dir = self.temp_path / "test"
        target_dir.mkdir()

        with patch.object(manager, 'clone_and_checkout_git') as mock_git:
            manager.download_or_clone_source("https://github.com/user/repo.git#v1.0.0", target_dir)
            mock_git.assert_called_once_with("https://github.com/user/repo.git#v1.0.0", target_dir)

    def test_download_or_clone_source_archive_url(self) -> None:
        """Test source download dispatcher chooses archive extraction for non-Git URLs."""
        with patch('builder.Path.cwd', return_value=self.temp_path):
            manager = BuilderManager()

        target_dir = self.temp_path / "test"
        target_dir.mkdir()

        with patch.object(manager, 'download_and_extract_archive') as mock_archive:
            manager.download_or_clone_source("https://example.com/project.zip", target_dir)
            mock_archive.assert_called_once_with("https://example.com/project.zip", target_dir)

    def test_parse_time_spec_valid(self) -> None:
        """Test parsing valid time specifications."""
        with patch('builder.Path.cwd', return_value=self.temp_path):
            manager = BuilderManager()

        # Test seconds
        delta = manager._parse_time_spec("30s")
        self.assertEqual(delta.total_seconds(), 30)

        # Test minutes
        delta = manager._parse_time_spec("5m")
        self.assertEqual(delta.total_seconds(), 5 * 60)

        # Test hours
        delta = manager._parse_time_spec("2h")
        self.assertEqual(delta.total_seconds(), 2 * 3600)

        # Test days
        delta = manager._parse_time_spec("7d")
        self.assertEqual(delta.total_seconds(), 7 * 24 * 3600)

        # Test case insensitive
        delta = manager._parse_time_spec("10M")
        self.assertEqual(delta.total_seconds(), 10 * 60)

    def test_parse_time_spec_invalid(self) -> None:
        """Test parsing invalid time specifications."""
        with patch('builder.Path.cwd', return_value=self.temp_path):
            manager = BuilderManager()

        invalid_specs = [
            "",           # Empty
            "5",          # No unit
            "m5",         # Unit before number
            "5x",         # Invalid unit
            "0s",         # Zero amount (after int conversion)
            "-5m",        # Negative amount
            "5.5h",       # Decimal amount
            "abc",        # Non-numeric
            "5 m",        # Space in between
        ]

        for spec in invalid_specs:
            with self.subTest(spec=spec):
                with self.assertRaises(ValueError):
                    manager._parse_time_spec(spec)

    @patch('builder.datetime')
    def test_prune_cache_removes_old_files(self, mock_datetime: Mock) -> None:
        """Test cache pruning removes old files."""
        # Mock current time
        current_time = datetime(2023, 10, 5, 12, 0, 0)
        mock_datetime.now.return_value = current_time
        mock_datetime.fromtimestamp.side_effect = datetime.fromtimestamp

        with patch('builder.Path.cwd', return_value=self.temp_path), \
             patch('builder.Path.home', return_value=self.temp_path):
            manager = BuilderManager()

        # Create cache structure
        manager.ensure_cache_directories()

        # Create old cache entry (6 hours ago)
        old_cache_dir = manager.executables_dir / "old_entry"
        old_cache_dir.mkdir(exist_ok=True)
        old_builder = old_cache_dir / "builder"
        old_builder.touch()

        # Create recent cache entry (1 hour ago)
        new_cache_dir = manager.executables_dir / "new_entry"
        new_cache_dir.mkdir(exist_ok=True)
        new_builder = new_cache_dir / "builder"
        new_builder.touch()

        # Mock the _get_file_age method instead of stat
        def mock_get_file_age(file_path):
            if 'old_entry' in str(file_path):
                return current_time - timedelta(hours=6)
            else:
                return current_time - timedelta(hours=1)

        with patch.object(manager, '_get_file_age', side_effect=mock_get_file_age):
            # Prune files older than 2 hours
            removed = manager.prune_cache(timedelta(hours=2))

        # Should remove 1 old file
        self.assertEqual(removed, 1)
        # The old cache directory should be removed
        self.assertFalse(old_cache_dir.exists())
        # The new cache directory should still exist
        self.assertTrue(new_cache_dir.exists())

    @patch('builder.datetime')
    def test_prune_cache_no_files_to_remove(self, mock_datetime: Mock) -> None:
        """Test cache pruning when no files need removal."""
        current_time = datetime(2023, 10, 5, 12, 0, 0)
        mock_datetime.now.return_value = current_time
        mock_datetime.fromtimestamp.side_effect = datetime.fromtimestamp

        with patch('builder.Path.cwd', return_value=self.temp_path), \
             patch('builder.Path.home', return_value=self.temp_path):
            manager = BuilderManager()

        # Create cache structure
        manager.ensure_cache_directories()

        # Create recent cache entry (1 hour ago)
        cache_dir = manager.executables_dir / "recent_entry"
        cache_dir.mkdir(exist_ok=True)
        builder = cache_dir / "builder"
        builder.touch()

        # Mock the _get_file_age method to return recent time
        def mock_get_file_age(file_path):
            return current_time - timedelta(minutes=15)  # 15 minutes ago (newer than 30 minute cutoff)

        with patch.object(manager, '_get_file_age', side_effect=mock_get_file_age):
            # Try to prune files older than 30 minutes
            removed = manager.prune_cache(timedelta(minutes=30))

        # Should remove 0 files
        self.assertEqual(removed, 0)
        # Cache directory should still exist
        self.assertTrue(cache_dir.exists())

    def test_prune_cache_nonexistent_directory(self) -> None:
        """Test cache pruning when cache directory doesn't exist."""
        with patch('builder.Path.cwd', return_value=self.temp_path), \
             patch('builder.Path.home', return_value=self.temp_path):
            manager = BuilderManager()

        # Don't create cache directories
        removed = manager.prune_cache(timedelta(hours=1))
        self.assertEqual(removed, 0)

    def test_copy_and_extract_file_archive_zip(self) -> None:
        """Test extracting local ZIP archive."""
        with patch('builder.Path.cwd', return_value=self.temp_path), \
             patch('builder.Path.home', return_value=self.temp_path):
            manager = BuilderManager()

        # Create a test zip file
        test_dir = self.temp_path / "test_content"
        test_dir.mkdir()
        test_file = test_dir / "test.txt"
        test_file.write_text("Hello, World!")

        zip_path = self.temp_path / "test.zip"
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            zipf.write(test_file, "test.txt")

        # Extract to target directory
        target_dir = self.temp_path / "extracted"
        target_dir.mkdir()

        manager.copy_and_extract_file_archive(str(zip_path), target_dir)

        # Verify extraction
        extracted_file = target_dir / "test.txt"
        self.assertTrue(extracted_file.exists())
        self.assertEqual(extracted_file.read_text(), "Hello, World!")

    def test_copy_and_extract_file_archive_tar_gz(self) -> None:
        """Test extracting local tar.gz archive."""
        with patch('builder.Path.cwd', return_value=self.temp_path), \
             patch('builder.Path.home', return_value=self.temp_path):
            manager = BuilderManager()

        # Create a test tar.gz file
        test_dir = self.temp_path / "test_content"
        test_dir.mkdir()
        test_file = test_dir / "test.txt"
        test_file.write_text("Hello, tar.gz!")

        tar_path = self.temp_path / "test.tar.gz"
        with tarfile.open(tar_path, 'w:gz') as tarf:
            tarf.add(test_file, arcname="test.txt")

        # Extract to target directory
        target_dir = self.temp_path / "extracted"
        target_dir.mkdir()

        manager.copy_and_extract_file_archive(str(tar_path), target_dir)

        # Verify extraction
        extracted_file = target_dir / "test.txt"
        self.assertTrue(extracted_file.exists())
        self.assertEqual(extracted_file.read_text(), "Hello, tar.gz!")

    def test_copy_and_extract_file_archive_nonexistent(self) -> None:
        """Test error handling for nonexistent archive file."""
        with patch('builder.Path.cwd', return_value=self.temp_path), \
             patch('builder.Path.home', return_value=self.temp_path):
            manager = BuilderManager()

        target_dir = self.temp_path / "extracted"
        target_dir.mkdir()

        with self.assertRaises(FileNotFoundError):
            manager.copy_and_extract_file_archive("/nonexistent/file.zip", target_dir)

    def test_copy_and_extract_file_archive_unsupported_format(self) -> None:
        """Test error handling for unsupported archive format."""
        with patch('builder.Path.cwd', return_value=self.temp_path), \
             patch('builder.Path.home', return_value=self.temp_path):
            manager = BuilderManager()

        # Create a file with unsupported extension
        test_file = self.temp_path / "test.rar"
        test_file.write_text("fake rar file")

        target_dir = self.temp_path / "extracted"
        target_dir.mkdir()

        with self.assertRaises(RuntimeError) as cm:
            manager.copy_and_extract_file_archive(str(test_file), target_dir)

        self.assertIn("Unsupported local archive format", str(cm.exception))

    def test_copy_file_directory(self) -> None:
        """Test copying local directory."""
        with patch('builder.Path.cwd', return_value=self.temp_path), \
             patch('builder.Path.home', return_value=self.temp_path):
            manager = BuilderManager()

        # Create source directory with files
        source_dir = self.temp_path / "source"
        source_dir.mkdir()

        # Create some test files
        (source_dir / "file1.txt").write_text("Content 1")
        (source_dir / "file2.txt").write_text("Content 2")

        # Create subdirectory
        sub_dir = source_dir / "subdir"
        sub_dir.mkdir()
        (sub_dir / "file3.txt").write_text("Content 3")

        # Copy to target directory
        target_dir = self.temp_path / "target"

        manager.copy_file_directory(str(source_dir), target_dir)

        # Verify copy
        self.assertTrue(target_dir.exists())
        self.assertTrue((target_dir / "file1.txt").exists())
        self.assertTrue((target_dir / "file2.txt").exists())
        self.assertTrue((target_dir / "subdir" / "file3.txt").exists())

        self.assertEqual((target_dir / "file1.txt").read_text(), "Content 1")
        self.assertEqual((target_dir / "file2.txt").read_text(), "Content 2")
        self.assertEqual((target_dir / "subdir" / "file3.txt").read_text(), "Content 3")

    def test_copy_file_directory_nonexistent(self) -> None:
        """Test error handling for nonexistent directory."""
        with patch('builder.Path.cwd', return_value=self.temp_path), \
             patch('builder.Path.home', return_value=self.temp_path):
            manager = BuilderManager()

        target_dir = self.temp_path / "target"

        with self.assertRaises(FileNotFoundError):
            manager.copy_file_directory("/nonexistent/directory", target_dir)

    def test_handle_file_url_archive(self) -> None:
        """Test handling file URL pointing to archive."""
        with patch('builder.Path.cwd', return_value=self.temp_path), \
             patch('builder.Path.home', return_value=self.temp_path):
            manager = BuilderManager()

        # Create a test zip file
        test_dir = self.temp_path / "test_content"
        test_dir.mkdir()
        test_file = test_dir / "test.txt"
        test_file.write_text("Hello from archive!")

        zip_path = self.temp_path / "test.zip"
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            zipf.write(test_file, "test.txt")

        target_dir = self.temp_path / "target"
        target_dir.mkdir()

        manager._handle_file_url(str(zip_path), target_dir)

        # Verify extraction
        extracted_file = target_dir / "test.txt"
        self.assertTrue(extracted_file.exists())
        self.assertEqual(extracted_file.read_text(), "Hello from archive!")

    def test_handle_file_url_directory(self) -> None:
        """Test handling file URL pointing to directory."""
        with patch('builder.Path.cwd', return_value=self.temp_path), \
             patch('builder.Path.home', return_value=self.temp_path):
            manager = BuilderManager()

        # Create source directory
        source_dir = self.temp_path / "source"
        source_dir.mkdir()
        (source_dir / "file.txt").write_text("Hello from directory!")

        target_dir = self.temp_path / "target"

        manager._handle_file_url(str(source_dir), target_dir)

        # Verify copy
        copied_file = target_dir / "file.txt"
        self.assertTrue(copied_file.exists())
        self.assertEqual(copied_file.read_text(), "Hello from directory!")

    def test_download_or_clone_source_file_url(self) -> None:
        """Test source dispatcher with file:// URL."""
        with patch('builder.Path.cwd', return_value=self.temp_path), \
             patch('builder.Path.home', return_value=self.temp_path):
            manager = BuilderManager()

        # Create source directory
        source_dir = self.temp_path / "source"
        source_dir.mkdir()
        (source_dir / "test.txt").write_text("Test content")

        target_dir = self.temp_path / "target"

        # Test file:// URL
        file_url = f"file://{source_dir}"
        manager.download_or_clone_source(file_url, target_dir)

        # Verify copy
        copied_file = target_dir / "test.txt"
        self.assertTrue(copied_file.exists())
        self.assertEqual(copied_file.read_text(), "Test content")

    def test_download_or_clone_source_local_path(self) -> None:
        """Test source dispatcher with local file path."""
        with patch('builder.Path.cwd', return_value=self.temp_path), \
             patch('builder.Path.home', return_value=self.temp_path):
            manager = BuilderManager()

        # Create source directory
        source_dir = self.temp_path / "source"
        source_dir.mkdir()
        (source_dir / "test.txt").write_text("Local content")

        target_dir = self.temp_path / "target"

        # Test absolute path
        manager.download_or_clone_source(str(source_dir), target_dir)

        # Verify copy
        copied_file = target_dir / "test.txt"
        self.assertTrue(copied_file.exists())
        self.assertEqual(copied_file.read_text(), "Local content")


if __name__ == '__main__':
    unittest.main()


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
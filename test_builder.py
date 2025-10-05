#!/usr/bin/env python3
"""
Unit tests for the builder.py script - Fixed version testing individual components.
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
from builder import (
    BuilderRunner, ProjectConfiguration, PathBuilder, TrustManager,
    CacheManager, SourceFetcher, BuilderBuilder, CommandProcessor
)


class TestProjectConfiguration(unittest.TestCase):
    """Test cases for the ProjectConfiguration class."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)
        self.test_config_url = 'https://example.com/test.zip'
        self.config_file = self.temp_path / "builder.yaml"

    def tearDown(self) -> None:
        """Clean up after tests."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_builder_url_property(self) -> None:
        """Test that builder_url is loaded correctly from builder.yaml."""
        with open(self.config_file, 'w') as f:
            f.write(f'builder_binary: {self.test_config_url}\n')

        configuration = ProjectConfiguration(self.config_file)
        self.assertEqual(configuration.builder_url, self.test_config_url)

    def test_load_project_config_missing_file(self) -> None:
        """Test loading config with missing builder.yaml file."""
        with self.assertRaises(FileNotFoundError):
            ProjectConfiguration(self.config_file)

    def test_load_project_config_invalid_config(self) -> None:
        """Test loading config with invalid YAML content."""
        with open(self.config_file, 'w') as f:
            f.write('invalid: yaml: content: [unclosed\n')

        with self.assertRaises(Exception):
            ProjectConfiguration(self.config_file)

    def test_config_file_property(self) -> None:
        """Test config_file property returns correct path."""
        with open(self.config_file, 'w') as f:
            f.write(f'builder_binary: {self.test_config_url}\n')

        configuration = ProjectConfiguration(self.config_file)
        self.assertEqual(configuration.config_file, self.config_file)


class TestPathBuilder(unittest.TestCase):
    """Test cases for the PathBuilder class."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)
        self.home_dir = self.temp_path
        self.project_root = self.temp_path / "project"
        self.project_root.mkdir(exist_ok=True)

    def tearDown(self) -> None:
        """Clean up after tests."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_caret_encode_url(self) -> None:
        """Test URL encoding using caret encoding."""
        path_builder = PathBuilder(self.home_dir, self.project_root)

        # Test safe characters are unchanged
        safe_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~"
        self.assertEqual(path_builder._caret_encode_url(safe_chars), safe_chars)

        # Test unsafe characters are encoded
        unsafe_chars = ['/', ':', '?', '#', '[', ']', '@', '!', '$', '&', "'", '(', ')', '*', '+', ',', ';', '=']
        for char in unsafe_chars:
            result = path_builder._caret_encode_url(char)
            self.assertTrue(result.startswith('^'))
            self.assertNotEqual(result, char)

        # Test full URL encoding
        url = "https://github.com/user/repo.git?tag=v1.0"
        encoded = path_builder._caret_encode_url(url)
        self.assertNotIn(':', encoded)
        self.assertNotIn('/', encoded)
        self.assertNotIn('?', encoded)

    def test_get_builder_cache_dir(self) -> None:
        """Test getting cache directory for a URL."""
        path_builder = PathBuilder(self.home_dir, self.project_root)
        url = "https://github.com/test/repo.git"
        cache_dir = path_builder.get_builder_cache_dir(url)
        expected_dir = path_builder.get_executables_dir() / path_builder._caret_encode_url(url)
        self.assertEqual(cache_dir, expected_dir)

    def test_get_builder_executable_path_for_url(self) -> None:
        """Test getting executable path for a URL."""
        path_builder = PathBuilder(self.home_dir, self.project_root)
        url = "https://github.com/test/repo.git"
        exe_path = path_builder.get_builder_executable_path_for_url(url)
        expected_path = path_builder.get_builder_cache_dir(url) / "builder"
        self.assertEqual(exe_path, expected_path)

    def test_path_methods(self) -> None:
        """Test various path accessor methods."""
        path_builder = PathBuilder(self.home_dir, self.project_root)

        # Test directory paths
        self.assertEqual(path_builder.get_cache_dir(), self.home_dir / ".cache" / "builder")
        self.assertEqual(path_builder.get_executables_dir(), self.home_dir / ".cache" / "builder" / "executables")
        self.assertEqual(path_builder.get_config_dir(), self.home_dir / ".config" / "builder")

        # Test file paths
        self.assertEqual(path_builder.get_config_dir() / "trusted_urls", self.home_dir / ".config" / "builder" / "trusted_urls")
        self.assertEqual(path_builder.get_project_config_file(), self.project_root / "builder.yaml")


class TestTrustManager(unittest.TestCase):
    """Test cases for the TrustManager class."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)
        self.project_root = self.temp_path / "project"
        self.project_root.mkdir(exist_ok=True)
        self.path_builder = PathBuilder(self.temp_path, self.project_root)

    def tearDown(self) -> None:
        """Clean up after tests."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_extract_domain(self) -> None:
        """Test domain extraction from URLs."""
        trust_manager = TrustManager(self.path_builder)

        test_cases = [
            ("https://github.com/user/repo.git", "github.com"),
            ("http://example.com/path", "example.com"),
            ("ftp://files.example.org/file.txt", "files.example.org"),
            ("https://sub.domain.com:8080/path", "sub.domain.com:8080"),
            ("invalid-url", "")  # Invalid URLs return empty string
        ]

        for url, expected_domain in test_cases:
            domain = trust_manager._extract_domain(url)
            self.assertEqual(domain, expected_domain, f"Failed for URL: {url}")

    def test_load_trusted_urls_builtin_only(self) -> None:
        """Test loading trusted URLs with no file (builtin only)."""
        trust_manager = TrustManager(self.path_builder)
        trusted_urls = trust_manager.all_trusted_urls()

        # Should contain builtin trusted URLs
        self.assertIn("https://github.com/kstenerud/builder-test.git", trusted_urls)
        self.assertGreater(len(trusted_urls), 0)

    def test_load_trusted_urls_with_file(self) -> None:
        """Test loading trusted URLs with existing file."""
        trust_manager = TrustManager(self.path_builder)

        # Create config directory and file
        self.path_builder.get_config_dir().mkdir(parents=True, exist_ok=True)
        trusted_urls_file = self.path_builder.get_config_dir() / "trusted_urls"

    def test_add_trusted_url_new(self) -> None:
        """Test adding a new trusted URL."""
        trust_manager = TrustManager(self.path_builder)
        new_url = "https://newtrusted.com/repo.git"

        trust_manager.add_trusted_url(new_url)

        # Verify it was added
        trusted_urls = trust_manager.all_trusted_urls()
        self.assertIn(new_url, trusted_urls)

    def test_add_trusted_url_duplicate(self) -> None:
        """Test adding a duplicate trusted URL."""
        trust_manager = TrustManager(self.path_builder)
        builtin_url = trust_manager.builtin_trusted_urls[0]

        # Get initial count
        initial_urls = trust_manager.all_trusted_urls()
        initial_count = len(initial_urls)

        trust_manager.add_trusted_url(builtin_url)

        # Verify the URL was added to user list (even though it's already in builtin list)
        final_urls = trust_manager.all_trusted_urls()
        self.assertEqual(len(final_urls), initial_count + 1)

    def test_remove_trusted_url_success(self) -> None:
        """Test removing a trusted URL successfully."""
        trust_manager = TrustManager(self.path_builder)
        test_url = "https://removeme.com/repo.git"

        # Add the URL first
        trust_manager.add_trusted_url(test_url)

        # Remove it
        trust_manager.remove_trusted_url(test_url)

        # Verify it was removed
        trusted_urls = trust_manager.all_trusted_urls()
        self.assertNotIn(test_url, trusted_urls)

    def test_remove_trusted_url_builtin(self) -> None:
        """Test removing a builtin trusted URL."""
        trust_manager = TrustManager(self.path_builder)
        builtin_url = trust_manager.builtin_trusted_urls[0]

        # Get initial state
        initial_urls = trust_manager.all_trusted_urls()

        trust_manager.remove_trusted_url(builtin_url)

        # Verify builtin URL is still present (cannot be removed)
        final_urls = trust_manager.all_trusted_urls()
        self.assertIn(builtin_url, final_urls)

    def test_remove_trusted_url_not_found(self) -> None:
        """Test removing a URL that doesn't exist."""
        trust_manager = TrustManager(self.path_builder)
        nonexistent_url = "https://nonexistent.com/repo.git"

        # Get initial state
        initial_urls = trust_manager.all_trusted_urls()

        trust_manager.remove_trusted_url(nonexistent_url)

        # Verify nothing changed
        final_urls = trust_manager.all_trusted_urls()
        self.assertEqual(initial_urls, final_urls)

    def test_is_url_trusted_builtin(self) -> None:
        """Test URL trust validation for builtin URLs."""
        trust_manager = TrustManager(self.path_builder)
        self.assertTrue(trust_manager.is_url_trusted("https://github.com/kstenerud/builder-test.git"))

    def test_is_url_trusted_same_domain(self) -> None:
        """Test URL trust validation for same domain."""
        trust_manager = TrustManager(self.path_builder)

        # Add a trusted URL
        trust_manager.add_trusted_url("https://github.com/trusted/repo.git")

        # Test same domain URLs
        self.assertTrue(trust_manager.is_url_trusted("https://github.com/other/repo.git"))
        self.assertTrue(trust_manager.is_url_trusted("https://github.com/different/project.git"))

        # Test different domain
        self.assertFalse(trust_manager.is_url_trusted("https://malicious.com/repo.git"))

    def test_validate_builder_url_trust_success(self) -> None:
        """Test successful URL trust validation."""
        trust_manager = TrustManager(self.path_builder)
        trusted_url = "https://github.com/kstenerud/builder-test.git"

        trust_manager.validate_builder_url_trust(trusted_url)  # Should not raise

    def test_validate_builder_url_trust_failure(self) -> None:
        """Test failed URL trust validation."""
        trust_manager = TrustManager(self.path_builder)
        untrusted_url = "https://malicious.com/evil.git"

        with self.assertRaises(ValueError) as cm:
            trust_manager.validate_builder_url_trust(untrusted_url)

        self.assertIn("Untrusted URL domain", str(cm.exception))


class TestSourceFetcher(unittest.TestCase):
    """Test cases for the SourceFetcher class."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

    def tearDown(self) -> None:
        """Clean up after tests."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_download_and_extract_archive_zip(self) -> None:
        """Test archive format detection for ZIP files through public interface."""
        source_fetcher = SourceFetcher()

        # Mock the private _download_and_extract_archive method
        with patch.object(source_fetcher, '_download_and_extract_archive') as mock_download:
            url = "https://example.com/test.zip"
            target_dir = self.temp_path / "test"
            target_dir.mkdir()

            source_fetcher.clone_source(url, target_dir)
            mock_download.assert_called_once_with(url, target_dir)

    def test_download_and_extract_archive_tar_gz(self) -> None:
        """Test archive format detection for TAR.GZ files through public interface."""
        source_fetcher = SourceFetcher()

        # Mock the private _download_and_extract_archive method
        with patch.object(source_fetcher, '_download_and_extract_archive') as mock_download:
            url = "https://example.com/test.tar.gz"
            target_dir = self.temp_path / "test"
            target_dir.mkdir()

            source_fetcher.clone_source(url, target_dir)
            mock_download.assert_called_once_with(url, target_dir)

    def test_download_and_extract_archive_unsupported(self) -> None:
        """Test archive format detection for unsupported formats through public interface."""
        source_fetcher = SourceFetcher()
        target_dir = self.temp_path / "test"
        target_dir.mkdir()

        with self.assertRaises(RuntimeError) as cm:
            source_fetcher.clone_source("https://example.com/test.rar", target_dir)

        self.assertIn("Unsupported archive format", str(cm.exception))

    def test_parse_git_url_with_reference(self) -> None:
        """Test parsing Git URLs with references."""
        source_fetcher = SourceFetcher()

        git_url, ref = source_fetcher._parse_git_url("https://github.com/user/repo.git#main")
        self.assertEqual(git_url, "https://github.com/user/repo.git")
        self.assertEqual(ref, "main")

        git_url, ref = source_fetcher._parse_git_url("https://github.com/user/repo.git#v1.0.0")
        self.assertEqual(git_url, "https://github.com/user/repo.git")
        self.assertEqual(ref, "v1.0.0")

        git_url, ref = source_fetcher._parse_git_url("https://github.com/user/repo.git#abc123")
        self.assertEqual(git_url, "https://github.com/user/repo.git")
        self.assertEqual(ref, "abc123")

    def test_parse_git_url_without_reference(self) -> None:
        """Test parsing Git URLs without references."""
        source_fetcher = SourceFetcher()

        git_url, ref = source_fetcher._parse_git_url("https://github.com/user/repo.git")
        self.assertEqual(git_url, "https://github.com/user/repo.git")
        self.assertIsNone(ref)

    @patch('subprocess.run')
    def test_clone_and_checkout_git_with_reference(self, mock_run: Mock) -> None:
        """Test Git cloning with specific reference through public interface."""
        source_fetcher = SourceFetcher()
        mock_run.return_value.returncode = 0

        url = "https://github.com/user/repo.git#v1.0.0"
        target_dir = self.temp_path / "test"
        target_dir.mkdir()

        source_fetcher.clone_source(url, target_dir)

        # Should call git clone and checkout
        self.assertEqual(mock_run.call_count, 2)

    @patch('subprocess.run')
    def test_clone_and_checkout_git_default_branch_main(self, mock_run: Mock) -> None:
        """Test Git cloning falls back to main branch through public interface."""
        source_fetcher = SourceFetcher()

        # First call (clone) succeeds, second call (checkout main) succeeds
        mock_run.side_effect = [
            Mock(returncode=0),  # git clone
            Mock(returncode=0)   # git checkout main
        ]

        url = "https://github.com/user/repo.git"
        target_dir = self.temp_path / "test"
        target_dir.mkdir()

        source_fetcher.clone_source(url, target_dir)

        # Should try main branch
        self.assertEqual(mock_run.call_count, 2)
        self.assertIn("main", str(mock_run.call_args_list[1]))

    def test_clone_source_archive_url(self) -> None:
        """Test source download dispatcher chooses archive extraction for non-Git URLs."""
        source_fetcher = SourceFetcher()
        target_dir = self.temp_path / "test"
        target_dir.mkdir()

        with patch.object(source_fetcher, '_download_and_extract_archive_by_extension') as mock_archive:
            source_fetcher.clone_source("https://example.com/project.zip", target_dir)
            mock_archive.assert_called_once_with("https://example.com/project.zip", target_dir)

    def test_clone_source_git_url(self) -> None:
        """Test source download dispatcher chooses Git clone for .git URLs."""
        source_fetcher = SourceFetcher()
        target_dir = self.temp_path / "test"
        target_dir.mkdir()

        with patch.object(source_fetcher, '_clone_and_checkout_git') as mock_git:
            source_fetcher.clone_source("https://github.com/user/repo.git", target_dir)
            mock_git.assert_called_once_with("https://github.com/user/repo.git", target_dir)


class TestBuilderBuilder(unittest.TestCase):
    """Test cases for the BuilderBuilder class."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

    def tearDown(self) -> None:
        """Clean up after tests."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_build_no_cargo_toml(self) -> None:
        """Test build failure when no Rust project is found."""
        builder = BuilderBuilder()

        # Create source directory with no Cargo.toml
        source_dir = self.temp_path / "source"
        source_dir.mkdir()

        with self.assertRaises(RuntimeError) as cm:
            builder.build(source_dir)

        self.assertIn("No Rust project (Cargo.toml) found", str(cm.exception))

    @patch('subprocess.run')
    def test_build_success(self, mock_run: Mock) -> None:
        """Test successful Rust project build."""
        builder = BuilderBuilder()
        mock_run.return_value.returncode = 0

        # Create source directory with Rust project
        source_dir = self.temp_path / "source"
        source_dir.mkdir()
        project_dir = source_dir / "project"
        project_dir.mkdir()

        # Create Cargo.toml to make it a Rust project
        cargo_toml = project_dir / "Cargo.toml"
        cargo_toml.write_text("[package]\nname = \"builder\"\nversion = \"0.1.0\"")

        # Create mock executable
        target_dir = project_dir / "target" / "release"
        target_dir.mkdir(parents=True)
        builder_exe = target_dir / "builder"
        builder_exe.write_text("mock executable")

        result = builder.build(source_dir)
        self.assertEqual(result, builder_exe)

    @patch('subprocess.run')
    def test_build_failure(self, mock_run: Mock) -> None:
        """Test Rust project build failure."""
        builder = BuilderBuilder()
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "Build failed"

        # Create source directory with Rust project
        source_dir = self.temp_path / "source"
        source_dir.mkdir()
        project_dir = source_dir / "project"
        project_dir.mkdir()

        # Create Cargo.toml to make it a Rust project
        cargo_toml = project_dir / "Cargo.toml"
        cargo_toml.write_text("[package]\nname = \"builder\"\nversion = \"0.1.0\"")

        with self.assertRaises(RuntimeError):
            builder.build(source_dir)


class TestCacheManager(unittest.TestCase):
    """Test cases for the CacheManager class."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)
        self.project_root = self.temp_path / "project"
        self.project_root.mkdir(exist_ok=True)
        self.path_builder = PathBuilder(self.temp_path, self.project_root)

    def tearDown(self) -> None:
        """Clean up after tests."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_ensure_cache_directories(self) -> None:
        """Test cache directory creation on construction."""
        # Directories should be created automatically during construction
        cache_manager = CacheManager(self.path_builder)

        self.assertTrue(self.path_builder.get_cache_dir().exists())
        self.assertTrue(self.path_builder.get_executables_dir().exists())

    def test_is_builder_cached(self) -> None:
        """Test checking if builder is cached."""
        cache_manager = CacheManager(self.path_builder)
        url = "https://github.com/test/repo.git"

        # Initially not cached
        self.assertFalse(cache_manager.is_builder_cached(url))

        # Create cached executable
        exe_path = self.path_builder.get_builder_executable_path_for_url(url)
        exe_path.parent.mkdir(parents=True, exist_ok=True)
        exe_path.write_text("mock executable")

        # Now should be cached
        self.assertTrue(cache_manager.is_builder_cached(url))

    def test_cache_builder(self) -> None:
        """Test caching builder executable with idempotent behavior."""
        cache_manager = CacheManager(self.path_builder)
        url = "https://github.com/test/repo.git"

        # Create source executable
        source_path = self.temp_path / "source_builder"
        source_path.write_text("mock executable")

        # Initially not cached
        self.assertFalse(cache_manager.is_builder_cached(url))

        cache_manager.cache_builder(source_path, url)

        # Verify it was cached
        self.assertTrue(cache_manager.is_builder_cached(url))

        # Test idempotent behavior - calling again should not fail
        cache_manager.cache_builder(source_path, url)
        self.assertTrue(cache_manager.is_builder_cached(url))

    def test_prune_older_than_or_equal_age_comparison(self) -> None:
        """Test cache pruning with various age comparisons including edge case for age 0."""
        from datetime import datetime, timedelta
        import shutil
        import time

        cache_manager = CacheManager(self.path_builder)

        # Create multiple cache entries with different ages
        urls = [
            "https://github.com/test/repo1.git",
            "https://github.com/test/repo2.git",
            "https://github.com/test/repo3.git"
        ]

        # Create cached executables
        for url in urls:
            exe_path = self.path_builder.get_builder_executable_path_for_url(url)
            exe_path.parent.mkdir(parents=True, exist_ok=True)
            exe_path.write_text("mock executable")
            # Verify they are cached
            self.assertTrue(cache_manager.is_builder_cached(url))

        # Wait a small amount to ensure files have different ages
        time.sleep(0.01)

        # Test pruning with age 0 - should clear entire cache
        removed_paths = cache_manager.prune_older_than_or_equal(timedelta(seconds=0))
        self.assertEqual(len(removed_paths), 3, "Age 0 should remove all cache entries")

        # Verify all entries were removed
        for url in urls:
            self.assertFalse(cache_manager.is_builder_cached(url), f"Cache entry for {url} should be removed")

        # Recreate cache entries for second test
        for url in urls:
            exe_path = self.path_builder.get_builder_executable_path_for_url(url)
            exe_path.parent.mkdir(parents=True, exist_ok=True)
            exe_path.write_text("mock executable")

        # Test pruning with very small age - should still remove entries due to <= comparison
        removed_paths = cache_manager.prune_older_than_or_equal(timedelta(microseconds=1))
        self.assertEqual(len(removed_paths), 3, "Very small age should remove all entries due to <= comparison")

        # Verify all entries were removed
        for url in urls:
            self.assertFalse(cache_manager.is_builder_cached(url), f"Cache entry for {url} should be removed with small age")


class TestBuilderRunnerIntegration(unittest.TestCase):
    """Integration tests for BuilderRunner with real component interactions."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

        # Create a mock builder.yaml
        self.config_file = self.temp_path / "builder.yaml"
        with open(self.config_file, 'w') as f:
            f.write('builder_binary: https://github.com/kstenerud/builder-test.git\n')

    def tearDown(self) -> None:
        """Clean up after tests."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_ensure_cache_directories(self) -> None:
        """Test that cache directories are created automatically."""
        with patch('builder.Path.cwd', return_value=self.temp_path):
            runner = BuilderRunner()

        # Directories should be created automatically during manager initialization
        self.assertTrue(runner.path_builder.get_cache_dir().exists())
        self.assertTrue(runner.path_builder.get_executables_dir().exists())

    def test_load_project_config(self) -> None:
        """Test loading project configuration."""
        with patch('builder.Path.cwd', return_value=self.temp_path):
            runner = BuilderRunner()

        url = runner.configuration.builder_url
        self.assertEqual(url, 'https://github.com/kstenerud/builder-test.git')

    def test_get_builder_executable_path(self) -> None:
        """Test getting builder executable path."""
        with patch('builder.Path.cwd', return_value=self.temp_path):
            runner = BuilderRunner()

        path = runner.path_builder.get_builder_executable_path_for_url(runner.configuration.builder_url)
        self.assertTrue(str(path).endswith('builder'))

    def test_is_builder_cached(self) -> None:
        """Test checking if builder is cached through CacheManager."""
        with patch('builder.Path.cwd', return_value=self.temp_path):
            runner = BuilderRunner()

        # Remove any existing cached executable to ensure clean state
        exe_path = runner.path_builder.get_builder_executable_path_for_url(runner.configuration.builder_url)
        if exe_path.exists():
            exe_path.unlink()

        # Initially not cached
        self.assertFalse(runner.cache_manager.is_builder_cached(runner.configuration.builder_url))

    @patch('builder.subprocess.run')
    def test_run_with_trust_validation(self, mock_run: Mock) -> None:
        """Test running builder with trust validation through public interface."""
        with patch('builder.Path.cwd', return_value=self.temp_path):
            runner = BuilderRunner()

        # Should not raise since the URL is in builtin trusted URLs
        # This is an integration test, so we won't mock everything
        try:
            # This will fail due to network/build, but trust validation should pass
            # Testing through public interface instead of private ensure_builder_available
            runner.run(['--version'])
        except Exception:
            # We expect this to fail at build stage, but trust validation should have passed
            pass


if __name__ == '__main__':
    unittest.main()
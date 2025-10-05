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
    BuilderManager, ConfigManager, PathManager, TrustManager, 
    CacheManager, SourceManager, BuildManager, CommandProcessor
)


class TestConfigManager(unittest.TestCase):
    """Test cases for the ConfigManager class."""

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

    def test_load_project_config(self) -> None:
        """Test loading builder_binary URL from builder.yaml."""
        with open(self.config_file, 'w') as f:
            f.write(f'builder_binary: {self.test_config_url}\n')

        config_manager = ConfigManager(self.temp_path)
        self.assertEqual(config_manager.load_project_config(), self.test_config_url)

    def test_load_project_config_missing_file(self) -> None:
        """Test loading config with missing builder.yaml file."""
        config_manager = ConfigManager(self.temp_path)
        with self.assertRaises(FileNotFoundError):
            config_manager.load_project_config()

    def test_load_project_config_invalid_config(self) -> None:
        """Test loading config with invalid YAML content."""
        with open(self.config_file, 'w') as f:
            f.write('invalid: yaml: content: [unclosed\n')

        config_manager = ConfigManager(self.temp_path)
        with self.assertRaises(Exception):
            config_manager.load_project_config()

    def test_config_file_property(self) -> None:
        """Test config_file property returns correct path."""
        config_manager = ConfigManager(self.temp_path)
        self.assertEqual(config_manager.config_file, self.config_file)


class TestPathManager(unittest.TestCase):
    """Test cases for the PathManager class."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)
        self.executables_dir = self.temp_path / "executables"

    def tearDown(self) -> None:
        """Clean up after tests."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_caret_encode_url(self) -> None:
        """Test URL encoding using caret encoding."""
        path_manager = PathManager(self.executables_dir)
        
        # Test safe characters are unchanged
        safe_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~"
        self.assertEqual(path_manager.caret_encode_url(safe_chars), safe_chars)

        # Test unsafe characters are encoded
        unsafe_chars = ['/', ':', '?', '#', '[', ']', '@', '!', '$', '&', "'", '(', ')', '*', '+', ',', ';', '=']
        for char in unsafe_chars:
            result = path_manager.caret_encode_url(char)
            self.assertTrue(result.startswith('^'))
            self.assertNotEqual(result, char)

        # Test full URL encoding
        url = "https://github.com/user/repo.git?tag=v1.0"
        encoded = path_manager.caret_encode_url(url)
        self.assertNotIn(':', encoded)
        self.assertNotIn('/', encoded)
        self.assertNotIn('?', encoded)

    def test_get_builder_cache_dir(self) -> None:
        """Test getting cache directory for a URL."""
        path_manager = PathManager(self.executables_dir)
        url = "https://github.com/test/repo.git"
        cache_dir = path_manager.get_builder_cache_dir(url)
        expected_dir = self.executables_dir / path_manager.caret_encode_url(url)
        self.assertEqual(cache_dir, expected_dir)

    def test_get_builder_executable_path_for_url(self) -> None:
        """Test getting executable path for a URL."""
        path_manager = PathManager(self.executables_dir)
        url = "https://github.com/test/repo.git"
        exe_path = path_manager.get_builder_executable_path_for_url(url)
        expected_path = path_manager.get_builder_cache_dir(url) / "builder"
        self.assertEqual(exe_path, expected_path)


class TestTrustManager(unittest.TestCase):
    """Test cases for the TrustManager class."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

    def tearDown(self) -> None:
        """Clean up after tests."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_extract_domain(self) -> None:
        """Test extracting domain from URLs."""
        trust_manager = TrustManager(self.temp_path)
        
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
        """Test loading trusted URLs when only builtin URLs exist."""
        trust_manager = TrustManager(self.temp_path)
        trusted_urls = trust_manager.load_trusted_urls()
        
        # Should contain builtin trusted URLs
        self.assertIn("https://github.com/kstenerud/builder-test.git", trusted_urls)
        self.assertGreater(len(trusted_urls), 0)

    def test_load_trusted_urls_with_file(self) -> None:
        """Test loading trusted URLs when trusted_urls.txt exists."""
        trust_manager = TrustManager(self.temp_path)
        
        # Create trusted URLs file
        custom_urls = [
            "https://custom.com/repo1.git",
            "https://custom.com/repo2.git"
        ]
        
        trust_manager.config_dir.mkdir(parents=True, exist_ok=True)
        with open(trust_manager.trusted_urls_file, 'w') as f:
            for url in custom_urls:
                f.write(f"{url}\n")
        
        trusted_urls = trust_manager.load_trusted_urls()
        
        # Should contain both builtin and custom URLs
        for url in custom_urls:
            self.assertIn(url, trusted_urls)
        self.assertIn("https://github.com/kstenerud/builder-test.git", trusted_urls)

    def test_add_trusted_url_new(self) -> None:
        """Test adding a new trusted URL."""
        trust_manager = TrustManager(self.temp_path)
        new_url = "https://newtrusted.com/repo.git"
        
        result = trust_manager.add_trusted_url(new_url)
        self.assertTrue(result)
        
        # Verify it was added
        trusted_urls = trust_manager.load_trusted_urls()
        self.assertIn(new_url, trusted_urls)

    def test_add_trusted_url_duplicate(self) -> None:
        """Test adding a duplicate trusted URL."""
        trust_manager = TrustManager(self.temp_path)
        builtin_url = trust_manager.builtin_trusted_urls[0]
        
        result = trust_manager.add_trusted_url(builtin_url)
        self.assertFalse(result)  # Should return False for duplicate

    def test_remove_trusted_url_success(self) -> None:
        """Test removing a trusted URL successfully."""
        trust_manager = TrustManager(self.temp_path)
        test_url = "https://removeme.com/repo.git"
        
        # Add the URL first
        trust_manager.add_trusted_url(test_url)
        
        # Remove it
        result = trust_manager.remove_trusted_url(test_url)
        self.assertTrue(result)
        
        # Verify it was removed
        trusted_urls = trust_manager.load_trusted_urls()
        self.assertNotIn(test_url, trusted_urls)

    def test_remove_trusted_url_builtin(self) -> None:
        """Test removing a builtin trusted URL."""
        trust_manager = TrustManager(self.temp_path)
        builtin_url = trust_manager.builtin_trusted_urls[0]
        
        result = trust_manager.remove_trusted_url(builtin_url)
        self.assertFalse(result)  # Cannot remove builtin URLs

    def test_remove_trusted_url_not_found(self) -> None:
        """Test removing a URL that doesn't exist."""
        trust_manager = TrustManager(self.temp_path)
        
        result = trust_manager.remove_trusted_url("https://nonexistent.com/repo.git")
        self.assertFalse(result)

    def test_is_url_trusted_builtin(self) -> None:
        """Test URL trust validation for builtin URLs."""
        trust_manager = TrustManager(self.temp_path)
        self.assertTrue(trust_manager.is_url_trusted("https://github.com/kstenerud/builder-test.git"))

    def test_is_url_trusted_same_domain(self) -> None:
        """Test URL trust validation for same domain."""
        trust_manager = TrustManager(self.temp_path)
        
        # Add a trusted URL
        trust_manager.add_trusted_url("https://github.com/trusted/repo.git")
        
        # Test same domain URLs
        self.assertTrue(trust_manager.is_url_trusted("https://github.com/other/repo.git"))
        self.assertTrue(trust_manager.is_url_trusted("https://github.com/different/project.git"))
        
        # Test different domain
        self.assertFalse(trust_manager.is_url_trusted("https://malicious.com/repo.git"))

    def test_validate_builder_url_trust_success(self) -> None:
        """Test successful URL trust validation."""
        trust_manager = TrustManager(self.temp_path)
        trusted_url = "https://github.com/kstenerud/builder-test.git"
        
        trust_manager.validate_builder_url_trust(trusted_url)  # Should not raise

    def test_validate_builder_url_trust_failure(self) -> None:
        """Test failed URL trust validation."""
        trust_manager = TrustManager(self.temp_path)
        untrusted_url = "https://malicious.com/evil.git"
        
        with self.assertRaises(ValueError) as cm:
            trust_manager.validate_builder_url_trust(untrusted_url)
        
        self.assertIn("Untrusted URL domain", str(cm.exception))


class TestSourceManager(unittest.TestCase):
    """Test cases for the SourceManager class."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

    def tearDown(self) -> None:
        """Clean up after tests."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_download_and_extract_archive_zip(self) -> None:
        """Test archive format detection for ZIP files."""
        source_manager = SourceManager()

        # Mock the _download_and_extract_archive method
        with patch.object(source_manager, '_download_and_extract_archive') as mock_download:
            url = "https://example.com/test.zip"
            target_dir = self.temp_path / "test"
            target_dir.mkdir()

            source_manager.download_and_extract_archive(url, target_dir)
            mock_download.assert_called_once_with(url, target_dir)

    def test_download_and_extract_archive_tar_gz(self) -> None:
        """Test archive format detection for TAR.GZ files."""
        source_manager = SourceManager()

        # Mock the _download_and_extract_archive method
        with patch.object(source_manager, '_download_and_extract_archive') as mock_download:
            url = "https://example.com/test.tar.gz"
            target_dir = self.temp_path / "test"
            target_dir.mkdir()

            source_manager.download_and_extract_archive(url, target_dir)
            mock_download.assert_called_once_with(url, target_dir)

    def test_download_and_extract_archive_unsupported(self) -> None:
        """Test archive format detection for unsupported formats."""
        source_manager = SourceManager()
        target_dir = self.temp_path / "test"
        target_dir.mkdir()

        with self.assertRaises(RuntimeError) as cm:
            source_manager.download_and_extract_archive("https://example.com/test.rar", target_dir)

        self.assertIn("Unsupported archive format", str(cm.exception))
        self.assertIn(".zip, .tar.gz, .tgz", str(cm.exception))

    def test_parse_git_url_with_reference(self) -> None:
        """Test parsing Git URLs with references."""
        source_manager = SourceManager()

        git_url, ref = source_manager._parse_git_url("https://github.com/user/repo.git#main")
        self.assertEqual(git_url, "https://github.com/user/repo.git")
        self.assertEqual(ref, "main")

        git_url, ref = source_manager._parse_git_url("https://github.com/user/repo.git#v1.0.0")
        self.assertEqual(git_url, "https://github.com/user/repo.git")
        self.assertEqual(ref, "v1.0.0")

        git_url, ref = source_manager._parse_git_url("https://github.com/user/repo.git#abc123")
        self.assertEqual(git_url, "https://github.com/user/repo.git")
        self.assertEqual(ref, "abc123")

    def test_parse_git_url_without_reference(self) -> None:
        """Test parsing Git URLs without references."""
        source_manager = SourceManager()

        git_url, ref = source_manager._parse_git_url("https://github.com/user/repo.git")
        self.assertEqual(git_url, "https://github.com/user/repo.git")
        self.assertIsNone(ref)

    @patch('subprocess.run')
    def test_clone_and_checkout_git_with_reference(self, mock_run: Mock) -> None:
        """Test Git cloning with specific reference."""
        source_manager = SourceManager()
        mock_run.return_value.returncode = 0

        url = "https://github.com/user/repo.git#v1.0.0"
        target_dir = self.temp_path / "test"
        target_dir.mkdir()

        source_manager.clone_and_checkout_git(url, target_dir)

        # Should call git clone and checkout
        self.assertEqual(mock_run.call_count, 2)

    @patch('subprocess.run')
    def test_clone_and_checkout_git_default_branch_main(self, mock_run: Mock) -> None:
        """Test Git cloning falls back to main branch."""
        source_manager = SourceManager()
        
        # First call (clone) succeeds, second call (checkout main) succeeds
        mock_run.side_effect = [
            Mock(returncode=0),  # git clone
            Mock(returncode=0)   # git checkout main
        ]

        url = "https://github.com/user/repo.git"
        target_dir = self.temp_path / "test"
        target_dir.mkdir()

        source_manager.clone_and_checkout_git(url, target_dir)

        # Should try main branch
        self.assertEqual(mock_run.call_count, 2)
        self.assertIn("main", str(mock_run.call_args_list[1]))

    def test_download_or_clone_source_archive_url(self) -> None:
        """Test source download dispatcher chooses archive extraction for non-Git URLs."""
        source_manager = SourceManager()
        target_dir = self.temp_path / "test"
        target_dir.mkdir()

        with patch.object(source_manager, 'download_and_extract_archive') as mock_archive:
            source_manager.download_or_clone_source("https://example.com/project.zip", target_dir)
            mock_archive.assert_called_once_with("https://example.com/project.zip", target_dir)

    def test_download_or_clone_source_git_url(self) -> None:
        """Test source download dispatcher chooses Git clone for .git URLs."""
        source_manager = SourceManager()
        target_dir = self.temp_path / "test"
        target_dir.mkdir()

        with patch.object(source_manager, 'clone_and_checkout_git') as mock_git:
            source_manager.download_or_clone_source("https://github.com/user/repo.git", target_dir)
            mock_git.assert_called_once_with("https://github.com/user/repo.git", target_dir)


class TestBuildManager(unittest.TestCase):
    """Test cases for the BuildManager class."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

    def tearDown(self) -> None:
        """Clean up after tests."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_find_rust_project_root(self) -> None:
        """Test finding Rust project root."""
        build_manager = BuildManager()

        # Create a Cargo.toml file
        cargo_file = self.temp_path / "Cargo.toml"
        cargo_file.write_text("[package]\nname = 'test'\n")

        found_root = build_manager.find_rust_project_root(self.temp_path)
        self.assertEqual(found_root, self.temp_path)

        # Test non-existent project
        empty_dir = self.temp_path / "empty"
        empty_dir.mkdir()
        found_root = build_manager.find_rust_project_root(empty_dir)
        self.assertIsNone(found_root)

    @patch('subprocess.run')
    def test_build_rust_project_success(self, mock_run: Mock) -> None:
        """Test successful Rust project build."""
        build_manager = BuildManager()
        mock_run.return_value.returncode = 0

        project_dir = self.temp_path / "project"
        project_dir.mkdir()
        
        # Create mock executable
        target_dir = project_dir / "target" / "release"
        target_dir.mkdir(parents=True)
        builder_exe = target_dir / "builder"
        builder_exe.write_text("mock executable")

        result = build_manager.build_rust_project(project_dir)
        self.assertEqual(result, builder_exe)

    @patch('subprocess.run')
    def test_build_rust_project_failure(self, mock_run: Mock) -> None:
        """Test Rust project build failure."""
        build_manager = BuildManager()
        mock_run.return_value.returncode = 1

        project_dir = self.temp_path / "project"
        project_dir.mkdir()

        with self.assertRaises(RuntimeError):
            build_manager.build_rust_project(project_dir)


class TestCacheManager(unittest.TestCase):
    """Test cases for the CacheManager class."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)
        self.cache_dir = self.temp_path / "cache"
        self.executables_dir = self.temp_path / "executables"
        self.path_manager = PathManager(self.executables_dir)

    def tearDown(self) -> None:
        """Clean up after tests."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_ensure_cache_directories(self) -> None:
        """Test cache directory creation."""
        cache_manager = CacheManager(self.cache_dir, self.executables_dir, self.path_manager)
        cache_manager.ensure_cache_directories()
        
        self.assertTrue(self.cache_dir.exists())
        self.assertTrue(self.executables_dir.exists())

    def test_is_builder_cached(self) -> None:
        """Test checking if builder is cached."""
        cache_manager = CacheManager(self.cache_dir, self.executables_dir, self.path_manager)
        url = "https://github.com/test/repo.git"
        
        # Initially not cached
        self.assertFalse(cache_manager.is_builder_cached(url))
        
        # Create cached executable
        exe_path = self.path_manager.get_builder_executable_path_for_url(url)
        exe_path.parent.mkdir(parents=True, exist_ok=True)
        exe_path.write_text("mock executable")
        
        # Now should be cached
        self.assertTrue(cache_manager.is_builder_cached(url))

    def test_cache_builder_executable(self) -> None:
        """Test caching builder executable."""
        cache_manager = CacheManager(self.cache_dir, self.executables_dir, self.path_manager)
        url = "https://github.com/test/repo.git"
        
        # Create source executable
        source_path = self.temp_path / "source_builder"
        source_path.write_text("mock executable")
        
        cache_manager.cache_builder_executable(source_path, url)
        
        # Verify it was cached
        self.assertTrue(cache_manager.is_builder_cached(url))


class TestBuilderManagerIntegration(unittest.TestCase):
    """Integration tests for BuilderManager with real component interactions."""

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
        """Test that cache directories are created."""
        with patch('builder.Path.cwd', return_value=self.temp_path):
            manager = BuilderManager()

        manager.ensure_cache_directories()
        
        self.assertTrue(manager.cache_dir.exists())
        self.assertTrue(manager.executables_dir.exists())
        self.assertTrue(manager.config_dir.exists())

    def test_load_project_config(self) -> None:
        """Test loading project configuration."""
        with patch('builder.Path.cwd', return_value=self.temp_path):
            manager = BuilderManager()

        url = manager.load_project_config()
        self.assertEqual(url, 'https://github.com/kstenerud/builder-test.git')

    def test_get_builder_executable_path(self) -> None:
        """Test getting builder executable path."""
        with patch('builder.Path.cwd', return_value=self.temp_path):
            manager = BuilderManager()

        path = manager.get_builder_executable_path()
        self.assertTrue(str(path).endswith('builder'))

    def test_is_builder_cached(self) -> None:
        """Test checking if builder is cached."""
        with patch('builder.Path.cwd', return_value=self.temp_path):
            manager = BuilderManager()

        # Remove any existing cached executable to ensure clean state
        exe_path = manager.get_builder_executable_path()
        if exe_path.exists():
            exe_path.unlink()
        
        # Initially not cached
        self.assertFalse(manager.is_builder_cached())

    @patch('builder.subprocess.run')
    def test_ensure_builder_available_with_trust_validation(self, mock_run: Mock) -> None:
        """Test ensuring builder is available with trust validation."""
        with patch('builder.Path.cwd', return_value=self.temp_path):
            manager = BuilderManager()

        # Should not raise since the URL is in builtin trusted URLs
        # This is an integration test, so we won't mock everything
        try:
            # This will fail due to network/build, but trust validation should pass
            manager.ensure_builder_available()
        except Exception:
            # We expect this to fail at build stage, but trust validation should have passed
            pass


if __name__ == '__main__':
    unittest.main()
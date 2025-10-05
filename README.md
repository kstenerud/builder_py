# Builder.py

A Python script that manages and forwards commands to builder executables. This script automatically downloads, builds, caches, and executes builder programs based on project configuration.

## Features

- **Global Cache Management**: Maintains a global cache for multiple versions of builder programs in `~/.cache/builder/`
- **Automatic Download & Build**: Downloads Rust projects from URLs, builds them, and caches the resulting executables
- **Command Forwarding**: Transparently forwards all command-line arguments to the cached builder executable
- **Project Configuration**: Uses YAML configuration files to specify builder sources

## Quick Start

1. **No dependencies needed** - Uses only Python standard library

2. **Make the script executable**:
   ```bash
   chmod +x builder.py
   ```

3. **Run the script** (it will automatically download and build the builder):
   ```bash
   ./builder.py --version
   ```

## Project Structure

```
builder_py/
├── builder.py          # Main script
├── builder.yaml        # Project configuration
├── requirements.txt    # Python dependencies
├── setup.py           # Setup script
├── test_builder.py    # Unit tests
├── demo.py            # Demonstration script
├── Makefile           # Common tasks
└── README.md          # This file
```

## Configuration

The project configuration is stored in `builder.yaml` at the project root:

```yaml
# Builder configuration file
builder_binary: "https://github.com/kstenerud/builder-test/archive/refs/tags/1.0.2.zip"
```

### Configuration Options

- `builder_binary`: URL pointing to an archive (`.zip`, `.tar.gz`, or `.tgz`) containing a Rust project that builds a `builder` executable

## Supported Archive Formats

The script supports downloading and extracting the following archive formats:

- **ZIP files** (`.zip`): Standard ZIP archives
- **Gzipped tar files** (`.tar.gz`): Compressed tar archives
- **Gzipped tar files** (`.tgz`): Compressed tar archives (alternative extension)

Example URLs:
```yaml
# ZIP archive
builder_binary: "https://example.com/project.zip"

# Tar.gz archive
builder_binary: "https://example.com/project.tar.gz"

# Tgz archive
builder_binary: "https://example.com/project.tgz"
```

## Cache Structure

The global cache is organized as follows:

```
~/.cache/builder/
└── executables/
    └── xyz/              # Unique directory (will be configurable later)
        └── builder       # Cached executable
```

## Usage

The script forwards all command-line arguments to the builder executable:

```bash
# Check version
./builder.py --version

# Pass any arguments
./builder.py arg1 arg2 arg3

# The script will automatically:
# 1. Check if builder is cached
# 2. Download and build if needed
# 3. Execute with your arguments
```

## Development

### Using the Makefile

The project includes a Makefile for common tasks:

```bash
# See all available targets
make help

# Install dependencies and run tests
make all

# Run only tests
make test

# Run demonstration
make demo

# Clean cache and temporary files
make clean

# Test with different builder versions
make test-v1.0.0
make test-v1.0.1
make test-v1.0.2
```

### Running Tests

```bash
python -m unittest test_builder.py -v
```

Or using make:

```bash
make test
```

### Setup Script

Use the setup script to install dependencies and run tests:

```bash
python setup.py
```

### Type Checking

The code uses type hints and can be checked with mypy:

```bash
pip install mypy
mypy builder.py
```

## Architecture

### BuilderManager Class

The main `BuilderManager` class handles:

- **Cache Management**: Creating and managing cache directories
- **Configuration Loading**: Reading `builder.yaml` files
- **Download & Extract**: Downloading zip files and extracting them
- **Rust Project Building**: Finding Cargo.toml files and running `cargo build`
- **Executable Caching**: Copying built executables to the cache
- **Command Execution**: Running cached executables with forwarded arguments

### Key Methods

- `ensure_builder_available()`: Main orchestration method
- `load_project_config()`: Loads project configuration
- `download_and_build_builder()`: Downloads and builds from source
- `run_builder()`: Executes the cached builder with arguments

## Test Data

The project is configured to use the test repository at:
https://github.com/kstenerud/builder-test

Available test versions:
- 1.0.0: `https://github.com/kstenerud/builder-test/archive/refs/tags/1.0.0.zip`
- 1.0.1: `https://github.com/kstenerud/builder-test/archive/refs/tags/1.0.1.zip`
- 1.0.2: `https://github.com/kstenerud/builder-test/archive/refs/tags/1.0.2.zip`

The test builder executable:
- Echoes back command-line arguments (one per line)
- Shows version information when called with `--version`
- Includes git commit, tag, and branch information if available

## Future Enhancements

- **Multiple Provenance Support**: The cache directory structure is designed to support multiple builder sources with unique directory names
- **Version Management**: Support for multiple versions of the same builder
- **Configuration Validation**: Enhanced validation of project configuration
- **Parallel Downloads**: Support for concurrent downloads and builds

## Requirements

- Python 3.7+
- Rust toolchain (cargo) for building downloaded projects

**No external Python dependencies required** - uses only the Python standard library.

## License

This project is provided as-is for development and testing purposes.
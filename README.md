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

- `builder_binary`: URL pointing to either:
  - An archive (`.zip`, `.tar.gz`, or `.tgz`) containing a Rust project that builds a `builder` executable
  - A Git repository (ending in `.git`) containing a Rust project that builds a `builder` executable

## Supported Source Formats

The script supports downloading from multiple source types:

### Archive Formats

- **ZIP files** (`.zip`): Standard ZIP archives
- **Gzipped tar files** (`.tar.gz`): Compressed tar archives
- **Gzipped tar files** (`.tgz`): Compressed tar archives (alternative extension)

### Git Repositories

- **Git URLs** (ending in `.git`): Clone Git repositories directly
- **Git URLs with references** (`.git#<reference>`): Clone and checkout specific branches, tags, or commits

Example URLs:

```yaml
# Archive formats
builder_binary: "https://example.com/project.zip"
builder_binary: "https://example.com/project.tar.gz"
builder_binary: "https://example.com/project.tgz"

# Git repositories
builder_binary: "https://github.com/user/project.git"
builder_binary: "https://github.com/user/project.git#main"
builder_binary: "https://github.com/user/project.git#v1.0.0"
builder_binary: "https://github.com/user/project.git#abc123def"
```

### Git Reference Behavior

- **With reference** (`#branch`, `#tag`, or `#commit`): Checkout the specified reference
- **Without reference**: Attempt to checkout `main` branch, fallback to `master` if `main` doesn't exist
- **Error handling**: Fail if neither `main` nor `master` branches exist when no reference is specified

The Git clone operation uses optimized flags for minimal bandwidth:
- `--filter=blob:none`: Skip downloading file contents initially
- `--no-checkout`: Don't checkout files during clone
- `--single-branch`: Only clone the default branch initially

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

# Clean up old cache entries (older than 30 days)
./builder.py --cache-prune-older-than 30d

# The script will automatically:
# 1. Check if builder is cached
# 2. Download and build if needed
# 3. Execute with your arguments
```

## Cache Management

### Cache Pruning

You can clean up old cached builders using the `--cache-prune-older-than` flag:

```bash
# Remove cache entries older than 5 minutes
./builder.py --cache-prune-older-than 5m

# Remove cache entries older than 2 hours
./builder.py --cache-prune-older-than 2h

# Remove cache entries older than 30 days
./builder.py --cache-prune-older-than 30d

# Remove cache entries older than 400 seconds
./builder.py --cache-prune-older-than 400s
```

**Time Format**: `<positive_integer><unit>` where unit is:
- `s` - seconds
- `m` - minutes
- `h` - hours
- `d` - days

The time units are case-insensitive (`5M` = `5m`).

**File Age Detection**: The script uses the following priority for determining file age:
1. Access time (when the cached binary was last used)
2. Modified time (when the file was last changed)
3. Created time (when the file was first created)

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

Available test versions (archives):

- 1.0.0: `https://github.com/kstenerud/builder-test/archive/refs/tags/1.0.0.zip`
- 1.0.1: `https://github.com/kstenerud/builder-test/archive/refs/tags/1.0.1.zip`
- 1.0.2: `https://github.com/kstenerud/builder-test/archive/refs/tags/1.0.2.zip`

Available test versions (Git):

- Latest: `https://github.com/kstenerud/builder-test.git`
- Specific tag: `https://github.com/kstenerud/builder-test.git#1.0.2`
- Specific branch: `https://github.com/kstenerud/builder-test.git#main`

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
- Git command-line tool (for Git repository support)

**No external Python dependencies required** - uses only the Python standard library.

## License

This project is provided as-is for development and testing purposes.
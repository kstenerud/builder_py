# Builder.py Project Guide for AI Agents

## Project Overview

This is a Python-based builder wrapper script that automatically downloads, builds, and caches builder executables from various sources (Git repositories, archives, local files). The system acts as a transparent proxy that forwards commands to the appropriate builder executable while managing the underlying complexity of source fetching, building, and caching.

The underlying reason for this wrapper is so that a project can control via `builder.yaml` the exact version of the builder that gets used to build the project. This allows for reproducible builds. The wrapper doesn't concern itself with the actual building; only ensuring the correct version of builder is called.

The intended use is for a copy of `builder.py` to be checked in at the root of a project, along with a `builder.yaml` configuration file that will contain the specific build instructions.

## Critical Design Principles

### 🔒 **API Stability Contract**
- **ONLY the CLI interface is user-facing and must maintain backwards compatibility**
- **ALL internal Python APIs can change freely without versioning concerns**
- The entire internal class structure, method signatures, and implementation details are implementation details
- Users interact exclusively through command-line arguments

### 📖 **Code Quality Guidelines**
- **Readability > Performance**: This is not on the hot path, so prioritize clear, maintainable code
- **Single Responsibility Principle**: Each class has one clear purpose
- **Clear Separation of Concerns**: Avoid tight coupling between components
- **DRY, but not at readability's expense**: Don't abstract just to reduce lines of code
- **Documentation must stay in sync**: Comments and docstrings should reflect actual behavior

### 🏗️ **Architectural Principles**
- **Dependency Injection**: Components receive their dependencies rather than creating them
- **Composition over Inheritance**: Classes collaborate through composition
- **Fail Fast**: Validate inputs early and provide clear error messages
- **Idempotent Operations**: Repeated operations should be safe (e.g., caching, directory creation)

## Architecture Overview

### Core Components

```
BuilderRunner (Orchestrator)
├── ProjectConfiguration (Config parsing)
├── PathBuilder (Path management)
├── TrustManager (Security validation)
├── CacheManager (Cache operations)
├── SourceFetcher (Source retrieval)
├── BuilderBuilder (Rust compilation)
└── CommandProcessor (CLI command handling)
```

### Class Responsibilities

#### **BuilderRunner** - Main Orchestrator
- Coordinates all components to fulfill user requests
- Ensures builder availability through `_ensure_builder_available()`
- Executes builder with `run()`
- **Key Insight**: This is the only class that orchestrates the full workflow

#### **ProjectConfiguration** - Configuration Management
- Parses `builder.yaml` files using regex patterns
- Extracts `builder_binary` URL from YAML content
- **Key Insight**: Uses regex rather than full YAML parser for simplicity and fewer dependencies

#### **PathBuilder** - Centralized Path Management
- All file/directory paths decisions go through this class
- Uses caret-encoding for URL-safe directory names
- Manages cache structure: `~/.cache/builder/executables/[encoded-url]/builder`
- **Key Insight**: Path construction logic is centralized to avoid hardcoded paths throughout codebase

#### **TrustManager** - Security Layer
- Prefix-based trust validation for URLs
- Built-in trusted URL prefixes + user-configurable trust list
- Trust validation happens before any downloads for maximum security
- **Key Insight**: Security validation occurs at the earliest possible point in the workflow

#### **CacheManager** - Cache Operations
- Checks cache validity with `is_builder_cached()`
- Idempotent caching with `cache_builder()`
- Age-based cache pruning (using `<= cutoff_time` for inclusive age comparison)
- Can prune the cache of a specific URL
- **Key Insight**: All cache operations are idempotent and safe to repeat

#### **SourceFetcher** - Source Code Retrieval
- **Public API**: Only `clone_source()` - the unified entry point
- **Private Methods**: All implementation details (Git cloning, archive extraction, file copying)
- Supports: Git repos (with optional references), archives (.zip, .tar.gz, .tgz), local files/directories
- **Key Insight**: Single public method hides complexity while supporting multiple source types

#### **BuilderBuilder** - Rust Project Compilation
- Builds the `builder` binary
- Finds Rust project root by locating `Cargo.toml`
- Builds in release mode with `cargo build --release`
- **Key Insight**: Currently Rust-specific but designed to be extensible

#### **CommandProcessor** - CLI Command Handling
- Processes special commands (trust management, cache operations, help)
- Dispatches commands using strategy pattern
- **Key Insight**: Isolates CLI parsing logic from business logic

## Implementation Details

### Security Model
- **Trust-first approach**: URLs must be trusted before any network operations
- **Prefix-based trust**: Trust applies to URL prefixes, providing granular control
- **Built-in trusted prefixes**: Default safe sources are included
- **User extensible**: Users can add/remove trusted URL prefixes via CLI

### Caching Strategy
- **URL-based keying**: Each unique source URL gets its own cache entry
- **Caret encoding**: URLs are safely encoded for filesystem use
- **Age-based pruning**: Inclusive age comparison (`<= cutoff_time`)
- **Idempotent operations**: Multiple cache operations are safe

### Error Handling
- **Fail fast**: Validate early, fail with clear messages
- **Graceful degradation**: Continue operation when possible (e.g., cache age check failures)
- **User-friendly errors**: CLI errors include suggested solutions

### File Structure
```
~/.cache/builder/
├── executables/
│   └── [caret-encoded-url]/
│       └── builder (executable)
└── ...

~/.config/builder/
└── trusted_urls (user-added trusted URLs)
```

## Testing Architecture

### Test Philosophy
- **Test through public interfaces**: Tests primarily use public APIs, not internal methods
- **Behavior-focused**: Tests validate end-to-end behavior rather than implementation details
- **Comprehensive coverage**: 41 tests covering all major functionality
- **Fast execution**: Test suite runs in ~0.05-0.07 seconds

### Test Structure
- Each class has dedicated test suite
- Integration tests validate component interaction
- Tests are isolated using temporary directories
- Mocking used for external dependencies (subprocess calls, file operations)

## CLI Interface (User-Facing Contract)

### Core Commands
```bash
./builder.py [args...]              # Forward to builder executable
./builder.py --cache-help           # Show cache management help
./builder.py --cache-prune-older-than <time>  # Remove old cache entries
./builder.py --cache-prune-builder [url]      # Remove specific cache entry
./builder.py --trust-yes <url>      # Add trusted URL
./builder.py --trust-no <url>       # Remove trusted URL
./builder.py --trust-list           # List trusted URLs
```

### Time Specifications
- Format: `<positive_integer><unit>`
- Units: `s` (seconds), `m` (minutes), `h` (hours), `d` (days)
- Examples: `5m`, `2h`, `30d`

## Configuration File Format

### builder.yaml
```yaml
builder_binary: https://github.com/user/repo.git
# or
builder_binary: "https://github.com/user/repo.git#v1.0.0"
# or
builder_binary: /path/to/local/directory
```

## Development Guidelines

### When Adding Features
1. **Identify the right component**: Which class has the responsibility?
2. **Maintain encapsulation**: Keep internal methods private (prefixed with `_`)
3. **Update tests**: Add tests for new behavior through public interfaces
4. **Update documentation**: Keep docstrings and this file in sync
5. **Consider security**: Does this change affect trust validation?

### When Refactoring
1. **Tests must continue passing**: Behavior should remain unchanged
2. **Maintain CLI compatibility**: Never break the user-facing interface
3. **Update CLAUDE.md**: Document new insights or architectural changes
4. **Check separation of concerns**: Does each class still have a single responsibility?

### Code Style
- Use type hints for all methods
- Document all public methods with docstrings
- Use meaningful variable names
- Prefer explicit over implicit
- Keep methods focused and short
- Put print calls for user-facing messages as close to the UI code as possible (in this case, that's usually in CommandProcessor)

## Common Pitfalls to Avoid

### ❌ **Breaking CLI Compatibility**
- Never change existing command syntax
- Never remove existing commands
- New commands should follow established patterns

### ❌ **Tight Coupling**
- Don't let classes directly instantiate their dependencies
- Avoid calling methods across multiple abstraction levels
- Don't hardcode paths outside PathBuilder

### ❌ **Security Bypasses**
- Always validate trust before network operations
- Don't allow trust validation to be skipped
- Trust validation should happen as early as possible

### ❌ **Cache Inconsistencies**
- Cache operations must be idempotent
- Cache keys must be deterministic
- Age comparisons should be inclusive (<=)

### ❌ **Outdated Documentation**
- Update docstrings when changing method behavior
- Update CLAUDE.md when gaining new architectural insights
- Keep test descriptions accurate

## Key Insights Gained

### **Private vs Public Method Design**
- Initially, many methods were public for granular testing
- **Insight**: Since only CLI is user-facing, internal methods should be private
- **Result**: Cleaner API surface, better encapsulation, tests through public interfaces

### **Cache Pruning Logic**
- Original implementation used `< cutoff_time` for age comparison
- **Insight**: Age comparisons should be inclusive (`<= cutoff_time`) for intuitive behavior
- **Result**: Age=0 properly clears entire cache, exact age matches are pruned

### **Trust Validation Security Model**

- Initially used domain-based trust validation (trust entire domains)
- **Insight**: Domain-based trust creates security vulnerabilities (trusting `github.com` trusts ALL GitHub repositories)
- **Result**: Prefix-based trust validation provides granular control (trust specific users, organizations, or repositories)

### **Security-First Architecture**
- Trust validation was initially scattered throughout the codebase
- **Insight**: Security validation should happen at the earliest possible point
- **Result**: All URLs are validated before any network operations

### **Separation of Concerns Evolution**
- Initially had some classes doing multiple responsibilities
- **Insight**: Each class should have exactly one reason to change
- **Result**: PathBuilder for all paths, TrustManager for all security, CacheManager for all caching

### **Documentation as Architecture Guide**
- Documentation often fell behind code changes
- **Insight**: Documentation drift creates maintenance burden and confusion
- **Result**: This CLAUDE.md file serves as authoritative architecture guide

## Future Considerations

### Potential Extensions
- `builder.py` is intended as a downloader, cacher, and wrapper around the actual builder `builder`, so its future ambitions will be small.
- Integration with other package managers

### Architecture Evolution
- Component interfaces are stable
- Internal implementations can evolve freely
- CLI contract must remain backwards compatible
- Consider dependency injection framework if complexity grows

---

*This document should be updated whenever significant architectural insights are gained or when the system design evolves.*

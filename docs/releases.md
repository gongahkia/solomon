# Release Policy

Shibahama uses Semantic Versioning.

- Increment `MAJOR` for incompatible public API, storage format, binding, or protocol changes
  after a stable release exists.
- Increment `MINOR` for backwards-compatible features.
- Increment `PATCH` for backwards-compatible bug fixes, documentation fixes, and maintenance.
- Before `1.0.0`, `MINOR` releases may still contain breaking changes, but the changelog must call
  them out explicitly.

Every release must update `CHANGELOG.md`, tag the repository as `vMAJOR.MINOR.PATCH`, and keep
Cargo, Python, and Node package versions aligned unless a package has not shipped yet.

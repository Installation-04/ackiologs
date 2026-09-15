"""Single source of truth for the running version. Stays "0.0.0-dev" for local/source
runs; the release workflow overwrites this file with the tag being released
(e.g. "1.2.3") before building the Linux/Windows/Docker artifacts, so all four
carry the same version and report it via GET /api/version."""

__version__ = "0.0.0-dev"

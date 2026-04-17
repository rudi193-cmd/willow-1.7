# Security Policy

## Supported Versions

Only the current `master` branch is supported. No backport patches are issued.

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Report privately via [GitHub Security Advisories](https://github.com/rudi193-cmd/willow-1.7/security/advisories/new).

Include:
- Description of the vulnerability and its impact
- Steps to reproduce
- Any suggested fix (optional)

You will receive an acknowledgment within 7 days. Patches are prioritized based on severity.

## Security Model

willow-1.7 is designed as a local-first, portless system. Key properties:

**No network surface.** The server communicates via stdio (MCP) and Unix socket (Postgres only). There are no HTTP listeners and no open ports.

**PGP-hardened gate (SAP v2).** Every application must present a signed SAFE manifest before accessing any tool. Signatures are verified against a pinned GPG fingerprint on every call. Revocation is instant — delete the folder or its signature file.

**Memory sanitization.** All memory read paths pass through `core/memory_sanitizer.py` before results reach an LLM. Twenty-four patterns across seven categories detect prompt injection attempts from user-written content.

**Kart sandbox.** The KART task worker executes shell commands inside a `bubblewrap` (bwrap) sandbox: no network, no PID namespace escape, read-only system binaries, tmpfs `/tmp`.

**Path traversal and symlink rejection.** All file-touching tools reject paths containing `..` and refuse to follow symlinks outside permitted roots.

Known limitations: the system is designed for single-user local deployment. Multi-user or networked deployments are out of scope and untested.

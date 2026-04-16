# Contributing to willow-1.7

willow-1.7 is a personal infrastructure project. It is open source so others can learn from it, adapt it, or build on it — not because it is seeking contributors in the traditional sense.

That said, if you find a bug, have a question, or want to propose something:

## Issues

Use GitHub Issues for bugs and questions. Be specific: what you expected, what happened, your OS and Python version.

## Discussions

Use GitHub Discussions for anything open-ended — architecture questions, use cases, ideas. The Discussions tab is the right place for "I'm trying to do X with willow, how would you approach it?"

## Pull Requests

PRs are welcome for:
- Bug fixes with a clear reproduction case
- Documentation corrections
- Portability improvements (tested on a different OS/distro)

PRs are not the right path for:
- New tools or features (open a Discussion first)
- Changes to the SAFE authorization model
- Persona or lore additions (those belong in application repos, not the server)

## Code style

- Python 3.10+
- No new dependencies without a strong reason
- No new HTTP listeners. Portless means portless.
- b17 tag on every new file before it is closed

## License

MIT. See [LICENSE](LICENSE).

# Security policy

## Supported versions

Until the first stable release, only the latest version on the default branch
receives security fixes.

## Reporting a vulnerability

Please do not open a public issue for a vulnerability. Use GitHub's private
security-advisory reporting feature for the repository. Include affected
versions, reproduction steps, impact, and any suggested mitigation.

The project parses local JSON and image files and can write generated artifacts.
Treat untrusted inputs cautiously, use the documented execution limits, and
review output paths before enabling overwrite behavior.

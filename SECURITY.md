# Security Policy

## Reporting a vulnerability

Please **do not** open a public issue for a security problem.

Report it privately through GitHub's [Security Advisories](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
page for this repository ("Security" tab → "Report a vulnerability"). That channel
is private and reaches the maintainers directly.

If advisories are unavailable to you, open a regular issue that says only that you
have a security report and how to reach you — no details, no proof of concept.

Useful in a report:

- RunDeps version (`rundeps --version`) and `rundeps doctor` output
- platform and Python version
- what an attacker could do, and what they need to be able to do it
- a minimal reproduction, if you have one

We will acknowledge the report and tell you whether it is in scope. Please give us
a reasonable window to fix the issue before public disclosure.

## Scope

RunDeps runs `pip install`, so the security of the packages you install is
ultimately the packages' own business. In scope for this project:

- A package being installed without the user's confirmation
- A low-confidence or unresolvable import being installed automatically
- Installing into the global interpreter when isolation was requested
- Package names or arguments reaching pip that could be interpreted as options,
  URLs or paths (argument injection)
- Command injection through crafted file names, config values or console output
- Reading, logging or transmitting credentials, tokens or environment variables
- Writing to the target script or to files outside the project directory
- Executing target code during a scan that is documented as read-only

## Out of scope

- A malicious package doing malicious things after you approved its installation
- Compromise of PyPI, a package index, pip itself, or a transitive dependency
- Missing vulnerability scanning, code signing or provenance checks — RunDeps does
  not claim to provide these
- Static analysis missing a dynamic import; that is a documented limitation, and
  the runtime fallback is best-effort

## What RunDeps does not protect you from

RunDeps decides *what* to install and *where*. It does not audit *what the package
does*. Installing from an unknown index or approving an unfamiliar package is the
same risk as running `pip install` yourself.

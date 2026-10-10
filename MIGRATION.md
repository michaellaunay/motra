# Migration to the Python 3.14 fork line

This is an unreleased documentation draft, not a publication or version decision.
The existing distribution name `motra` and version `0.2.0.dev0`
remain unchanged. A PyPI fork name and release/prerelease version require a separate
human decision; no ownership of upstream names is implied.

CPython 3.12, 3.13 and 3.14 standard with GIL are qualified on Linux x86_64.
Python <3.12 is outside this line. Windows, macOS, other architectures, PyPy and
free-threaded Python are NOT_RUN. Metadata >=3.12 is not a promise about future
Python versions.

Caches no longer survive separate run() calls, including clean_mappings_cache=False. Applications requiring cross-run reuse must manage it explicitly. Recheck chains and M2T, not only M2M.

Use local, provenance-checked ecosystem wheels together. The accepted T12 closure
passes 911 tests per environment for both supported-minimum and recent profiles,
each on 3.12/3.13/3.14 source and wheel. The supported closure uses setuptools
83.0.0, pytest 9.0.3, lxml 6.1.0, Jinja2 3.1.6, ordered-set 4.0.1, autopep8 2.0.0
and build 1.0.0; exact transitives are in the qualification locks. Historical
setuptools 77.0.1/pytest 8.0.0 compatibility results are not supported minimums.
Audits on 2026-10-09 reported no known advisories for the two supported profiles;
this is dated evidence, not a security guarantee.

For rollback, create a separate checkout at known qualified commit
`f3c9a251cd9e574201f8900cadd492bc9ffdd136` and reinstall the matching complete
closure from its hashed locks in a fresh environment. Do not mix isolated old
components with new ones or overwrite a dirty checkout. Back up models and
application-generated code before migration. The original upstream baseline
`c0b3e8e54b46572c3bc10bb2b719102e267c371b` is historical, not qualified for Python
3.14 and not a safe default rollback environment.

Keep `LICENSE` and existing author/copyright notices with redistributed code.
The ecosystem delivery guide lives in the separate pyecore-codex-harness pilot
repository (`docs/MIGRATION_GUIDE.md`, `docs/PYTHON_SUPPORT.md`,
`docs/RELEASE_PLAN.md`). Documentation drafts are separate from the frozen T12
artifacts until reviewed and committed.

## Unreleased — Python 3.14 migration (release decision pending)

- CPython >=3.12 metadata; qualified 3.12/3.13/3.14 standard with GIL on Linux x86_64 only.
- Build backend setuptools >=83.0.0 and test extra pytest >=9.0.3. Project/module names, nsURI, licenses and author credits are retained.
- M2M, M2T and chain execution contexts are isolated and restored after nesting or exceptions.
- Execution caches are bounded to a single run and preserve object identity; deferred annotations are qualified.
- Checked-in metamodel resources ship in installed distributions.

Caches no longer survive separate run() calls, including clean_mappings_cache=False. Applications requiring cross-run reuse must manage it explicitly. Recheck chains and M2T, not only M2M.

# CHANGELOG

## 0.1.0

* Add first implementation of Motra M2T including:
  * `@template`, `@main`, `@helper`
  * polymorphic calls
  * cached results
* Introduce more flexible polymorphic calls for M2M.
* Add new examples.

## 0.0.4

* Fix issue with result being automatically moved to resource root.

## 0.0.1

* Initial version with Motra M2M including:
  * `@mapping`, `@main`, `@disjunct`
  * polymorphic calls
  * cached results

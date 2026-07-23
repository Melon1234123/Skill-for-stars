# Pure Python Task 2 report

## Official HYG v4.1 verification

- Official project page observed: `https://www.astronexus.com/projects/hyg`.
  It states that HYG is hosted at `https://codeberg.org/astronexus` and that
  its hosted version is the most recent version saved there.
- Official source repository cloned outside the repository:
  `https://codeberg.org/astronexus/hyg.git` to
  `/tmp/hyg-official-source-20260723`.
- Its `data/hyg/version-info.md` history includes
  `b457d51b235aae40fb3ac9fa6ad7554d237c406d` at
  `2025-06-29T12:52:06-07:00`, with subject
  `v4.1 -> v4.2: 34 new proper names from the IAU in the last 14 months`.
  The source README states that versions since v4.0 use CC BY-SA 4.0.
- Downloaded official asset outside the repository:
  `https://www.astronexus.com/downloads/catalogs/hygdata_v41.csv.gz` to
  `/tmp/astronexus-v41.tmp`.
- Observed response: `Content-Length: 13636476`,
  `Last-Modified: Fri, 13 Dec 2024 04:58:39 GMT`, no ETag supplied.
- `shasum -a 256 /tmp/astronexus-v41.tmp`:
  `7c88281796e46774d8bc8e416f23466a019063216b073159fb08998dd4b636a4`.
- The complete evidence table and commands are in
  `docs/sources/hyg-v4.1.md`.

## TDD evidence

### RED

Command:

```text
.venv/bin/python -m pytest tests/test_sky_chart_catalog.py -q
```

Before implementation, collection failed as expected with:

```text
ModuleNotFoundError: No module named 'starskill.sky_chart_catalog'
```

### GREEN

The loader now reads only package resources, verifies the canonical JSON
record-array SHA-256 values, rejects duplicate star IDs and unknown segment
endpoints, and checks that both JSON envelopes match the fixed HYG source URL
and license.

Command:

```text
.venv/bin/python -m pytest tests/test_sky_chart_catalog.py -q
```

Result:

```text
...                                                                      [100%]
```

Canonical record verification also reported:

```text
bright_stars.json 100 True 9575f2f43cd996402e9ecaa182099cd81d0036a3126b096e8257b12f0cb8ffa9
constellation_segments.json 23 True a518862c8a364220b4c043dccd0430fe9c5c09cb5f5501741373be29566fa2fb
```

Full offline suite:

```text
.venv/bin/python -m pytest
234 passed, 1 warning in 8.06s
```

## Wheel validation

The `build` module is not installed in `.venv`, so the required no-install
fallback was attempted:

```text
.venv/bin/python -m pip wheel --no-build-isolation --no-deps . -w <temporary-directory>
```

It did not produce a wheel because the existing virtual environment lacks
`setuptools` and therefore cannot import `setuptools.build_meta`:

```text
pip._vendor.pyproject_hooks._impl.BackendUnavailable: Cannot import 'setuptools.build_meta'
```

No dependency was installed and no handcrafted wheel was substituted. Searches
found no compatible existing Python 3.11+ setuptools installation or cached
wheel. Consequently, archive-content assertions could not be executed in this
environment; the source-package resource assertion passed in the catalog test.

# HYG v4.1 source verification

The official HYG page identifies Codeberg as the current source host. Its
direct v4.1 asset was fetched into `/tmp/astronexus-v41.tmp`, outside this
repository. For the historical v4.1 release date, the former official HYG
repository at `https://github.com/astronexus/HYG-Database` is the applicable
upstream: its README states that future updates moved to Codeberg. Its commit
`5283c6086806d0cdb19cf0d91d84102d8ec3289b` explicitly says `Add v4.1 of HYG`
and has the observed commit timestamp below. This is the v4.1 release evidence;
the later v4.1-to-v4.2 transition is not used to date v4.1. The Codeberg README
says versions since v4.0 are CC BY-SA 4.0.

| Field | Observed value |
| --- | --- |
| Official release page | `https://www.astronexus.com/projects/hyg` |
| Release tag | `4.1` |
| Release date | `2024-01-20T09:49:29-08:00` |
| Asset URL | `https://www.astronexus.com/downloads/catalogs/hygdata_v41.csv.gz` |
| Asset filename | `hygdata_v41.csv.gz` |
| License | `CC BY-SA 4.0; https://creativecommons.org/licenses/by-sa/4.0/deed.en` |
| Downloaded bytes | `13636476` |
| Compressed SHA-256 | `7c88281796e46774d8bc8e416f23466a019063216b073159fb08998dd4b636a4` |
| ETag / Last-Modified | `ETag not supplied; Last-Modified: Fri, 13 Dec 2024 04:58:39 GMT` |
| Verified at UTC | `2026-07-23T13:08:00Z` |

Observed commands: `curl -fsSL -D /tmp/astronexus-v41.headers -o
/tmp/astronexus-v41.tmp https://www.astronexus.com/downloads/catalogs/hygdata_v41.csv.gz`,
`wc -c /tmp/astronexus-v41.tmp`, `shasum -a 256 /tmp/astronexus-v41.tmp`, and
`git -C /tmp/hyg-github-official-20260723 show --format=fuller --no-patch
5283c6086806d0cdb19cf0d91d84102d8ec3289b`.

## Raw official release-history evidence

The historical official GitHub repository was cloned outside the project with
`git clone --filter=blob:none --no-checkout
https://github.com/astronexus/HYG-Database.git
/tmp/hyg-github-official-20260723`. The release commit was observed with the
command above:

```text
commit 5283c6086806d0cdb19cf0d91d84102d8ec3289b
Author:     David Nash <Dpnash1@gmail.com>
AuthorDate: Sat Jan 20 09:49:29 2024 -0800
Commit:     David Nash <Dpnash1@gmail.com>
CommitDate: Sat Jan 20 09:49:29 2024 -0800

    Add v4.1 of HYG (see README for verson details)
```

## Raw asset response headers

`curl -fsSI https://www.astronexus.com/downloads/catalogs/hygdata_v41.csv.gz`
observed the following response on 2026-07-23:

```text
HTTP/1.1 200 OK
Date: Thu, 23 Jul 2026 13:08:01 GMT
Server: Apache
Last-Modified: Fri, 13 Dec 2024 04:58:39 GMT
Accept-Ranges: bytes
Content-Length: 13636476
Content-Type: application/x-gzip
```

## Reproducible packaged-record verification

This command downloads the official asset to a fresh directory under `/tmp`,
then uses only the Python standard library to reproduce the packaged selection:
unique HR records sorted by HYG magnitude, with magnitude at most 3.0. It
compares every shipped field. `name` is HYG's exact nonempty `proper` value,
or, when `proper` is empty, its exact `bf` (Bayer/Flamsteed) value. This is a
source-column fallback, not a display-name normalizer. It does not write the
downloaded asset into this repository.

```sh
asset_dir=$(mktemp -d /tmp/starskill-hyg-v41.XXXXXX)
asset_path="$asset_dir/hygdata_v41.csv.gz"
curl -fsSL https://www.astronexus.com/downloads/catalogs/hygdata_v41.csv.gz -o "$asset_path"
HYG_GZIP="$asset_path" .venv/bin/python - <<'PY'
import csv
import gzip
import json
import os
from pathlib import Path

source_path = Path(os.environ["HYG_GZIP"])
packaged = json.loads(Path("src/starskill/data/bright_stars.json").read_text(encoding="utf-8"))["records"]
seen: set[str] = set()
expected: list[dict[str, object]] = []
with gzip.open(source_path, "rt", newline="") as source:
    rows = list(csv.DictReader(source))
for row in sorted(rows, key=lambda item: float(item["mag"])):
    if not row["hr"] or float(row["mag"]) > 3.0:
        continue
    star_id = f"hr-{int(row['hr'])}"
    if star_id in seen:
        continue
    seen.add(star_id)
    expected.append(
        {
            "star_id": star_id,
            "name": row["proper"] or row["bf"],
            "ra_deg": round(float(row["ra"]) * 15, 6),
            "dec_deg": round(float(row["dec"]), 6),
            "magnitude": float(row["mag"]),
        }
    )
    if len(expected) == 100:
        break
actual = [
    {
        key: star[key]
        for key in ("star_id", "name", "ra_deg", "dec_deg", "magnitude")
    }
    for star in packaged
]
assert expected == actual, "packaged records differ from official HYG v4.1 selection"
print(f"verified {len(actual)} packaged HYG v4.1 records")
PY
```

Executed successfully on 2026-07-23, printing:

```text
verified 100 packaged HYG v4.1 records
```

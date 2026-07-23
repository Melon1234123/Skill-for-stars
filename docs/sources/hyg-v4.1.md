# HYG v4.1 source verification

The official HYG page identifies Codeberg as the source host. Its direct v4.1
asset was fetched into `/tmp/astronexus-v41.tmp`, outside this repository. The
official Codeberg history records HYG v4.1 under the release transition commit
`b457d51b235aae40fb3ac9fa6ad7554d237c406d` (`v4.1 -> v4.2: 34 new proper
names from the IAU in the last 14 months`, dated `2025-06-29T12:52:06-07:00`).
The official page states that HYG is hosted at Codeberg and that its hosted copy
is the most recent saved there. The Codeberg README says versions since v4.0
are CC BY-SA 4.0.

| Field | Observed value |
| --- | --- |
| Official release page | `https://www.astronexus.com/projects/hyg` |
| Release tag | `4.1` |
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
`git -C /tmp/hyg-official-source-20260723 log --all --format='%H %ad %s'
--date=iso-strict -- data/hyg/version-info.md`.

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
compares every packaged `star_id`, right ascension, declination, and magnitude.
It does not write the downloaded asset into this repository.

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
            "ra_deg": round(float(row["ra"]) * 15, 6),
            "dec_deg": round(float(row["dec"]), 6),
            "magnitude": float(row["mag"]),
        }
    )
    if len(expected) == 100:
        break
actual = [
    {key: star[key] for key in ("star_id", "ra_deg", "dec_deg", "magnitude")}
    for star in packaged
]
assert expected == actual, "packaged records differ from official HYG v4.1 selection"
print(f"verified {len(actual)} packaged HYG v4.1 records")
PY
```

Executed successfully on 2026-07-23, printing:

```text
verified 100 packaged HYG v4.1 records against /tmp/starskill-hyg-v41.i4deg5/hygdata_v41.csv.gz
```

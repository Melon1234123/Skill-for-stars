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
| Verified at UTC | `2026-07-23T12:57:19Z` |

Observed commands: `curl -fsSL -D /tmp/astronexus-v41.headers -o
/tmp/astronexus-v41.tmp https://www.astronexus.com/downloads/catalogs/hygdata_v41.csv.gz`,
`wc -c /tmp/astronexus-v41.tmp`, `shasum -a 256 /tmp/astronexus-v41.tmp`, and
`git -C /tmp/hyg-official-source-20260723 log --all --format='%H %ad %s'
--date=iso-strict -- data/hyg/version-info.md`.

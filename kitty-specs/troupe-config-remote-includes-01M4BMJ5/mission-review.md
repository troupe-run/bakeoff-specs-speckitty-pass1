# Post-merge mission review: troupe-config-remote-includes-01M4BMJ5

**Verdict: PASS WITH NOTES** (reviewer-renata, 2026-10-08, on `feat/troupe-config-remote-includes` at `eb4bc81`)

## Coverage

- All of FR-001–FR-012, NFR-001–NFR-005, C-001–C-006 and S-1–S-13 are implemented in live code paths. Each has at least one real-CLI, real-HTTP test that fails if it breaks.
- Every new module has live callers. The include-prefix logic now lives only in `troupe.includes`.
- Network access is confined to `troupe.remote`.

## Findings and dispositions

| ID | Severity | Finding | Disposition |
|---|---|---|---|
| D-1 | Low | The first schema violation is ordered by key name, not position in the file; research R-6 said "document order". | Research R-6 wording corrected; the spec does not fix an order. |
| D-2 | Low | A `file:` reference in remote content that resolves outside http(s) gives a message naming the URL but not the configuration path. | Bead filed. |
| D-3 | Low | Spec S-2/FR-003 said "the local file"; the contract and code name the including location, which is a URL for nested remote includes. | Spec aligned with the contract. |
| D-4 | Low | The acceptance matrix uses placeholder descriptions, and NFR/C/S rows are missing. | Accepted as tool scaffolding; the evidence column carries the proof. |
| R-a | Low | An https → http redirect is followed. | Added to bead 1j5.4 (http in clear text). |
| R-b | Low | While a remote include keeps failing, each `watch` retry can hold the theatre lock for up to 10 s. | Bead filed. |
| R-c | Low | `file://host/x` in remote content resolves to another host (standard URL rules). | Documented in spec S-1. |

Open follow-ups, all children of `bakeoff-specs-speckitty-1j5`:
- `1j5.1`: IPv6 socket creation.
- `1j5.2`: refusal ordering for `--include` on a uri path in remote content.
- `1j5.3`: body size limit (product decision).
- `1j5.4`: http in clear text, including the https → http redirect (product decision).
- `1j5.5` (D-2) and `1j5.6` (R-b).

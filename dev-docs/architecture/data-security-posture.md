# Data Security Posture — Why the Cloud-DB Threat Model Doesn't Apply

**Status:** living
**Owner:** @systems_lead
**Companion:** [system-architecture-contracts.md](system-architecture-contracts.md)
(module boundaries), [ci-policy.md](ci-policy.md) (offline-at-runtime enforcement).

## Why this doc exists

A recurring warning in the "vibecoding" community — building apps with AI
tools like Cursor / Lovable / Bolt / Claude Code — is that a **private repo is
not a private app**. The canonical failure: a Supabase (or Firebase) project
ships its anon key inside the client bundle, so anyone can open dev tools, grab
the key, and query the tables directly. The only guard is Row-Level Security
(RLS), which AI scaffolds skip constantly — or "enable" with a `USING (true)`
policy that shows green in the dashboard while protecting nothing.

That is a real and common disaster. This doc records **why it is structurally
impossible in PHOTONForge**, so the question doesn't have to be re-litigated
every time someone new sees the warning — and, more usefully, what our data
layer *should* actually worry about instead.

## The finding: cloud-exposure risks cannot reach us

The vibecoding disaster is a **cloud / multi-tenant / web** failure. PHOTONForge
is a **local, single-user, offline** system (NFR-2.1: 100% offline at runtime;
NFR-2.3: the DB lives on the external SSD, not a server). Point by point:

| The cloud-DB warning | PHOTONForge reality |
|---|---|
| "Your anon key ships inside the app" | No Supabase / Postgres / Firebase anywhere in the runtime package. No key to leak. |
| "Anyone can query your tables from dev tools" | There is **no front door**: no web app, no HTTP server (no flask/fastapi/django), no listening socket. Nothing serves the DB. |
| "The database answers the network" | `photonforge.db` / `library.db` is a **local SQLite file on the SSD**, reached only via in-process `sqlite3` calls in `src/photo_workflow/photondb.py`. |
| "RLS is the only thing protecting rows" | RLS is a Postgres multi-tenant concept. Single-user + offline → no tenant boundary and no remote "stranger" to scope against. |
| "Make two accounts, read A's row as B" | No accounts, no auth layer, no remote reader. The test has no meaning here. |

The only `http` strings in `src/photo_workflow/` are XML namespace URIs in XMP
sidecar generation (`src/photo_workflow/darktable_bridge.py`) — declarations,
not network calls.

### The one adjacent risk, and its status

The genuine local analog of "the AI skipped the safety" is **SQL injection via
string-built queries**. Status: **clean**. Every query in
`src/photo_workflow/photondb.py` is parameterized with `?` placeholders and a
bound-value tuple (e.g. `WHERE folder=? AND filename=?`). User-influenced values
(filenames, folders, EXIF-derived text) are always bound, never interpolated.
The folder key additionally passes through `sanitize_table_name()`
(regex-normalized to `[A-Za-z0-9_]`) and is stored as a **column value**, not a
table name — so even dynamic-identifier injection has no live vector. No f-string
or `%`-formatted SQL exists in the data layer.

## What our data layer actually must protect

Our real risks are **integrity and durability of a file on removable media**,
not confidentiality:

| Risk | Threat model | Where it's handled |
|---|---|---|
| **Corruption on unsafe SSD removal mid-write** | The headline threat: yanking the cartridge during a DB write. | **KPM-1.4** (zero corruption / 50 safe-eject cycles), `scripts/safe_eject.sh`, `scripts/soak_cycle.py`, cartridge lifecycle in `src/photo_workflow/cartridge.py` / `src/photo_workflow/volume.py`. |
| **Journal mode tradeoff** | `PRAGMA journal_mode=DELETE` (`src/photo_workflow/photondb.py`), not WAL — deliberate for removable media (WAL's `-wal`/`-shm` sidecars complicate clean ejection). A durability choice, not a hole; revisit only under real write contention. | schema note in `requirements/interfaces/IF-4.1.md`. |
| **No backup of the catalog** | If the SSD dies, `photonforge.db` is gone. A disaster-recovery gap, not an exposure one. | **Open** — no automated backup today. |
| **Physical access to the SSD** | Anyone holding the cartridge can read it (it's an unencrypted SQLite file). | Accepted: this is a single-user personal device; at-rest encryption is out of scope unless a user need says otherwise. |

## How to re-verify this posture (5-minute check)

If a future change adds a network dependency or cloud DB, these greps catch it:

```bash
# Must return nothing in the runtime package:
grep -rEi 'supabase|postgres|firebase|psycopg|sqlalchemy|flask|fastapi|django|requests\.|httpx|socket\.' src/photo_workflow/

# Confirm the data layer is still parameterized (values bound, no f-string SQL):
grep -nE 'execute\(|f".*(SELECT|INSERT|UPDATE)|\.format\(' src/photo_workflow/photondb.py
```

CI already enforces the broader guarantee: NFR-2.1 (offline at runtime) is a
policy gate — see [ci-policy.md](ci-policy.md). If those constraints ever
change (e.g. an optional cloud sync feature), this doc and the offline NFRs must
be revisited **in the same PR**, and the confidentiality threat model above
stops being moot.

## Provenance

Prompted by an r/vibecoding post (2026-07, "a private repo is not a private
app") flagged as a possible blind spot. Investigation confirmed the class of
failure is architecturally absent; the audit above is the durable record so the
check need not be repeated ad hoc.

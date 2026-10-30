# Zabbix integration for needrestart-lxc

Per-container restart alerts for LXC containers on Proxmox VE, with a
higher-priority trigger when the pending updates fix CVEs.

Requires **Zabbix 7.0 or newer** (dependent items with JSONPath, JSON LLD
macros). Tested against Zabbix 7.4.

## What it does

- A master item (`needrestart.lxc.master`) reads a JSON document with one entry
  per running container: `ctid`, `name`, `services` (needing restart), `cves`
  (unique CVEs fixed by the pending updates), `cves_ok` (whether CVE analysis is
  complete), `max_cvss` (highest CVSS base score among those CVEs, or `n/a`),
  `state` (0 = no alert, 1 = warning, 2 = high), `invasive`/
  `invasive_services` (count and names of flagged services needrestart would
  defer as potentially invasive; used by the script-server report, not by the
  triggers) and `details` (human-readable per-service breakdown).
- A discovery rule (`needrestart.lxc.discovery`, dependent on the master)
  discovers every container; each gets dependent items including
  `needrestart.lxc.services[{#CTID}]`, `needrestart.lxc.cves[{#CTID}]`,
  `needrestart.lxc.state[{#CTID}]`, `needrestart.lxc.max_cvss[{#CTID}]` and
  `needrestart.lxc.details[{#CTID}]`.
- Two mutually exclusive trigger prototypes per container (exactly one problem
  is open at a time, so the alert list stays clean). Both read the container's
  single consolidated `state` item (0/1/2) as the firing source:
  - **WARNING** — `{#CTNAME}: {ITEM.VALUE1} services need restart`, opdata
    `{ITEM.VALUE2} CVEs, highest CVSS {ITEM.VALUE4}` — fires when `state` = 1
    (restart needed without known CVEs — including the indeterminate-analysis
    case)
  - **HIGH** — same name and opdata — fires when `state` = 2 (the pending
    updates fix known CVEs, e.g. `test.lnw.verbo.net: 16 services need restart`,
    opdata `15 CVEs, highest CVSS 9.8`)

Both trigger prototypes allow **manual close** (matching the host-level
`Template needrestart` triggers), so an operator can close a restart alert they
have handled; the problem re-fires on the next problem cycle after the trigger
recovers.

`cves_ok` records whether the CVE analysis completed (1) or was indeterminate
(0 — the online lookup failed *and* no changelog verdict was available, so the
true count is unknowable). Indeterminate containers still alert: `state` = 1
(WARNING), matching the aggregate `summary.state`, so a lookup outage can never
hide restart findings; the WARNING may upgrade to HIGH on a later scan once the
lookup succeeds. `cves_ok` stays in the JSON so the indeterminate state remains
visible in the data. Containers where CVE analysis is not applicable
(non-Debian/Ubuntu, no dpkg) get the WARNING like any other restart finding.

> **Why the trigger uses `state` instead of combining `services`/`cves`/`cves_ok`:**
> the old expression compared three separate dependent items. Dependent items
> update at slightly different moments when the master refreshes, so a trigger
> using `last()` on several of them could briefly see a *mixed snapshot* (e.g.
> new `services` count with an old `cves_ok` value) and fire a false problem that
> immediately recovered — a PROBLEM/OK flap on every scan. Consolidating the
> decision into one `state` value per container (and one `state` in the summary)
> makes the trigger atomic and eliminates the race.

The severity reflects risk rather than an outage: pending restarts are
WARNING, pending restarts that fix known CVEs are HIGH. The CVSS figure does
not change the severity; it is informational only.

> **CVSS source:** for Ubuntu containers the score is the `cvss3` value from
> the Ubuntu Security API; for Debian containers it is the base score computed
> from the CVSS vector in the OSV response. Neither is a new network
> dependency (the host already performs these lookups for the CVE count). A
> CVE with no published metric, or with only a CVSS v4 vector, yields no score,
> and a container where none of its CVEs are scored reports `n/a`.

### Aggregate alert (one email instead of one per container)

When many containers need a restart at once, the per-container triggers would
otherwise generate one notification each (e.g. 130 emails). To collapse this
into a single email while keeping the full impact visible, the JSON also
carries a `summary` block and the template adds four host-level dependent
items plus two aggregate triggers:

- `needrestart.lxc.summary.count` — how many containers need a restart
- `needrestart.lxc.summary.cves` — total CVEs fixed across those containers
- `needrestart.lxc.summary.text` — a pre-formatted list of every affected
  container with its service/CVE counts (the email body)
- `needrestart.lxc.summary.state` — consolidated alert state for the episode
  (0 = none, 1 = warning, 2 = high)
- `needrestart.lxc.summary.max_cvss` — highest CVSS base score across all
  containers needing a restart, or `n/a`
- **WARNING** aggregate trigger — `{HOST.NAME}: {ITEM.VALUE1} containers need
  restart`, opdata `{ITEM.VALUE2} CVEs, highest CVSS {ITEM.VALUE5}` — fires when
  `summary.state` = 1
- **HIGH** aggregate trigger — same name/opdata — fires when `summary.state` = 2
  (count &gt; 0 and CVEs &gt; 0). Anchored on the single `summary.state` value for the
  same race-resistance as the per-container triggers; the `max_cvss` term is a
  harmless always-true clause that only gives the item a `{ITEM.VALUE5}` slot.
  Both aggregate triggers also allow **manual close**.

> **Note:** Zabbix 7.0 does not support template-level triggers in the XML
> export format (the template schema only allows triggers nested under items
> or as LLD trigger prototypes). The two aggregate triggers are therefore **not
> part of `template_needrestart_lxc.xml`** — they are created once on the
> template via the API (`trigger.create`, expression referencing
> `needrestart.lxc.summary.count`/`.cves`/`.text`/`.max_cvss`), which propagates
> them to every linked host. See `zabbix/create_aggregate_triggers` for the exact
> call; re-run it after re-importing the template if the triggers are missing
> or their text needs the new `max_cvss` clause.

Both aggregate triggers carry the tag `needrestart=aggregate`; the per-container
triggers carry `needrestart=container`. To get **one email per episode** with
the full list, configure your notification action to only match the aggregate
tag:

1. In the action's **Conditions**, add a condition **Tag** = `needrestart`
   **equals** `aggregate` (so per-container triggers never email).
2. In the action's **Operations** message, include `{ITEM.VALUE3}` to render the
   full per-container list, e.g.:

   ```
   {TRIGGER.NAME}
   {ITEM.VALUE3}
   ```

   `{ITEM.VALUE1}` is the container count, `{ITEM.VALUE2}` the CVE count and
   `{ITEM.VALUE5}` the highest CVSS base score.

The per-container triggers stay active and visible in the Zabbix problem list
for per-container tracking; they just no longer generate their own emails.

The master item polls every 15 minutes, matching the cron job that refreshes
the JSON every 15 minutes, so data is at most ~30 minutes old.

## Architecture

The scan (including the CVE analysis) takes several seconds on a host with
many containers and would exceed the Zabbix server `Timeout` (default 4s) if
the agent ran it synchronously. The scan therefore runs from cron as root; the
script writes `/var/cache/needrestart-lxc/zabbix.json` itself (creating the
directory if needed), and the agent check only reads that file (instant).
The cron job holds a `flock` so a slow scan and a manual `--zabbix` run can
never write the cache files concurrently.

## Installation (per Proxmox host)

1. Install the script:

   ```
   install -m 750 -o root -g root needrestart-lxc /usr/local/bin/needrestart-lxc
   ```

2. Install the agent config and cron job:

   ```
   install -m 644 zabbix/zabbix_agent2.d/needrestart-lxc.conf /etc/zabbix/zabbix_agent2.d/
   install -m 644 zabbix/cron.d/needrestart-lxc /etc/cron.d/
   ```

The agent `UserParameter` reads the JSON directly (with an empty-document
fallback), so no separate wrapper script is needed.

The script exports its own PATH so the cron job finds `/usr/sbin/pct` even
though cron runs with a minimal environment.

3. Generate the JSON once and restart the agent (the script creates
   `/var/cache/needrestart-lxc` and writes `zabbix.json` itself):

   ```
   /usr/local/bin/needrestart-lxc --zabbix
   systemctl restart zabbix-agent2
   ```

4. Verify the agent responds instantly:

   ```
   zabbix_agent2 -t needrestart.lxc.master
   ```

## Template

Import `template_needrestart_lxc.xml` in the Zabbix UI (Data collection ->
Templates -> Import) or via the API, then link it to the Proxmox host.
The template group `Templates` must exist (it does on a default install).

Notes:

- The CVE lookup requires outbound HTTPS from the Proxmox host and a `python3`
  interpreter (stdlib `urllib`, no extra packages); results are cached for 24h
  in `/var/cache/needrestart-lxc`.
- Only dpkg-based containers (Debian/Ubuntu) get CVE analysis; others are
  reported with `cves` = 0 (the restart trigger still applies).
- The `cves` count is the number of *unique* CVEs fixed across the pending
  updates in the container (deduplicated per source-package update, so a
  security update shared by six services counts once).
- If importing via the API fails with "SQL statement execution has failed" on
  the `triggers`/`functions` tables, the Zabbix `ids` table (internal ID
  allocator) is stale — a known artifact of DB restores. Repair:

  ```sql
  UPDATE ids SET nextid = (SELECT MAX(triggerid) FROM triggers) WHERE table_name='triggers';
  UPDATE ids SET nextid = (SELECT MAX(functionid) FROM functions) WHERE table_name='functions';
  ```

## template_needrestart.xml

Export of the Zabbix template `Template needrestart` (the host-level counterpart of the lxc one).
This was previously unversioned; added 2026-09-25 when `needrestart.ucode.status` was fixed.

That item parses `NEEDRESTART-UCSTA:` from `needrestart -b`, which only exists in needrestart >= 3.7
(Debian 13). On Debian 12/11 (needrestart 3.6) the line is absent, which used to make the item
unsupported - on 13 hosts. Its REGEX preprocessing step now has
`error_handler=CUSTOM_VALUE, error_handler_params=1`, i.e. "no microcode upgrade pending", which is
what the trigger `Microcode upgrade pending` (`<>1`) expects. Note that hosts carrying a
*standalone* copy of the item (not inherited from the template, `templateid` NULL) are not updated
by a template change and need the same edit applied directly.

### Host CVE / CVSS enrichment (needrestart-cve)

`needrestart` has no CVE or CVSS concept: `needrestart -b` only lists the units
whose processes map outdated libraries, so the original `Services need restart`
trigger could not tell a security update from a routine version bump (it was
HIGH for both). The host helper `needrestart-cve` adds the missing context
without changing the alert set: it starts from needrestart's own `-SVC:` list,
resolves each unit's deleted libraries to the owning dpkg package, derives the
version the process actually started with from `dpkg.log`, and asks OSV
(Debian) or the Ubuntu Security API how many CVEs the installed version fixes.
For each CVE it also stores the highest CVSS base score (computed from OSV's
CVSS v3 vector, or taken from the Ubuntu API's `cvss3`). The algorithm is the
same one needrestart-lxc uses for containers, so host and container reports
agree.

The helper runs from cron (every 15 minutes) and writes
`/var/cache/needrestart-cve/zabbix.json`. The write is atomic (temp file +
rename), so a cron run and an on-demand script-server scan cannot tear the
document. The agent item `needrestart.cve.master` reads that file, so the
Zabbix poll never performs an online lookup:

| Item | Meaning |
|---|---|
| `needrestart.cve.master` | the JSON document itself |
| `needrestart.cve.services` | services needrestart flags |
| `needrestart.cve.count` | unique CVEs fixed by restarting them |
| `needrestart.cve.cves_ok` | 0 when the analysis is indeterminate |
| `needrestart.cve.max_cvss` | highest CVSS score, or `n/a` |
| `needrestart.cve.state` | 0 clean, 1 restart without known CVEs, 2 restart with CVEs, 9 no data |
| `needrestart.cve.generated` | epoch of the report the agent is serving (freshness check) |
| `needrestart.cve.details` | per-service verdicts (service: CVEs, highest CVSS) |

Severity now follows risk, and the two restart triggers are mutually
exclusive because both read the single `needrestart.cve.state` value:

- **WARNING** `{HOST.NAME}: N services need restart` — `state` = 1: a restart is
  needed but no known CVEs are fixed by it (maintenance), including the case
  where the analysis is indeterminate (`cves_ok` = 0).
- **HIGH** — `state` = 2: the pending updates fix known CVEs. Operational data
  on both: `N CVEs, highest CVSS x.y`.
- **WARNING** `Needrestart CVE analysis is not reporting` — `state` = 9: the
  agent read no cache document (helper not installed, not yet run, or
  unreadable). This guards the failure that would otherwise be silent: the
  legacy trigger is disabled, so if the helper stops producing data the restart
  alerts must not disappear unnoticed. It is deliberately *not* a `nodata()`
  trigger: a host that is powered off reports no value at all, and must stay
  quiet instead of raising a permanent "not reporting" problem.
- **WARNING** `Needrestart CVE data is stale` — `now() - last(needrestart.cve.generated)
  > 3600` while `state` is not 9: the agent is still serving a report that
  the cron job has stopped refreshing (four missed runs). This is the case
  that a state check alone cannot see: the document exists and looks
  plausible, it is simply old. A missing document raises state 9 instead, and a
  powered-off host raises neither.

The legacy `Services need restart` trigger is imported as **DISABLED**; it is
superseded by the triggers above and would otherwise raise a duplicate problem
for one and the same finding. `needrestart.master` and its other items are
untouched, so kernel, microcode and session monitoring keep working even if the
CVE helper is not deployed on a host.

Deployment is handled by cdist (`manifest/autorun/zabbix-agent-config`, the
`needrestart` block): it installs `/usr/local/bin/needrestart-cve`, the
`needrestart.conf` UserParameters and the 15-minute cron job, then links the
template. The helper needs `python3` and outbound HTTPS to `api.osv.dev` /
`ubuntu.com`; lookups are cached for 24h in `/var/cache/needrestart-cve`.

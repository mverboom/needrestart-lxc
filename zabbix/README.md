# Zabbix integration for needrestart-lxc

Per-container restart alerts for LXC containers on Proxmox VE, with a
higher-priority trigger when the pending updates fix CVEs.

Requires **Zabbix 7.0 or newer** (dependent items with JSONPath, JSON LLD
macros). Tested against Zabbix 7.4.

## What it does

- A master item (`needrestart.lxc.master`) reads a JSON document with one entry
  per running container: `ctid`, `name`, `services` (needing restart), `cves`
  (unique CVEs fixed by the pending updates), `cves_ok` (whether CVE analysis is
  complete), `state` (0 = no alert, 1 = warning, 2 = high) and `details`
  (human-readable per-service breakdown).
- A discovery rule (`needrestart.lxc.discovery`, dependent on the master)
  discovers every container; each gets dependent items including
  `needrestart.lxc.services[{#CTID}]`, `needrestart.lxc.cves[{#CTID}]`,
  `needrestart.lxc.state[{#CTID}]` and `needrestart.lxc.details[{#CTID}]`.
- Two mutually exclusive trigger prototypes per container (exactly one problem
  is open at a time, so the alert list stays clean). Both read the container's
  single consolidated `state` item (0/1/2) as the firing source:
  - **WARNING** — `{#CTNAME}: {ITEM.VALUE1} services need restart`, opdata
    `{ITEM.VALUE2} CVEs` — fires when `state` = 1 (restart needed, CVE analysis
    complete with a genuine zero)
  - **HIGH** — same name and opdata — fires when `state` = 2 (the pending
    updates fix known CVEs, e.g. `test.lnw.verbo.net: 16 services need restart`,
    opdata `15 CVEs`)

The `cves_ok` flag guards against a false WARNING. The CVE count comes from an
online security lookup with a changelog fallback; if that lookup fails *and*
no changelog verdict is available the count is unknowable (it could be 0 or
many). In that indeterminate case `cves_ok` = 0, so `state` = 0 and **no**
trigger fires — the alert is deferred to the next scan (15 min later) rather
than risking a false "no CVEs" WARNING that would be superseded by a HIGH once
the lookup succeeds. Containers where CVE analysis is not applicable
(non-Debian/Ubuntu, no dpkg) keep `cves_ok` = 1 and still get the WARNING when
services need a restart.

> **Why the trigger uses `state` instead of combining `services`/`cves`/`cves_ok`:**
> the old expression compared three separate dependent items. Dependent items
> update at slightly different moments when the master refreshes, so a trigger
> using `last()` on several of them could briefly see a *mixed snapshot* (e.g.
> new `services` count with an old `cves_ok` value) and fire a false problem that
> immediately recovered — a PROBLEM/OK flap on every scan. Consolidating the
> decision into one `state` value per container (and one `state` in the summary)
> makes the trigger atomic and eliminates the race.

The severity reflects risk rather than an outage: pending restarts are
WARNING, pending restarts that fix known CVEs are HIGH.

### Aggregate alert (one email instead of one per container)

When many containers need a restart at once, the per-container triggers would
otherwise generate one notification each (e.g. 130 emails). To collapse this
into a single email while keeping the full impact visible, the JSON also
carries a `summary` block and the template adds three host-level dependent
items plus two aggregate triggers:

- `needrestart.lxc.summary.count` — how many containers need a restart
- `needrestart.lxc.summary.cves` — total CVEs fixed across those containers
- `needrestart.lxc.summary.text` — a pre-formatted list of every affected
  container with its service/CVE counts (the email body)
- `needrestart.lxc.summary.state` — consolidated alert state for the episode
  (0 = none, 1 = warning, 2 = high)
- **WARNING** aggregate trigger — `{HOST.NAME}: {ITEM.VALUE1} containers need
  restart`, opdata `{ITEM.VALUE2} CVEs` — fires when `summary.state` = 1
- **HIGH** aggregate trigger — same name/opdata — fires when `summary.state` = 2
  (count &gt; 0 and CVEs &gt; 0). Anchored on the single `summary.state` value for the
  same race-resistance as the per-container triggers.

> **Note:** Zabbix 7.0 does not support template-level triggers in the XML
> export format (the template schema only allows triggers nested under items
> or as LLD trigger prototypes). The two aggregate triggers are therefore **not
> part of `template_needrestart_lxc.xml`** — they are created once on the
> template via the API (`trigger.create`, expression referencing
> `needrestart.lxc.summary.count`/`.cves`/`.text`), which propagates them to
> every linked host. See `zabbix/create_aggregate_triggers.py` for the exact
> call; re-run it after re-importing the template if the triggers are missing.

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

   `{ITEM.VALUE1}` is the container count and `{ITEM.VALUE2}` the CVE count.

The per-container triggers stay active and visible in the Zabbix problem list
for per-container tracking; they just no longer generate their own emails.

The master item polls every hour; a cron job refreshes the JSON every 15
minutes, so data is at most ~1 hour old.

## Architecture

The scan (including the CVE analysis) takes several seconds on a host with
many containers and would exceed the Zabbix server `Timeout` (default 4s) if
the agent ran it synchronously. The scan therefore runs from cron as root; the
script writes `/var/cache/needrestart-lxc/zabbix.json` itself (creating the
directory if needed), and the agent check only reads that file (instant).

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

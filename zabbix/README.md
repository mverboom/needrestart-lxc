# Zabbix integration for needrestart-lxc

Per-container restart alerts for LXC containers on Proxmox VE, with a
higher-priority trigger when the pending updates fix CVEs.

Requires **Zabbix 7.0 or newer** (dependent items with JSONPath, JSON LLD
macros). Tested against Zabbix 7.4.

## What it does

- A master item (`needrestart.lxc.master`) reads a JSON document with one entry
  per running container: `ctid`, `name`, `services` (needing restart), `cves`
  (unique CVEs fixed by the pending updates) and `details` (human-readable
  per-service breakdown).
- A discovery rule (`needrestart.lxc.discovery`, dependent on the master)
  discovers every container; each gets three dependent items:
  `needrestart.lxc.services[{#CTID}]`, `needrestart.lxc.cves[{#CTID}]` and
  `needrestart.lxc.details[{#CTID}]`.
- Two mutually exclusive trigger prototypes per container (exactly one problem
  is open at a time, so the alert list stays clean):
  - **WARNING** — `{#CTNAME}: {ITEM.VALUE1} services need restart`, opdata
    `{ITEM.VALUE2} CVEs` — fires when services &gt; 0 and no CVEs are pending
    (opdata shows `0 CVEs`)
  - **HIGH** — same name and opdata — fires when the pending updates fix CVEs
    (e.g. `test.lnw.verboom.net: 6 services need restart`, opdata `15 CVEs`)

The severity reflects risk rather than an outage: pending restarts are
WARNING, pending restarts that fix known CVEs are HIGH.

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

2. Install the wrapper, agent config and cron job:

   ```
   install -m 755 zabbix/needrestart-lxc-zabbix-cat /usr/local/bin/
   install -m 644 zabbix/zabbix_agent2.d/needrestart-lxc.conf /etc/zabbix/zabbix_agent2.d/
   install -m 644 zabbix/cron.d/needrestart-lxc /etc/cron.d/
   ```

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

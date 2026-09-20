# script-server integration

Web UI (script-server on the cdist host) to report on — and trigger —
needrestart and needrestart-lxc across the managed hosts.

## How it works

- The cdist user's SSH lands as root on every managed host, where cdist deploys
  `/usr/local/bin/needrestart-lxc` (see `manifest/autorun/zabbix-agent-config`).
- script-server runners execute as the cdist user
  (`sudo -u cdist -i needrestart-ss ...` / `... needrestart-lxc-ss ...`), so the
  wrappers can simply `ssh <host>` to run scans or restarts.
- There are **two runners**, one per tool: `needrestart` and
  `needrestart-lxc`. Each has an **Action** pulldown (`Status report` /
  `Restart flagged services`); the selected value is passed to the wrapper as
  the first positional argument (the subcommand) and also selects which include
  file defines the remaining fields.
- Runner definitions live in `/etc/script-server-dev/runners/`
  (`needrestart.json`, `needrestart-lxc.json`); each is a symlink into this
  repo's clone at `/home/cdist/files.external/needrestart-lxc.git/scriptserver/`,
  as are the wrappers in `~cdist/bin`.

## Action includes

script-server's `include` mechanism (same pattern as the `Updates` runner)
merges an action-specific JSON into the runner. The two base runners therefore
only declare the `Action` pulldown:

```json
"include": "/home/cdist/files.external/needrestart-lxc.git/scriptserver/include/needrestart-${Action}.json"
```

The include files live in `scriptserver/include/` and are referenced by
**absolute path** into the checkout, so they need no separate symlinks — a
`git pull` activates changes. They can override the fields that must differ per
action, which is why the base runner sets neither `requires_terminal` nor
`output_format` (base values win on merge, so they must stay unset):

- `needrestart-status.json` / `nrlxc-status.json`:
  `requires_terminal: false`, `output_format: html_iframe`, plus `All hosts`,
  `Hosts` and (lxc only) `Data`.
- `needrestart-restart.json` / `nrlxc-restart.json`:
  `requires_terminal: true`, plus `Hosts`, `Services`/`Containers`,
  `Allow all`, `Exclude` and `Restart mode` (dry-run / restart).

## Runners

### Status report (read-only)

- `needrestart`: per-host HTML report (batch scan `needrestart -b -w`) of
  services running outdated libraries, kernel/microcode status and user
  sessions; rows flag services needrestart would defer as potentially invasive
  (Invasive column).
- `needrestart-lxc`: HTML report per host: containers, state badge (clean /
  restart / CVEs), services and CVE verdicts, Invasive badge. Two data
  sources — **Scan now** (`needrestart-lxc --zabbix`, fresh incl. CVE analysis)
  and **Cached** (`/var/cache/needrestart-lxc/zabbix.json`, at most 15 minutes
  old).

Rows needing work deep-link into the same runner's **restart** action (host,
service/container and restart mode pre-filled). Deep links require
`output_format: html_iframe` and the hash-mode router pre-fill (see the
script-server skill notes). Both the top-level `Action` and the inner
`Restart mode` are pinned in the link because script-server's pre-fill replaces
the whole value state: parameters not in the link get no value, not their
default.

### Restart

Restart flagged services on one or several hosts in one run. **Hosts** is a
multiselect; **Services** / **Containers** is a multiselect of `host:service`
pairs refreshed from the selected hosts. The status report's **go to restart**
button prefills both from the ticked rows. Leave the selection empty to preview
everything with `Restart mode = Dry run`; a real restart with an empty
selection additionally requires **Allow all** (safety switch — never restart
everything by accident).

Each host is scanned fresh and processed sequentially with live terminal
output. Restarting includes the escalation ladder (restart → kill + start →
SIGKILL). Non-systemd processes and scope units are reported but never
restarted automatically, mirroring the script's own safety rules. Potentially
invasive services (needrestart's deferred list, shown in the report's Invasive
column) are restarted like any other flagged service; that marking is
informational and does not skip them.

## Installation / update

On the cdist control host:

```sh
cd /home/cdist/files.external/needrestart-lxc.git && git pull --ff-only origin master
# wrappers: symlinked into ~cdist/bin (survive git pulls)
ln -sfn ../files.external/needrestart-lxc.git/scriptserver/needrestart-ss \
        /home/cdist/bin/needrestart-ss
ln -sfn ../files.external/needrestart-lxc.git/scriptserver/needrestart-lxc-ss \
        /home/cdist/bin/needrestart-lxc-ss
# runner definitions: symlinked into script-server (survive git pulls)
ln -sfn /home/cdist/files.external/needrestart-lxc.git/scriptserver/needrestart.json \
        /etc/script-server-dev/runners/needrestart.json
ln -sfn /home/cdist/files.external/needrestart-lxc.git/scriptserver/needrestart-lxc.json \
        /etc/script-server-dev/runners/needrestart-lxc.json
```

Remove the superseded runner symlinks if present:
`needrestart-list.json`, `needrestart-restart.json`,
`needrestart-lxc-list.json`, `needrestart-lxc-restart.json`.

A `git pull` is enough after that: the wrappers and both runner definitions are
symlinks into the checkout, the action includes are read from the checkout by
absolute path, and script-server re-reads runner files from disk on every page
load — no service restart needed. (Caveat: editing a runner through
script-server's admin UI would write through the symlink into the git
checkout; treat the checkout as the single source of truth.)

## Host lists

- `needrestart-ss hosts`: hosts whose cdist explorer `packages` file lists the
  `needrestart` package.
- `needrestart-lxc-ss hosts`: cdist explorer data
  (`/home/cdist/explore/<fqdn>/distro` == `proxmox`) intersected with the
  zabbix-agent-config gate (`/home/cdist/config/files/zabbix/agents/<fqdn>`
  existing) — i.e. exactly the hosts where the manifest deploys
  needrestart-lxc.

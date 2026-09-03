# script-server integration for needrestart-lxc

Web UI (script-server on the cdist host) to report on — and trigger —
needrestart-lxc across all Proxmox hosts managed by cdist.

## How it works

- The cdist user's SSH lands as root on every PVE host, where cdist deploys
  `/usr/local/bin/needrestart-lxc` (see `manifest/autorun/zabbix-agent-config`).
- script-server runners execute as the cdist user
  (`sudo -u cdist -i needrestart-lxc-ss ...`), so the wrapper
  `needrestart-lxc-ss` can simply `ssh <host>` to run scans or restarts.
- Runner definitions live in `/etc/script-server-dev/runners/`
  (`needrestart-status.json`, `needrestart-restart.json`); the wrapper lives in
  `~cdist/bin/needrestart-lxc-ss` (symlink into this repo's clone at
  `/home/cdist/files.external/needrestart-lxc.git/scriptserver/`).

## Runners

### list (read-only)

HTML report per host: containers, state badge (clean / restart / CVEs),
services and CVE verdicts. Two data sources:

- **Scan now** (default): `ssh <host> /usr/local/bin/needrestart-lxc --zabbix` —
  fresh scan including CVE analysis; also warms the host's 24h CVE API cache
  shared with the cron job.
- **Cached**: read `/var/cache/needrestart-lxc/zabbix.json` — instant, at most
  15 minutes old.

Rows needing work deep-link into the restart runner (host, container and
dry-run pre-filled). Deep links require `output_format: html` (hash-mode router
pre-fill, see script-server skill notes).

### restart

Restart flagged services inside containers, on one or several Proxmox hosts in
one run. **Hosts** is a multiselect; **Containers** is a multiselect of
`host:container` pairs refreshed from the selected hosts' cached reports —
leave it empty to restart ALL flagged containers on every selected host. The
list report's **go to restart** button prefills both from the ticked rows.

Each host is scanned fresh and processed sequentially with live terminal
output. `restart` is the default action; select `dry-run` to preview first.
Restarting includes the escalation ladder (restart → kill + start → SIGKILL).
Non-systemd processes and scope units are reported but never restarted
automatically, mirroring the script's own safety rules.

## Installation / update

On the cdist control host:

```sh
cd /home/cdist/files.external/needrestart-lxc.git && git pull --ff-only origin master
# wrapper: symlinked into ~cdist/bin (survives git pulls)
ln -sfn ../files.external/needrestart-lxc.git/scriptserver/needrestart-lxc-ss \
        /home/cdist/bin/needrestart-lxc-ss
# runner definitions: symlinked into script-server (survive git pulls)
ln -sfn /home/cdist/files.external/needrestart-lxc.git/scriptserver/needrestart-status.json \
        /etc/script-server-dev/runners/needrestart-status.json
ln -sfn /home/cdist/files.external/needrestart-lxc.git/scriptserver/needrestart-restart.json \
        /etc/script-server-dev/runners/needrestart-restart.json
```

A `git pull` is enough: the wrapper and both runner definitions are symlinks
into the checkout, and script-server re-reads runner files from disk on every
page load - no service restart needed. (Caveat: editing a runner through
script-server's admin UI would write through the symlink into the git
checkout; treat the checkout as the single source of truth.)

## Host list

`needrestart-lxc-ss hosts` derives the PVE hosts dynamically: cdist explorer
data (`/home/cdist/explore/<fqdn>/distro` == `proxmox`) intersected with the
zabbix-agent-config gate (`/home/cdist/config/files/zabbix/agents/<fqdn>`
existing) — i.e. exactly the hosts where the manifest deploys
needrestart-lxc.
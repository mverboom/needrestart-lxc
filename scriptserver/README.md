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

### needrestart-lxc status (read-only)

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

### needrestart-lxc restart

Runs `needrestart-lxc [-n] -r [-c CTID] [-e REGEX]` on one host with live
terminal output. `dry-run` is the default action; `restart` restarts every
flagged service, including the escalation ladder (restart → kill + start →
SIGKILL). Non-systemd processes and scope units are reported but never
restarted automatically, mirroring the script's own safety rules.

## Installation / update

On the cdist control host:

```sh
cd /home/cdist/files.external/needrestart-lxc.git && git pull --ff-only origin master
# wrapper: symlinked into ~cdist/bin (survives git pulls)
ln -sfn ../files.external/needrestart-lxc.git/scriptserver/needrestart-lxc-ss \
        /home/cdist/bin/needrestart-lxc-ss
# runner definitions: copy into script-server (owned by script-dev)
install -o script-dev -g script-dev -m 664 \
    scriptserver/needrestart-status.json scriptserver/needrestart-restart.json \
    /etc/script-server-dev/runners/
```

script-server picks up runner changes after a restart of the service
(`systemctl restart script-server-dev` or equivalent for the launcher process).

## Host list

`needrestart-lxc-ss hosts` derives the PVE hosts dynamically: cdist explorer
data (`/home/cdist/explore/<fqdn>/distro` == `proxmox`) intersected with the
zabbix-agent-config gate (`/home/cdist/config/files/zabbix/agents/<fqdn>`
existing) — i.e. exactly the hosts where the manifest deploys
needrestart-lxc.
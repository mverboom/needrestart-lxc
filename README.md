# needrestart-lxc

**This code was created with the assistance of an LLM. If you are not comfortable with that, please don't use it.**

This script was created in order to be able to detect services within lxc container that need to be restarted because of updated binaries or libraries. This is a simplified implementation of what needrestart provides, specifically for containers. It does not require needrestart on the Proxmox VE server.

## Running the command

### Default action

When running the command without options it will scan all containers for services that need to be restarted.
This is the same as starting the script with the list (-l, --list) option.

### Restart

The script can restart the services that need to be restarted. This requires the -r or --restart option.

For regular services the script runs `systemctl restart`. It then verifies that
the outdated processes are actually gone. Some services use `KillMode=process`
(e.g. `cron.service` on Debian/Ubuntu), which means `systemctl restart` only
kills the main daemon and leaves child processes — such as long-running daemons
spawned by a cron job — alive with outdated libraries. When the script detects
that stale processes remain after the restart, it automatically escalates to
`systemctl kill <service>` (which sends the signal to **all** processes in the
cgroup regardless of `KillMode`) followed by `systemctl start <service>`. If
processes survive `SIGTERM`, a final `SIGKILL` is sent. Each escalation step is
reported on stderr/stdout.

Scope units (`*.scope`) are stopped with `systemctl stop` (which terminates
their processes), and the container's own systemd (`systemd-manager`) is
re-executed with `systemctl daemon-reexec`.

### Dry run

To review the commands that would be executed the script can be run in dry run mode with -n or --dry-run.

```
needrestart-lxc -r -n
Container 100 (test): restarting service systemd-journald.service
  [DRY RUN] Would run: pct exec 100 -- systemctl restart systemd-journald.service
Container 100 (test): restarting service systemd-logind.service
  [DRY RUN] Would run: pct exec 100 -- systemctl restart systemd-logind.service
```

### Specific container

To only do a check for a specific container, the container to be checked can be specified by its numerical
ID with the -c option.

```
needrestart-lxc -c 100
Container 100 (test): service systemd-journald.service needs restart
Container 100 (test): service systemd-logind.service needs restart
```

### Excluding services

It is possible to exclude services from being checked with the -e or --exclude
option. This option can be used multiple times.

```
needrestart-lxc -c 100 -e systemd-logind.service
Container 100 (test): service systemd-journald.service needs restart
```

### User session services

The script detects outdated processes in user session cgroups (e.g., `user@N.service`) and
reports them as services needing restart. This covers cases where `needrestart` would flag an
entire container for reboot because of outdated libraries in user session processes.

Services that live *inside* a user session manager subtree (units under
`user@N.service/`, such as the session `dbus.service`, `pipewire.service`,
or `wireplumber.service`) are managed by the user's own systemd instance,
not PID 1. They are restarted granularly with `systemctl --user` invoked as
the owning user (`runuser -u <user> -- env XDG_RUNTIME_DIR=/run/user/<uid>
systemctl --user restart <unit>`). Restarting the *system* unit of the same
name (the previous behaviour) did not touch these processes, so they were
left stale after `-r`. The owning user is resolved inside the container from
the UID found in the cgroup path. As with system services, the script verifies
that the stale processes are actually gone and escalates to `systemctl --user
kill` (+ start) and finally `SIGKILL` if needed.

For login session scopes and other scope units that cannot be restarted with `systemctl restart`,
the script identifies them as scope units and stops them with `systemctl stop`, which
terminates their processes. Session scopes (e.g., `session-c2.scope`) are siblings of
`user@N.service` in the cgroup hierarchy and are stopped at the system level; user-session
scopes (under `user@N.service/`) are stopped with `systemctl --user stop`. This is necessary
because session scopes are siblings of `user@N.service` in the cgroup hierarchy — restarting
`user@N.service` does not kill processes in session scopes.

### Deep scan

The deep scan takes longer and checks all open files for a container for changed inodes. This can be invoked
by -d or --deep.

### Security scan (CVE analysis)

The security scan (`-s` or `--security`) goes one step further: for every stale library it determines the
owning dpkg package, the version the stale process is actually running, and whether the pending update is
a security fix — including how many CVEs it addresses.

With `-s` alone the output stays on a single line and appends the total CVE count:

```
needrestart-lxc -c 100 -s
Container 100 (gw.cnw.verboom.net): service unbound.service needs restart (1 CVE)
```

With `-s -v` the per-package details are shown below the service line:

```
needrestart-lxc -c 100 -s -v
Container 100 (gw.cnw.verboom.net): service unbound.service needs restart
  - /usr/lib/x86_64-linux-gnu/libcrypto.so.3
  [security] libssl3 3.0.11-1~deb12u1 -> 3.0.11-1~deb12u2: SECURITY update, fixes 1 CVE (CVE-2023-5363) [OSV]
```

How it works:

1. **Package mapping** — each stale library path is resolved against the container's dpkg file-list
database (`/var/lib/dpkg/info/*.list`), which works even though the file on disk was deleted/replaced.
2. **Old version** — the version the stale process is running is derived from the container's `dpkg.log`
upgrade/install timestamps matched against the process start time (`/proc/<pid>` on the host). This
is more accurate than assuming "last upgrade": a long-running daemon can be several versions behind.
`/var/log/apt/history.log` is used as a fallback when `dpkg.log` is unavailable.
3. **CVE lookup** — the version delta is checked against security data, queried online and cached for
24h in `/var/cache/needrestart-lxc`:
   - **Debian**: the [OSV](https://osv.dev) API (per-package query by version, filtered to the
     container's Debian release).
   - **Ubuntu**: the [Ubuntu Security API](https://ubuntu.com/security/api/docs) (`cves.json` per
     source package, filtered by release codename and `released` status; includes CVSS scores).
   - **Fallback (offline)**: the package's `changelog.Debian.gz` inside the container is parsed for
     CVE references between the old and new versions. Security uploads are detected by the
     `-security`/`-updates` suite marker in the changelog entry headers.
4. **Output** — with `-s` alone each service line gets a `(N CVEs)` suffix (the total across all
packages of that service); with `-s -v` the per-package verdicts are printed below the line. The same
applies in `-r`/`-n` (restart/dry-run) mode, right before the restart.

Caveats:

- Only dpkg-based containers (Debian/Ubuntu) are analyzed; other distros are reported and skipped.
- Online lookups require outbound HTTPS from the Proxmox host and a `python3` interpreter (stdlib
  `urllib`, no extra packages). The Ubuntu API is rate-limited, so the script paces requests and
  retries on HTTP 429. Everything is cached for 24h.
- The old version can only be determined if the relevant `dpkg.log`/`apt history.log` entries are still
  retained (log rotation). Otherwise the latest changelog entry is reported with an
  "old version unknown" note.
- Log timestamps are interpreted with the container's timezone (`/etc/timezone`) — containers that
  override the host timezone may yield an imprecise old version.
- The CVE count is per package, not per service: restarting one service may fix CVEs that also matter
  for other services, so treat the number as "what this update fixes", not "what this restart fixes".

### Verbose

Using verbose mode with -v or --verbose will provide more information about the specific libraries.

```
needrestart-lxc -c 100 -d -v
Loaded 1 container names
Found 1 running containers
Scanning container processes for outdated libraries...
Checking PID 2148 (CT 100, systemd-manager)...
  -> Service systemd-manager in CT 100 needs restart
Checking PID 2262 (CT 100, systemd-journald.service)...
  -> Service systemd-journald.service in CT 100 needs restart
Checking PID 2370 (CT 100, cron.service)...
Checking PID 2371 (CT 100, dbus.service)...
Checking PID 2376 (CT 100, rsyslog.service)...
Checking PID 2378 (CT 100, systemd-logind.service)...
  -> Service systemd-logind.service in CT 100 needs restart
Checking PID 6560 (CT 100, nullmailer.service)...
Checking PID 6567 (CT 100, unattended-upgrades.service)...
  -> Service unattended-upgrades.service in CT 100 needs restart
Checking PID 6602 (CT 100, unbound.service)...
  -> Service unbound.service in CT 100 needs restart
Container 100 (gw.cnw.verboom.net): service systemd-journald.service needs restart
  - /usr/lib/x86_64-linux-gnu/libcrypto.so.3
Container 100 (gw.cnw.verboom.net): service systemd-logind.service needs restart
  - /usr/lib/x86_64-linux-gnu/libcrypto.so.3
Container 100 (gw.cnw.verboom.net): service systemd-manager needs restart
  - /usr/lib/x86_64-linux-gnu/libcrypto.so.3
Container 100 (gw.cnw.verboom.net): service unattended-upgrades.service needs restart
  - /usr/lib/x86_64-linux-gnu/libcrypto.so.3
  - /usr/lib/x86_64-linux-gnu/libssl.so.3
```

### Zabbix integration

The script can feed Zabbix with per-container restart and CVE alerts. The
`--zabbix` mode emits a single JSON document (one entry per running container)
that a Zabbix template turns into per-container items and triggers:

- **WARNING** when a container has services needing restart (no known CVEs)
- **HIGH** when the pending updates fix CVEs

The problem reads `container: N services need restart` with the CVE count as
operational data; exactly one problem is open per container at a time.

The scan runs via cron so the agent check stays fast; see
[`zabbix/README.md`](zabbix/README.md) for the full installation guide,
the template and the config snippets. Requires Zabbix 7.0 or newer.

```
needrestart-lxc --zabbix
{"containers": [{"ctid": "124", "name": "test.lnw.verboom.net",
  "services": 6, "cves": 15, "details": "..."}, ...]}
```

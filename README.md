# needrestart-lxc

**This code was created with the assistance of an LLM. If you are not comfortable with that, please don't use it.**

This script was created in order to be able to detect services within lxc container that need to be restarted because of updated binaries or libraries. This is a simplified implementation of what needrestart provides, specifically for containers. It does not require needrestart on the Proxmox VE server.

## Running the command

### Default action

When running the command without options it will scan all containers for services that need to be restarted.
This is the same as starting the script with the list (-l, --list) option.

### Restart

The script can restart the services that need to be restarted. This requires the -r or --restart option.

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

For login session scopes and other scope units that cannot be restarted with `systemctl restart`,
the script maps them to their parent `user@N.service` when possible, since that is the
restartable unit.

### Deep scan

The deep scan takes longer and checks all open files for a container for changed inodes. This can be invoked
by -d or --deep.

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

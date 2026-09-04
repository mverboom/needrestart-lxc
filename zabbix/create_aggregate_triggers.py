#!/usr/bin/env python3
"""
Create the two aggregate restart triggers on the "Template needrestart lxc"
template via the Zabbix API.

Zabbix 7.0 does not support template-level triggers in the XML export format,
so these triggers cannot live in template_needrestart_lxc.xml. They are created
once on the template and propagate to every linked host. Re-run this script
after re-importing the template if the triggers are missing.

The firing condition is anchored on the consolidated summary.state item
(value 1 = warning, value 2 = high) so the aggregate trigger evaluates a
single value instead of racing across summary.count / summary.cves /
summary.text. count / cves / text are kept in the expression for the
{ITEM.VALUE1}/{ITEM.VALUE2}/{ITEM.VALUE3} macros (name, opdata, body).

Usage:
    python3 create_aggregate_triggers.py [--api-key /path/to/key]

The API key file contains the raw Zabbix API token (one line). The key is read
from the file and never printed.
"""
import json
import sys
import urllib.error
import urllib.request

API_URL = "https://zabbix.lnw.verboom.net/zabbix/api_jsonrpc.php"
TEMPLATE = "Template needrestart lxc"
DEFAULT_KEY_FILE = "/home/mark/.pi/api-zabbix"

# Zabbix trigger priorities: 0=not classified,1=info,2=warning,3=average,
# 4=high,5=disaster
WARNING = 2
HIGH = 4


def call(token, method, params):
    payload = {"jsonrpc": "2.0", "method": method, "id": 1, "params": params}
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json-rpc",
                 "Authorization": f"Bearer {token}"},
    )
    # TLS verification stays on; the API cert validates against the system CA.
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": {"data": e.read().decode()[:300]}}
    except urllib.error.URLError as e:
        return {"error": {"data": f"connection failed: {e.reason}"}}


def aggregate_expr(cmp_op, state_value):
    """Build the aggregate trigger expression.

    The empty-string operand in the `summary.text <> ""` clause must appear as
    two double-quote characters in the final expression.
    """
    empty = '""'
    return (
        f"last(/{TEMPLATE}/needrestart.lxc.summary.count)>0 and "
        f"last(/{TEMPLATE}/needrestart.lxc.summary.cves){cmp_op} and "
        f"last(/{TEMPLATE}/needrestart.lxc.summary.text)<>{empty} and "
        f"last(/{TEMPLATE}/needrestart.lxc.summary.state)={state_value}"
    )


def main():
    key_file = DEFAULT_KEY_FILE
    argv = sys.argv[1:]
    if argv:
        if len(argv) == 2 and argv[0] == "--api-key":
            key_file = argv[1]
        else:
            sys.exit(f"usage: {sys.argv[0]} [--api-key /path/to/key]")

    try:
        with open(key_file) as fh:
            token = fh.read().strip()
    except OSError as e:
        sys.exit(f"cannot read API key file {key_file}: {e}")
    if not token:
        sys.exit(f"API key file {key_file} is empty")

    # Find the template id.
    r = call(token, "template.get",
             {"output": ["templateid"], "filter": {"host": [TEMPLATE]}})
    if "error" in r:
        sys.exit(f"template.get failed: {r['error']}")
    if not r.get("result"):
        sys.exit(f"template '{TEMPLATE}' not found")
    templateid = r["result"][0]["templateid"]

    triggers = [
        {
            "expression": aggregate_expr("=0", 1),
            "description": "{HOST.NAME}: {ITEM.VALUE1} containers need restart",
            "opdata": "{ITEM.VALUE2} CVEs",
            "priority": WARNING,
            "comments": ("Aggregate alert: one or more containers have services "
                         "needing a restart and no known CVEs are pending. The "
                         "notification message can include the full per-container "
                         "list via {ITEM.VALUE3}. The consolidated summary.state "
                         "(value 1) is the trigger source so the aggregate trigger "
                         "cannot race across the separate summary items."),
            "tags": [{"tag": "needrestart", "value": "aggregate"}],
        },
        {
            "expression": aggregate_expr(">0", 2),
            "priority": HIGH,
            "description": "{HOST.NAME}: {ITEM.VALUE1} containers need restart",
            "opdata": "{ITEM.VALUE2} CVEs",
            "comments": ("Aggregate alert: one or more containers have services "
                         "needing a restart and the pending updates fix known CVEs. "
                         "The notification message can include the full per-container "
                         "list via {ITEM.VALUE3}. The summary.state (value 2) is the "
                         "trigger source so the aggregate trigger cannot race across "
                         "the separate summary items."),
            "tags": [{"tag": "needrestart", "value": "aggregate"}],
        },
    ]

    created = 0
    for t in triggers:
        r = call(token, "trigger.create", [t])
        if "error" in r:
            data = r["error"].get("data", "")
            if "already exists" in data:
                print(f"already present, skipping: {t['description']}")
            else:
                print(f"trigger.create failed: {r['error']}")
        else:
            created += len(r.get("result", {}).get("triggerids", []))
            print(f"created trigger: {t['description']}")

    print(f"done. created {created} aggregate trigger(s) on template "
          f"'{TEMPLATE}' (id {templateid}).")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Create the two aggregate restart triggers on the "Template needrestart lxc"
template via the Zabbix API.

Zabbix 7.0 does not support template-level triggers in the XML export format,
so these triggers cannot live in template_needrestart_lxc.xml. They are created
once on the template and propagate to every linked host. Re-run this script
after re-importing the template if the triggers are missing.

Usage:
    python3 create_aggregate_triggers.py [--api-key /path/to/key]

The API key file contains the raw Zabbix API token (one line). The key is read
from the file and never printed.
"""
import argparse
import json
import ssl
import sys
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
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        resp = urllib.request.urlopen(req, timeout=30, context=ctx)
        return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": {"data": e.read().decode()[:300]}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-key", default=DEFAULT_KEY_FILE,
                    help="path to file containing the Zabbix API token")
    args = ap.parse_args()

    token = open(args.api_key).read().strip()

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
            "expression": (f"last(/{TEMPLATE}/needrestart.lxc.summary.count)>0 and "
                           f"last(/{TEMPLATE}/needrestart.lxc.summary.cves)=0 and "
                           f"last(/{TEMPLATE}/needrestart.lxc.summary.text)<>\""),
            "description": "{HOST.NAME}: {ITEM.VALUE1} containers need restart",
            "opdata": "{ITEM.VALUE2} CVEs",
            "priority": WARNING,
            "comments": ("Aggregate alert: one or more containers have services "
                         "needing a restart and no known CVEs are pending. The "
                         "notification message can include the full per-container "
                         "list via {ITEM.VALUE3}."),
            "tags": [{"tag": "needrestart", "value": "aggregate"}],
        },
        {
            "expression": (f"last(/{TEMPLATE}/needrestart.lxc.summary.count)>0 and "
                           f"last(/{TEMPLATE}/needrestart.lxc.summary.cves)>0 and "
                           f"last(/{TEMPLATE}/needrestart.lxc.summary.text)<>\""),
            "description": "{HOST.NAME}: {ITEM.VALUE1} containers need restart",
            "opdata": "{ITEM.VALUE2} CVEs",
            "priority": HIGH,
            "comments": ("Aggregate alert: one or more containers have services "
                         "needing a restart and the pending updates fix known CVEs. "
                         "The notification message can include the full per-container "
                         "list via {ITEM.VALUE3}."),
            "tags": [{"tag": "needrestart", "value": "aggregate"}],
        },
    ]

    created = 0
    for t in triggers:
        # The empty-string literal must use double quotes in the expression.
        t["expression"] += '"'
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

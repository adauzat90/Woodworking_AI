"""Shell-side client for the Woodworking AI Fusion folder-bridge.

Standard-library only -- run it with any Python; it needs neither Fusion nor the
``woodworking_ai`` package. It drops a request into the bridge inbox and waits
for the add-in (running inside Fusion) to build it and write a result.

Usage::

    python bridge_client.py status
    python bridge_client.py import path/to/spec.json [--no-machined] [--reports] [--wait N]
    python bridge_client.py design "36 inch sink base, two shaker doors" [--wait N]
    python bridge_client.py submit path/to/request.json [--wait N]

The drop directory is ``$WOODAI_FUSION_DROP`` or ``~/.woodai/fusion_drop`` and
must match what the add-in uses.
"""

import argparse
import json
import os
import sys
import time
import uuid


def drop_root():
    env = os.environ.get("WOODAI_FUSION_DROP")
    if env and env.strip():
        return os.path.abspath(env.strip())
    return os.path.join(os.path.expanduser("~"), ".woodai", "fusion_drop")


def _dirs():
    root = drop_root()
    return root, os.path.join(root, "inbox"), os.path.join(root, "outbox")


def bridge_status():
    """Return ``{"status": ..., "heartbeat": ..., "alive": bool, "root": ...}``."""
    root, _, _ = _dirs()
    out = {"root": root}
    for key, fname in (("status", "status.json"), ("heartbeat", "heartbeat.json")):
        path = os.path.join(root, fname)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                out[key] = json.load(fh)
        except Exception:
            out[key] = None
    hb = out.get("heartbeat") or {}
    out["alive"] = _fresh(hb.get("time"), max_age=10.0) and bool(
        (out.get("status") or {}).get("running", False)
    )
    return out


def _fresh(stamp, max_age):
    """True if ISO ``stamp`` (local, seconds) is within *max_age* seconds of now."""
    if not stamp:
        return False
    try:
        t = time.mktime(time.strptime(stamp, "%Y-%m-%dT%H:%M:%S"))
    except Exception:
        return False
    return (time.time() - t) <= max_age


def submit(request, name=None):
    """Write *request* (a dict) into the inbox atomically; return its name."""
    root, inbox, _ = _dirs()
    os.makedirs(inbox, exist_ok=True)
    if not name:
        name = "req-" + uuid.uuid4().hex[:8]
    if not name.endswith(".json"):
        name += ".json"
    final = os.path.join(inbox, name)
    tmp = final + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(request, fh, indent=2)
    os.replace(tmp, final)          # atomic: the watcher never sees a partial file
    return name


def wait_result(name, timeout=180.0, poll=0.5):
    """Poll the outbox for ``<stem>.result.json``; return it, or None on timeout."""
    _, _, outbox = _dirs()
    stem = name[:-5] if name.endswith(".json") else name
    result_path = os.path.join(outbox, stem + ".result.json")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.isfile(result_path):
            try:
                with open(result_path, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except Exception:
                pass    # mid-write; try again
        time.sleep(poll)
    return None


def submit_and_wait(request, name=None, timeout=180.0):
    return wait_result(submit(request, name=name), timeout=timeout)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _options_from_args(args):
    opts = {}
    if getattr(args, "no_machined", False):
        opts["machined"] = False
    if getattr(args, "no_subassembly", False):
        opts["by_subassembly"] = False
    if getattr(args, "reports", False):
        opts["write_reports"] = True
    if getattr(args, "no_critic", False):
        opts["run_critic"] = False
    if getattr(args, "model", None):
        opts["model"] = args.model
    if getattr(args, "new_doc", False):
        opts["new_document"] = True
    return opts


def _print_result(result):
    if result is None:
        print("TIMED OUT waiting for a result. Is the add-in running with the "
              "bridge started, and a Design document open?")
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


def main(argv=None):
    p = argparse.ArgumentParser(description="Drive the Woodworking AI Fusion add-in.")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="show whether the in-Fusion bridge is alive")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--no-machined", action="store_true", dest="no_machined")
    common.add_argument("--no-subassembly", action="store_true", dest="no_subassembly")
    common.add_argument("--reports", action="store_true",
                        help="also write cut list + drilling CSVs to the outbox")
    common.add_argument("--new-doc", action="store_true", dest="new_doc",
                        help="build into a fresh Fusion document, not the active one")
    common.add_argument("--wait", type=float, default=180.0, metavar="SECONDS",
                        help="seconds to wait for the result (default 180)")

    pi = sub.add_parser("import", parents=[common], help="build an existing spec")
    pi.add_argument("spec", help="path to a spec .json")

    pd = sub.add_parser("design", parents=[common], help="Claude designs from a prompt")
    pd.add_argument("prompt", help="plain-language description")
    pd.add_argument("--model", default=None, help="override the Claude model")
    pd.add_argument("--no-critic", action="store_true", dest="no_critic")

    pu = sub.add_parser("submit", parents=[common], help="submit a raw request .json")
    pu.add_argument("request", help="path to a request .json (envelope or bare spec)")

    args = p.parse_args(argv)

    if args.cmd == "status":
        st = bridge_status()
        print(json.dumps(st, indent=2))
        return 0 if st.get("alive") else 3

    if args.cmd == "import":
        with open(args.spec, "r", encoding="utf-8") as fh:
            spec = json.load(fh)
        request = {"spec": spec, "options": _options_from_args(args)}
    elif args.cmd == "design":
        request = {"prompt": args.prompt, "options": _options_from_args(args)}
    elif args.cmd == "submit":
        with open(args.request, "r", encoding="utf-8") as fh:
            request = json.load(fh)
    else:  # pragma: no cover
        p.error("unknown command")

    name = submit(request)
    print("submitted:", name, "-> waiting up to %.0fs" % args.wait, file=sys.stderr)
    return _print_result(wait_result(name, timeout=args.wait))


if __name__ == "__main__":
    raise SystemExit(main())

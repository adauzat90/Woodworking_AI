"""Watched-folder bridge for the Woodworking AI Fusion add-in.

Lets an external process -- a script or an agent -- drive the add-in **without
opening a network port**: drop a request ``.json`` into ``<drop>/inbox`` and the
add-in builds it in the active Design document, writing a ``<name>.result.json``
into ``<drop>/outbox``.

Fusion's API is single-threaded and **not** thread-safe, so the background
poller here never touches ``adsk`` -- it only detects a new file, atomically
claims it (moves it out of the inbox), and fires a **custom event**. Fusion
delivers that event on its main thread, where :class:`_BridgeEventHandler`
reads the request and does the actual build. This is the supported pattern for
periodic/background work in a Fusion add-in.

Drop-folder layout (root is ``$WOODAI_FUSION_DROP`` or ``~/.woodai/fusion_drop``)::

    <drop>/inbox/       # external caller writes requests here (atomic rename)
    <drop>/processing/  # a claimed request, mid-build
    <drop>/processed/   # requests that have been built
    <drop>/outbox/      # <name>.result.json (+ optional spec / CSV reports)
    <drop>/status.json  # written on start/stop
    <drop>/heartbeat.json   # refreshed every poll -- proof the watcher is alive
"""

import os
import json
import time
import threading
import traceback

import adsk.core

EVENT_ID = "WoodworkingAI_BridgeRequest"
POLL_SECONDS = 1.0


def default_drop_root():
    """The bridge drop directory: ``$WOODAI_FUSION_DROP`` or a home default."""
    env = os.environ.get("WOODAI_FUSION_DROP")
    if env and env.strip():
        return os.path.abspath(env.strip())
    return os.path.join(os.path.expanduser("~"), ".woodai", "fusion_drop")


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _safe_write_json(path, obj):
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=2)
        os.replace(tmp, path)
    except Exception:
        pass


class DropWatcher:
    """Polls ``inbox`` and hands each request to the main thread to build.

    *process_request* is ``callable(request_dict, name, outbox_dir) -> dict`` and
    is invoked on Fusion's main thread (so it may call ``adsk`` freely).
    """

    def __init__(self, app, ui, process_request, log=None):
        self._app = app
        self._ui = ui
        self._process = process_request
        self._log = log or (lambda _msg: None)
        self._thread = None
        self._stop = threading.Event()
        self._event = None
        self._handler = None
        self._built = 0

        self.root = default_drop_root()
        self.inbox = os.path.join(self.root, "inbox")
        self.processing = os.path.join(self.root, "processing")
        self.processed = os.path.join(self.root, "processed")
        self.outbox = os.path.join(self.root, "outbox")

    # -- lifecycle --------------------------------------------------------
    def start(self):
        for d in (self.inbox, self.processing, self.processed, self.outbox):
            os.makedirs(d, exist_ok=True)

        # Recover anything left mid-flight from a previous run.
        self._requeue_stale()

        # A fresh custom-event registration (clear any stale one first).
        try:
            self._app.unregisterCustomEvent(EVENT_ID)
        except Exception:
            pass
        self._event = self._app.registerCustomEvent(EVENT_ID)
        self._handler = _BridgeEventHandler(self)
        self._event.add(self._handler)

        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="WoodworkingAI-bridge", daemon=True
        )
        self._thread.start()
        self._write_status(True)
        self._log("bridge watching " + self.inbox)

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3.0)
            self._thread = None
        if self._event is not None and self._handler is not None:
            try:
                self._event.remove(self._handler)
            except Exception:
                pass
        try:
            self._app.unregisterCustomEvent(EVENT_ID)
        except Exception:
            pass
        self._event = None
        self._handler = None
        self._write_status(False)
        self._log("bridge stopped")

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    # -- background poller (NEVER calls adsk except fireCustomEvent) -------
    def _loop(self):
        while not self._stop.is_set():
            try:
                self._poll_once()
            except Exception:
                pass
            self._write_heartbeat()
            self._stop.wait(POLL_SECONDS)

    def _poll_once(self):
        try:
            names = sorted(os.listdir(self.inbox))
        except Exception:
            return
        for name in names:
            if not name.lower().endswith(".json"):
                continue
            src = os.path.join(self.inbox, name)
            if not os.path.isfile(src):
                continue
            claim = os.path.join(self.processing, name)
            try:
                # Atomic claim: removes it from the inbox so no double-build,
                # and dodges partially-written files if the caller renamed in.
                os.replace(src, claim)
            except Exception:
                continue
            # fireCustomEvent is the one adsk call allowed off the main thread.
            self._app.fireCustomEvent(EVENT_ID, claim)

    def _requeue_stale(self):
        """Move any ``processing/`` leftovers back to ``inbox`` to retry once."""
        try:
            for name in os.listdir(self.processing):
                src = os.path.join(self.processing, name)
                if os.path.isfile(src):
                    dst = os.path.join(self.inbox, name)
                    try:
                        os.replace(src, dst)
                    except Exception:
                        pass
        except Exception:
            pass

    # -- status files (so an external caller can see we're alive) ---------
    def _write_status(self, running):
        _safe_write_json(os.path.join(self.root, "status.json"), {
            "running": running,
            "pid": os.getpid(),
            "event": EVENT_ID,
            "inbox": self.inbox,
            "outbox": self.outbox,
            "poll_seconds": POLL_SECONDS,
            "time": _now(),
        })

    def _write_heartbeat(self):
        _safe_write_json(os.path.join(self.root, "heartbeat.json"), {
            "time": _now(),
            "running": True,
            "built": self._built,
        })


class _BridgeEventHandler(adsk.core.CustomEventHandler):
    """Delivered on Fusion's main thread -- safe to call ``adsk`` here."""

    def __init__(self, watcher):
        super().__init__()
        self._w = watcher

    def notify(self, args):
        w = self._w
        claim = args.additionalInfo          # path in processing/
        name = os.path.basename(claim)
        result = {"ok": False, "request": name, "time": _now()}
        try:
            with open(claim, "r", encoding="utf-8") as fh:
                request = json.load(fh)
            built = w._process(request, name, w.outbox)
            if isinstance(built, dict):
                result = built
            result.setdefault("ok", False)
            result.setdefault("request", name)
            result.setdefault("time", _now())
        except Exception:
            result["ok"] = False
            result["error"] = traceback.format_exc()

        stem = os.path.splitext(name)[0]
        _safe_write_json(
            os.path.join(w.outbox, stem + ".result.json"), result
        )
        # Retire the request (processing/ -> processed/), best effort.
        try:
            dest = os.path.join(w.processed, name)
            if os.path.exists(dest):
                os.remove(dest)
            os.replace(claim, dest)
        except Exception:
            pass
        w._built += 1
        if result.get("ok"):
            w._log("built %s -> %s" % (name, result.get("component", "?")))
        else:
            w._log("failed %s" % name)

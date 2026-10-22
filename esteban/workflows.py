"""Workflow runner.

Alfred workflows are directories containing an info.plist XML plist with
`objects` (typed nodes such as alfred.workflow.input.keyword,
alfred.workflow.input.scriptfilter, alfred.workflow.action.openurl) and
`connections` routing arguments between nodes (verified against a live
workflow on the analyzed system). Workflow script outputs follow Alfred's
JSON contract:

  {"items": [{"uid","title","subtitle","arg","quicklookurl",
              "mods": {"cmd": {"subtitle","arg"}}, "icon": {...}}]}

This clone executes the graph for the node types that matter on Linux and
keeps the keyword registry in the `triggers` table, exactly as Alfred does.
"""
from __future__ import annotations

import json
import plistlib
import subprocess
import time
from pathlib import Path

from . import store, clipboard

TRIGGER_TYPE = "alfred.workflow.trigger"
INPUT_TYPE = "alfred.workflow.input"
ACTION_TYPE = "alfred.workflow.action"
OUTPUT_TYPE = "alfred.workflow.output"


def load_workflows(cfg: dict, con) -> dict:
    wdir = Path(cfg["workflows"]["dir"]).expanduser()
    workflows = {}
    if not wdir.is_dir():
        return workflows
    for wf in sorted(wdir.iterdir()):
        info = wf / "info.plist"
        if not info.is_file():
            continue
        try:
            data = plistlib.loads(info.read_bytes())
        except Exception:
            continue
        if data.get("disabled"):
            continue
        workflows[str(wf)] = data
        for obj in data.get("objects", []):
            t = obj.get("type", "")
            if t in ("alfred.workflow.trigger.keyword", "alfred.workflow.input.keyword",
                     "alfred.workflow.trigger.fallback"):
                kw = obj.get("keyword", "")
                if kw:
                    con.execute("INSERT OR REPLACE INTO triggers (keyword, triggeruid, workflowuid) VALUES (?, ?, ?)",
                                (kw, obj.get("uid", ""), data.get("bundleid", wf.name)))
    con.commit()
    return workflows


def find_workflow(workflows: dict, query: str):
    first = query.split(maxsplit=1)
    if not first:
        return None
    kw = first[0]
    arg = first[1] if len(first) > 1 else ""
    for path, data in workflows.items():
        for obj in data.get("objects", []):
            if obj.get("type") in ("alfred.workflow.trigger.keyword",
                                   "alfred.workflow.input.keyword") and obj.get("keyword") == kw:
                return path, data, obj, arg
    return None


def run(workflows: dict, query: str, con, cfg: dict):
    hit = find_workflow(workflows, query)
    if not hit:
        return []
    wpath, data, obj, arg = hit
    store.add_knowledge(con, obj.get("uid", ""), query.split(maxsplit=1)[0])
    items = [{"uid": obj.get("uid", ""), "title": data.get("name", "Workflow"),
              "subtitle": data.get("description", ""), "arg": arg,
              "action": ("run", wpath, obj.get("uid", ""), arg)}]
    return items


def execute_graph(wpath: str, start_uid: str, arg: str, con, cfg: dict) -> list:
    """Follow connections from a keyword object, executing nodes in order."""
    data = plistlib.loads((Path(wpath) / "info.plist").read_bytes())
    objects = {o.get("uid"): o for o in data.get("objects", [])}
    connections = data.get("connections", {})
    current, value = objects.get(start_uid), arg
    results = []
    while current:
        t = current.get("type", "")
        if t == "alfred.workflow.input.scriptfilter":
            value = run_script_filter(wpath, current, value, con)
            results.extend(value)
        elif t in ("alfred.workflow.action.openurl",):
            url = current.get("url", value) or value
            from . import websearch
            websearch.open_url(url.format(query=value), con)
            results.append({"title": "Opened URL", "subtitle": url.format(query=value), "arg": value})
        elif t in ("alfred.workflow.output.clipboard", "alfred.workflow.action.openfile"):
            text = current.get("text", value) or value
            clipboard.copy_text(con, cfg, text)
            if current.get("autopaste"):
                try:
                    subprocess.run(["xdotool", "key", "ctrl+v"], timeout=2)
                except Exception:
                    pass
            results.append({"title": "Copied to clipboard", "subtitle": text[:120], "arg": value})
        elif t in ("alfred.workflow.output.notification",):
            notify(cfg, current.get("text", value) or value)
            results.append({"title": "Notification", "subtitle": value, "arg": value})
        elif t in ("alfred.workflow.action.script", "alfred.workflow.action.terminalcommand"):
            run_script(wpath, current, value)
            results.append({"title": "Script executed", "subtitle": value, "arg": value})
        nxt = connections.get(current.get("uid"), [])
        if not nxt:
            break
        current = objects.get(nxt[0].get("destinationuid"))
    return results


def run_script_filter(wpath: str, obj: dict, query: str, con) -> list:
    script = obj.get("script", "")
    scriptfile = obj.get("scriptfile")
    payload = json.dumps({"items": []})
    if scriptfile:
        target = Path(wpath) / scriptfile
        try:
            out = subprocess.run([str(target), query], capture_output=True, text=True,
                                 timeout=10, cwd=wpath)
            payload = out.stdout or payload
        except Exception:
            return []
    elif script:
        try:
            out = subprocess.run(["sh", "-c", script.replace("{query}", query)],
                                 capture_output=True, text=True, timeout=10, cwd=wpath)
            payload = out.stdout or payload
        except Exception:
            return []
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return []
    items = []
    for it in data.get("items", []):
        action = it.get("arg") or it.get("title")
        items.append({"uid": it.get("uid", ""), "title": it.get("title", ""),
                      "subtitle": it.get("subtitle", ""), "arg": action,
                      "quicklookurl": it.get("quicklookurl", ""),
                      "mods": it.get("mods", {}), "action": ("openurl", action)
                      if str(action).startswith("http") else ("open", action)})
    return items


def run_script(wpath: str, obj: dict, arg: str) -> None:
    script = obj.get("script", "")
    scriptfile = obj.get("scriptfile")
    if scriptfile:
        subprocess.Popen([str(Path(wpath) / scriptfile), arg], start_new_session=True, cwd=wpath)
    elif script:
        subprocess.Popen(["sh", "-c", script.replace("{query}", arg)], start_new_session=True, cwd=wpath)


def notify(cfg: dict, text: str) -> None:
    try:
        subprocess.run(["notify-send", "esteban", text], timeout=5)
    except Exception:
        pass

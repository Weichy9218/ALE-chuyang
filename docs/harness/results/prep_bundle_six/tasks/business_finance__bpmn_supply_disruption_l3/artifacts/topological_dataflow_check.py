#!/usr/bin/env python3
"""Read-only BPMN check for the task's static topological in_*/out_* rule.

Reports each in_* property on user tasks new relative to --original and whether a
matching out_* property is on a user-task predecessor that is itself reachable
from a start event. XML is never modified. Exit 0 means the bounded check found
no unmatched inputs; exit 1 means findings; exit 2 means parse/usage error.
"""
import argparse, json, sys
from collections import defaultdict, deque
import xml.etree.ElementTree as ET

BPMN = "http://www.omg.org/spec/BPMN/20100524/MODEL"
FLOWABLE = "http://flowable.org/bpmn"
Q = lambda ns, tag: "{%s}%s" % (ns, tag)

def load(path):
    root = ET.parse(path).getroot()
    processes = root.findall(".//" + Q(BPMN, "process"))
    if not processes:
        raise ValueError("no BPMN process found")
    return root, processes

def task_props(task):
    ans = []
    for p in task.findall(".//" + Q(FLOWABLE, "formProperty")):
        pid = p.get("id")
        if pid:
            ans.append(pid)
    return ans

def graph(process):
    nodes = {}
    for e in process.iter():
        eid = e.get("id")
        if eid:
            nodes[eid] = e
    adj = defaultdict(set)
    for sf in process.findall(".//" + Q(BPMN, "sequenceFlow")):
        s, t = sf.get("sourceRef"), sf.get("targetRef")
        if s and t:
            adj[s].add(t)
    starts = [e.get("id") for e in process.findall(".//" + Q(BPMN, "startEvent")) if e.get("id")]
    return nodes, adj, starts

def reachable(adj, seeds, blocked=None):
    seen, q = set(), deque(seeds)
    while q:
        x = q.popleft()
        if x in seen or x == blocked:
            continue
        seen.add(x)
        q.extend(adj.get(x, ()))
    return seen

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bpmn", help="modified BPMN XML")
    ap.add_argument("--original", required=True, help="original BPMN used to identify new user-task IDs")
    a = ap.parse_args()
    try:
        _, orig_ps = load(a.original)
        original_task_ids = {t.get("id") for p in orig_ps for t in p.findall(".//" + Q(BPMN,"userTask")) if t.get("id")}
        _, processes = load(a.bpmn)
        reports, bad = [], 0
        for process in processes:
            nodes, adj, starts = graph(process)
            from_start = reachable(adj, starts)
            tasks = [t for t in process.findall(".//" + Q(BPMN,"userTask")) if t.get("id")]
            producers = defaultdict(list)
            for t in tasks:
                for prop in task_props(t):
                    if prop.startswith("out_"):
                        producers[prop[4:]].append(t.get("id"))
            for consumer in tasks:
                cid = consumer.get("id")
                if cid in original_task_ids:
                    continue
                for prop in task_props(consumer):
                    if not prop.startswith("in_"):
                        continue
                    key = prop[3:]
                    candidates = producers.get(key, [])
                    matching_predecessors = []
                    for producer in candidates:
                        if producer == cid or producer not in from_start:
                            continue
                        if cid in reachable(adj, [producer]):
                            matching_predecessors.append(producer)
                    ok = bool(matching_predecessors)
                    bad += int(not ok)
                    reports.append({
                        "process_id": process.get("id"), "consumer_task": cid,
                        "input_property": prop, "required_output_property": "out_" + key,
                        "matching_topological_predecessors": sorted(matching_predecessors),
                        "all_matching_producer_ids": sorted(candidates), "ok": ok
                    })
        print(json.dumps({
            "scope": "in_ properties on userTask IDs absent from --original",
            "new_task_inputs_checked": len(reports), "unmatched_count": bad,
            "findings": reports
        }, indent=2, sort_keys=True))
        return 1 if bad else 0
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        return 2
if __name__ == "__main__":
    sys.exit(main())

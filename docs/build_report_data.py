#!/usr/bin/env python3
"""Merge original + rerun13 ALE runs (latest-per-task), emit CSV + table JSON + aggregate stats.
Re-run any time as the rerun progresses. Output: ALE_tasks.csv, _tasktable.json, printed stats."""
import json, glob, collections, csv, os

BASE = "/home/dataset-local/zmh/ALE_TEST/agents-last-exam/.logs/ale"
ORIG = BASE + "/local_docker_pi_qwen35_cli/pi/qwen3-5-397b-a17b"
RERUN = BASE + "/local_docker_pi_qwen35_cli_rerun13/pi/qwen3-5-397b-a17b"
OUT = "/home/dataset-local/wcy/ALE-Test/docs"
RERUN_SET = set(l.strip() for l in open("/home/dataset-local/zmh/ALE_TEST/agents-last-exam/selected_tasks/pi_cli_dead13.txt") if l.strip())

def latest(runroot, taskdir):
    cands = sorted(glob.glob(runroot + "/" + taskdir + "/v0/*/run.json"))
    return cands[-1] if cands else None

def toolcounts(rjpath):
    tj = rjpath.rsplit("/",1)[0] + "/trajectory.json"
    tc = collections.Counter()
    try:
        t = json.load(open(tj))
        for s in t.get("steps", []):
            for c in (s.get("tool_calls") or []):
                tc[c.get("name","?")] += 1
    except Exception:
        pass
    return tc

def parse(rjpath, task):
    d = json.load(open(rjpath)); u = d.get("usage",{}) or {}
    tc = toolcounts(rjpath)
    intok = u.get("total_input_tokens",0) or 0
    return {
        "id": task, "dom": task.split("/")[0],
        "st": d.get("status"), "sc": d.get("score"),
        "steps": u.get("total_steps",0) or 0,
        "in": intok, "out": u.get("total_output_tokens",0) or 0,
        "dur": round((d.get("timings",{}) or {}).get("duration_s",0) or 0),
        "b": tc.get("bash",0), "r": tc.get("read",0), "w": tc.get("write",0),
        "e": tc.get("edit",0), "g": tc.get("grep",0)+tc.get("find",0)+tc.get("ls",0),
        "dead": intok == 0, "src": "orig",
    }

# all tasks from original run
rows = {}
for rj in glob.glob(ORIG + "/*/v0/*/run.json"):
    taskdir = rj[len(ORIG)+1:].split("/")[0]
    task = taskdir.replace("__","/",1)
    if task not in rows or rj > rows[task]["_rj"]:
        r = parse(rj, task); r["_rj"] = rj; rows[task] = r

# overlay rerun results where available (latest, and only if non-dead OR nothing better)
rerun_status = {}
for task in RERUN_SET:
    taskdir = task.replace("/","__",1)
    rj = latest(RERUN, taskdir)
    if rj:
        r = parse(rj, task); r["src"] = "rerun"
        # prefer rerun over orig for these tasks (it's the fresh attempt)
        rows[task] = r
        rerun_status[task] = "done" if not r["dead"] else "infra_fail"
    else:
        rerun_status[task] = "pending"
        if task in rows: rows[task]["rerunning"] = True

data = list(rows.values())
for r in data: r.pop("_rj", None)
data.sort(key=lambda x: -(x["sc"] if x["sc"] is not None and not x["dead"] else -1))

# CSV
with open(OUT+"/ALE_tasks.csv","w",newline="") as f:
    w = csv.writer(f)
    w.writerow(["id","domain","status","score","steps","bash","read","write","edit","other_tools","input_tokens","output_tokens","duration_s","note"])
    for r in data:
        note = "" if not r["dead"] else ("重跑中" if r.get("rerunning") else "本机资源不足(需16CPU/60GB)")
        w.writerow([r["id"],r["dom"],r["st"],
                    "" if r["sc"] is None else round(r["sc"],4),
                    r["steps"],r["b"],r["r"],r["w"],r["e"],r["g"],r["in"],r["out"],r["dur"],note])

# table JSON (compact)
json.dump(data, open(OUT+"/_tasktable.json","w"), ensure_ascii=False)

# aggregate stats
real = [r for r in data if not r["dead"]]
scored = [r for r in real if r["sc"] is not None]
def bucket(s):
    if s>=0.999: return "1.0"
    if s>=0.5: return "0.5-0.99"
    if s>0: return "0-0.5"
    return "0.0"
st = collections.Counter(r["st"] for r in real)
bk = collections.Counter(bucket(r["sc"]) for r in scored)
dom = collections.defaultdict(list)
for r in scored: dom[r["dom"]].append(r["sc"])
print("=== MERGED STATS ===")
print("total tasks:", len(data), "| dead(0tok):", sum(r["dead"] for r in data), "| real attempts:", len(real), "| scored:", len(scored))
print("mean over scored: %.3f" % (sum(r["sc"] for r in scored)/len(scored)))
print("status(real):", dict(st))
print("buckets(scored):", dict(bk))
print("rerun status:", collections.Counter(rerun_status.values()))
print("--- domain means (scored) ---")
for d in sorted(dom, key=lambda k:-sum(dom[k])/len(dom[k])):
    v=dom[d]; print("  %-18s %.3f n=%d" % (d, sum(v)/len(v), len(v)))

# ---- static table rows (no JS dependency) ----
def tok(n):
    if n>=1_000_000: return "%.2fM"%(n/1e6)
    if n>=1000: return "%dk"%round(n/1000)
    return str(n)
def score_cell(r):
    if r["dead"]:
        return '<span style="color:var(--muted)">%s</span>' % ("重跑中" if r.get("rerunning") else "资源不足")
    if r["sc"] is None:
        return '<span style="color:var(--critical)">崩溃</span>'
    s=r["sc"]; c = "var(--good)" if s>=0.999 else ("var(--blue)" if s>=0.5 else ("var(--ink2)" if s>0 else "var(--critical)"))
    return '<b style="color:%s">%.2f</b>' % (c, s)
STC={"completed":"var(--good)","timeout":"var(--warning)","failed":"var(--critical)"}
rowhtml=[]
for r in data:
    dim = ' style="opacity:.5"' if r["dead"] else ''
    ids = r["id"].split("/",1)[1] if "/" in r["id"] else r["id"]
    stc = STC.get(r["st"],"var(--muted)")
    rowhtml.append(
      '<tr%s><td title="%s" class="tid">%s</td><td class="tdom">%s</td>'
      '<td class="num">%s</td><td><span style="color:%s">%s</span></td>'
      '<td class="num">%d</td><td class="num">%d</td><td class="num">%d</td>'
      '<td class="num">%d</td><td class="num">%d</td><td class="num">%s</td><td class="num">%s</td></tr>'
      % (dim, r["id"], ids, r["dom"], score_cell(r), stc, r["st"] or "?",
         r["steps"], r["b"], r["r"], r["w"], r["e"], tok(r["in"]), tok(r["out"]))
    )
open(OUT+"/_taskrows.html","w").write("\n".join(rowhtml))

# ---- domain chart data (JS literal for the bar chart) ----
DOM_ZH={"legal":"法律","business_finance":"商业金融","computing_math":"计算数学",
"life_sciences":"生命科学","health_medicine":"健康医疗","education_info":"教育信息",
"engineering":"工程","physical_sciences":"物理科学","social_sciences":"社会科学",
"transport_safety":"交通安全","psychology_neuro":"心理神经","other":"其他"}
dl=[]
for d in sorted(dom, key=lambda k:-sum(dom[k])/len(dom[k])):
    v=dom[d]; dl.append([d, DOM_ZH.get(d,d), round(sum(v)/len(v),3), len(v)])
open(OUT+"/_domains.json","w").write(json.dumps(dl,ensure_ascii=False))
print("wrote _taskrows.html (%d rows), _domains.json (%d domains)" % (len(rowhtml), len(dl)))

# ---- inject into template -> final self-contained HTML ----
tpl_path = OUT + "/ALE_report.template.html"
if os.path.exists(tpl_path):
    tpl = open(tpl_path, encoding="utf-8").read()
    rows = open(OUT + "/_taskrows.html", encoding="utf-8").read()
    doms = open(OUT + "/_domains.json", encoding="utf-8").read().strip()
    tpl = tpl.replace("<!--__ROWS__-->", rows)
    ds = "/*__DOMAINS__*/"; de = "/*__END__*/"
    i = tpl.index(ds); j = tpl.index(de, i) + len(de)
    tpl = tpl[:i] + ds + doms + de + tpl[j:]
    open(OUT + "/ALE_report.html", "w", encoding="utf-8").write(tpl)
    print("built ALE_report.html: %d bytes, %d table rows injected" % (len(tpl), rows.count("<tr")))
else:
    print("no template found at", tpl_path)

#!/usr/bin/env python3
"""Read-only integrity index for the staged FluSight historical CSV."""
import argparse, csv, datetime as dt, hashlib, json
from collections import Counter, defaultdict

ap = argparse.ArgumentParser()
ap.add_argument("history_csv")
a = ap.parse_args()
raw = open(a.history_csv, "rb").read()
text = raw.decode("utf-8-sig").splitlines()
rows = list(csv.DictReader(text))
required = {"as_of", "date", "location", "location_name", "value", "weekly_rate"}
if not rows or not required.issubset(rows[0]):
    raise SystemExit("missing required history columns")
by = defaultdict(list)
keys = Counter()
for r in rows:
    try: d = dt.date.fromisoformat(r["date"])
    except ValueError: raise SystemExit("invalid date: " + repr(r["date"]))
    by[r["location"]].append((d, r))
    keys[(r["location"], r["date"])] += 1

def runs(ds):
    ds = sorted(ds)
    out = []
    for d in ds:
        if not out or (d-out[-1][1]).days != 7: out.append([d,d])
        else: out[-1][1] = d
    return [{"start":str(x),"end":str(y),"weeks":((y-x).days//7)+1} for x,y in out]

locations = []
for loc in sorted(by):
    rs = sorted(by[loc])
    dates = [d for d,_ in rs]
    missing_value = [d for d,r in rs if r["value"].strip() == ""]
    missing_rate = [d for d,r in rs if r["weekly_rate"].strip() == ""]
    expected = set()
    if dates:
        d = dates[0]
        while d <= dates[-1]: expected.add(d); d += dt.timedelta(days=7)
    absent = expected - set(dates)
    locations.append({
      "location":loc, "location_name":rs[0][1]["location_name"],
      "row_count":len(rs), "first_date":str(dates[0]), "last_date":str(dates[-1]),
      "blank_value_count":len(missing_value), "blank_value_runs":runs(missing_value),
      "blank_weekly_rate_count":len(missing_rate), "absent_week_count":len(absent),
      "absent_week_runs":runs(absent)
    })
out = {
 "sha256":hashlib.sha256(raw).hexdigest(), "row_count":len(rows),
 "location_count":len(by),
 "duplicate_location_date_keys":sum(n-1 for n in keys.values() if n>1),
 "as_of_values":sorted({r["as_of"] for r in rows}),
 "locations_with_blank_values":[x for x in locations if x["blank_value_count"]],
 "locations_with_absent_weeks":[x for x in locations if x["absent_week_count"]],
 "all_location_summaries":locations
}
print(json.dumps(out, indent=2, sort_keys=True))

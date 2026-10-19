import json
import argparse
import os
from collections import defaultdict
def build(year, root="."):
    src_path = os.path.join(root, "data", "seasons", str(year), "transactions.json")
    with open(src_path) as f:
        raw = json.load(f)
    by_month = defaultdict(list)
    types_by_month = defaultdict(dict)
    for t in raw["transactions"]:
        date = t.get("date")
        if not date:
            continue
        month = date[5:7]
        person = t.get("person") or {}
        from_team = t.get("fromTeam") or {}
        to_team = t.get("toTeam") or {}
        row = [
            date,
            t.get("typeCode"),
            person.get("id"),
            person.get("fullName"),
            from_team.get("id"),
            to_team.get("id"),
            t.get("description"),
        ]
        by_month[month].append(row)
        if t.get("typeCode"):
            types_by_month[month][t["typeCode"]] = t.get("typeDesc")
    out_dir = os.path.join(root, "data", "seasons", str(year), "transactions")
    os.makedirs(out_dir, exist_ok=True)
    for month in [f"{m:02d}" for m in range(1, 13)]:
        rows = sorted(by_month.get(month, []), key=lambda r: r[0])
        payload = {
            "v": 1,
            "year": year,
            "month": month,
            "types": dict(sorted(types_by_month.get(month, {}).items())),
            "tx": rows,
        }
        out_path = os.path.join(out_dir, f"{month}.json")
        with open(out_path, "w") as f:
            json.dump(payload, f, separators=(",", ":"))
        print(f"{out_path}: {len(rows)} tx")
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--root", default=".")
    args = ap.parse_args()
    build(args.year, args.root)

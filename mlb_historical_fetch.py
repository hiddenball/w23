import argparse
import csv
import json
import time
import sys
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
BASE = "https://statsapi.mlb.com/api/v1"
BASE_1_1 = "https://statsapi.mlb.com/api/v1.1"
SPORT_ID = 1
REQUEST_DELAY = 0.6
MAX_RETRIES = 4
RETRY_BACKOFF = 2.0
START_YEAR = 1980
END_YEAR = 2025
DATA_DIR = Path("data")
COVERAGE_SUFFIX = ""
def fetch_json(url, retries=MAX_RETRIES):
    last_err = None
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": "personal-site-ingest/1.0"})
            with urlopen(req, timeout=30) as resp:
                raw = resp.read()
            time.sleep(REQUEST_DELAY)
            if not raw:
                return None
            return json.loads(raw)
        except HTTPError as e:
            if e.code == 404:
                return None
            last_err = e
        except URLError as e:
            last_err = e
        except json.JSONDecodeError as e:
            last_err = e
        wait = RETRY_BACKOFF ** attempt
        time.sleep(wait)
    return None
def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
def is_meaningfully_empty(data):
    if data is None:
        return True
    if isinstance(data, dict):
        if not data:
            return True
        if set(data.keys()) <= {"copyright"}:
            return True
    if isinstance(data, list) and not data:
        return True
    return False
class Coverage:
    def __init__(self):
        self.rows = {}
    def record(self, year, field, had_data: bool):
        key = (year, field)
        row = self.rows.setdefault(key, {"total": 0, "nonempty": 0})
        row["total"] += 1
        if had_data:
            row["nonempty"] += 1
    def write(self):
        out = []
        for (year, field), row in sorted(self.rows.items()):
            pct = (row["nonempty"] / row["total"] * 100) if row["total"] else 0.0
            out.append({
                "year": year,
                "field": field,
                "total_checked": row["total"],
                "had_data": row["nonempty"],
                "pct_available": round(pct, 1),
            })
        json_path = DATA_DIR / f"coverage_report{COVERAGE_SUFFIX}.json"
        csv_path = DATA_DIR / f"coverage_report{COVERAGE_SUFFIX}.csv"
        save_json(json_path, out)
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["year", "field", "total_checked", "had_data", "pct_available"])
            w.writeheader()
            w.writerows(out)
def get_season_game_pks(year, limit=None):
    url = (f"{BASE}/schedule?sportId={SPORT_ID}&season={year}"
           f"&gameType=R,F,D,L,W,C,P,A"
           f"&fields=dates,date,games,gamePk,status,detailedState")
    data = fetch_json(url)
    pks = []
    if data:
        for date_entry in data.get("dates", []):
            for game in date_entry.get("games", []):
                pks.append(game["gamePk"])
    if limit:
        pks = pks[:limit]
    return pks
def fetch_game_data(year, game_pk, skip_existing, coverage, include_feed=False):
    game_dir = DATA_DIR / "seasons" / str(year) / "games" / str(game_pk)
    targets = [
        ("linescore", f"{BASE}/game/{game_pk}/linescore", game_dir / "linescore.json"),
        ("boxscore", f"{BASE}/game/{game_pk}/boxscore", game_dir / "boxscore.json"),
        ("playbyplay", f"{BASE}/game/{game_pk}/playByPlay", game_dir / "playbyplay.json"),
        ("winprobability", f"{BASE}/game/{game_pk}/winProbability", game_dir / "winprobability.json"),
    ]
    if include_feed:
        targets.append(
            ("feed", f"{BASE_1_1}/game/{game_pk}/feed/live", game_dir / "feed.json")
        )
    for field, url, path in targets:
        if skip_existing and path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
                coverage.record(year, field, not is_meaningfully_empty(existing))
            except Exception:
                pass
            continue
        data = fetch_json(url)
        empty = is_meaningfully_empty(data)
        coverage.record(year, field, not empty)
        save_json(path, data if data is not None else {})
def fetch_team_ids():
    url = f"{BASE}/teams?sportId={SPORT_ID}"
    data = fetch_json(url)
    if not data:
        return []
    return [t["id"] for t in data.get("teams", [])]
def fetch_rosters(year, team_ids, skip_existing, coverage):
    for team_id in team_ids:
        path = DATA_DIR / "seasons" / str(year) / "rosters" / f"{team_id}.json"
        if skip_existing and path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
                coverage.record(year, "roster", not is_meaningfully_empty(existing))
            except Exception:
                pass
            continue
        url = f"{BASE}/teams/{team_id}/roster?rosterType=fullSeason&season={year}"
        data = fetch_json(url)
        empty = is_meaningfully_empty(data)
        coverage.record(year, "roster", not empty)
        save_json(path, data if data is not None else {})
def fetch_draft(year, skip_existing, coverage):
    path = DATA_DIR / "draft" / f"{year}.json"
    if skip_existing and path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            coverage.record(year, "draft", not is_meaningfully_empty(existing))
        except Exception:
            pass
        return
    url = f"{BASE}/draft/{year}"
    data = fetch_json(url)
    empty = is_meaningfully_empty(data)
    coverage.record(year, "draft", not empty)
    save_json(path, data if data is not None else {})
def fetch_transactions(year, skip_existing, coverage):
    path = DATA_DIR / "seasons" / str(year) / "transactions.json"
    if skip_existing and path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            coverage.record(year, "transactions", not is_meaningfully_empty(existing))
        except Exception:
            pass
        return
    url = f"{BASE}/transactions?startDate={year}-01-01&endDate={year}-12-31&sportId={SPORT_ID}"
    data = fetch_json(url)
    empty = is_meaningfully_empty(data)
    coverage.record(year, "transactions", not empty)
    save_json(path, data if data is not None else {})
def fetch_standings_splits(year, skip_existing, coverage):
    path = DATA_DIR / "seasons" / str(year) / "standings-splits.json"
    if skip_existing and path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            coverage.record(year, "standings_splits", not is_meaningfully_empty(existing))
        except Exception:
            pass
        return
    url = (f"{BASE}/standings?leagueId=103,104&season={year}"
           f"&standingsTypes=regularSeason&hydrate=team")
    data = fetch_json(url)
    empty = is_meaningfully_empty(data)
    coverage.record(year, "standings_splits", not empty)
    save_json(path, data if data is not None else {})
def get_date_game_pks(date_str):
    url = (f"{BASE}/schedule?sportId={SPORT_ID}&date={date_str}"
           f"&fields=dates,date,games,gamePk,status,detailedState")
    data = fetch_json(url)
    pks = []
    if data:
        for date_entry in data.get("dates", []):
            for game in date_entry.get("games", []):
                pks.append(game["gamePk"])
    return pks
def get_date_games_with_status(date_str):
    url = (f"{BASE}/schedule?sportId={SPORT_ID}&date={date_str}"
           f"&fields=dates,date,games,gamePk,status,abstractGameState,detailedState")
    data = fetch_json(url)
    games = []
    if data:
        for date_entry in data.get("dates", []):
            for game in date_entry.get("games", []):
                status = game.get("status", {})
                games.append({
                    "gamePk": game["gamePk"],
                    "abstractGameState": status.get("abstractGameState"),
                    "detailedState": status.get("detailedState"),
                })
    return games
def poll_live_games(coverage):
    today = time.strftime("%Y-%m-%d", time.gmtime())
    games = get_date_games_with_status(today)
    live = [g for g in games if g["abstractGameState"] == "Live"]
    year = int(today[:4])
    for g in live:
        fetch_game_data(year, g["gamePk"], skip_existing=False, coverage=coverage, include_feed=True)
def fetch_single_date(date_str, coverage, games_only=False):
    year = int(date_str[:4])
    if not games_only:
        fetch_draft(year, skip_existing=False, coverage=coverage)
        fetch_transactions(year, skip_existing=False, coverage=coverage)
        fetch_standings_splits(year, skip_existing=False, coverage=coverage)
        team_ids = fetch_team_ids()
        fetch_rosters(year, team_ids, skip_existing=False, coverage=coverage)
    game_pks = get_date_game_pks(date_str)
    for pk in game_pks:
        fetch_game_data(year, pk, skip_existing=False, coverage=coverage)
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=START_YEAR)
    parser.add_argument("--end", type=int, default=END_YEAR)
    parser.add_argument("--only-years", type=int, nargs="*", default=None)
    parser.add_argument("--date", type=str, default=None)
    parser.add_argument("--games-only", action="store_true", default=False)
    parser.add_argument("--live-poll", action="store_true", default=False)
    parser.add_argument("--games-per-year-limit", type=int, default=None)
    parser.add_argument("--skip-existing", action="store_true", default=True)
    parser.add_argument("--no-skip-existing", dest="skip_existing", action="store_false")
    parser.add_argument("--output-dir", type=str, default="data")
    args = parser.parse_args()
    global DATA_DIR, COVERAGE_SUFFIX
    DATA_DIR = Path(args.output_dir)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if args.live_poll:
        COVERAGE_SUFFIX = "_live"
        coverage = Coverage()
        poll_live_games(coverage)
        coverage.write()
        return
    if args.date:
        COVERAGE_SUFFIX = f"_{args.date}"
        coverage = Coverage()
        fetch_single_date(args.date, coverage, games_only=args.games_only)
        coverage.write()
        return
    years = args.only_years if args.only_years else list(range(args.start, args.end + 1))
    COVERAGE_SUFFIX = f"_{min(years)}-{max(years)}"
    coverage = Coverage()
    team_ids = fetch_team_ids()
    for year in years:
        fetch_draft(year, args.skip_existing, coverage)
        fetch_transactions(year, args.skip_existing, coverage)
        fetch_standings_splits(year, args.skip_existing, coverage)
        fetch_rosters(year, team_ids, args.skip_existing, coverage)
        game_pks = get_season_game_pks(year, limit=args.games_per_year_limit)
        for i, pk in enumerate(game_pks, 1):
            fetch_game_data(year, pk, args.skip_existing, coverage)
        coverage.write()
    coverage.write()
if __name__ == "__main__":
    main()

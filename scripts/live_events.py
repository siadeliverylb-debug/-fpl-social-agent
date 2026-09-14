"""Poll live fixtures for the current gameweek to detect goals, assists,
cards, penalties, kickoff and full-time -- for immediate (non-approval)
posting since they're only worth posting while still live."""

import requests

BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
FIXTURES_URL = "https://fantasy.premierleague.com/api/fixtures/"

# stat identifier (from the fixtures API) -> story type
STAT_TYPES = {
    "goals_scored": "goal",
    "assists": "assist",
    "yellow_cards": "yellow_card",
    "red_cards": "red_card",
    "penalties_missed": "penalty_miss",
    "penalties_saved": "penalty_save",
    "own_goals": "own_goal",
}


def _fetch_json(url):
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    return resp.json()


def fetch_live_events(state):
    """Mutates state['live'] in place (fixture start/finish flags + per-stat
    counters) and returns the list of new story dicts since the last poll."""
    bootstrap = _fetch_json(BOOTSTRAP_URL)
    current_event = next((e["id"] for e in bootstrap["events"] if e.get("is_current")), None)
    if current_event is None:
        return []

    players = {p["id"]: {"name": p["web_name"], "team": p["team"]} for p in bootstrap["elements"]}
    teams = {t["id"]: t["short_name"] for t in bootstrap["teams"]}

    fixtures = _fetch_json(f"{FIXTURES_URL}?event={current_event}")

    live = state.setdefault("live", {"fixtures": {}, "stats": {}})
    stories = []

    for fx in fixtures:
        fid = str(fx["id"])
        is_new_fixture = fid not in live["fixtures"]
        prev_fx = live["fixtures"].get(fid, {"started": False, "finished": False})
        home = teams.get(fx["team_h"], "?")
        away = teams.get(fx["team_a"], "?")

        if is_new_fixture:
            # First time seeing this fixture -- establish a baseline (current
            # started/finished flags and every stat count so far) without
            # emitting stories for it, the same way a first-ever scan doesn't
            # treat the whole season's history as breaking news. Otherwise a
            # cold state.json (or this feature's very first run) would replay
            # every goal/card from every in-progress-or-finished match.
            for stat in fx.get("stats", []):
                for side in ("h", "a"):
                    for entry in stat.get(side, []):
                        stat_key = f"{fid}:{entry['element']}:{stat['identifier']}"
                        live["stats"][stat_key] = entry["value"]
            live["fixtures"][fid] = {"started": fx["started"], "finished": fx["finished"]}
            continue

        if fx["started"] and not prev_fx["started"]:
            stories.append({
                "type": "kickoff",
                "key": f"kickoff:{fid}",
                "home": home,
                "away": away,
            })

        if not fx["started"]:
            live["fixtures"][fid] = {"started": fx["started"], "finished": fx["finished"]}
            continue

        score = f"{fx['team_h_score']}-{fx['team_a_score']}"

        # Goals and assists are buffered per side instead of appended straight
        # to `stories`, so a goal can be paired with its assist (if exactly
        # one of each landed on the same side this poll) into a single post.
        new_goals = {"h": [], "a": []}
        new_assists = {"h": [], "a": []}

        for stat in fx.get("stats", []):
            story_type = STAT_TYPES.get(stat["identifier"])
            if story_type is None:
                continue
            for side in ("h", "a"):
                for entry in stat.get(side, []):
                    pid = entry["element"]
                    value = entry["value"]
                    stat_key = f"{fid}:{pid}:{stat['identifier']}"
                    prev_value = live["stats"].get(stat_key, 0)
                    if value > prev_value:
                        player = players.get(pid, {"name": f"Player {pid}", "team": None})
                        player_team = teams.get(player["team"], "?")
                        for i in range(prev_value, value):
                            event = {
                                "type": story_type,
                                "key": f"{story_type}:{fid}:{pid}:{i + 1}",
                                "player": player["name"],
                                "team": player_team,
                                "home": home,
                                "away": away,
                                "score": score,
                            }
                            if story_type == "goal":
                                new_goals[side].append(event)
                            elif story_type == "assist":
                                new_assists[side].append(event)
                            else:
                                stories.append(event)
                    live["stats"][stat_key] = value

        for side in ("h", "a"):
            goals = new_goals[side]
            assists = new_assists[side]
            if len(goals) == 1 and len(assists) == 1:
                goals[0]["assisted_by"] = assists[0]["player"]
                stories.append(goals[0])
            else:
                stories.extend(goals)
                stories.extend(assists)

        if fx["finished"] and not prev_fx["finished"]:
            stories.append({
                "type": "full_time",
                "key": f"fulltime:{fid}",
                "home": home,
                "away": away,
                "score": score,
            })

        live["fixtures"][fid] = {"started": fx["started"], "finished": fx["finished"]}

    return stories

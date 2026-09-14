"""Poll live fixtures for the current gameweek to detect goals, assists,
cards, penalties, kickoff and full-time -- for immediate (non-approval)
posting since they're only worth posting while still live."""

import requests

BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
FIXTURES_URL = "https://fantasy.premierleague.com/api/fixtures/"
EVENT_LIVE_URL = "https://fantasy.premierleague.com/api/event/{}/live/"

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
    fixture_minute = {str(fx["id"]): fx.get("minutes") for fx in fixtures}
    fixture_active = {str(fx["id"]): fx["started"] and not fx.get("finished_provisional") for fx in fixtures}

    # FPL doesn't expose a "substitutions" stat on the fixtures endpoint at
    # all -- no event, no explicit "off X, on Y" pairing. The closest signal
    # is this per-gameweek live-stats endpoint: a player who didn't start
    # (starts=0) but has accumulated minutes came on at some point, and a
    # player who did start (starts=1) but whose minutes have stalled well
    # behind the fixture's current match clock has come off. Pairing an
    # on/off within the same poll for the same team is a best-effort guess,
    # not a guarantee.
    OFF_MINUTE_BUFFER = 3
    event_live = _fetch_json(EVENT_LIVE_URL.format(current_event))
    subs_on_by_fixture = {}
    subs_off_by_fixture = {}
    for el in event_live.get("elements", []):
        minutes = el["stats"].get("minutes", 0)
        starts = el["stats"].get("starts", 0)
        for ex in el.get("explain", []):
            fid_key = str(ex["fixture"])
            if not starts and minutes > 0:
                subs_on_by_fixture.setdefault(fid_key, []).append(el["id"])
            elif (
                starts
                and fixture_active.get(fid_key)
                and fixture_minute.get(fid_key) is not None
                and minutes < fixture_minute[fid_key] - OFF_MINUTE_BUFFER
            ):
                subs_off_by_fixture.setdefault(fid_key, []).append(el["id"])

    live = state.setdefault("live", {"fixtures": {}, "stats": {}})
    live.setdefault("posted_score", {})
    live.setdefault("last_goal", {})
    live.setdefault("subs_seen", {})
    live.setdefault("subs_off_seen", {})
    live.setdefault("subs_baselined", {})
    live.setdefault("bonus_posted", {})
    stories = []

    for fx in fixtures:
        fid = str(fx["id"])
        is_new_fixture = fid not in live["fixtures"]
        prev_fx = live["fixtures"].get(fid, {"started": False, "finished_provisional": False})
        home = teams.get(fx["team_h"], "?")
        away = teams.get(fx["team_a"], "?")

        # Substitutions get their own baseline flag, independent of
        # is_new_fixture: a fixture that was already being tracked (for
        # goals/cards) before this feature shipped would otherwise have
        # every substitution already made in it -- potentially the whole
        # bench -- treated as breaking news the moment this code first runs
        # against it, instead of only genuinely new subs from here on.
        if fid not in live["subs_baselined"]:
            for pid in subs_on_by_fixture.get(fid, []):
                live["subs_seen"][f"{fid}:{pid}"] = True
            for pid in subs_off_by_fixture.get(fid, []):
                live["subs_off_seen"][f"{fid}:{pid}"] = True
            live["subs_baselined"][fid] = True

        if is_new_fixture:
            # First time seeing this fixture -- establish a baseline (current
            # started/finished flags, every stat count so far, and a 0-0
            # posted-score tally) without emitting stories for it, the same
            # way a first-ever scan doesn't treat the whole season's history
            # as breaking news. Otherwise a cold state.json (or this
            # feature's very first run) would replay every goal/card from
            # every in-progress-or-finished match.
            for stat in fx.get("stats", []):
                for side in ("h", "a"):
                    for entry in stat.get(side, []):
                        stat_key = f"{fid}:{entry['element']}:{stat['identifier']}"
                        live["stats"][stat_key] = entry["value"]
            live["fixtures"][fid] = {"started": fx["started"], "finished_provisional": fx.get("finished_provisional")}
            live["posted_score"][fid] = [0, 0]
            if fx.get("finished_provisional"):
                live["bonus_posted"][fid] = True
            continue

        if fx["started"] and not prev_fx["started"]:
            stories.append({
                "type": "kickoff",
                "key": f"kickoff:{fid}",
                "home": home,
                "away": away,
            })

        if not fx["started"]:
            live["fixtures"][fid] = {"started": fx["started"], "finished_provisional": fx.get("finished_provisional")}
            continue

        # The score shown on a post is OUR running tally of goals we've
        # actually announced, in the order we announce them -- not FPL's
        # live score. FPL only gives cumulative counts (no per-goal
        # timestamps), and its scorer/assist attribution can lag or get
        # corrected after the fact, so "the current live score" at post time
        # can already include goals that happened after the one being
        # posted about. This tally only ever moves forward as we post.
        psc = live["posted_score"].setdefault(fid, [0, 0])
        minute = fx.get("minutes")

        def score_str():
            return f"{psc[0]}-{psc[1]}"

        new_on = [pid for pid in subs_on_by_fixture.get(fid, []) if f"{fid}:{pid}" not in live["subs_seen"]]
        new_off = [pid for pid in subs_off_by_fixture.get(fid, []) if f"{fid}:{pid}" not in live["subs_off_seen"]]

        # Best-effort pairing: match each newly-on player with a newly-off
        # player from the same team seen this same poll. Leftover off
        # players (no matching sub this poll -- e.g. a red card, or the
        # pairing just missed) are still marked seen so they don't linger
        # and get mis-paired with an unrelated substitution later.
        off_by_team = {}
        for off_pid in new_off:
            off_team = players.get(off_pid, {"team": None})["team"]
            off_by_team.setdefault(off_team, []).append(off_pid)

        for pid in new_on:
            sub_key = f"{fid}:{pid}"
            live["subs_seen"][sub_key] = True
            player = players.get(pid, {"name": f"Player {pid}", "team": None})
            team_id = player["team"]

            subbed_out = None
            candidates = off_by_team.get(team_id)
            if candidates:
                off_pid = candidates.pop(0)
                live["subs_off_seen"][f"{fid}:{off_pid}"] = True
                subbed_out = players.get(off_pid, {"name": f"Player {off_pid}"})["name"]

            story = {
                "type": "substitution",
                "key": f"sub:{sub_key}",
                "player": player["name"],
                "team": teams.get(team_id, "?"),
                "home": home,
                "away": away,
                "score": score_str(),
                "minute": minute,
            }
            if subbed_out:
                story["subbed_out"] = subbed_out
            stories.append(story)

        for remaining in off_by_team.values():
            for off_pid in remaining:
                live["subs_off_seen"][f"{fid}:{off_pid}"] = True

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
                                "minute": minute,
                            }
                            if story_type == "goal":
                                new_goals[side].append(event)
                            elif story_type == "assist":
                                new_assists[side].append(event)
                            elif story_type == "own_goal":
                                # An own goal by a side's player counts for
                                # the OTHER side on the scoreboard.
                                if side == "h":
                                    psc[1] += 1
                                else:
                                    psc[0] += 1
                                event["score"] = score_str()
                                stories.append(event)
                            else:
                                event["score"] = score_str()
                                stories.append(event)
                    live["stats"][stat_key] = value

        for side in ("h", "a"):
            goals = new_goals[side]
            assists = new_assists[side]
            side_key = f"{fid}:{side}"

            if len(goals) == 1 and len(assists) == 1:
                # Assist landed in the same poll as its goal -- one combined post.
                if side == "h":
                    psc[0] += 1
                else:
                    psc[1] += 1
                goals[0]["score"] = score_str()
                goals[0]["assisted_by"] = assists[0]["player"]
                stories.append(goals[0])
                live["last_goal"][side_key] = {
                    "player": goals[0]["player"], "team": goals[0]["team"],
                    "assisted_by": assists[0]["player"], "score": goals[0]["score"],
                }
                continue

            for g in goals:
                if side == "h":
                    psc[0] += 1
                else:
                    psc[1] += 1
                g["score"] = score_str()
                stories.append(g)
                live["last_goal"][side_key] = {
                    "player": g["player"], "team": g["team"],
                    "assisted_by": g.get("assisted_by"), "score": g["score"],
                }

            if assists:
                last = live["last_goal"].get(side_key)
                if len(assists) == 1 and last and not last.get("assisted_by"):
                    # The assist arrived on a later poll than its goal (FPL's
                    # scorer/assist attribution can lag) -- repost the goal
                    # with the assist added instead of a disconnected assist
                    # post with no goal context. Uses the score as it stood
                    # for the original goal, not today's live score.
                    a = assists[0]
                    last["assisted_by"] = a["player"]
                    stories.append({
                        "type": "goal_update",
                        "key": f"goalupdate:{a['key']}",
                        "player": last["player"],
                        "team": last["team"],
                        "assisted_by": a["player"],
                        "home": home,
                        "away": away,
                        "score": last["score"],
                        "minute": minute,
                    })
                else:
                    for a in assists:
                        a["score"] = score_str()
                    stories.extend(assists)

        # finished_provisional flips at the final whistle -- that's the real
        # "match is over" signal. FPL's own `finished` flag only flips later,
        # once bonus points/BPS are fully confirmed, which can lag well
        # behind full-time (and in practice can take a long time to arrive),
        # so full-time posts off finished_provisional instead of waiting on it.
        if fx.get("finished_provisional") and not prev_fx.get("finished_provisional"):
            stories.append({
                "type": "full_time",
                "key": f"fulltime:{fid}",
                "home": home,
                "away": away,
                "score": score_str(),
                "minute": minute,
            })

        # Bonus (BPS-based) is what's actually "provisional" here: it can
        # keep shifting between players for a short while after the final
        # whistle as BPS gets recalculated, so posting on every fluctuation
        # would mean repeatedly "correcting" an earlier post. This posts once,
        # right at finished_provisional, off whatever the bonus numbers are
        # at that point -- in the large majority of cases these don't change
        # again, and waiting for FPL's own `finished` flag (bonus officially
        # locked) isn't reliable since it can lag full-time significantly.
        if fx.get("finished_provisional") and fid not in live["bonus_posted"]:
            bonus_stat = next((s for s in fx.get("stats", []) if s["identifier"] == "bonus"), None)
            if bonus_stat:
                entries = bonus_stat.get("h", []) + bonus_stat.get("a", [])
                recipients = sorted(
                    (e for e in entries if e["value"] > 0),
                    key=lambda e: e["value"], reverse=True,
                )
                if recipients:
                    stories.append({
                        "type": "bonus_points",
                        "key": f"bonus:{fid}",
                        "home": home,
                        "away": away,
                        "score": score_str(),
                        "players": [
                            {
                                "name": players.get(e["element"], {"name": f"Player {e['element']}"})["name"],
                                "points": e["value"],
                            }
                            for e in recipients
                        ],
                    })
                live["bonus_posted"][fid] = True

        live["fixtures"][fid] = {"started": fx["started"], "finished_provisional": fx.get("finished_provisional")}

    return stories

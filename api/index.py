from flask import Flask, Response
import os, json, urllib.request, urllib.parse, csv as csv_mod
from datetime import datetime, timezone
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)
CLIENT_ID     = os.environ["STRAVA_CLIENT_ID"]
CLIENT_SECRET = os.environ["STRAVA_CLIENT_SECRET"]
REFRESH_TOKEN = os.environ["STRAVA_REFRESH_TOKEN"]
HEVY_CSV_PATH = os.path.join(os.path.dirname(__file__), '..', 'workouts.csv')
START_DATE    = datetime(2025, 9, 1, tzinfo=timezone.utc)

# ── Activités manuelles (Padel / Escalade / Squash / Piscine uniquement) ──────
_M = [
    ("2025-09-02","Padel","Padel"),("2025-09-04","Padel","Padel"),
    ("2025-09-09","Padel","Padel"),("2025-09-18","Padel","Padel"),
    ("2025-09-21","Padel","Padel"),("2025-09-24","Padel","Padel"),
    ("2025-09-29","Padel","Padel"),
    ("2025-10-03","Padel","Padel"),("2025-10-05","Padel","Padel"),
    ("2025-10-08","Padel","Padel"),("2025-10-12","Padel","Padel"),
    ("2025-10-15","Padel","Padel"),("2025-10-18","Padel","Padel"),
    ("2025-10-19","Padel","Padel"),("2025-10-26","Padel","Padel"),
    ("2025-10-28","Padel","Padel"),
    ("2025-11-03","Padel","Padel"),("2025-11-12","Padel","Padel"),
    ("2025-11-15","Padel","Tournois Padel"),
    ("2025-12-01","Padel","Padel"),("2025-12-04","Padel","Padel"),
    ("2025-12-11","Padel","Padel"),("2025-12-14","Padel","Padel"),
    ("2025-12-15","Padel","Padel"),("2025-12-22","Padel","Padel"),
    ("2026-01-02","Padel","Padel"),("2026-01-03","Piscine","Piscine"),
    ("2026-01-05","Padel","Padel"),("2026-01-06","Padel","Padel"),
    ("2026-01-09","Escalade","Escalade"),("2026-01-10","Padel","Tournois Padel"),
    ("2026-01-14","Padel","Padel"),("2026-01-20","Escalade","Escalade"),
    ("2026-02-03","Padel","Padel"),("2026-02-11","Squash","Squash"),
    ("2026-02-12","Padel","Padel"),("2026-02-19","Squash","Squash"),
    ("2026-02-25","Padel","Padel"),("2026-02-27","Padel","Padel"),
    ("2026-03-02","Padel","Padel"),("2026-03-04","Padel","Padel"),
    ("2026-03-18","Padel","Padel"),("2026-03-23","Padel","Padel"),
    ("2026-04-02","Padel","Padel"),
]
MANUAL = [{
    "id": "manual_" + d + "_" + t,
    "name": n, "type": t, "sport_type": t,
    "start_date_local": d + "T10:00:00",
    "start_date": d + "T09:00:00Z",
    "elapsed_time": 5400, "moving_time": 5400, "distance": 0,
    "total_elevation_gain": 0, "calories": 350, "manual": True,
} for d, t, n in _M]

# ── Strava API ─────────────────────────────────────────────────────────────────
def _post(url, data):
    req = urllib.request.Request(url,
        data=urllib.parse.urlencode(data).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def _get(url, token):
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def get_access_token():
    tok = _post("https://www.strava.com/oauth/token", {
        "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
        "grant_type": "refresh_token", "refresh_token": REFRESH_TOKEN})
    return tok["access_token"]

def fetch_activities(token):
    start_ts = int(START_DATE.timestamp())
    activities, page = [], 1
    while True:
        batch = _get("https://www.strava.com/api/v3/athlete/activities"
                     "?after=" + str(start_ts) + "&per_page=100&page=" + str(page), token)
        if not batch:
            break
        activities.extend(batch)
        page += 1
    return activities

def fetch_detail(token, aid):
    try:
        return _get("https://www.strava.com/api/v3/activities/" + str(aid), token)
    except Exception:
        return {}

def fetch_wt_details(token, activities):
    wt = sorted([a for a in activities if a.get("type") == "WeightTraining"],
                key=lambda x: x["start_date_local"], reverse=True)[:30]
    details = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(fetch_detail, token, a["id"]): a["id"] for a in wt}
        for f in futures:
            aid = futures[f]
            try:
                details[aid] = f.result()
            except Exception:
                pass
    return details

# ── Hevy CSV ───────────────────────────────────────────────────────────────────
def read_hevy_csv():
    """Lit workouts.csv exporté depuis Hevy et retourne la liste des séances."""
    if not os.path.exists(HEVY_CSV_PATH):
        return []
    workouts_dict = {}
    skipped = set()
    with open(HEVY_CSV_PATH, encoding='utf-8') as f:
        for row in csv_mod.DictReader(f):
            key = (row.get('title') or '') + '|||' + (row.get('start_time') or '')
            if key in skipped:
                continue
            if key not in workouts_dict:
                try:
                    dt = datetime.strptime(row['start_time'].strip(), "%b %d, %Y, %I:%M %p")
                    dt = dt.replace(tzinfo=timezone.utc)
                except Exception:
                    skipped.add(key); continue
                if dt < START_DATE:
                    skipped.add(key); continue
                workouts_dict[key] = {'title': row['title'], '_dt': dt, 'exercises': {}}
            w = workouts_dict[key]
            ex = (row.get('exercise_title') or '').strip()
            if not ex:
                continue
            if ex not in w['exercises']:
                w['exercises'][ex] = []
            try:
                weight = float(row['weight_kg']) if row.get('weight_kg') else 0
                reps = int(row['reps']) if row.get('reps') else 0
            except (ValueError, TypeError):
                continue
            if (row.get('set_type') or '').strip() == 'normal' and weight > 0 and reps > 0:
                w['exercises'][ex].append({'weight_kg': weight, 'reps': reps, 'set_type': 'normal'})
    result = []
    for w in workouts_dict.values():
        exs = [{'title': t, 'sets': s} for t, s in w['exercises'].items() if s]
        if exs:
            result.append({'title': w['title'], '_dt': w['_dt'], 'exercises': exs})
    return result

def parse_hevy_data(workouts):
    """
    Retourne :
    - exercises : dict {titre_exercice: [{date, dt, max_weight, total_sets, total_reps, volume}]}
    - sessions  : liste [{date, dt, title, exercises_summary, total_sets, total_volume}]
    """
    exercises = defaultdict(list)
    sessions = []
    for w in sorted(workouts, key=lambda x: x["_dt"]):
        dt = w["_dt"]
        date_str = dt.strftime("%d/%m")
        sess_exs = []
        total_sets = 0
        total_vol = 0.0
        for ex in (w.get("exercises") or []):
            title = (ex.get("title") or "").strip()
            if not title:
                continue
            normal_sets = [s for s in (ex.get("sets") or [])
                           if (s.get("set_type") or "normal") in ("normal",)
                           and (s.get("weight_kg") or 0) > 0
                           and (s.get("reps") or 0) > 0]
            if not normal_sets:
                continue
            ww = [float(s["weight_kg"]) for s in normal_sets]
            rr = [int(s["reps"]) for s in normal_sets]
            max_w = max(ww)
            vol = sum(x * y for x, y in zip(ww, rr))
            exercises[title].append({
                "date": date_str,
                "dt": dt,
                "max_weight": max_w,
                "total_sets": len(normal_sets),
                "total_reps": sum(rr),
                "volume": round(vol, 1),
            })
            total_sets += len(normal_sets)
            total_vol += vol
            sess_exs.append({"name": title, "max_weight": max_w,
                              "sets": len(normal_sets), "reps": sum(rr)})
        if sess_exs:
            sessions.append({
                "date": date_str,
                "dt": dt,
                "title": (w.get("title") or "Séance"),
                "exercises": sess_exs,
                "total_sets": total_sets,
                "total_volume": round(total_vol, 1),
            })
    return exercises, sessions

# ── Helpers ────────────────────────────────────────────────────────────────────
def fmt_dur(s):
    h, m = divmod(int(s) // 60, 60)
    return str(h) + "h" + str(m).zfill(2) if h else str(m) + " min"

def parse_date(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))

def parse_muscle_groups(name):
    n = (name or "").lower()
    g = []
    if any(x in n for x in ["pec", "chest", "poitrine", "bench"]): g.append("Pecs")
    if any(x in n for x in ["épau", "epaul", "shoulder", "delt", "ohp", "press"]): g.append("Épaules")
    if "tricep" in n or "dip" in n: g.append("Triceps")
    if any(x in n for x in ["dos", "back", "pull", "row", "lat", "deadlift", "rdl"]): g.append("Dos")
    if any(x in n for x in ["bicep", "curl"]): g.append("Biceps")
    if any(x in n for x in ["jambe", "leg", "squat", "quad", "cuisse", "fesse", "lunge", "rdl"]): g.append("Jambes")
    if any(x in n for x in ["abdo", "core", "gainage", "plank"]): g.append("Abdos")
    return g if g else ["Autre"]

EMOJIS = {"Run":"🏃","Ride":"🚴","Swim":"🏊","Walk":"🚶","Hike":"🥾",
          "WeightTraining":"🏋️","Yoga":"🧘","Workout":"💪","VirtualRide":"🚴",
          "VirtualRun":"🏃","Padel":"🎾","Escalade":"🧗","Squash":"🏸",
          "Piscine":"🏊","Soccer":"⚽","Tennis":"🎾","EBikeRide":"⚡",
          "Crossfit":"🔥","Rowing":"🚣","Skiing":"⛷️","Basketball":"🏀"}
LABELS = {"Run":"Course","Ride":"Vélo","Swim":"Natation","Walk":"Marche",
          "Hike":"Randonnée","WeightTraining":"Muscu","Yoga":"Yoga",
          "Workout":"Entraînement","VirtualRide":"Vélo virtuel","Padel":"Padel",
          "Escalade":"Escalade","Squash":"Squash","Piscine":"Piscine",
          "EBikeRide":"Vélo élec.","Soccer":"Football","Tennis":"Tennis",
          "Crossfit":"CrossFit","Rowing":"Aviron","Skiing":"Ski"}
COLORS = {"Run":"#FC4C02","Ride":"#F5A623","Swim":"#4A90D9","Walk":"#7ED321",
          "Hike":"#50C878","WeightTraining":"#9B59B6","Yoga":"#E91E63",
          "Workout":"#FF6B35","Padel":"#E74C3C","Escalade":"#8B4513",
          "Squash":"#2ECC71","Piscine":"#3498DB","EBikeRide":"#1ABC9C",
          "Soccer":"#27AE60","Tennis":"#F1C40F","Crossfit":"#E74C3C"}
MG_COLORS = {"Pecs":"#FC4C02","Épaules":"#F5A623","Triceps":"#9B59B6",
             "Dos":"#3498DB","Biceps":"#2ECC71","Jambes":"#E74C3C",
             "Abdos":"#1ABC9C","Autre":"#95A5A6"}

def e(t): return EMOJIS.get(t, "🏅")
def l(t): return LABELS.get(t, t)
def c(t): return COLORS.get(t, "#95A5A6")
def mc_color(g): return MG_COLORS.get(g, "#95A5A6")

CSS = """
:root{--bg:#0f0f13;--s1:#1a1a24;--s2:#22222f;--bd:#2e2e3e;--tx:#e8e8f0;--t2:#8888aa;--or:#FC4C02;--ac:#6366f1}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--tx);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px}
a{color:var(--or);text-decoration:none}
header{background:linear-gradient(135deg,#1a0804,#0f0f13);border-bottom:1px solid var(--bd);padding:1rem 2rem;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:.5rem;position:sticky;top:0;z-index:100}
header h1{font-size:1.4rem;font-weight:800}header h1 span{color:var(--or)}
.hr{text-align:right;font-size:.75rem;color:var(--t2)}
.tabs{display:flex;gap:.3rem;padding:.7rem 2rem;border-bottom:1px solid var(--bd);background:var(--s1);position:sticky;top:57px;z-index:99;overflow-x:auto}
.tab{padding:.4rem 1rem;border-radius:20px;border:1px solid var(--bd);cursor:pointer;font-size:.82rem;white-space:nowrap;background:transparent;color:var(--t2)}
.tab.active,.tab:hover{background:var(--or);color:#fff;border-color:var(--or)}
.section{display:none;padding:1.5rem 2rem;max-width:1400px;margin:0 auto}
.section.active{display:block}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:.8rem;margin-bottom:1.5rem}
.kpi{background:var(--s1);border:1px solid var(--bd);border-radius:12px;padding:1rem;text-align:center}
.kv{font-size:1.6rem;font-weight:800;color:var(--or);line-height:1}
.kv small{font-size:.85rem}
.kl{font-size:.68rem;color:var(--t2);margin-top:.3rem;text-transform:uppercase;letter-spacing:.04em}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:1.2rem;margin-bottom:1.2rem}
@media(max-width:900px){.grid2{grid-template-columns:1fr}}
.card{background:var(--s1);border:1px solid var(--bd);border-radius:14px;padding:1.2rem;margin-bottom:1.2rem}
.card h2{font-size:.9rem;font-weight:700;margin-bottom:1rem}
.ch{position:relative}.ch-lg{height:260px}.ch-md{height:190px}.ch-sm{height:150px}
.sr{display:flex;align-items:center;gap:.7rem;padding:.5rem 0;border-bottom:1px solid var(--bd)}
.sr:last-child{border:none}
.si{font-size:1.3rem;width:1.8rem;text-align:center}.sinfo{flex:1}
.sn{font-weight:600;font-size:.85rem}.ss{font-size:.72rem;color:var(--t2)}
.sc{font-size:1.3rem;font-weight:800}
table{width:100%;border-collapse:collapse;font-size:.8rem}
th{color:var(--t2);font-weight:600;padding:.45rem .6rem;text-align:left;border-bottom:1px solid var(--bd);font-size:.7rem;text-transform:uppercase;letter-spacing:.04em;white-space:nowrap}
td{padding:.5rem .6rem;border-bottom:1px solid var(--bd)}
tr:last-child td{border:none}tr:hover td{background:var(--s2)}
.badge{display:inline-block;padding:.12rem .45rem;border-radius:20px;font-size:.65rem;font-weight:600;color:#fff;white-space:nowrap}
.mtag{display:inline-block;padding:.15rem .5rem;border-radius:4px;font-size:.68rem;font-weight:600;margin:.1rem;background:var(--s2);border:1px solid var(--bd)}
.dw{display:flex;gap:1.5rem;align-items:center;flex-wrap:wrap}
.dc{position:relative;height:160px;width:160px;flex-shrink:0}
.leg{display:flex;flex-direction:column;gap:.3rem;flex:1;min-width:120px}
.li{font-size:.78rem;display:flex;align-items:center;gap:.5rem}
.ld{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.bar-row{display:flex;align-items:center;gap:.6rem;margin:.4rem 0}
.bar-label{font-size:.78rem;width:100px;text-align:right;color:var(--t2)}
.bar-wrap{flex:1;height:12px;background:var(--s2);border-radius:6px;overflow:hidden}
.bar-fill{height:100%;border-radius:6px}
.bar-val{font-size:.75rem;font-weight:600;width:55px}
.ex-chip{display:inline-block;background:var(--s2);border:1px solid var(--bd);border-radius:6px;padding:.2rem .5rem;font-size:.72rem;margin:.15rem;color:var(--t2)}
.info-box{background:var(--s2);border-left:3px solid var(--or);border-radius:4px;padding:.8rem 1rem;font-size:.8rem;color:var(--t2);line-height:1.6}
.ex-select{background:var(--s2);border:1px solid var(--bd);color:var(--tx);border-radius:8px;padding:.4rem .8rem;font-size:.82rem;cursor:pointer;margin-bottom:1rem;width:100%}
.pr-badge{display:inline-block;background:#fc4c0220;border:1px solid var(--or);border-radius:4px;padding:.1rem .4rem;font-size:.65rem;color:var(--or);margin-left:.3rem;vertical-align:middle}
.set-tag{display:inline-block;background:var(--s2);border-radius:4px;padding:.1rem .35rem;font-size:.65rem;margin:.05rem;color:var(--t2)}
"""

def td_cell(val): return "<td>" + str(val) + "</td>"

def activity_row(a):
    dt = parse_date(a["start_date_local"])
    dist = (str(round(a.get("distance", 0)/1000, 1)) + " km") if a.get("distance", 0) > 100 else "—"
    dur = fmt_dur(a.get("moving_time", 0))
    avg_hr = ("♥ " + str(int(a.get("average_heartrate", 0)))) if a.get("average_heartrate") else "—"
    max_hr = (str(int(a.get("max_heartrate", 0)))) if a.get("max_heartrate") else "—"
    cal = (str(int(a.get("calories", 0) or 0)) + " kcal") if a.get("calories") else "—"
    elev = ("+" + str(int(a.get("total_elevation_gain", 0))) + " m") if a.get("total_elevation_gain", 0) > 1 else "—"
    manual = " <span style='font-size:.65rem;color:#888'>[manuel]</span>" if a.get("manual") else ""
    badge = "<span class='badge' style='background:" + c(a["type"]) + "'>" + l(a["type"]) + "</span>"
    return ("<tr>" + td_cell(dt.strftime("%d/%m/%y")) +
            td_cell(e(a["type"]) + " " + (a.get("name") or "—") + manual) +
            td_cell(badge) + td_cell(dist) + td_cell(dur) +
            td_cell(avg_hr) + td_cell(max_hr) + td_cell(cal) + td_cell(elev) + "</tr>")

def build_html(strava_acts, wt_details, hevy_workouts):
    all_acts = strava_acts + MANUAL
    all_acts.sort(key=lambda x: x["start_date_local"], reverse=True)

    total = len(all_acts)
    total_dist = sum(a.get("distance", 0) for a in all_acts) / 1000
    total_time = sum(a.get("moving_time", 0) for a in all_acts)
    total_elev = sum(a.get("total_elevation_gain", 0) for a in all_acts)
    total_cal = sum((a.get("calories", 0) or 0) for a in all_acts)

    by_type = defaultdict(list)
    by_month = defaultdict(list)
    by_week = defaultdict(list)

    for a in all_acts:
        dt = parse_date(a["start_date_local"])
        by_type[a["type"]].append(a)
        by_month[(dt.year, dt.month)].append(a)
        iso_w = dt.isocalendar()[1]
        by_week[str(dt.year) + "-" + str(iso_w).zfill(2)].append(a)

    now = datetime.now()
    mkeys, mlabels = [], []
    y, m = 2025, 9
    while (y, m) <= (now.year, now.month):
        mkeys.append((y, m))
        mn = ["Jan","Fév","Mar","Avr","Mai","Jun","Jul","Aoû","Sep","Oct","Nov","Déc"][m-1]
        mlabels.append(mn + " " + str(y)[2:])
        m += 1
        if m > 12:
            m, y = 1, y + 1

    mc_counts = [len(by_month.get(k, [])) for k in mkeys]
    md_vals = [round(sum(a.get("distance", 0) for a in by_month.get(k, []))/1000, 1) for k in mkeys]
    mt_vals = [round(sum(a.get("moving_time", 0) for a in by_month.get(k, []))/3600, 1) for k in mkeys]

    ws = sorted(by_week.keys())
    wl = ["S" + k.split("-")[1] for k in ws]
    wn = [len(by_week[k]) for k in ws]

    act_days = sorted(set(parse_date(a["start_date_local"]).date() for a in all_acts))
    mx, cu = 1, 1
    for i in range(1, len(act_days)):
        if (act_days[i] - act_days[i-1]).days == 1:
            cu += 1; mx = max(mx, cu)
        else:
            cu = 1
    if not act_days:
        mx = 0
    apw = round(total / max(len(by_week), 1), 1)

    tl = [l(t) for t in by_type]
    tn = [len(v) for v in by_type.values()]
    tc = [c(t) for t in by_type]

    sport_rows = ""
    for t, acts in sorted(by_type.items(), key=lambda x: -len(x[1])):
        dist = sum(a.get("distance", 0) for a in acts) / 1000
        sec = sum(a.get("moving_time", 0) for a in acts)
        extra = " · " + str(int(dist)) + " km" if dist > 0 else ""
        sport_rows += ("<div class='sr'><span class='si'>" + e(t) + "</span>"
            "<div class='sinfo'><div class='sn'>" + l(t) + "</div>"
            "<div class='ss'>" + fmt_dur(sec) + extra + "</div></div>"
            "<span class='sc' style='color:" + c(t) + "'>" + str(len(acts)) + "</span></div>")

    leg = "".join("<div class='li'><span class='ld' style='background:" + c(t) + "'></span>"
                  + l(t) + " <b>(" + str(len(acts)) + ")</b></div>"
                  for t, acts in sorted(by_type.items(), key=lambda x: -len(x[1])))

    rows = "".join(activity_row(a) for a in all_acts[:30])

    # ── Musculation (Strava) ──────────────────────────────────────────────────
    wt_acts = sorted(by_type.get("WeightTraining", []), key=lambda x: x["start_date_local"])
    wt_total = len(wt_acts)
    wt_time = sum(a.get("moving_time", 0) for a in wt_acts)
    wt_cal = sum((a.get("calories", 0) or 0) for a in wt_acts)

    mg_count = defaultdict(int)
    for a in wt_acts:
        for g in parse_muscle_groups(a.get("name", "")):
            mg_count[g] += 1
    mg_sorted = sorted(mg_count.items(), key=lambda x: -x[1])
    mg_max = max((v for _, v in mg_sorted), default=1)

    mg_bars = ""
    for g, n in mg_sorted:
        pct = round(n / mg_max * 100)
        col = mc_color(g)
        mg_bars += ("<div class='bar-row'><span class='bar-label'>" + g + "</span>"
                    "<div class='bar-wrap'><div class='bar-fill' style='width:"
                    + str(pct) + "%;background:" + col + "'></div></div>"
                    "<span class='bar-val' style='color:" + col + "'>" + str(n) + "</span></div>")

    wt_last = wt_acts[-30:]
    wt_dates = [parse_date(a["start_date_local"]).strftime("%d/%m") for a in wt_last]
    wt_dur_data = [round(a.get("moving_time", 0) / 60) for a in wt_last]
    wt_cal_data = [int(a.get("calories", 0) or 0) for a in wt_last]

    wt_monthly = []
    for k in mkeys:
        n = sum(1 for a in wt_acts
                if parse_date(a["start_date_local"]).year == k[0]
                and parse_date(a["start_date_local"]).month == k[1])
        wt_monthly.append(n)

    wt_rows = ""
    for a in sorted(wt_acts, key=lambda x: x["start_date_local"], reverse=True)[:20]:
        dt = parse_date(a["start_date_local"])
        groups = parse_muscle_groups(a.get("name", ""))
        tags = "".join("<span class='mtag' style='color:" + mc_color(g) + "'>" + g + "</span>" for g in groups)
        avg_hr = ("♥ " + str(int(a.get("average_heartrate", 0)))) if a.get("average_heartrate") else "—"
        max_hr = str(int(a.get("max_heartrate", 0))) if a.get("max_heartrate") else "—"
        cal = str(int(a.get("calories", 0) or 0)) + " kcal"
        dur = fmt_dur(a.get("moving_time", 0))
        wt_rows += ("<tr>" + td_cell(dt.strftime("%d/%m/%y")) +
                    td_cell(a.get("name", "Musculation")) + td_cell(tags) +
                    td_cell(dur) + td_cell(cal) +
                    td_cell(avg_hr) + td_cell(max_hr) + "</tr>")

    # ── Hevy data ─────────────────────────────────────────────────────────────
    hevy_exercises, hevy_sessions = parse_hevy_data(hevy_workouts)

    has_hevy = bool(hevy_sessions)

    # Hevy KPIs
    hevy_total_sessions = len(hevy_sessions)
    hevy_total_sets = sum(s["total_sets"] for s in hevy_sessions)
    hevy_total_vol = round(sum(s["total_volume"] for s in hevy_sessions) / 1000, 1)  # tonnes
    hevy_avg_sets = round(hevy_total_sets / max(hevy_total_sessions, 1), 1)

    # Top exercises by sessions count
    ex_freq = sorted([(ex, len(pts)) for ex, pts in hevy_exercises.items()], key=lambda x: -x[1])

    # Build max weight bars (top 12 exercises)
    hevy_max_bars = ""
    if hevy_exercises:
        max_overall = max((max(p["max_weight"] for p in pts)
                          for pts in hevy_exercises.values() if pts), default=1)
        for ex_name, pts in ex_freq[:12]:
            best = max(p["max_weight"] for p in pts)
            pct = round(best / max(max_overall, 1) * 100)
            hevy_max_bars += ("<div class='bar-row'>"
                "<span class='bar-label' style='width:160px;font-size:.76rem'>" + ex_name[:22] + "</span>"
                "<div class='bar-wrap'><div class='bar-fill' style='width:" + str(pct) + "%;background:#9B59B6'></div></div>"
                "<span class='bar-val' style='color:#9B59B6'>" + str(best) + " kg</span></div>")

    # Build recent Hevy sessions table
    hevy_sess_rows = ""
    for s in reversed(hevy_sessions[-25:]):
        ex_list = ", ".join(
            ex["name"][:20] + " (" + str(ex["max_weight"]) + "kg×" + str(ex["sets"]) + "s)"
            for ex in s["exercises"][:4])
        if len(s["exercises"]) > 4:
            ex_list += " +"
        hevy_sess_rows += ("<tr>"
            + td_cell(s["date"])
            + td_cell(s["title"])
            + td_cell(str(s["total_sets"]) + " séries")
            + td_cell(str(round(s["total_volume"])) + " kg")
            + td_cell("<small style='color:var(--t2)'>" + ex_list + "</small>")
            + "</tr>")

    # Prepare JSON data for Chart.js (exercise progression)
    # Format: {exercise: {dates: [], max_weights: [], volumes: [], sets: []}}
    hevy_chart_data = {}
    for ex_name, pts in ex_freq[:20]:
        hevy_chart_data[ex_name] = {
            "dates": [p["date"] for p in pts],
            "max_weights": [p["max_weight"] for p in pts],
            "volumes": [p["volume"] for p in pts],
            "sets": [p["total_sets"] for p in pts],
            "reps": [p["total_reps"] for p in pts],
        }

    hevy_data_json = json.dumps(hevy_chart_data, ensure_ascii=False)

    # Exercise select options
    ex_options = "".join(
        "<option value='" + ex.replace("'", "&#39;") + "'>" + ex + "</option>"
        for ex, _ in ex_freq[:20])

    # Volume evolution per month from Hevy
    hevy_vol_monthly = []
    for k in mkeys:
        vol = sum(s["total_volume"] for s in hevy_sessions
                  if s["dt"].year == k[0] and s["dt"].month == k[1])
        hevy_vol_monthly.append(round(vol))

    # Hevy CSV status message
    if not os.path.exists(HEVY_CSV_PATH):
        hevy_section = ("<div class='info-box'>"
            "📂 <b>Ajoute ton fichier Hevy</b> pour voir l'évolution de tes charges :<br>"
            "1. Dans Hevy → Profil → Paramètres → <b>Export Data</b> → tu reçois un email avec <code>workouts.csv</code><br>"
            "2. Ajoute ce fichier à la racine de ton repo GitHub (à côté de <code>vercel.json</code>)<br>"
            "3. Vercel redéploie automatiquement"
            "</div>")
    elif not hevy_sessions:
        hevy_section = "<div class='info-box'>⚠️ Aucune séance Hevy trouvée depuis le 1er septembre 2025 dans workouts.csv.</div>"
    else:
        hevy_section = ""  # rendered via data

    # ── Padel ─────────────────────────────────────────────────────────────────
    padel_acts = sorted(by_type.get("Padel", []), key=lambda x: x["start_date_local"])
    padel_total = len(padel_acts)
    padel_monthly = []
    for k in mkeys:
        n = sum(1 for a in padel_acts
                if parse_date(a["start_date_local"]).year == k[0]
                and parse_date(a["start_date_local"]).month == k[1])
        padel_monthly.append(n)
    padel_months_active = sum(1 for x in padel_monthly if x > 0)
    padel_avg = round(padel_total / max(padel_months_active, 1), 1)
    padel_record = max(padel_monthly) if padel_monthly else 0
    padel_tournois = sum(1 for a in padel_acts if "tournois" in (a.get("name", "") or "").lower())
    padel_total_time = sum(a.get("moving_time", 0) for a in padel_acts)

    padel_rows = ""
    for a in reversed(padel_acts[-30:]):
        dt = parse_date(a["start_date_local"])
        nm = a.get("name") or "Padel"
        is_t = "tournois" in nm.lower()
        badge_t = "<span class='badge' style='background:#E74C3C'>Tournois</span> " if is_t else ""
        padel_rows += ("<tr>"
            + td_cell(dt.strftime("%d/%m/%y"))
            + td_cell(badge_t + "🎾 " + nm)
            + "</tr>")

    # ── Cardio ────────────────────────────────────────────────────────────────
    run_acts = sorted(by_type.get("Run", []), key=lambda x: x["start_date_local"])
    ride_acts = sorted(
        by_type.get("Ride", []) + by_type.get("EBikeRide", []) + by_type.get("VirtualRide", []),
        key=lambda x: x["start_date_local"])
    swim_acts = sorted(by_type.get("Swim", []) + by_type.get("Piscine", []),
                       key=lambda x: x["start_date_local"])

    run_dates = [parse_date(a["start_date_local"]).strftime("%d/%m") for a in run_acts[-25:]]
    run_dist = [round(a.get("distance", 0)/1000, 1) for a in run_acts[-25:]]
    run_hr = [int(a.get("average_heartrate", 0)) for a in run_acts[-25:]]

    ride_dates = [parse_date(a["start_date_local"]).strftime("%d/%m") for a in ride_acts[-25:]]
    ride_dist = [round(a.get("distance", 0)/1000, 1) for a in ride_acts[-25:]]

    # Best run stats
    best_run_dist = max((a.get("distance", 0) for a in run_acts), default=0) / 1000
    best_run_pace = ""
    if run_acts:
        for a in run_acts:
            if a.get("distance", 0) > 100 and a.get("moving_time", 0) > 0:
                ps = a["moving_time"] / (a["distance"] / 1000)
                pm, pss = int(ps // 60), int(ps % 60)
                best_run_pace = str(pm) + "'" + str(pss).zfill(2) + "/km"

    cardio_all = sorted(run_acts + ride_acts + swim_acts,
                        key=lambda x: x["start_date_local"], reverse=True)[:30]
    cardio_rows = ""
    for a in cardio_all:
        dt = parse_date(a["start_date_local"])
        dist = str(round(a.get("distance", 0)/1000, 1)) + " km" if a.get("distance", 0) > 100 else "—"
        dur = fmt_dur(a.get("moving_time", 0))
        avg_hr = ("♥ " + str(int(a.get("average_heartrate", 0)))) if a.get("average_heartrate") else "—"
        cal = (str(int(a.get("calories", 0) or 0)) + " kcal") if a.get("calories") else "—"
        elev = ("+" + str(int(a.get("total_elevation_gain", 0))) + " m") if a.get("total_elevation_gain", 0) > 1 else "—"
        if a["type"] in ("Run", "VirtualRun") and a.get("distance", 0) > 100:
            pace_s = a.get("moving_time", 0) / (a.get("distance", 1) / 1000)
            pm = int(pace_s // 60); ps = int(pace_s % 60)
            pace = str(pm) + "'" + str(ps).zfill(2) + "/km"
        else:
            pace = "—"
        cardio_rows += ("<tr>" + td_cell(dt.strftime("%d/%m/%y"))
            + td_cell(e(a["type"]) + " " + (a.get("name") or "—"))
            + td_cell(dist) + td_cell(dur) + td_cell(pace)
            + td_cell(avg_hr) + td_cell(cal) + td_cell(elev) + "</tr>")

    all_rows = "".join(activity_row(a) for a in all_acts)
    now_str = datetime.now().strftime("%d/%m/%Y à %H:%M")

    run_chart_js = ""
    if run_acts:
        run_chart_js = ("new Chart('cRD',{type:'line',data:{labels:" + json.dumps(run_dates)
            + ",datasets:["
            + "{label:'Distance (km)',data:" + json.dumps(run_dist)
            + ",borderColor:'#FC4C02',backgroundColor:'rgba(252,76,2,0.1)',tension:.3,fill:true,yAxisID:'y'},"
            + "{label:'FC moy (bpm)',data:" + json.dumps(run_hr)
            + ",borderColor:'#E74C3C',backgroundColor:'rgba(231,76,60,0.05)',tension:.3,fill:false,yAxisID:'y1'}"
            + "]},options:{responsive:true,maintainAspectRatio:false,"
            + "plugins:{legend:{position:'bottom'}},"
            + "scales:{x:{grid:{color:gc},ticks:{maxRotation:45,maxTicksLimit:15}},y:{grid:{color:gc}},y1:{grid:{drawOnChartArea:false},position:'right'}}}});")

    ride_chart_js = ""
    if ride_acts:
        ride_chart_js = ("new Chart('cBD',{type:'line',data:{labels:" + json.dumps(ride_dates)
            + ",datasets:[{label:'Distance (km)',data:" + json.dumps(ride_dist)
            + ",borderColor:'#F5A623',backgroundColor:'rgba(245,166,35,0.1)',tension:.3,fill:true}]},"
            + "options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},"
            + "scales:{x:{grid:{color:gc},ticks:{maxRotation:45,maxTicksLimit:15}},y:{grid:{color:gc}}}}});")

    run_card = ("<div class='card'><h2>🏃 Évolution course — distance & FC</h2>"
                "<div class='ch ch-md'><canvas id='cRD'></canvas></div></div>") if run_acts else ""
    ride_card = ("<div class='card'><h2>🚴 Évolution vélo — distance (km)</h2>"
                 "<div class='ch ch-md'><canvas id='cBD'></canvas></div></div>") if ride_acts else ""

    # Hevy exercise chart JS
    hevy_js = ""
    hevy_vol_chart_js = ""
    if has_hevy:
        hevy_js = (
            "const hevyData = " + hevy_data_json + ";\n"
            "let exChart = null;\n"
            "function updateExChart(){\n"
            "  const ex = document.getElementById('exSelect').value;\n"
            "  const d = hevyData[ex] || {dates:[],max_weights:[],volumes:[],sets:[],reps:[]};\n"
            "  if(exChart) exChart.destroy();\n"
            "  exChart = new Chart('cExEvo',{type:'line',\n"
            "    data:{labels:d.dates,datasets:[\n"
            "      {label:'Charge max (kg)',data:d.max_weights,borderColor:'#9B59B6',backgroundColor:'rgba(155,89,182,0.1)',tension:.3,fill:true,yAxisID:'y',pointRadius:5,pointHoverRadius:7},\n"
            "      {label:'Volume (kg×reps)',data:d.volumes,borderColor:'#FC4C02',backgroundColor:'rgba(252,76,2,0.05)',tension:.3,fill:false,yAxisID:'y1'}\n"
            "    ]},\n"
            "    options:{responsive:true,maintainAspectRatio:false,\n"
            "      plugins:{legend:{position:'bottom'}},\n"
            "      scales:{x:{grid:{color:gc},ticks:{maxRotation:45,maxTicksLimit:20}},\n"
            "              y:{grid:{color:gc},title:{display:true,text:'kg',color:'#8888aa'}},\n"
            "              y1:{grid:{drawOnChartArea:false},position:'right',title:{display:true,text:'vol.',color:'#8888aa'}}}}\n"
            "  });\n"
            "}\n"
            "function updateSetsChart(){\n"
            "  const ex = document.getElementById('exSelect').value;\n"
            "  const d = hevyData[ex] || {dates:[],sets:[],reps:[]};\n"
            "  if(window.setsChart) window.setsChart.destroy();\n"
            "  window.setsChart = new Chart('cExSets',{type:'bar',\n"
            "    data:{labels:d.dates,datasets:[\n"
            "      {label:'Séries',data:d.sets,backgroundColor:'rgba(99,102,241,0.7)',borderRadius:3,yAxisID:'y'},\n"
            "      {label:'Reps totales',data:d.reps,backgroundColor:'rgba(252,76,2,0.5)',borderRadius:3,yAxisID:'y1'}\n"
            "    ]},\n"
            "    options:{responsive:true,maintainAspectRatio:false,\n"
            "      plugins:{legend:{position:'bottom'}},\n"
            "      scales:{x:{grid:{color:gc},ticks:{maxRotation:45,maxTicksLimit:20}},\n"
            "              y:{grid:{color:gc},ticks:{stepSize:1}},\n"
            "              y1:{grid:{drawOnChartArea:false},position:'right',ticks:{stepSize:1}}}}\n"
            "  });\n"
            "}\n"
            "function onExChange(){\n"
            "  updateExChart();\n"
            "  updateSetsChart();\n"
            "}\n"
            "const firstEx = Object.keys(hevyData)[0];\n"
            "if(firstEx){\n"
            "  document.getElementById('exSelect').value = firstEx;\n"
            "  onExChange();\n"
            "}\n"
        )
        hevy_vol_chart_js = (
            "new Chart('cHevyVol',{type:'bar',data:{labels:" + json.dumps(mlabels)
            + ",datasets:[{label:'Volume total (kg)',data:" + json.dumps(hevy_vol_monthly)
            + ",backgroundColor:'rgba(155,89,182,0.7)',borderColor:'#9B59B6',borderWidth:1,borderRadius:5}]},"
            + "options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},"
            + "scales:{x:{grid:{color:gc}},y:{grid:{color:gc}}}}});\n"
        )

    # Hevy HTML sections
    if has_hevy:
        hevy_kpis = ("<div class='kpis'>"
            "<div class='kpi'><div class='kv'>" + str(hevy_total_sessions) + "</div><div class='kl'>Séances Hevy</div></div>"
            "<div class='kpi'><div class='kv'>" + str(hevy_total_sets) + "</div><div class='kl'>Séries totales</div></div>"
            "<div class='kpi'><div class='kv'>" + str(hevy_total_vol) + "<small> t</small></div><div class='kl'>Volume total soulevé</div></div>"
            "<div class='kpi'><div class='kv'>" + str(hevy_avg_sets) + "</div><div class='kl'>Séries/séance</div></div>"
            "<div class='kpi'><div class='kv'>" + str(len(hevy_exercises)) + "</div><div class='kl'>Exercices différents</div></div>"
            "</div>")

        hevy_prog_section = (
            "<div class='card'><h2>📈 Progression par exercice (Hevy)</h2>"
            "<select class='ex-select' id='exSelect' onchange='onExChange()'>"
            + ex_options +
            "</select>"
            "<div class='grid2'>"
            "<div><div class='ch ch-lg'><canvas id='cExEvo'></canvas></div></div>"
            "<div><div class='ch ch-lg'><canvas id='cExSets'></canvas></div></div>"
            "</div></div>"
        )

        hevy_vol_section = (
            "<div class='card'><h2>🏋️ Volume mensuel soulevé (kg·reps) — Hevy</h2>"
            "<div class='ch ch-md'><canvas id='cHevyVol'></canvas></div></div>"
        )

        hevy_maxweight_section = (
            "<div class='card'><h2>🥇 Charges max par exercice</h2>"
            + hevy_max_bars + "</div>"
        )

        hevy_sessions_section = (
            "<div class='card'><h2>📋 Historique séances Hevy (25 dernières)</h2>"
            "<div style='overflow-x:auto'><table>"
            "<thead><tr><th>Date</th><th>Titre</th><th>Séries</th><th>Volume</th><th>Exercices</th></tr></thead>"
            "<tbody>" + hevy_sess_rows + "</tbody></table></div></div>"
        )
    else:
        hevy_kpis = ""
        hevy_prog_section = hevy_section
        hevy_vol_section = ""
        hevy_maxweight_section = ""
        hevy_sessions_section = ""

    html = (
"""<!DOCTYPE html>
<html lang="fr"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>🏅 Sport Récap</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>""" + CSS + """</style>
</head><body>

<header>
  <h1>🏅 Sport <span>Récap</span></h1>
  <div class="hr"><div>""" + str(total) + """ activités · depuis 01/09/2025</div><div>Mis à jour """ + now_str + """</div></div>
</header>

<div class="tabs">
  <button class="tab active" onclick="show('overview',this)">📊 Vue d'ensemble</button>
  <button class="tab" onclick="show('muscu',this)">💪 Musculation</button>
  <button class="tab" onclick="show('padel',this)">🎾 Padel</button>
  <button class="tab" onclick="show('cardio',this)">🏃 Cardio</button>
  <button class="tab" onclick="show('all',this)">📋 Toutes</button>
</div>

<div id="overview" class="section active">
  <div class="kpis">
    <div class="kpi"><div class="kv">""" + str(total) + """</div><div class="kl">Séances</div></div>
    <div class="kpi"><div class="kv">""" + str(int(total_dist)) + """<small> km</small></div><div class="kl">Distance</div></div>
    <div class="kpi"><div class="kv">""" + fmt_dur(total_time) + """</div><div class="kl">Temps</div></div>
    <div class="kpi"><div class="kv">""" + "{:,}".format(int(total_cal)) + """</div><div class="kl">Calories</div></div>
    <div class="kpi"><div class="kv">""" + str(int(total_elev)) + """<small> m</small></div><div class="kl">Dénivelé +</div></div>
    <div class="kpi"><div class="kv">""" + str(apw) + """</div><div class="kl">Séances/sem.</div></div>
    <div class="kpi"><div class="kv">""" + str(mx) + """</div><div class="kl">Streak max</div></div>
    <div class="kpi"><div class="kv">""" + str(len(by_type)) + """</div><div class="kl">Sports</div></div>
  </div>

  <div class="card"><h2>📅 Activités par mois</h2><div class="ch ch-lg"><canvas id="cM"></canvas></div></div>

  <div class="grid2">
    <div class="card"><h2>📏 Distance & temps par mois</h2><div class="ch ch-md"><canvas id="cDT"></canvas></div></div>
    <div class="card"><h2>🥧 Répartition par sport</h2>
      <div class="dw"><div class="dc"><canvas id="cDo"></canvas></div><div class="leg">""" + leg + """</div></div>
    </div>
  </div>

  <div class="card"><h2>📆 Fréquence par semaine</h2><div class="ch ch-md"><canvas id="cW"></canvas></div></div>

  <div class="grid2">
    <div class="card"><h2>🏆 Par sport</h2>""" + sport_rows + """</div>
    <div class="card"><h2>🕐 30 dernières activités</h2>
      <div style="overflow-x:auto"><table><thead><tr><th>Date</th><th>Activité</th><th>Sport</th><th>Dist.</th><th>Durée</th><th>FC moy</th><th>FC max</th><th>Cal.</th><th>D+</th></tr></thead>
      <tbody>""" + rows + """</tbody></table></div>
    </div>
  </div>
</div>

<div id="muscu" class="section">
  <div class="kpis">
    <div class="kpi"><div class="kv">""" + str(wt_total) + """</div><div class="kl">Séances (Strava)</div></div>
    <div class="kpi"><div class="kv">""" + fmt_dur(wt_time) + """</div><div class="kl">Temps total</div></div>
    <div class="kpi"><div class="kv">""" + "{:,}".format(int(wt_cal)) + """</div><div class="kl">Calories</div></div>
    <div class="kpi"><div class="kv">""" + fmt_dur(wt_time // max(wt_total, 1)) + """</div><div class="kl">Durée moy.</div></div>
    <div class="kpi"><div class="kv">""" + str(round(wt_total / max(len(by_week), 1), 1)) + """</div><div class="kl">Séances/sem.</div></div>
  </div>

  """ + hevy_kpis + """

  """ + hevy_prog_section + """

  """ + hevy_vol_section + """

  <div class="grid2">
    <div class="card"><h2>💪 Groupes musculaires (noms séances)</h2>""" + mg_bars + """</div>
    <div class="card"><h2>📅 Muscu par mois (Strava)</h2><div class="ch ch-md"><canvas id="cWTM"></canvas></div></div>
  </div>

  """ + hevy_maxweight_section + """

  <div class="card"><h2>⏱️ 30 dernières séances — durée & calories (Strava)</h2><div class="ch ch-lg"><canvas id="cWTD"></canvas></div></div>

  """ + hevy_sessions_section + """

  <div class="card"><h2>📋 Historique séances Strava (20 dernières)</h2>
    <div style="overflow-x:auto"><table><thead><tr><th>Date</th><th>Nom</th><th>Groupes</th><th>Durée</th><th>Cal.</th><th>FC moy</th><th>FC max</th></tr></thead>
    <tbody>""" + wt_rows + """</tbody></table></div>
  </div>
</div>

<div id="padel" class="section">
  <div class="kpis">
    <div class="kpi"><div class="kv">""" + str(padel_total) + """</div><div class="kl">Sessions padel</div></div>
    <div class="kpi"><div class="kv">""" + str(padel_avg) + """</div><div class="kl">Sessions/mois moy.</div></div>
    <div class="kpi"><div class="kv">""" + str(padel_record) + """</div><div class="kl">Record mensuel</div></div>
    <div class="kpi"><div class="kv">""" + str(padel_tournois) + """</div><div class="kl">Tournois</div></div>
    <div class="kpi"><div class="kv">""" + fmt_dur(padel_total_time) + """</div><div class="kl">Temps total</div></div>
  </div>

  <div class="card"><h2>🎾 Sessions padel par mois</h2><div class="ch ch-lg"><canvas id="cPM"></canvas></div></div>

  <div class="card"><h2>📋 Historique (30 dernières)</h2>
    <div style="max-height:400px;overflow-y:auto"><table><thead><tr><th>Date</th><th>Session</th></tr></thead>
    <tbody>""" + padel_rows + """</tbody></table></div>
  </div>
</div>

<div id="cardio" class="section">
  <div class="kpis">
    <div class="kpi"><div class="kv">""" + str(len(run_acts)) + """</div><div class="kl">Courses</div></div>
    <div class="kpi"><div class="kv">""" + str(int(sum(a.get("distance",0) for a in run_acts)/1000)) + """<small> km</small></div><div class="kl">Dist. course</div></div>
    <div class="kpi"><div class="kv">""" + str(round(best_run_dist, 1)) + """<small> km</small></div><div class="kl">Record distance</div></div>
    <div class="kpi"><div class="kv">""" + str(len(ride_acts)) + """</div><div class="kl">Sorties vélo</div></div>
    <div class="kpi"><div class="kv">""" + str(int(sum(a.get("distance",0) for a in ride_acts)/1000)) + """<small> km</small></div><div class="kl">Dist. vélo</div></div>
    <div class="kpi"><div class="kv">""" + str(len(swim_acts)) + """</div><div class="kl">Natation</div></div>
  </div>

  """ + run_card + ride_card + """

  <div class="card"><h2>📋 Activités cardio (30 dernières)</h2>
    <div style="overflow-x:auto"><table><thead><tr><th>Date</th><th>Activité</th><th>Dist.</th><th>Durée</th><th>Allure</th><th>FC moy</th><th>Cal.</th><th>D+</th></tr></thead>
    <tbody>""" + cardio_rows + """</tbody></table></div>
  </div>
</div>

<div id="all" class="section">
  <div class="card"><h2>📋 Toutes les activités (""" + str(total) + """)</h2>
    <div style="overflow-x:auto"><table><thead><tr><th>Date</th><th>Activité</th><th>Sport</th><th>Dist.</th><th>Durée</th><th>FC moy</th><th>FC max</th><th>Cal.</th><th>D+</th></tr></thead>
    <tbody>""" + all_rows + """</tbody></table></div>
  </div>
</div>

<script>
Chart.defaults.color='#8888aa';
Chart.defaults.font={family:'-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif',size:11};
const gc='rgba(255,255,255,0.06)';

function show(id,btn){
  document.querySelectorAll('.section').forEach(s=>s.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  btn.classList.add('active');
  if(id==='muscu' && window.exChartPending){window.exChartPending=false;onExChange();}
}

new Chart('cM',{type:'bar',data:{labels:""" + json.dumps(mlabels) + """,datasets:[{label:'Séances',data:""" + json.dumps(mc_counts) + """,backgroundColor:'#FC4C02cc',borderColor:'#FC4C02',borderWidth:1,borderRadius:5}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{grid:{color:gc}},y:{grid:{color:gc},ticks:{stepSize:1}}}}});

new Chart('cDT',{type:'line',data:{labels:""" + json.dumps(mlabels) + """,datasets:[{label:'Distance (km)',data:""" + json.dumps(md_vals) + """,borderColor:'#FC4C02',backgroundColor:'rgba(252,76,2,0.1)',tension:.3,fill:true,yAxisID:'y'},{label:'Temps (h)',data:""" + json.dumps(mt_vals) + """,borderColor:'#6366f1',backgroundColor:'rgba(99,102,241,0.1)',tension:.3,fill:true,yAxisID:'y1'}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom'}},scales:{x:{grid:{color:gc}},y:{grid:{color:gc},position:'left'},y1:{grid:{drawOnChartArea:false},position:'right'}}}});

new Chart('cDo',{type:'doughnut',data:{labels:""" + json.dumps(tl) + """,datasets:[{data:""" + json.dumps(tn) + """,backgroundColor:""" + json.dumps(tc) + """,borderWidth:2,borderColor:'#1a1a24'}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},cutout:'65%'}});

new Chart('cW',{type:'bar',data:{labels:""" + json.dumps(wl) + """,datasets:[{label:'Séances',data:""" + json.dumps(wn) + """,backgroundColor:ctx=>ctx.raw>5?'#FC4C02':ctx.raw>3?'#F5A623':'#6366f1',borderRadius:3}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{grid:{color:gc},ticks:{maxRotation:0,maxTicksLimit:22}},y:{grid:{color:gc},ticks:{stepSize:1}}}}});

new Chart('cWTM',{type:'bar',data:{labels:""" + json.dumps(mlabels) + """,datasets:[{label:'Séances',data:""" + json.dumps(wt_monthly) + """,backgroundColor:'#9B59B6cc',borderColor:'#9B59B6',borderWidth:1,borderRadius:5}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{grid:{color:gc}},y:{grid:{color:gc},ticks:{stepSize:1}}}}});

new Chart('cWTD',{type:'line',data:{labels:""" + json.dumps(wt_dates) + """,datasets:[{label:'Durée (min)',data:""" + json.dumps(wt_dur_data) + """,borderColor:'#9B59B6',backgroundColor:'rgba(155,89,182,0.1)',tension:.3,fill:true,yAxisID:'y'},{label:'Calories',data:""" + json.dumps(wt_cal_data) + """,borderColor:'#E74C3C',backgroundColor:'rgba(231,76,60,0.1)',tension:.3,fill:true,yAxisID:'y1'}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom'}},scales:{x:{grid:{color:gc},ticks:{maxRotation:45,maxTicksLimit:15}},y:{grid:{color:gc},position:'left'},y1:{grid:{drawOnChartArea:false},position:'right'}}}});

new Chart('cPM',{type:'bar',data:{labels:""" + json.dumps(mlabels) + """,datasets:[{label:'Sessions',data:""" + json.dumps(padel_monthly) + """,backgroundColor:'#E74C3Ccc',borderColor:'#E74C3C',borderWidth:1,borderRadius:5}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{grid:{color:gc}},y:{grid:{color:gc},ticks:{stepSize:1}}}}});

""" + run_chart_js + ride_chart_js + hevy_js + hevy_vol_chart_js + """

window.exChartPending = true;
</script>
</body></html>"""
    )
    return html

@app.route("/")
@app.route("/index")
def dashboard():
    try:
        token = get_access_token()
        strava = fetch_activities(token)
        wt_details = fetch_wt_details(token, strava)
        hevy = read_hevy_csv()
        return Response(build_html(strava, wt_details, hevy), mimetype="text/html")
    except Exception:
        import traceback
        return Response("<pre style='padding:2rem;color:#fff;background:#111;font-size:13px'>"
                        + traceback.format_exc() + "</pre>", status=500, mimetype="text/html")

@app.route("/debug/wt")
def debug_wt():
    try:
        token = get_access_token()
        acts = fetch_activities(token)
        wt = [a for a in acts if a.get("type") == "WeightTraining"]
        if not wt:
            return Response('{"error":"Aucune séance WeightTraining trouvée"}', mimetype="application/json")
        detail = fetch_detail(token, wt[0]["id"])
        return Response(json.dumps(detail, indent=2, ensure_ascii=False), mimetype="application/json")
    except Exception as ex:
        return Response(json.dumps({"error": str(ex)}), mimetype="application/json")

@app.route("/debug/hevy")
def debug_hevy():
    try:
        csv_exists = os.path.exists(HEVY_CSV_PATH)
        workouts = read_hevy_csv() if csv_exists else []
        exercises, sessions = parse_hevy_data(workouts)
        first = None
        if workouts:
            w = workouts[0]
            first = {"title": w["title"], "date": str(w["_dt"].date()),
                     "exercises": [{"name": e["title"], "sets": len(e["sets"])} for e in w["exercises"]]}
        return Response(json.dumps({
            "csv_found": csv_exists,
            "csv_path": HEVY_CSV_PATH,
            "total_workouts": len(workouts),
            "total_exercises": len(exercises),
            "first_workout": first
        }, indent=2, ensure_ascii=False), mimetype="application/json")
    except Exception as ex:
        import traceback
        return Response(json.dumps({"error": str(ex), "trace": traceback.format_exc()}),
                        mimetype="application/json")

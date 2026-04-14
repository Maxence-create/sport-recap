from flask import Flask, Response
import os, json, urllib.request, urllib.parse, csv as csv_mod
from datetime import datetime, date, timedelta, timezone
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)
CLIENT_ID     = os.environ["STRAVA_CLIENT_ID"]
CLIENT_SECRET = os.environ["STRAVA_CLIENT_SECRET"]
REFRESH_TOKEN = os.environ["STRAVA_REFRESH_TOKEN"]
HEVY_CSV_PATH = os.path.join(os.path.dirname(__file__), '..', 'workouts.csv')
START_DATE    = datetime(2025, 9, 1, tzinfo=timezone.utc)

# ── OBJECTIFS (court / moyen / long terme en kg) ───────────────────────────────
# Court  = 1-3 mois  |  Moyen = 6 mois  |  Long = 12+ mois
GOALS = {
    "Incline Bench Press (Smith Machine)": (70,  85,  100),
    "Iso-Lateral Chest Press (Machine)":   (85,  95,  110),
    "Butterfly (Pec Deck)":                (35,  42,  52),
    "Cable Fly Crossovers":                (12,  15,  20),
    "Overhead Press (Dumbbell)":           (26,  30,  36),
    "Lateral Raise (Cable)":               (10,  12.5,16),
    "Lateral Raise (Dumbbell)":            (9,   12,  15),
    "Face Pull":                           (20,  25,  30),
    "Lat Pulldown (Cable)":                (75,  85,  100),
    "Seated Cable Row - Bar Grip":         (75,  85,  100),
    "Single Arm Cable Row":                (32,  37,  45),
    "Straight Arm Lat Pulldown (Cable)":   (22,  27,  35),
    "Preacher Curl (Barbell)":             (42,  50,  60),
    "Preacher Curl (Machine)":             (35,  42,  50),
    "Seated Incline Curl (Dumbbell)":      (16,  18,  22),
    "Bicep Curl (Cable)":                  (27,  32,  37),
    "Hammer Curl (Dumbbell)":              (14,  16,  20),
    "Triceps Pushdown":                    (32,  37,  45),
    "Triceps Rope Pushdown":               (20,  25,  30),
    "Overhead Triceps Extension (Cable)":  (20,  25,  32),
    "Seated Triceps Press":                (100, 110, 130),
    "Squat (Barbell)":                     (100, 120, 150),
    "Leg Press (Machine)":                 (160, 180, 220),
    "Leg Extension (Machine)":             (75,  85,  100),
    "Lying Leg Curl (Machine)":            (60,  70,  80),
    "Bench Press (Barbell)":               (75,  90,  110),
    "Bench Press (Dumbbell)":              (20,  24,  28),
}

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
        if not batch: break
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
            try: details[aid] = f.result()
            except Exception: pass
    return details

# ── Hevy CSV ───────────────────────────────────────────────────────────────────
def read_hevy_csv():
    if not os.path.exists(HEVY_CSV_PATH):
        return []
    workouts_dict = {}
    skipped = set()
    with open(HEVY_CSV_PATH, encoding='utf-8') as f:
        for row in csv_mod.DictReader(f):
            key = (row.get('title') or '') + '|||' + (row.get('start_time') or '')
            if key in skipped: continue
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
            if not ex: continue
            if ex not in w['exercises']: w['exercises'][ex] = []
            try:
                weight = float(row['weight_kg']) if row.get('weight_kg') else 0
                reps = int(row['reps']) if row.get('reps') else 0
            except (ValueError, TypeError): continue
            if (row.get('set_type') or '').strip() == 'normal' and weight > 0 and reps > 0:
                w['exercises'][ex].append({'weight_kg': weight, 'reps': reps, 'set_type': 'normal'})
    result = []
    for w in workouts_dict.values():
        exs = [{'title': t, 'sets': s} for t, s in w['exercises'].items() if s]
        if exs:
            result.append({'title': w['title'], '_dt': w['_dt'], 'exercises': exs})
    return result

def parse_hevy_data(workouts):
    exercises = defaultdict(list)
    sessions = []
    for w in sorted(workouts, key=lambda x: x['_dt']):
        dt = w['_dt']
        date_str = dt.strftime("%d/%m")
        sess_exs = []
        total_sets = 0
        total_vol = 0.0
        for ex in (w.get('exercises') or []):
            title = (ex.get('title') or '').strip()
            if not title: continue
            normal = [s for s in (ex.get('sets') or [])
                      if (s.get('set_type') or 'normal') == 'normal'
                      and (s.get('weight_kg') or 0) > 0
                      and (s.get('reps') or 0) > 0]
            if not normal: continue
            ww = [float(s['weight_kg']) for s in normal]
            rr = [int(s['reps']) for s in normal]
            max_w = max(ww)
            vol = sum(x * y for x, y in zip(ww, rr))
            exercises[title].append({
                "date": date_str, "dt": dt,
                "max_weight": max_w, "total_sets": len(normal),
                "total_reps": sum(rr), "volume": round(vol, 1),
            })
            total_sets += len(normal); total_vol += vol
            sess_exs.append({"name": title, "max_weight": max_w,
                              "sets": len(normal), "reps": sum(rr)})
        if sess_exs:
            sessions.append({"date": date_str, "dt": dt,
                              "title": (w.get('title') or 'Séance'),
                              "exercises": sess_exs,
                              "total_sets": total_sets,
                              "total_volume": round(total_vol, 1)})
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
    if any(x in n for x in ["pec","chest","poitrine","bench","press"]): g.append("Pecs")
    if any(x in n for x in ["épau","epaul","shoulder","delt","ohp"]): g.append("Épaules")
    if any(x in n for x in ["tricep","dip"]): g.append("Triceps")
    if any(x in n for x in ["dos","back","pull","row","lat","deadlift","rdl"]): g.append("Dos")
    if any(x in n for x in ["bicep","curl"]): g.append("Biceps")
    if any(x in n for x in ["jambe","leg","squat","quad","cuisse","fesse","lunge"]): g.append("Jambes")
    if any(x in n for x in ["abdo","core","gainage","plank","crunch"]): g.append("Abdos")
    return g if g else ["Autre"]

def ex_to_muscle(ex_name):
    n = ex_name.lower()
    if any(x in n for x in ["bench","chest","pec","butterfly","fly","dip"]): return "Pecs"
    if any(x in n for x in ["shoulder","overhead","lateral raise","face pull","delt"]): return "Épaules"
    if any(x in n for x in ["tricep","pushdown","extension"]): return "Triceps"
    if any(x in n for x in ["lat pulldown","row","pull up","back","straight arm","bent over"]): return "Dos"
    if any(x in n for x in ["curl","bicep","hammer","preacher"]): return "Biceps"
    if any(x in n for x in ["squat","leg press","leg extension","leg curl","lunge","calf"]): return "Jambes"
    if any(x in n for x in ["crunch","cable crunch","ab","core"]): return "Abdos"
    return "Autre"

EMOJIS = {"Run":"🏃","Ride":"🚴","Swim":"🏊","Walk":"🚶","Hike":"🥾",
          "WeightTraining":"🏋️","Yoga":"🧘","Workout":"💪","VirtualRide":"🚴",
          "VirtualRun":"🏃","Padel":"🎾","Escalade":"🧗","Squash":"🏸",
          "Piscine":"🏊","Soccer":"⚽","Tennis":"🎾","EBikeRide":"⚡",
          "Crossfit":"🔥","Rowing":"🚣","Skiing":"⛷️"}
LABELS = {"Run":"Course","Ride":"Vélo","Swim":"Natation","Walk":"Marche",
          "Hike":"Randonnée","WeightTraining":"Muscu","Yoga":"Yoga",
          "Workout":"Entraînement","VirtualRide":"Vélo virtuel","Padel":"Padel",
          "Escalade":"Escalade","Squash":"Squash","Piscine":"Piscine",
          "EBikeRide":"Vélo élec.","Soccer":"Football","Tennis":"Tennis",
          "Crossfit":"CrossFit","Rowing":"Aviron","Skiing":"Ski"}
COLORS = {"Run":"#FC4C02","Ride":"#F5A623","Swim":"#4A90D9","Walk":"#7ED321",
          "Hike":"#50C878","WeightTraining":"#bc8cff","Yoga":"#E91E63",
          "Workout":"#FF6B35","Padel":"#E74C3C","Escalade":"#8B4513",
          "Squash":"#2ECC71","Piscine":"#3498DB","EBikeRide":"#1ABC9C",
          "Soccer":"#27AE60","Tennis":"#F1C40F","Crossfit":"#E74C3C"}
MG_COLORS = {"Pecs":"#FC4C02","Épaules":"#F5A623","Triceps":"#bc8cff",
             "Dos":"#58a6ff","Biceps":"#3fb950","Jambes":"#E74C3C",
             "Abdos":"#1ABC9C","Autre":"#6e7681"}

def e(t): return EMOJIS.get(t, "🏅")
def l(t): return LABELS.get(t, t)
def c(t): return COLORS.get(t, "#6e7681")
def mc(g): return MG_COLORS.get(g, "#6e7681")

# ── CSS ────────────────────────────────────────────────────────────────────────
CSS = """
:root{
  --bg:#080b12;--s1:#0d1117;--s2:#161b25;--s3:#1c2333;--s4:#21262d;
  --bd:#30363d;--bd2:#3d444d;--tx:#e6edf3;--t2:#8b949e;--t3:#6e7681;
  --or:#FC4C02;--or2:#ff6b35;--ac:#58a6ff;--gr:#3fb950;--pr:#bc8cff;--yw:#e3b341;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--tx);font-family:-apple-system,BlinkMacSystemFont,'SF Pro Display','Segoe UI',sans-serif;font-size:14px;line-height:1.5}
::-webkit-scrollbar{width:6px;height:6px}
::-webkit-scrollbar-track{background:var(--s1)}
::-webkit-scrollbar-thumb{background:var(--bd2);border-radius:3px}

/* Header */
header{
  background:linear-gradient(135deg,rgba(26,8,4,.95),rgba(8,11,18,.98));
  border-bottom:1px solid rgba(252,76,2,.2);
  padding:.9rem 2rem;display:flex;align-items:center;justify-content:space-between;
  flex-wrap:wrap;gap:.5rem;position:sticky;top:0;z-index:200;
  backdrop-filter:blur(20px);
}
header h1{font-size:1.3rem;font-weight:800;letter-spacing:-.02em}
header h1 span{color:var(--or)}
.pulse{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--gr);margin-right:.4rem;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.5;transform:scale(.8)}}
.hr{text-align:right;font-size:.72rem;color:var(--t2)}

/* Tabs */
.tabs{display:flex;gap:.3rem;padding:.6rem 2rem;border-bottom:1px solid var(--bd);
  background:rgba(13,17,23,.95);position:sticky;top:57px;z-index:199;overflow-x:auto;
  backdrop-filter:blur(10px)}
.tab{padding:.38rem 1rem;border-radius:6px;border:1px solid transparent;
  cursor:pointer;font-size:.8rem;white-space:nowrap;background:transparent;
  color:var(--t2);font-weight:500;transition:all .15s}
.tab:hover{color:var(--tx);border-color:var(--bd2);background:var(--s2)}
.tab.active{background:var(--or);color:#fff;border-color:var(--or);
  box-shadow:0 0 12px rgba(252,76,2,.35)}

/* Sections */
.section{display:none;padding:1.5rem 2rem;max-width:1500px;margin:0 auto}
.section.active{display:block}

/* KPIs */
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:.8rem;margin-bottom:1.5rem}
.kpi{background:var(--s1);border:1px solid var(--bd);border-radius:12px;padding:1rem .9rem;
  text-align:center;position:relative;overflow:hidden;transition:border-color .2s}
.kpi:hover{border-color:var(--bd2)}
.kpi::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;
  background:linear-gradient(90deg,transparent,var(--or),transparent);opacity:.5}
.kv{font-size:1.55rem;font-weight:800;color:var(--or);line-height:1;
  font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.kv small{font-size:.8rem;font-weight:600}
.kl{font-size:.65rem;color:var(--t2);margin-top:.3rem;text-transform:uppercase;letter-spacing:.06em}
.kpi.blue .kv{color:var(--ac)}
.kpi.blue::before{background:linear-gradient(90deg,transparent,var(--ac),transparent)}
.kpi.green .kv{color:var(--gr)}
.kpi.green::before{background:linear-gradient(90deg,transparent,var(--gr),transparent)}
.kpi.purple .kv{color:var(--pr)}
.kpi.purple::before{background:linear-gradient(90deg,transparent,var(--pr),transparent)}

/* Grid */
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:1.2rem;margin-bottom:1.2rem}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:1.2rem;margin-bottom:1.2rem}
@media(max-width:1100px){.grid3{grid-template-columns:1fr 1fr}}
@media(max-width:760px){.grid2,.grid3{grid-template-columns:1fr}}

/* Cards */
.card{background:var(--s1);border:1px solid var(--bd);border-radius:14px;
  padding:1.2rem;margin-bottom:1.2rem;transition:border-color .2s}
.card:hover{border-color:var(--bd2)}
.card h2{font-size:.82rem;font-weight:700;color:var(--t2);margin-bottom:1rem;
  text-transform:uppercase;letter-spacing:.07em;display:flex;align-items:center;gap:.4rem}
.card h2 .icon{font-size:1rem}

/* Charts */
.ch{position:relative}.ch-xl{height:300px}.ch-lg{height:240px}.ch-md{height:180px}.ch-sm{height:140px}

/* Sport rows */
.sr{display:flex;align-items:center;gap:.7rem;padding:.5rem 0;border-bottom:1px solid var(--bd)}
.sr:last-child{border:none}
.si{font-size:1.2rem;width:1.8rem;text-align:center}.sinfo{flex:1}
.sn{font-weight:600;font-size:.84rem}.ss{font-size:.72rem;color:var(--t2)}
.sc{font-size:1.2rem;font-weight:800}

/* Tables */
table{width:100%;border-collapse:collapse;font-size:.78rem}
th{color:var(--t2);font-weight:600;padding:.4rem .6rem;text-align:left;
  border-bottom:1px solid var(--bd);font-size:.68rem;text-transform:uppercase;
  letter-spacing:.05em;white-space:nowrap}
td{padding:.48rem .6rem;border-bottom:1px solid rgba(48,54,61,.5)}
tr:last-child td{border:none}
tr:hover td{background:var(--s2)}

/* Badges */
.badge{display:inline-block;padding:.1rem .45rem;border-radius:5px;
  font-size:.64rem;font-weight:700;color:#fff;white-space:nowrap}
.mtag{display:inline-block;padding:.1rem .4rem;border-radius:4px;
  font-size:.65rem;font-weight:600;margin:.08rem;background:var(--s2);
  border:1px solid var(--bd)}

/* Donut legend */
.dw{display:flex;gap:1.5rem;align-items:center;flex-wrap:wrap}
.dc{position:relative;height:155px;width:155px;flex-shrink:0}
.leg{display:flex;flex-direction:column;gap:.25rem;flex:1;min-width:120px}
.li{font-size:.76rem;display:flex;align-items:center;gap:.45rem}
.ld{width:7px;height:7px;border-radius:50%;flex-shrink:0}

/* Bar rows */
.bar-row{display:flex;align-items:center;gap:.6rem;margin:.35rem 0}
.bar-label{font-size:.75rem;width:120px;text-align:right;color:var(--t2);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar-wrap{flex:1;height:10px;background:var(--s2);border-radius:5px;overflow:hidden}
.bar-fill{height:100%;border-radius:5px;transition:width .5s ease}
.bar-val{font-size:.74rem;font-weight:700;width:60px}

/* Goals progress */
.goal-row{margin:.7rem 0;padding:.7rem .9rem;background:var(--s2);border-radius:10px;
  border:1px solid var(--bd)}
.goal-name{font-weight:700;font-size:.83rem;margin-bottom:.45rem;display:flex;align-items:center;gap:.5rem}
.goal-pr{color:var(--or);font-size:.78rem}
.goal-tracks{display:flex;flex-direction:column;gap:.3rem}
.goal-track{display:flex;align-items:center;gap:.6rem}
.goal-lbl{font-size:.68rem;color:var(--t2);width:55px;text-align:right;
  text-transform:uppercase;letter-spacing:.04em}
.goal-bar{flex:1;height:8px;background:var(--s3);border-radius:4px;overflow:hidden}
.goal-fill{height:100%;border-radius:4px;transition:width .6s ease}
.goal-fill.ct{background:linear-gradient(90deg,#3fb950,#58a6ff)}
.goal-fill.mt{background:linear-gradient(90deg,#f5a623,#fc4c02)}
.goal-fill.lt{background:linear-gradient(90deg,#bc8cff,#fc4c02)}
.goal-num{font-size:.72rem;font-weight:700;width:55px}
.goal-done{display:inline-block;padding:.05rem .3rem;border-radius:3px;
  background:rgba(63,185,80,.2);border:1px solid var(--gr);color:var(--gr);
  font-size:.62rem;font-weight:700;margin-left:.3rem}

/* Exercise selector */
.ex-select{background:var(--s2);border:1px solid var(--bd2);color:var(--tx);
  border-radius:8px;padding:.42rem .8rem;font-size:.82rem;cursor:pointer;
  margin-bottom:1rem;width:100%;outline:none;transition:border-color .2s}
.ex-select:focus{border-color:var(--or)}

/* Heatmap */
.heatmap-wrap{overflow-x:auto;padding-bottom:.5rem}
.heatmap{display:flex;gap:3px;align-items:flex-start;min-width:max-content}
.hm-col{display:flex;flex-direction:column;gap:3px}
.hm-cell{width:12px;height:12px;border-radius:2px;transition:transform .1s}
.hm-cell:hover{transform:scale(1.5);z-index:10}
.hm-0{background:var(--s3)}
.hm-1{background:rgba(252,76,2,.3)}
.hm-2{background:rgba(252,76,2,.6)}
.hm-3{background:rgba(252,76,2,.85)}
.hm-4{background:#FC4C02}
.hm-months{display:flex;gap:3px;margin-bottom:.3rem;padding-left:0}
.hm-ml{font-size:.65rem;color:var(--t3)}

/* Info box */
.info-box{background:var(--s2);border-left:3px solid var(--or);border-radius:4px;
  padding:.8rem 1rem;font-size:.8rem;color:var(--t2);line-height:1.6;margin-bottom:1rem}

/* Recent activity item */
.act-item{display:flex;align-items:center;gap:.8rem;padding:.55rem 0;
  border-bottom:1px solid rgba(48,54,61,.4)}
.act-item:last-child{border:none}
.act-emoji{font-size:1.2rem;width:1.8rem;text-align:center}
.act-info{flex:1;min-width:0}
.act-name{font-weight:600;font-size:.83rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.act-meta{font-size:.7rem;color:var(--t2)}
.act-stat{font-size:.82rem;font-weight:700;text-align:right}

/* Week card */
.week-day{display:flex;align-items:center;gap:.6rem;padding:.35rem 0;
  border-bottom:1px solid rgba(48,54,61,.3)}
.week-day:last-child{border:none}
.wday-label{font-size:.72rem;color:var(--t2);width:32px;text-align:right}
.wday-acts{flex:1;display:flex;gap:.3rem;flex-wrap:wrap}
.wday-chip{padding:.1rem .5rem;border-radius:4px;font-size:.68rem;font-weight:600;color:#fff}

/* Stat highlight */
.stat-hl{display:flex;justify-content:space-between;padding:.4rem 0;
  border-bottom:1px solid rgba(48,54,61,.4);font-size:.8rem}
.stat-hl:last-child{border:none}
.stat-hl span:last-child{font-weight:700;color:var(--or)}
"""

def td_c(v): return "<td>" + str(v) + "</td>"

def act_row_full(a):
    dt = parse_date(a["start_date_local"])
    dist = (str(round(a.get("distance",0)/1000,1))+" km") if a.get("distance",0)>100 else "—"
    dur = fmt_dur(a.get("moving_time",0))
    avhr = ("♥ "+str(int(a.get("average_heartrate",0)))) if a.get("average_heartrate") else "—"
    mxhr = str(int(a.get("max_heartrate",0))) if a.get("max_heartrate") else "—"
    cal = (str(int(a.get("calories",0) or 0))+" kcal") if a.get("calories") else "—"
    elev = ("+"+str(int(a.get("total_elevation_gain",0)))+" m") if a.get("total_elevation_gain",0)>1 else "—"
    manual = " <span style='font-size:.62rem;color:var(--t3)'>[manuel]</span>" if a.get("manual") else ""
    badge = "<span class='badge' style='background:"+c(a["type"])+"'>"+l(a["type"])+"</span>"
    return ("<tr>"+td_c(dt.strftime("%d/%m/%y"))
            +td_c(e(a["type"])+" "+(a.get("name") or "—")+manual)
            +td_c(badge)+td_c(dist)+td_c(dur)+td_c(avhr)+td_c(mxhr)+td_c(cal)+td_c(elev)+"</tr>")

# ── Main HTML builder ──────────────────────────────────────────────────────────
def build_html(strava_acts, wt_details, hevy_workouts):
    all_acts = strava_acts + MANUAL
    all_acts.sort(key=lambda x: x["start_date_local"], reverse=True)

    total = len(all_acts)
    total_dist = sum(a.get("distance",0) for a in all_acts)/1000
    total_time = sum(a.get("moving_time",0) for a in all_acts)
    total_elev = sum(a.get("total_elevation_gain",0) for a in all_acts)
    total_cal = sum((a.get("calories",0) or 0) for a in all_acts)

    by_type = defaultdict(list)
    by_month = defaultdict(list)
    by_week = defaultdict(list)
    by_day = defaultdict(list)

    for a in all_acts:
        dt = parse_date(a["start_date_local"])
        by_type[a["type"]].append(a)
        by_month[(dt.year,dt.month)].append(a)
        by_week[str(dt.year)+"-"+str(dt.isocalendar()[1]).zfill(2)].append(a)
        by_day[dt.date()].append(a)

    now = datetime.now()
    mkeys, mlabels = [], []
    y, m = 2025, 9
    while (y,m) <= (now.year,now.month):
        mkeys.append((y,m))
        mn = ["Jan","Fév","Mar","Avr","Mai","Jun","Jul","Aoû","Sep","Oct","Nov","Déc"][m-1]
        mlabels.append(mn+" "+str(y)[2:])
        m += 1
        if m > 12: m,y = 1,y+1

    mc_counts = [len(by_month.get(k,[])) for k in mkeys]
    mt_vals = [round(sum(a.get("moving_time",0) for a in by_month.get(k,[]))/3600,1) for k in mkeys]
    ws = sorted(by_week.keys())
    wl = ["S"+k.split("-")[1] for k in ws]
    wn = [len(by_week[k]) for k in ws]

    # Streak
    act_days = sorted(by_day.keys())
    mx_streak, cu = 1, 1
    for i in range(1,len(act_days)):
        if (act_days[i]-act_days[i-1]).days == 1: cu+=1; mx_streak=max(mx_streak,cu)
        else: cu=1
    if not act_days: mx_streak=0
    cur_streak = 1
    if act_days:
        for i in range(len(act_days)-1,0,-1):
            if (act_days[i]-act_days[i-1]).days == 1: cur_streak+=1
            else: break
        if (date.today()-act_days[-1]).days > 1: cur_streak=0
    apw = round(total/max(len(by_week),1),1)

    # Donut data
    tl=[l(t) for t in by_type]; tn=[len(v) for v in by_type.values()]; tc=[c(t) for t in by_type]

    # Sport summary rows
    sport_rows=""
    for t,acts in sorted(by_type.items(),key=lambda x:-len(x[1])):
        dist=sum(a.get("distance",0) for a in acts)/1000
        sec=sum(a.get("moving_time",0) for a in acts)
        extra=" · "+str(round(dist,0))+" km" if dist>0 else ""
        sport_rows+=("<div class='sr'><span class='si'>"+e(t)+"</span>"
            "<div class='sinfo'><div class='sn'>"+l(t)+"</div>"
            "<div class='ss'>"+fmt_dur(sec)+extra+"</div></div>"
            "<span class='sc' style='color:"+c(t)+"'>"+str(len(acts))+"</span></div>")

    leg="".join("<div class='li'><span class='ld' style='background:"+c(t)+"'></span>"+l(t)
                +" <b>("+str(len(acts))+")</b></div>"
                for t,acts in sorted(by_type.items(),key=lambda x:-len(x[1])))

    # Recent 12 activities
    recent_items=""
    for a in all_acts[:12]:
        dt=parse_date(a["start_date_local"])
        dist_s=""
        if a.get("distance",0)>100: dist_s=" · "+str(round(a["distance"]/1000,1))+" km"
        dur_s=" · "+fmt_dur(a.get("moving_time",0))
        hr_s=(" · ♥"+str(int(a.get("average_heartrate",0)))) if a.get("average_heartrate") else ""
        manual_s=" [manuel]" if a.get("manual") else ""
        recent_items+=("<div class='act-item'>"
            "<span class='act-emoji'>"+e(a["type"])+"</span>"
            "<div class='act-info'>"
            "<div class='act-name'>"+(a.get("name") or l(a["type"]))+manual_s+"</div>"
            "<div class='act-meta'>"+dt.strftime("%d/%m/%Y")+dist_s+dur_s+hr_s+"</div>"
            "</div>"
            "<span class='act-stat' style='color:"+c(a["type"])+"'>"+l(a["type"])+"</span>"
            "</div>")

    # This week summary
    today_d = date.today()
    week_start = today_d - timedelta(days=today_d.weekday())
    week_html=""
    day_names=["Lun","Mar","Mer","Jeu","Ven","Sam","Dim"]
    for i in range(7):
        d2 = week_start+timedelta(days=i)
        acts_d = by_day.get(d2,[])
        chips=""
        for a in acts_d:
            chips+=("<span class='wday-chip' style='background:"+c(a["type"])+"'>"
                   +e(a["type"])+" "+l(a["type"])+"</span>")
        if not acts_d: chips="<span style='color:var(--t3);font-size:.7rem'>—</span>"
        bold=" style='color:var(--tx);font-weight:700'" if d2==today_d else ""
        week_html+=("<div class='week-day'>"
            "<span class='wday-label'"+bold+">"+day_names[i]+"</span>"
            "<div class='wday-acts'>"+chips+"</div></div>")

    # Heatmap
    hm_start = date(2025,9,1)
    hm_end   = date.today()
    # align to Monday
    hm_cursor = hm_start - timedelta(days=hm_start.weekday())
    hm_cols = ""
    month_markers = []
    prev_month = -1
    col_idx = 0
    while hm_cursor <= hm_end:
        hm_col_cells=""
        for day_offset in range(7):
            d2 = hm_cursor+timedelta(days=day_offset)
            if d2 < hm_start or d2 > hm_end:
                hm_col_cells+="<div class='hm-cell hm-0'></div>"
            else:
                n = len(by_day.get(d2,[]))
                cls = "hm-"+("0" if n==0 else "1" if n==1 else "2" if n==2 else "3" if n==3 else "4")
                types_s=", ".join(set(l(a["type"]) for a in by_day.get(d2,[])))
                title_s=d2.strftime("%d/%m")+(": "+types_s if types_s else "")
                hm_col_cells+=("<div class='hm-cell "+cls+"' title='"+title_s+"'></div>")
        if hm_cursor.month != prev_month:
            month_markers.append((col_idx, ["Jan","Fév","Mar","Avr","Mai","Jun","Jul","Aoû","Sep","Oct","Nov","Déc"][hm_cursor.month-1]))
            prev_month = hm_cursor.month
        hm_cols+="<div class='hm-col'>"+hm_col_cells+"</div>"
        hm_cursor+=timedelta(weeks=1)
        col_idx+=1
    hm_legend=("Activité : "
        "<span class='hm-cell hm-0' style='display:inline-block;vertical-align:middle'></span> 0 &nbsp;"
        "<span class='hm-cell hm-1' style='display:inline-block;vertical-align:middle'></span> 1 &nbsp;"
        "<span class='hm-cell hm-2' style='display:inline-block;vertical-align:middle'></span> 2 &nbsp;"
        "<span class='hm-cell hm-3' style='display:inline-block;vertical-align:middle'></span> 3 &nbsp;"
        "<span class='hm-cell hm-4' style='display:inline-block;vertical-align:middle'></span> 4+")

    # All activities table
    all_rows="".join(act_row_full(a) for a in all_acts)

    # ── Musculation ──────────────────────────────────────────────────────────
    wt_acts=sorted(by_type.get("WeightTraining",[]),key=lambda x:x["start_date_local"])
    wt_total=len(wt_acts)
    wt_time=sum(a.get("moving_time",0) for a in wt_acts)
    wt_cal=sum((a.get("calories",0) or 0) for a in wt_acts)

    mg_count=defaultdict(int)
    for a in wt_acts:
        for g in parse_muscle_groups(a.get("name","")): mg_count[g]+=1
    mg_sorted=sorted(mg_count.items(),key=lambda x:-x[1])
    mg_max=max((v for _,v in mg_sorted),default=1)
    mg_bars=""
    for g,n in mg_sorted:
        pct=round(n/mg_max*100); col=mc(g)
        mg_bars+=("<div class='bar-row'><span class='bar-label'>"+g+"</span>"
            "<div class='bar-wrap'><div class='bar-fill' style='width:"+str(pct)+"%;background:"+col+"'></div></div>"
            "<span class='bar-val' style='color:"+col+"'>"+str(n)+"</span></div>")

    wt_last=wt_acts[-30:]
    wt_dates=[parse_date(a["start_date_local"]).strftime("%d/%m") for a in wt_last]
    wt_dur_d=[round(a.get("moving_time",0)/60) for a in wt_last]
    wt_cal_d=[int(a.get("calories",0) or 0) for a in wt_last]
    wt_monthly=[sum(1 for a in wt_acts
                    if parse_date(a["start_date_local"]).year==k[0]
                    and parse_date(a["start_date_local"]).month==k[1]) for k in mkeys]

    wt_rows=""
    for a in sorted(wt_acts,key=lambda x:x["start_date_local"],reverse=True)[:20]:
        dt=parse_date(a["start_date_local"])
        groups=parse_muscle_groups(a.get("name",""))
        tags="".join("<span class='mtag' style='color:"+mc(g)+"'>"+g+"</span>" for g in groups)
        avhr=("♥ "+str(int(a.get("average_heartrate",0)))) if a.get("average_heartrate") else "—"
        mxhr=str(int(a.get("max_heartrate",0))) if a.get("max_heartrate") else "—"
        wt_rows+=("<tr>"+td_c(dt.strftime("%d/%m/%y"))+td_c(a.get("name","Muscu"))
                  +td_c(tags)+td_c(fmt_dur(a.get("moving_time",0)))
                  +td_c(str(int(a.get("calories",0) or 0))+" kcal")
                  +td_c(avhr)+td_c(mxhr)+"</tr>")

    # ── Hevy data ────────────────────────────────────────────────────────────
    hevy_exercises, hevy_sessions = parse_hevy_data(hevy_workouts)
    has_hevy = bool(hevy_sessions)

    hevy_total_sets = sum(s["total_sets"] for s in hevy_sessions)
    hevy_total_vol = round(sum(s["total_volume"] for s in hevy_sessions)/1000,1)
    hevy_avg_sets = round(hevy_total_sets/max(len(hevy_sessions),1),1)

    ex_freq=sorted([(ex,len(pts)) for ex,pts in hevy_exercises.items()],key=lambda x:-x[1])
    ex_options="".join("<option value='"+ex.replace("'","&#39;")+"'>"+ex+"</option>"
                       for ex,_ in ex_freq[:25])

    # Max weight bars per exercise
    max_w_bars=""
    if hevy_exercises:
        all_maxes=[(ex,max(p["max_weight"] for p in pts)) for ex,pts in hevy_exercises.items() if pts]
        all_maxes.sort(key=lambda x:-x[1])
        overall_max=all_maxes[0][1] if all_maxes else 1
        for ex_name,best in all_maxes[:15]:
            pct=round(best/overall_max*100)
            col=mc(ex_to_muscle(ex_name))
            muscle_tag="<span style='font-size:.62rem;color:"+col+";font-weight:600'>"+ex_to_muscle(ex_name)+"</span>"
            max_w_bars+=("<div class='bar-row'>"
                "<span class='bar-label' style='width:180px'>"+ex_name[:26]+"</span>"
                "<div class='bar-wrap'><div class='bar-fill' style='width:"+str(pct)+"%;background:"+col+"'></div></div>"
                "<span class='bar-val' style='color:"+col+"'>"+str(best)+"kg</span>"
                +"</div>")

    # Volume par mois Hevy
    hevy_vol_monthly=[round(sum(s["total_volume"] for s in hevy_sessions
                               if s["dt"].year==k[0] and s["dt"].month==k[1])) for k in mkeys]

    # Hevy sessions table
    hevy_sess_rows=""
    for s in reversed(hevy_sessions[-25:]):
        ex_list=", ".join(ex["name"][:22]+" ("+str(ex["max_weight"])+"kg×"+str(ex["sets"])+"s)"
                          for ex in s["exercises"][:4])
        if len(s["exercises"])>4: ex_list+=" +"
        hevy_sess_rows+=("<tr>"+td_c(s["date"])+td_c(s["title"])
                         +td_c(str(s["total_sets"])+" séries")
                         +td_c(str(round(s["total_volume"]))+" kg")
                         +td_c("<span style='color:var(--t2);font-size:.72rem'>"+ex_list+"</span>")+"</tr>")

    # Radar muscle data
    mg_names=["Pecs","Épaules","Triceps","Dos","Biceps","Jambes","Abdos"]
    radar_data=[]
    if hevy_exercises:
        mg_vol=defaultdict(float)
        for ex_name,pts in hevy_exercises.items():
            muscle=ex_to_muscle(ex_name)
            mg_vol[muscle]+=sum(p["volume"] for p in pts)
        mg_vol_max=max(mg_vol.values()) if mg_vol else 1
        radar_data=[round(mg_vol.get(g,0)/mg_vol_max*100) for g in mg_names]

    # Chart data for exercises
    hevy_chart_data={}
    for ex_name,pts in ex_freq[:25]:
        hevy_chart_data[ex_name]={
            "dates":[p["date"] for p in hevy_exercises[ex_name]],
            "max_weights":[p["max_weight"] for p in hevy_exercises[ex_name]],
            "volumes":[p["volume"] for p in hevy_exercises[ex_name]],
            "sets":[p["total_sets"] for p in hevy_exercises[ex_name]],
            "reps":[p["total_reps"] for p in hevy_exercises[ex_name]],
        }
    hevy_data_json=json.dumps(hevy_chart_data,ensure_ascii=False)

    # ── Records & Goals ──────────────────────────────────────────────────────
    goal_rows=""
    all_ex_maxes={}
    all_ex_dates={}
    for ex_name,pts in hevy_exercises.items():
        best=max(pts,key=lambda p:p["max_weight"])
        all_ex_maxes[ex_name]=best["max_weight"]
        all_ex_dates[ex_name]=best["dt"].strftime("%d/%m/%y")

    # Only show exercises that have goals defined
    for ex_name,(g_short,g_mid,g_long) in GOALS.items():
        if ex_name not in all_ex_maxes: continue
        cur=all_ex_maxes[ex_name]
        pr_date=all_ex_dates[ex_name]
        muscle=ex_to_muscle(ex_name)
        muscle_color=mc(muscle)

        def pct_clamp(v,g): return min(100,round(v/g*100)) if g>0 else 0

        pct_s=pct_clamp(cur,g_short)
        pct_m=pct_clamp(cur,g_mid)
        pct_l=pct_clamp(cur,g_long)

        done_s="<span class='goal-done'>✓</span>" if cur>=g_short else ""
        done_m="<span class='goal-done'>✓</span>" if cur>=g_mid else ""
        done_l="<span class='goal-done'>✓</span>" if cur>=g_long else ""

        goal_rows+=("<div class='goal-row'>"
            "<div class='goal-name'>"
            "<span style='color:"+muscle_color+";font-size:.75rem'>"+muscle+"</span>"
            " "+ex_name
            +"<span class='goal-pr'>PR : "+str(cur)+"kg <span style='color:var(--t3);font-size:.68rem'>("+pr_date+")</span></span>"
            "</div>"
            "<div class='goal-tracks'>"
            "<div class='goal-track'><span class='goal-lbl'>Court</span>"
            "<div class='goal-bar'><div class='goal-fill ct' style='width:"+str(pct_s)+"%'></div></div>"
            "<span class='goal-num' style='color:var(--gr)'>"+str(pct_s)+"%"+done_s+"</span>"
            "<span style='color:var(--t3);font-size:.7rem'>→ "+str(g_short)+"kg</span></div>"
            "<div class='goal-track'><span class='goal-lbl'>Moyen</span>"
            "<div class='goal-bar'><div class='goal-fill mt' style='width:"+str(pct_m)+"%'></div></div>"
            "<span class='goal-num' style='color:var(--or)'>"+str(pct_m)+"%"+done_m+"</span>"
            "<span style='color:var(--t3);font-size:.7rem'>→ "+str(g_mid)+"kg</span></div>"
            "<div class='goal-track'><span class='goal-lbl'>Long</span>"
            "<div class='goal-bar'><div class='goal-fill lt' style='width:"+str(pct_l)+"%'></div></div>"
            "<span class='goal-num' style='color:var(--pr)'>"+str(pct_l)+"%"+done_l+"</span>"
            "<span style='color:var(--t3);font-size:.7rem'>→ "+str(g_long)+"kg</span></div>"
            "</div></div>")

    # Top PRs for overview
    pr_rows=""
    pr_sorted=sorted(all_ex_maxes.items(),key=lambda x:-x[1])[:10]
    for ex_name,best in pr_sorted:
        col=mc(ex_to_muscle(ex_name))
        pr_rows+=("<div class='stat-hl'><span>"+ex_name+"</span>"
                  "<span style='color:"+col+"'>"+str(best)+" kg</span></div>")

    # ── Padel ────────────────────────────────────────────────────────────────
    padel_acts=sorted(by_type.get("Padel",[]),key=lambda x:x["start_date_local"])
    padel_total=len(padel_acts)
    padel_monthly=[sum(1 for a in padel_acts
                       if parse_date(a["start_date_local"]).year==k[0]
                       and parse_date(a["start_date_local"]).month==k[1]) for k in mkeys]
    padel_ma=sum(1 for x in padel_monthly if x>0)
    padel_avg=round(padel_total/max(padel_ma,1),1)
    padel_record=max(padel_monthly) if padel_monthly else 0
    padel_tournois=sum(1 for a in padel_acts if "tournois" in (a.get("name","") or "").lower())
    padel_time=sum(a.get("moving_time",0) for a in padel_acts)

    padel_rows=""
    for a in reversed(padel_acts[-30:]):
        dt=parse_date(a["start_date_local"])
        nm=a.get("name") or "Padel"
        is_t="tournois" in nm.lower()
        b="<span class='badge' style='background:#E74C3C'>Tournois</span> " if is_t else ""
        padel_rows+="<tr>"+td_c(dt.strftime("%d/%m/%y"))+td_c(b+"🎾 "+nm)+"</tr>"

    # Other sports (escalade, squash, piscine)
    esc_acts=by_type.get("Escalade",[])
    sq_acts=by_type.get("Squash",[])
    pis_acts=by_type.get("Piscine",[])

    other_rows=""
    other_all=sorted(esc_acts+sq_acts+pis_acts,key=lambda x:x["start_date_local"],reverse=True)
    for a in other_all:
        dt=parse_date(a["start_date_local"])
        other_rows+="<tr>"+td_c(dt.strftime("%d/%m/%y"))+td_c(e(a["type"])+" "+(a.get("name") or l(a["type"])))+td_c("<span class='badge' style='background:"+c(a["type"])+"'>"+l(a["type"])+"</span>")+"</tr>"

    # ── Cardio ───────────────────────────────────────────────────────────────
    run_acts=sorted(by_type.get("Run",[]),key=lambda x:x["start_date_local"])
    ride_acts=sorted(by_type.get("Ride",[])+by_type.get("EBikeRide",[])+by_type.get("VirtualRide",[]),
                     key=lambda x:x["start_date_local"])

    run_dates=[parse_date(a["start_date_local"]).strftime("%d/%m") for a in run_acts[-25:]]
    run_dist=[round(a.get("distance",0)/1000,1) for a in run_acts[-25:]]
    run_hr=[int(a.get("average_heartrate",0) or 0) for a in run_acts[-25:]]
    ride_dates=[parse_date(a["start_date_local"]).strftime("%d/%m") for a in ride_acts[-25:]]
    ride_dist=[round(a.get("distance",0)/1000,1) for a in ride_acts[-25:]]

    best_run_dist=max((a.get("distance",0) for a in run_acts),default=0)/1000
    total_run_dist=sum(a.get("distance",0) for a in run_acts)/1000
    total_ride_dist=sum(a.get("distance",0) for a in ride_acts)/1000

    cardio_all=sorted(run_acts+ride_acts,key=lambda x:x["start_date_local"],reverse=True)[:30]
    cardio_rows=""
    for a in cardio_all:
        dt=parse_date(a["start_date_local"])
        dist=str(round(a.get("distance",0)/1000,1))+" km" if a.get("distance",0)>100 else "—"
        dur=fmt_dur(a.get("moving_time",0))
        avhr=("♥ "+str(int(a.get("average_heartrate",0)))) if a.get("average_heartrate") else "—"
        cal=(str(int(a.get("calories",0) or 0))+" kcal") if a.get("calories") else "—"
        elev=("+"+str(int(a.get("total_elevation_gain",0)))+" m") if a.get("total_elevation_gain",0)>1 else "—"
        pace="—"
        if a["type"] in ("Run","VirtualRun") and a.get("distance",0)>100:
            ps=a.get("moving_time",0)/(a.get("distance",1)/1000)
            pace=str(int(ps//60))+"'"+str(int(ps%60)).zfill(2)+"/km"
        cardio_rows+=("<tr>"+td_c(dt.strftime("%d/%m/%y"))
                      +td_c(e(a["type"])+" "+(a.get("name") or "—"))
                      +td_c(dist)+td_c(dur)+td_c(pace)+td_c(avhr)+td_c(cal)+td_c(elev)+"</tr>")

    now_str=datetime.now().strftime("%d/%m/%Y à %H:%M")

    # ── JS charts ────────────────────────────────────────────────────────────
    run_js=""
    if run_acts:
        run_js=("new Chart('cRD',{type:'line',data:{labels:"+json.dumps(run_dates)
            +",datasets:[{label:'Distance (km)',data:"+json.dumps(run_dist)
            +",borderColor:'#FC4C02',backgroundColor:'rgba(252,76,2,0.1)',tension:.3,fill:true,yAxisID:'y'},"
            +"{label:'FC moy',data:"+json.dumps(run_hr)
            +",borderColor:'#E74C3C',tension:.3,fill:false,yAxisID:'y1',borderDash:[4,3]}]},"
            +"options:{responsive:true,maintainAspectRatio:false,"
            +"plugins:{legend:{position:'bottom'}},"
            +"scales:{x:{grid:{color:gc},ticks:{maxRotation:45,maxTicksLimit:15}},"
            +"y:{grid:{color:gc}},y1:{grid:{drawOnChartArea:false},position:'right'}}}});")
    ride_js=""
    if ride_acts:
        ride_js=("new Chart('cBD',{type:'line',data:{labels:"+json.dumps(ride_dates)
            +",datasets:[{label:'Distance (km)',data:"+json.dumps(ride_dist)
            +",borderColor:'#F5A623',backgroundColor:'rgba(245,166,35,0.1)',tension:.3,fill:true}]},"
            +"options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},"
            +"scales:{x:{grid:{color:gc},ticks:{maxRotation:45,maxTicksLimit:15}},y:{grid:{color:gc}}}}});")

    run_card=("<div class='card'><h2><span class='icon'>🏃</span> Course — Distance & FC</h2>"
              "<div class='ch ch-md'><canvas id='cRD'></canvas></div></div>") if run_acts else ""
    ride_card=("<div class='card'><h2><span class='icon'>🚴</span> Vélo — Distance</h2>"
               "<div class='ch ch-md'><canvas id='cBD'></canvas></div></div>") if ride_acts else ""

    hevy_js=""
    hevy_vol_js=""
    hevy_radar_js=""
    if has_hevy:
        hevy_js=(
            "const hD="+hevy_data_json+";\n"
            "let exC=null,setsC=null;\n"
            "function updateExChart(){\n"
            "  const ex=document.getElementById('exSelect').value;\n"
            "  const d=hD[ex]||{dates:[],max_weights:[],volumes:[],sets:[],reps:[]};\n"
            "  if(exC)exC.destroy();\n"
            "  exC=new Chart('cExEvo',{type:'line',\n"
            "    data:{labels:d.dates,datasets:[\n"
            "      {label:'Charge max (kg)',data:d.max_weights,borderColor:'#bc8cff',"
            "backgroundColor:'rgba(188,140,255,0.1)',tension:.35,fill:true,yAxisID:'y',"
            "pointRadius:4,pointHoverRadius:7,pointBackgroundColor:'#bc8cff'},\n"
            "      {label:'Volume (kg×reps)',data:d.volumes,borderColor:'#FC4C02',"
            "backgroundColor:'rgba(252,76,2,0.05)',tension:.35,fill:false,yAxisID:'y1',"
            "borderDash:[4,3]}\n"
            "    ]},\n"
            "    options:{responsive:true,maintainAspectRatio:false,\n"
            "      plugins:{legend:{position:'bottom',labels:{color:'#8b949e'}}},"
            "      scales:{x:{grid:{color:gc},ticks:{maxRotation:45,maxTicksLimit:18}},"
            "              y:{grid:{color:gc},title:{display:true,text:'kg',color:'#8b949e'}},"
            "              y1:{grid:{drawOnChartArea:false},position:'right',"
            "                  title:{display:true,text:'vol.',color:'#8b949e'}}}}});\n"
            "  if(setsC)setsC.destroy();\n"
            "  setsC=new Chart('cExSets',{type:'bar',\n"
            "    data:{labels:d.dates,datasets:[\n"
            "      {label:'Séries',data:d.sets,backgroundColor:'rgba(88,166,255,0.7)',borderRadius:3,yAxisID:'y'},\n"
            "      {label:'Reps',data:d.reps,backgroundColor:'rgba(252,76,2,0.5)',borderRadius:3,yAxisID:'y1'}\n"
            "    ]},\n"
            "    options:{responsive:true,maintainAspectRatio:false,\n"
            "      plugins:{legend:{position:'bottom',labels:{color:'#8b949e'}}},\n"
            "      scales:{x:{grid:{color:gc},ticks:{maxRotation:45,maxTicksLimit:18}},"
            "              y:{grid:{color:gc},ticks:{stepSize:1}},"
            "              y1:{grid:{drawOnChartArea:false},position:'right',ticks:{stepSize:5}}}}});\n"
            "}\n"
            "const firstEx=Object.keys(hD)[0];\n"
            "if(firstEx){document.getElementById('exSelect').value=firstEx;updateExChart();}\n"
        )
        hevy_vol_js=("new Chart('cHVol',{type:'bar',data:{labels:"+json.dumps(mlabels)
            +",datasets:[{label:'Volume (kg)',data:"+json.dumps(hevy_vol_monthly)
            +",backgroundColor:'rgba(188,140,255,0.7)',borderColor:'#bc8cff',borderWidth:1,borderRadius:5}]},"
            +"options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},"
            +"scales:{x:{grid:{color:gc}},y:{grid:{color:gc}}}}});\n")
        if radar_data:
            hevy_radar_js=("new Chart('cRadar',{type:'radar',data:{labels:"+json.dumps(mg_names)
                +",datasets:[{label:'Volume relatif',data:"+json.dumps(radar_data)
                +",backgroundColor:'rgba(188,140,255,0.15)',borderColor:'#bc8cff',"
                +"pointBackgroundColor:'#bc8cff',pointRadius:4}]},"
                +"options:{responsive:true,maintainAspectRatio:false,"
                +"plugins:{legend:{display:false}},"
                +"scales:{r:{grid:{color:'rgba(255,255,255,0.08)'},ticks:{display:false},"
                +"pointLabels:{color:'#8b949e',font:{size:11}}}}}});\n")

    hevy_section=""
    if not os.path.exists(HEVY_CSV_PATH):
        hevy_section=("<div class='info-box'>📂 <b>Ajoute workouts.csv</b> (export Hevy) à la racine de ton repo GitHub pour voir tes progressions.</div>")
    elif not hevy_sessions:
        hevy_section=("<div class='info-box'>⚠️ Aucune séance Hevy trouvée dans workouts.csv depuis le 1er septembre 2025.</div>")

    # ── Build HTML ────────────────────────────────────────────────────────────
    html=("""<!DOCTYPE html>
<html lang="fr"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>🏅 Sport Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>"""+CSS+"""</style>
</head><body>

<header>
  <h1>🏅 Sport <span>Dashboard</span></h1>
  <div class="hr">
    <div><span class="pulse"></span>"""+str(total)+""" activités · depuis 01/09/2025</div>
    <div>Mis à jour """+now_str+"""</div>
  </div>
</header>

<div class="tabs">
  <button class="tab active" onclick="show('overview',this)">📊 Vue d'ensemble</button>
  <button class="tab" onclick="show('muscu',this)">💪 Musculation</button>
  <button class="tab" onclick="show('records',this)">🏆 Records & Objectifs</button>
  <button class="tab" onclick="show('padel',this)">🎾 Padel & Sports</button>
  <button class="tab" onclick="show('cardio',this)">🏃 Cardio</button>
  <button class="tab" onclick="show('all',this)">📋 Toutes</button>
</div>

<!-- ═══════════════ OVERVIEW ═══════════════ -->
<div id="overview" class="section active">
  <div class="kpis">
    <div class="kpi"><div class="kv">"""+str(total)+"""</div><div class="kl">Séances totales</div></div>
    <div class="kpi blue"><div class="kv">"""+str(int(total_dist))+"""<small> km</small></div><div class="kl">Distance</div></div>
    <div class="kpi"><div class="kv">"""+fmt_dur(total_time)+"""</div><div class="kl">Temps total</div></div>
    <div class="kpi green"><div class="kv">"""+"{:,}".format(int(total_cal))+"""</div><div class="kl">Calories</div></div>
    <div class="kpi blue"><div class="kv">"""+str(int(total_elev))+"""<small> m</small></div><div class="kl">Dénivelé +</div></div>
    <div class="kpi"><div class="kv">"""+str(apw)+"""</div><div class="kl">Séances / sem.</div></div>
    <div class="kpi green"><div class="kv">"""+str(cur_streak)+"""</div><div class="kl">Streak actuel</div></div>
    <div class="kpi"><div class="kv">"""+str(mx_streak)+"""</div><div class="kl">Streak max</div></div>
  </div>

  <div class="card"><h2><span class="icon">📅</span> Calendrier d'activité</h2>
    <div class="heatmap-wrap">
      <div class="heatmap">"""+hm_cols+"""</div>
    </div>
    <div style="font-size:.68rem;color:var(--t3);margin-top:.6rem">"""+hm_legend+"""</div>
  </div>

  <div class="grid2">
    <div class="card"><h2><span class="icon">📅</span> Activités par mois</h2><div class="ch ch-md"><canvas id="cM"></canvas></div></div>
    <div class="card"><h2><span class="icon">🥧</span> Répartition par sport</h2>
      <div class="dw"><div class="dc"><canvas id="cDo"></canvas></div><div class="leg">"""+leg+"""</div></div>
    </div>
  </div>

  <div class="card"><h2><span class="icon">📆</span> Fréquence hebdomadaire</h2><div class="ch ch-md"><canvas id="cW"></canvas></div></div>

  <div class="grid2">
    <div class="card"><h2><span class="icon">⚡</span> Cette semaine</h2>"""+week_html+"""</div>
    <div class="card"><h2><span class="icon">🕐</span> Activités récentes</h2>"""+recent_items+"""</div>
  </div>

  <div class="grid2">
    <div class="card"><h2><span class="icon">🏆</span> Par sport</h2>"""+sport_rows+"""</div>
    <div class="card"><h2><span class="icon">💪</span> Records de charge</h2>"""+pr_rows+"""</div>
  </div>
</div>

<!-- ═══════════════ MUSCULATION ═══════════════ -->
<div id="muscu" class="section">
  <div class="kpis">
    <div class="kpi"><div class="kv">"""+str(len(hevy_sessions))+"""</div><div class="kl">Séances (Hevy)</div></div>
    <div class="kpi"><div class="kv">"""+str(hevy_total_sets)+"""</div><div class="kl">Séries totales</div></div>
    <div class="kpi blue"><div class="kv">"""+str(hevy_total_vol)+"""<small> t</small></div><div class="kl">Volume soulevé</div></div>
    <div class="kpi"><div class="kv">"""+str(hevy_avg_sets)+"""</div><div class="kl">Séries / séance</div></div>
    <div class="kpi purple"><div class="kv">"""+str(len(hevy_exercises))+"""</div><div class="kl">Exercices</div></div>
    <div class="kpi"><div class="kv">"""+str(wt_total)+"""</div><div class="kl">Séances (Strava)</div></div>
    <div class="kpi"><div class="kv">"""+fmt_dur(wt_time)+"""</div><div class="kl">Temps total</div></div>
    <div class="kpi green"><div class="kv">"""+"{:,}".format(int(wt_cal))+"""</div><div class="kl">Calories</div></div>
  </div>

  """+hevy_section+"""

  """+("" if not has_hevy else """
  <div class="card"><h2><span class="icon">📈</span> Progression par exercice</h2>
    <select class="ex-select" id="exSelect" onchange="updateExChart()">"""+ex_options+"""</select>
    <div class="grid2">
      <div><div class="ch ch-lg"><canvas id="cExEvo"></canvas></div></div>
      <div><div class="ch ch-lg"><canvas id="cExSets"></canvas></div></div>
    </div>
  </div>

  <div class="grid2">
    <div class="card"><h2><span class="icon">🏋️</span> Volume mensuel soulevé (kg)</h2><div class="ch ch-md"><canvas id="cHVol"></canvas></div></div>
    """+("" if not radar_data else """<div class="card"><h2><span class="icon">🕸️</span> Répartition musculaire (volume)</h2><div class="ch ch-md"><canvas id="cRadar"></canvas></div></div>""")+"""
  </div>
  """)+"""

  <div class="grid2">
    <div class="card"><h2><span class="icon">💪</span> Charges max par exercice</h2>"""+max_w_bars+"""</div>
    <div class="card"><h2><span class="icon">💪</span> Groupes musculaires (séances)</h2>"""+mg_bars+"""</div>
  </div>

  <div class="card"><h2><span class="icon">⏱️</span> Durée & Calories par séance (30 dernières)</h2><div class="ch ch-lg"><canvas id="cWTD"></canvas></div></div>

  """+("" if not has_hevy else """
  <div class="card"><h2><span class="icon">📋</span> Séances Hevy (25 dernières)</h2>
    <div style="overflow-x:auto"><table>
      <thead><tr><th>Date</th><th>Titre</th><th>Séries</th><th>Volume</th><th>Exercices</th></tr></thead>
      <tbody>"""+hevy_sess_rows+"""</tbody>
    </table></div>
  </div>
  """)+"""

  <div class="card"><h2><span class="icon">📋</span> Séances Strava</h2>
    <div style="overflow-x:auto"><table>
      <thead><tr><th>Date</th><th>Nom</th><th>Groupes</th><th>Durée</th><th>Cal.</th><th>FC moy</th><th>FC max</th></tr></thead>
      <tbody>"""+wt_rows+"""</tbody>
    </table></div>
  </div>
</div>

<!-- ═══════════════ RECORDS & OBJECTIFS ═══════════════ -->
<div id="records" class="section">
  <div class="kpis">
    <div class="kpi"><div class="kv">"""+str(len(all_ex_maxes))+"""</div><div class="kl">Exercices trackés</div></div>
    <div class="kpi blue"><div class="kv">"""+str(len([k for k,v in GOALS.items() if k in all_ex_maxes and all_ex_maxes[k]>=v[0]]))+"""</div><div class="kl">Objectifs CT atteints</div></div>
    <div class="kpi green"><div class="kv">"""+str(len([k for k,v in GOALS.items() if k in all_ex_maxes and all_ex_maxes[k]>=v[1]]))+"""</div><div class="kl">Objectifs MT atteints</div></div>
    <div class="kpi purple"><div class="kv">"""+str(len([k for k,v in GOALS.items() if k in all_ex_maxes and all_ex_maxes[k]>=v[2]]))+"""</div><div class="kl">Objectifs LT atteints</div></div>
  </div>
  <div class="info-box">
    🎯 <b>Court terme</b> = 1-3 mois &nbsp;·&nbsp; <b>Moyen terme</b> = 6 mois &nbsp;·&nbsp; <b>Long terme</b> = 12+ mois<br>
    Pour modifier tes objectifs : édite le dictionnaire <code>GOALS</code> en haut de <code>api/index.py</code>.
  </div>
  """+goal_rows+"""
</div>

<!-- ═══════════════ PADEL & SPORTS ═══════════════ -->
<div id="padel" class="section">
  <div class="kpis">
    <div class="kpi"><div class="kv">"""+str(padel_total)+"""</div><div class="kl">Sessions padel</div></div>
    <div class="kpi"><div class="kv">"""+str(padel_avg)+"""</div><div class="kl">Sessions / mois</div></div>
    <div class="kpi"><div class="kv">"""+str(padel_record)+"""</div><div class="kl">Record mensuel</div></div>
    <div class="kpi"><div class="kv">"""+str(padel_tournois)+"""</div><div class="kl">Tournois</div></div>
    <div class="kpi blue"><div class="kv">"""+fmt_dur(padel_time)+"""</div><div class="kl">Temps total</div></div>
    <div class="kpi green"><div class="kv">"""+str(len(esc_acts))+"""</div><div class="kl">Escalade</div></div>
    <div class="kpi"><div class="kv">"""+str(len(sq_acts))+"""</div><div class="kl">Squash</div></div>
    <div class="kpi purple"><div class="kv">"""+str(len(pis_acts))+"""</div><div class="kl">Piscine</div></div>
  </div>

  <div class="grid2">
    <div class="card"><h2><span class="icon">🎾</span> Sessions padel par mois</h2><div class="ch ch-md"><canvas id="cPM"></canvas></div></div>
    <div class="card"><h2><span class="icon">📋</span> Padel — Historique</h2>
      <div style="max-height:380px;overflow-y:auto"><table>
        <thead><tr><th>Date</th><th>Session</th></tr></thead>
        <tbody>"""+padel_rows+"""</tbody>
      </table></div>
    </div>
  </div>

  <div class="card"><h2><span class="icon">🧗</span> Escalade · Squash · Piscine</h2>
    <div style="overflow-x:auto"><table>
      <thead><tr><th>Date</th><th>Activité</th><th>Sport</th></tr></thead>
      <tbody>"""+other_rows+"""</tbody>
    </table></div>
  </div>
</div>

<!-- ═══════════════ CARDIO ═══════════════ -->
<div id="cardio" class="section">
  <div class="kpis">
    <div class="kpi"><div class="kv">"""+str(len(run_acts))+"""</div><div class="kl">Courses</div></div>
    <div class="kpi blue"><div class="kv">"""+str(round(total_run_dist,0))+"""<small> km</small></div><div class="kl">Total course</div></div>
    <div class="kpi"><div class="kv">"""+str(round(best_run_dist,1))+"""<small> km</small></div><div class="kl">Record distance</div></div>
    <div class="kpi"><div class="kv">"""+str(len(ride_acts))+"""</div><div class="kl">Sorties vélo</div></div>
    <div class="kpi blue"><div class="kv">"""+str(round(total_ride_dist,0))+"""<small> km</small></div><div class="kl">Total vélo</div></div>
  </div>

  """+run_card+ride_card+"""

  <div class="card"><h2><span class="icon">📋</span> Activités cardio</h2>
    <div style="overflow-x:auto"><table>
      <thead><tr><th>Date</th><th>Activité</th><th>Dist.</th><th>Durée</th><th>Allure</th><th>FC moy</th><th>Cal.</th><th>D+</th></tr></thead>
      <tbody>"""+cardio_rows+"""</tbody>
    </table></div>
  </div>
</div>

<!-- ═══════════════ TOUTES ═══════════════ -->
<div id="all" class="section">
  <div class="card"><h2><span class="icon">📋</span> Toutes les activités ("""+str(total)+""")</h2>
    <div style="overflow-x:auto"><table>
      <thead><tr><th>Date</th><th>Activité</th><th>Sport</th><th>Dist.</th><th>Durée</th><th>FC moy</th><th>FC max</th><th>Cal.</th><th>D+</th></tr></thead>
      <tbody>"""+all_rows+"""</tbody>
    </table></div>
  </div>
</div>

<script>
Chart.defaults.color='#8b949e';
Chart.defaults.font={family:'-apple-system,BlinkMacSystemFont,"SF Pro",sans-serif',size:11};
const gc='rgba(255,255,255,0.05)';

function show(id,btn){
  document.querySelectorAll('.section').forEach(s=>s.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  btn.classList.add('active');
}

// Overview charts
new Chart('cM',{type:'bar',data:{labels:"""+json.dumps(mlabels)+""",datasets:[{label:'Séances',data:"""+json.dumps(mc_counts)+""",backgroundColor:'rgba(252,76,2,.75)',borderColor:'#FC4C02',borderWidth:1,borderRadius:6}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{grid:{color:gc}},y:{grid:{color:gc},ticks:{stepSize:1}}}}});

new Chart('cDo',{type:'doughnut',data:{labels:"""+json.dumps(tl)+""",datasets:[{data:"""+json.dumps(tn)+""",backgroundColor:"""+json.dumps(tc)+""",borderWidth:2,borderColor:'#0d1117'}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},cutout:'68%'}});

new Chart('cW',{type:'bar',data:{labels:"""+json.dumps(wl)+""",datasets:[{label:'Séances',data:"""+json.dumps(wn)+""",backgroundColor:ctx=>ctx.raw>=6?'#FC4C02':ctx.raw>=4?'#F5A623':ctx.raw>=2?'#58a6ff':'rgba(88,166,255,0.4)',borderRadius:4}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{grid:{color:gc},ticks:{maxRotation:0,maxTicksLimit:22}},y:{grid:{color:gc},ticks:{stepSize:1}}}}});

// Muscu charts
new Chart('cWTD',{type:'line',data:{labels:"""+json.dumps(wt_dates)+""",datasets:[{label:'Durée (min)',data:"""+json.dumps(wt_dur_d)+""",borderColor:'#bc8cff',backgroundColor:'rgba(188,140,255,0.1)',tension:.3,fill:true,yAxisID:'y'},{label:'Calories',data:"""+json.dumps(wt_cal_d)+""",borderColor:'#FC4C02',backgroundColor:'rgba(252,76,2,0.05)',tension:.3,fill:false,yAxisID:'y1',borderDash:[4,3]}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom'}},scales:{x:{grid:{color:gc},ticks:{maxRotation:45,maxTicksLimit:15}},y:{grid:{color:gc},position:'left'},y1:{grid:{drawOnChartArea:false},position:'right'}}}});

// Padel chart
new Chart('cPM',{type:'bar',data:{labels:"""+json.dumps(mlabels)+""",datasets:[{label:'Sessions',data:"""+json.dumps(padel_monthly)+""",backgroundColor:'rgba(231,76,60,.75)',borderColor:'#E74C3C',borderWidth:1,borderRadius:6}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{grid:{color:gc}},y:{grid:{color:gc},ticks:{stepSize:1}}}}});

"""+run_js+ride_js+hevy_js+hevy_vol_js+hevy_radar_js+"""
</script>
</body></html>""")
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
        return Response("<pre style='padding:2rem;color:#fff;background:#0d1117;font-size:12px'>"
                        +traceback.format_exc()+"</pre>", status=500, mimetype="text/html")

@app.route("/debug/hevy")
def debug_hevy():
    try:
        w=read_hevy_csv(); ex,sess=parse_hevy_data(w)
        first=None
        if w:
            fw=w[0]; first={"title":fw["title"],"date":str(fw["_dt"].date()),
                            "exercises":[{"name":ex2["title"],"sets":len(ex2["sets"])} for ex2 in fw["exercises"]]}
        return Response(json.dumps({"csv_found":os.path.exists(HEVY_CSV_PATH),
                                    "total_workouts":len(w),"total_exercises":len(ex),
                                    "first_workout":first},indent=2,ensure_ascii=False),
                        mimetype="application/json")
    except Exception as ex2:
        import traceback
        return Response(json.dumps({"error":str(ex2),"trace":traceback.format_exc()}),
                        mimetype="application/json")

@app.route("/debug/wt")
def debug_wt():
    try:
        token=get_access_token(); acts=fetch_activities(token)
        wt=[a for a in acts if a.get("type")=="WeightTraining"]
        if not wt: return Response('{"error":"no WeightTraining"}',mimetype="application/json")
        return Response(json.dumps(fetch_detail(token,wt[0]["id"]),indent=2,ensure_ascii=False),
                        mimetype="application/json")
    except Exception as ex:
        return Response(json.dumps({"error":str(ex)}),mimetype="application/json")

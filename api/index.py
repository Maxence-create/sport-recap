from flask import Flask, Response, redirect, request
import os, json, urllib.request, urllib.parse, time
from datetime import datetime, timezone
from collections import defaultdict

app = Flask(__name__)

CLIENT_ID     = os.environ["STRAVA_CLIENT_ID"]
CLIENT_SECRET = os.environ["STRAVA_CLIENT_SECRET"]
REFRESH_TOKEN = os.environ["STRAVA_REFRESH_TOKEN"]
START_DATE    = datetime(2025, 9, 1, tzinfo=timezone.utc)

def get_access_token():
    data = urllib.parse.urlencode({
        "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
        "grant_type": "refresh_token", "refresh_token": REFRESH_TOKEN
    }).encode()
    req = urllib.request.Request(
        "https://www.strava.com/oauth/token", data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())["access_token"]

def fetch_activities(token):
    start_ts = int(START_DATE.timestamp())
    activities, page = [], 1
    while True:
        url = (f"https://www.strava.com/api/v3/athlete/activities"
               f"?after={start_ts}&per_page=100&page={page}")
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=15) as r:
            batch = json.loads(r.read())
        if not batch: break
        activities.extend(batch)
        page += 1
    return activities

def fmt_dur(s):
    h, m = divmod(s // 60, 60)
    return f"{int(h)}h{int(m):02d}" if h else f"{int(m)} min"

EMOJIS = {"Run":"🏃","Ride":"🚴","Swim":"🏊","Walk":"🚶","Hike":"🥾",
          "WeightTraining":"🏋️","Yoga":"🧘","Workout":"💪","VirtualRide":"🚴",
          "VirtualRun":"🏃","Soccer":"⚽","Tennis":"🎾","Crossfit":"🔥",
          "EBikeRide":"⚡","Rowing":"🚣","Skiing":"⛷️","Basketball":"🏀"}
LABELS = {"Run":"Course","Ride":"Vélo","Swim":"Natation","Walk":"Marche",
          "Hike":"Randonnée","WeightTraining":"Muscu","Yoga":"Yoga",
          "Workout":"Entraînement","VirtualRide":"Vélo virtuel",
          "EBikeRide":"Vélo élec.","Soccer":"Football","Tennis":"Tennis",
          "Crossfit":"CrossFit","Rowing":"Aviron","Skiing":"Ski"}
COLORS = {"Run":"#FC4C02","Ride":"#F5A623","Swim":"#4A90D9","Walk":"#7ED321",
          "Hike":"#50C878","WeightTraining":"#9B59B6","Yoga":"#E91E63",
          "Workout":"#FF6B35","VirtualRide":"#F39C12","EBikeRide":"#2ECC71",
          "Soccer":"#27AE60","Tennis":"#F1C40F","Crossfit":"#E74C3C",
          "Rowing":"#1ABC9C","Skiing":"#3498DB"}

def e(t): return EMOJIS.get(t,"🏅")
def l(t): return LABELS.get(t,t)
def c(t): return COLORS.get(t,"#95A5A6")

def build_html(activities):
    total      = len(activities)
    total_dist = sum(a.get("distance",0) for a in activities)/1000
    total_time = sum(a.get("moving_time",0) for a in activities)
    total_elev = sum(a.get("total_elevation_gain",0) for a in activities)
    total_cal  = sum(a.get("calories",0) or 0 for a in activities)

    by_type  = defaultdict(list)
    by_month = defaultdict(list)
    by_week  = defaultdict(list)

    for a in activities:
        dt = datetime.fromisoformat(a["start_date_local"].replace("Z","+00:00"))
        by_type[a["type"]].append(a)
        by_month[(dt.year,dt.month)].append(a)
        by_week[f"{dt.year}-{dt.isocalendar()[1]:02d}"].append(a)

    now = datetime.now()
    mkeys, mlabels = [], []
    y,m = 2025,9
    while (y,m)<=(now.year,now.month):
        mkeys.append((y,m))
        mlabels.append(f"{'Jan Fév Mar Avr Mai Jun Jul Aoû Sep Oct Nov Déc'.split()[m-1]} {str(y)[2:]}")
        m+=1
        if m>12: m,y=1,y+1

    mc = [len(by_month.get(k,[])) for k in mkeys]
    md = [round(sum(a.get("distance",0) for a in by_month.get(k,[]))/1000,1) for k in mkeys]
    mt = [round(sum(a.get("moving_time",0) for a in by_month.get(k,[]))/3600,1) for k in mkeys]

    tl = [l(t) for t in by_type]
    tn = [len(v) for v in by_type.values()]
    tc = [c(t) for t in by_type]

    ws = sorted(by_week.keys())
    wl = [f"S{k.split('-')[1]}" for k in ws]
    wn = [len(by_week[k]) for k in ws]

    act_days = sorted(set(
        datetime.fromisoformat(a["start_date_local"].replace("Z","+00:00")).date()
        for a in activities))
    mx,cu=1,1
    for i in range(1,len(act_days)):
        if (act_days[i]-act_days[i-1]).days==1: cu+=1; mx=max(mx,cu)
        else: cu=1
    if not act_days: mx=0
    apw = round(total/max(len(by_week),1),1)

    recent = sorted(activities,key=lambda x:x["start_date_local"],reverse=True)[:25]
    rows=""
    for a in recent:
        dt=datetime.fromisoformat(a["start_date_local"].replace("Z","+00:00"))
        d=f"{a.get('distance',0)/1000:.1f} km" if a.get("distance",0)>100 else "—"
        ev=f"+{int(a.get('total_elevation_gain',0))} m" if a.get("total_elevation_gain",0)>1 else "—"
        rows+=(f"<tr><td>{dt.strftime('%d/%m/%y')}</td>"
               f"<td>{e(a['type'])} {a.get('name','—')}</td>"
               f"<td><span class='badge' style='background:{c(a['type'])}'>{l(a['type'])}</span></td>"
               f"<td>{d}</td><td>{fmt_dur(a.get('moving_time',0))}</td><td>{ev}</td></tr>")

    sports_html=""
    for t,acts in sorted(by_type.items(),key=lambda x:-len(x[1])):
        dist=sum(a.get("distance",0) for a in acts)/1000
        sec=sum(a.get("moving_time",0) for a in acts)
        sports_html+=(f"<div class='sport-row'><span class='si'>{e(t)}</span>"
            f"<div class='sinfo'><div class='sn'>{l(t)}</div>"
            f"<div class='ss'>{fmt_dur(sec)}{f' · {dist:.0f} km' if dist>0 else ''}</div></div>"
            f"<span class='sc' style='color:{c(t)}'>{len(acts)}</span></div>")

    leg="".join(f"<div class='li'><span class='ld' style='background:{c(t)}'></span>{l(t)} <b>({len(acts)})</b></div>"
                for t,acts in sorted(by_type.items(),key=lambda x:-len(x[1])))

    now_str=datetime.now().strftime("%d/%m/%Y à %H:%M")

    return f"""<!DOCTYPE html>
<html lang="fr"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>🏅 Sport Récap</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root{{--bg:#0f0f13;--s1:#1a1a24;--s2:#22222f;--bd:#2e2e3e;--tx:#e8e8f0;--t2:#8888aa;--or:#FC4C02;--ac:#6366f1}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--tx);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}}
header{{background:linear-gradient(135deg,#1a0804,#0f0f13);border-bottom:1px solid var(--bd);padding:1.2rem 2rem;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:.5rem}}
header h1{{font-size:1.5rem;font-weight:800}}header h1 span{{color:var(--or)}}
.hr{{text-align:right;font-size:.78rem;color:var(--t2)}}
.wrap{{max-width:1300px;margin:0 auto;padding:1.5rem;display:grid;grid-template-columns:1fr 280px;gap:1.5rem}}
@media(max-width:900px){{.wrap{{grid-template-columns:1fr}}}}
.main{{display:flex;flex-direction:column;gap:1.5rem}}
.side{{display:flex;flex-direction:column;gap:1.5rem}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:.8rem}}
@media(max-width:700px){{.kpis{{grid-template-columns:repeat(2,1fr)}}}}
.kpi{{background:var(--s1);border:1px solid var(--bd);border-radius:14px;padding:1.1rem;text-align:center;transition:transform .15s}}
.kpi:hover{{transform:translateY(-2px)}}
.kv{{font-size:1.7rem;font-weight:800;color:var(--or);line-height:1}}.kv small{{font-size:.9rem}}
.kl{{font-size:.72rem;color:var(--t2);margin-top:.3rem;text-transform:uppercase;letter-spacing:.04em}}
.card{{background:var(--s1);border:1px solid var(--bd);border-radius:14px;padding:1.3rem}}
.card h2{{font-size:.95rem;font-weight:700;margin-bottom:1rem}}
.ch{{position:relative;height:220px}}.ch-sm{{height:180px}}
.sport-row{{display:flex;align-items:center;gap:.8rem;padding:.6rem 0;border-bottom:1px solid var(--bd)}}
.sport-row:last-child{{border:none}}
.si{{font-size:1.5rem;width:2rem;text-align:center}}.sinfo{{flex:1}}
.sn{{font-weight:600;font-size:.88rem}}.ss{{font-size:.75rem;color:var(--t2);margin-top:.1rem}}
.sc{{font-size:1.4rem;font-weight:800}}
.dw{{display:flex;flex-direction:column;gap:.8rem;align-items:center}}
.dc{{position:relative;height:160px;width:160px}}
.leg{{display:flex;flex-direction:column;gap:.3rem;width:100%}}
.li{{font-size:.8rem;display:flex;align-items:center;gap:.5rem}}
.ld{{width:9px;height:9px;border-radius:50%;flex-shrink:0}}
table{{width:100%;border-collapse:collapse;font-size:.82rem}}
th{{color:var(--t2);font-weight:600;padding:.5rem .6rem;text-align:left;border-bottom:1px solid var(--bd);font-size:.72rem;text-transform:uppercase;letter-spacing:.04em;white-space:nowrap}}
td{{padding:.55rem .6rem;border-bottom:1px solid var(--bd)}}
tr:last-child td{{border:none}}tr:hover td{{background:var(--s2)}}
.badge{{display:inline-block;padding:.15rem .5rem;border-radius:20px;font-size:.68rem;font-weight:600;color:#fff;white-space:nowrap}}
</style></head><body>
<header>
  <h1>🏅 Sport <span>Récap</span></h1>
  <div class="hr"><div>{total} activités · depuis le 01/09/2025</div><div>Mis à jour {now_str}</div></div>
</header>
<div class="wrap">
<div class="main">
  <div class="kpis">
    <div class="kpi"><div class="kv">{total}</div><div class="kl">Séances</div></div>
    <div class="kpi"><div class="kv">{total_dist:.0f}<small> km</small></div><div class="kl">Distance</div></div>
    <div class="kpi"><div class="kv">{fmt_dur(total_time)}</div><div class="kl">Temps actif</div></div>
    <div class="kpi"><div class="kv">{total_elev:.0f}<small> m</small></div><div class="kl">Dénivelé +</div></div>
    <div class="kpi"><div class="kv">{int(total_cal):,}</div><div class="kl">Calories</div></div>
    <div class="kpi"><div class="kv">{apw}</div><div class="kl">Séances/sem.</div></div>
    <div class="kpi"><div class="kv">{mx}</div><div class="kl">Streak max</div></div>
    <div class="kpi"><div class="kv">{len(by_type)}</div><div class="kl">Sports</div></div>
  </div>
  <div class="card"><h2>📅 Activités par mois</h2><div class="ch"><canvas id="cM"></canvas></div></div>
  <div class="card"><h2>📏 Distance &amp; temps par mois</h2><div class="ch"><canvas id="cD"></canvas></div></div>
  <div class="card"><h2>📆 Fréquence par semaine</h2><div class="ch ch-sm"><canvas id="cW"></canvas></div></div>
  <div class="card"><h2>🕐 Dernières activités</h2>
    <table><thead><tr><th>Date</th><th>Activité</th><th>Sport</th><th>Dist.</th><th>Durée</th><th>D+</th></tr></thead>
    <tbody>{rows}</tbody></table>
  </div>
</div>
<div class="side">
  <div class="card"><h2>🥧 Par sport</h2>
    <div class="dw"><div class="dc"><canvas id="cDo"></canvas></div><div class="leg">{leg}</div></div>
  </div>
  <div class="card"><h2>🏆 Détail</h2>{sports_html}</div>
</div>
</div>
<script>
Chart.defaults.color='#8888aa';
Chart.defaults.font={{family:'-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif',size:11}};
const g='rgba(255,255,255,0.06)';
new Chart(document.getElementById('cM'),{{type:'bar',data:{{labels:{json.dumps(mlabels)},datasets:[{{label:'Séances',data:{json.dumps(mc)},backgroundColor:'#FC4C02cc',borderColor:'#FC4C02',borderWidth:1,borderRadius:5}}]}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:false}}}},scales:{{x:{{grid:{{color:g}}}},y:{{grid:{{color:g}},ticks:{{stepSize:1}}}}}}}}  }});
new Chart(document.getElementById('cD'),{{type:'line',data:{{labels:{json.dumps(mlabels)},datasets:[{{label:'Distance (km)',data:{json.dumps(md)},borderColor:'#FC4C02',backgroundColor:'rgba(252,76,2,0.1)',tension:.3,fill:true,yAxisID:'y'}},{{label:'Temps (h)',data:{json.dumps(mt)},borderColor:'#6366f1',backgroundColor:'rgba(99,102,241,0.1)',tension:.3,fill:true,yAxisID:'y1'}}]}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{position:'bottom'}}}},scales:{{x:{{grid:{{color:g}}}},y:{{grid:{{color:g}},position:'left',title:{{display:true,text:'km'}}}},y1:{{grid:{{drawOnChartArea:false}},position:'right',title:{{display:true,text:'h'}}}}}}}}  }});
new Chart(document.getElementById('cW'),{{type:'bar',data:{{labels:{json.dumps(wl)},datasets:[{{label:'Séances',data:{json.dumps(wn)},backgroundColor:ctx=>ctx.raw>4?'#FC4C02':ctx.raw>2?'#F5A623':'#6366f1',borderRadius:3}}]}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:false}}}},scales:{{x:{{grid:{{color:g}},ticks:{{maxRotation:0,maxTicksLimit:20}}}},y:{{grid:{{color:g}},ticks:{{stepSize:1}}}}}}}}  }});
new Chart(document.getElementById('cDo'),{{type:'doughnut',data:{{labels:{json.dumps(tl)},datasets:[{{data:{json.dumps(tn)},backgroundColor:{json.dumps(tc)},borderWidth:2,borderColor:'#1a1a24'}}]}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:c=>` ${{c.label}}: ${{c.raw}}`}}}}}},cutout:'65%'}}  }});
</script>
</body></html>"""

@app.route("/")
@app.route("/index")
def dashboard():
    try:
        token = get_access_token()
        activities = fetch_activities(token)
        html = build_html(activities)
        return Response(html, mimetype="text/html")
    except Exception as ex:
        return Response(f"<h2>Erreur : {ex}</h2>", status=500, mimetype="text/html")

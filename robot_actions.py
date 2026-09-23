"""
Robot de trading actions PEA — croisement de moyennes mobiles (SMA)
Aucun ordre réel. Quatre modes :
  "rapport"    : page HTML récapitulative (tableaux + courbes), ouverte dans le navigateur
  "backtest"   : Phase 1 — tableau texte 2016-2021 (réglage) / 2022-aujourd'hui (vérification)
  "robustesse" : Phase 2 — tableau texte de plusieurs réglages de moyennes mobiles
  "signaux"    : Phase 3 — ce que le robot ferait demain + journal CSV (à lancer après 17h35)

Installation :  pip install yfinance pandas
Lancement   :  python robot_actions.py
"""
import json
import os
import time
import webbrowser
from datetime import datetime

import pandas as pd
import yfinance as yf

# ---------- Paramètres ----------
# Le mode peut aussi être choisi sans modifier le fichier : ROBOT_MODE=signaux python robot_actions.py
MODE = os.environ.get("ROBOT_MODE", "rapport")   # "rapport", "backtest", "robustesse" ou "signaux"

ACTIONS = {         # ticker Yahoo Finance : (nom, catégorie)
    # Rendement élevé
    "BNP.PA":  ("BNP Paribas",   "Rendement"),
    "CS.PA":   ("AXA",           "Rendement"),
    "ORA.PA":  ("Orange",        "Rendement"),
    "ENGI.PA": ("Engie",         "Rendement"),
    # Rendement + plus-value
    "TTE.PA":  ("TotalEnergies", "Mixte"),
    "SAN.PA":  ("Sanofi",        "Mixte"),
    "ALV.DE":  ("Allianz",       "Mixte"),
    # Croissance
    "AI.PA":   ("Air Liquide",   "Croissance"),
    "SU.PA":   ("Schneider",     "Croissance"),
    "DG.PA":   ("Vinci",         "Croissance"),
    "AIR.PA":  ("Airbus",        "Croissance"),
}

DEBUT      = "2016-01-01"
COUPURE    = "2021-12-31"   # réglage avant, vérification après
SMA_COURTE = 20
SMA_LONGUE = 50
REGLAGES   = [(10, 30), (15, 40), (20, 50), (30, 100), (50, 200)]
CAPITAL    = 1000.0         # capital fictif par action
FRAIS      = 0.005          # 0,5 % par ordre (prudent)
STOP_LOSS  = 0.08           # 8 % sous le prix d'entrée
JOURNAL    = os.environ.get("ROBOT_JOURNAL", "journal_signaux.csv")
RAPPORT    = os.environ.get("ROBOT_RAPPORT", "rapport_robot.html")

_cache = {}


def charger(ticker):
    """Cours journaliers ajustés des dividendes (buy & hold = dividendes réinvestis)."""
    if ticker not in _cache:
        for essai in range(3):          # Yahoo refuse parfois une requête : on réessaie
            df = yf.Ticker(ticker).history(start=DEBUT, interval="1d", auto_adjust=True)
            if not df.empty:
                break
            time.sleep(5 * (essai + 1))
        if df.empty:
            raise ValueError("aucune donnée")
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        _cache[ticker] = df[["Open", "High", "Low", "Close"]].rename(columns=str.lower)
    return _cache[ticker].copy()


def ajouter_signaux(df, courte=SMA_COURTE, longue=SMA_LONGUE):
    df["sma_c"] = df["close"].rolling(courte).mean()
    df["sma_l"] = df["close"].rolling(longue).mean()
    df["haussier"] = df["sma_c"] > df["sma_l"]
    precedent = df["haussier"].shift(1, fill_value=False)
    df["achat"] = df["haussier"] & ~precedent
    df["vente"] = ~df["haussier"] & precedent
    return df


def backtest(df):
    """Signal à la clôture, exécution à l'ouverture du lendemain."""
    cash, qte, entree = CAPITAL, 0.0, 0.0
    trades, valeurs, points, ordre = [], [], [], None

    for date, l in df.iterrows():
        if ordre == "achat" and qte == 0:
            entree = l["open"]
            qte, cash = cash * (1 - FRAIS) / entree, 0.0
            points.append((date, entree, "achat"))
        elif ordre == "vente" and qte > 0:
            cash, qte = qte * l["open"] * (1 - FRAIS), 0.0
            trades.append(l["open"] / entree - 1)
            points.append((date, l["open"], "vente"))
        ordre = None

        if qte > 0:
            stop = entree * (1 - STOP_LOSS)
            if l["low"] <= stop:
                sortie = min(l["open"], stop)
                cash, qte = qte * sortie * (1 - FRAIS), 0.0
                trades.append(sortie / entree - 1)
                points.append((date, sortie, "stop"))

        if l["achat"]:
            ordre = "achat"
        elif l["vente"]:
            ordre = "vente"
        valeurs.append(cash + qte * l["close"])

    robot = pd.Series(valeurs, index=df.index)
    bh = df["close"] / df["close"].iloc[0]
    return {
        "robot": robot.iloc[-1] / CAPITAL - 1,
        "bh": bh.iloc[-1] - 1,
        "dd_robot": (robot / robot.cummax() - 1).min(),
        "dd_bh": (bh / bh.cummax() - 1).min(),
        "trades": len(trades),
        "gagnants": sum(t > 0 for t in trades),
        "courbe_robot": robot,
        "courbe_bh": bh * CAPITAL,
        "points": points,
    }


def verdict(r):
    """Robot utile s'il bat le buy & hold, ou s'il fait presque autant avec 2x moins de baisse."""
    return r["robot"] > r["bh"] or (r["robot"] > 0.8 * r["bh"] and r["dd_robot"] > r["dd_bh"] / 2)


def periodes(df):
    """Signaux calculés sur tout l'historique, puis découpés (les moyennes sont déjà 'chaudes')."""
    fin_reglage = int(COUPURE[:4])
    return {
        f"{DEBUT[:4]}-{fin_reglage}": df.loc[:COUPURE],
        f"{fin_reglage + 1}-auj.": df.loc[COUPURE:].iloc[1:],
    }


# ---------- Modes texte ----------

def lancer_backtest():
    print(f"Réglage SMA {SMA_COURTE}/{SMA_LONGUE}, frais {FRAIS:.1%}, stop {STOP_LOSS:.0%}\n")
    print(f"{'Action':14} {'Période':11} {'Robot':>8} {'B&H':>8} {'Baisse R':>9} {'Baisse BH':>10} {'Trades':>7} {'Gagn.':>6}  Verdict")
    bilan = {"robot": 0, "bh": 0}
    for ticker, (nom, _) in ACTIONS.items():
        try:
            df = ajouter_signaux(charger(ticker))
        except Exception as e:
            print(f"{nom:14} erreur : {e}")
            continue
        for label, part in periodes(df).items():
            r = backtest(part)
            gagne = verdict(r)
            if "auj" in label:
                bilan["robot" if gagne else "bh"] += 1
            print(f"{nom:14} {label:11} {r['robot']:>+8.0%} {r['bh']:>+8.0%} {r['dd_robot']:>9.0%} "
                  f"{r['dd_bh']:>10.0%} {r['trades']:>7} {r['gagnants']:>6}  {'✅ robot' if gagne else '❌ B&H'}")
    print(f"\nPériode de vérification : robot utile sur {bilan['robot']} action(s), "
          f"buy & hold meilleur sur {bilan['bh']}.")


def lancer_robustesse():
    print(f"Période de vérification ({int(COUPURE[:4]) + 1}-aujourd'hui) — écart robot vs buy & hold\n")
    print(f"{'Action':14}" + "".join(f"{f'{c}/{l}':>9}" for c, l in REGLAGES))
    for ticker, (nom, _) in ACTIONS.items():
        try:
            base = charger(ticker)
        except Exception as e:
            print(f"{nom:14} erreur : {e}")
            continue
        ligne = f"{nom:14}"
        for c, l in REGLAGES:
            r = backtest(list(periodes(ajouter_signaux(base.copy(), c, l)).values())[1])
            ligne += f"{r['robot'] - r['bh']:>+9.0%}"
        print(ligne)
    print("\nUn réglage fiable reste correct sur les colonnes voisines, pas sur une seule.")


def lancer_signaux():
    lignes = []
    for ticker, (nom, _) in ACTIONS.items():
        try:
            d = ajouter_signaux(charger(ticker)).iloc[-1]
        except Exception as e:
            print(f"{nom:14} erreur : {e}")
            continue
        if d["achat"]:
            action = "ACHETER"
        elif d["vente"]:
            action = "VENDRE"
        else:
            action = "rien (haussier)" if d["haussier"] else "rien (baissier)"
        print(f"{nom:14} {d['close']:>9.2f}  →  {action}")
        lignes.append({"date_signal": d.name.date(), "action": nom, "ticker": ticker,
                       "cloture": round(d["close"], 2), "signal": action,
                       "prix_execution": "", "notes": ""})
    if lignes:
        nouveau = pd.DataFrame(lignes)
        if os.path.exists(JOURNAL):     # pas de doublon si le script est relancé le même jour
            deja = pd.read_csv(JOURNAL, sep=";", dtype=str)
            cles = set(zip(deja["date_signal"], deja["ticker"]))
            nouveau = nouveau[[(str(d), t) not in cles for d, t in zip(nouveau["date_signal"], nouveau["ticker"])]]
        if nouveau.empty:
            print(f"\nSignaux déjà enregistrés dans {JOURNAL}.")
            return
        nouveau.to_csv(JOURNAL, mode="a", index=False, sep=";", header=not os.path.exists(JOURNAL))
        print(f"\nAjouté à {JOURNAL} ({datetime.now():%d/%m %H:%M}). "
              "Complétez 'prix_execution' avec l'ouverture du lendemain.")


# ---------- Rapport HTML ----------

def _liste(serie, dec=2):
    return [None if pd.isna(v) else round(float(v), dec) for v in serie]


def _stats(r):
    return {"robot": round(r["robot"] * 100, 1), "bh": round(r["bh"] * 100, 1),
            "ddRobot": round(r["dd_robot"] * 100, 1), "ddBh": round(r["dd_bh"] * 100, 1),
            "trades": r["trades"], "gagnants": r["gagnants"], "gagne": bool(verdict(r))}


def lancer_rapport():
    fin_reglage = int(COUPURE[:4])
    donnees = {
        "genere": f"{datetime.now():%d/%m/%Y à %H:%M}",
        "reglage": f"{SMA_COURTE}/{SMA_LONGUE}",
        "frais": FRAIS * 100, "stop": STOP_LOSS * 100, "capital": CAPITAL,
        "periodes": [f"{DEBUT[:4]} à {fin_reglage}", f"{fin_reglage + 1} à aujourd'hui"],
        "periodesCourts": list(periodes(pd.DataFrame(index=pd.DatetimeIndex([])))),
        "reglages": [f"{c}/{l}" for c, l in REGLAGES],
        "actions": [], "erreurs": [],
    }
    for ticker, (nom, cat) in ACTIONS.items():
        print(f"Calcul : {nom}…")
        try:
            base = charger(ticker)
        except Exception as e:
            donnees["erreurs"].append(f"{nom} ({ticker}) : {e}")
            continue
        df = ajouter_signaux(base.copy())
        complet = backtest(df)
        position = {d: i for i, d in enumerate(df.index)}
        robuste = []
        for c, l in REGLAGES:
            r = backtest(list(periodes(ajouter_signaux(base.copy(), c, l)).values())[1])
            robuste.append(round((r["robot"] - r["bh"]) * 100, 1))
        dernier = df.iloc[-1]
        if dernier["achat"]:
            signal = "achat"
        elif dernier["vente"]:
            signal = "vente"
        else:
            signal = "haussier" if dernier["haussier"] else "baissier"
        donnees["actions"].append({
            "ticker": ticker, "nom": nom, "cat": cat,
            "signal": signal, "dateSignal": f"{df.index[-1]:%d/%m/%Y}",
            "dernierCours": round(float(dernier["close"]), 2),
            "periodes": [_stats(backtest(p)) for p in periodes(df).values()],
            "robuste": robuste,
            "dates": [d.strftime("%Y-%m-%d") for d in df.index],
            "cours": _liste(df["close"]), "smaC": _liste(df["sma_c"]), "smaL": _liste(df["sma_l"]),
            "eqRobot": _liste(complet["courbe_robot"], 0), "eqBh": _liste(complet["courbe_bh"], 0),
            "ordres": [[position[d], round(float(p), 2), t] for d, p, t in complet["points"]],
            "coupure": int((df.index <= pd.Timestamp(COUPURE)).sum()),
        })

    html = MODELE_HTML.replace("__DONNEES__", json.dumps(donnees, ensure_ascii=False))
    os.makedirs(os.path.dirname(os.path.abspath(RAPPORT)), exist_ok=True)
    with open(RAPPORT, "w", encoding="utf-8") as f:
        f.write(html)
    chemin = os.path.abspath(RAPPORT)
    print(f"\nRapport enregistré : {chemin}")
    if not os.environ.get("CI"):        # pas de navigateur sur GitHub Actions
        webbrowser.open("file://" + chemin)


MODELE_HTML = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rapport du robot de trading</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Serif:wght@500&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root{
  --fond:#EDF1F4; --surface:#FFFFFF; --encre:#18212B; --doux:#5B6775; --ligne:#D5DCE3;
  --robot:#1D5FD1; --bh:#8E99A6; --gain:#1B8A5A; --perte:#C23B32; --stop:#C98210;
}
@media (prefers-color-scheme: dark){
  :root{ --fond:#12181F; --surface:#1A222C; --encre:#E7ECF1; --doux:#9AA6B3; --ligne:#2B3642;
         --robot:#6FA2FF; --bh:#6C7784; --gain:#43B883; --perte:#EE6B61; --stop:#E9A73A; }
}
*{box-sizing:border-box}
body{margin:0;background:var(--fond);color:var(--encre);
  font:16px/1.5 "IBM Plex Sans",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  font-variant-numeric:tabular-nums}
main{max-width:1080px;margin:0 auto;padding:32px 20px 64px}
h1{font-size:15px;font-weight:600;margin:0}
.reglages{color:var(--doux);margin:4px 0 0;font-size:14px}
.verdict{font-family:"IBM Plex Serif",Georgia,"Times New Roman",serif;font-weight:500;
  font-size:clamp(28px,5vw,44px);line-height:1.15;margin:32px 0 12px;max-width:24ch}
.explication{color:var(--doux);max-width:66ch;margin:0}
h2{font-size:20px;font-weight:600;margin:56px 0 4px}
.sous-titre{color:var(--doux);font-size:14px;margin:0 0 14px;max-width:70ch}
.defile{overflow-x:auto;background:var(--surface);border:1px solid var(--ligne);border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:14px;white-space:nowrap}
th,td{padding:10px 12px;text-align:right;border-bottom:1px solid var(--ligne)}
th:first-child,td:first-child{text-align:left}
th{font-weight:500;color:var(--doux);font-size:13px}
tbody tr:last-child td{border-bottom:0}
tr.cliquable{cursor:pointer}
th:first-child,td:first-child{position:sticky;left:0;background:var(--surface);z-index:1}
tr.cliquable:hover td,tr.actif td{background:color-mix(in srgb,var(--robot) 9%,var(--surface))}
tr.cliquable:focus-visible{outline:2px solid var(--robot);outline-offset:-2px}
.cat{display:block;color:var(--doux);font-size:12px}
.pos{color:var(--gain)} .neg{color:var(--perte)}
.badge{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:600}
.badge.oui{background:color-mix(in srgb,var(--gain) 16%,transparent);color:var(--gain)}
.badge.non{background:color-mix(in srgb,var(--bh) 22%,transparent);color:var(--doux)}
.entete-detail{display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end;justify-content:space-between;margin-top:56px}
.entete-detail h2{margin:0}
select{font:inherit;font-size:15px;padding:8px 12px;border-radius:8px;border:1px solid var(--ligne);
  background:var(--surface);color:var(--encre);min-width:200px}
.graph{background:var(--surface);border:1px solid var(--ligne);border-radius:10px;padding:18px 16px 12px;margin-top:16px}
.graph h3{font-size:15px;font-weight:600;margin:0}
.graph p{font-size:13px;color:var(--doux);margin:2px 0 10px}
.toile{position:relative;height:340px}
.mini{margin-top:16px}
td.chaleur{font-weight:500}
th.actuel{color:var(--encre)}
.ordres{background:var(--surface);border:1px solid var(--ligne);border-radius:10px;padding:18px 20px;margin-top:24px}
.ordres h2{margin:0}
.ordres .sous-titre{margin:2px 0 12px}
.ordre{display:flex;justify-content:space-between;gap:12px;padding:8px 0;border-top:1px solid var(--ligne)}
.ordre strong{font-weight:600}
.sens{font-weight:600}
.sens.achat{color:var(--gain)} .sens.vente{color:var(--perte)}
.tendances{font-size:14px;color:var(--doux);margin:12px 0 0}
.erreurs{margin-top:24px;padding:12px 16px;border-left:3px solid var(--perte);background:var(--surface);font-size:14px}
footer{margin-top:56px;color:var(--doux);font-size:13px;max-width:70ch}
@media (max-width:600px){ .toile{height:250px} main{padding-top:24px} }
</style>
</head>
<body>
<main>
  <header>
    <h1>Rapport du robot de trading</h1>
    <p class="reglages" id="reglages"></p>
  </header>

  <section class="ordres" id="ordres"></section>

  <p class="verdict" id="verdict"></p>
  <p class="explication" id="explication"></p>
  <div id="erreurs"></div>

  <h2>Toutes les actions</h2>
  <p class="sous-titre" id="sous-titre-tableau"></p>
  <div class="defile"><table>
    <thead><tr>
      <th>Action</th><th>Robot</th><th>Buy &amp; hold</th><th>Pire baisse robot</th>
      <th>Pire baisse B&amp;H</th><th>Trades gagnants</th><th id="th-p1"></th><th id="th-p2"></th>
    </tr></thead>
    <tbody id="tableau"></tbody>
  </table></div>

  <div class="entete-detail">
    <h2>Détail par action</h2>
    <label><span class="sr" hidden>Action</span><select id="choix" aria-label="Choisir une action"></select></label>
  </div>

  <section class="graph">
    <h3>Évolution du capital</h3>
    <p id="legende-capital"></p>
    <div class="toile"><canvas id="g-capital"></canvas></div>
  </section>

  <section class="graph">
    <h3>Cours, moyennes mobiles et ordres</h3>
    <p>▲ achat, ▼ vente sur signal, ✕ sortie par stop-loss. Zoomez en tournant le téléphone.</p>
    <div class="toile"><canvas id="g-cours"></canvas></div>
  </section>

  <div class="defile mini"><table>
    <thead><tr><th>Période</th><th>Robot</th><th>Buy &amp; hold</th><th>Pire baisse robot</th>
      <th>Pire baisse B&amp;H</th><th>Trades</th><th>Gagnants</th><th>Verdict</th></tr></thead>
    <tbody id="detail"></tbody>
  </table></div>

  <h2>Robustesse des réglages</h2>
  <p class="sous-titre" id="sous-titre-robuste"></p>
  <div class="defile"><table>
    <thead><tr id="tete-robuste"></tr></thead>
    <tbody id="robuste"></tbody>
  </table></div>

  <footer id="pied"></footer>
</main>

<script>
const D = __DONNEES__;
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const fr = (v, d = 0) => v.toLocaleString("fr-FR", {maximumFractionDigits: d, minimumFractionDigits: d});
const pct = v => (v > 0 ? "+" : "") + fr(v) + " %";
const signe = v => v > 0 ? "pos" : (v < 0 ? "neg" : "");
const badge = ok => `<span class="badge ${ok ? "oui" : "non"}">${ok ? "Robot" : "Buy & hold"}</span>`;
const [P1, P2] = D.periodes;

document.getElementById("reglages").textContent =
  `Généré le ${D.genere} — moyennes mobiles ${D.reglage}, frais ${fr(D.frais, 1)} % par ordre, stop-loss ${fr(D.stop)} %, ${fr(D.capital)} € fictifs par action.`;

if (D.erreurs.length) {
  document.getElementById("erreurs").innerHTML =
    `<div class="erreurs"><strong>Actions non chargées :</strong><br>${D.erreurs.join("<br>")}<br>Vérifiez le ticker sur finance.yahoo.com.</div>`;
}

const n = D.actions.length;
const nb = D.actions.filter(a => a.periodes[1].gagne).length;
const verdict = document.getElementById("verdict");
if (!n) {
  verdict.textContent = "Aucune donnée n'a pu être chargée.";
} else if (!nb) {
  verdict.textContent = `De ${P2}, le buy & hold fait mieux que le robot sur les ${n} actions.`;
} else {
  verdict.textContent = `De ${P2}, le robot fait mieux que le buy & hold sur ${nb} action${nb > 1 ? "s" : ""} sur ${n}.`;
}
document.getElementById("explication").textContent =
  `La période ${P1} sert à régler le robot ; la période ${P2} vérifie qu'il marche sur des données qu'il n'a pas vues. ` +
  `Le robot est jugé utile s'il bat le buy & hold, ou s'il fait au moins 80 % de sa performance avec une pire baisse deux fois plus faible.`;

// ---- Ordres pour la prochaine séance
if (n) {
  const aPasser = D.actions.filter(a => a.signal === "achat" || a.signal === "vente");
  const liste = s => D.actions.filter(a => a.signal === s || (s === "haussier" && a.signal === "achat")
    || (s === "baissier" && a.signal === "vente")).map(a => a.nom).join(", ") || "aucune";
  document.getElementById("ordres").innerHTML =
    `<h2>Ordres pour la prochaine séance</h2>
     <p class="sous-titre">D'après la clôture du ${D.actions[0].dateSignal}. À passer à l'ouverture sur votre PEA.</p>` +
    (aPasser.length
      ? aPasser.map(a => `<div class="ordre"><span><strong>${a.nom}</strong> <span class="cat">clôture ${fr(a.dernierCours, 2)}</span></span>
          <span class="sens ${a.signal}">${a.signal === "achat" ? "Acheter" : "Vendre"}</span></div>`).join("")
      : `<div class="ordre"><span>Aucun ordre : le robot garde ses positions.</span></div>`) +
    `<p class="tendances">Tendance haussière : ${liste("haussier")}.<br>Tendance baissière : ${liste("baissier")}.</p>`;
}

// ---- Tableau principal
document.getElementById("sous-titre-tableau").textContent =
  `Chiffres de la période de vérification (${P2}). Touchez une ligne pour voir ses courbes.`;
document.getElementById("th-p1").textContent = `Verdict ${D.periodesCourts[0]}`;
document.getElementById("th-p2").textContent = `Verdict ${D.periodesCourts[1]}`;
document.getElementById("tableau").innerHTML = D.actions.map((a, i) => {
  const v = a.periodes[1];
  return `<tr class="cliquable" tabindex="0" data-i="${i}">
    <td>${a.nom}<span class="cat">${a.cat}</span></td>
    <td class="${signe(v.robot)}">${pct(v.robot)}</td>
    <td class="${signe(v.bh)}">${pct(v.bh)}</td>
    <td>${pct(v.ddRobot)}</td><td>${pct(v.ddBh)}</td>
    <td>${v.gagnants} / ${v.trades}</td>
    <td>${badge(a.periodes[0].gagne)}</td><td>${badge(v.gagne)}</td></tr>`;
}).join("");
document.querySelectorAll("tr.cliquable").forEach(tr => {
  const aller = () => { afficher(+tr.dataset.i); document.querySelector(".entete-detail").scrollIntoView({behavior: "smooth"}); };
  tr.addEventListener("click", aller);
  tr.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); aller(); } });
});

// ---- Robustesse
document.getElementById("sous-titre-robuste").textContent =
  `Écart entre le robot et le buy & hold sur ${P2}, pour chaque réglage des moyennes mobiles. ` +
  `Un réglage fiable reste positif sur plusieurs colonnes voisines, pas sur une seule.`;
document.getElementById("tete-robuste").innerHTML = "<th>Action</th>" +
  D.reglages.map(r => `<th class="${r === D.reglage ? "actuel" : ""}">${r}${r === D.reglage ? " (actuel)" : ""}</th>`).join("");
document.getElementById("robuste").innerHTML = D.actions.map(a => `<tr><td>${a.nom}</td>` +
  a.robuste.map(v => {
    const force = Math.min(Math.abs(v), 60) / 60 * 32 + 4;
    const couleur = v >= 0 ? "--gain" : "--perte";
    return `<td class="chaleur ${signe(v)}" style="background:color-mix(in srgb,var(${couleur}) ${force}%,transparent)">${pct(v)}</td>`;
  }).join("") + "</tr>").join("");

document.getElementById("pied").textContent =
  "Données Yahoo Finance, cours ajustés des dividendes : le buy & hold inclut les dividendes réinvestis. " +
  "Simulation sans argent réel ; les résultats passés ne préjugent pas des résultats futurs. Ce rapport n'est pas un conseil en investissement.";

// ---- Graphiques
const choix = document.getElementById("choix");
choix.innerHTML = D.actions.map((a, i) => `<option value="${i}">${a.nom}</option>`).join("");
choix.addEventListener("change", () => afficher(+choix.value));

const ligneCoupure = idx => ({
  id: "coupure",
  afterDatasetsDraw(c) {
    const x = c.scales.x.getPixelForValue(idx), {top, bottom} = c.chartArea, ctx = c.ctx;
    ctx.save();
    ctx.strokeStyle = css("--doux"); ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, bottom); ctx.stroke();
    ctx.setLineDash([]); ctx.fillStyle = css("--doux"); ctx.font = "12px 'IBM Plex Sans', sans-serif";
    ctx.fillText("vérification →", x + 6, top + 12);
    ctx.restore();
  }
});

function options(unite) {
  return {
    locale: "fr-FR", responsive: true, maintainAspectRatio: false, animation: false,
    interaction: {mode: "index", intersect: false},
    elements: {point: {radius: 0, hoverRadius: 3}, line: {borderWidth: 1.6}},
    plugins: {
      legend: {labels: {color: css("--doux"), usePointStyle: true, boxWidth: 8, font: {size: 12}}},
      tooltip: {filter: it => it.raw !== null,
        callbacks: {label: it => ` ${it.dataset.label} : ${fr(it.raw, unite === "€" ? 0 : 2)} ${unite}`}}
    },
    scales: {
      x: {grid: {display: false}, ticks: {color: css("--doux"), maxTicksLimit: 7, maxRotation: 0,
          callback(v) { return this.getLabelForValue(v).slice(0, 4); }}},
      y: {grid: {color: css("--ligne")}, ticks: {color: css("--doux")}}
    }
  };
}

let gCapital, gCours;
function afficher(i) {
  const a = D.actions[i];
  if (!a) return;
  choix.value = i;
  document.querySelectorAll("tr.cliquable").forEach(tr => tr.classList.toggle("actif", +tr.dataset.i === i));
  const fin = a.eqRobot[a.eqRobot.length - 1], finBh = a.eqBh[a.eqBh.length - 1];
  document.getElementById("legende-capital").textContent =
    `${fr(D.capital)} € investis en ${a.dates[0].slice(0, 4)} : ${fr(fin)} € avec le robot, ${fr(finBh)} € en buy & hold.`;

  gCapital && gCapital.destroy();
  gCapital = new Chart(document.getElementById("g-capital"), {
    type: "line",
    data: {labels: a.dates, datasets: [
      {label: "Robot", data: a.eqRobot, borderColor: css("--robot"), backgroundColor: css("--robot")},
      {label: "Buy & hold", data: a.eqBh, borderColor: css("--bh"), backgroundColor: css("--bh")}
    ]},
    options: options("€"), plugins: [ligneCoupure(a.coupure)]
  });

  const marque = type => {
    const arr = new Array(a.dates.length).fill(null);
    a.ordres.filter(o => o[2] === type).forEach(o => arr[o[0]] = o[1]);
    return arr;
  };
  const point = (label, type, couleur, style, rotation = 0) => ({
    label, data: marque(type), showLine: false, pointStyle: style, rotation,
    pointRadius: 6, pointHoverRadius: 7, borderColor: couleur, backgroundColor: couleur
  });
  gCours && gCours.destroy();
  gCours = new Chart(document.getElementById("g-cours"), {
    type: "line",
    data: {labels: a.dates, datasets: [
      {label: "Cours", data: a.cours, borderColor: css("--encre"), backgroundColor: css("--encre"), borderWidth: 1.2},
      {label: "Moyenne courte", data: a.smaC, borderColor: css("--robot"), backgroundColor: css("--robot"), borderWidth: 1},
      {label: "Moyenne longue", data: a.smaL, borderColor: css("--stop"), backgroundColor: css("--stop"), borderWidth: 1},
      point("Achat", "achat", css("--gain"), "triangle"),
      point("Vente", "vente", css("--perte"), "triangle", 180),
      point("Stop-loss", "stop", css("--stop"), "crossRot")
    ]},
    options: options("€"), plugins: [ligneCoupure(a.coupure)]
  });

  document.getElementById("detail").innerHTML = a.periodes.map((p, k) => `<tr>
    <td>${D.periodes[k]}</td><td class="${signe(p.robot)}">${pct(p.robot)}</td>
    <td class="${signe(p.bh)}">${pct(p.bh)}</td><td>${pct(p.ddRobot)}</td><td>${pct(p.ddBh)}</td>
    <td>${p.trades}</td><td>${p.gagnants}</td><td>${badge(p.gagne)}</td></tr>`).join("");
}

if (typeof Chart === "undefined") {
  document.querySelectorAll(".toile").forEach(t => t.innerHTML =
    "<p>Les graphiques n'ont pas pu se charger. Vérifiez votre connexion internet puis rechargez la page.</p>");
} else if (n) {
  afficher(0);
}
</script>
</body>
</html>
"""


if __name__ == "__main__":
    {"rapport": lancer_rapport, "backtest": lancer_backtest,
     "robustesse": lancer_robustesse, "signaux": lancer_signaux}[MODE]()

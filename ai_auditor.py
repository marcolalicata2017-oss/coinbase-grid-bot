import os
import json
import time
import subprocess
import pandas as pd
import requests
from datetime import datetime, timedelta
from google import genai

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

FILE_DIARIO = "diario_di_bordo.csv"
FILE_PORTAFOGLIO = "storico_portafoglio_giornaliero.csv"
FILE_CONFIG = "config.json"
FILE_MEMORIA = "memoria_decisioni_ai.json"

ALTCOIN_CANDIDATE_RADAR = [
    "BTC-EUR", "ETH-EUR", "SOL-EUR", "DOGE-EUR", 
    "LINK-EUR", "ADA-EUR", "AVAX-EUR", "NEAR-EUR", "DOT-EUR", "SUI-EUR"
]

def invia_telegram(messaggio):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Token o Chat ID Telegram non configurati.", flush=True)
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload_markdown = {
        "chat_id": TELEGRAM_CHAT_ID, 
        "text": messaggio, 
        "parse_mode": "Markdown"
    }
    
    try:
        resp = requests.post(url, json=payload_markdown, timeout=10)
        if resp.status_code != 200:
            payload_plain = {"chat_id": TELEGRAM_CHAT_ID, "text": messaggio}
            requests.post(url, json=payload_plain, timeout=10)
        else:
            print("✅ Notifica Telegram inviata con successo!", flush=True)
    except Exception as e:
        print(f"❌ Errore invio Telegram: {e}", flush=True)

def ottieni_prezzo_corrente(pair):
    try:
        url = f"https://api.exchange.coinbase.com/products/{pair}/ticker"
        headers = {"User-Agent": "Python-Bot"}
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            return float(resp.json().get("price", 0.0))
    except Exception:
        pass
    return 0.0

RADAR_ERRORI = []          # (pair, motivo) dell'ultima scansione
FILE_RADAR_CSV = "radar_scansioni.csv"
RADAR_CSV_COLONNE = ["Data_Ora", "Pair", "Prezzo", "Var24h_pct", "Ret7d_pct", "RSI_1h", "VAI", "Vol_EUR_24h",
                     "ATR_pct", "Dist_EMA50_pct", "Dist_EMA200_pct", "Pressione", "Score", "Rank", "In_Config"]

def _rsi_wilder(prezzi, periodo=14):
    delta = prezzi.diff()
    gain = delta.clip(lower=0).ewm(alpha=1.0 / periodo, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1.0 / periodo, adjust=False).mean()
    rs = gain / loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return 100.0 if (pd.isna(val) and loss.iloc[-1] == 0 and gain.iloc[-1] > 0) else (50.0 if pd.isna(val) else float(val))

def calcola_score_radar(m):
    """Punteggio deterministico 0-100 per asset del radar. Solo informativo: va nel prompt e nel CSV,
    non cambia ordini ne' config. Componenti: momentum 7g, trend (EMA50/EMA200), RSI, volumi, liquidita', volatilita'."""
    score = 50.0
    r7 = m.get("ret_7d_pct")
    if r7 is not None:
        score += max(-15.0, min(15.0, r7)) * 0.8
    score += 8.0 if m["dist_ema50_pct"] >= 0 else -8.0
    if m.get("dist_ema200_pct") is not None:
        score += 4.0 if m["dist_ema200_pct"] >= 0 else -4.0
    rsi = m["rsi_1h"]
    if rsi >= 75: score -= 10.0
    elif rsi <= 25: score -= 5.0
    elif 40 <= rsi <= 60: score += 6.0
    if m["pressione_rilevata"] == "DISTRIBUZIONE": score -= 10.0
    elif 1.2 <= m["volume_anomaly_vai"] <= 3.0 and m["var_24h_pct"] >= -1.5: score += 6.0
    vol_eur = m["volume_eur_24h"]
    if vol_eur < 200_000: score -= 15.0
    elif vol_eur < 1_000_000: score -= 5.0
    if m["atr_pct"] > 3.0: score -= 5.0
    return round(max(0.0, min(100.0, score)), 1)

def scansiona_radar_altcoin_con_volumi(lista_pairs):
    """Scansiona prezzo, variazioni 24h/7g, RSI 1h (Wilder), VAI (volume anomalo vs media 7 giorni), volume in EUR,
    ATR%, distanza da EMA50/EMA200 orarie e calcola uno score deterministico con classifica.
    Gli errori per coppia vengono registrati in RADAR_ERRORI e stampati."""
    global RADAR_ERRORI
    RADAR_ERRORI = []
    radar = {}
    headers = {"User-Agent": "Python-Bot"}
    print("🔭 [RADAR] Scansione tecnica e volumi anomali in corso...", flush=True)

    for pair in lista_pairs:
        try:
            url = f"https://api.exchange.coinbase.com/products/{pair}/candles?granularity=3600"
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}")
            data = resp.json()
            if not isinstance(data, list) or len(data) < 24:
                raise RuntimeError(f"candele insufficienti ({len(data) if isinstance(data, list) else 'formato'})")
            candele = list(reversed(data))
            lows = pd.Series([float(c[1]) for c in candele])
            highs = pd.Series([float(c[2]) for c in candele])
            prezzi = pd.Series([float(c[4]) for c in candele])
            volumi = pd.Series([float(c[5]) for c in candele])

            px_att = float(prezzi.iloc[-1])
            var_24h = (px_att - prezzi.iloc[-24]) / prezzi.iloc[-24] * 100.0
            ret_7d = ((px_att - prezzi.iloc[-168]) / prezzi.iloc[-168] * 100.0) if len(prezzi) >= 168 else None

            vol_24h_tot = float(volumi.tail(24).sum())
            finestra_totale = min(len(volumi), 168)
            vol_medio_24h = (volumi.tail(finestra_totale).sum() / (finestra_totale / 24.0)) if finestra_totale >= 24 else vol_24h_tot
            vai_ratio = round(vol_24h_tot / vol_medio_24h, 2) if vol_medio_24h > 0 else 1.0
            volume_eur_24h = float((volumi.tail(24) * prezzi.tail(24)).sum())

            rsi_val = _rsi_wilder(prezzi)
            ema50 = float(prezzi.ewm(span=min(50, len(prezzi)), adjust=False).mean().iloc[-1])
            dist_ema50 = (px_att - ema50) / ema50 * 100.0
            dist_ema200 = None
            if len(prezzi) >= 200:
                ema200 = float(prezzi.ewm(span=200, adjust=False).mean().iloc[-1])
                dist_ema200 = (px_att - ema200) / ema200 * 100.0
            prev_close = prezzi.shift(1)
            tr = pd.concat([highs - lows, (highs - prev_close).abs(), (lows - prev_close).abs()], axis=1).max(axis=1)
            atr = tr.rolling(14).mean().iloc[-1]
            atr_pct = float(atr / px_att * 100.0) if not pd.isna(atr) and px_att > 0 else 0.0

            pressione = "ACCUMULO" if (var_24h >= -1.5 and vai_ratio >= 1.8) else ("DISTRIBUZIONE" if vai_ratio >= 2.0 and var_24h < -4.0 else "NORMALE")

            voce = {
                "prezzo": round(px_att, 4),
                "var_24h_pct": round(var_24h, 2),
                "ret_7d_pct": round(ret_7d, 2) if ret_7d is not None else None,
                "rsi_1h": round(rsi_val, 1),
                "volume_anomaly_vai": vai_ratio,
                "volume_eur_24h": round(volume_eur_24h, 0),
                "atr_pct": round(atr_pct, 2),
                "dist_ema50_pct": round(dist_ema50, 2),
                "dist_ema200_pct": round(dist_ema200, 2) if dist_ema200 is not None else None,
                "pressione_rilevata": pressione,
            }
            voce["score"] = calcola_score_radar(voce)
            radar[pair] = voce
        except Exception as e:
            RADAR_ERRORI.append((pair, str(e)))
            print(f"⚠️ [RADAR] {pair} non letto: {e}", flush=True)
        time.sleep(0.12)

    for i, (pair, _) in enumerate(sorted(radar.items(), key=lambda kv: kv[1]["score"], reverse=True), start=1):
        radar[pair]["rank"] = i

    print(f"✅ [RADAR] Scansionati {len(radar)}/{len(lista_pairs)} asset (errori: {len(RADAR_ERRORI)}).", flush=True)
    return radar

def segna_asset_in_config(radar, config_attuale):
    """Aggiunge 'in_config' a ogni voce: il bot opera solo sulle coppie gia' presenti in config.json."""
    assets = (config_attuale or {}).get("assets", {})
    for pair, voce in radar.items():
        voce["in_config"] = pair in assets
    return radar

def salva_radar_csv(radar, quando=None):
    """Accoda la scansione a radar_scansioni.csv (serve a verificare nel tempo se i segnali anticipano i rialzi)."""
    import csv
    if not radar:
        return False
    try:
        nuovo = not os.path.exists(FILE_RADAR_CSV) or os.path.getsize(FILE_RADAR_CSV) == 0
        ts = (quando or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
        with open(FILE_RADAR_CSV, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if nuovo:
                w.writerow(RADAR_CSV_COLONNE)
            for pair, v in radar.items():
                w.writerow([ts, pair, v["prezzo"], v["var_24h_pct"], v.get("ret_7d_pct", ""), v["rsi_1h"],
                            v["volume_anomaly_vai"], v["volume_eur_24h"], v["atr_pct"], v["dist_ema50_pct"],
                            v.get("dist_ema200_pct", ""), v["pressione_rilevata"], v["score"], v["rank"],
                            v.get("in_config", "")])
        return True
    except Exception as e:
        print(f"⚠️ [RADAR] Salvataggio CSV fallito: {e}", flush=True)
        return False

def commit_radar_csv():
    """Commit del solo CSV del radar. Mai bloccante: un errore git non ferma l'audit."""
    try:
        if not os.path.exists(FILE_RADAR_CSV):
            return False
        subprocess.run(["git", "config", "user.name", "AI-Auditor-Bot"], check=True)
        subprocess.run(["git", "config", "user.email", "ai-auditor@bot.local"], check=True)
        subprocess.run(["git", "add", FILE_RADAR_CSV], check=True)
        r = subprocess.run(["git", "status", "--porcelain", "--", FILE_RADAR_CSV], capture_output=True, text=True)
        if not r.stdout.strip():
            return False
        subprocess.run(["git", "commit", "-m", "📡 [AUTOMATION] Scansione radar", "--", FILE_RADAR_CSV], check=True)
        subprocess.run(["git", "pull", "--rebase", "--autostash"], check=False)
        subprocess.run(["git", "push"], check=True)
        print("✅ [RADAR] CSV scansioni committato.", flush=True)
        return True
    except Exception as e:
        print(f"⚠️ [RADAR] Commit CSV non riuscito (non blocca l'audit): {e}", flush=True)
        return False

def calcola_benchmark_buy_and_hold(df_portafoglio):
    """Calcola rendimento cumulativo del bot vs un portafoglio passivo 50% BTC / 50% ETH."""
    if df_portafoglio.empty or len(df_portafoglio) < 2:
        return 0.0, 0.0, 0.0
    
    valore_iniziale = float(df_portafoglio.iloc[0].get("Valore_Totale_EUR", 1.0))
    valore_attuale = float(df_portafoglio.iloc[-1].get("Valore_Totale_EUR", 1.0))
    rendimento_bot_pct = ((valore_attuale - valore_iniziale) / valore_iniziale) * 100.0

    giorni_storico = len(df_portafoglio)
    px_btc_now = ottieni_prezzo_corrente("BTC-EUR")
    px_eth_now = ottieni_prezzo_corrente("ETH-EUR")
    
    # Stima variazione BTC ed ETH sull'intervallo temporale dello storico
    rendimento_bh_pct = 0.0
    try:
        url_btc = f"https://api.exchange.coinbase.com/products/BTC-EUR/candles?granularity=86400"
        url_eth = f"https://api.exchange.coinbase.com/products/ETH-EUR/candles?granularity=86400"
        headers = {"User-Agent": "Python-Bot"}
        r_b = requests.get(url_btc, headers=headers, timeout=5).json()
        r_e = requests.get(url_eth, headers=headers, timeout=5).json()
        
        idx = min(giorni_storico, len(r_b) - 1, len(r_e) - 1)
        if idx > 0 and px_btc_now > 0 and px_eth_now > 0:
            px_btc_start = float(r_b[idx][4])
            px_eth_start = float(r_e[idx][4])
            ret_btc = ((px_btc_now - px_btc_start) / px_btc_start) * 100.0
            ret_eth = ((px_eth_now - px_eth_start) / px_eth_start) * 100.0
            rendimento_bh_pct = (ret_btc * 0.5) + (ret_eth * 0.5)
    except Exception as e:
        print(f"⚠️ Avviso calcolo B&H: {e}", flush=True)

    alpha_pct = rendimento_bot_pct - rendimento_bh_pct
    return round(rendimento_bot_pct, 2), round(rendimento_bh_pct, 2), round(alpha_pct, 2)

def carica_memoria_storica():
    if os.path.exists(FILE_MEMORIA):
        try:
            with open(FILE_MEMORIA, "r", encoding="utf-8") as f:
                contenuto = f.read().strip()
                if contenuto: return json.loads(contenuto)
        except Exception as e:
            print(f"⚠️ Errore lettura memoria storica: {e}", flush=True)
    return []

def salva_memoria_storica(memoria):
    try:
        with open(FILE_MEMORIA, "w", encoding="utf-8") as f:
            json.dump(memoria, f, indent=2, ensure_ascii=False)
        print("🧠 Memoria decisionale salvata su file.", flush=True)
    except Exception as e:
        print(f"⚠️ Errore salvataggio memoria storica: {e}", flush=True)

# ==========================================
# VALIDAZIONE RIGIDA DEL CONFIG PROPOSTO DALL'AI
# ==========================================
LIM_BUY_DIST = (0.005, 0.02)
LIM_SELL_DIST = (0.018, 0.05)
LIM_WEIGHT = (0.0, 40.0)
LIM_CONVICTION = (0.0, 2.0)
SELL_ACTION_OK = {"tranche", "scale_out", "liquidate_all"}   # l'auditor resta autonomo
EXIT_OK = {"none", "soft_exit", "market_sell"}   # l'auditor resta autonomo

def _clamp(v, lo, hi):
    return max(lo, min(hi, float(v)))

def valida_config(nuovo, attuale):
    """Restituisce (config_sicuro, note). Valori fuori range vengono riportati nel range;
    valori sconosciuti e asset nuovi non passano."""
    note = []
    if not isinstance(nuovo, dict) or not isinstance(nuovo.get("assets"), dict):
        return None, ["config senza 'assets' valido: scartato"]
    att_assets = (attuale or {}).get("assets", {})
    out = {k: v for k, v in nuovo.items() if k != "assets"}
    out["assets"] = {}
    for pair, d in nuovo["assets"].items():
        if pair not in att_assets:
            note.append(f"{pair}: nuovo asset proposto dall'AI, ignorato")
            continue
        base = dict(att_assets[pair])
        d = dict(d) if isinstance(d, dict) else {}
        try:
            for k, (lo, hi) in (("grid_dist_buy", LIM_BUY_DIST), ("grid_dist_sell", LIM_SELL_DIST),
                                ("target_weight_pct", LIM_WEIGHT), ("buy_conviction", LIM_CONVICTION)):
                if k in d:
                    v = _clamp(d[k], lo, hi)
                    if abs(v - float(d[k])) > 1e-12:
                        note.append(f"{pair}.{k}: {d[k]} riportato a {v}")
                    base[k] = v
            if "is_active" in d:
                base["is_active"] = bool(d["is_active"])
            if d.get("sell_action", base.get("sell_action", "tranche")) not in SELL_ACTION_OK:
                note.append(f"{pair}.sell_action '{d.get('sell_action')}' non valido, mantenuto il precedente")
            elif "sell_action" in d:
                base["sell_action"] = d["sell_action"]
            if d.get("exit_strategy", base.get("exit_strategy", "none")) not in EXIT_OK:
                note.append(f"{pair}.exit_strategy '{d.get('exit_strategy')}' non valido, mantenuto il precedente")
            elif "exit_strategy" in d:
                base["exit_strategy"] = d["exit_strategy"]
        except (TypeError, ValueError) as e:
            note.append(f"{pair}: valori non numerici ({e}), mantenuto il precedente")
        out["assets"][pair] = base
    for pair in att_assets:
        out["assets"].setdefault(pair, att_assets[pair])
    totale = sum(float(v.get("target_weight_pct", 0)) for v in out["assets"].values())
    if totale > 100.0:
        note.append(f"somma pesi {totale:.1f}% > 100%: config scartato")
        return None, note
    return out, note

def applica_commit_github(nuovo_config, nuova_scheda_memoria=None):
    try:
        # Inietta sempre il flag per forzare il riallineamento immediato nel bot esecutore
        nuovo_config["force_grid_realign"] = True
        
        with open(FILE_CONFIG, "w", encoding="utf-8") as f:
            json.dump(nuovo_config, f, indent=2)
        
        if nuova_scheda_memoria:
            memoria = carica_memoria_storica()
            memoria.append(nuova_scheda_memoria)
            salva_memoria_storica(memoria)

        subprocess.run(["git", "config", "user.name", "AI-Auditor-Bot"], check=True)
        subprocess.run(["git", "config", "user.email", "ai-auditor@bot.local"], check=True)
        subprocess.run(["git", "add", FILE_CONFIG], check=True)
        if os.path.exists(FILE_MEMORIA):
            subprocess.run(["git", "add", FILE_MEMORIA], check=True)
        if os.path.exists(FILE_RADAR_CSV):
            subprocess.run(["git", "add", FILE_RADAR_CSV], check=True)

        result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if result.stdout.strip():
            subprocess.run(["git", "commit", "-m", "🤖 AI Auditor: Allineamento Tattico, Anti-Inazione & Reset Griglie"], check=True)
            subprocess.run(["git", "push"], check=True)
            print("✅ config.json e memoria_decisioni_ai.json committati su GitHub con force_grid_realign=True!", flush=True)
            return True
        else:
            print("ℹ️ Nessuna modifica sostanziale da committare.", flush=True)
            return False
    except Exception as e:
        print(f"❌ Errore auto-commit su GitHub: {e}", flush=True)
        return False

def esegui_audit():
    if not GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY non configurata!", flush=True)
        return

    client = genai.Client(api_key=GEMINI_API_KEY)
    df_diario = pd.read_csv(FILE_DIARIO, on_bad_lines='skip') if os.path.exists(FILE_DIARIO) else pd.DataFrame()
    df_portafoglio = pd.read_csv(FILE_PORTAFOGLIO) if os.path.exists(FILE_PORTAFOGLIO) else pd.DataFrame()
    memoria_storica = carica_memoria_storica()
    
    radar_mercato = scansiona_radar_altcoin_con_volumi(ALTCOIN_CANDIDATE_RADAR)
    ret_bot, ret_bh, alpha = calcola_benchmark_buy_and_hold(df_portafoglio)

    config_attuale = {}
    if os.path.exists(FILE_CONFIG):
        try:
            with open(FILE_CONFIG, "r", encoding="utf-8") as f:
                config_attuale = json.load(f)
        except Exception as e:
            print(f"⚠️ Errore lettura config.json: {e}", flush=True)

    segna_asset_in_config(radar_mercato, config_attuale)
    salva_radar_csv(radar_mercato)

    ora_dt = datetime.now()
    data_odierna_str = ora_dt.strftime('%Y-%m-%d')
    is_domenica = (ora_dt.weekday() == 6)

    data_limite = (ora_dt - timedelta(days=7 if is_domenica else 1)).strftime("%Y-%m-%d")
    diario_rec = df_diario[df_diario['Data_Ora'] >= data_limite] if not df_diario.empty and 'Data_Ora' in df_diario.columns else pd.DataFrame()

    saldo_eur_effettivo = 0.0
    valore_crypto_totale = 0.0
    valore_totale_portafoglio = 1.0
    pct_cassa_eur = 100.0
    dd_3gg_pct = 0.0
    dd_7gg_pct = 0.0

    if not df_portafoglio.empty:
        ultima_riga = df_portafoglio.iloc[-1]
        saldo_eur_effettivo = float(ultima_riga.get("Saldo_EUR", 0.0))
        valore_crypto_totale = float(ultima_riga.get("Valore_Crypto_EUR", 0.0))
        valore_totale_portafoglio = float(ultima_riga.get("Valore_Totale_EUR", saldo_eur_effettivo + valore_crypto_totale))
        if valore_totale_portafoglio > 0:
            pct_cassa_eur = (saldo_eur_effettivo / valore_totale_portafoglio) * 100.0

        valore_3gg = float(df_portafoglio.iloc[-3]["Valore_Totale_EUR"]) if len(df_portafoglio) >= 3 else valore_totale_portafoglio
        valore_7gg = float(df_portafoglio.iloc[-7]["Valore_Totale_EUR"]) if len(df_portafoglio) >= 7 else valore_totale_portafoglio

        if valore_3gg > 0:
            dd_3gg_pct = ((valore_totale_portafoglio - valore_3gg) / valore_3gg) * 100.0
        if valore_7gg > 0:
            dd_7gg_pct = ((valore_totale_portafoglio - valore_7gg) / valore_7gg) * 100.0

    stato_liquidita_alert = "NORMALE"
    if pct_cassa_eur < 15.0 or saldo_eur_effettivo < 35.0:
        stato_liquidita_alert = "ALLERTA CRITICA LIQUIDITÀ"
    elif pct_cassa_eur >= 50.0:
        stato_liquidita_alert = "ALLERTA ECCESSO LIQUIDITÀ / RISCHIO INAZIONE"

    prompt = f"""
    Sei il Direttore Investimenti e Risk Manager Quantitativo di un Hedge Fund Crypto su Coinbase Advanced.
    Gestisci un portafoglio a BANDE FLESSIBILI.

    Data Corrente: {data_odierna_str}
    Tipo Esecuzione: {"SETTIMANALE STRATEGICO (Ribilanciamento Macro Pesi & Memoria)" if is_domenica else "GIORNALIERO TATTICO (Riallocazione Pesi, Scouting Volumi & Benchmark)"}

    ⚡ COMMISSIONI COINBASE ADVANCED (Livello Intro): Maker 0.25%, Taker 0.50%.
    🎯 REGOLE NET SPREAD: Con fee totali a 0.50% (Maker+Maker), 'grid_dist_sell' NON deve mai scendere sotto 0.018 (1.8% lordo = +1.30% netto).

    💰 STATO REALE PORTAFOGLIO, LIQUIDITÀ & BENCHMARK:
    - Valore Totale: {valore_totale_portafoglio:.2f} EUR
    - Cassa EUR Libera: {saldo_eur_effettivo:.2f} EUR ({pct_cassa_eur:.1f}% del portafoglio)
    - Totale Crypto in Carico: {valore_crypto_totale:.2f} EUR
    - Stato Riserva Cassa: {stato_liquidita_alert}
    - 📉 Traiettoria Capitale (Portfolio Drawdown):
      * Rendimento/Drawdown 3 Giorni: {dd_3gg_pct:+.2f}%
      * Rendimento/Drawdown 7 Giorni: {dd_7gg_pct:+.2f}%
    - ⚖️ CONFRONTO STRATEGICO VS BUY & HOLD (50% BTC / 50% ETH):
      * Rendimento Totale Bot: {ret_bot:+.2f}%
      * Rendimento Benchmark B&H: {ret_bh:+.2f}%
      * Alpha Generato: {alpha:+.2f}% (Se negativo, stiamo sotto-performando il mercato passivo per eccesso di prudenza/inazione!)

    🔭 RADAR TECNICO MERCATO & VOLUMI ANOMALI (VAI = Volume Anomaly Index):
    Ogni asset ha uno 'score' deterministico 0-100 (momentum 7g, trend EMA50/EMA200, RSI, volumi, liquidità EUR, volatilità), un 'rank' e 'in_config'. 'ACCUMULO' si basa solo sul volume: confermalo con score alto e trend positivo.
    Limiti che il sistema applica: grid_dist_sell 0.018-0.05, target_weight_pct 0-40 (somma <= 100), buy_conviction 0-2.
    {json.dumps(radar_mercato, indent=2)}

    🧠 VALUTAZIONE MEMORIA DECISIONALE (COSA HA FUNZIONATO E COSA NO):
    {json.dumps(memoria_storica[-5:], indent=2) if memoria_storica else "Nessuna memoria registrata."}

    🛑 REGOLA FERREA ANTI-INAZIONE (CASSA > 50%):
    Se Cassa EUR è al {pct_cassa_eur:.1f}% (> 50%), TI È SEVERAMENTE VIETATO impostare 'buy_conviction': 0.0 su tutti gli asset!
    - Devi obbligatoriamente allocare liquidità e impostare 'buy_conviction': 1.0 (o 1.2) su almeno 1 o 2 asset:
      * Preferisci asset del Radar in 'ACCUMULO' (VAI >= 1.8x) o large-cap con RSI scarico (RSI < 45).
    - 'grid_dist_buy' deve restare tra 0.005 e 0.02: il bot limita comunque a 0.02 (2%) e valori fuori range vengono riportati nel range. Per catturare storni usa piuttosto buy_conviction e pesi.
    - Se ci sono asset zombie con ordini bloccati senza volumi (come DOGE), metti 'exit_strategy': 'soft_exit' e ruota il capitale verso gli asset GIÀ presenti in config.json con score radar più alto. Asset nuovi proposti dal radar vengono ignorati dal sistema: non proporli.

    🚨 PROTOCOLLO LIQUIDITY CRUNCH & NO-LOSS RULE:
    - Se Cassa EUR < 15%: evita di vendere in perdita. Il prezzo medio di carico NON è tracciato dal bot e non ti viene fornito: stimalo dal diario di bordo qui sotto e, se non sei sicuro, non vendere. Se in profitto, 'sell_action': 'scale_out' (50%).

    CONFIGURAZIONE ATTUALE (config.json):
    {json.dumps(config_attuale, indent=2) if config_attuale else "Nessun config.json trovato."}

    DATI RECENTI DIARIO DI BORDO:
    {diario_rec.to_string() if not diario_rec.empty else "Nessuna operazione registrata nel periodo."}

    STRUTTURA OBBLIGATORIA DELLA RISPOSTA:
    Separa rigorosamente le 3 parti con '---JSON_CONFIG---' e '---JSON_MEMORIA---':

    Parte 1: Report per Telegram (Markdown) contenente OBBLIGATORIAMENTE:
    - 💧 Quadro Cassa & Alpha vs Buy & Hold (Bot: {ret_bot:+.2f}% vs B&H: {ret_bh:+.2f}% | Alpha: {alpha:+.2f}%)
    - 🔭 RADAR OPPORTUNITÀ & VOLUMI ANOMALI: analisi delle coin scansionate e giustificazione delle rotazioni.
    - ⚡ Strategia di Impiego Cassa: come attiviamo o difendiamo la liquidità nelle condizioni odierne.
    - 🎯 Decisioni operative sui singoli pair.
    ---JSON_CONFIG---
    Parte 2: JSON completo e valido per config.json (o 'NO_CHANGE').
    ---JSON_MEMORIA---
    Parte 3: Scheda di memoria JSON con i campi: data, tipo_audit, regime_rilevato, decisione, ipotesi_e_aspettativa, esito_decisione_precedente, lezione_appresa.
    """

    modelli = [
        'gemini-3.8-flash',
        'gemini-3.7-flash',
        'gemini-3.6-flash',
        'gemini-3.5-flash',
        'gemini-3.5-flash-lite',
        'gemini-3.1-flash-lite'
    ]
    testo_risposta = None

    for modello in modelli:
        for tentativo in range(3):
            try:
                print(f"🔄 Chiamata con modello {modello} (tentativo {tentativo + 1})...", flush=True)
                response = client.models.generate_content(model=modello, contents=prompt)
                testo_risposta = response.text
                break
            except Exception as e:
                errore_str = str(e)
                print(f"⚠️ Errore con {modello}: {errore_str}", flush=True)
                
                if "404" in errore_str or "not_found" in errore_str.lower():
                    print(f"⏩ Modello {modello} non disponibile (404). Salto al prossimo...", flush=True)
                    break

                if "503" in errore_str or "high demand" in errore_str.lower():
                    attesa = (tentativo + 1) * 8
                    print(f"⏳ Sovraccarico server (503). Attesa decongestione: {attesa}s...", flush=True)
                    time.sleep(attesa)
                else:
                    time.sleep(2)
                    
        if testo_risposta:
            print(f"✅ Risposta generata con successo usando: {modello}", flush=True)
            break

    if not testo_risposta:
        print("❌ Impossibile completare l'audit.", flush=True)
        return

    parti_config = testo_risposta.split("---JSON_CONFIG---")
    report_telegram = parti_config[0].strip()
    
    resto = parti_config[1].strip() if len(parti_config) > 1 else "NO_CHANGE"
    parti_memoria = resto.split("---JSON_MEMORIA---")
    
    json_config_str = parti_memoria[0].strip()
    json_memoria_str = parti_memoria[1].strip() if len(parti_memoria) > 1 else "NO_CHANGE"

    modificato = False
    if json_config_str != "NO_CHANGE":
        try:
            if json_config_str.startswith("```"):
                json_config_str = json_config_str.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            nuovo_config = json.loads(json_config_str)
            nuovo_config, note_validazione = valida_config(nuovo_config, config_attuale)
            if note_validazione:
                report_telegram += "\n\n🛡️ *[GUARDRAIL]*\n" + "\n".join(f"- {n}" for n in note_validazione)
            if nuovo_config is None:
                raise ValueError("config AI non valido, nessun push")
            
            nuova_scheda = None
            if json_memoria_str != "NO_CHANGE":
                if json_memoria_str.startswith("```"):
                    json_memoria_str = json_memoria_str.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                nuova_scheda = json.loads(json_memoria_str)

            modificato = applica_commit_github(nuovo_config, nuova_scheda)
        except Exception as e:
            print(f"⚠️ Errore parsing JSON da Gemini: {e}", flush=True)

    intestazione = "🧠 *[AI AUDITOR - SETTIMANALE STRATEGICO]*\n\n" if is_domenica else "⚡ *[AI AUDITOR - BENCHMARK, RADAR & HARVESTING]*\n\n"
    if modificato:
        report_telegram += "\n\n🚀 *[PARAMETRI AGGIORNATI SU GITHUB: il bot riposiziona le griglie solo se serve]*"

    if len(RADAR_ERRORI) >= 3:
        report_telegram += "\n\n⚠️ *[RADAR]* Coppie non lette: " + ", ".join(f"{p} ({m})" for p, m in RADAR_ERRORI)
    if not modificato:
        commit_radar_csv()

    invia_telegram(intestazione + report_telegram)
    print("✅ Audit completato con successo!", flush=True)

if __name__ == "__main__":
    esegui_audit()



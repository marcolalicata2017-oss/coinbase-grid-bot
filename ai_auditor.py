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

def scansiona_radar_altcoin_con_volumi(lista_pairs):
    """Scansiona Prezzo, Delta 24h, RSI 1h e VAI (Volume Anomaly Index vs media 7 giorni)."""
    radar = {}
    headers = {"User-Agent": "Python-Bot"}
    print("🔭 [RADAR] Scansione tecnica e volumi anomali in corso...", flush=True)
    
    for pair in lista_pairs:
        try:
            url = f"https://api.exchange.coinbase.com/products/{pair}/candles?granularity=3600"
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and len(data) >= 24:
                    candele = list(reversed(data))
                    prezzi = pd.Series([float(c[4]) for c in candele])
                    volumi = pd.Series([float(c[5]) for c in candele])
                    
                    px_att = prezzi.iloc[-1]
                    var_24h = ((px_att - prezzi.iloc[-24]) / prezzi.iloc[-24] * 100.0)
                    
                    # Calcolo Volume Anomaly Index (VAI): ultime 24 ore vs media storica disponibile
                    vol_24h_tot = volumi.tail(24).sum()
                    finestra_totale = min(len(volumi), 168) # Fino a 7 giorni (168 ore)
                    vol_medio_24h = (volumi.tail(finestra_totale).sum() / (finestra_totale / 24.0)) if finestra_totale >= 24 else vol_24h_tot
                    vai_ratio = round(vol_24h_tot / vol_medio_24h, 2) if vol_medio_24h > 0 else 1.0

                    delta = prezzi.diff()
                    gain = delta.where(delta > 0, 0).rolling(14).mean()
                    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
                    rs = gain / loss
                    rsi = 100 - (100 / (1 + rs))
                    rsi_val = float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50.0

                    # Stato della pressione (Verde se il prezzo regge, Rosso se distribuzione)
                    pressione = "ACCUMULO" if (var_24h >= -1.5 and vai_ratio >= 1.8) else ("DISTRIBUZIONE" if vai_ratio >= 2.0 and var_24h < -4.0 else "NORMALE")
                    
                    radar[pair] = {
                        "prezzo": round(px_att, 4),
                        "var_24h_pct": round(var_24h, 2),
                        "rsi_1h": round(rsi_val, 1),
                        "volume_anomaly_vai": vai_ratio,
                        "pressione_rilevata": pressione
                    }
        except Exception:
            pass
        time.sleep(0.12)
        
    print(f"✅ [RADAR] Scansionati {len(radar)} asset con analisi volumetrica.", flush=True)
    return radar

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

def applica_commit_github(nuovo_config, nuova_scheda_memoria=None):
    try:
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

        result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if result.stdout.strip():
            subprocess.run(["git", "commit", "-m", "🤖 AI Auditor: Aggiornamento tattico radar, volumi & memoria"], check=True)
            subprocess.run(["git", "push"], check=True)
            print("✅ config.json e memoria_decisioni_ai.json committati su GitHub!", flush=True)
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

    config_attuale = {}
    if os.path.exists(FILE_CONFIG):
        try:
            with open(FILE_CONFIG, "r", encoding="utf-8") as f:
                config_attuale = json.load(f)
        except Exception as e:
            print(f"⚠️ Errore lettura config.json: {e}", flush=True)

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

    prompt = f"""
    Sei il Direttore Investimenti e Risk Manager Quantitativo di un Hedge Fund Crypto su Coinbase Advanced.
    Gestisci un portafoglio a BANDE FLESSIBILI SENZA DISTINZIONE FISSA CORE/SATELLITE.

    Data Corrente: {data_odierna_str}
    Tipo Esecuzione: {"SETTIMANALE STRATEGICO (Ribilanciamento Macro Pesi & Memoria)" if is_domenica else "GIORNALIERO TATTICO (Riallocazione Pesi, Scouting Volumi & Fast Harvesting)"}

    ⚡ COMMISSIONI COINBASE ADVANCED: Maker 0.35%, Taker 0.75%.
    🎯 REGOLE NET SPREAD: Con fee totali a 0.70%, 'grid_dist_sell' NON deve mai scendere sotto 0.020 (2.0%).

    💰 STATO REALE PORTAFOGLIO, LIQUIDITÀ & DRAWDOWN:
    - Valore Totale: {valore_totale_portafoglio:.2f} EUR
    - Cassa EUR Libera: {saldo_eur_effettivo:.2f} EUR ({pct_cassa_eur:.1f}% del portafoglio)
    - Totale Crypto in Carico: {valore_crypto_totale:.2f} EUR
    - Stato Riserva Cassa: {stato_liquidita_alert}
    - 📉 Traiettoria Capitale (Portfolio Drawdown):
      * Rendimento/Drawdown 3 Giorni: {dd_3gg_pct:+.2f}%
      * Rendimento/Drawdown 7 Giorni: {dd_7gg_pct:+.2f}%

    🔭 RADAR TECNICO MERCATO & VOLUMI ANOMALI (VAI = Volume Anomaly Index):
    {json.dumps(radar_mercato, indent=2)}

    🧠 VALUTAZIONE MEMORIA DECISIONALE (COSA HA FUNZIONATO E COSA NO):
    {json.dumps(memoria_storica[-5:], indent=2) if memoria_storica else "Nessuna memoria registrata."}
    * Confronta l'aspettativa dell'ultimo audit con i dati reali del diario recente.

    🌊 PROTOCOLLO CACCIA VOLUMI ANOMALI & FAST HARVESTING:
    1. Se un asset nel Radar mostra 'pressione_rilevata': 'ACCUMULO' (volume_anomaly_vai >= 1.8x con prezzo stabile o in ipervenduto RSI < 40):
       - Consideralo candidato ad alta priorità per catturare un'impennata di volatilità.
       - Puoi assegnargli un target weight del 10.0% - 15.0% dismettendo asset fermi con 'buy_conviction': 0.0 (come DOGE).
    2. Se un asset mostra 'pressione_rilevata': 'DISTRIBUZIONE' (volumi record su candele fortemente negative):
       - EVITALO! È un falso positivo da scarico whale.
    3. Su tutti gli asset in downtrend o laterale, mantieni 'grid_dist_sell': 0.020 per incassare velocemente sui rimbalzi.

    🚨 PROTOCOLLO LIQUIDITY CRUNCH & NO-LOSS RULE:
    - Se Cassa EUR < 15% (o < 40 EUR) o un asset supera di molto il target weight:
      * NON VENDERE MAI IN PERDITA RISPETTO AL CARICO MEDIO!
      * Se l'asset è in profitto: applica 'sell_action': 'scale_out' (vende il 50%) per liberare cassa.
      * Se l'asset è in perdita: tieni 'sell_action': 'tranche' e metti 'buy_conviction': 0.5 o 0.0.

    CONFIGURAZIONE ATTUALE (config.json):
    {json.dumps(config_attuale, indent=2) if config_attuale else "Nessun config.json trovato."}

    DATI RECENTI DIARIO DI BORDO:
    {diario_rec.to_string() if not diario_rec.empty else "Nessuna operazione registrata nel periodo."}

    STRUTTURA OBBLIGATORIA DELLA RISPOSTA:
    Separa rigorosamente le 3 parti con '---JSON_CONFIG---' e '---JSON_MEMORIA---':

    Parte 1: Report per Telegram (Markdown) contenente OBBLIGATORIAMENTE:
    - 💧 Quadro Cassa & Drawdown ({dd_3gg_pct:+.2f}% 3G)
    - 🔭 RADAR OPPORTUNITÀ & VOLUMI ANOMALI: commenta cosa emerge dall'analisi volumetrica (VAI, RSI, accumuli sospetti). Se proponi una rotazione (es. dismettere DOGE in soft_exit per un'opportunità), indicalo esplicitamente. Se non ruoti nulla, spiega perché.
    - 🔍 Verifica della Memoria: esame critico delle decisioni precedenti
    - 🎯 Decisioni operative sui singoli pair
    ---JSON_CONFIG---
    Parte 2: JSON completo e valido per config.json (o 'NO_CHANGE').
    ---JSON_MEMORIA---
    Parte 3: Scheda di memoria JSON con i campi: data, tipo_audit, regime_rilevato, decisione, ipotesi_e_aspettativa, esito_decisione_precedente, lezione_appresa.
    """

    modelli = ['gemini-3.5-flash', 'gemini-3.6-flash']
    testo_risposta = None

    for modello in modelli:
        for tentativo in range(3):
            try:
                print(f"🔄 Chiamata con modello {modello} (tentativo {tentativo + 1})...", flush=True)
                response = client.models.generate_content(model=modello, contents=prompt)
                testo_risposta = response.text
                break
            except Exception as e:
                print(f"⚠️ Errore con {modello}: {e}", flush=True)
                time.sleep(3)
        if testo_risposta:
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
            
            nuova_scheda = None
            if json_memoria_str != "NO_CHANGE":
                if json_memoria_str.startswith("```"):
                    json_memoria_str = json_memoria_str.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                nuova_scheda = json.loads(json_memoria_str)

            modificato = applica_commit_github(nuovo_config, nuova_scheda)
        except Exception as e:
            print(f"⚠️ Errore parsing JSON da Gemini: {e}", flush=True)

    intestazione = "🧠 *[AI AUDITOR - SETTIMANALE STRATEGICO]*\n\n" if is_domenica else "⚡ *[AI AUDITOR - RADAR VOLUMI & HARVESTING]*\n\n"
    if modificato:
        report_telegram += "\n\n🚀 *[PARAMETRI & MEMORIA AGGIORNATI SU GITHUB]*"

    invia_telegram(intestazione + report_telegram)
    print("✅ Audit completato con successo!", flush=True)

if __name__ == "__main__":
    esegui_audit()

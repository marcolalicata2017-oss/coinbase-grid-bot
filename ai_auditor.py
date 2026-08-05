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

def invia_telegram(messaggio):
    """Invia un messaggio a Telegram gestendo automaticamente i fallimenti di parsing Markdown."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Token o Chat ID Telegram non configurati.", flush=True)
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    # 1. Tentativo primario con Markdown
    payload_markdown = {
        "chat_id": TELEGRAM_CHAT_ID, 
        "text": messaggio, 
        "parse_mode": "Markdown"
    }
    
    try:
        resp = requests.post(url, json=payload_markdown, timeout=10)
        
        # 2. Se Telegram rifiuta la formattazione (Error 400 Bad Request), riprova in testo semplice
        if resp.status_code != 200:
            print(f"⚠️ Errore Telegram API ({resp.status_code}): {resp.text}", flush=True)
            print("🔄 Riprovo l'invio in formato TESTO SEMPLICE (senza Markdown)...", flush=True)
            
            payload_plain = {
                "chat_id": TELEGRAM_CHAT_ID, 
                "text": messaggio
            }
            resp_retry = requests.post(url, json=payload_plain, timeout=10)
            
            if resp_retry.status_code == 200:
                print("✅ Notifica inviata con successo in testo semplice!", flush=True)
            else:
                print(f"❌ Fallimento definitivo invio Telegram: {resp_retry.text}", flush=True)
        else:
            print("✅ Notifica Telegram inviata con successo!", flush=True)
            
    except Exception as e:
        print(f"❌ Errore di rete durante l'invio a Telegram: {e}", flush=True)

def ottieni_altcoin_eur_disponibili_coinbase():
    """Recupera dinamicamente via API l'elenco aggiornato di tutti i pair SPOT EUR reali su Coinbase."""
    try:
        url = "https://api.exchange.coinbase.com/products"
        headers = {"User-Agent": "Python-Bot"}
        resp = requests.get(url, headers=headers, timeout=10)
        
        if resp.status_code == 200:
            prodotti = resp.json()
            coppie_eur_valide = []
            
            esclusi = ["USDC-EUR", "EURC-EUR", "USDT-EUR", "BTC-EUR", "ETH-EUR"]
            
            for p in prodotti:
                id_pair = p.get("id", "")
                quote = p.get("quote_currency", "")
                status = p.get("status", "")
                disabled = p.get("trading_disabled", False)
                
                if quote == "EUR" and status == "online" and not disabled:
                    if id_pair not in esclusi:
                        coppie_eur_valide.append(id_pair)
            
            coppie_eur_valide.sort()
            print(f"📡 [COINBASE API] Trovati {len(coppie_eur_valide)} pair Spot EUR attivi.", flush=True)
            return coppie_eur_valide
    except Exception as e:
        print(f"⚠️ Errore recupero pair dinamici da Coinbase: {e}", flush=True)
    
    return ["LINK-EUR", "ADA-EUR", "NEAR-EUR", "DOT-EUR", "AVAX-EUR", "XRP-EUR", "ATOM-EUR", "ALGO-EUR"]

def carica_memoria_storica():
    """Carica lo storico delle decisioni e delle lezioni apprese."""
    if os.path.exists(FILE_MEMORIA):
        try:
            with open(FILE_MEMORIA, "r", encoding="utf-8") as f:
                contenuto = f.read().strip()
                if contenuto:
                    return json.loads(contenuto)
        except Exception as e:
            print(f"⚠️ Errore lettura memoria storica: {e}", flush=True)
    return []

def salva_memoria_storica(memoria):
    """Salva la memoria aggiornata su file JSON."""
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
            subprocess.run(["git", "commit", "-m", "🤖 Auto-tuning e aggiornamento memoria da AI Auditor"], check=True)
            subprocess.run(["git", "push"], check=True)
            print("✅ config.json e memoria_decisioni_ai.json committati su GitHub!", flush=True)
            return True
        else:
            print("ℹ️ Nessuna modifica sostanziale da committare.", flush=True)
            return False
    except Exception as e:
        print(f"❌ Errore durante l'auto-commit su GitHub: {e}", flush=True)
        return False

def esegui_audit():
    if not GEMINI_API_KEY:
        print("❌ API Key di Gemini non configurata!", flush=True)
        return

    client = genai.Client(api_key=GEMINI_API_KEY)

    # Legge il diario tollerando righe corrotte (on_bad_lines='skip')
    df_diario = pd.read_csv(FILE_DIARIO, on_bad_lines='skip') if os.path.exists(FILE_DIARIO) else pd.DataFrame()
    df_portafoglio = pd.read_csv(FILE_PORTAFOGLIO) if os.path.exists(FILE_PORTAFOGLIO) else pd.DataFrame()
    memoria_storica = carica_memoria_storica()
    altcoin_disponibili = ottieni_altcoin_eur_disponibili_coinbase()

    config_attuale = {}
    if os.path.exists(FILE_CONFIG):
        try:
            with open(FILE_CONFIG, "r", encoding="utf-8") as f:
                config_attuale = json.load(f)
        except Exception as e:
            print(f"⚠️ Errore lettura config.json: {e}", flush=True)

    ora_dt = datetime.now()
    is_domenica = (ora_dt.weekday() == 6)

    data_limite = (ora_dt - timedelta(days=7 if is_domenica else 1)).strftime("%Y-%m-%d")
    diario_rec = df_diario[df_diario['Data_Ora'] >= data_limite] if not df_diario.empty and 'Data_Ora' in df_diario.columns else pd.DataFrame()

    prompt = f"""
    Sei un Portfolio Manager & Risk Manager Quantitativo spietato, focalizzato unicamente sulla PROFITTABILITÀ NETTA (Net Spread Efficiency). Operi in ambiente di Grid Trading Crypto su Coinbase.

    Data Corrente: {ora_dt.strftime('%Y-%m-%d')}
    Tipo Audit: {"SETTIMANALE STRATEGICO & AUTO-TUNING (CORE + SATELLITE)" if is_domenica else "GIORNALIERO TATTICO (SOLO MODULO SATELLITE)"}

    ⚡ STRUTTURA COMMISSIONI COINBASE ADVANCED (PROFILO INTRO 2):
    - Maker Fee: 0.35% (Ordini limite immessi sul book)
    - Taker Fee: 0.75% (Ordini a mercato o esecuzioni immediate)
    - Soglia Minima d'Ordine: 5.00 EUR

    🎯 VINCOLO TASSATIVO SUL MARGINE NETTO (NET PROFIT RULE):
    1. NON impostare MAI una 'grid_dist_sell' inferiore a 0.02 (2.0%). Con fee Maker totali dello 0.70% (0.35% buy + 0.35% sell), impostare spread inferiori distrugge la profittabilità netta.
    2. Se l'asset ha alta volatilità, imposta 'grid_dist_sell' a 0.025 (2.5%) o 0.03 (3.0%) per catturare un margine reale pulito > 1.5%.

    CONFIGURAZIONE ATTUALE BOT (config.json):
    {json.dumps(config_attuale, indent=2) if config_attuale else "Nessun config.json trovato."}

    MEMORIA STORICA DELLE TUE DECISIONI PASSATE (Lezioni Apprese):
    {json.dumps(memoria_storica[-5:], indent=2) if memoria_storica else "Nessun dato di memoria storica registrato."}

    DATI DIARIO DI BORDO RECENTI (Saldi Reali EUR e Crypto in carico):
    {diario_rec.to_string() if not diario_rec.empty else "Nessuna operazione registrata nel periodo."}

    📡 ELENCO DINAMICO MERCATI SPOT EUR ATTUALMENTE DISPONIBILI E SCAMBIABILI SU COINBASE:
    {json.dumps(altcoin_disponibili)}

    GUIDA ALLA LETTURA DEL DIARIO DI BORDO:
    - Messaggi come 'SELL Eseguito su Exchange', 'Riallineamento Ordine SELL Mancante' o 'Dynamic Profit' indicano VENDITE COMPLETATE CON SUCCESSO dall'exchange con incasso di profitto. NON rappresentano errori o malfunzionamenti.

    ARCHITETTURA DI PORTAFOGLIO IN CORSA (CORE-SATELLITE 90/10):
    1. Operatività sui Saldi Reali: Lavora sulla cassa EUR effettiva e sulle posizioni aperte. NON ipotizzare depositi o budget teorici.
    2. Proporzioni ("target_weight_pct"):
       - MODULO CORE (totale 90.0%): Destinato alla stabilità (tipicamente BTC, ETH e opzionalmente SOL).
       - MODULO SATELLITE (totale 10.0%): Riservato a 1 singola altcoin ad alta volatilità opportunistica. Se la cassa EUR è ridotta, NON frazionare il Satellite su più monete: mantieni UN SOLO asset per superare sempre il minimo d'ordine di 5.00 EUR.

    🎯 EFFICIENZA E ROTAZIONE COIN SATELLITE (OGNI GIORNO):
    - Confronta i risultati correnti con le tue decisioni passate memorizzate. Se una decisione recente si è rivelata sub-ottimale, estrai una 'Lezione Appresa'.
    - Analizza la performance dell'altcoin marcata con "type": "satellite".
    - Se l'altcoin Satellite in carico (es. LINK-EUR) sta generando esecuzioni e profitti costanti, MANTIENILA invariata.
    - Cambia la coin Satellite SOLO SE:
      a) La coin in carico entra in un trend fortemente ribassista (Circuit Breaker attivo, priva di volatilità o in perdita persistente).
      b) Un'altra altcoin nell'Elenco Dinamico presenta uno score di profittabilità nettamente superiore (almeno +20%) per volatilità e struttura di mercato.
    - In caso di dismissione/rotazione:
      * Imposta "exit_strategy": "market_sell" (per liquidare subito in EUR) oppure "soft_exit" sulla vecchia coin.
      * Seleziona la nuova altcoin SCEGLIENDO TASSATIVAMENTE DALL'ELENCO DINAMICO SOPRA e inseriscila con "target_weight_pct": 10.0.
      * NON inventare ticker e NON selezionare coppie non presenti nell'Elenco Dinamico.
    - NEI GIORNI FERIALI (Lunedì-Sabato): NON modificare i parametri della sezione CORE (type: "core").

    VALUTAZIONE DINAMICA SU SOLANA (SOL-EUR):
    1. MANTENERLA nel Core (type: "core") con quota percentuale adeguata se produce profitti costanti.
    2. SPOSTARLA nello slot Satellite (type: "satellite") con "target_weight_pct": 10.0 se la ritieni più adatta ad uscite rapide.
    3. DISMETTERLA portando "target_weight_pct": 0.0 ed impostando "exit_strategy": "soft_exit" (o "market_sell" se c'è rischio crollo).

    LA DOMENICA (AUDIT SETTIMANALE):
    Puoi ricalibrare sia i parametri del CORE (grid_dist_buy, grid_dist_sell >= 0.02, target_weight_pct) sia la coin del SATELLITE.

    GUARDRAILS OBBLIGATORI DA RISPETTARE NEL JSON:
    - La somma di tutti i "target_weight_pct" degli asset attivi deve fare SEMPRE 100.0.
    - Nessuna distanza griglia buy (grid_dist_buy) può scendere sotto 0.008 o salire sopra 0.05.
    - Nessuna distanza griglia sell (grid_dist_sell) può scendere sotto 0.020 (2.0%).

    STRUTTURA DI RISPOSTA RICHIESTA:
    Fornisci la tua risposta strutturata in TRE parti separate esattamente dai delimitatori '---JSON_CONFIG---' e '---JSON_MEMORIA---':
    
    Parte 1: Report narrativo in italiano formattato in Markdown per Telegram (Includi una sezione '🧠 LEZIONI DALL'ESPERIENZA & DECISIONI PASSATE' e '💰 ANALISI MARGINALITÀ NETTA').
    ---JSON_CONFIG---
    Parte 2: La nuova struttura del file config.json valida (oppure scrivi 'NO_CHANGE' se non servono modifiche).
    ---JSON_MEMORIA---
    Parte 3: Un oggetto JSON contenente la nuova scheda di memoria da registrare (oppure scrivi 'NO_CHANGE'). 
    Esempio di struttura della scheda di memoria:
    {{
      "data": "{ora_dt.strftime('%Y-%m-%d')}",
      "tipo_audit": "{'settimanale' if is_domenica else 'giornaliero'}",
      "decisione": "Descrizione sintetica delle modifiche apportate",
      "motivazione": "Spiegazione quantitativa della scelta e calcolo fee",
      "lezione_appresa": "Cosa si impara dai dati recenti rispetto alle decisioni passate"
    }}
    """

    modelli_disponibili = ['gemini-3.5-flash', 'gemini-3.6-flash']
    testo_risposta = None

    for modello in modelli_disponibili:
        for tentativo in range(3):
            try:
                print(f"🔄 Tentativo di chiamata con modello: {modello} (tentativo {tentativo + 1})...", flush=True)
                response = client.models.generate_content(
                    model=modello,
                    contents=prompt
                )
                testo_risposta = response.text
                break
            except Exception as e:
                err_str = str(e)
                if "503" in err_str or "UNAVAILABLE" in err_str or "429" in err_str:
                    attesa = 4 * (tentativo + 1)
                    print(f"⚠️ Attesa {attesa}s per saturazione su {modello}...", flush=True)
                    time.sleep(attesa)
                else:
                    print(f"⚠️ Errore con {modello}: {e}", flush=True)
                    break
        if testo_risposta:
            break

    if not testo_risposta:
        print("❌ Impossibile completare l'audit su tutti i modelli.", flush=True)
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
            print(f"⚠️ Errore durante il parsing del JSON da Gemini: {e}", flush=True)

    intestazione = "🧠 *[AI AUDITOR - AUDIT SETTIMANALE & AUTO-TUNING]*\n\n" if is_domenica else "🛰️ *[AI AUDITOR - DAILY SATELLITE CHECK]*\n\n"
    if modificato:
        report_telegram += "\n\n🚀 *[AUTO-TUNING & MEMORIA APPLICATI]*: `config.json` e `memoria_decisioni_ai.json` aggiornati su GitHub."

    invia_telegram(intestazione + report_telegram)
    print("✅ Audit completato con successo e notifica Telegram inviata!", flush=True)

if __name__ == "__main__":
    esegui_audit()

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
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: 
        print("⚠️ Token o Chat ID Telegram non configurati!")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": messaggio, "parse_mode": "Markdown"}
        requests.post(url, data=data, timeout=10)
    except Exception as e:
        print(f"⚠️ Errore invio Telegram: {e}")

def carica_memoria_storica():
    """Carica lo storico delle decisioni e delle lezioni apprese."""
    if os.path.exists(FILE_MEMORIA):
        try:
            with open(FILE_MEMORIA, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Errore lettura memoria storica: {e}")
    return []

def salva_memoria_storica(memoria):
    """Salva la memoria aggiornata su file JSON."""
    try:
        with open(FILE_MEMORIA, "w", encoding="utf-8") as f:
            json.dump(memoria, f, indent=2, ensure_ascii=False)
        print("🧠 Memoria decisionale salvata su file.")
    except Exception as e:
        print(f"⚠️ Errore salvataggio memoria storica: {e}")

def applica_commit_github(nuovo_config, nuova_scheda_memoria=None):
    try:
        # 1. Scrittura nuovo config.json
        with open(FILE_CONFIG, "w", encoding="utf-8") as f:
            json.dump(nuovo_config, f, indent=2)
        
        # 2. Scrittura memoria se presente
        if nuova_scheda_memoria:
            memoria = carica_memoria_storica()
            memoria.append(nuova_scheda_memoria)
            salva_memoria_storica(memoria)

        # 3. Configurazione Git
        subprocess.run(["git", "config", "user.name", "AI-Auditor-Bot"], check=True)
        subprocess.run(["git", "config", "user.email", "ai-auditor@bot.local"], check=True)
        
        # 4. Git Add per config.json e memoria
        subprocess.run(["git", "add", FILE_CONFIG], check=True)
        if os.path.exists(FILE_MEMORIA):
            subprocess.run(["git", "add", FILE_MEMORIA], check=True)

        result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        
        if result.stdout.strip():
            subprocess.run(["git", "commit", "-m", "🤖 Auto-tuning e aggiornamento memoria da AI Auditor"], check=True)
            subprocess.run(["git", "push"], check=True)
            print("✅ config.json e memoria_decisioni_ai.json committati su GitHub!")
            return True
        else:
            print("ℹ️ Nessuna modifica sostanziale da committare.")
            return False
    except Exception as e:
        print(f"❌ Errore durante l'auto-commit su GitHub: {e}")
        return False

def esegui_audit():
    if not GEMINI_API_KEY:
        print("❌ API Key di Gemini non configurata!")
        return

    client = genai.Client(api_key=GEMINI_API_KEY)

    df_diario = pd.read_csv(FILE_DIARIO) if os.path.exists(FILE_DIARIO) else pd.DataFrame()
    df_portafoglio = pd.read_csv(FILE_PORTAFOGLIO) if os.path.exists(FILE_PORTAFOGLIO) else pd.DataFrame()
    memoria_storica = carica_memoria_storica()

    config_attuale = {}
    if os.path.exists(FILE_CONFIG):
        try:
            with open(FILE_CONFIG, "r", encoding="utf-8") as f:
                config_attuale = json.load(f)
        except Exception as e:
            print(f"⚠️ Errore lettura config.json: {e}")

    ora_dt = datetime.now()
    is_domenica = (ora_dt.weekday() == 6)

    data_limite = (ora_dt - timedelta(days=7 if is_domenica else 1)).strftime("%Y-%m-%d")
    diario_rec = df_diario[df_diario['Data_Ora'] >= data_limite] if not df_diario.empty and 'Data_Ora' in df_diario.columns else pd.DataFrame()

    prompt = f"""
    Sei un Quant Trader & Risk Manager specializzato in Grid Trading Crypto. Operi con capacità di auto-apprendimento ed esperienza decisionale.
    
    Data Corrente: {ora_dt.strftime('%Y-%m-%d')}
    Tipo Audit: {"SETTIMANALE STRATEGICO & AUTO-TUNING (CORE + SATELLITE)" if is_domenica else "GIORNALIERO TATTICO (SOLO MODULO SATELLITE)"}

    CONFIGURAZIONE ATTUALE BOT (config.json):
    {json.dumps(config_attuale, indent=2) if config_attuale else "Nessun config.json trovato."}

    MEMORIA STORICA DELLE TUE DECISIONI PASSATE (Lezioni Apprese):
    {json.dumps(memoria_storica[-5:], indent=2) if memoria_storica else "Nessun dato di memoria storica registrato."}

    DATI DIARIO DI BORDO RECENTI (Saldi Reali EUR e Crypto in carico):
    {diario_rec.to_string() if not diario_rec.empty else "Nessuna operazione registrata nel periodo."}

    GUIDA ALLA LETTURA DEL DIARIO DI BORDO:
    - Messaggi come 'SELL Eseguito su Exchange', 'Riallineamento Ordine SELL Mancante' o 'Dynamic Profit' indicano VENDITE COMPLETATE CON SUCCESSO dall'exchange con incasso di profitto. NON rappresentano errori o malfunzionamenti.

    ARCHITETTURA DI PORTAFOGLIO IN CORSA (CORE-SATELLITE 90/10):
    1. Operatività sui Saldi Reali: Lavora sulla cassa EUR effettiva e sulle posizioni aperte. NON ipotizzare depositi o budget teorici.
    2. Proporzioni ("target_weight_pct"):
       - MODULO CORE (totale 90.0%): Destinato alla stabilità (tipicamente BTC, ETH e opzionalmente SOL).
       - MODULO SATELLITE (totale 10.0%): Riservato a 1 singola altcoin ad alta volatilità opportunistica presente su Coinbase (es. AVAX-EUR, LINK-EUR, ADA-EUR, NEAR-EUR, SUI-EUR, DOT-EUR, APT-EUR).

    LOGICA DI APPRENDIMENTO ED VALUTAZIONE SULLA COIN SATELLITE (OGNI GIORNO):
    - Confronta i risultati correnti con le tue decisioni passate memorizzate. Se una decisione recente si è rivelata sbagliata o sub-ottimale, estrai una 'Lezione Appresa' e non ripetere lo stesso errore.
    - Analizza la performance dell'altcoin attualmente marcata con "type": "satellite".
    - Se è in forte perdita, priva di volatilità utile o in trend fortemente ribassista, DISMETTILA:
      * Imposta "exit_strategy": "market_sell" (per liquidare subito in EUR) oppure "soft_exit".
      * Seleziona LIBERAMENTE una nuova altcoin promettente su exchange e inseriscila come nuova coin "satellite" con "target_weight_pct": 10.0.
    - Se la coin satellite attuale performa bene, MANTIENILA invariata.
    - NEI GIORNI FERIALI (Lunedì-Sabato): NON modificare i parametri della sezione CORE (type: "core").

    VALUTAZIONE DINAMICA SU SOLANA (SOL-EUR):
    Spetta a te decidere come gestirla sulla base dei dati di rendimento reali nel diario di bordo:
    1. MANTENERLA nel Core (type: "core") con una quota percentuale adeguata se sta producendo profitti costanti.
    2. SPOSTARLA nello slot Satellite (type: "satellite") con "target_weight_pct": 10.0 se la ritieni più adatta ad uscite rapide.
    3. DISMETTERLA portando "target_weight_pct": 0.0 ed impostando "exit_strategy": "soft_exit" (o "market_sell" se c'è rischio crollo) per liberare cassa EUR a favore di BTC, ETH o altre altcoin.

    LA DOMENICA (AUDIT SETTIMANALE):
    Puoi ricalibrare sia i parametri del CORE (grid_dist_buy, grid_dist_sell, target_weight_pct) sia la coin del SATELLITE, motivando le scelte in base all'esperienza accumulata.

    GUARDRAILS OBBLIGATORI DA RISPETTARE NEL JSON:
    - La somma di tutti i "target_weight_pct" degli asset attivi deve fare SEMPRE 100.0.
    - Nessuna distanza griglia (buy/sell) può scendere sotto 0.005 o salire sopra 0.05.

    STRUTTURA DI RISPOSTA RICHIESTA:
    Fornisci la tua risposta strutturata in TRE parti separate esattamente dai delimitatori '---JSON_CONFIG---' e '---JSON_MEMORIA---':
    
    Parte 1: Report narrativo in italiano formattato in Markdown per Telegram (Includi una sezione '🧠 LEZIONI DALL'ESPERIENZA & DECISIONI PASSATE').
    ---JSON_CONFIG---
    Parte 2: La nuova struttura del file config.json valida (oppure scrivi 'NO_CHANGE' se non servono modifiche).
    ---JSON_MEMORIA---
    Parte 3: Un oggetto JSON contenente la nuova scheda di memoria da registrare (oppure scrivi 'NO_CHANGE'). 
    Esempio di struttura della scheda di memoria:
    {{
      "data": "{ora_dt.strftime('%Y-%m-%d')}",
      "tipo_audit": "{'settimanale' if is_domenica else 'giornaliero'}",
      "decisione": "Descrizione sintetica delle modifiche apportate",
      "motivazione": "Spiegazione quantitativa della scelta",
      "lezione_appresa": "Cosa si impara dai dati recenti rispetto alle decisioni passate"
    }}
    """

    modelli_disponibili = ['gemini-2.5-flash', 'gemini-1.5-flash']
    testo_risposta = None

    for modello in modelli_disponibili:
        for tentativo in range(3):
            try:
                print(f"🔄 Tentativo di chiamata con modello: {modello} (tentativo {tentativo + 1})...")
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
                    print(f"⚠️ Attesa {attesa}s per saturazione su {modello}...")
                    time.sleep(attesa)
                else:
                    print(f"⚠️ Errore con {modello}: {e}")
                    break
        if testo_risposta:
            break

    if not testo_risposta:
        print("❌ Impossibile completare l'audit su tutti i modelli.")
        return

    # Parsing delle tre sezioni
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
            print(f"⚠️ Errore durante il parsing del JSON da Gemini: {e}")

    intestazione = "🧠 *[AI AUDITOR - AUDIT SETTIMANALE & AUTO-TUNING]*\n\n" if is_domenica else "🛰️ *[AI AUDITOR - DAILY SATELLITE CHECK]*\n\n"
    if modificato:
        report_telegram += "\n\n🚀 *[AUTO-TUNING & MEMORIA APPLICATI]*: `config.json` e `memoria_decisioni_ai.json` aggiornati su GitHub."

    invia_telegram(intestazione + report_telegram)
    print("✅ Audit completato con successo e notifica Telegram inviata!")

if __name__ == "__main__":
    esegui_audit()

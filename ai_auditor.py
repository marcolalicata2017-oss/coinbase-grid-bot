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

def applica_commit_github(nuovo_config):
    try:
        with open(FILE_CONFIG, "w") as f:
            json.dump(nuovo_config, f, indent=2)
        
        # Configura l'utente Git per il commit
        subprocess.run(["git", "config", "user.name", "AI-Auditor-Bot"], check=True)
        subprocess.run(["git", "config", "user.email", "ai-auditor@bot.local"], check=True)
        
        # Esegue commit e push
        subprocess.run(["git", "add", FILE_CONFIG], check=True)
        result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        
        if result.stdout.strip():
            subprocess.run(["git", "commit", "-m", "🤖 Auto-tuning configurazione da AI Auditor"], check=True)
            subprocess.run(["git", "push"], check=True)
            print("✅ config.json aggiornato e committato su GitHub con successo!")
            return True
        else:
            print("ℹ️ Nessuna modifica sostanziale da committare su config.json.")
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
    
    config_attuale = {}
    if os.path.exists(FILE_CONFIG):
        try:
            with open(FILE_CONFIG, "r") as f:
                config_attuale = json.load(f)
        except Exception as e:
            print(f"⚠️ Errore lettura config.json: {e}")

    ora_dt = datetime.now()
    is_domenica = (ora_dt.weekday() == 6)

    data_limite = (ora_dt - timedelta(days=7 if is_domenica else 1)).strftime("%Y-%m-%d")
    diario_rec = df_diario[df_diario['Data_Ora'] >= data_limite] if not df_diario.empty and 'Data_Ora' in df_diario.columns else pd.DataFrame()

    prompt = f"""
    Sei un Quant Trader & Risk Manager specializzato in Grid Trading Crypto.
    
    Data Corrente: {ora_dt.strftime('%Y-%m-%d')}
    Tipo Audit: {"SETTIMANALE STRATEGICO & AUTO-TUNING" if is_domenica else "GIORNALIERO INFORMATIVO"}

    CONFIGURAZIONE ATTUALE BOT (config.json):
    {json.dumps(config_attuale, indent=2) if config_attuale else "Nessun config.json trovato."}

    DATI DIARIO DI BORDO RECENTI:
    {diario_rec.to_string() if not diario_rec.empty else "Nessuna operazione registrata nel periodo."}

    GUIDA ALLA LETTURA DEL DIARIO DI BORDO:
    - Messaggi come 'SELL Eseguito su Exchange', 'Riallineamento Ordine SELL Mancante' o 'Dynamic Profit' indicano VENDITE COMPLETATE CON SUCCESSO dall'exchange con incasso di profitto. NON rappresentano errori o malfunzionamenti.

    STRUTTURA DI RISPOSTA RICHIESTA:
    Fornisci la tua risposta strutturata esattamente in due parti separate dal delimitatore '---JSON_CONFIG---':
    Parte 1: Il report narrativo in italiano formattato in Markdown per Telegram.
    Parte 2: La nuova struttura del file config.json valida (oppure scrivi 'NO_CHANGE' se non servono modifiche).
    """

    if is_domenica:
        prompt += """
        ISTRUZIONI AUDIT SETTIMANALE & AUTO-TUNING:
        1. Analizza le performance del diario di bordo e valuta se ottimizzare i parametri (grid_dist_buy, grid_dist_sell, budget_eur, max_active_levels, exit_strategy).
        2. Per disinvestire o ridurre l'esposizione su un asset a favore di un altro, imposta 'exit_strategy':
           - 'market_sell': se la convenienza di riallocazione immediata o la protezione da crolli supera le perdite.
           - 'soft_exit': se è preferibile bloccare i nuovi acquisti e attendere il recupero degli ordini di vendita esistenti.
        3. GUARDRAILS OBBLIGATORI DA RISPETTARE:
           - Nessuna distanza griglia (buy/sell) può scendere sotto 0.005 o salire sopra 0.05.
           - Nessun singolo asset può superare il 60% del budget totale.
           - Il budget complessivo distribuito deve rimanere pari al totale attuale.
        """
    else:
        prompt += """
        ISTRUZIONI AUDIT GIORNALIERO:
        Sintesi delle operazioni ultime 24h. NON modificare i parametri. Nella Parte 2 restituisci 'NO_CHANGE'.
        """

    modelli_disponibili = ['gemini-3.5-flash', 'gemini-2.5-flash', 'gemini-1.5-flash']
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

    # Separazione del report narrativo dall'eventuale JSON di configurazione
    parti = testo_risposta.split("---JSON_CONFIG---")
    report_telegram = parti[0].strip()
    json_str = parti[1].strip() if len(parti) > 1 else "NO_CHANGE"

    # Gestione Auto-Tuning del config.json
    modificato = False
    if is_domenica and json_str != "NO_CHANGE":
        try:
            # Pulisce eventuali formattazioni markdown tipo ```json ... ```
            if json_str.startswith("```"):
                json_str = json_str.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            
            nuovo_config = json.loads(json_str)
            modificato = applica_commit_github(nuovo_config)
        except Exception as e:
            print(f"⚠️ Errore durante il parsing del nuovo config JSON: {e}")

    # Invio notifica su Telegram
    intestazione = "🧠 *[AI AUDITOR - REPORT SETTIMANALE & AUTO-TUNING]*\n\n" if is_domenica else "🌙 *[AI AUDITOR - DAILY SUMMARY]*\n\n"
    if modificato:
        report_telegram += "\n\n🚀 *[AUTO-TUNING APPLICATO]*: Il file `config.json` è stato aggiornato in autonomia ed è già operativo."

    invia_telegram(intestazione + report_telegram)
    print("✅ Audit completato con successo e notifica Telegram inviata!")

if __name__ == "__main__":
    esegui_audit()

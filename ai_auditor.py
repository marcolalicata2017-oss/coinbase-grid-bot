import os
import json
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

def esegui_audit():
    if not GEMINI_API_KEY:
        print("❌ API Key di Gemini non configurata!")
        return

    # Inizializzazione Client Google GenAI
    client = genai.Client(api_key=GEMINI_API_KEY)

    # Carica Dati e Configurazione
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

    # Filtra dati recenti (7 giorni per la domenica, 1 giorno negli altri casi)
    data_limite = (ora_dt - timedelta(days=7 if is_domenica else 1)).strftime("%Y-%m-%d")
    diario_rec = df_diario[df_diario['Data_Ora'] >= data_limite] if not df_diario.empty and 'Data_Ora' in df_diario.columns else pd.DataFrame()

    prompt = f"""
    Sei un Quant Trader & Risk Manager specializzato in Grid Trading per mercati Crypto.
    
    Data Corrente: {ora_dt.strftime('%Y-%m-%d')}
    Tipo Audit: {"SETTIMANALE STRATEGICO & BACKTEST" if is_domenica else "GIORNALIERO INFORMATIVO"}

    CONFIGURAZIONE ATTUALE BOT (config.json):
    {json.dumps(config_attuale, indent=2) if config_attuale else "Nessun config.json trovato."}

    DATI DIARIO DI BORDO RECENTI:
    {diario_rec.to_string() if not diario_rec.empty else "Nessuna operazione registrata nel periodo."}

    Fornisci un report sintetico in italiano formattato per Telegram (in Markdown).
    """

    if is_domenica:
        prompt += """
        ISTRUZIONI AUDIT SETTIMANALE:
        1. **Valutazione Ottimizzazione:** Analizza i dati registrati nel diario di bordo della settimana appena trascorsa rispetto alle configurazioni attuali.
        2. **Backtest e Simulazione:** Valuta se parametrizzazioni alternative (es. distanze griglia `grid_dist` più strette/larghe, o diversa allocazione budget) avrebbero massimizzato la profittabilità netta tenendo conto dei prezzi toccati, della volatilità reale e delle commissioni.
        3. **Regola della Potenzialità Netta:** 
           - SE e SOLO SE il backtest/simulazione mostra un margine di miglioramento concreto e significativo rispetto alla resa attuale, proponi le modifiche motivandole con i numeri della simulazione.
           - SE la configurazione attuale risulta già ottimale o se non ci sono margini di miglioramento rilevanti, CONFERMA esplicitamente che le configurazioni attuali sono già massimizzate per il regime di mercato rilevato. NON proporre modifiche per forza.
        """
    else:
        prompt += """
        ISTRUZIONI AUDIT GIORNALIERO:
        Fai solo una sintesi rapida ed essenziale delle operazioni delle ultime 24h, indicando se lo stato del portafoglio e il comportamento del bot sono stati regolari. NON proporre modifiche ai parametri.
        """

    try:
        # Uso dell'alias universale 'gemini-1.5-flash-latest' per evitare errori 404
        response = client.models.generate_content(
            model='gemini-1.5-flash-latest',
            contents=prompt
        )
        testo_report = response.text
        
        intestazione = "🧠 *[AI AUDITOR - REPORT SETTIMANALE & BACKTEST]*\n\n" if is_domenica else "🌙 *[AI AUDITOR - DAILY SUMMARY]*\n\n"
        invia_telegram(intestazione + testo_report)
        print("✅ Audit completato e notifica Telegram inviata!")
    except Exception as e:
        print(f"❌ Errore durante l'audit AI: {e}")

if __name__ == "__main__":
    esegui_audit()

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

def invia_telegram(messaggio):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
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

    # Inizializzazione Client Ufficiale Google GenAI
    client = genai.Client(api_key=GEMINI_API_KEY)

    # Carica Dati
    df_diario = pd.read_csv(FILE_DIARIO) if os.path.exists(FILE_DIARIO) else pd.DataFrame()
    df_portafoglio = pd.read_csv(FILE_PORTAFOGLIO) if os.path.exists(FILE_PORTAFOGLIO) else pd.DataFrame()

    ora_dt = datetime.now()
    is_domenica = (ora_dt.weekday() == 6)

    # Filtra dati recenti
    data_limite = (ora_dt - timedelta(days=7 if is_domenica else 1)).strftime("%Y-%m-%d")
    
    diario_rec = df_diario[df_diario['Data_Ora'] >= data_limite] if not df_diario.empty else pd.DataFrame()

    prompt = f"""
    Sei un AI Post-Trade Auditor e Risk Manager per un bot quantitativo di trading a griglia su Coinbase.
    
    Data Corrente: {ora_dt.strftime('%Y-%m-%d')}
    Tipo Audit: {"SETTIMANALE STRATEGICO" if is_domenica else "GIORNALIERO INFORMATIVO"}

    Dati Diario di Bordo recenti:
    {diario_rec.to_string() if not diario_rec.empty else "Nessuna operazione registrata nel periodo."}

    Fornisci un report sintetico in italiano formattato per Telegram (Markdown).
    """

    if is_domenica:
        prompt += """
        Trattandosi del Report Settimanale, analizza l'efficienza delle griglie e fornisci 2-3 raccomandazioni concrete sui parametri (es. distanze griglia o budget) motivando le scelte.
        """
    else:
        prompt += """
        Trattandosi del Report Giornaliero, fai solo una sintesi delle operazioni delle ultime 24h, indicando se lo stato del portafoglio e il comportamento del bot sono stati regolari. NON proporre modifiche ai parametri.
        """

    try:
        # Usiamo il modello stabile gemini-1.5-flash
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt,
        )
        testo_report = response.text
        
        intestazione = "🧠 *[AI AUDITOR - REPORT SETTIMANALE]*\n\n" if is_domenica else "🌙 *[AI AUDITOR - DAILY SUMMARY]*\n\n"
        invia_telegram(intestazione + testo_report)
        print("✅ Audit completato e notifica Telegram inviata!")
    except Exception as e:
        print(f"❌ Errore durante l'audit AI: {e}")

if __name__ == "__main__":
    esegui_audit()

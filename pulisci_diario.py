import os
import pandas as pd

FILE_DIARIO = "diario_di_bordo.csv"

if os.path.exists(FILE_DIARIO):
    df = pd.read_csv(FILE_DIARIO)
    righe_prima = len(df)
    
    # Rimuove le righe duplicate basate su Asset, Prezzo e Motivo
    df_pulito = df.drop_duplicates(subset=["Pair", "Prezzo_Pivot", "Motivo"], keep="first")
    
    # Rimuove eventuali log fantasma con ordini a vuoto
    df_pulito = df_pulito[~df_pulito["Motivo"].str.contains("BUY Eseguito.*Falso", na=False)]
    
    df_pulito.to_csv(FILE_DIARIO, index=False)
    print(f"✅ Pulizia completata: rimosse {righe_prima - len(df_pulito)} righe spazzatura. Righe residue: {len(df_pulito)}")
else:
    print("⚠️ File diario_di_bordo.csv non trovato.")

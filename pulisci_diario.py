import os
import pandas as pd

FILE_DIARIO = "diario_di_bordo.csv"

if os.path.exists(FILE_DIARIO):
    df = pd.read_csv(FILE_DIARIO)
    righe_prima = len(df)
    
    # Colonne chiave che identificano uno stato identico di portafoglio/operazione
    colonne_stato = ["Pair", "Prezzo_Pivot", "Saldo_EUR_Pool", "Crypto_Posseduta", "Motivo"]
    
    # Verifica che le colonne esistano nel CSV prima di filtrare
    colonne_presenti = [c for c in colonne_stato if c in df.columns]
    
    if colonne_presenti:
        # Identifica e rimuove solo i duplicati consecutivi con lo stesso saldo e prezzo
        maschera_duplicati_consecutivi = (
            df[colonne_presenti] == df[colonne_presenti].shift(1)
        ).all(axis=1)
        
        df_pulito = df[~maschera_duplicati_consecutivi]
        
        df_pulito.to_csv(FILE_DIARIO, index=False)
        rimosse = righe_prima - len(df_pulito)
        print(f"✅ Pulizia completata: rimosse {rimosse} righe duplicate a saldo invariato. Righe salvate: {len(df_pulito)}")
    else:
        print("⚠️ Colonne di controllo non trovate nel file CSV.")
else:
    print(f"⚠️ File {FILE_DIARIO} non trovato.")

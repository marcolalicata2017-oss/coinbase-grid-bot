import os
import pandas as pd

FILE_DIARIO = "diario_di_bordo.csv"

if os.path.exists(FILE_DIARIO):
    df = pd.read_csv(FILE_DIARIO)
    righe_prima = len(df)
    
    # 1. Colonne che definiscono uno stato di portafoglio/ordine identico
    colonne_chiave = ["Pair", "Prezzo_Pivot", "Saldo_EUR_Pool", "Crypto_Posseduta", "Motivo"]
    colonne_presenti = [c for c in colonne_chiave if c in df.columns]
    
    if colonne_presenti:
        # 2. Ordina cronologicamente se presente la data
        if "Data_Ora" in df.columns:
            df["Data_Ora"] = pd.to_datetime(df["Data_Ora"], errors="coerce")
            df = df.sort_values(by=["Pair", "Data_Ora"])
        
        # 3. Rileva i duplicati consecutivi RAGGRUPPATI per singolo Pair
        maschera_duplicati = (
            df.groupby("Pair")[colonne_presenti].shift(1) == df[colonne_presenti]
        ).all(axis=1)
        
        df_pulito = df[~maschera_duplicati]
        
        # 4. Ripristina l'ordinamento cronologico originale
        if "Data_Ora" in df_pulito.columns:
            df_pulito = df_pulito.sort_values(by="Data_Ora")
            df_pulito["Data_Ora"] = df_pulito["Data_Ora"].dt.strftime("%Y-%m-%d %H:%M:%S")
        
        df_pulito.to_csv(FILE_DIARIO, index=False)
        rimosse = righe_prima - len(df_pulito)
        print(f" Pulizia completata: rimosse {rimosse} righe duplicate. Righe residue: {len(df_pulito)}")
    else:
        print(" Colonne di controllo non trovate nel file CSV.")
else:
    print(f" File {FILE_DIARIO} non trovato.")

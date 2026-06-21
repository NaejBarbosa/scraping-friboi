import sqlite3
import csv
import subprocess
import os

db_path = '/root/scraping-friboi/friboi_catalogo.db'
csv_path = '/sdcard/Download/duplicidades_friboi.csv'

# Garante que o diretório de destino exista
os.makedirs(os.path.dirname(csv_path), exist_ok=True)

print("Iniciando a exportação das duplicidades de EAN para CSV...")

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

query = """
SELECT ean, sku, title, marca, classe, conservacao
FROM produtos
WHERE ean IN (
    SELECT ean 
    FROM produtos 
    WHERE ean IS NOT NULL AND ean != 'N/A' AND ean != '' 
    GROUP BY ean 
    HAVING COUNT(*) > 1
)
ORDER BY ean, sku;
"""

try:
    cursor.execute(query)
    rows = cursor.fetchall()
    headers = ['ean', 'sku', 'title', 'marca', 'classe', 'conservacao']

    # Gravação no formato cp1252 (Windows-1252) com delimitador ponto e vírgula (;)
    with open(csv_path, mode='w', encoding='cp1252', newline='', errors='replace') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(headers)
        for row in rows:
            # Limpa aspas que possam ter vindo do banco e trata campos nulos
            clean_row = [str(col).strip("'\"") if col is not None else '' for col in row]
            writer.writerow(clean_row)

    print(f"Planilha de duplicidades exportada com sucesso para: {csv_path}")

    # Força a indexação do arquivo no Android para ser visível imediatamente
    print("Executando termux-media-scan para indexar o arquivo no dispositivo...")
    subprocess.run(['termux-media-scan', csv_path], check=True)
    print("Processo de scan de mídia concluído!")

except Exception as e:
    print(f"Ocorreu um erro durante o processo: {e}")
finally:
    conn.close()

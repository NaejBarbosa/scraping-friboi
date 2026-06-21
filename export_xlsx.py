import sqlite3
import subprocess
import os
from openpyxl import Workbook

db_path = '/root/scraping-friboi/friboi_catalogo.db'
download_dir = '/sdcard/Download'

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

def clean_val(val):
    if val is None:
        return ""
    # Limpa aspas que possam ter vindo do banco
    return str(val).strip("'\"")

def generate_xlsx(query, headers, filename):
    cursor.execute(query)
    rows = cursor.fetchall()
    
    wb = Workbook()
    ws = wb.active
    ws.title = "Dados"
    
    # Adiciona cabeçalho
    ws.append(headers)
    
    # Adiciona as linhas de dados
    for row in rows:
        clean_row = [clean_val(cell) for cell in row]
        ws.append(clean_row)
        
    xlsx_path = os.path.join(download_dir, filename)
    wb.save(xlsx_path)
    
    print(f"Planilha XLSX gerada com sucesso: {xlsx_path}")
    try:
        subprocess.run(['termux-media-scan', xlsx_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"Indexação realizada com sucesso para {filename}!")
    except Exception as e:
        print(f"Erro no media-scan para {filename}: {e}")

# 1. Exporta as duplicidades de EAN para XLSX
generate_xlsx(
    """
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
    """, 
    ['ean', 'sku', 'title', 'marca', 'classe', 'conservacao'], 
    'friboi_duplicidades_final.xlsx'
)

# 2. Exporta todo o catálogo de produtos para XLSX
generate_xlsx(
    "SELECT sku, title, descrFiscal, ean, dun, marca, classe, conservacao, pesoLiquido, pesoBruto, url FROM produtos", 
    ['sku', 'title', 'descrFiscal', 'ean', 'dun', 'marca', 'classe', 'conservacao', 'pesoLiquido', 'pesoBruto', 'url'], 
    'friboi_produtos_final.xlsx'
)

conn.close()
print("Exportação final XLSX concluída!")

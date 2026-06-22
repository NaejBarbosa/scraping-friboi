#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Nome: fill_product_images.py
Descrição: Script autônomo para enriquecer o banco de dados do catálogo Friboi,
           adicionando as URLs das imagens dos produtos extraídas da API do portal B2B.
Autor: Antigravity - Engenheiro de Dados Sênior
"""

import os
import sys
import time
import sqlite3
import requests
import argparse

# Configurações de API
API_PRODUCT_TEMPLATE = "https://www.friboionline.com.br/ccstoreui/v1/products/{sku}"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept-Encoding': 'gzip, deflate, br'
}
BASE_URL = "https://www.friboionline.com.br"

def init_column(db_path):
    """
    Verifica se a coluna 'image_url' existe na tabela 'produtos'.
    Caso não exista, adiciona-a via ALTER TABLE.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Obtém informações sobre as colunas da tabela produtos
    cursor.execute("PRAGMA table_info(produtos)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if 'image_url' not in columns:
        print("[*] Adicionando coluna 'image_url' na tabela 'produtos'...")
        cursor.execute("ALTER TABLE produtos ADD COLUMN image_url TEXT")
        conn.commit()
        print("[+] Coluna 'image_url' adicionada com sucesso.")
    else:
        print("[*] Coluna 'image_url' já existente no banco de dados.")
        
    conn.close()

def make_request_with_retry(url, max_retries=3, delay=2):
    """
    Realiza requisições HTTP GET com lógica de retentativas.
    """
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=HEADERS, timeout=15)
            if response.status_code == 200:
                return response
            elif response.status_code in [404, 400]:
                # Erro definitivo
                return response
            else:
                print(f"\n  [!] Recebido HTTP {response.status_code}. Retentando {attempt+1}/{max_retries}...")
        except requests.RequestException as e:
            print(f"\n  [!] Conexão falhou/timeout: {e}. Retentando {attempt+1}/{max_retries}...")
        
        time.sleep(delay * (attempt + 1))
    return None

def main():
    parser = argparse.ArgumentParser(description="fill_product_images: Adiciona URLs de imagens de produtos no banco SQLite.")
    parser.add_argument('--db', type=str, default='/root/scraping-friboi/friboi_catalogo.db', 
                        help='Caminho absoluto para o banco SQLite (default: /root/scraping-friboi/friboi_catalogo.db)')
    parser.add_argument('--delay', type=float, default=0.5, 
                        help='Intervalo de cortesia em segundos entre requisições (default: 0.5)')
    parser.add_argument('--limit', type=int, default=None,
                        help='Número máximo de produtos a processar nesta execução')
    args = parser.parse_args()
    
    db_path = args.db
    delay_time = args.delay
    limit = args.limit
    
    if not os.path.exists(db_path):
        print(f"[!] Banco de dados SQLite não encontrado no caminho: {db_path}")
        sys.exit(1)
        
    print(f"[*] Conectando ao banco de dados SQLite: {db_path}")
    init_column(db_path)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Seleciona produtos que ainda não têm imagem associada
    query = """
    SELECT sku, title 
    FROM produtos 
    WHERE image_url IS NULL OR image_url = ''
    """
    
    cursor.execute(query)
    pending_products = cursor.fetchall()
    total_pending = len(pending_products)
    
    print(f"[*] Total de produtos sem imagem: {total_pending}")
    
    if total_pending == 0:
        print("[*] Todos os produtos do banco já possuem imagens associadas. Processo encerrado.")
        conn.close()
        sys.exit(0)
        
    if limit:
        pending_products = pending_products[:limit]
        print(f"[*] Limitando execução para os primeiros {len(pending_products)} produtos.")
        
    processed_count = 0
    updated_count = 0
    errors_count = 0
    
    print("\n" + "="*75)
    print("Iniciando a busca e enriquecimento de URLs de imagem...")
    print("="*75 + "\n")
    
    for sku, title in pending_products:
        processed_count += 1
        print(f"[{processed_count}/{len(pending_products)}] Processando SKU: {sku} | '{title[:45]}...'")
        
        api_url = API_PRODUCT_TEMPLATE.format(sku=sku)
        response = make_request_with_retry(api_url)
        
        image_url = "N/A"
        
        if response and response.status_code == 200:
            try:
                data = response.json()
                # Tenta extrair a imagem em alta resolução (primaryFullImageURL) ou secundárias (primaryMediumImageURL)
                api_image = data.get('primaryFullImageURL') or data.get('primaryMediumImageURL') or data.get('primaryLargeImageURL')
                
                if api_image:
                    # Converte URL relativa para absoluta se necessário
                    if api_image.startswith('/'):
                        image_url = BASE_URL + api_image
                    else:
                        image_url = api_image
                        
                    # Grava no banco de dados imediatamente
                    cursor.execute("""
                        UPDATE produtos 
                        SET image_url = ? 
                        WHERE sku = ?
                    """, (image_url, sku))
                    conn.commit()
                    updated_count += 1
                    print(f"  [OK] Imagem vinculada: {image_url}")
                else:
                    # Nenhum campo de imagem encontrado na API
                    cursor.execute("""
                        UPDATE produtos 
                        SET image_url = 'N/A' 
                        WHERE sku = ?
                    """, (sku,))
                    conn.commit()
                    print("  [!] Nenhuma imagem disponível no retorno da API (marcado como N/A).")
            except Exception as e:
                errors_count += 1
                print(f"  [!] Erro ao parsear JSON da API: {e}")
        elif response and response.status_code == 404:
            # SKU não encontrado no portal atual, marca como N/A para evitar loops infinitos
            cursor.execute("""
                UPDATE produtos 
                SET image_url = 'N/A' 
                WHERE sku = ?
            """, (sku,))
            conn.commit()
            print("  [!] SKU não localizado na API (404) - Marcado como N/A.")
        else:
            errors_count += 1
            print("  [!] Falha ao se conectar com a API ou timeout persistente.")
            
        print("-" * 55)
        time.sleep(delay_time)
        
    conn.close()
    
    print("\n" + "="*75)
    print("Processamento de Imagens Concluído!")
    print(f"Total analisado nesta rodada: {processed_count}")
    print(f"URLs de imagens salvas: {updated_count}")
    print(f"Erros encontrados: {errors_count}")
    print("="*75 + "\n")

if __name__ == '__main__':
    main()

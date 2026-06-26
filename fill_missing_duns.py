#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Nome: fill_missing_duns.py
Descrição: Script autônomo para ambiente Termux/Android que localiza, valida e preenche 
           os códigos DUN-14 faltantes no banco de dados SQLite do catálogo Friboi.
Autor: Antigravity - Engenheiro de Dados Sênior
"""

import os
import sys
import re
import time
import sqlite3
import random
import unicodedata
import argparse
import requests
from bs4 import BeautifulSoup

# Lista de User-Agents realistas para evitar bloqueios de robôs simples
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
]

# Ordem inteligente dos prefixos logísticos baseada na probabilidade de ocorrência
# 1 = Caixa de embarque padrão (Mais comum)
# 2 = Embalagem contendo múltiplos pacotes menores
# 9 = Peso variável (Altamente comum em carnes in natura da Friboi)
# Outros prefixos do DUN-14 são menos frequentes e serão testados depois.
PREFIX_ORDER = [1, 2, 9, 3, 4, 5, 6, 7, 8]

def clean_text_comparison(text):
    """
    Remove acentos, converte para minúsculas e remove caracteres especiais
    para garantir que a comparação de strings seja justa e imune a formatações.
    """
    if not text:
        return ""
    text_normalized = unicodedata.normalize('NFKD', text)
    text_ascii = text_normalized.encode('ASCII', 'ignore').decode('utf-8')
    return text_ascii.strip().lower()

def extract_meaningful_tokens(text):
    """
    Tokeniza o texto em palavras chaves relevantes, descartando termos logísticos e stop words.
    """
    cleaned = clean_text_comparison(text)
    words = re.findall(r'\b\w{3,}\b', cleaned)
    
    stop_words = {
        'com', 'para', 'dos', 'das', 'uma', 'uns', 'caixa', 'unidades', 'unidade', 
        'peso', 'variado', 'kg', 'pacote', 'embalagem', 'congelado', 'resfriado', 
        'friboi', 'seara', 'maturatta', 'swift', 'reserva', 'fatiado', 'pedaco', 'peca'
    }
    return {w for w in words if w not in stop_words}

def calculate_gtin14_dv(digits13):
    """
    Calcula matematicamente o dígito verificador Módulo 10 para GTIN-14 (DUN-14).
    Pesos de esquerda para a direita (índices 0 a 12): 3, 1, 3, 1, 3, 1, 3, 1, 3, 1, 3, 1, 3.
    """
    if len(digits13) != 13 or not digits13.isdigit():
        raise ValueError("A base numérica para cálculo do DV do GTIN-14 deve conter exatamente 13 dígitos.")
    
    total = sum(int(digit) * (3 if i % 2 == 0 else 1) for i, digit in enumerate(digits13))
    remainder = total % 10
    return (10 - remainder) % 10

def extract_valid_duns_from_text(text, ean_13):
    """
    Varre o texto em busca de números de 14 dígitos e verifica se eles são
    DUN-14 matematicamente válidos baseados no EAN-13 fornecido.
    O EAN-13 deve ter 13 dígitos. O DUN-14 válido deve ter a estrutura:
    [prefixo_logistico_1_a_9][12_primeiros_digitos_do_ean_13][dígito_verificador_modulo10]
    """
    if len(ean_13) != 13 or not ean_13.isdigit():
        return set()
        
    base_ean = ean_13[:12]
    duns_found = set()
    
    # Encontra todos os números de 14 dígitos
    candidates = re.findall(r'\b\d{14}\b', text)
    
    for candidate in candidates:
        # O DUN-14 deve conter os 12 primeiros dígitos do EAN na posição do meio (índices 1 à 12)
        if candidate[1:13] == base_ean:
            prefix = int(candidate[0])
            if 1 <= prefix <= 9:
                # Verifica se o DV calculado bate com o do candidato (índice 13)
                try:
                    expected_dv = calculate_gtin14_dv(candidate[:13])
                    if int(candidate[13]) == expected_dv:
                        duns_found.add(candidate)
                except ValueError:
                    continue
                    
    return duns_found

def make_request_with_retry(url, headers, max_retries=3, initial_delay=5):
    """
    Realiza uma requisição HTTP GET com lógica de Wait & Retry.
    Trata erros de timeout, queda de conexão e status HTTP 429 ou 5xx.
    """
    retries = 0
    delay = initial_delay
    
    while retries < max_retries:
        try:
            # Alterna o User-Agent a cada tentativa para mitigar bloqueios
            headers['User-Agent'] = random.choice(USER_AGENTS)
            
            response = requests.get(url, headers=headers, timeout=12)
            
            if response.status_code == 429:
                print(f"\n  [!] Recebido status HTTP 429 (Too Many Requests). Aguardando {delay * 2}s (Cool Down)...")
                time.sleep(delay * 2)
                retries += 1
                delay *= 2
                continue
                
            if response.status_code in [500, 502, 503, 504]:
                print(f"\n  [!] Status HTTP {response.status_code} recebido. Retentando em {delay}s... (Tentativa {retries+1}/{max_retries})")
                time.sleep(delay)
                retries += 1
                delay *= 2  # Backoff exponencial
                continue
                
            return response
            
        except (requests.exceptions.RequestException, requests.exceptions.Timeout) as e:
            print(f"\n  [!] Conexão falhou/timeout: {e}. Retentando em {delay}s... (Tentativa {retries+1}/{max_retries})")
            time.sleep(delay)
            retries += 1
            delay *= 2
            continue
            
    return None

def validate_via_cosmos(dun, db_title, db_brand):
    """
    Valida o DUN-14 consultando a interface pública do Bluesoft Cosmos.
    """
    url = f"https://cosmos.bluesoft.com.br/produtos/{dun}"
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
        'Referer': 'https://cosmos.bluesoft.com.br/',
        'Upgrade-Insecure-Requests': '1',
        'Connection': 'keep-alive',
    }
    
    response = make_request_with_retry(url, headers)
    if not response:
        return False, "TIMEOUT_OR_CONNECTION_ERROR"
        
    if response.status_code == 403:
        return False, "CLOUDFLARE_BLOCKED"
        
    if response.status_code == 404:
        return False, "NOT_FOUND"
        
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 1. Extração do Título da página
        title_elem = soup.find('h1', id='product-name-header')
        if not title_elem:
            title_elem = soup.find('h1')
        api_title = title_elem.text.strip() if title_elem else ""
        
        # 2. Extração da Marca
        brand_elem = soup.find('span', itemprop='brand')
        if not brand_elem:
            brand_elem = soup.find('a', href=re.compile(r'/marcas/'))
        api_brand = brand_elem.text.strip() if brand_elem else ""
        
        # Se a marca no Cosmos estiver vazia mas achamos o título, podemos inferir do título
        if not api_brand and 'friboi' in clean_text_comparison(api_title):
            api_brand = "Friboi"
            
        # 3. Validação de Correspondência
        match = check_correspondence(db_title, db_brand, api_title, api_brand)
        if match:
            return True, {
                "source": "Cosmos API",
                "title": api_title,
                "brand": api_brand if api_brand else "N/A"
            }
            
    return False, "MISMATCH"

def validate_via_duckduckgo(dun, db_title, db_brand):
    """
    Valida o DUN-14 fazendo uma busca textual na versão HTML do DuckDuckGo.
    Motor de fallback de altíssima disponibilidade que não sofre com bloqueios do Cloudflare.
    """
    url = f"https://html.duckduckgo.com/html/?q={dun}"
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
    }
    
    response = make_request_with_retry(url, headers)
    if not response:
        return False, "TIMEOUT_OR_CONNECTION_ERROR"
        
    if response.status_code == 429:
        return False, "RATE_LIMITED"
        
    if response.status_code != 200:
        return False, "SEARCH_ERROR"
        
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Extrai o texto dos títulos e dos trechos de resultados
    titles = [t.text.strip() for t in soup.find_all('a', class_='result__a')]
    snippets = [s.text.strip() for s in soup.find_all('a', class_='result__snippet')]
    
    combined_text = " ".join(titles + snippets)
    combined_clean = clean_text_comparison(combined_text)
    
    # 1. Validação de Marca
    db_brand_clean = clean_text_comparison(db_brand)
    brand_match = db_brand_clean in combined_clean
    if not brand_match and 'friboi' in db_brand_clean:
        # Permite correlacionar Friboi com a empresa mãe JBS nos resultados
        brand_match = 'friboi' in combined_clean or 'jbs' in combined_clean
        
    if not brand_match:
        return False, "BRAND_MISMATCH"
        
    # 2. Validação das Palavras-Chave do Produto
    db_tokens = extract_meaningful_tokens(db_title)
    if not db_tokens:
        # Fallback caso o título original não tenha tokens válidos após filtro
        return True, {"source": "DuckDuckGo HTML (Brand Match Only)", "title": "N/A"}
        
    # Verifica se pelo menos uma palavra chave específica de corte/produto consta na busca do DDG
    word_match = any(w in combined_clean for w in db_tokens)
    if word_match:
        # Pega o melhor fragmento do snippet para fins de log
        matching_snippet = "N/A"
        for snip in snippets:
            if any(w in clean_text_comparison(snip) for w in db_tokens):
                matching_snippet = snip[:65] + "..."
                break
        return True, {
            "source": "DuckDuckGo Search",
            "title": matching_snippet,
            "brand": db_brand
        }
        
    return False, "TITLE_MISMATCH"

def validate_via_openfoodfacts(dun, db_title, db_brand):
    """
    Valida o DUN-14 consultando a base aberta do Open Food Facts.
    """
    url = f"https://br.openfoodfacts.org/api/v2/product/{dun}.json"
    headers = {
        'User-Agent': 'FriboiDUNFiller - Python Automation - Version 1.0 (Termux Environment)'
    }
    
    response = make_request_with_retry(url, headers)
    if not response or response.status_code != 200:
        return False, "API_ERROR"
        
    data = response.json()
    if data.get('status') == 1:
        product_data = data.get('product', {})
        api_title = product_data.get('product_name', '')
        api_brand = product_data.get('brands', '')
        
        match = check_correspondence(db_title, db_brand, api_title, api_brand)
        if match:
            return True, {
                "source": "Open Food Facts",
                "title": api_title,
                "brand": api_brand if api_brand else "N/A"
            }
            
    return False, "NOT_FOUND_OR_MISMATCH"

def check_correspondence(db_title, db_brand, api_title, api_brand):
    """
    Aplica a lógica de correspondência inteligente baseada em marca e tokens
    para atestar a veracidade de um código DUN-14 candidato.
    """
    # 1. Normalização e Validação de Marca
    db_brand_clean = clean_text_comparison(db_brand)
    api_brand_clean = clean_text_comparison(api_brand)
    api_title_clean = clean_text_comparison(api_title)
    
    brand_match = (
        db_brand_clean in api_brand_clean or 
        db_brand_clean in api_title_clean or
        (api_brand_clean and api_brand_clean in db_brand_clean)
    )
    
    if not brand_match and 'friboi' in db_brand_clean:
        # Se a marca cadastrada for Friboi, aceita se o título retornado contiver "friboi"
        brand_match = 'friboi' in api_title_clean or 'friboi' in api_brand_clean
        
    if not brand_match:
        return False
        
    # 2. Validação de Palavras-Chave de Produto
    db_tokens = extract_meaningful_tokens(db_title)
    api_tokens = extract_meaningful_tokens(api_title)
    
    if not db_tokens:
        # Se o título original não tiver tokens significativos, confia na marca
        return True
        
    intersection = db_tokens.intersection(api_tokens)
    # Se compartilharem pelo menos 1 palavra chave específica de corte (ex: "alcatra", "contra"), está confirmado!
    return len(intersection) >= 1

def try_find_dun_from_ean_page_cosmos(ean_13):
    """
    Tenta consultar a página do produto EAN-13 no Bluesoft Cosmos e extrair
    os DUN-14 das caixas de embarque exibidas no HTML da página do produto.
    Isso economiza requisições reduzindo de 9 para 1 por produto no Cosmos!
    """
    url = f"https://cosmos.bluesoft.com.br/produtos/{ean_13}"
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
        'Referer': 'https://cosmos.bluesoft.com.br/',
        'Upgrade-Insecure-Requests': '1',
    }
    
    response = make_request_with_retry(url, headers)
    if not response:
        return None, "TIMEOUT_OR_CONNECTION_ERROR"
        
    if response.status_code == 403:
        return None, "CLOUDFLARE_BLOCKED"
        
    if response.status_code == 404:
        return None, "NOT_FOUND"
        
    if response.status_code == 200:
        duns = extract_valid_duns_from_text(response.text, ean_13)
        if duns:
            # Retorna o primeiro DUN encontrado associado àquele EAN
            return list(duns)[0], "Cosmos Product Page"
            
    return None, "NO_DUNS_IN_HTML"

def try_find_dun_from_ean_search_ddg(ean_13):
    """
    Tenta buscar o EAN-13 no DuckDuckGo HTML e pescar menções a códigos DUN-14
    válidos contidos no texto de descrição dos snippets e títulos da busca.
    """
    url = f"https://html.duckduckgo.com/html/?q={ean_13}"
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
    }
    
    response = make_request_with_retry(url, headers)
    if not response:
        return None, "TIMEOUT_OR_CONNECTION_ERROR"
        
    if response.status_code == 429:
        return None, "RATE_LIMITED"
        
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, 'html.parser')
        titles = [t.text.strip() for t in soup.find_all('a', class_='result__a')]
        snippets = [s.text.strip() for s in soup.find_all('a', class_='result__snippet')]
        
        combined_text = " ".join(titles + snippets)
        duns = extract_valid_duns_from_text(combined_text, ean_13)
        if duns:
            return list(duns)[0], "DuckDuckGo EAN Search"
            
    return None, "NO_DUNS_IN_SEARCH"

def main():
    parser = argparse.ArgumentParser(description="fill_missing_duns: Preenche códigos DUN-14 no catálogo da Friboi.")
    parser.add_argument('--db', type=str, default='/root/projetos-scraping/scraping-friboi/friboi_catalogo.db', 
                        help='Caminho absoluto para o banco SQLite (default: /root/projetos-scraping/scraping-friboi/friboi_catalogo.db)')
    parser.add_argument('--delay', type=float, default=2.0, 
                        help='Intervalo de cortesia em segundos entre requisições de rede (default: 2.0)')
    parser.add_argument('--limit', type=int, default=None,
                        help='Número máximo de produtos a processar nesta rodada')
    args = parser.parse_args()
    
    db_path = args.db
    delay_time = args.delay
    limit = args.limit
    
    if not os.path.exists(db_path):
        print(f"[!] Banco de dados SQLite não encontrado no caminho: {db_path}")
        sys.exit(1)
        
    print(f"[*] Conectando ao banco de dados SQLite: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Seleciona SKUs com EAN-13 válido mas sem DUN-14
    query = """
    SELECT sku, title, ean, marca 
    FROM produtos 
    WHERE (dun IS NULL OR dun = '') 
      AND ean IS NOT NULL 
      AND ean != 'N/A' 
      AND ean != ''
    """
    
    cursor.execute(query)
    all_products = cursor.fetchall()
    
    # Filtra localmente os registros para garantir EAN-13 numérico limpo
    filtered_products = []
    for row in all_products:
        sku = row[0].strip("'\"")
        title = row[1].strip("'\"")
        ean = row[2].strip("'\"")
        marca = row[3].strip("'\"")
        
        if len(ean) == 13 and ean.isdigit():
            filtered_products.append((sku, title, ean, marca))
            
    total_found = len(filtered_products)
    print(f"[*] Total de produtos sem DUN-14 e com EAN-13 de 13 dígitos: {total_found}")
    
    if total_found == 0:
        print("[*] Nenhum produto pendente de preenchimento de DUN-14. Processo encerrado.")
        conn.close()
        sys.exit(0)
        
    if limit:
        filtered_products = filtered_products[:limit]
        print(f"[*] Limitando execução para os primeiros {len(filtered_products)} produtos.")
        
    processed_count = 0
    updated_count = 0
    
    # Flags de controle dos motores
    cosmos_blocked = False
    ddg_rate_limited = False
    ddg_cool_down_until = 0
    
    print("\n" + "="*75)
    print("Iniciando a busca e validação inteligente de códigos DUN-14...")
    print("="*75 + "\n")
    
    for sku, title, ean, marca in filtered_products:
        processed_count += 1
        print(f"[{processed_count}/{len(filtered_products)}] SKU: {sku} | EAN: {ean} | '{title[:45]}...' | Marca: {marca}")
        
        dun_found = None
        source_found = None
        
        # -------------------------------------------------------------
        # ESTRATÉGIA 1: Buscar a página do EAN-13 no Cosmos (Mais rápida e elegante)
        # -------------------------------------------------------------
        if not cosmos_blocked:
            dun, reason = try_find_dun_from_ean_page_cosmos(ean)
            if dun:
                dun_found = dun
                source_found = reason
            elif reason == "CLOUDFLARE_BLOCKED":
                print("  [!] Bluesoft Cosmos retornou status 403 (Cloudflare). Rota desabilitada temporariamente nesta execução.")
                cosmos_blocked = True
                
        # -------------------------------------------------------------
        # ESTRATÉGIA 2: Fallback - Pesquisa do EAN-13 no DuckDuckGo (Pescar o DUN-14 de caixas no HTML)
        # -------------------------------------------------------------
        if not dun_found and not ddg_rate_limited:
            # Respeita o cool down se houver
            if time.time() > ddg_cool_down_until:
                dun, reason = try_find_dun_from_ean_search_ddg(ean)
                if dun:
                    dun_found = dun
                    source_found = reason
                elif reason == "RATE_LIMITED":
                    print("  [!] DuckDuckGo ativou Rate Limit (429). Iniciando Cool Down de 20s...")
                    ddg_cool_down_until = time.time() + 20
                    # Espera um pouco a mais
                    time.sleep(10)
            else:
                print("  [*] Ignorando DuckDuckGo temporariamente (Modo Cool Down ativo)...")
                
        # -------------------------------------------------------------
        # ESTRATÉGIA 3: Fallback Final - Busca ativa gerando as 9 variações do EAN
        # -------------------------------------------------------------
        if not dun_found:
            # Caso a página do EAN-13 não mencione o DUN-14, testamos as variações uma por uma
            base_digits = ean[:12]
            
            for prefix in PREFIX_ORDER:
                candidate13 = str(prefix) + base_digits
                dv = calculate_gtin14_dv(candidate13)
                candidate_dun = candidate13 + str(dv)
                
                # Validação 3.1: Cosmos (se não estiver bloqueado)
                if not cosmos_blocked:
                    success, res_info = validate_via_cosmos(candidate_dun, title, marca)
                    if success:
                        dun_found = candidate_dun
                        source_found = res_info["source"]
                        break
                    elif res_info == "CLOUDFLARE_BLOCKED":
                        cosmos_blocked = True
                        
                # Validação 3.2: Open Food Facts
                success_off, res_info_off = validate_via_openfoodfacts(candidate_dun, title, marca)
                if success_off:
                    dun_found = candidate_dun
                    source_found = res_info_off["source"]
                    break
                    
                # Validação 3.3: DuckDuckGo Search (se não estiver com rate limit)
                if not ddg_rate_limited and time.time() > ddg_cool_down_until:
                    success_ddg, res_info_ddg = validate_via_duckduckgo(candidate_dun, title, marca)
                    if success_ddg:
                        dun_found = candidate_dun
                        source_found = res_info_ddg["source"]
                        break
                    elif res_info_ddg == "RATE_LIMITED":
                        print("  [!] DuckDuckGo retornou 429 nas variações. Entrando em Cool Down...")
                        ddg_cool_down_until = time.time() + 20
                        time.sleep(10)
                        
                time.sleep(delay_time)
                
        if dun_found:
            # Preenchimento e persistência imediata
            cursor.execute("""
                UPDATE produtos 
                SET dun = ? 
                WHERE sku = ?
            """, (dun_found, sku))
            
            # COMMIT imediato de segurança
            conn.commit()
            updated_count += 1
            print(f"  [OK] DUN-14 '{dun_found}' confirmado e salvo! (Origem: {source_found})")
        else:
            print(f"  [!] DUN-14 não localizado para EAN: {ean}")
            
        print("-" * 55)
        time.sleep(delay_time)
        
    conn.close()
    
    print("\n" + "="*75)
    print("Processamento concluído!")
    print(f"Total de produtos analisados: {processed_count}")
    print(f"DUN-14 preenchidos e salvos com sucesso: {updated_count}")
    print("="*75 + "\n")

if __name__ == '__main__':
    main()

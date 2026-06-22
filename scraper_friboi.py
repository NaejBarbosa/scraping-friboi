#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Scraper Friboi B2B - Arquitetura de Recursos Limitados (Termux/Android)
Autor: Engenheiro de Dados Sênior
Descrição: Script de web scraping resiliente para extrair o catálogo de produtos
           comerciais da Friboi a partir do seu portal B2B, gravando os dados em SQLite.
"""

import os
import re
import sys
import time
import json
import sqlite3
import requests
from bs4 import BeautifulSoup

# Configurações gerais
DB_NAME = "friboi_catalogo.db"
SITEMAP_URL = "https://www.friboionline.com.br/productSitemap.xml"
API_PRODUCT_TEMPLATE = "https://www.friboionline.com.br/ccstoreui/v1/products/{sku}"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept-Encoding': 'gzip, deflate, br'
}

def clean_text(text):
    """
    Remove quebras de linha, tabulações e múltiplos espaços do texto.
    """
    if not text:
        return ""
    # Remove HTML tags residuais caso existam
    text = re.sub(r'<[^>]*>', ' ', text)
    # Substitui múltiplos espaços e quebras de linha por um único espaço
    cleaned = re.sub(r'\s+', ' ', text)
    return cleaned.strip()

def init_db(db_path):
    """
    Inicializa o banco de dados SQLite e cria as tabelas necessárias.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Tabela de produtos (SKU como chave primária)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS produtos (
            sku TEXT PRIMARY KEY,
            title TEXT,
            descrFiscal TEXT,
            ean TEXT,
            dun TEXT,
            marca TEXT,
            classe TEXT,
            conservacao TEXT,
            pesoLiquido TEXT,
            pesoBruto TEXT,
            url TEXT,
            image_url TEXT
        )
    """)
    
    # Tabela auxiliar para fila de URLs
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fila_urls (
            url TEXT PRIMARY KEY,
            status_processamento TEXT DEFAULT 'pendente'
        )
    """)
    
    # Criar um índice para otimizar a busca por status_processamento
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_status ON fila_urls (status_processamento)")
    
    conn.commit()
    conn.close()
    print(f"[*] Banco de dados SQLite inicializado com sucesso: {db_path}")

def safe_request(url, max_retries=5, retry_delay=15):
    """
    Realiza uma requisição HTTP GET resiliente com lógica de 'Wait & Retry'.
    Detecta queda de conexão, timeouts e erros 5xx do servidor, aguardando 15s antes de retentar.
    """
    retries = 0
    while retries < max_retries:
        try:
            response = requests.get(url, headers=HEADERS, timeout=20)
            
            # Trata erros temporários de servidor (HTTP 500, 502, 503, 504)
            if response.status_code in [500, 502, 503, 504]:
                print(f"\n[!] Erro de Servidor ({response.status_code}) ao acessar: {url}")
                print(f"    Retentando em {retry_delay}s... (Tentativa {retries + 1}/{max_retries})")
                retries += 1
                time.sleep(retry_delay)
                continue
                
            return response
            
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            print(f"\n[!] Falha de Conexão/Timeout ao acessar: {url}")
            print(f"    Detalhe: {str(e)}")
            print(f"    Aguardando sinal de internet ({retry_delay}s) para retentar... (Tentativa {retries + 1}/{max_retries})")
            retries += 1
            time.sleep(retry_delay)
            
    # Se estourar todas as retentativas, lança exceção para tratamento na fila
    raise requests.exceptions.RequestException(f"Falha persistente após {max_retries} tentativas para {url}")

def populate_queue(db_path):
    """
    Lê o sitemap de produtos da Friboi e popula a fila de URLs caso esteja vazia.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Verifica se já existem URLs cadastradas
    cursor.execute("SELECT COUNT(*) FROM fila_urls")
    total_fila = cursor.fetchone()[0]
    
    if total_fila > 0:
        print(f"[*] Fila já existente com {total_fila} registros. Retomando estado anterior...")
        conn.close()
        return
        
    print(f"[*] Fila de URLs vazia. Baixando sitemap XML de produtos...")
    try:
        response = safe_request(SITEMAP_URL)
        if response.status_code != 200:
            print(f"[!] Erro ao baixar sitemap: HTTP {response.status_code}")
            sys.exit(1)
            
        soup = BeautifulSoup(response.content, 'xml')
        locs = [loc.text.strip() for loc in soup.find_all('loc')]
        
        # Filtra apenas URLs legítimas de produto (evitando imagens e arquivos)
        # Formato correto: https://www.friboionline.com.br/product/nome-do-produto/sku
        product_urls = []
        for url in locs:
            if '/product/' in url and not any(x in url for x in ['/file/', '/images/', '.jpg', '.jpeg', '.png']):
                product_urls.append(url)
                
        print(f"[*] Total de {len(product_urls)} URLs de produtos encontradas no sitemap.")
        
        # Insere na fila de URLs com status 'pendente'
        # Utiliza INSERT OR IGNORE para evitar duplicidades
        cursor.executemany(
            "INSERT OR IGNORE INTO fila_urls (url, status_processamento) VALUES (?, 'pendente')",
            [(url,) for url in product_urls]
        )
        conn.commit()
        
        cursor.execute("SELECT COUNT(*) FROM fila_urls")
        total_inserido = cursor.fetchone()[0]
        print(f"[*] {total_inserido} URLs salvas na fila para processamento.")
        
    except Exception as e:
        print(f"[!] Falha crítica ao processar sitemap: {str(e)}")
        sys.exit(1)
    finally:
        conn.close()

def infer_classe(title, descr_fiscal, category_path):
    """
    Heurística para inferir a classe do produto com base em palavras-chave e caminho de categoria.
    """
    text = f"{title} {descr_fiscal} {category_path}".lower()
    
    if any(w in text for w in ['bovino', 'boi', 'novilha', 'angus', 'maturatta', 'friboi', 'alcatra', 'picanha', 'maminha', 'contrafilé', 'fraldinha', 'acém', 'costela', 'cupim', 'musculo', 'músculo', 'paleta']):
        return "Bovinos"
    elif any(w in text for w in ['frango', 'ave', 'aves', 'sobrecoxa', 'peito de frango', 'asa', 'sassami', 'coração de frango', 'peru', 'chester', 'seara']):
        return "Aves"
    elif any(w in text for w in ['suino', 'suíno', 'porco', 'pork', 'pernil', 'lombo', 'panceta', 'copa lombo', 'costela suína']):
        return "Suínos"
    elif any(w in text for w in ['peixe', 'pescado', 'salmão', 'tilápia', 'camarão', 'bacalhau']):
        return "Pescados"
    elif any(w in text for w in ['linguiça', 'salsicha', 'presunto', 'mortadela', 'bacon', 'salame', 'embutido', 'defrumado']):
        return "Embutidos e Processados"
    return "Outros"

def infer_conservacao(title, descr_fiscal, temp_api):
    """
    Heurística para inferir a conservação do produto.
    """
    if temp_api:
        temp_clean = temp_api.upper()
        if "RESFRIADO" in temp_clean or "RESFRIADA" in temp_clean:
            return "Resfriado"
        elif "CONGELADO" in temp_clean or "CONGELADA" in temp_clean:
            return "Congelado"
            
    text = f"{title} {descr_fiscal}".lower()
    if any(w in text for w in ['resfriado', 'resfriada', 'chilled', 'fresco', 'in natura resfriado']):
        return "Resfriado"
    elif any(w in text for w in ['congelado', 'congelada', 'frozen', 'congelados']):
        return "Congelado"
    elif any(w in text for w in ['temperatura ambiente', 'seco', 'curado', 'salgado']):
        return "Temperatura Ambiente"
    return "Resfriado"  # Padrão para produtos cárneos da Friboi se não especificado

def extract_weights(title, descr_fiscal, weight_api, peso_vol_api):
    """
    Heurística baseada em Regex para extrair Peso Líquido e Peso Bruto.
    """
    # Procura padrões de peso como 1.5kg, 350g, 6,8kg, 900 g, 20kg no título e descrição
    weight_regex = r'\b(\d+(?:[.,]\d+)?)\s*(kg|g|quilos|quilo|gramas)\b'
    
    peso_liq = ""
    peso_bruto = ""
    
    # 1. Tenta achar no título
    match_title = re.search(weight_regex, title, re.IGNORECASE)
    if match_title:
        val, unit = match_title.groups()
        val = val.replace(',', '.')
        peso_liq = f"{val} {unit.lower()}"
        
    # 2. Tenta na descrição se não achar no título
    if not peso_liq and descr_fiscal:
        match_desc = re.search(weight_regex, descr_fiscal, re.IGNORECASE)
        if match_desc:
            val, unit = match_desc.groups()
            val = val.replace(',', '.')
            peso_liq = f"{val} {unit.lower()}"
            
    # 3. Fallback no weight da API
    if not peso_liq and weight_api:
        peso_liq = f"{weight_api} kg"
        
    # Peso Bruto: Em produtos B2B in natura, frequentemente refere-se ao peso médio da caixa (volume)
    if peso_vol_api:
        peso_bruto = f"{peso_vol_api} kg (Caixa)"
    elif peso_liq:
        # Se não tiver peso do volume, define o bruto igual ao líquido
        peso_bruto = peso_liq
    else:
        peso_liq = "Variável"
        peso_bruto = "Variável"
        
    return clean_text(peso_liq), clean_text(peso_bruto)

def extract_barcodes(html_content, api_ean):
    """
    Varre o HTML e dados estruturados usando Regex buscando padrões de EAN-13 e DUN-14.
    Valida e garante que EAN retorne exatamente 13 dígitos e DUN exatamente 14 dígitos.
    """
    ean = ""
    dun = ""
    
    # 1. Processamento do EAN a partir da API (Fonte primária estruturada)
    if api_ean:
        api_ean = str(api_ean).strip()
        # Se tem 12 dígitos, preenche com 0 à esquerda para formar o padrão EAN-13
        if len(api_ean) == 12 and api_ean.isdigit():
            ean = "0" + api_ean
        elif len(api_ean) == 13 and api_ean.isdigit():
            ean = api_ean
            
    # 2. Varredura via Regex no HTML caso o EAN não tenha sido obtido estruturado
    if not ean:
        # Regex para EAN-13 (13 dígitos) e EAN-12 (12 dígitos)
        ean_matches_13 = re.findall(r'\b\d{13}\b', html_content)
        if ean_matches_13:
            ean = ean_matches_13[0]
        else:
            ean_matches_12 = re.findall(r'\b\d{12}\b', html_content)
            if ean_matches_12:
                ean = "0" + ean_matches_12[0]
                
    # 3. Varredura de DUN-14 (14 dígitos, código de caixa de distribuição) no HTML/Textos
    dun_matches_14 = re.findall(r'\b\d{14}\b', html_content)
    if dun_matches_14:
        dun = dun_matches_14[0]
        
    # Validação rígida: EAN deve ter exatamente 13 dígitos e DUN exatamente 14 dígitos numéricos
    if not (len(ean) == 13 and ean.isdigit()):
        ean = ""
    if not (len(dun) == 14 and dun.isdigit()):
        dun = ""
        
    return ean, dun

def process_product(url, html_content):
    """
    Parseia a página do produto usando BeautifulSoup e Regex.
    Consulta a API interna do produto como enriquecimento de dados estruturados.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Extrai o SKU da URL (último conjunto de dígitos)
    sku = url.strip('/').split('/')[-1]
    if not sku or not sku.isdigit():
        # Fallback via regex no final do link
        match = re.search(r'/(\d+)/?$', url)
        sku = match.group(1) if match else None
        
    if not sku:
        raise ValueError("Não foi possível extrair o SKU da URL")
        
    # Inicializa variáveis
    title = ""
    descr_fiscal = ""
    brand = ""
    api_ean = ""
    temp_api = ""
    cat_path = ""
    weight_api = None
    peso_vol_api = None
    image_url = ""
    
    # 1. Tenta extrair dados iniciais do JSON-LD na página do produto (BeautifulSoup)
    script_ld = soup.find('script', id='CC-schema-org-server', type='application/ld+json')
    if script_ld:
        try:
            ld_data = json.loads(script_ld.string)
            title = ld_data.get('name', '')
            brand = ld_data.get('brand', '')
            if isinstance(brand, dict):
                brand = brand.get('name', '')
        except Exception:
            pass
            
    if not title:
        title_tag = soup.find('title')
        if title_tag:
            title = title_tag.text
            
    # 2. Faz consulta na API interna do produto (Enriquecimento corporativo)
    # A API fornece metadados cruciais impossíveis de obter no HTML estático do SPA.
    api_url = API_PRODUCT_TEMPLATE.format(sku=sku)
    try:
        api_res = safe_request(api_url)
        if api_res.status_code == 200:
            api_data = api_res.json()
            
            # Sobrescreve/enriquece os dados mestre
            title = api_data.get('displayName', title)
            brand = api_data.get('brand', api_data.get('x_MARCA', brand))
            descr_fiscal = api_data.get('longDescription', api_data.get('description', ''))
            api_ean = api_data.get('x_cCdEAN', '')
            temp_api = api_data.get('x_TEMPERATURA', '')
            cat_path = api_data.get('parentCategoryIdPath', '')
            weight_api = api_data.get('weight')
            peso_vol_api = api_data.get('x_nPesoMedioVolume')
            api_image = api_data.get('primaryFullImageURL') or api_data.get('primaryMediumImageURL') or api_data.get('primaryLargeImageURL')
            if api_image:
                if api_image.startswith('/'):
                    image_url = "https://www.friboionline.com.br" + api_image
                else:
                    image_url = api_image
    except Exception as e:
        # Prossegue com os dados capturados via HTML se a API falhar
        print(f"\n[!] Aviso: Não foi possível enriquecer o SKU {sku} via API: {str(e)}")
        
    # Limpeza dos textos
    title = clean_text(title)
    descr_fiscal = clean_text(descr_fiscal)
    brand = clean_text(brand)
    
    # Se o título contiver o SKU no final (ex: "Produto (1005)"), removemos para limpar o título
    title = re.sub(r'\s*\(\d+\)\s*$', '', title)
    
    # 3. Varredura de códigos de barra (EAN/DUN) com Regex
    ean, dun = extract_barcodes(html_content + " " + descr_fiscal, api_ean)
    
    # 4. Inferências heurísticas de Classe e Conservação
    classe = infer_classe(title, descr_fiscal, cat_path)
    conservacao = infer_conservacao(title, descr_fiscal, temp_api)
    
    # 5. Inferência de pesos líquido e bruto
    peso_liq, peso_bruto = extract_weights(title, descr_fiscal, weight_api, peso_vol_api)
    
    return {
        'sku': sku,
        'title': title,
        'descrFiscal': descr_fiscal,
        'ean': ean,
        'dun': dun,
        'marca': brand if brand else 'Friboi',
        'classe': classe,
        'conservacao': conservacao,
        'pesoLiquido': peso_liq,
        'pesoBruto': peso_bruto,
        'url': url,
        'image_url': image_url
    }

def main():
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), DB_NAME)
    
    print("="*70)
    print("      INICIANDO WEB SCRAPER - CATÁLOGO B2B FRIBOI")
    print("="*70)
    
    # 1. Inicializa o Banco de Dados
    init_db(db_path)
    
    # 2. Popula a Fila de URLs
    populate_queue(db_path)
    
    # 3. Execução do processamento (Resume State)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Obtém estatísticas iniciais da fila
    cursor.execute("SELECT COUNT(*) FROM fila_urls")
    total_links = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM fila_urls WHERE status_processamento = 'processado'")
    processados_init = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM fila_urls WHERE status_processamento = 'invalido'")
    invalidos_init = cursor.fetchone()[0]
    
    print(f"[*] Estatísticas da Fila:")
    print(f"    - Total de links: {total_links}")
    print(f"    - Processados anteriormente (Resume State): {processados_init}")
    print(f"    - Inválidos anteriormente: {invalidos_init}")
    print(f"    - Pendentes: {total_links - processados_init - invalidos_init}")
    print("-"*70)
    
    # Loop de processamento
    while True:
        # Busca a próxima URL pendente
        cursor.execute("""
            SELECT url FROM fila_urls 
            WHERE status_processamento = 'pendente' 
            LIMIT 1
        """)
        row = cursor.fetchone()
        
        # Se não houver mais URLs pendentes, finaliza a execução
        if not row:
            print("\n[+] Execução concluída! Todos os links pendentes foram processados.")
            break
            
        url = row[0]
        
        # Recalcula contagens para exibir no log de progresso em tempo real
        cursor.execute("SELECT COUNT(*) FROM fila_urls WHERE status_processamento = 'processado'")
        processados = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM fila_urls WHERE status_processamento = 'invalido'")
        invalidos = cursor.fetchone()[0]
        
        pendentes = total_links - processados - invalidos
        progresso_pct = (processados / total_links) * 100 if total_links > 0 else 0
        
        # Exibe log de progresso no terminal
        sys.stdout.write(f"\rProgresso: [{processados}/{total_links}] ({progresso_pct:.2f}%) | Pendentes: {pendentes} | Processando...")
        sys.stdout.flush()
        
        try:
            # Baixa a página do produto (Resiliente)
            response = safe_request(url)
            
            if response.status_code == 404:
                # Link quebrado, marca como inválido na fila
                cursor.execute("""
                    UPDATE fila_urls 
                    SET status_processamento = 'invalido' 
                    WHERE url = ?
                """, (url,))
                conn.commit()  # Commit imediato
                print(f"\n[!] Link inválido (404) ignorado: {url}")
                continue
                
            if response.status_code != 200:
                # Outros erros que não impedem a fila, mas devem ser registrados
                print(f"\n[!] Erro HTTP {response.status_code} ao baixar produto: {url}")
                continue
                
            # Parseia e extrai dados do produto
            produto_dados = process_product(url, response.text)
            
            # Salva os dados na tabela de produtos utilizando INSERT OR IGNORE para evitar duplicidades
            cursor.execute("""
                INSERT OR IGNORE INTO produtos (
                    sku, title, descrFiscal, ean, dun, marca, classe, conservacao, pesoLiquido, pesoBruto, url, image_url
                ) VALUES (
                    :sku, :title, :descrFiscal, :ean, :dun, :marca, :classe, :conservacao, :pesoLiquido, :pesoBruto, :url, :image_url
                )
            """, produto_dados)
            
            # Atualiza o status do processamento na fila
            cursor.execute("""
                UPDATE fila_urls 
                SET status_processamento = 'processado' 
                WHERE url = ?
            """, (url,))
            
            # REALIZA O COMMIT DA TRANSAÇÃO IMEDIATAMENTE (Atomicidade na Gravação)
            conn.commit()
            
            # Log de depuração detalhado do item processado
            print(f"\n[OK] SKU: {produto_dados['sku']} | EAN: {produto_dados['ean'] or 'N/A'} | DUN: {produto_dados['dun'] or 'N/A'} | Marca: {produto_dados['marca']} | Título: {produto_dados['title'][:45]}...")
            
        except Exception as e:
            # Em caso de qualquer outra falha ao processar o item individual
            print(f"\n[!] Falha ao processar a URL {url}: {str(e)}")
            # Marca como inválido para não travar a fila em falhas estruturais permanentes do link
            cursor.execute("""
                UPDATE fila_urls 
                SET status_processamento = 'invalido' 
                WHERE url = ?
            """, (url,))
            conn.commit()
            
        # Pequeno delay de cortesia entre requisições para evitar rate limit
        time.sleep(0.5)
        
    conn.close()
    print("="*70)
    print("      SCRAPER FINALIZADO COM SUCESSO!")
    print("="*70)

if __name__ == "__main__":
    main()

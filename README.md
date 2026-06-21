# Scraper de Catálogo Friboi B2B 🚀

Um robô de extração e processamento resiliente projetado para mapear e extrair o catálogo completo de produtos do portal B2B **Friboi Online**. O projeto foi estruturado com foco em estabilidade para execução em recursos limitados (como dispositivos móveis via Android/Termux), persistindo dados em **SQLite** com suporte nativo a retomada de estado (*Resume State*) e exportação automatizada para planilhas nativas do **Excel (`.xlsx`)** sem quebras de acentuação.

---

## 🌟 Funcionalidades e Diferenciais

* **Sitemap Crawling automático**: Mapeia todas as URLs válidas de produtos a partir do arquivo XML do sitemap corporativo.
* **Fila Dinâmica com Controle de Estado (Resume State)**: Utiliza banco de dados SQLite para gerenciar a fila. Se a execução for interrompida, ela é retomada exatamente do ponto em que parou, evitando chamadas de rede redundantes.
* **Enriquecimento via API Privada**: Localiza dados mestre do produto que não estão expostos no HTML estático do SPA consultando endpoints internos de API da plataforma.
* **Robô Resiliente (Wait & Retry)**: Arquitetura preparada para variações de rede do dispositivo. Em caso de timeout ou erro 5xx no servidor, o script aguarda um intervalo de cortesia (15s) e executa tentativas automáticas antes de descartar a URL.
* **Heurísticas e Normalização de Dados**:
  * Regex para validação rígida de códigos **EAN-13** (consumidor) e **DUN-14** (distribuição/caixa).
  * Inferência de classes de produto (Bovinos, Aves, Suínos, Pescados, Embutidos e Processados, Outros).
  * Extração e inferência de tipo de conservação (Congelado, Resfriado, Temperatura Ambiente) e pesos (líquido e bruto).
* **Exportação Nativa para Excel (`.xlsx`)**: Geração direta e limpa dos dados para formato binário legítimo utilizando `openpyxl`. Corrige o problema clássico de visualizadores de planilhas do celular que corrompem caracteres acentuados (`ç`, `ã`, `é`) em formatos CSV ou HTML.

---

## 📁 Estrutura do Projeto

* `scraper_friboi.py`: Script principal contendo o robô extrator, parser HTML e lógica de persistência.
* `export_xlsx.py`: Script utilitário para exportar o catálogo completo e a lista de duplicidades de EAN para a pasta de downloads do celular.
* `.gitignore`: Configuração para impedir o versionamento de arquivos de log temporários, bancos de dados locais e planilhas geradas.

---

## 🛠️ Configuração e Instalação

### Pré-requisitos
Certifique-se de possuir o **Python 3** instalado em sua máquina ou ambiente Termux.

### Instalação de Dependências
Para instalar as bibliotecas de processamento e exportação de planilhas, execute:

```bash
# Instalação das bibliotecas necessárias
pip3 install requests beautifulsoup4 openpyxl lxml
```

*(Caso utilize o Termux no Android, certifique-se de executar a instalação de dependências sob o ambiente correto de Python do Termux, usando `/data/data/com.termux/files/usr/bin/pip3` se necessário)*.

---

## 🚀 Como Utilizar

### 1. Iniciar o Scraper
Para rodar o processo de scraping em segundo plano (background) e salvar a saída em arquivo de log:

```bash
nohup python3 scraper_friboi.py > scraper.log 2>&1 &
echo $! > scraper.pid
```

### 2. Acompanhar a Execução
Você pode monitorar o progresso em tempo real inspecionando o arquivo de logs criado:

```bash
tail -f scraper.log
```

### 3. Exportar os Resultados para Excel
Para gerar as planilhas finais do catálogo completo de produtos e das duplicidades identificadas, execute:

```bash
python3 export_xlsx.py
```

Os arquivos serão gravados diretamente na pasta de downloads do seu dispositivo (`/sdcard/Download/`):
* `friboi_produtos_final.xlsx`: Catálogo geral com todos os dados estruturados.
* `friboi_duplicidades_final.xlsx`: Lista de SKUs concorrentes que compartilham o mesmo código EAN de consumo.

---

## 🗄️ Modelo do Banco de Dados (SQLite)

O banco de dados local `friboi_catalogo.db` é composto por duas tabelas principais:

### 1. Tabela `produtos`
Guarda as fichas cadastrais normalizadas de cada item:
* `sku` (TEXT, PRIMARY KEY): Código de identificação exclusivo da distribuidora.
* `title` (TEXT): Título/Nome do produto limpo.
* `descrFiscal` (TEXT): Descrição longa ou descrição fiscal interna.
* `ean` (TEXT): Código de barras do consumidor (13 dígitos).
* `dun` (TEXT): Código de barras da caixa de distribuição (14 dígitos).
* `marca` (TEXT): Marca fabricante (Friboi, Maturatta, Seara, Grano, etc.).
* `classe` (TEXT): Categoria inferida do item.
* `conservacao` (TEXT): Estado térmico de conservação.
* `pesoLiquido` (TEXT): Peso unitário de venda.
* `pesoBruto` (TEXT): Peso do volume total ou caixa de transporte.
* `url` (TEXT): Link de origem do produto.

### 2. Tabela `fila_urls`
Controla a fila de requisições:
* `url` (TEXT, PRIMARY KEY): Link de destino.
* `status_processamento` (TEXT): Estado do link (`pendente`, `processado`, `invalido`).

---

## 🔎 Análise de Duplicidades (EAN vs SKU)

Durante a consolidação dos dados, identificou-se que a coluna `sku` (chave primária) possui registros únicos, mas a base de dados corporativa possui **37 códigos EAN repetidos** que apontam para múltiplos SKUs diferentes.
Essas ocorrências podem representar:
1. Variações mínimas de embalagem ou peso que compartilham a mesma etiqueta de código de barras de consumo.
2. Cadastros duplicados na plataforma B2B de origem que foram herdados durante a extração.

A lista detalhada dessas ocorrências pode ser analisada diretamente na planilha `friboi_duplicidades_final.xlsx` gerada após a exportação.

#!/usr/bin/env node
// process_images.js
// Script para download, redimensionamento e conversão de imagens em lote no Termux/Node.js

const fs = require('fs');
const path = require('path');
const axios = require('axios');
const sharp = require('sharp');

// Configurações
const DATA_FILE = path.join(__dirname, 'dados_produtos.json');
const OUTPUT_DIR = path.join(__dirname, 'imagens_preparadas');
const CONCURRENCY_LIMIT = 5; // Limite de concorrência para poupar recursos do Termux
const TIMEOUT_MS = 15000;    // Timeout de 15s para requisições de imagem

// Cria o diretório de saída caso não exista
if (!fs.existsSync(OUTPUT_DIR)) {
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });
}

// Verifica se o arquivo de dados existe
if (!fs.existsSync(DATA_FILE)) {
  console.error(`[!] Erro: Arquivo de dados de produtos não encontrado em: ${DATA_FILE}`);
  process.exit(1);
}

// Carrega os dados dos produtos
const produtos = require(DATA_FILE);
console.log(`[*] Carregados ${produtos.length} produtos para processamento de imagens.`);
console.log(`[*] Imagens tratadas serão salvas em: ${OUTPUT_DIR}\n`);

/**
 * Realiza o download de uma imagem da internet e a processa utilizando o Sharp
 */
async function processarImagem(item, indice, total) {
  const nomeArquivo = `${item.barcode}.webp`;
  const caminhoDestino = path.join(OUTPUT_DIR, nomeArquivo);

  // Skip se o arquivo já existir (suporta retomada em caso de interrupção)
  if (fs.existsSync(caminhoDestino)) {
    console.log(`[${indice}/${total}] SKU: ${item.sku} | Código: ${item.barcode} | Já existe localmente. Pulando...`);
    return;
  }

  try {
    // 1. Download da imagem como ArrayBuffer (Buffer de memória)
    const response = await axios.get(item.image_url, {
      responseType: 'arraybuffer',
      timeout: TIMEOUT_MS,
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
        'Accept': 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8'
      }
    });

    const buffer = Buffer.from(response.data);

    // 2. Processamento da imagem com Sharp:
    //    - Redimensiona largura para max de 400px (mantendo proporção e sem ampliar imagens menores)
    //    - Converte para .webp com qualidade de 80%
    await sharp(buffer)
      .resize({
        width: 400,
        fit: 'inside',
        withoutEnlargement: true // Não amplia imagens menores que 400px para não distorcer
      })
      .webp({ quality: 80 })
      .toFile(caminhoDestino);

    console.log(`[${indice}/${total}] SKU: ${item.sku} | Código: ${item.barcode} | Imagem processada e salva com sucesso.`);
  } catch (error) {
    let msgErro = error.message;
    if (error.response) {
      msgErro = `HTTP ${error.response.status}`;
    } else if (error.code === 'ECONNABORTED') {
      msgErro = 'Timeout de conexão';
    }
    console.error(`\x1b[31m[!] Erro no código ${item.barcode} (SKU: ${item.sku}): ${msgErro}\x1b[0m`);
  }
}

/**
 * Gerenciador de concorrência assíncrona baseada em fila de trabalhadores (workers)
 */
async function executarFila() {
  let itemAtual = 0;
  const total = produtos.length;
  const tempoInicio = Date.now();

  async function trabalhador() {
    while (itemAtual < total) {
      const indice = itemAtual++;
      if (indice >= total) break;
      await processarImagem(produtos[indice], indice + 1, total);
    }
  }

  // Inicializa o número configurado de workers concorrentes
  const trabalhadores = Array.from({ length: CONCURRENCY_LIMIT }, trabalhador);
  
  // Aguarda todos os workers terminarem o processamento da fila inteira
  await Promise.all(trabalhadores);

  const tempoTotalMin = ((Date.now() - tempoInicio) / 1000 / 60).toFixed(2);
  console.log(`\n=============================================================`);
  console.log(`[*] Processamento de lote finalizado!`);
  console.log(`[*] Tempo total gasto: ${tempoTotalMin} minutos.`);
  console.log(`[*] Veja os ficheiros em: ${OUTPUT_DIR}`);
  console.log(`=============================================================\n`);
}

// Inicia a execução do pipeline
executarFila().catch(err => {
  console.error('[!] Falha crítica no processador:', err);
});

# ConforME - Instruções para Agentes de IA

## 🎯 Objetivo do Projeto
Automatizar avaliação de compliance de peças de marketing usando IA (Google Gemini).
O sistema analisa textos, imagens, PDFs e outros formatos, comparando com regras de compliance.

---

## 📁 Arquitetura (3 Scripts)

| Script | Responsabilidade |
|--------|------------------|
| `captura_arquivos.py` | Varredura de pastas, cópia de arquivos, hash SHA256 |
| `avaliacao_ia.py` | Envio para Gemini, parsing de resposta estruturada |
| `exportacao.py` | Geração de Excel (independente + master cumulativo) |

---

## ⚠️ Regras Obrigatórias

### Leitura de Arquivos
- **NÃO usar** bibliotecas de parsing (docx, pdfplumber, openpyxl para leitura)
- Arquivos de texto → enviados como string
- Qualquer outro formato → enviados como **bytes** para a IA interpretar

### Regras de Compliance
- Ficam em `Regras/*.txt` como arquivos externos
- O prompt da IA está em `Regras/InstrucaoIA.txt`
- **NUNCA** hardcode regras no código Python
- O placeholder `{{REGRAS_DINAMICAS}}` é substituído automaticamente

### Padrões de Código
- Todas as funções devem ter **docstrings**
- Usar **logging** estruturado (não print)
- Tratamento de erros com **try/except**
- Configurações vêm de `config/config.yaml`

### Segurança
- API Keys via **variável de ambiente** `GOOGLE_API_KEY`
- Nunca commitar chaves no código
- Arquivo `.env` está no `.gitignore`

---

## 🔧 Formato de Resposta da IA (NÃO ALTERAR!)

```
ARQUIVO: [nome];
CONTEUDO_IDENTIFICADO: [resumo];
VIOLACOES_ENCONTRADAS: [lista];
AVALIACAO: [análise];
RESULTADO: [Aprovado/Reprovado/Inconclusivo];
JUSTIFICATIVA: [explicação];
RECOMENDACOES: [sugestões];
```

O parsing em `parse_ia_response()` depende destes campos exatos com `;` no final.

---

## 📊 Saídas

| Pasta | Arquivo | Descrição |
|-------|---------|-----------|
| `ArquivosHouseXXXX/` | `manifest.json` | Metadados + hash |
| `TEMP/` | `resultados_*.json` | JSON intermediário |
| `BancodeDados/` | `ResultadoConforme*.xlsx` | Por execução |
| `BancodeDados/` | `historico_master.xlsx` | Cumulativo |

---

## ✅ Ao Fazer Alterações

1. Manter docstrings em todas as funções
2. Usar logging estruturado
3. Não quebrar o formato de resposta da IA
4. Testar com `python <script>.py --help`
5. Verificar se config.yaml tem os parâmetros necessários

---

## 📝 Ao Adicionar Novas Regras

1. Criar arquivo `.txt` em `Regras/`
2. Formato: `XX_nome_categoria.txt`
3. Conteúdo: `# Categoria` + lista com `-`
4. Regras são carregadas automaticamente

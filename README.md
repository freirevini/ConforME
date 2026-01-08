# ConforME - Automação de Compliance de Marketing

Sistema de avaliação automatizada de peças de marketing usando Inteligência Artificial (Google Gemini).

## 📋 Índice

- [Requisitos](#requisitos)
- [Instalação](#instalação)
- [Configuração](#configuração)
- [Como Executar](#como-executar)
- [Personalizando Regras](#personalizando-regras)
- [Personalizando o Prompt da IA](#personalizando-o-prompt-da-ia)
- [Estrutura de Pastas](#estrutura-de-pastas)
- [Saídas Geradas](#saídas-geradas)

---

## Requisitos

- Python 3.10+
- Conta Google (para API Key gratuita) ou projeto GCP (para Vertex AI)

---

## Instalação

```bash
# 1. Clone o repositório
git clone <url-do-repositorio>
cd ConforME

# 2. Instale as dependências
pip install -r requirements.txt
```

---

## Configuração

### Opção 1: Variável de Ambiente (Recomendado)

```powershell
# Windows PowerShell
$env:GOOGLE_API_KEY = "sua_api_key_aqui"

# Linux/Mac
export GOOGLE_API_KEY="sua_api_key_aqui"
```

### Opção 2: Arquivo config.yaml

Edite `config/config.yaml`:
```yaml
auth:
  mode: "api_key"
  api_key: "sua_api_key_aqui"  # NÃO commitar!
```

### Obter API Key Gratuita

1. Acesse: https://aistudio.google.com/apikey
2. Clique em "Create API Key"
3. Copie a chave gerada

### Configurar Pasta de Origem

Edite `config/config.yaml`:
```yaml
paths:
  source_folder: "G:\\Marketing\\Campanhas\\2025"  # Altere para sua pasta
```

---

## Como Executar

O sistema possui 3 scripts que devem ser executados em ordem:

### Passo 1: Captura de Arquivos

```bash
python captura_arquivos.py
```

**O que faz:**
- Percorre a pasta configurada em `source_folder`
- Copia arquivos para `ArquivosHouseDDMMYYYY/`
- Gera `manifest.json` com metadados

**Saída esperada:**
```
✅ Captura concluída! Arquivos em: ArquivosHouse08012026
   Execute agora: python avaliacao_ia.py --manifest "ArquivosHouse08012026/manifest.json"
```

### Passo 2: Avaliação por IA

```bash
python avaliacao_ia.py --manifest "ArquivosHouse08012026/manifest.json"
```

**O que faz:**
- Carrega regras de `Regras/*.txt`
- Envia cada arquivo para a IA
- Salva resultados em `TEMP/resultados_*.json`

**Saída esperada:**
```
✅ Avaliação concluída!
   Resultados salvos em: TEMP/resultados_08012026_143052.json
   Execute agora: python exportacao.py --input "TEMP/resultados_08012026_143052.json"
```

### Passo 3: Exportação para Excel

```bash
python exportacao.py --input "TEMP/resultados_08012026_143052.json"
```

**O que faz:**
- Gera planilha independente: `BancodeDados/ResultadoConformeDDMMYYYY.xlsx`
- Atualiza histórico cumulativo: `BancodeDados/historico_master.xlsx`

**Saída esperada:**
```
✅ Exportação concluída!
   📊 Planilha independente: BancodeDados/ResultadoConforme08012026.xlsx
   📚 Histórico master: BancodeDados/historico_master.xlsx
```

---

## Personalizando Regras

As regras de compliance ficam em arquivos `.txt` na pasta `Regras/`.

### Estrutura de um Arquivo de Regras

```text
# Nome da Categoria

- Primeira regra de compliance
- Segunda regra de compliance
- Terceira regra de compliance
```

### Exemplo: `Regras/01_ofertas_utilizacao_produtos.txt`

```text
# Ofertas/Utilização Produtos

- Ausência da frase: 'Sujeito à análise de crédito' no conteúdo
- Ausência dos Canais de atendimento
- Informações incorretas sobre o produto
- Ausência de Clareza nas informações para o cliente
```

### Adicionar Nova Categoria

1. Crie um novo arquivo `.txt` em `Regras/`
2. Use o formato: `XX_nome_categoria.txt` (ex: `07_redes_sociais.txt`)
3. Adicione as regras no formato de lista com `-`

**As regras são carregadas automaticamente** na próxima execução.

---

## Personalizando o Prompt da IA

O prompt principal está em `Regras/InstrucaoIA.txt`.

### Estrutura do Prompt

```text
Você é um especialista em Compliance de Marketing...

=== CONTEXTO ===
[Descrição do contexto]

=== REGRAS DE COMPLIANCE ===
{{REGRAS_DINAMICAS}}   ← Placeholder substituído automaticamente

=== INSTRUÇÕES DE ANÁLISE ===
[Passos que a IA deve seguir]

=== FORMATO DE RESPOSTA OBRIGATÓRIO ===
ARQUIVO: [nome];
CONTEUDO_IDENTIFICADO: [resumo];
VIOLACOES_ENCONTRADAS: [lista];
AVALIACAO: [análise];
RESULTADO: [Aprovado/Reprovado/Inconclusivo];
JUSTIFICATIVA: [explicação];
RECOMENDACOES: [sugestões];
```

### O que você pode editar:

| Seção | O que alterar |
|-------|---------------|
| Contexto | Adicionar informações sobre produtos específicos |
| Instruções | Mudar a forma como a IA deve analisar |
| Definições de Resultado | Ajustar critérios de aprovação |

### ⚠️ Importante

- **NÃO remova** `{{REGRAS_DINAMICAS}}` — é substituído pelas regras dos arquivos `.txt`
- **NÃO altere** os nomes dos campos de resposta (ARQUIVO, RESULTADO, etc.) — o parsing depende deles
- **Mantenha** o ponto-e-vírgula `;` no final de cada campo

---

## Estrutura de Pastas

```
ConforME/
├── config/
│   └── config.yaml          # Configurações do projeto
├── Regras/
│   ├── 01_ofertas_*.txt     # Regras de compliance
│   ├── 02_regulamentos.txt
│   ├── ...
│   └── InstrucaoIA.txt      # Prompt principal da IA
├── BancodeDados/
│   ├── ResultadoConforme*.xlsx  # Planilhas por execução
│   └── historico_master.xlsx    # Histórico cumulativo
├── TEMP/
│   └── resultados_*.json    # Resultados intermediários
├── ArquivosHouseXXXX/       # Arquivos copiados (por execução)
├── logs/                    # Logs de execução
├── captura_arquivos.py      # Script 1/3
├── avaliacao_ia.py          # Script 2/3
├── exportacao.py            # Script 3/3
└── requirements.txt         # Dependências
```

---

## Saídas Geradas

### Planilha Excel (Colunas)

| Coluna | Descrição |
|--------|-----------|
| Data | Data/hora da avaliação |
| Nome do Arquivo | Nome original do arquivo |
| Caminho Pasta | Pasta de origem |
| Hash SHA256 | Identificador único (rastreabilidade) |
| Conteúdo Identificado | Resumo do conteúdo |
| Violações Encontradas | Lista de violações |
| Avaliação | Análise completa |
| Resultado | Aprovado / Reprovado / Inconclusivo |
| Justificativa | Explicação do resultado |
| Recomendações | Sugestões de correção |
| Parecer Final Humano | **Vazio** (para revisão manual) |

---

## Dúvidas Frequentes

### A IA lê imagens?
Sim! O Gemini é multimodal e analisa textos, imagens, PDFs e outros formatos automaticamente.

### Como mudar o modelo de IA?
Edite `config/config.yaml`:
```yaml
ai:
  model_name: "gemini-2.0-flash-001"  # ou outro modelo disponível
```

### Como aumentar a precisão?
Reduza a temperatura em `config/config.yaml`:
```yaml
ai:
  temperature: 0.1  # Menor = mais determinístico
```

### Posso rodar em produção com Vertex AI?
Sim! Altere o modo em `config/config.yaml`:
```yaml
auth:
  mode: "vertex"
  project_id: "seu-projeto-gcp"
  location: "us-central1"
```

---

## Licença

Projeto interno - Uso restrito.

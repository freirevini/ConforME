---
description: Automação de análise de compliance para peças de marketing: varredura de pastas, captura de múltiplos formatos, envio a Vertex/GenAI, geração de relatório Excel e banco de dados para aprendizado humano contín
---

# Objetivo do Workflow
Criar e executar uma automação que percorre uma árvore de pastas (rota fictícia inicial), identifica arquivos de marketing (múltiplos formatos), copia-os para pasta local de execução com timestamp, envia-os ao motor GenAI/Vertex para avaliação conforme regras em `Regras/` e gera relatório Excel com colunas definidas para acompanhamento e aprendizado humano.

---

## Estrutura de pastas (sugestão inicial - rotas fictícias)
- /dados_origem/
  - /campanha_janeiro/
  - /campanha_fevereiro/
  - /assets/
- ./Automacao/  (onde o .py da automação ficará)
- ./Regras/     (txt com regras editáveis; carregadas no início)
- ./BancodeDados/  (arquivo Excel acumulado)
- ./ArquivosHouseDDMMYYYY/  (criado a cada execução com data)

---

## Regras operacionais do código (resumidas)
1. O agente deve percorrer recursivamente `/dados_origem/` (rota fictícia; depois substituída) e identificar arquivos de qualquer formato listado em `accepted_extensions`.
2. Ao encontrar um arquivo aceito:
   - criar (se não existir) pasta `ArquivosHouse<DDMMYYYY>` dentro do diretório da automação e copiar o arquivo para lá (nome sanitizado).
   - manter uma cópia original intacta.
3. Em vez de depender de bibliotecas pesadas para “ler” Word/Excel/Outlook, o agente **anexa o arquivo como parte** na chamada à API GenAI:
   - para texto/html/msg: usar `Part.from_text(...)`
   - para binários/imagens: usar `Part.from_bytes(...)` com mime-type apropriado
   - **Obs**: isto simula o comportamento de “usuário anexando” arquivos ao chat/IA.
4. As regras de compliance serão carregadas a partir da pasta `Regras/` contendo arquivos `.txt` (um por categoria). O conteúdo desses .txt será concatenado e injetado no prompt do sistema para avaliação. (ver lista de arquivos carregados).
5. A IA deve retornar a avaliação no **formato estrito** especificado (cada campo termina com `;`) para fácil parsing:
   - Campos principais (exemplo): `Relacionado ao BV: ...; Resultado: Aprovado/Reprovado/Inconclusivo; PontosEncontrados: ...; Recomendação: ...;`
6. O pipeline salvará resultados em:
   - arquivo Excel diário (TEMP) com colunas: `Data - Nome do Arquivo - Caminho Pasta - Avaliação - Resultado - Parecer Final Humano`
   - um BancodeDados principal em `BancodeDados/resultados_master.xlsx` que acumula todas as execuções (coluna 'Parecer Final Humano' inicialmente em branco).
7. A coluna **Parecer Final Humano** fica em branco para permitir correção manual posterior — essa planilha deverá ser considerada em futuras decisões do modelo (ver sugestão de aprendizado abaixo).
8. O workflow registrará logs estruturados (INFO/DEBUG/ERROR) e retornará um JSON resumo da execução.

---

## Arquivos de regras (pasta Regras/)
Coloque aqui arquivos `.txt` editáveis contendo regras / checklists por categoria (um arquivo por categoria). Exemplos de nomes:
- `01_ofertas_utilizacao_produtos.txt`
- `02_regulamentos.txt`
- `03_informativos_educativos.txt`
- `04_lancamentos_parcerias.txt`
- `05_influenciadores.txt`
- `06_pontos_a_evitar.txt`

**OBS:** esses arquivos já foram anexados ao projeto e devem ser copiados para `./Regras/`. (Veja os arquivos carregados: 01_ofertas..., 02_regulamentos..., 03_informativos..., 04_lancamentos..., 05_influenciadores..., 06_pontos_a_evitar...). :contentReference[oaicite:0]{index=0} :contentReference[oaicite:1]{index=1} :contentReference[oaicite:2]{index=2} :contentReference[oaicite:3]{index=3} :contentReference[oaicite:4]{index=4} :contentReference[oaicite:5]{index=5}

---

## Formato de saída esperado (exemplo de linha)
`NomeArquivo; Caminho; Formato; Relacionado ao BV: [Sim/Não]; AvaliaçãoAgente: ...; Resultado: [Aprovado|Reprovado|Inconclusivo]; PontosEncontrados: ...; Recomendação: ...;`

---

## Instrução/arquivo editável para "Instrução da IA"
Crie `Regras/InstrucaoIA.txt` com a instrução mestre (o texto do prompt do sistema pode ser editado aqui sem mexer no código). O agente irá recarregar esse arquivo a cada execução.

---

## Arquivos de saída e banco de dados
- Pasta `BancodeDados/` contém `resultados_master.xlsx` com colunas:
  `Data - Nome do Arquivo - Caminho Pasta - Avaliação - Resultado - Parecer Final Humano`
- A cada execução é criado também `TEMP/resultados_<timestamp>.xlsx` para download.

---

## Sugestão de processo de aprendizado contínuo (human-in-the-loop)
- Periodicamente (p.ex. semanal) o processo lê `BancodeDados/resultados_master.xlsx` e identifica linhas onde `Parecer Final Humano` ≠ vazio.
- Esses pares (entrada original + parecer humano) são usados para:
  - ajustar regras (txt) manualmente e/ou
  - montar um dataset para treinamento/ajuste-fino/feedback-loop da política de decisão (offline).
- No curto prazo, o agente pode usar ponderação por histórico: se houver discordância humana histórica para conteúdos similares, reduzir confiança e marcar como `Inconclusivo`.

---

## Observações de segurança e limite
- Não executar correções automáticas de remoção de conteúdo sensível sem validação humana.
- Logs não devem conter o conteúdo completo do arquivo (apenas metadados) quando conterem dados PII; cuidado com armazenamento.
- Validar quotas e permissões da API GenAI (project_id e location) antes de rodar.

---

## Referência de implementação (arquivo base enviado)
Use o arquivo `app.py` existente como referência para arquitetura e funções auxiliares (logging, load_rules_context, _build_system_prompt, análise com Vertex). :contentReference[oaicite:6]{index=6}


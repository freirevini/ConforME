# Regras do Projeto ConforME

## Arquitetura
- O projeto tem 3 scripts Python separados: captura, avaliação, exportação
- NÃO usar bibliotecas de parsing específicas (docx, pdfplumber, etc.)
- Arquivos são enviados como bytes para a IA interpretar
- Configurações centralizadas em `config/config.yaml`

## Regras de Compliance
- As regras ficam em `Regras/*.txt` como arquivos externos
- O prompt da IA está em `Regras/InstrucaoIA.txt`
- NUNCA hardcode regras no código Python
- Placeholder `{{REGRAS_DINAMICAS}}` é substituído automaticamente

## Padrões de Código
- Todas as funções devem ter docstrings completas
- Usar logging estruturado em vez de print
- Tratamento de erros com try/except em todas as operações de I/O
- Nomes de variáveis e funções em snake_case
- Comentários em português

## Segurança
- API Keys devem vir de variável de ambiente GOOGLE_API_KEY
- Nunca hardcode credenciais
- Arquivo .env está no .gitignore

## Saída
- Excel independente por execução + histórico master cumulativo
- Hash SHA256 obrigatório para rastreabilidade
- Campo "Parecer Final Humano" sempre vazio (preenchido manualmente)

## Formato de Resposta da IA
- Campos obrigatórios: ARQUIVO, RESULTADO, AVALIACAO, JUSTIFICATIVA
- Cada campo termina com ponto-e-vírgula (;)
- NÃO alterar nomes dos campos - o parsing depende deles

"""
Dr. Responsa Backend - Arquivo Único Consolidado
Analisa peças de marketing para compliance usando Google Vertex AI (Gemini).
"""
from __future__ import annotations

# ============================================================================
# IMPORTS
# ============================================================================
import os
import re
import getpass
import time
import logging
import html
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional

import yaml
import pandas as pd
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flasgger import Swagger, swag_from

from google import genai
from google.genai import types

from storage import StorageBackend, JSONBackend

# ============================================================================
# LOGGING ESTRUTURADO
# ============================================================================
def setup_logging() -> logging.Logger:
    """
    Configura logging estruturado para a aplicação.
    
    Returns:
        Logger configurado.
    """
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_format = os.getenv(
        "LOG_FORMAT",
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )
    
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format=log_format,
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    logger = logging.getLogger("dr_responsa")
    logger.setLevel(getattr(logging, log_level, logging.INFO))
    
    return logger


logger = setup_logging()


# ============================================================================
# SANITIZAÇÃO DE INPUTS
# ============================================================================
def sanitize_filename(filename: str) -> str:
    """
    Sanitiza nome de arquivo para evitar path traversal e caracteres maliciosos.
    
    Args:
        filename: Nome do arquivo original.
    
    Returns:
        Nome de arquivo sanitizado.
    """
    if not filename:
        return ""
    
    # Remove path traversal
    filename = filename.replace("..", "").replace("/", "").replace("\\", "")
    
    # Remove caracteres perigosos
    filename = re.sub(r'[<>:"|?*]', '', filename)
    
    # Limita tamanho
    if len(filename) > 255:
        name, ext = os.path.splitext(filename)
        filename = name[:255 - len(ext)] + ext
    
    return filename.strip()


def sanitize_text_input(text: str, max_length: int = 10000) -> str:
    """
    Sanitiza entrada de texto para evitar injeções.
    
    Args:
        text: Texto original.
        max_length: Tamanho máximo permitido.
    
    Returns:
        Texto sanitizado.
    """
    if not text:
        return ""
    
    # Escapa HTML
    text = html.escape(text)
    
    # Limita tamanho
    if len(text) > max_length:
        text = text[:max_length]
    
    return text.strip()


# PDF Support (opcional)
try:
    from PyPDF2 import PdfReader
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False
    logger.warning("PyPDF2 não instalado. Suporte a PDF de regras desabilitado.")


# ============================================================================
# PATHS
# ============================================================================
BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config" / "config.yaml"
RULES_DIR = BASE_DIR / "rules"
STATIC_DIR = BASE_DIR / "static"
UPLOADS_DIR = STATIC_DIR / "uploads"
TEMP_DIR = STATIC_DIR / "temp"

# Cria pastas necessárias
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================================
# CONFIGURAÇÃO - load_config()
# ============================================================================
_config_cache: Optional[Dict[str, Any]] = None


def load_config(reload: bool = False) -> Dict[str, Any]:
    """
    Carrega configurações do arquivo config/config.yaml.
    
    Args:
        reload: Se True, força recarregamento do arquivo.
    
    Returns:
        Dicionário com configurações.
    """
    global _config_cache
    
    if _config_cache is not None and not reload:
        return _config_cache
    
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Arquivo de configuração não encontrado: {CONFIG_PATH}")
    
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        _config_cache = yaml.safe_load(f)
    
    logger.info(f"Configuração carregada: {CONFIG_PATH}")
    return _config_cache


def get_ai_config() -> Dict[str, Any]:
    """Retorna configuração da IA."""
    return load_config().get("ai", {})


def get_accepted_extensions() -> List[str]:
    """Retorna lista de extensões aceitas."""
    return load_config().get("accepted_extensions", [])


def get_extra_fields() -> List[Dict[str, str]]:
    """Retorna campos extras para extração."""
    return load_config().get("extra_fields", [])


def get_extra_field_names() -> List[str]:
    """Retorna nomes dos campos extras."""
    return [f["name"] for f in get_extra_fields()]


def get_export_config() -> Dict[str, Any]:
    """Retorna configuração de exportação."""
    return load_config().get("export", {"filename_prefix": "resultados", "date_format": "%Y%m%d_%H%M%S"})


def get_system_context() -> Dict[str, Any]:
    """Retorna contexto do sistema para prompt."""
    return load_config().get("system_context", {})


def get_basic_compliance_prompt() -> str:
    """Retorna prompt básico para avaliação de outros itens (não-marketing)."""
    return load_config().get("basic_compliance_prompt", """
Você é um especialista em compliance e riscos não financeiros para instituições financeiras.
Avalie o conteúdo considerando riscos reputacionais, conformidade regulatória e proteção ao consumidor.
""")


def get_scope_guard_config() -> Dict[str, Any]:
    """Retorna configuração de guardrails de escopo da IA."""
    return load_config().get("ai_scope_guard", {})


def is_scope_guard_enabled() -> bool:
    """Verifica se o guardrail de escopo está habilitado."""
    return get_scope_guard_config().get("enabled", False)


def get_guard_prompt() -> str:
    """Retorna o prompt de guarda para injetar no system prompt."""
    return get_scope_guard_config().get("guard_prompt", "")


def get_rejection_message() -> str:
    """Retorna mensagem de rejeição quando fora do escopo."""
    return get_scope_guard_config().get("rejection_message", "Conteúdo fora do escopo permitido.")


def get_storage_config() -> Dict[str, Any]:
    """Retorna configuração de armazenamento."""
    return load_config().get("storage", {})


def get_evaluation_modes() -> Dict[str, Any]:
    """Retorna configuração dos modos de avaliação."""
    return load_config().get("evaluation_modes", {})


def get_evaluation_mode_config(mode: str) -> Dict[str, Any]:
    """Retorna configuração de um modo específico."""
    modes = get_evaluation_modes()
    return modes.get(mode, modes.get("conventional", {}))


# ============================================================================
# STORAGE BACKEND - Factory
# ============================================================================
_storage_backend: Optional[StorageBackend] = None


def get_storage_backend() -> StorageBackend:
    """
    Factory para obter o backend de armazenamento configurado.
    
    Returns:
        Instância do StorageBackend (JSON para POC, SQLite/GCS para produção)
    """
    global _storage_backend
    
    if _storage_backend is not None:
        return _storage_backend
    
    config = get_storage_config()
    backend_type = config.get("backend", "json")
    
    if backend_type == "json":
        json_config = config.get("json", {})
        data_dir = json_config.get("data_dir", "database")
        
        # Resolve caminho relativo ao BASE_DIR
        if not os.path.isabs(data_dir):
            data_dir = str(BASE_DIR / data_dir)
        
        _storage_backend = JSONBackend(data_dir)
        _storage_backend.initialize()
        logger.info(f"Storage backend inicializado: JSON ({data_dir})")
    
    elif backend_type == "sqlite":
        # SQLite para desenvolvimento (requer sqlite3)
        # from storage import SQLiteBackend
        # sqlite_config = config.get("sqlite", {})
        # db_path = sqlite_config.get("database_path", "database/evaluations.db")
        # _storage_backend = SQLiteBackend(db_path)
        logger.warning("SQLite backend não habilitado para POC, usando JSON")
        _storage_backend = JSONBackend(str(BASE_DIR / "database"))
        _storage_backend.initialize()
    
    elif backend_type == "gcs":
        # TODO: Implementar GCSBackend para produção
        logger.warning("GCS backend não implementado, usando JSON como fallback")
        _storage_backend = JSONBackend(str(BASE_DIR / "database"))
        _storage_backend.initialize()
    
    else:
        raise ValueError(f"Backend de storage desconhecido: {backend_type}")
    
    return _storage_backend


# ============================================================================
# REGRAS - load_rules_context()
# ============================================================================
_rules_cache: Optional[Dict[str, List[str]]] = None


def load_rules_context(reload: bool = False) -> Dict[str, List[str]]:
    """
    Carrega regras de compliance da pasta rules/.
    
    Args:
        reload: Se True, força recarregamento dos arquivos.
    
    Returns:
        Dicionário {nome_categoria: [lista_de_regras]}.
    """
    global _rules_cache
    
    if _rules_cache is not None and not reload:
        return _rules_cache
    
    _rules_cache = {}
    
    if not RULES_DIR.exists():
        logger.warning(f"Pasta de regras não encontrada: {RULES_DIR}")
        return _rules_cache
    
    # Lista arquivos ordenados
    files = sorted(RULES_DIR.glob("*"))
    
    for filepath in files:
        if filepath.is_dir():
            continue
        
        ext = filepath.suffix.lower()
        
        try:
            content = ""
            if ext == ".txt":
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            elif ext == ".pdf" and PDF_SUPPORT:
                reader = PdfReader(str(filepath))
                content = "\n".join(page.extract_text() or "" for page in reader.pages)
            else:
                continue
            
            # Extrai nome da categoria
            category_name = _extract_category_name(content, filepath.name)
            
            # Extrai regras
            rules = _extract_rules(content)
            
            if rules:
                _rules_cache[category_name] = rules
                logger.info(f"Regras carregadas: {category_name} ({len(rules)} regras)")
                
        except Exception as e:
            logger.error(f"Erro ao carregar {filepath.name}: {e}")
    
    return _rules_cache


def _extract_category_name(content: str, filename: str) -> str:
    """Extrai nome da categoria do conteúdo ou nome do arquivo."""
    # Tenta extrair do conteúdo (primeira linha com #)
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    
    # Fallback: usa nome do arquivo
    name = Path(filename).stem
    name = re.sub(r"^\d+_", "", name)  # Remove prefixo numérico
    return name.replace("_", " ").title()


def _extract_rules(content: str) -> List[str]:
    """Extrai lista de regras do conteúdo."""
    rules = []
    for line in content.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Remove marcadores
        if line.startswith("- "):
            line = line[2:]
        elif line.startswith("* "):
            line = line[2:]
        elif re.match(r"^\d+\.\s", line):
            line = re.sub(r"^\d+\.\s", "", line)
        if line:
            rules.append(line.strip())
    return rules


def get_rule_categories() -> List[str]:
    """Retorna nomes das categorias de regras."""
    return list(load_rules_context().keys())


def build_rules_prompt_section() -> str:
    """Constrói seção de regras para o prompt da IA."""
    sections = []
    for name, rules in load_rules_context().items():
        rules_text = "\n".join(f"  - {rule}" for rule in rules)
        sections.append(f"**{name}:**\n{rules_text}")
    return "\n\n".join(sections)


def build_output_format() -> str:
    """Constrói formato de saída esperado."""
    lines = []
    for name in get_rule_categories():
        lines.append(f"{name}: ...;")
    for field in get_extra_field_names():
        lines.append(f"{field}: ...;")
    return "\n".join(lines)


# ============================================================================
# IA - analyze_files_with_vertex()
# ============================================================================
_client: Optional[genai.Client] = None


def _get_vertex_client() -> genai.Client:
    """Retorna cliente Vertex AI (singleton)."""
    global _client
    if _client is None:
        ai = get_ai_config()
        _client = genai.Client(
            vertexai=True,
            project=ai.get("project_id", ""),
            location=ai.get("location", "us-central1")
        )
    return _client


def _build_system_prompt(
    evaluation_mode: str = "conventional",
    guided_prompt: str = "",
    item_type: str = "marketing"
) -> str:
    """
    Constrói prompt do sistema dinamicamente.
    
    Args:
        evaluation_mode: Modo de avaliação (conventional, guided, combined)
        guided_prompt: Instruções do usuário para modo orientado
        item_type: Tipo de item (marketing usa regras completas, outros usa prompt básico)
    """
    ctx = get_system_context()
    extra_fields = get_extra_fields()
    mode_config = get_evaluation_mode_config(evaluation_mode)
    
    # Data atual para contexto temporal
    current_date = datetime.now().strftime("%d/%m/%Y")
    current_datetime = datetime.now().strftime("%d/%m/%Y às %H:%M")
    
    date_context = f"""
=== CONTEXTO TEMPORAL ===
Data atual da análise: {current_date}
Data e hora da execução: {current_datetime}
IMPORTANTE: Use esta data como referência para avaliar validade de promoções, campanhas e datas mencionadas no conteúdo.
"""
    
    # Injetar guardrail de escopo se habilitado
    guard_section = ""
    if is_scope_guard_enabled():
        guard_prompt_text = get_guard_prompt()
        if guard_prompt_text:
            guard_section = f"\n{guard_prompt_text}\n"
    
    # Para marketing, usa prompt completo com regras do banco
    if item_type == "marketing":
        products = ", ".join(f"'{p}'" for p in ctx.get("products", []))
        instructions = "\n".join(f"- {i}" for i in ctx.get("evaluation_instructions", []))
        
        prompt = f"""{guard_section}{date_context}
Você é um {ctx.get('role', 'analista de compliance')}.
Os produtos ofertados pelo banco são: {products}.

{instructions}

Os textos terão no máximo {ctx.get('max_text_length', 120)} caracteres.
"""
        
        # Adiciona regras padrão se o modo usar
        if mode_config.get("use_standard_rules", True):
            prompt += f"""
=== REGRAS DE COMPLIANCE ===
{build_rules_prompt_section()}

=== CAMPOS EXTRAS ===
"""
            for field in extra_fields:
                prompt += f"- {field['name']}: {field['prompt_hint']}\n"
        
        # Adiciona prompt orientado para marketing se modo usar
        if mode_config.get("use_guided_prompt", False) and guided_prompt:
            prompt += f"\n=== AVALIAÇÃO ORIENTADA ADICIONAL ===\n{guided_prompt}\n"
    else:
        # Para outros itens (links, texto, arquivos), usa prompt básico
        basic_prompt = get_basic_compliance_prompt()
        prompt = f"""{guard_section}{date_context}
{basic_prompt}
"""
        # Para modo orientado, adiciona instrução específica para responder à pergunta do usuário
        if evaluation_mode == "guided" and guided_prompt:
            prompt += f"""
=== AVALIAÇÃO ORIENTADA ===
O usuário solicitou especificamente: "{guided_prompt}"

IMPORTANTE: Sua resposta DEVE focar em responder EXATAMENTE o que o usuário perguntou.
Use o contexto de produtos e serviços do Banco BV (Cartão de Crédito, Conta Digital, Empréstimo Consignado, 
Financiamento de Veículos, Empréstimo com Garantia, Financiamento de Placas Solares, Seguros) para 
responder de forma precisa e objetiva.

Gere um campo adicional na resposta:
Resumo: [Resposta direta e objetiva à pergunta do usuário - máximo 500 caracteres];
"""
        elif guided_prompt:
            # Fallback para outros modos com prompt orientado
            prompt += f"\n=== AVALIAÇÃO ORIENTADA ADICIONAL ===\n{guided_prompt}\n"
    
    # Formato de saída específico para outros itens (não-marketing)
    if item_type != "marketing":
        prompt += """
=== FORMATO DE SAÍDA ===
Para cada item analisado, responda EXATAMENTE neste formato (cada campo termina com ponto-e-vírgula):

Relacionado ao BV: [Sim/Não];
Avaliação do Agente: [Resumo dos principais problemas identificados - máximo 500 caracteres];
Resultado: [Aprovado/Reprovado/Inconclusivo];
Obs: [Se Inconclusivo, detalhe o motivo em até 500 caracteres. Se Aprovado ou Reprovado, deixe vazio];

DEFINIÇÃO DE RESULTADOS:
- Aprovado: Conteúdo sem riscos significativos identificados
- Reprovado: Conteúdo com riscos que impedem aprovação
- Inconclusivo: IA não conseguiu concluir por necessidade de avaliação mais aprofundada ou informações adicionais
"""
    else:
        prompt += f"""
=== FORMATO DE SAÍDA ===
Responda APENAS no formato abaixo (cada linha termina com ponto-e-vírgula):
{build_output_format()}
"""
    return prompt


def _validate_guided_prompt(prompt: str) -> tuple:
    """
    Valida se o prompt orientado está dentro do escopo permitido.
    
    Regras:
    - Deve ser relacionado a análise de riscos, compliance ou avaliação
    - Não pode mencionar outros bancos
    - Não pode ser sobre temas fora do escopo (ex: receitas, piadas, etc.)
    
    Returns:
        tuple: (is_valid: bool, error_message: str)
    """
    prompt_lower = prompt.lower()
    
    # Lista de outros bancos que não devem ser mencionados
    other_banks = [
        'santander', 'itaú', 'itau', 'bradesco', 'caixa', 'banco do brasil',
        'nubank', 'inter', 'c6', 'original', 'safra', 'btg', 'xp', 'modal',
        'pan', 'bmg', 'daycoval', 'abc', 'votorantim', 'sicoob', 'sicredi'
    ]
    
    # Verifica se menciona outros bancos
    for bank in other_banks:
        if bank in prompt_lower:
            return (False, f"Solicitação fora do escopo. Não é possível avaliar conteúdos relacionados a outras instituições financeiras.")
    
    # Palavras-chave que indicam temas fora do escopo
    off_topic_keywords = [
        'receita', 'culinária', 'piada', 'música', 'filme', 'série', 'jogo',
        'esporte', 'futebol', 'política', 'religião', 'horóscopo', 'previsão do tempo',
        'traduzir', 'tradução', 'código', 'programação', 'python', 'javascript'
    ]
    
    # Verifica se é sobre tema fora do escopo
    for keyword in off_topic_keywords:
        if keyword in prompt_lower:
            return (False, f"Solicitação fora do escopo. Por favor, envie uma solicitação relacionada a análise de riscos, compliance ou avaliação de conteúdos.")
    
    # Palavras-chave que indicam que está no escopo
    in_scope_keywords = [
        'avaliar', 'avaliação', 'analisar', 'análise', 'verificar', 'verificação',
        'risco', 'compliance', 'conformidade', 'regulatório', 'lgpd', 'bacen',
        'produto', 'serviço', 'oferta', 'promoção', 'campanha', 'marketing',
        'site', 'página', 'conteúdo', 'texto', 'imagem', 'documento',
        'cartão', 'empréstimo', 'financiamento', 'seguro', 'conta', 'crédito',
        'bv', 'banco', 'financeira', 'taxa', 'juros', 'cet', 'contrato'
    ]
    
    # Verifica se tem pelo menos uma palavra-chave do escopo
    has_scope_keyword = any(keyword in prompt_lower for keyword in in_scope_keywords)
    
    if not has_scope_keyword:
        return (False, "Solicitação fora do escopo. Por favor, descreva o que você gostaria que seja avaliado em relação a riscos, compliance ou produtos do Banco BV.")
    
    return (True, "")


def _get_mime_type(ext: str) -> str:
    """Retorna MIME type para extensão."""
    return {
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp"
    }.get(ext, "application/octet-stream")


def _build_regex_patterns() -> Dict[str, re.Pattern]:
    """Constrói padrões regex para extração."""
    patterns = {}
    for name in get_rule_categories():
        patterns[name] = re.compile(rf"{re.escape(name)}[\s\S]*?:\s*([^;\n]*)", re.IGNORECASE)
    for field in get_extra_field_names():
        patterns[field] = re.compile(rf"{re.escape(field)}[\s\S]*?:\s*([^;\n]*)", re.IGNORECASE)
    return patterns


def _parse_ai_response(raw_text: str) -> Dict[str, str]:
    """Extrai campos da resposta da IA."""
    patterns = _build_regex_patterns()
    return {
        name: (m.group(1).strip().rstrip(";") if (m := pattern.search(raw_text)) else "")
        for name, pattern in patterns.items()
    }


def _is_out_of_scope(raw_text: str) -> bool:
    """Verifica se a resposta da IA indica conteúdo fora do escopo."""
    return "[FORA_DO_ESCOPO]" in raw_text.upper()


def _evaluate_single_file(
    file_path: str,
    evaluation_mode: str = "conventional",
    guided_prompt: str = ""
) -> tuple[Dict[str, str], bool]:
    """
    Avalia um único arquivo com Vertex AI.
    
    Args:
        file_path: Caminho do arquivo
        evaluation_mode: Modo de avaliação (conventional, guided, combined)
        guided_prompt: Instruções do usuário para modo orientado
    
    Returns:
        Tupla (resultado_dict, is_out_of_scope)
    """
    ext = os.path.splitext(file_path)[1].lower()
    accepted = set(get_accepted_extensions())
    all_fields = get_rule_categories() + get_extra_field_names()
    
    if ext not in accepted:
        return {f: "" for f in all_fields}, False
    
    # Lê arquivo
    if ext in {".html", ".htm", ".txt", ".msg"}:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            file_part = types.Part.from_text(text=f.read())
    else:
        with open(file_path, "rb") as f:
            file_part = types.Part.from_bytes(data=f.read(), mime_type=_get_mime_type(ext))
    
    # Monta conteúdo com prompt baseado no modo
    system_prompt = _build_system_prompt(evaluation_mode, guided_prompt)
    contents = [types.Content(role="user", parts=[file_part, types.Part.from_text(text=system_prompt)])]
    
    # Configuração
    ai = get_ai_config()
    cfg = types.GenerateContentConfig(
        temperature=ai.get("temperature", 0.5),
        max_output_tokens=ai.get("max_output_tokens", 2048),
        top_p=ai.get("top_p", 0.95),
        response_modalities=["TEXT"]
    )
    
    # Chama IA
    response = _get_vertex_client().models.generate_content(
        model=ai.get("model_name", "gemini-2.0-flash-001"),
        contents=contents,
        config=cfg
    )
    
    raw_text = response.candidates[0].content.parts[0].text if response.candidates else ""
    
    # Verifica se conteúdo está fora do escopo
    if _is_out_of_scope(raw_text):
        logger.warning(f"Conteúdo fora do escopo detectado: {os.path.basename(file_path)}")
        return {f: "Fora do Escopo" for f in all_fields}, True
    
    return _parse_ai_response(raw_text), False


def analyze_files_with_vertex(
    folder_path: str,
    evaluation_mode: str = "conventional",
    guided_prompt: str = ""
) -> pd.DataFrame:
    """
    Avalia todos os arquivos de uma pasta.
    
    Args:
        folder_path: Caminho da pasta com arquivos.
        evaluation_mode: Modo de avaliação (conventional, guided, combined)
        guided_prompt: Instruções do usuário para modo orientado
    
    Returns:
        DataFrame com resultados da avaliação.
    """
    rows = []
    idx = 1
    accepted = set(get_accepted_extensions())
    rule_categories = get_rule_categories()
    extra_fields = get_extra_field_names()
    
    for root, _, files in os.walk(folder_path):
        for fname in files:
            path = os.path.join(root, fname)
            if not os.path.isfile(path):
                continue
            
            ext = os.path.splitext(fname)[1].lower()
            
            # Arquivo não reconhecido
            if ext not in accepted:
                rows.append({
                    "Item": idx,
                    "Nome": fname,
                    "Formato": "tipo desconhecido",
                    **{cat: "" for cat in rule_categories},
                    **{f: "" for f in extra_fields},
                    "Avaliação Final": "Ignorado",
                    "Data e Hora": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "Usuário": getpass.getuser(),
                })
                idx += 1
                continue
            
            # Avalia com modo e prompt orientado
            evaluation, is_out_of_scope = _evaluate_single_file(path, evaluation_mode, guided_prompt)
            
            # Se fora do escopo, marca como tal
            if is_out_of_scope:
                rows.append({
                    "Item": idx,
                    "Nome": fname,
                    "Formato": ext[1:],
                    **{cat: "Fora do Escopo" for cat in rule_categories},
                    **{f: "Fora do Escopo" for f in extra_fields},
                    "Avaliação Final": "Fora do Escopo",
                    "Data e Hora": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "Usuário": getpass.getuser(),
                })
                idx += 1
                continue
            
            # Determina aprovação
            aprovado = all(
                evaluation.get(k, "") == "" or
                "nenhuma inconsist" in evaluation.get(k, "").lower() or
                "não aplicá" in evaluation.get(k, "").lower()
                for k in rule_categories
            )
            
            rows.append({
                "Item": idx,
                "Nome": fname,
                "Formato": ext[1:],
                **{cat: evaluation.get(cat, "") for cat in rule_categories},
                **{f: evaluation.get(f, "") for f in extra_fields},
                "Avaliação Final": "Aprovado" if aprovado else "Reprovado",
                "Data e Hora": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "Usuário": getpass.getuser(),
            })
            idx += 1
    
    # Ordena colunas
    columns = (
        ["Item", "Nome", "Formato"] +
        rule_categories +
        extra_fields +
        ["Avaliação Final", "Data e Hora", "Usuário"]
    )
    
    df = pd.DataFrame(rows)
    existing = [c for c in columns if c in df.columns]
    return df[existing]


# ============================================================================
# FLASK APP
# ============================================================================
app = Flask(__name__, static_folder=str(STATIC_DIR))

# CORS configurado para permitir todas as origens (desenvolvimento)
CORS(app, 
     resources={r"/*": {"origins": "*"}},
     supports_credentials=True,
     allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])

# Swagger/OpenAPI Configuration
swagger_config = {
    "headers": [],
    "specs": [
        {
            "endpoint": "apispec",
            "route": "/apispec.json",
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/docs"
}

swagger_template = {
    "info": {
        "title": "Dr. Responsa API",
        "description": "API para análise de compliance de peças de marketing usando IA",
        "version": "1.0.0",
        "contact": {
            "name": "Equipe Dr. Responsa"
        }
    },
    "basePath": "/",
    "schemes": ["http", "https"]
}

swagger = Swagger(app, config=swagger_config, template=swagger_template)


@app.route("/")
def home():
    """
    Health check e informações do serviço
    ---
    tags:
      - Sistema
    responses:
      200:
        description: Status do serviço
        schema:
          type: object
          properties:
            status:
              type: string
              example: ok
            service:
              type: string
              example: Dr. Responsa API
            rules_loaded:
              type: array
              items:
                type: string
            extra_fields:
              type: array
              items:
                type: string
    """
    return jsonify({
        "status": "ok",
        "service": "Dr. Responsa API",
        "rules_loaded": get_rule_categories(),
        "extra_fields": get_extra_field_names()
    })


@app.route("/analyze", methods=["POST"])
def analyze():
    """
    Analisa arquivos de marketing para compliance
    ---
    tags:
      - Análise
    consumes:
      - multipart/form-data
    parameters:
      - name: files
        in: formData
        type: file
        required: true
        description: Arquivos para análise (PDF, JPG, PNG, etc.)
    responses:
      200:
        description: Análise realizada com sucesso
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            message:
              type: string
              example: Análise concluída em 5.2s
            data:
              type: object
              properties:
                total_files:
                  type: integer
                  example: 3
                approved:
                  type: integer
                  example: 2
                rejected:
                  type: integer
                  example: 1
                ignored:
                  type: integer
                  example: 0
                duration_seconds:
                  type: number
                  example: 5.2
                download_url:
                  type: string
                  example: /download/resultados_20241211_120000.xlsx
                preview:
                  type: array
                  items:
                    type: object
      400:
        description: Nenhum arquivo enviado ou arquivo inválido
      500:
        description: Erro interno do servidor
    """
    request_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
    start_time = time.time()
    
    logger.info(f"[{request_id}] Nova requisição de análise recebida")
    
    # Recebe arquivos
    uploaded_files = request.files.getlist("files")
    if not uploaded_files:
        logger.warning(f"[{request_id}] Requisição sem arquivos")
        return jsonify({"success": False, "error": "Nenhum arquivo enviado"}), 400
    
    logger.info(f"[{request_id}] Arquivos recebidos: {len(uploaded_files)}")
    
    # Limpa pasta de uploads
    for f in UPLOADS_DIR.iterdir():
        if f.is_file():
            f.unlink()
    
    # Salva arquivos com nomes sanitizados
    saved_files = []
    for file in uploaded_files:
        if file and file.filename:
            safe_filename = sanitize_filename(file.filename)
            if safe_filename:
                file.save(UPLOADS_DIR / safe_filename)
                saved_files.append(safe_filename)
                logger.debug(f"[{request_id}] Arquivo salvo: {safe_filename}")
    
    if not saved_files:
        logger.warning(f"[{request_id}] Nenhum arquivo válido para processar")
        return jsonify({"success": False, "error": "Nenhum arquivo válido"}), 400
    
    try:
        # Obtém parâmetros de modo de avaliação
        evaluation_mode = request.form.get("evaluation_mode", "conventional")
        guided_prompt = request.form.get("guided_prompt", "")
        
        logger.info(f"[{request_id}] Modo de avaliação: {evaluation_mode}")
        if guided_prompt:
            logger.info(f"[{request_id}] Prompt orientado: {guided_prompt[:100]}...")
        
        # Analisa
        logger.info(f"[{request_id}] Iniciando análise de {len(saved_files)} arquivo(s)")
        df = analyze_files_with_vertex(str(UPLOADS_DIR), evaluation_mode, guided_prompt)
        
        if df.empty:
            logger.warning(f"[{request_id}] Nenhum arquivo pôde ser avaliado")
            return jsonify({
                "success": False,
                "error": "Nenhum arquivo pôde ser avaliado"
            }), 400
        
        # Limpa pasta temp
        for f in TEMP_DIR.iterdir():
            if f.is_file():
                f.unlink()
        
        # Gera Excel
        export_cfg = get_export_config()
        ts = datetime.now().strftime(export_cfg.get("date_format", "%Y%m%d_%H%M%S"))
        filename = f"{export_cfg.get('filename_prefix', 'resultados')}_{ts}.xlsx"
        filepath = TEMP_DIR / filename
        df.to_excel(filepath, index=False)
        
        duration = round(time.time() - start_time, 2)
        
        result = {
            "total_files": len(df),
            "approved": len(df[df["Avaliação Final"] == "Aprovado"]),
            "rejected": len(df[df["Avaliação Final"] == "Reprovado"]),
            "ignored": len(df[df["Avaliação Final"] == "Ignorado"]),
            "out_of_scope": len(df[df["Avaliação Final"] == "Fora do Escopo"]),
        }
        
        # Calcula resultado geral
        if result["rejected"] > 0:
            overall_result = "Reprovado"
        elif result["out_of_scope"] > 0:
            overall_result = "Inconclusivo"
        elif result["ignored"] > 0:
            overall_result = "Inconclusivo"
        else:
            overall_result = "Aprovado"
        
        # Salva no storage
        storage = get_storage_backend()
        evaluation_id = storage.generate_evaluation_id()
        
        # Obtém username do request (header ou form)
        username = request.form.get("username") or request.headers.get("X-Username") or getpass.getuser()
        
        # Converte DataFrame para lista de dicts para salvar
        detailed_results = df.to_dict("records")
        
        storage.save_evaluation(
            evaluation_id=evaluation_id,
            username=username,
            item_count=result["total_files"],
            overall_result=overall_result,
            detailed_results=detailed_results
        )
        
        logger.info(
            f"[{request_id}] Análise concluída em {duration}s - ID: {evaluation_id} - "
            f"Total: {result['total_files']}, Aprovados: {result['approved']}, "
            f"Reprovados: {result['rejected']}, Ignorados: {result['ignored']}"
        )
        
        return jsonify({
            "success": True,
            "message": f"Análise concluída em {duration}s",
            "data": {
                **result,
                "evaluation_id": evaluation_id,
                "overall_result": overall_result,
                "duration_seconds": duration,
                "download_url": f"/download/{filename}",
                "preview": df[["Item", "Nome", "Formato", "Avaliação Final"]].to_dict("records")
            }
        })
        
    except Exception as e:
        logger.error(f"[{request_id}] Erro na análise: {str(e)}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/analyze-text", methods=["POST"])
def analyze_text():
    """
    Analisa texto para compliance
    ---
    tags:
      - Análise
    consumes:
      - application/json
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            text:
              type: string
              description: Texto para análise
            evaluation_mode:
              type: string
              enum: [conventional, guided, combined]
              default: conventional
            guided_prompt:
              type: string
              description: Instruções do usuário para modo orientado
            item_type:
              type: string
              description: Tipo de item (marketing ou outros)
    responses:
      200:
        description: Análise realizada com sucesso
      400:
        description: Texto não fornecido
      500:
        description: Erro interno do servidor
    """
    request_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
    start_time = time.time()
    
    logger.info(f"[{request_id}] Nova requisição de análise de texto")
    
    data = request.get_json() or {}
    text_content = data.get("text", "").strip()
    
    if not text_content:
        return jsonify({"success": False, "error": "Texto não fornecido"}), 400
    
    evaluation_mode = data.get("evaluation_mode", "conventional")
    guided_prompt = data.get("guided_prompt", "")
    item_type = data.get("item_type", "text")
    
    # Trunca texto para exibição
    text_preview = text_content[:50] + "..." if len(text_content) > 50 else text_content
    
    try:
        # Cria part de texto
        text_part = types.Part.from_text(text=text_content)
        
        # Monta prompt baseado no tipo de item
        system_prompt = _build_system_prompt(evaluation_mode, guided_prompt, item_type)
        
        contents = [types.Content(role="user", parts=[text_part, types.Part.from_text(text=system_prompt)])]
        
        # Configuração
        ai = get_ai_config()
        cfg = types.GenerateContentConfig(
            temperature=ai.get("temperature", 0.5),
            max_output_tokens=ai.get("max_output_tokens", 2048),
            top_p=ai.get("top_p", 0.95),
            response_modalities=["TEXT"]
        )
        
        # Chama IA
        response = _get_vertex_client().models.generate_content(
            model=ai.get("model_name", "gemini-2.0-flash-001"),
            contents=contents,
            config=cfg
        )
        
        raw_text = response.candidates[0].content.parts[0].text if response.candidates else ""
        
        # Verifica escopo
        is_out_of_scope_flag = _is_out_of_scope(raw_text)
        
        # Parse resposta
        evaluation = _parse_ai_response(raw_text)
        
        # Determina aprovação
        rule_categories = get_rule_categories()
        extra_fields = get_extra_field_names()
        
        if is_out_of_scope_flag:
            overall_result = "Fora do Escopo"
        else:
            aprovado = all(
                evaluation.get(k, "") == "" or
                "nenhuma inconsist" in evaluation.get(k, "").lower() or
                "não aplicá" in evaluation.get(k, "").lower()
                for k in rule_categories
            )
            overall_result = "Aprovado" if aprovado else "Reprovado"
        
        duration = round(time.time() - start_time, 2)
        
        # ═══════════════════════════════════════════════════════════════════
        # GERA EXCEL COM RESULTADOS
        # ═══════════════════════════════════════════════════════════════════
        
        # Monta DataFrame
        row_data = {
            "Item": 1,
            "Nome": text_preview,
            "Formato": "TXT",
            **{cat: evaluation.get(cat, "") for cat in rule_categories},
            **{f: evaluation.get(f, "") for f in extra_fields},
            "Avaliação Final": overall_result,
            "Data e Hora": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Usuário": data.get("username") or getpass.getuser(),
        }
        
        df = pd.DataFrame([row_data])
        
        # Ordena colunas
        columns = (
            ["Item", "Nome", "Formato"] +
            rule_categories +
            extra_fields +
            ["Avaliação Final", "Data e Hora", "Usuário"]
        )
        existing = [c for c in columns if c in df.columns]
        df = df[existing]
        
        # Gera arquivo Excel
        export_cfg = get_export_config()
        ts = datetime.now().strftime(export_cfg.get("date_format", "%Y%m%d_%H%M%S"))
        filename = f"{export_cfg.get('filename_prefix', 'resultados')}_texto_{ts}.xlsx"
        filepath = TEMP_DIR / filename
        df.to_excel(filepath, index=False)
        
        # Salva no storage
        storage = get_storage_backend()
        evaluation_id = storage.generate_evaluation_id()
        username = data.get("username") or request.headers.get("X-Username") or getpass.getuser()
        
        storage.save_evaluation(
            evaluation_id=evaluation_id,
            username=username,
            item_count=1,
            overall_result=overall_result,
            detailed_results=[row_data]
        )
        
        logger.info(f"[{request_id}] Análise de texto concluída em {duration}s - ID: {evaluation_id}")
        
        return jsonify({
            "success": True,
            "data": {
                "evaluation_id": evaluation_id,
                "total_files": 1,
                "approved": 1 if overall_result == "Aprovado" else 0,
                "rejected": 1 if overall_result == "Reprovado" else 0,
                "ignored": 0,
                "out_of_scope": 1 if overall_result == "Fora do Escopo" else 0,
                "overall_result": overall_result,
                "duration_seconds": duration,
                "download_url": f"/download/{filename}",
                "preview": [{
                    "Item": 1,
                    "Nome": text_preview,
                    "Formato": "TXT",
                    "Avaliação Final": overall_result
                }]
            }
        })
        
    except Exception as e:
        logger.error(f"[{request_id}] Erro na análise de texto: {str(e)}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/analyze-url", methods=["POST"])
def analyze_url():
    """
    Analisa conteúdo completo de URL(s) para compliance (textos, imagens, links, logos)
    Suporta múltiplas URLs separadas por vírgula
    ---
    tags:
      - Análise
    consumes:
      - application/json
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            url:
              type: string
              description: URL(s) para análise (separadas por vírgula)
            evaluation_mode:
              type: string
              enum: [conventional, guided, combined]
              default: conventional
            guided_prompt:
              type: string
              description: Instruções do usuário para modo orientado
            item_type:
              type: string
              description: Tipo de item (marketing ou outros)
    responses:
      200:
        description: Análise realizada com sucesso
      400:
        description: URL não fornecida ou inválida
      500:
        description: Erro interno do servidor
    """
    import urllib.request
    import urllib.error
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin
    
    request_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
    start_time = time.time()
    
    logger.info(f"[{request_id}] Nova requisição de análise de URL")
    
    data = request.get_json() or {}
    url_input = data.get("url", "").strip()
    
    if not url_input:
        return jsonify({"success": False, "error": "URL não fornecida"}), 400
    
    # Suporta múltiplas URLs separadas por vírgula
    urls = [u.strip() for u in url_input.split(",") if u.strip()]
    
    # Valida e normaliza URLs
    normalized_urls = []
    for url in urls:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        normalized_urls.append(url)
    
    evaluation_mode = data.get("evaluation_mode", "conventional")
    guided_prompt = data.get("guided_prompt", "")
    item_type = data.get("item_type", "links")
    
    # Valida prompt orientado se modo for guided
    if evaluation_mode == "guided" and guided_prompt:
        is_valid, error_message = _validate_guided_prompt(guided_prompt)
        if not is_valid:
            return jsonify({
                "success": False, 
                "error": error_message,
                "out_of_scope": True
            }), 400
    
    logger.info(f"[{request_id}] Processando {len(normalized_urls)} URL(s)")
    
    # Configuração da IA
    ai = get_ai_config()
    cfg = types.GenerateContentConfig(
        temperature=ai.get("temperature", 0.5),
        max_output_tokens=ai.get("max_output_tokens", 4096),
        top_p=ai.get("top_p", 0.95),
        response_modalities=["TEXT"]
    )
    
    # Monta prompt base
    system_prompt = _build_system_prompt(evaluation_mode, guided_prompt, item_type)
    
    rule_categories = get_rule_categories()
    extra_fields = get_extra_field_names()
    
    # Processa cada URL
    all_results = []
    preview_list = []
    approved_count = 0
    rejected_count = 0
    out_of_scope_count = 0
    guided_summary = ""  # Resumo para avaliação orientada exclusiva
    
    for idx, url in enumerate(normalized_urls, 1):
        try:
            logger.info(f"[{request_id}] Fazendo scraping de URL {idx}/{len(normalized_urls)}: {url}")
            
            req = urllib.request.Request(
                url,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            )
            
            with urllib.request.urlopen(req, timeout=30) as response:
                html_content = response.read().decode('utf-8', errors='ignore')
            
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Extrai imagens
            images = []
            for img in soup.find_all('img'):
                src = img.get('src', '')
                alt = img.get('alt', '')
                if src:
                    full_url = urljoin(url, src)
                    images.append({"src": full_url, "alt": alt})
            
            # Extrai links
            links = []
            for a in soup.find_all('a', href=True):
                href = a.get('href', '')
                text = a.get_text(strip=True)
                if href and not href.startswith('#'):
                    full_url = urljoin(url, href)
                    links.append({"href": full_url, "text": text[:100]})
            
            # Extrai logos
            logos = []
            for img in soup.find_all('img'):
                src = img.get('src', '').lower()
                alt = img.get('alt', '').lower()
                classes = ' '.join(img.get('class', [])).lower()
                if 'logo' in src or 'logo' in alt or 'logo' in classes:
                    logos.append(urljoin(url, img.get('src', '')))
            
            # Remove scripts/styles
            for script in soup(["script", "style"]):
                script.decompose()
            
            title = soup.title.string if soup.title else ""
            meta_desc = ""
            meta_tag = soup.find('meta', attrs={'name': 'description'})
            if meta_tag:
                meta_desc = meta_tag.get('content', '')
            
            body_text = soup.get_text(separator='\n', strip=True)
            if len(body_text) > 15000:
                body_text = body_text[:15000] + "..."
            
            # ═══════════════════════════════════════════════════════════════════
            # DETECÇÃO DE RELAÇÃO COM BANCO BV
            # ═══════════════════════════════════════════════════════════════════
            bv_keywords = ['banco bv', 'bv financeira', 'bv.com.br', 'bancobv', 'bv bank', 'bv crédito']
            content_lower = (html_content + title + meta_desc).lower()
            
            # Verifica domínio e conteúdo
            is_bv_related = (
                'bv.com.br' in url.lower() or
                'bancobv' in url.lower() or
                any(kw in content_lower for kw in bv_keywords) or
                any('bv' in logo.lower() for logo in logos)
            )
            relacionado_bv = "Sim" if is_bv_related else "Não"
            
            # Monta conteúdo para análise
            site_analysis = f"""
=== ANÁLISE COMPLETA DO SITE ===
URL: {url}
Título: {title}
Descrição: {meta_desc}
Relacionado ao Banco BV: {relacionado_bv}

=== IMAGENS ENCONTRADAS ({len(images)}) ===
{chr(10).join([f"- {img['alt'] or 'Sem descrição'}: {img['src']}" for img in images[:20]])}

=== LOGOS IDENTIFICADOS ({len(logos)}) ===
{chr(10).join([f"- {logo}" for logo in logos[:10]])}

=== LINKS DO SITE ({len(links)}) ===
{chr(10).join([f"- {link['text']}: {link['href']}" for link in links[:30]])}

=== CONTEÚDO TEXTUAL ===
{body_text}
"""
            
            # Chama IA
            text_part = types.Part.from_text(text=site_analysis)
            contents = [types.Content(role="user", parts=[text_part, types.Part.from_text(text=system_prompt)])]
            
            response_ai = _get_vertex_client().models.generate_content(
                model=ai.get("model_name", "gemini-2.0-flash-001"),
                contents=contents,
                config=cfg
            )
            
            raw_text = response_ai.candidates[0].content.parts[0].text if response_ai.candidates else ""
            
            # ═══════════════════════════════════════════════════════════════════
            # TRATAMENTO ESPECIAL: Site não relacionado ao BV
            # ═══════════════════════════════════════════════════════════════════
            if relacionado_bv == "Não":
                # Extrai nome da marca do site (do título ou domínio)
                from urllib.parse import urlparse
                domain = urlparse(url).netloc.replace('www.', '')
                marca = title.split('-')[0].strip() if title else domain
                
                avaliacao_agente = f"O site é da marca '{marca}' e não está em nosso escopo de avaliação."
                resultado = "Fora do Escopo"
                obs = "Site não relacionado ao Banco BV."
                out_of_scope_count += 1
                
                # Para avaliação orientada exclusiva, gera resumo específico
                if evaluation_mode == "guided" and guided_prompt:
                    guided_summary = f"O site é da marca '{marca}' e não está em nosso escopo."
            else:
                # Parse da resposta para novo formato (não-marketing)
                avaliacao_agente = ""
                resultado = ""
                obs = ""
                
                # Extrai campos do novo formato
                if "Avaliação do Agente:" in raw_text:
                    match = re.search(r"Avaliação do Agente:\s*([^;]*);?", raw_text, re.IGNORECASE)
                    if match:
                        avaliacao_agente = match.group(1).strip()[:500]
                
                if "Resultado:" in raw_text:
                    match = re.search(r"Resultado:\s*([^;]*);?", raw_text, re.IGNORECASE)
                    if match:
                        resultado_raw = match.group(1).strip().lower()
                        if "aprovado" in resultado_raw:
                            resultado = "Aprovado"
                        elif "reprovado" in resultado_raw:
                            resultado = "Reprovado"
                        elif "inconclusivo" in resultado_raw:
                            resultado = "Inconclusivo"
                        else:
                            resultado = "Inconclusivo"
                
                if "Obs:" in raw_text:
                    match = re.search(r"Obs:\s*([^;]*);?", raw_text, re.IGNORECASE)
                    if match:
                        obs = match.group(1).strip()[:500]
                
                # Extrai resumo da resposta para exibição no chat
                # Tanto para modo guided quanto conventional
                if not guided_summary:
                    # Tenta extrair um resumo da resposta da IA
                    resumo_match = re.search(r"Resumo:\s*([^;]*);?", raw_text, re.IGNORECASE)
                    if resumo_match:
                        guided_summary = resumo_match.group(1).strip()[:500]
                    elif avaliacao_agente:
                        # Usa a avaliação do agente como resumo
                        guided_summary = avaliacao_agente[:500]
                    else:
                        # Usa os primeiros 500 caracteres da resposta como resumo
                        guided_summary = raw_text[:500].strip()
                
                # Fallback: se não encontrou o formato novo, usa lógica antiga
                if not resultado:
                    is_out_of_scope_flag = _is_out_of_scope(raw_text)
                    evaluation = _parse_ai_response(raw_text)
                    
                    if is_out_of_scope_flag:
                        resultado = "Fora do Escopo"
                        out_of_scope_count += 1
                    else:
                        aprovado = all(
                            evaluation.get(k, "") == "" or
                            "nenhuma inconsist" in evaluation.get(k, "").lower() or
                            "não aplicá" in evaluation.get(k, "").lower()
                            for k in rule_categories
                        )
                        resultado = "Aprovado" if aprovado else "Reprovado"
                    avaliacao_agente = raw_text[:500] if not avaliacao_agente else avaliacao_agente
                
                # Contagem
                if resultado == "Aprovado":
                    approved_count += 1
                elif resultado == "Reprovado":
                    rejected_count += 1
                elif resultado == "Fora do Escopo":
                    out_of_scope_count += 1
            
            row_data = {
                "Item": idx,
                "Nome": url,
                "Relacionado ao BV": relacionado_bv,
                "Avaliação do Agente": avaliacao_agente,
                "Resultado": resultado,
                "Obs": obs,
                "Data e Hora": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "Usuário": data.get("username") or getpass.getuser(),
            }
            all_results.append(row_data)
            preview_list.append({
                "Item": idx,
                "Nome": url,
                "Relacionado ao BV": relacionado_bv,
                "Resultado": resultado
            })
            
        except urllib.error.URLError as e:
            logger.warning(f"[{request_id}] Erro ao acessar URL {url}: {str(e)}")
            row_data = {
                "Item": idx,
                "Nome": url,
                "Relacionado ao BV": "N/A",
                "Avaliação do Agente": f"Erro ao acessar URL: {str(e)[:200]}",
                "Resultado": "Inconclusivo",
                "Obs": "Link inacessível ou incorreto. Verifique se a URL está correta e acessível.",
                "Data e Hora": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "Usuário": data.get("username") or getpass.getuser(),
            }
            all_results.append(row_data)
            preview_list.append({
                "Item": idx,
                "Nome": url,
                "Relacionado ao BV": "N/A",
                "Resultado": "Inconclusivo"
            })
    
    try:
        duration = round(time.time() - start_time, 2)
        
        # Gera Excel com nova estrutura de colunas
        df = pd.DataFrame(all_results)
        columns = [
            "Item", 
            "Nome", 
            "Relacionado ao BV", 
            "Avaliação do Agente", 
            "Resultado", 
            "Obs",
            "Data e Hora", 
            "Usuário"
        ]
        existing = [c for c in columns if c in df.columns]
        df = df[existing]
        
        export_cfg = get_export_config()
        ts = datetime.now().strftime(export_cfg.get("date_format", "%Y%m%d_%H%M%S"))
        filename = f"{export_cfg.get('filename_prefix', 'resultados')}_url_{ts}.xlsx"
        filepath = TEMP_DIR / filename
        df.to_excel(filepath, index=False)
        
        # Salva no storage
        storage = get_storage_backend()
        evaluation_id = storage.generate_evaluation_id()
        username = data.get("username") or request.headers.get("X-Username") or getpass.getuser()
        
        overall_result = "Aprovado" if rejected_count == 0 and out_of_scope_count == 0 else "Reprovado"
        
        storage.save_evaluation(
            evaluation_id=evaluation_id,
            username=username,
            item_count=len(normalized_urls),
            overall_result=overall_result,
            detailed_results=all_results
        )
        
        logger.info(f"[{request_id}] Análise de {len(normalized_urls)} URL(s) concluída em {duration}s - ID: {evaluation_id}")
        
        # Monta resposta com guided_summary se for avaliação orientada exclusiva
        response_data = {
            "evaluation_id": evaluation_id,
            "total_files": len(normalized_urls),
            "approved": approved_count,
            "rejected": rejected_count,
            "ignored": 0,
            "out_of_scope": out_of_scope_count,
            "overall_result": overall_result,
            "duration_seconds": duration,
            "download_url": f"/download/{filename}",
            "preview": preview_list
        }
        
        # Adiciona resumo da avaliação orientada se disponível
        if evaluation_mode == "guided" and guided_summary:
            response_data["guided_summary"] = guided_summary
        
        return jsonify({
            "success": True,
            "data": response_data
        })
        
    except Exception as e:
        logger.error(f"[{request_id}] Erro na análise de URL: {str(e)}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/download/<filename>")
def download(filename: str):
    """
    Download do relatório Excel gerado
    ---
    tags:
      - Download
    parameters:
      - name: filename
        in: path
        type: string
        required: true
        description: Nome do arquivo para download
    responses:
      200:
        description: Arquivo Excel
        content:
          application/vnd.openxmlformats-officedocument.spreadsheetml.sheet:
            schema:
              type: file
      400:
        description: Nome de arquivo inválido
      404:
        description: Arquivo não encontrado
    """
    # Sanitiza e valida filename
    safe_filename = sanitize_filename(filename)
    
    if not safe_filename or safe_filename != filename:
        logger.warning(f"Tentativa de download com nome inválido: {filename}")
        return jsonify({"error": "Nome de arquivo inválido"}), 400
    
    filepath = TEMP_DIR / safe_filename
    if not filepath.exists():
        logger.warning(f"Arquivo não encontrado para download: {safe_filename}")
        return jsonify({"error": "Arquivo não encontrado"}), 404
    
    logger.info(f"Download realizado: {safe_filename}")
    return send_from_directory(str(TEMP_DIR), safe_filename, as_attachment=True)


@app.route("/evaluation/<string:evaluation_id>", methods=["GET"])
def get_evaluation(evaluation_id: str):
    """
    Consulta uma avaliação pelo ID
    ---
    tags:
      - Consulta
    parameters:
      - name: evaluation_id
        in: path
        type: string
        required: true
        description: ID da avaliação (ex: RNF0001264)
    responses:
      200:
        description: Dados da avaliação
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            data:
              type: object
              properties:
                id:
                  type: string
                  example: RNF0001264
                request_date:
                  type: string
                  example: "2025-12-12"
                username:
                  type: string
                  example: vinicius.silva
                item_count:
                  type: integer
                  example: 3
                overall_result:
                  type: string
                  example: Aprovado
                results:
                  type: array
                  items:
                    type: object
      404:
        description: Avaliação não encontrada
    """
    # Valida formato do ID (RNF + 7 dígitos)
    if not evaluation_id or not evaluation_id.upper().startswith("RNF"):
        logger.warning(f"Formato de ID inválido: {evaluation_id}")
        return jsonify({
            "success": False,
            "error": "Formato de ID inválido. Use o formato RNFXXXXXXX (ex: RNF0001264)"
        }), 400
    
    # Normaliza para maiúsculas
    evaluation_id = evaluation_id.upper()
    
    storage = get_storage_backend()
    evaluation = storage.get_evaluation(evaluation_id)
    
    if not evaluation:
        logger.info(f"Avaliação não encontrada: {evaluation_id}")
        return jsonify({
            "success": False,
            "error": f"Avaliação {evaluation_id} não encontrada"
        }), 404
    
    logger.info(f"Consulta de avaliação: {evaluation_id}")
    
    return jsonify({
        "success": True,
        "data": evaluation
    })


@app.route("/evaluations", methods=["GET"])
def list_evaluations():
    """
    Lista avaliações com filtros opcionais
    ---
    tags:
      - Consulta
    parameters:
      - name: username
        in: query
        type: string
        required: false
        description: Filtrar por usuário
      - name: limit
        in: query
        type: integer
        required: false
        default: 50
        description: Máximo de resultados
    responses:
      200:
        description: Lista de avaliações
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            data:
              type: array
              items:
                type: object
    """
    username = request.args.get("username")
    limit = request.args.get("limit", 50, type=int)
    
    storage = get_storage_backend()
    evaluations = storage.list_evaluations(username=username, limit=limit)
    
    logger.info(f"Listagem de avaliações: {len(evaluations)} resultados")
    
    return jsonify({
        "success": True,
        "data": evaluations,
        "count": len(evaluations)
    })


@app.route("/evaluations/statistics", methods=["GET"])
def get_statistics():
    """
    Retorna estatísticas das avaliações
    ---
    tags:
      - Consulta
    responses:
      200:
        description: Estatísticas gerais
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            data:
              type: object
    """
    storage = get_storage_backend()
    stats = storage.get_statistics()
    
    return jsonify({
        "success": True,
        "data": stats
    })


# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    # Carrega configurações na inicialização
    logger.info("=" * 50)
    logger.info("Dr. Responsa Backend - Iniciando")
    logger.info("=" * 50)
    
    load_config()
    load_rules_context()
    
    # Inicializa storage backend
    storage = get_storage_backend()
    stats = storage.get_statistics()
    logger.info(f"Storage inicializado - {stats.get('total_evaluations', 0)} avaliações registradas")
    
    logger.info(f"Categorias carregadas: {get_rule_categories()}")
    logger.info(f"Campos extras: {get_extra_field_names()}")
    logger.info("=" * 50)
    
    # Inicia servidor
    debug = os.getenv("FLASK_DEBUG", "true").lower() == "true"
    port = int(os.getenv("PORT", 8000))
    logger.info(f"Servidor iniciando em http://0.0.0.0:{port} (debug={debug})")
    app.run(host="0.0.0.0", port=port, debug=debug)

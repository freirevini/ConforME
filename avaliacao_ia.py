#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ConforME - Avaliação por IA
===========================

Script 02/03 da automação de compliance de marketing.

Responsabilidades:
- Ler manifest.json gerado pelo captura_arquivos.py
- Carregar regras de compliance dos arquivos .txt
- Construir prompt dinâmico com regras
- Enviar arquivos para IA (Google GenAI / Vertex AI)
- Parsear resposta estruturada
- Salvar resultados em JSON intermediário

Autor: ConforME Team
Data: Janeiro 2026
"""

import os
import sys
import json
import yaml
import logging
import argparse
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

# ============================================================================
# CONFIGURAÇÃO DE PATHS
# ============================================================================
BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config" / "config.yaml"
RULES_DIR = BASE_DIR / "Regras"
LOGS_DIR = BASE_DIR / "logs"
TEMP_DIR = BASE_DIR / "TEMP"


# ============================================================================
# LOGGING
# ============================================================================
def setup_logging(config: Dict[str, Any]) -> logging.Logger:
    """
    Configura o sistema de logging.
    
    Args:
        config: Dicionário de configurações do YAML.
        
    Returns:
        Logger configurado.
    """
    log_config = config.get("logging", {})
    log_level = getattr(logging, log_config.get("level", "INFO").upper())
    log_format = log_config.get("format", "%(asctime)s | %(levelname)-8s | %(message)s")
    
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            LOGS_DIR / "avaliacao_ia.log",
            encoding="utf-8"
        )
    ]
    
    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=handlers
    )
    
    return logging.getLogger("avaliacao_ia")


# ============================================================================
# CONFIGURAÇÃO
# ============================================================================
def load_config() -> Dict[str, Any]:
    """
    Carrega configurações do arquivo config.yaml.
    
    Returns:
        Dicionário com configurações.
    """
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Arquivo de configuração não encontrado: {CONFIG_PATH}")
    
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    
    return config


# ============================================================================
# CARREGAMENTO DE REGRAS
# ============================================================================
def load_compliance_rules(rules_dir: Path, logger: logging.Logger) -> Dict[str, List[str]]:
    """
    Carrega regras de compliance dos arquivos .txt na pasta Regras.
    
    Args:
        rules_dir: Caminho da pasta de regras.
        logger: Logger para registrar operações.
        
    Returns:
        Dicionário {nome_categoria: [lista_de_regras]}.
    """
    rules = {}
    
    if not rules_dir.exists():
        logger.warning(f"Pasta de regras não encontrada: {rules_dir}")
        return rules
    
    # Lista arquivos .txt ordenados
    txt_files = sorted(rules_dir.glob("*.txt"))
    
    for filepath in txt_files:
        # Ignora o arquivo de instrução da IA
        if filepath.name.lower() == "instrucaoia.txt":
            continue
        
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            
            # Extrai nome da categoria (primeira linha com #)
            category_name = None
            lines = content.split("\n")
            
            for line in lines:
                line = line.strip()
                if line.startswith("# "):
                    category_name = line[2:].strip()
                    break
            
            # Fallback: usa nome do arquivo
            if not category_name:
                name = filepath.stem
                # Remove prefixo numérico (ex: 01_ofertas -> ofertas)
                if name[:2].isdigit() and name[2] == "_":
                    name = name[3:]
                category_name = name.replace("_", " ").title()
            
            # Extrai regras (linhas com - ou *)
            rule_list = []
            for line in lines:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("- "):
                    rule_list.append(line[2:].strip())
                elif line.startswith("* "):
                    rule_list.append(line[2:].strip())
            
            if rule_list:
                rules[category_name] = rule_list
                logger.info(f"Regras carregadas: {category_name} ({len(rule_list)} itens)")
                
        except Exception as e:
            logger.error(f"Erro ao carregar {filepath.name}: {e}")
    
    logger.info(f"Total de categorias de regras: {len(rules)}")
    return rules


def load_ia_instruction(rules_dir: Path, logger: logging.Logger) -> str:
    """
    Carrega o prompt de instrução para a IA.
    
    Args:
        rules_dir: Caminho da pasta de regras.
        logger: Logger para registrar operações.
        
    Returns:
        Texto do prompt de instrução.
    """
    instruction_path = rules_dir / "InstrucaoIA.txt"
    
    if not instruction_path.exists():
        logger.warning("InstrucaoIA.txt não encontrado, usando prompt padrão")
        return "Analise o arquivo de marketing e verifique conformidade com as regras."
    
    with open(instruction_path, "r", encoding="utf-8") as f:
        instruction = f.read()
    
    logger.info(f"Instrução IA carregada: {instruction_path}")
    return instruction


def build_rules_section(rules: Dict[str, List[str]]) -> str:
    """
    Constrói seção de regras para injetar no prompt.
    
    Args:
        rules: Dicionário de regras por categoria.
        
    Returns:
        Texto formatado com todas as regras.
    """
    sections = []
    
    for category, rule_list in rules.items():
        rules_text = "\n".join(f"  - {rule}" for rule in rule_list)
        sections.append(f"**{category}:**\n{rules_text}")
    
    return "\n\n".join(sections)


def build_prompt(instruction: str, rules: Dict[str, List[str]]) -> str:
    """
    Constrói prompt final substituindo placeholders.
    
    Args:
        instruction: Texto de instrução da IA.
        rules: Dicionário de regras.
        
    Returns:
        Prompt completo pronto para enviar à IA.
    """
    rules_section = build_rules_section(rules)
    
    # Substitui placeholder
    prompt = instruction.replace("{{REGRAS_DINAMICAS}}", rules_section)
    
    return prompt


# ============================================================================
# CLIENTE DE IA
# ============================================================================
def get_ia_client(config: Dict[str, Any], logger: logging.Logger):
    """
    Inicializa cliente de IA baseado na configuração.
    
    Args:
        config: Configurações do projeto.
        logger: Logger para registrar operações.
        
    Returns:
        Tupla (client, model) ou (None, model) dependendo do modo.
    """
    auth_config = config.get("auth", {})
    mode = auth_config.get("mode", "api_key")
    ai_config = config.get("ai", {})
    model_name = ai_config.get("model_name", "gemini-2.0-flash-001")
    
    if mode == "vertex":
        # =================================================================
        # MODO PRODUÇÃO: Vertex AI
        # Descomente este bloco para usar em produção
        # =================================================================
        logger.info("Inicializando cliente Vertex AI (produção)")
        
        try:
            from google import genai
            from google.genai import types
            
            client = genai.Client(
                vertexai=True,
                project=auth_config.get("project_id", ""),
                location=auth_config.get("location", "us-central1")
            )
            
            logger.info(f"Vertex AI conectado: {auth_config.get('project_id')}")
            return client, model_name, "vertex"
            
        except ImportError:
            logger.error("Biblioteca google-genai não instalada. Use: pip install google-genai")
            raise
        
    else:
        # =================================================================
        # MODO TESTE: Google AI Studio (API Key)
        # Para testes locais sem custos de Vertex
        # =================================================================
        logger.info("Inicializando cliente Google AI Studio (teste)")
        
        # Tenta obter API key: 1º variável de ambiente, 2º config.yaml
        api_key = os.environ.get("GOOGLE_API_KEY") or auth_config.get("api_key", "")
        
        if not api_key:
            raise ValueError(
                "API Key não configurada. Opções:\n"
                "  1. Defina a variável de ambiente GOOGLE_API_KEY\n"
                "  2. Configure em config/config.yaml\n"
                "Obtenha sua key em: https://aistudio.google.com/apikey"
            )
        
        try:
            import google.generativeai as genai
            
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(model_name)
            
            logger.info(f"Google AI Studio configurado: {model_name}")
            return model, model_name, "api_key"
            
        except ImportError:
            logger.error("Biblioteca google-generativeai não instalada. Use: pip install google-generativeai")
            raise


# ============================================================================
# LEITURA DE ARQUIVOS
# ============================================================================
def read_file_content(file_path: Path, logger: logging.Logger) -> Tuple[Any, str]:
    """
    Lê conteúdo de arquivo como texto ou bytes.
    
    Simula o comportamento de anexar arquivo a um chat de IA.
    
    Args:
        file_path: Caminho do arquivo.
        logger: Logger para registrar operações.
        
    Returns:
        Tupla (conteúdo, tipo) onde tipo é "text" ou "binary".
    """
    ext = file_path.suffix.lower()
    
    # Extensões tratadas como texto puro
    text_extensions = {".txt", ".html", ".htm", ".csv", ".rtf"}
    
    if ext in text_extensions:
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            return content, "text"
        except Exception as e:
            logger.warning(f"Erro ao ler como texto, tentando binário: {e}")
    
    # Todos os outros formatos como binário
    with open(file_path, "rb") as f:
        content = f.read()
    
    return content, "binary"


def get_mime_type(ext: str) -> str:
    """
    Retorna MIME type para extensão de arquivo.
    
    Args:
        ext: Extensão do arquivo (com ponto).
        
    Returns:
        MIME type correspondente.
    """
    mime_map = {
        # Imagens
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        # Documentos
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls": "application/vnd.ms-excel",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".ppt": "application/vnd.ms-powerpoint",
        # E-mail
        ".msg": "application/vnd.ms-outlook",
        ".eml": "message/rfc822",
        # Texto
        ".txt": "text/plain",
        ".html": "text/html",
        ".htm": "text/html",
        ".csv": "text/csv",
        ".rtf": "application/rtf",
    }
    
    return mime_map.get(ext.lower(), "application/octet-stream")


# ============================================================================
# AVALIAÇÃO
# ============================================================================
def evaluate_file(
    file_path: Path,
    prompt: str,
    client: Any,
    model_name: str,
    mode: str,
    ai_config: Dict[str, Any],
    logger: logging.Logger
) -> Dict[str, Any]:
    """
    Avalia um único arquivo com a IA.
    
    Args:
        file_path: Caminho do arquivo a avaliar.
        prompt: Prompt com instruções e regras.
        client: Cliente de IA inicializado.
        model_name: Nome do modelo.
        mode: "vertex" ou "api_key".
        ai_config: Configurações de IA.
        logger: Logger para registrar operações.
        
    Returns:
        Dicionário com resultado da avaliação.
    """
    result = {
        "arquivo": file_path.name,
        "caminho": str(file_path),
        "data_avaliacao": datetime.now().isoformat(),
        "status": "pendente",
        "resposta_raw": None,
        "campos_extraidos": {},
        "erro": None
    }
    
    try:
        # Lê conteúdo do arquivo
        content, content_type = read_file_content(file_path, logger)
        ext = file_path.suffix.lower()
        mime_type = get_mime_type(ext)
        
        logger.debug(f"Arquivo lido: {file_path.name} ({content_type}, {mime_type})")
        
        # Monta conteúdo para envio
        if mode == "vertex":
            # Vertex AI com google-genai
            from google.genai import types
            
            if content_type == "text":
                parts = [
                    types.Part.from_text(text=content),
                    types.Part.from_text(text=prompt)
                ]
            else:
                parts = [
                    types.Part.from_bytes(data=content, mime_type=mime_type),
                    types.Part.from_text(text=prompt)
                ]
            
            contents = [types.Content(role="user", parts=parts)]
            
            cfg = types.GenerateContentConfig(
                temperature=ai_config.get("temperature", 0.1),
                max_output_tokens=ai_config.get("max_output_tokens", 4096),
                top_p=ai_config.get("top_p", 0.85)
            )
            
            response = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=cfg
            )
            
            raw_text = response.candidates[0].content.parts[0].text if response.candidates else ""
            
        else:
            # Google AI Studio com google-generativeai
            import google.generativeai as genai
            
            generation_config = genai.GenerationConfig(
                temperature=ai_config.get("temperature", 0.1),
                max_output_tokens=ai_config.get("max_output_tokens", 4096),
                top_p=ai_config.get("top_p", 0.85)
            )
            
            if content_type == "text":
                full_prompt = f"{prompt}\n\n--- CONTEÚDO DO ARQUIVO ---\n{content}"
                response = client.generate_content(
                    full_prompt,
                    generation_config=generation_config
                )
            else:
                # Para binários, criar arquivo temporário ou usar bytes direto
                # O google-generativeai suporta upload de arquivos
                import io
                
                # Cria objeto de arquivo em memória
                file_data = {
                    "mime_type": mime_type,
                    "data": content
                }
                
                response = client.generate_content(
                    [prompt, file_data],
                    generation_config=generation_config
                )
            
            raw_text = response.text if response else ""
        
        result["resposta_raw"] = raw_text
        result["campos_extraidos"] = parse_ia_response(raw_text)
        result["status"] = "sucesso"
        
        logger.info(f"Avaliação concluída: {file_path.name} -> {result['campos_extraidos'].get('RESULTADO', 'N/A')}")
        
    except Exception as e:
        result["status"] = "erro"
        result["erro"] = str(e)
        logger.error(f"Erro na avaliação de {file_path.name}: {e}")
    
    return result


def evaluate_batch(
    files: List[Dict[str, Any]],
    prompt: str,
    client: Any,
    model_name: str,
    mode: str,
    config: Dict[str, Any],
    logger: logging.Logger
) -> List[Dict[str, Any]]:
    """
    Avalia um lote de arquivos.
    
    Args:
        files: Lista de metadados dos arquivos.
        prompt: Prompt com instruções e regras.
        client: Cliente de IA.
        model_name: Nome do modelo.
        mode: Modo de autenticação.
        config: Configurações completas.
        logger: Logger.
        
    Returns:
        Lista de resultados de avaliação.
    """
    results = []
    ai_config = config.get("ai", {})
    retry_attempts = config.get("processing", {}).get("retry_attempts", 3)
    retry_delay = config.get("processing", {}).get("retry_delay_seconds", 5)
    
    total = len(files)
    
    for i, file_info in enumerate(files, 1):
        # Só processa arquivos copiados com sucesso
        if file_info.get("status_copia") != "sucesso":
            logger.warning(f"[{i}/{total}] Pulando (erro na cópia): {file_info['nome_original']}")
            continue
        
        file_path = Path(file_info["caminho_destino"])
        
        if not file_path.exists():
            logger.error(f"[{i}/{total}] Arquivo não encontrado: {file_path}")
            continue
        
        logger.info(f"[{i}/{total}] Avaliando: {file_path.name}")
        
        # Retry logic
        for attempt in range(retry_attempts):
            result = evaluate_file(
                file_path, prompt, client, model_name, mode, ai_config, logger
            )
            
            if result["status"] == "sucesso":
                break
            
            if attempt < retry_attempts - 1:
                logger.warning(f"Tentativa {attempt + 1} falhou, aguardando {retry_delay}s...")
                time.sleep(retry_delay)
        
        # Adiciona metadados do arquivo original
        result["hash_sha256"] = file_info.get("hash_sha256")
        result["pasta_origem"] = file_info.get("pasta_origem")
        results.append(result)
        
        # Pequena pausa entre chamadas (evita rate limit)
        if i < total:
            time.sleep(0.5)
    
    return results


# ============================================================================
# PARSING DE RESPOSTA
# ============================================================================
def parse_ia_response(raw_text: str) -> Dict[str, str]:
    """
    Extrai campos estruturados da resposta da IA.
    
    Args:
        raw_text: Resposta bruta da IA.
        
    Returns:
        Dicionário com campos extraídos.
    """
    fields = [
        "ARQUIVO",
        "CONTEUDO_IDENTIFICADO",
        "VIOLACOES_ENCONTRADAS",
        "AVALIACAO",
        "RESULTADO",
        "JUSTIFICATIVA",
        "RECOMENDACOES"
    ]
    
    extracted = {}
    
    for field in fields:
        # Padrão: CAMPO: valor;
        import re
        pattern = rf"{field}\s*:\s*([^;]+)"
        match = re.search(pattern, raw_text, re.IGNORECASE)
        
        if match:
            value = match.group(1).strip()
            # Remove colchetes se houver
            value = re.sub(r"^\[|\]$", "", value).strip()
            extracted[field] = value
        else:
            extracted[field] = ""
    
    return extracted


# ============================================================================
# PERSISTÊNCIA
# ============================================================================
def save_results(results: List[Dict[str, Any]], config: Dict[str, Any], logger: logging.Logger) -> Path:
    """
    Salva resultados em arquivo JSON na pasta TEMP.
    
    Args:
        results: Lista de resultados de avaliação.
        config: Configurações do projeto.
        logger: Logger.
        
    Returns:
        Caminho do arquivo JSON salvo.
    """
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%d%m%Y_%H%M%S")
    filename = f"resultados_{timestamp}.json"
    filepath = TEMP_DIR / filename
    
    output = {
        "metadata": {
            "data_execucao": datetime.now().isoformat(),
            "total_arquivos": len(results),
            "sucesso": sum(1 for r in results if r["status"] == "sucesso"),
            "erros": sum(1 for r in results if r["status"] == "erro")
        },
        "resultados": results
    }
    
    # Remove resposta raw se não configurado para salvar
    if not config.get("control", {}).get("save_raw_response", True):
        for r in output["resultados"]:
            r["resposta_raw"] = "[não salvo]"
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Resultados salvos: {filepath}")
    return filepath


# ============================================================================
# MAIN
# ============================================================================
def main() -> int:
    """
    Função principal do script de avaliação.
    
    Returns:
        Código de saída (0 = sucesso, 1 = erro).
    """
    print("\n" + "=" * 60)
    print("ConforME - Avaliação por IA")
    print("=" * 60 + "\n")
    
    # Parse argumentos
    parser = argparse.ArgumentParser(description="Avaliação de compliance por IA")
    parser.add_argument(
        "--manifest", "-m",
        type=str,
        required=True,
        help="Caminho do arquivo manifest.json gerado pelo captura_arquivos.py"
    )
    args = parser.parse_args()
    
    try:
        # Carrega configurações
        config = load_config()
        logger = setup_logging(config)
        
        logger.info("Iniciando processo de avaliação por IA")
        
        # Carrega manifest
        manifest_path = Path(args.manifest)
        if not manifest_path.exists():
            raise FileNotFoundError(f"Manifest não encontrado: {manifest_path}")
        
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        
        files = manifest.get("arquivos", [])
        logger.info(f"Manifest carregado: {len(files)} arquivos")
        
        # Carrega regras
        logger.info("-" * 40)
        logger.info("ETAPA 1: Carregamento de regras")
        logger.info("-" * 40)
        
        rules = load_compliance_rules(RULES_DIR, logger)
        instruction = load_ia_instruction(RULES_DIR, logger)
        prompt = build_prompt(instruction, rules)
        
        logger.debug(f"Prompt construído ({len(prompt)} caracteres)")
        
        # Inicializa cliente IA
        logger.info("-" * 40)
        logger.info("ETAPA 2: Conexão com IA")
        logger.info("-" * 40)
        
        client, model_name, mode = get_ia_client(config, logger)
        
        # Avalia arquivos
        logger.info("-" * 40)
        logger.info("ETAPA 3: Avaliação de arquivos")
        logger.info("-" * 40)
        
        results = evaluate_batch(
            files, prompt, client, model_name, mode, config, logger
        )
        
        # Salva resultados
        logger.info("-" * 40)
        logger.info("ETAPA 4: Salvando resultados")
        logger.info("-" * 40)
        
        json_path = save_results(results, config, logger)
        
        # Resumo final
        success_count = sum(1 for r in results if r["status"] == "sucesso")
        approved = sum(1 for r in results if r.get("campos_extraidos", {}).get("RESULTADO", "").upper() == "APROVADO")
        rejected = sum(1 for r in results if r.get("campos_extraidos", {}).get("RESULTADO", "").upper() == "REPROVADO")
        
        logger.info("=" * 40)
        logger.info("AVALIAÇÃO CONCLUÍDA")
        logger.info("=" * 40)
        logger.info(f"Total avaliado: {success_count}/{len(results)}")
        logger.info(f"Aprovados: {approved}")
        logger.info(f"Reprovados: {rejected}")
        logger.info(f"Inconclusivos: {success_count - approved - rejected}")
        
        print(f"\n✅ Avaliação concluída!")
        print(f"   Resultados salvos em: {json_path}")
        print(f"   Execute agora: python exportacao.py --input \"{json_path}\"\n")
        
        return 0
        
    except FileNotFoundError as e:
        print(f"\n❌ Arquivo não encontrado: {e}")
        return 1
    except ValueError as e:
        print(f"\n❌ Erro de configuração: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ Erro inesperado: {e}")
        logging.exception("Erro fatal na execução")
        return 1


if __name__ == "__main__":
    sys.exit(main())

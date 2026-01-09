#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ConforME - Avaliacao por IA (Vertex AI)
=======================================

Script 02/03 da automacao de compliance de marketing.

Responsabilidades:
- Ler manifest.json gerado pelo captura_arquivos.py
- Carregar regras de compliance dos arquivos .txt
- Construir prompt dinamico com regras
- Enviar arquivos para Vertex AI (Gemini)
- Parsear resposta estruturada
- Salvar resultados em JSON intermediario

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
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

# ============================================================================
# CONFIGURACAO DE PATHS
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
        config: Dicionario de configuracoes do YAML.
        
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
# CONFIGURACAO
# ============================================================================
def load_config() -> Dict[str, Any]:
    """
    Carrega configuracoes do arquivo config.yaml.
    
    Returns:
        Dicionario com configuracoes.
    """
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Arquivo de configuracao nao encontrado: {CONFIG_PATH}")
    
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
        logger: Logger para registrar operacoes.
        
    Returns:
        Dicionario {nome_categoria: [lista_de_regras]}.
    """
    rules = {}
    
    if not rules_dir.exists():
        logger.warning(f"Pasta de regras nao encontrada: {rules_dir}")
        return rules
    
    # Lista arquivos .txt ordenados
    txt_files = sorted(rules_dir.glob("*.txt"))
    
    for filepath in txt_files:
        # Ignora o arquivo de instrucao da IA
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
                # Remove prefixo numerico (ex: 01_ofertas -> ofertas)
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
    Carrega o prompt de instrucao para a IA.
    
    Args:
        rules_dir: Caminho da pasta de regras.
        logger: Logger para registrar operacoes.
        
    Returns:
        Texto do prompt de instrucao.
    """
    instruction_path = rules_dir / "InstrucaoIA.txt"
    
    if not instruction_path.exists():
        logger.warning("InstrucaoIA.txt nao encontrado, usando prompt padrao")
        return "Analise o arquivo de marketing e verifique conformidade com as regras."
    
    with open(instruction_path, "r", encoding="utf-8") as f:
        instruction = f.read()
    
    logger.info(f"Instrucao IA carregada: {instruction_path}")
    return instruction


def build_rules_section(rules: Dict[str, List[str]]) -> str:
    """
    Constroi secao de regras para injetar no prompt.
    
    Args:
        rules: Dicionario de regras por categoria.
        
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
    Constroi prompt final substituindo placeholders.
    
    Args:
        instruction: Texto de instrucao da IA.
        rules: Dicionario de regras.
        
    Returns:
        Prompt completo pronto para enviar a IA.
    """
    rules_section = build_rules_section(rules)
    
    # Substitui placeholder
    prompt = instruction.replace("{{REGRAS_DINAMICAS}}", rules_section)
    
    return prompt


# ============================================================================
# CLIENTE VERTEX AI
# ============================================================================
def get_vertex_client(config: Dict[str, Any], logger: logging.Logger):
    """
    Inicializa cliente Vertex AI.
    
    Requer Application Default Credentials (ADC) configurado:
    gcloud auth application-default login
    
    Args:
        config: Configuracoes do projeto.
        logger: Logger para registrar operacoes.
        
    Returns:
        Tupla (client, model_name).
    """
    auth_config = config.get("auth", {})
    ai_config = config.get("ai", {})
    
    project_id = auth_config.get("project_id", "")
    location = auth_config.get("location", "us-central1")
    model_name = ai_config.get("model_name", "gemini-2.5-flash")
    
    if not project_id:
        raise ValueError(
            "project_id nao configurado. "
            "Configure em config/config.yaml"
        )
    
    logger.info("Inicializando cliente Vertex AI")
    logger.info(f"Projeto: {project_id}")
    logger.info(f"Location: {location}")
    logger.info(f"Modelo: {model_name}")
    
    try:
        from google import genai
        
        client = genai.Client(
            vertexai=True,
            project=project_id,
            location=location
        )
        
        logger.info("Vertex AI conectado com sucesso")
        return client, model_name
        
    except ImportError:
        logger.error("Biblioteca google-genai nao instalada. Use: pip install google-genai")
        raise


def build_generation_config(ai_config: Dict[str, Any]):
    """
    Constroi configuracao de geracao para Vertex AI.
    
    Args:
        ai_config: Configuracoes de IA do config.yaml.
        
    Returns:
        Objeto GenerateContentConfig.
    """
    from google.genai import types
    
    config_params = {
        "temperature": ai_config.get("temperature", 0.1),
        "max_output_tokens": ai_config.get("max_output_tokens", 4096),
        "top_p": ai_config.get("top_p", 0.85),
        "top_k": ai_config.get("top_k", 40),
    }
    
    stop_sequences = ai_config.get("stop_sequences", [])
    if stop_sequences:
        config_params["stop_sequences"] = stop_sequences
    
    # Seed para reproducibilidade
    seed = ai_config.get("seed")
    if seed is not None:
        config_params["seed"] = seed
    
    return types.GenerateContentConfig(**config_params)


# ============================================================================
# LEITURA DE ARQUIVOS
# ============================================================================
def read_file_content(file_path: Path, logger: logging.Logger) -> Tuple[Any, str]:
    """
    Le conteudo de arquivo como texto ou bytes.
    
    Args:
        file_path: Caminho do arquivo.
        logger: Logger para registrar operacoes.
        
    Returns:
        Tupla (conteudo, tipo) onde tipo e "text" ou "binary".
    """
    ext = file_path.suffix.lower()
    
    # Extensoes tratadas como texto puro
    text_extensions = {".txt", ".html", ".htm", ".csv", ".rtf"}
    
    if ext in text_extensions:
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            return content, "text"
        except Exception as e:
            logger.warning(f"Erro ao ler como texto, tentando binario: {e}")
    
    # Todos os outros formatos como binario
    with open(file_path, "rb") as f:
        content = f.read()
    
    return content, "binary"


def get_mime_type(ext: str) -> str:
    """
    Retorna MIME type para extensao de arquivo.
    
    Args:
        ext: Extensao do arquivo (com ponto).
        
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
# AVALIACAO
# ============================================================================
def evaluate_file(
    file_path: Path,
    prompt: str,
    client: Any,
    model_name: str,
    ai_config: Dict[str, Any],
    logger: logging.Logger
) -> Dict[str, Any]:
    """
    Avalia um unico arquivo com Vertex AI.
    
    Args:
        file_path: Caminho do arquivo a avaliar.
        prompt: Prompt com instrucoes e regras.
        client: Cliente Vertex AI.
        model_name: Nome do modelo.
        ai_config: Configuracoes de IA.
        logger: Logger para registrar operacoes.
        
    Returns:
        Dicionario com resultado da avaliacao.
    """
    from google.genai import types
    
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
        # Le conteudo do arquivo
        content, content_type = read_file_content(file_path, logger)
        ext = file_path.suffix.lower()
        mime_type = get_mime_type(ext)
        
        logger.debug(f"Arquivo lido: {file_path.name} ({content_type}, {mime_type})")
        
        # Monta conteudo para envio
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
        generation_config = build_generation_config(ai_config)
        
        response = client.models.generate_content(
            model=model_name,
            contents=contents,
            config=generation_config
        )
        
        raw_text = response.candidates[0].content.parts[0].text if response.candidates else ""
        
        result["resposta_raw"] = raw_text
        result["campos_extraidos"] = parse_ia_response(raw_text)
        result["status"] = "sucesso"
        
        logger.info(f"Avaliacao concluida: {file_path.name} -> {result['campos_extraidos'].get('RESULTADO', 'N/A')}")
        
    except Exception as e:
        result["status"] = "erro"
        result["erro"] = str(e)
        logger.error(f"Erro na avaliacao de {file_path.name}: {e}")
    
    return result


def evaluate_batch(
    files: List[Dict[str, Any]],
    prompt: str,
    client: Any,
    model_name: str,
    config: Dict[str, Any],
    logger: logging.Logger
) -> List[Dict[str, Any]]:
    """
    Avalia um lote de arquivos.
    
    Args:
        files: Lista de metadados dos arquivos.
        prompt: Prompt com instrucoes e regras.
        client: Cliente Vertex AI.
        model_name: Nome do modelo.
        config: Configuracoes completas.
        logger: Logger.
        
    Returns:
        Lista de resultados de avaliacao.
    """
    results = []
    ai_config = config.get("ai", {})
    processing_config = config.get("processing", {})
    
    retry_attempts = processing_config.get("retry_attempts", 3)
    retry_delay = processing_config.get("retry_delay_seconds", 10)
    delay_between_calls = processing_config.get("delay_between_calls", 1.0)
    
    total = len(files)
    
    for i, file_info in enumerate(files, 1):
        # So processa arquivos copiados com sucesso
        if file_info.get("status_copia") != "sucesso":
            logger.warning(f"[{i}/{total}] Pulando (erro na copia): {file_info['nome_original']}")
            continue
        
        file_path = Path(file_info["caminho_destino"])
        
        if not file_path.exists():
            logger.error(f"[{i}/{total}] Arquivo nao encontrado: {file_path}")
            continue
        
        logger.info(f"[{i}/{total}] Avaliando: {file_path.name}")
        
        # Retry logic
        for attempt in range(retry_attempts):
            result = evaluate_file(
                file_path, prompt, client, model_name, ai_config, logger
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
        
        # Pausa entre chamadas (evita rate limit)
        if i < total:
            time.sleep(delay_between_calls)
    
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
        Dicionario com campos extraidos.
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
        # Padrao: CAMPO: valor;
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
# PERSISTENCIA
# ============================================================================
def save_results(results: List[Dict[str, Any]], config: Dict[str, Any], logger: logging.Logger) -> Path:
    """
    Salva resultados em arquivo JSON na pasta TEMP.
    
    Args:
        results: Lista de resultados de avaliacao.
        config: Configuracoes do projeto.
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
    
    # Remove resposta raw se nao configurado para salvar
    if not config.get("control", {}).get("save_raw_response", True):
        for r in output["resultados"]:
            r["resposta_raw"] = "[nao salvo]"
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Resultados salvos: {filepath}")
    return filepath


# ============================================================================
# MAIN
# ============================================================================
def main() -> int:
    """
    Funcao principal do script de avaliacao.
    
    Returns:
        Codigo de saida (0 = sucesso, 1 = erro).
    """
    print("\n" + "=" * 60)
    print("ConforME - Avaliacao por IA (Vertex AI)")
    print("=" * 60 + "\n")
    
    # Parse argumentos
    parser = argparse.ArgumentParser(description="Avaliacao de compliance por IA")
    parser.add_argument(
        "--manifest", "-m",
        type=str,
        required=True,
        help="Caminho do arquivo manifest.json gerado pelo captura_arquivos.py"
    )
    args = parser.parse_args()
    
    try:
        # Carrega configuracoes
        config = load_config()
        logger = setup_logging(config)
        
        logger.info("Iniciando processo de avaliacao por IA")
        
        # Carrega manifest
        manifest_path = Path(args.manifest)
        if not manifest_path.exists():
            raise FileNotFoundError(f"Manifest nao encontrado: {manifest_path}")
        
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
        
        logger.debug(f"Prompt construido ({len(prompt)} caracteres)")
        
        # Inicializa cliente Vertex AI
        logger.info("-" * 40)
        logger.info("ETAPA 2: Conexao com Vertex AI")
        logger.info("-" * 40)
        
        client, model_name = get_vertex_client(config, logger)
        
        # Avalia arquivos
        logger.info("-" * 40)
        logger.info("ETAPA 3: Avaliacao de arquivos")
        logger.info("-" * 40)
        
        results = evaluate_batch(
            files, prompt, client, model_name, config, logger
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
        logger.info("AVALIACAO CONCLUIDA")
        logger.info("=" * 40)
        logger.info(f"Total avaliado: {success_count}/{len(results)}")
        logger.info(f"Aprovados: {approved}")
        logger.info(f"Reprovados: {rejected}")
        logger.info(f"Inconclusivos: {success_count - approved - rejected}")
        
        print(f"\n[OK] Avaliacao concluida!")
        print(f"   Resultados salvos em: {json_path}")
        print(f"   Execute agora: python exportacao.py --input \"{json_path}\"\n")
        
        return 0
        
    except FileNotFoundError as e:
        print(f"\n[ERRO] Arquivo nao encontrado: {e}")
        return 1
    except ValueError as e:
        print(f"\n[ERRO] Erro de configuracao: {e}")
        return 1
    except Exception as e:
        print(f"\n[ERRO] Erro inesperado: {e}")
        logging.exception("Erro fatal na execucao")
        return 1


if __name__ == "__main__":
    sys.exit(main())

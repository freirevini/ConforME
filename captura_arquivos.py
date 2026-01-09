#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ConforME - Captura de Arquivos
==============================

Script 01/03 da automaÃ§Ã£o de compliance de marketing.

Responsabilidades:
- Percorrer Ã¡rvore de pastas em busca de arquivos de marketing
- Filtrar por extensÃµes aceitas
- Copiar arquivos para pasta de processamento (ArquivosHouseDDMMYYYY)
- Calcular hash SHA256 para rastreabilidade
- Gerar manifest.json com metadados dos arquivos

Autor: ConforME Team
Data: Janeiro 2026
"""

import os
import sys
import json
import yaml
import shutil
import hashlib
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional


# ============================================================================
# CONFIGURAÃ‡ÃƒO DE PATHS
# ============================================================================
BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config" / "config.yaml"
LOGS_DIR = BASE_DIR / "logs"


# ============================================================================
# LOGGING
# ============================================================================
def setup_logging(config: Dict[str, Any]) -> logging.Logger:
    """
    Configura o sistema de logging.
    
    Args:
        config: DicionÃ¡rio de configuraÃ§Ãµes do YAML.
        
    Returns:
        Logger configurado.
    """
    log_config = config.get("logging", {})
    log_level = getattr(logging, log_config.get("level", "INFO").upper())
    log_format = log_config.get("format", "%(asctime)s | %(levelname)-8s | %(message)s")
    
    # Cria pasta de logs se nÃ£o existir
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Configura handlers
    handlers = [
        logging.StreamHandler(sys.stdout),  # Console
        logging.FileHandler(
            LOGS_DIR / "captura_arquivos.log",
            encoding="utf-8"
        )
    ]
    
    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=handlers
    )
    
    return logging.getLogger("captura_arquivos")


# ============================================================================
# CONFIGURAÃ‡ÃƒO
# ============================================================================
def load_config() -> Dict[str, Any]:
    """
    Carrega configuraÃ§Ãµes do arquivo config.yaml.
    
    Returns:
        DicionÃ¡rio com configuraÃ§Ãµes.
        
    Raises:
        FileNotFoundError: Se config.yaml nÃ£o existir.
        yaml.YAMLError: Se YAML for invÃ¡lido.
    """
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Arquivo de configuraÃ§Ã£o nÃ£o encontrado: {CONFIG_PATH}")
    
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    
    return config


# ============================================================================
# HASH DE ARQUIVOS
# ============================================================================
def calculate_file_hash(file_path: Path) -> str:
    """
    Calcula hash SHA256 de um arquivo.
    
    Args:
        file_path: Caminho do arquivo.
        
    Returns:
        Hash SHA256 em hexadecimal (64 caracteres).
    """
    sha256_hash = hashlib.sha256()
    
    with open(file_path, "rb") as f:
        # LÃª em blocos para nÃ£o sobrecarregar memÃ³ria
        for byte_block in iter(lambda: f.read(65536), b""):
            sha256_hash.update(byte_block)
    
    return sha256_hash.hexdigest()


# ============================================================================
# VARREDURA DE ARQUIVOS
# ============================================================================
def scan_source_folder(
    source_folder: Path,
    accepted_extensions: List[str],
    logger: logging.Logger
) -> List[Dict[str, Any]]:
    """
    Percorre pasta de origem e lista arquivos aceitos.
    
    Args:
        source_folder: Pasta raiz para varredura.
        accepted_extensions: Lista de extensÃµes aceitas (com ponto).
        logger: Logger para registrar operaÃ§Ãµes.
        
    Returns:
        Lista de dicionÃ¡rios com metadados dos arquivos encontrados.
    """
    files_found = []
    accepted_set = set(ext.lower() for ext in accepted_extensions)
    
    logger.info(f"Iniciando varredura em: {source_folder}")
    logger.info(f"ExtensÃµes aceitas: {', '.join(accepted_extensions)}")
    
    if not source_folder.exists():
        logger.error(f"Pasta de origem nÃ£o existe: {source_folder}")
        return files_found
    
    # Percorre Ã¡rvore de diretÃ³rios
    for root, dirs, files in os.walk(source_folder):
        root_path = Path(root)
        
        for filename in files:
            file_path = root_path / filename
            ext = file_path.suffix.lower()
            
            # Verifica extensÃ£o
            if ext not in accepted_set:
                logger.debug(f"Ignorando (extensÃ£o nÃ£o aceita): {filename}")
                continue
            
            try:
                # Coleta metadados
                stat = file_path.stat()
                
                file_info = {
                    "nome_original": filename,
                    "caminho_completo": str(file_path),
                    "pasta_origem": str(root_path),
                    "extensao": ext,
                    "tamanho_bytes": stat.st_size,
                    "data_modificacao": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "hash_sha256": None  # SerÃ¡ preenchido apÃ³s cÃ³pia
                }
                
                files_found.append(file_info)
                logger.debug(f"Arquivo encontrado: {filename}")
                
            except Exception as e:
                logger.error(f"Erro ao processar {filename}: {e}")
    
    logger.info(f"Total de arquivos encontrados: {len(files_found)}")
    return files_found


# ============================================================================
# CÃ“PIA DE ARQUIVOS
# ============================================================================
def copy_files_to_house(
    files: List[Dict[str, Any]],
    base_dir: Path,
    use_hash: bool,
    logger: logging.Logger
) -> tuple[Path, List[Dict[str, Any]]]:
    """
    Copia arquivos para pasta ArquivosHouseDDMMYYYY.
    
    Args:
        files: Lista de metadados dos arquivos.
        base_dir: DiretÃ³rio base do projeto.
        use_hash: Se True, calcula hash SHA256.
        logger: Logger para registrar operaÃ§Ãµes.
        
    Returns:
        Tupla (caminho da pasta house, lista de arquivos com paths atualizados).
    """
    # Cria nome da pasta com data atual
    date_suffix = datetime.now().strftime("%d%m%Y")
    house_folder = base_dir / f"ArquivosHouse{date_suffix}"
    
    # Cria pasta (se jÃ¡ existir, adiciona timestamp)
    if house_folder.exists():
        timestamp = datetime.now().strftime("%H%M%S")
        house_folder = base_dir / f"ArquivosHouse{date_suffix}_{timestamp}"
    
    house_folder.mkdir(parents=True, exist_ok=True)
    logger.info(f"Pasta de destino criada: {house_folder}")
    
    # Copia cada arquivo
    copied_files = []
    
    for i, file_info in enumerate(files, 1):
        source_path = Path(file_info["caminho_completo"])
        
        # Trata duplicatas de nome
        dest_filename = file_info["nome_original"]
        dest_path = house_folder / dest_filename
        
        counter = 1
        while dest_path.exists():
            name_stem = source_path.stem
            dest_filename = f"{name_stem}_{counter}{source_path.suffix}"
            dest_path = house_folder / dest_filename
            counter += 1
        
        try:
            # Copia arquivo
            shutil.copy2(source_path, dest_path)
            
            # Calcula hash se habilitado
            if use_hash:
                file_info["hash_sha256"] = calculate_file_hash(dest_path)
            
            # Atualiza caminhos
            file_info["nome_destino"] = dest_filename
            file_info["caminho_destino"] = str(dest_path)
            file_info["status_copia"] = "sucesso"
            
            copied_files.append(file_info)
            logger.info(f"[{i}/{len(files)}] Copiado: {dest_filename}")
            
        except Exception as e:
            file_info["status_copia"] = f"erro: {str(e)}"
            file_info["caminho_destino"] = None
            copied_files.append(file_info)
            logger.error(f"[{i}/{len(files)}] Erro ao copiar {source_path.name}: {e}")
    
    success_count = sum(1 for f in copied_files if f["status_copia"] == "sucesso")
    logger.info(f"CÃ³pia concluÃ­da: {success_count}/{len(files)} arquivos")
    
    return house_folder, copied_files


# ============================================================================
# MANIFEST
# ============================================================================
def generate_manifest(
    house_folder: Path,
    files: List[Dict[str, Any]],
    config: Dict[str, Any],
    logger: logging.Logger
) -> Path:
    """
    Gera arquivo manifest.json com metadados da execuÃ§Ã£o.
    
    Args:
        house_folder: Pasta onde os arquivos foram copiados.
        files: Lista de metadados dos arquivos.
        config: ConfiguraÃ§Ãµes do projeto.
        logger: Logger para registrar operaÃ§Ãµes.
        
    Returns:
        Caminho do arquivo manifest.json gerado.
    """
    manifest = {
        "execucao": {
            "data_hora": datetime.now().isoformat(),
            "pasta_origem": config["paths"]["source_folder"],
            "pasta_destino": str(house_folder),
            "total_arquivos": len(files),
            "arquivos_sucesso": sum(1 for f in files if f.get("status_copia") == "sucesso"),
            "arquivos_erro": sum(1 for f in files if f.get("status_copia", "").startswith("erro")),
        },
        "configuracao": {
            "extensoes_aceitas": config["accepted_extensions"],
            "use_hash": config["control"]["use_hash"]
        },
        "arquivos": files
    }
    
    manifest_path = house_folder / "manifest.json"
    
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Manifest gerado: {manifest_path}")
    return manifest_path


# ============================================================================
# MAIN
# ============================================================================
def main() -> int:
    """
    FunÃ§Ã£o principal do script de captura.
    
    Returns:
        CÃ³digo de saÃ­da (0 = sucesso, 1 = erro).
    """
    print("\n" + "=" * 60)
    print("ConforME - Captura de Arquivos")
    print("=" * 60 + "\n")
    
    try:
        # Carrega configuraÃ§Ãµes
        config = load_config()
        logger = setup_logging(config)
        
        logger.info("Iniciando processo de captura de arquivos")
        
        # Extrai configuraÃ§Ãµes
        source_folder = Path(config["paths"]["source_folder"])
        accepted_extensions = config["accepted_extensions"]
        use_hash = config["control"]["use_hash"]
        
        # 1. Varredura
        logger.info("-" * 40)
        logger.info("ETAPA 1: Varredura de arquivos")
        logger.info("-" * 40)
        
        files = scan_source_folder(source_folder, accepted_extensions, logger)
        
        if not files:
            logger.warning("Nenhum arquivo encontrado para processar.")
            return 0
        
        # 2. CÃ³pia
        logger.info("-" * 40)
        logger.info("ETAPA 2: CÃ³pia de arquivos")
        logger.info("-" * 40)
        
        house_folder, copied_files = copy_files_to_house(
            files, BASE_DIR, use_hash, logger
        )
        
        # 3. Manifest
        logger.info("-" * 40)
        logger.info("ETAPA 3: GeraÃ§Ã£o do manifest")
        logger.info("-" * 40)
        
        manifest_path = generate_manifest(house_folder, copied_files, config, logger)
        
        # Resumo final
        logger.info("=" * 40)
        logger.info("CAPTURA CONCLUÃDA")
        logger.info("=" * 40)
        logger.info(f"Pasta de destino: {house_folder}")
        logger.info(f"Manifest: {manifest_path}")
        logger.info(f"Total processado: {len(copied_files)} arquivos")
        
        print(f"\nâœ… Captura concluÃ­da! Arquivos em: {house_folder}")
        print(f"   Execute agora: python avaliacao_ia.py --manifest \"{manifest_path}\"\n")
        
        return 0
        
    except FileNotFoundError as e:
        print(f"\nâŒ Erro de configuraÃ§Ã£o: {e}")
        return 1
    except Exception as e:
        print(f"\nâŒ Erro inesperado: {e}")
        logging.exception("Erro fatal na execuÃ§Ã£o")
        return 1


if __name__ == "__main__":
    sys.exit(main())


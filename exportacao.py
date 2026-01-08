#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ConforME - Exportação para Excel
================================

Script 03/03 da automação de compliance de marketing.

Responsabilidades:
- Ler resultados JSON gerados pelo avaliacao_ia.py
- Gerar planilha Excel independente (por execução)
- Atualizar planilha cumulativa (histórico master)
- Incluir todas as colunas obrigatórias

Autor: ConforME Team
Data: Janeiro 2026
"""

import os
import sys
import json
import yaml
import logging
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional

# Importação condicional do openpyxl (único uso permitido: geração de Excel)
try:
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from openpyxl.utils import get_column_letter
    EXCEL_SUPPORT = True
except ImportError:
    EXCEL_SUPPORT = False


# ============================================================================
# CONFIGURAÇÃO DE PATHS
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
            LOGS_DIR / "exportacao.log",
            encoding="utf-8"
        )
    ]
    
    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=handlers
    )
    
    return logging.getLogger("exportacao")


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
# CARREGAMENTO DE RESULTADOS
# ============================================================================
def load_results(json_path: Path, logger: logging.Logger) -> Dict[str, Any]:
    """
    Carrega resultados do arquivo JSON.
    
    Args:
        json_path: Caminho do arquivo JSON.
        logger: Logger.
        
    Returns:
        Dicionário com resultados.
    """
    if not json_path.exists():
        raise FileNotFoundError(f"Arquivo de resultados não encontrado: {json_path}")
    
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    logger.info(f"Resultados carregados: {json_path}")
    logger.info(f"Total de registros: {len(data.get('resultados', []))}")
    
    return data


# ============================================================================
# PREPARAÇÃO DE DADOS
# ============================================================================
def prepare_excel_data(results: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Prepara dados dos resultados para formato tabular do Excel.
    
    Args:
        results: Dicionário com resultados da avaliação.
        
    Returns:
        Lista de dicionários prontos para Excel.
    """
    rows = []
    
    for item in results.get("resultados", []):
        campos = item.get("campos_extraidos", {})
        
        row = {
            "Data": datetime.fromisoformat(item.get("data_avaliacao", "")).strftime("%d/%m/%Y %H:%M")
                   if item.get("data_avaliacao") else "",
            "Nome do Arquivo": item.get("arquivo", ""),
            "Caminho Pasta": item.get("pasta_origem", ""),
            "Hash SHA256": item.get("hash_sha256", ""),
            "Conteúdo Identificado": campos.get("CONTEUDO_IDENTIFICADO", ""),
            "Violações Encontradas": campos.get("VIOLACOES_ENCONTRADAS", ""),
            "Avaliação": campos.get("AVALIACAO", ""),
            "Resultado": campos.get("RESULTADO", ""),
            "Justificativa": campos.get("JUSTIFICATIVA", ""),
            "Recomendações": campos.get("RECOMENDACOES", ""),
            "Status Processamento": item.get("status", ""),
            "Erro": item.get("erro", "") or "",
            "Parecer Final Humano": ""  # Sempre vazio inicialmente
        }
        
        rows.append(row)
    
    return rows


# ============================================================================
# ESTILOS DO EXCEL
# ============================================================================
def get_header_style():
    """Retorna estilo para cabeçalho do Excel."""
    return {
        "font": Font(bold=True, color="FFFFFF", size=11),
        "fill": PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid"),
        "alignment": Alignment(horizontal="center", vertical="center", wrap_text=True),
        "border": Border(
            left=Side(style="thin"),
            right=Side(style="thin"),
            top=Side(style="thin"),
            bottom=Side(style="thin")
        )
    }


def get_result_fill(result: str) -> PatternFill:
    """
    Retorna cor de fundo baseada no resultado.
    
    Args:
        result: Resultado da avaliação.
        
    Returns:
        PatternFill com cor correspondente.
    """
    result_upper = result.upper().strip() if result else ""
    
    colors = {
        "APROVADO": "C6EFCE",      # Verde claro
        "REPROVADO": "FFC7CE",     # Vermelho claro
        "INCONCLUSIVO": "FFEB9C"   # Amarelo claro
    }
    
    color = colors.get(result_upper, "FFFFFF")
    return PatternFill(start_color=color, end_color=color, fill_type="solid")


def get_cell_style():
    """Retorna estilo para células de dados."""
    return {
        "alignment": Alignment(vertical="top", wrap_text=True),
        "border": Border(
            left=Side(style="thin"),
            right=Side(style="thin"),
            top=Side(style="thin"),
            bottom=Side(style="thin")
        )
    }


# ============================================================================
# GERAÇÃO DE EXCEL
# ============================================================================
def create_excel_workbook(data: List[Dict[str, Any]], logger: logging.Logger) -> Workbook:
    """
    Cria workbook do Excel com os dados formatados.
    
    Args:
        data: Lista de dicionários com dados.
        logger: Logger.
        
    Returns:
        Workbook pronto para salvar.
    """
    if not data:
        raise ValueError("Nenhum dado para exportar")
    
    wb = Workbook()
    ws = wb.active
    ws.title = "Resultados Compliance"
    
    # Colunas
    columns = list(data[0].keys())
    header_style = get_header_style()
    cell_style = get_cell_style()
    
    # Define larguras customizadas
    column_widths = {
        "Data": 18,
        "Nome do Arquivo": 30,
        "Caminho Pasta": 40,
        "Hash SHA256": 15,
        "Conteúdo Identificado": 40,
        "Violações Encontradas": 35,
        "Avaliação": 50,
        "Resultado": 15,
        "Justificativa": 40,
        "Recomendações": 40,
        "Status Processamento": 15,
        "Erro": 30,
        "Parecer Final Humano": 40
    }
    
    # Cabeçalho
    for col_idx, column_name in enumerate(columns, 1):
        cell = ws.cell(row=1, column=col_idx, value=column_name)
        cell.font = header_style["font"]
        cell.fill = header_style["fill"]
        cell.alignment = header_style["alignment"]
        cell.border = header_style["border"]
        
        # Define largura
        width = column_widths.get(column_name, 20)
        ws.column_dimensions[get_column_letter(col_idx)].width = width
    
    # Dados
    for row_idx, row_data in enumerate(data, 2):
        for col_idx, column_name in enumerate(columns, 1):
            value = row_data.get(column_name, "")
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.alignment = cell_style["alignment"]
            cell.border = cell_style["border"]
            
            # Cor especial para coluna Resultado
            if column_name == "Resultado":
                cell.fill = get_result_fill(value)
                cell.alignment = Alignment(horizontal="center", vertical="center")
    
    # Congela cabeçalho
    ws.freeze_panes = "A2"
    
    # Altura da linha do cabeçalho
    ws.row_dimensions[1].height = 30
    
    logger.info(f"Workbook criado: {len(data)} linhas, {len(columns)} colunas")
    
    return wb


def save_independent_excel(
    wb: Workbook,
    config: Dict[str, Any],
    logger: logging.Logger
) -> Path:
    """
    Salva planilha Excel independente (por execução).
    
    Args:
        wb: Workbook a salvar.
        config: Configurações.
        logger: Logger.
        
    Returns:
        Caminho do arquivo salvo.
    """
    output_dir = BASE_DIR / config["paths"]["output_folder"]
    output_dir.mkdir(parents=True, exist_ok=True)
    
    export_config = config.get("export", {})
    prefix = export_config.get("filename_prefix", "ResultadoConforme")
    date_format = export_config.get("date_format", "%d%m%Y")
    
    date_str = datetime.now().strftime(date_format)
    filename = f"{prefix}{date_str}.xlsx"
    filepath = output_dir / filename
    
    # Se já existe, adiciona timestamp
    if filepath.exists():
        timestamp = datetime.now().strftime("%H%M%S")
        filename = f"{prefix}{date_str}_{timestamp}.xlsx"
        filepath = output_dir / filename
    
    wb.save(filepath)
    logger.info(f"Planilha independente salva: {filepath}")
    
    return filepath


def update_master_excel(
    data: List[Dict[str, Any]],
    config: Dict[str, Any],
    logger: logging.Logger
) -> Path:
    """
    Atualiza planilha cumulativa (histórico master).
    
    Args:
        data: Dados a adicionar.
        config: Configurações.
        logger: Logger.
        
    Returns:
        Caminho do arquivo master.
    """
    output_dir = BASE_DIR / config["paths"]["output_folder"]
    output_dir.mkdir(parents=True, exist_ok=True)
    
    master_filename = config.get("export", {}).get("master_filename", "historico_master.xlsx")
    master_path = output_dir / master_filename
    
    if master_path.exists():
        # Abre arquivo existente
        wb = load_workbook(master_path)
        ws = wb.active
        
        # Encontra última linha
        last_row = ws.max_row
        
        # Adiciona novos dados
        columns = list(data[0].keys()) if data else []
        cell_style = get_cell_style()
        
        for row_data in data:
            last_row += 1
            for col_idx, column_name in enumerate(columns, 1):
                value = row_data.get(column_name, "")
                cell = ws.cell(row=last_row, column=col_idx, value=value)
                cell.alignment = cell_style["alignment"]
                cell.border = cell_style["border"]
                
                if column_name == "Resultado":
                    cell.fill = get_result_fill(value)
                    cell.alignment = Alignment(horizontal="center", vertical="center")
        
        logger.info(f"Adicionados {len(data)} registros ao histórico master")
        
    else:
        # Cria novo arquivo master
        wb = create_excel_workbook(data, logger)
        logger.info("Criado novo arquivo histórico master")
    
    wb.save(master_path)
    logger.info(f"Histórico master atualizado: {master_path}")
    
    return master_path


# ============================================================================
# MAIN
# ============================================================================
def main() -> int:
    """
    Função principal do script de exportação.
    
    Returns:
        Código de saída (0 = sucesso, 1 = erro).
    """
    print("\n" + "=" * 60)
    print("ConforME - Exportação para Excel")
    print("=" * 60 + "\n")
    
    # Verifica dependências
    if not EXCEL_SUPPORT:
        print("❌ Erro: openpyxl não instalado. Use: pip install openpyxl")
        return 1
    
    # Parse argumentos
    parser = argparse.ArgumentParser(description="Exportação de resultados para Excel")
    parser.add_argument(
        "--input", "-i",
        type=str,
        required=True,
        help="Caminho do arquivo JSON com resultados da avaliação"
    )
    args = parser.parse_args()
    
    try:
        # Carrega configurações
        config = load_config()
        logger = setup_logging(config)
        
        logger.info("Iniciando processo de exportação")
        
        # Carrega resultados
        logger.info("-" * 40)
        logger.info("ETAPA 1: Carregamento de resultados")
        logger.info("-" * 40)
        
        json_path = Path(args.input)
        results = load_results(json_path, logger)
        
        # Prepara dados
        logger.info("-" * 40)
        logger.info("ETAPA 2: Preparação dos dados")
        logger.info("-" * 40)
        
        data = prepare_excel_data(results)
        
        if not data:
            logger.warning("Nenhum resultado para exportar")
            return 0
        
        logger.info(f"Dados preparados: {len(data)} registros")
        
        # Gera Excel independente
        logger.info("-" * 40)
        logger.info("ETAPA 3: Geração do Excel independente")
        logger.info("-" * 40)
        
        wb = create_excel_workbook(data, logger)
        independent_path = save_independent_excel(wb, config, logger)
        
        # Atualiza master
        logger.info("-" * 40)
        logger.info("ETAPA 4: Atualização do histórico master")
        logger.info("-" * 40)
        
        master_path = update_master_excel(data, config, logger)
        
        # Resumo final
        # Conta resultados
        approved = sum(1 for d in data if d.get("Resultado", "").upper() == "APROVADO")
        rejected = sum(1 for d in data if d.get("Resultado", "").upper() == "REPROVADO")
        inconclusive = len(data) - approved - rejected
        
        logger.info("=" * 40)
        logger.info("EXPORTAÇÃO CONCLUÍDA")
        logger.info("=" * 40)
        logger.info(f"Total: {len(data)} registros")
        logger.info(f"  ✓ Aprovados: {approved}")
        logger.info(f"  ✗ Reprovados: {rejected}")
        logger.info(f"  ? Inconclusivos: {inconclusive}")
        
        print(f"\n✅ Exportação concluída!")
        print(f"   📊 Planilha independente: {independent_path}")
        print(f"   📚 Histórico master: {master_path}")
        print(f"\n   Resumo:")
        print(f"      Total: {len(data)} | Aprovados: {approved} | Reprovados: {rejected} | Inconclusivos: {inconclusive}\n")
        
        return 0
        
    except FileNotFoundError as e:
        print(f"\n❌ Arquivo não encontrado: {e}")
        return 1
    except ValueError as e:
        print(f"\n❌ Erro de dados: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ Erro inesperado: {e}")
        logging.exception("Erro fatal na execução")
        return 1


if __name__ == "__main__":
    sys.exit(main())

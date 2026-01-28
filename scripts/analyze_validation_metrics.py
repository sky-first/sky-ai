#!/usr/bin/env python3
"""
Script para analisar métricas de validação a partir dos logs.

Analisa padrões de perguntas bloqueadas, warnings mais comuns, etc.
"""

from __future__ import annotations

import os
import sys
import json
import re
from collections import Counter, defaultdict
from typing import Dict, List

from dotenv import load_dotenv
load_dotenv()

# Adicionar o diretório raiz do projeto ao PYTHONPATH
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


def parse_log_line(line: str) -> Dict | None:
    """
    Tenta parsear uma linha de log JSON.
    Retorna None se não for JSON válido.
    """
    try:
        # Remover espaços em branco
        line = line.strip()
        if not line:
            return None
        
        # Tentar parsear como JSON
        data = json.loads(line)
        return data
    except (json.JSONDecodeError, ValueError):
        return None


def analyze_validation_logs(log_file: str = None) -> Dict:
    """
    Analisa logs de validação e retorna estatísticas.
    
    Args:
        log_file: Caminho para arquivo de log (opcional, pode ler de stdin)
    """
    validation_events = []
    
    # Ler logs
    if log_file and os.path.exists(log_file):
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    else:
        # Tentar ler de stdin ou arquivos comuns
        print("📝 Lendo logs... (pode passar arquivo como argumento)")
        print("   Exemplo: python3 analyze_validation_metrics.py < log_file.jsonl")
        return {}
    
    # Parsear linhas
    for line in lines:
        data = parse_log_line(line)
        if data and isinstance(data, dict):
            event_type = data.get("event_type", "")
            if "validation" in event_type.lower():
                validation_events.append(data)
    
    if not validation_events:
        print("⚠️  Nenhum evento de validação encontrado nos logs.")
        return {}
    
    # Análise
    stats = {
        "total_events": len(validation_events),
        "blocked_questions": 0,
        "warnings_issued": 0,
        "infos_issued": 0,
        "error_codes": Counter(),
        "warning_codes": Counter(),
        "info_codes": Counter(),
        "avg_question_length": 0,
        "avg_question_words": 0,
        "blocked_by_code": Counter(),
    }
    
    total_length = 0
    total_words = 0
    
    for event in validation_events:
        # Métricas gerais
        if event.get("was_blocked"):
            stats["blocked_questions"] += 1
            error_codes = event.get("error_codes", [])
            if error_codes:
                stats["blocked_by_code"][error_codes[0]] += 1
        
        # Contar códigos
        for code in event.get("error_codes", []):
            stats["error_codes"][code] += 1
        
        for code in event.get("warning_codes", []):
            stats["warning_codes"][code] += 1
            stats["warnings_issued"] += 1
        
        for code in event.get("info_codes", []):
            stats["info_codes"][code] += 1
            stats["infos_issued"] += 1
        
        # Comprimento médio
        length = event.get("question_length", 0)
        words = event.get("question_words", 0)
        if length > 0:
            total_length += length
            total_words += words
    
    if stats["total_events"] > 0:
        stats["avg_question_length"] = total_length / stats["total_events"]
        stats["avg_question_words"] = total_words / stats["total_events"]
    
    return stats


def print_analysis(stats: Dict):
    """Imprime análise formatada"""
    print("="*80)
    print("📊 ANÁLISE DE MÉTRICAS DE VALIDAÇÃO")
    print("="*80)
    print()
    
    if not stats:
        print("❌ Nenhum dado para analisar.")
        return
    
    print(f"📈 Total de eventos: {stats['total_events']}")
    print(f"🚫 Perguntas bloqueadas: {stats['blocked_questions']} ({stats['blocked_questions']/stats['total_events']*100:.1f}%)")
    print(f"⚠️  Warnings emitidos: {stats['warnings_issued']}")
    print(f"ℹ️  Infos emitidos: {stats['infos_issued']}")
    print()
    
    print(f"📏 Comprimento médio das perguntas:")
    print(f"   - Caracteres: {stats['avg_question_length']:.1f}")
    print(f"   - Palavras: {stats['avg_question_words']:.1f}")
    print()
    
    if stats['error_codes']:
        print("❌ ERROS MAIS COMUNS:")
        for code, count in stats['error_codes'].most_common(5):
            print(f"   - {code}: {count} ocorrências")
        print()
    
    if stats['warning_codes']:
        print("⚠️  WARNINGS MAIS COMUNS:")
        for code, count in stats['warning_codes'].most_common(5):
            print(f"   - {code}: {count} ocorrências")
        print()
    
    if stats['info_codes']:
        print("ℹ️  INFOS MAIS COMUNS:")
        for code, count in stats['info_codes'].most_common(5):
            print(f"   - {code}: {count} ocorrências")
        print()
    
    if stats['blocked_by_code']:
        print("🚫 PERGUNTAS BLOQUEADAS POR CÓDIGO:")
        for code, count in stats['blocked_by_code'].most_common():
            print(f"   - {code}: {count} bloqueios")
        print()
    
    print("="*80)


def main():
    """Função principal"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Analisa métricas de validação dos logs")
    parser.add_argument("log_file", nargs="?", help="Arquivo de log para analisar (opcional)")
    parser.add_argument("--output", "-o", help="Arquivo JSON para salvar resultados")
    
    args = parser.parse_args()
    
    # Analisar logs
    stats = analyze_validation_logs(args.log_file)
    
    # Imprimir análise
    print_analysis(stats)
    
    # Salvar se solicitado
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            # Converter Counter para dict para JSON
            stats_json = {
                **stats,
                "error_codes": dict(stats["error_codes"]),
                "warning_codes": dict(stats["warning_codes"]),
                "info_codes": dict(stats["info_codes"]),
                "blocked_by_code": dict(stats["blocked_by_code"]),
            }
            json.dump(stats_json, f, indent=2, ensure_ascii=False)
        print(f"\n💾 Resultados salvos em: {args.output}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())


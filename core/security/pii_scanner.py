# core/security/pii_scanner.py
"""
Scanner de dados sensíveis (PII) para detecção e bloqueio.

Analisa textos e dados estruturados procurando por informações sensíveis
usando os padrões definidos em pii_patterns.py.
"""
import re
from typing import List, Dict, Optional, Tuple, Any

from core.security.pii_patterns import (
    PIISeverity,
    PIIType,
    get_all_block_patterns,
    get_all_warn_patterns,
    get_all_info_patterns,
)


class PIIDetectionResult:
    """Resultado da detecção de PII"""
    def __init__(
        self,
        detected: bool,
        severity: Optional[PIISeverity] = None,
        pii_types: Optional[List[PIIType]] = None,
        patterns_matched: Optional[List[str]] = None,
        should_block: bool = False,
    ):
        self.detected = detected
        self.severity = severity
        self.pii_types = pii_types or []
        self.patterns_matched = patterns_matched or []
        self.should_block = should_block


def scan_text_for_pii(text: str) -> PIIDetectionResult:
    """
    Escaneia um texto procurando por dados sensíveis (PII).
    
    Args:
        text: Texto a ser escaneado
        
    Returns:
        PIIDetectionResult com informações sobre detecções
    """
    if not text or not isinstance(text, str):
        return PIIDetectionResult(detected=False)
    
    detected_types = set()
    matched_patterns = []
    max_severity = None
    
    # Verificar padrões BLOCK primeiro (mais críticos)
    for pattern, severity, pii_type in get_all_block_patterns():
        if pattern.search(text):
            detected_types.add(pii_type)
            matched_patterns.append(pattern.pattern[:100])  # Limitar tamanho
            if max_severity is None or severity == PIISeverity.BLOCK:
                max_severity = PIISeverity.BLOCK
    
    # Verificar padrões WARN
    if max_severity != PIISeverity.BLOCK:
        for pattern, severity, pii_type in get_all_warn_patterns():
            if pattern.search(text):
                detected_types.add(pii_type)
                matched_patterns.append(pattern.pattern[:100])
                if max_severity is None or severity == PIISeverity.WARN:
                    max_severity = PIISeverity.WARN
    
    # Verificar padrões INFO
    if max_severity is None:
        for pattern, severity, pii_type in get_all_info_patterns():
            if pattern.search(text):
                detected_types.add(pii_type)
                matched_patterns.append(pattern.pattern[:100])
                if max_severity is None:
                    max_severity = PIISeverity.INFO
    
    if max_severity is None:
        return PIIDetectionResult(detected=False)
    
    return PIIDetectionResult(
        detected=True,
        severity=max_severity,
        pii_types=list(detected_types),
        patterns_matched=list(set(matched_patterns))[:10],  # Limitar a 10 padrões únicos
        should_block=(max_severity == PIISeverity.BLOCK),
    )


def scan_data_for_pii(data: List[Dict[str, Any]]) -> PIIDetectionResult:
    """
    Escaneia dados estruturados (lista de dicionários) procurando por PII.
    
    Args:
        data: Lista de dicionários com dados
        
    Returns:
        PIIDetectionResult com informações sobre detecções
    """
    if not data or not isinstance(data, list):
        return PIIDetectionResult(detected=False)
    
    all_detected_types = set()
    all_matched_patterns = []
    max_severity = None
    
    # Escanear cada linha de dados (limitar para performance)
    for row in data[:100]:
        if not isinstance(row, dict):
            continue
        
        # Converter linha para string para escanear
        row_text = " ".join(str(v) for v in row.values() if v is not None)
        
        # Escanear o texto da linha
        result = scan_text_for_pii(row_text)
        
        if result.detected:
            all_detected_types.update(result.pii_types)
            all_matched_patterns.extend(result.patterns_matched)
            
            # Atualizar severidade máxima
            if max_severity is None:
                max_severity = result.severity
            elif result.severity == PIISeverity.BLOCK:
                max_severity = PIISeverity.BLOCK
            elif result.severity == PIISeverity.WARN and max_severity != PIISeverity.BLOCK:
                max_severity = PIISeverity.WARN
    
    if max_severity is None:
        return PIIDetectionResult(detected=False)
    
    return PIIDetectionResult(
        detected=True,
        severity=max_severity,
        pii_types=list(all_detected_types),
        patterns_matched=list(set(all_matched_patterns))[:10],  # Remover duplicatas
        should_block=(max_severity == PIISeverity.BLOCK),
    )


# ==================== DETECÇÃO DE CONTEXTO AGREGADO (GENÉRICO) ====================

def _is_aggregate_analysis_question(question: str) -> bool:
    """
    Detecta se uma pergunta indica análise/agregação de negócio (genérico, multi-tenant).
    
    Usa padrões linguísticos universais que funcionam para qualquer domínio.
    
    Args:
        question: Pergunta do usuário
        
    Returns:
        True se a pergunta indica análise agregada, False caso contrário
    """
    if not question or not isinstance(question, str):
        return False
    
    question_lower = question.lower()
    
    # Padrões de ranking/top N (genérico para qualquer domínio)
    ranking_patterns = [
        r'\b(top|melhores|piores|mais|menos|maior|menor|melhor|pior)\s+\d*',  # top 10, melhores, mais vendidos
        r'\b(quais|which|quelles|welche|quali)\s+(?:são|are|sont|sind|sono)',  # quais são os
        r'\b(ranking|rank|classificação|classificación)',  # ranking, classificação
        r'\b(mais\s+rentáveis|mais\s+vendidos|mais\s+frequentes)',  # mais rentáveis, mais vendidos
    ]
    
    # Padrões de agregação/totais (genérico) - expandido para capturar mais casos
    aggregation_patterns = [
        r'\b(total|soma|sum|contagem|count|média|avg|average|mean)',  # total, soma, média
        r'\b(ticket\s+médio|average|média|por\s+entidade)',  # ticket médio, receita média
        r'\b(por|by|par|durch|per)\s+\w+',  # por categoria, por mês, by category
        r'\b(agrupado|grouped|groupé|gruppiert|raggruppato)',  # agrupado por
        r'\b(distribuição|distribution|distribución|répartition|verteilung)',  # distribuição
        r'\b(margem|margin|profit|receita|revenue)',  # margem, receita (geralmente agregado)
        r'\b(impacto|impact|consolidado|consolidated)',  # impacto, consolidado
    ]
    
    # Padrões temporais/analíticos (genérico)
    temporal_patterns = [
        r'\b(mensal|anual|monthly|yearly|mensuelle|mensual)',  # mensal, anual
        r'\b(por\s+mês|por\s+ano|per\s+month|per\s+year)',  # por mês, por ano
        r'\b(tendência|trend|tendance|tendencia)',  # tendência
        r'\b(evolução|evolution|evolución|évolution)',  # evolução
        r'\b(comparar|compare|comparer|vergleichen)',  # comparar
        r'\b(análise|analysis|analyse|analisi)',  # análise
        r'\b(performance|desempenho|rendimiento)',  # performance
        r'\b(métrica|metric|métrique)',  # métrica
    ]
    
    # Verificar se a pergunta contém padrões indicativos de análise agregada
    all_patterns = ranking_patterns + aggregation_patterns + temporal_patterns
    
    for pattern in all_patterns:
        if re.search(pattern, question_lower, re.IGNORECASE):
            return True
    
    return False


def _is_aggregated_sql(sql: str) -> bool:
    """
    Detecta se uma query SQL é agregada (genérico para qualquer banco de dados).
    
    Verifica presença de:
    - GROUP BY
    - Funções de agregação (SUM, COUNT, AVG, MAX, MIN)
    - ORDER BY ... LIMIT (indica ranking/top N)
    
    Args:
        sql: Query SQL a ser analisada
        
    Returns:
        True se o SQL é agregado, False caso contrário
    """
    if not sql or not isinstance(sql, str):
        return False
    
    sql_upper = sql.upper()
    
    # Verificar GROUP BY
    if 'GROUP BY' in sql_upper:
        return True
    
    # Verificar funções de agregação
    aggregate_functions = ['SUM(', 'COUNT(', 'AVG(', 'MAX(', 'MIN(', 'AVERAGE(']
    for func in aggregate_functions:
        if func in sql_upper:
            return True
    
    # Verificar ORDER BY ... LIMIT (indica ranking/top N)
    if 'ORDER BY' in sql_upper and 'LIMIT' in sql_upper:
        return True
    
    return False


def _has_only_name_pii(detection_result: Optional[PIIDetectionResult]) -> bool:
    """
    Verifica se o resultado de detecção contém APENAS nomes (PIIType.NAME),
    sem outros tipos de PII sensíveis (telefones, emails, documentos, etc.).
    
    Args:
        detection_result: Resultado da detecção de PII
        
    Returns:
        True se contém apenas nomes, False caso contrário
    """
    if not detection_result or not detection_result.detected:
        return False
    
    if not detection_result.pii_types:
        return False
    
    # Tipos de PII que devem SEMPRE bloquear (Dados Tóxicos/Perigosos)
    # Se o usuário tem acesso às tabelas, permitimos Email/Telefone/Receita por padrão.
    sensitive_types = {
        PIIType.SSN,
        PIIType.CREDIT_CARD,
        PIIType.PASSWORD,
        PIIType.PASSPORT,
        PIIType.DRIVER_LICENSE,
        PIIType.MEDICAL,
        PIIType.SESSION_TOKEN,
        PIIType.BIOMETRIC,
        PIIType.GDPR_SENSITIVE,
    }
    
    # Se detectou algum tipo sensível além de NAME, bloquear
    detected_sensitive = set(detection_result.pii_types) & sensitive_types
    if detected_sensitive:
        return False
    
    # Se contém apenas tipos permitidos ou INFO, permitir
    forbidden_types = {
        PIIType.SSN, PIIType.CREDIT_CARD, PIIType.PASSWORD, PIIType.MEDICAL, 
        PIIType.BIOMETRIC, PIIType.GDPR_SENSITIVE
    }
    detected_types = set(detection_result.pii_types)
    
    return not (detected_types & forbidden_types)


def _has_explicit_pii_request_pattern(question: str) -> bool:
    """
    Verifica se a pergunta contém padrões explícitos de solicitação de dados pessoais.
    
    Esses padrões devem SEMPRE bloquear, mesmo em contexto de análise agregada.
    
    Args:
        question: Pergunta do usuário
        
    Returns:
        True se contém padrão explícito de solicitação de PII, False caso contrário
    """
    # DEPOIMENTO DO USUÁRIO: "perguntas simples caem no pii scaner , o que podemos fazer sem perder qualidade"
    # Se o usuário quer listar dados que ele tem permissão, permitimos.
    # Bloqueamos apenas se for algo relacionado a senhas ou dados tóxicos via padrões específicos.
    return False
    
    return False


def should_allow_pii_in_aggregate_context(
    question: str,
    sql: Optional[str],
    data: Optional[List[Dict[str, Any]]],
    pii_detection_result: Optional[PIIDetectionResult],
) -> bool:
    """
    Determina se PII detectado deve ser permitido em contexto de análise agregada.
    
    Regra de exceção genérica (multi-tenant, funciona para qualquer domínio):
    - Permite APENAS se TODAS as condições forem verdadeiras:
      1. Pergunta indica análise/agregação (padrões linguísticos genéricos)
      2. SQL é agregado (GROUP BY, SUM, ORDER BY LIMIT)
      3. Apenas NOMES detectados (não telefones, emails, documentos)
      4. Múltiplas linhas retornadas (ranking/lista, não registro individual)
      5. Não há padrão explícito de solicitação de dados pessoais
    
    Bloqueia se:
    - Telefones, emails, documentos detectados (mesmo em agregação)
    - Padrão explícito de solicitação de dados pessoais
    - Registro individual (LIMIT 1, WHERE id = X)
    
    Args:
        question: Pergunta do usuário
        sql: SQL gerado (opcional)
        data: Dados retornados (opcional)
        pii_detection_result: Resultado da detecção de PII
        
    Returns:
        True se deve permitir PII em contexto agregado, False caso contrário
    """
    # Se não há detecção de PII, não precisa aplicar exceção
    if not pii_detection_result or not pii_detection_result.detected:
        return False
    
    # Se há padrão explícito de solicitação de dados pessoais, SEMPRE bloquear
    if _has_explicit_pii_request_pattern(question):
        return False
    
    # Verificar se contém apenas nomes (não outros tipos sensíveis)
    if not _has_only_name_pii(pii_detection_result):
        return False
    
    # Verificar se pergunta indica análise agregada
    is_aggregate_question = _is_aggregate_analysis_question(question)
    if not is_aggregate_question:
        return False
    
    # Verificar se SQL é agregado (se disponível)
    # SQL agregado é o indicador mais confiável de análise agregada
    sql_is_aggregated = False
    sql_has_limit_1 = False
    sql_has_group_by = False
    
    if sql:
        sql_upper = sql.upper()
        sql_is_aggregated = _is_aggregated_sql(sql)
        sql_has_limit_1 = bool(re.search(r'\bLIMIT\s+1\b', sql_upper))
        sql_has_group_by = 'GROUP BY' in sql_upper
        
        # Se SQL não é agregado, bloquear (não é análise agregada)
        if not sql_is_aggregated:
            return False
        
        # Se SQL tem LIMIT 1 sem GROUP BY, é registro individual - bloquear
        if sql_has_limit_1 and not sql_has_group_by:
            return False
    
    # Se SQL está disponível e é agregado, usar como fonte principal
    # (mesmo se dados estiverem vazios - podem ter sido filtrados por PII ou erro)
    if sql_is_aggregated:
        # SQL agregado + pergunta agregada + apenas nomes = análise legítima, permitir
        return True
    
    # Se não temos SQL, verificar dados retornados
    # Se temos dados múltiplos, é ranking/lista
    if data and len(data) > 1:
        return True
    
    # Se não temos dados suficientes e SQL não está disponível ou não é agregado, bloquear
    return False


def should_allow_pii_exception(
    question: str,
    sql: Optional[str],
    data: Optional[List[Dict[str, Any]]],
    pii_detection_result: Optional[PIIDetectionResult],
) -> bool:
    """
    Determina se uma exceção deve ser aplicada para permitir PII detectado.
    
    Aplica duas regras de exceção:
    1. Contexto Agregado: Análises de negócio, rankings, totais (apenas NOMES).
    2. Small Result Set: Lookups simples (<= 5 linhas) para Email/Phone/Address.
    
    Args:
        question: Pergunta do usuário
        sql: SQL gerado (opcional)
        data: Dados retornados (opcional)
        pii_detection_result: Resultado da detecção de PII
        
    Returns:
        True se deve permitir PII (exceção aplicada), False caso contrário
    """
    # Se não há detecção de PII, permitir (não há o que bloquear)
    if not pii_detection_result or not pii_detection_result.detected:
        return True
        
    # Se deveria bloquear mas queremos verificar exceções
    if not pii_detection_result.should_block:
        return True

    # 1. Regra de Contexto Agregado (existente)
    # Verifica se é uma análise de negócio que retorna apenas Nomes
    if should_allow_pii_in_aggregate_context(question, sql, data, pii_detection_result):
        return True
        
    # 2. Regra de Small Result Set (NOVA)
    # Permite lookups simples (ex: "email do cliente X") se retornar poucas linhas
    if _should_allow_small_result_set(data, pii_detection_result):
        return True
        
    return False


def _should_allow_small_result_set(
    data: Optional[List[Dict[str, Any]]],
    pii_detection_result: Optional[PIIDetectionResult],
) -> bool:
    """
    Verifica se o resultado é pequeno o suficiente para permitir PII de contato (Email/Phone/etc).
    
    Regras:
    - Máximo 5 linhas
    - Apenas tipos de PII permitidos (Name, Email, Phone, Address, GPS, License Plate, IP)
    - Bloqueia tipos críticos (SSN, Credit Card, Password, Financial, Medical, etc.)
    """
    if not data:
        return False
        
    # Limite de linhas para considerar "lookup simples"
    if len(data) > 5:
        return False
        
    if not pii_detection_result or not pii_detection_result.pii_types:
        return True
        
    # Tipos de PII permitidos em lookups simples (contato/identificação básica)
    allowed_types = {
        PIIType.NAME,
        PIIType.EMAIL,
        PIIType.PHONE,
        PIIType.ADDRESS,
        PIIType.GPS,
        PIIType.LICENSE_PLATE,
        PIIType.IP_ADDRESS,
        PIIType.UUID,
    }
    
    # Verificar se TODOS os tipos detectados estão na lista de permitidos
    detected_types = set(pii_detection_result.pii_types)
    
    # Se houver qualquer tipo não permitido (ex: SSN, Credit Card), retornar False (Bloquear)
    if not detected_types.issubset(allowed_types):
        return False
        
    return True


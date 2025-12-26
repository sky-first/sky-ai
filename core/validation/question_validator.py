# core/validation/question_validator.py
"""
Sistema de validação genérico de perguntas baseado em metadados.
Funciona para qualquer domínio, não apenas billing.
"""

from __future__ import annotations

from typing import List, Dict, Optional
from dataclasses import dataclass
from enum import Enum
import re

from core.logging_utils import log_event


class ValidationSeverity(Enum):
    """Severidade de uma validação"""
    ERROR = "error"      # Bloqueia execução
    WARNING = "warning"  # Avisa mas permite
    INFO = "info"        # Informa apenas


@dataclass
class ValidationResult:
    """Resultado de uma validação"""
    severity: ValidationSeverity
    code: str  # Código único do problema
    message: str
    suggestion: Optional[str] = None  # Sugestão de correção
    metadata: Optional[Dict] = None  # Metadados adicionais


class QuestionValidator:
    """
    Validador genérico de perguntas baseado em metadados disponíveis.
    Não conhece domínio específico, apenas valida contra schema.
    """
    
    def __init__(self, available_tables: List[Dict], available_columns: Dict[str, List[str]]):
        """
        Args:
            available_tables: Lista de tabelas disponíveis com metadados
                Cada dict deve ter pelo menos: {"name": str, "logical_name": str}
            available_columns: Dict {table_name: [column_names]}
        """
        # Normalizar tabelas: usar logical_name como chave principal
        self.available_tables = {}
        for t in available_tables:
            logical_name = t.get("logical_name") or t.get("name", "")
            if logical_name:
                self.available_tables[logical_name] = t
        
        self.available_columns = available_columns or {}
    
    def validate_question(self, question: str) -> List[ValidationResult]:
        """
        Valida uma pergunta e retorna lista de problemas encontrados.
        
        Args:
            question: Pergunta do usuário
            
        Returns:
            Lista de ValidationResult com problemas encontrados
        """
        if not question or not isinstance(question, str):
            return [ValidationResult(
                severity=ValidationSeverity.ERROR,
                code="EMPTY_QUESTION",
                message="A pergunta não pode estar vazia.",
            )]
        
        results = []
        
        # 1. Detectar ambiguidade (requer parâmetros específicos)
        if self._is_ambiguous(question):
            results.append(ValidationResult(
                severity=ValidationSeverity.WARNING,
                code="AMBIGUOUS_QUESTION",
                message="Esta pergunta requer informações específicas que não foram fornecidas.",
                suggestion="Reformule a pergunta para ser mais específica. Ex: 'Quais itens foram vendidos na fatura X?' → 'Quais itens foram vendidos?' ou 'Mostre os itens da fatura mais recente'",
            ))
        
        # 2. Detectar referências a entidades não disponíveis
        missing_refs = self._check_missing_references(question)
        if missing_refs:
            results.append(ValidationResult(
                severity=ValidationSeverity.WARNING,
                code="MISSING_REFERENCES",
                message=f"A pergunta menciona entidades que podem não estar disponíveis: {', '.join(missing_refs[:3])}",
                suggestion="Verifique se as tabelas/colunas mencionadas existem nos dados disponíveis.",
                metadata={"missing": missing_refs},
            ))
        
        # 3. Detectar padrões que podem gerar múltiplas queries
        if self._may_generate_multiple_queries(question):
            results.append(ValidationResult(
                severity=ValidationSeverity.ERROR,
                code="MULTIPLE_QUERIES_RISK",
                message="Esta pergunta pode tentar gerar múltiplas queries SQL.",
                suggestion="Reformule para uma única pergunta que possa ser respondida com uma query.",
            ))
        
        # 4. Detectar perguntas que provavelmente retornarão 0 resultados
        if self._likely_empty_result(question):
            results.append(ValidationResult(
                severity=ValidationSeverity.INFO,
                code="LIKELY_EMPTY_RESULT",
                message="Esta pergunta pode não retornar resultados com os dados disponíveis.",
                suggestion="Considere reformular ou verificar se os dados necessários estão disponíveis.",
            ))
        
        # 5. Detectar perguntas muito complexas (muito longas ou muitos termos)
        complexity_issue = self._check_complexity(question)
        if complexity_issue:
            results.append(complexity_issue)
        
        return results
    
    def _is_ambiguous(self, question: str) -> bool:
        """
        Detecta se a pergunta é ambígua (requer parâmetros específicos).
        Padrões genéricos que funcionam para qualquer domínio.
        """
        ambiguous_patterns = [
            # Português - padrões básicos
            r'\b(uma|um|a|o)\s+(específic[ao]|particular|determinad[ao])\b',
            r'\b(qual|quais)\s+.*\s+(específic[ao]|particular|determinad[ao])\b',
            r'\b(em|na|no)\s+(uma|um)\s+(fatura|pedido|cliente|produto|item|venda|transação|registro)\s+específic[ao]\b',
            r'\b(em|na|no)\s+(uma|um)\s+[a-z]+\s+específic[ao]\b',
            r'\b(para|por)\s+(uma|um)\s+[a-z]+\s+específic[ao]\b',
            # Português - padrões adicionais
            r'\b(mostre|mostrar|listar|liste|exiba|exibir)\s+.*\s+(de|do|da)\s+(uma|um)\s+[a-z]+\s+específic[ao]\b',
            r'\b(quais|qual)\s+.*\s+(de|do|da)\s+(uma|um)\s+[a-z]+\s+específic[ao]\b',
            r'\b(em|na|no)\s+(qual|quais)\s+[a-z]+\s+específic[ao]\b',
            r'\b(para|por)\s+(qual|quais)\s+[a-z]+\s+específic[ao]\b',
            # Inglês - padrões básicos
            r'\b(in|on|at|for)\s+(a|an|the)\s+specific\b',
            r'\b(which|what)\s+.*\s+(specific|particular|determined)\b',
            r'\b(in|on|at)\s+(a|an|the)\s+specific\s+[a-z]+\b',
            # Inglês - padrões adicionais
            r'\b(show|list|display|find)\s+.*\s+(for|of|in)\s+(a|an|the)\s+specific\s+[a-z]+\b',
            r'\b(which|what)\s+.*\s+(for|of|in)\s+(a|an|the)\s+specific\s+[a-z]+\b',
        ]
        
        question_lower = question.lower()
        for pattern in ambiguous_patterns:
            if re.search(pattern, question_lower, re.IGNORECASE):
                return True
        return False
    
    def _check_missing_references(self, question: str) -> List[str]:
        """
        Verifica se a pergunta menciona tabelas/colunas que não existem.
        Baseado em metadados, não hardcoded.
        """
        missing = []
        
        if not self.available_tables:
            return missing
        
        # Normalizar nomes de tabelas disponíveis
        available_table_names = set()
        available_table_variations = set()  # Variações (singular, plural, sem prefixos)
        
        for table_name in self.available_tables.keys():
            table_lower = table_name.lower()
            available_table_names.add(table_lower)
            
            # Adicionar variações (sem prefixos, singular/plural)
            parts = table_lower.split('_')
            if len(parts) > 1:
                # Adicionar última parte (sem prefixos como "silver_", "gold_", etc)
                base_name = parts[-1]
                available_table_variations.add(base_name)
                
                # Adicionar singular/plural
                if base_name.endswith('s') and len(base_name) > 1:
                    singular = base_name[:-1]
                    available_table_variations.add(singular)
                elif not base_name.endswith('s'):
                    plural = base_name + 's'
                    available_table_variations.add(plural)
            
            # Adicionar nome completo sem underscores
            no_underscore = table_lower.replace('_', '')
            if no_underscore:
                available_table_variations.add(no_underscore)
        
        # Verificar referências explícitas (entre aspas, backticks, etc)
        quoted_refs = re.findall(r'[`"\']([^`"\']+)[`"\']', question.lower())
        for ref in quoted_refs:
            ref_clean = ref.strip().replace('_', '').replace('-', '')
            if ref_clean:
                # Verificar se existe exatamente ou como variação
                if (ref_clean not in available_table_names and 
                    ref_clean not in available_table_variations):
                    # Verificar se não é uma substring de alguma tabela
                    is_substring = any(
                        ref_clean in name or name in ref_clean 
                        for name in list(available_table_names) + list(available_table_variations)
                    )
                    if not is_substring:
                        missing.append(ref)
        
        # Verificar referências implícitas (palavras que parecem nomes de tabelas)
        # Padrão: "tabela X", "na tabela Y", "da tabela Z"
        table_ref_patterns = [
            r'\btabela\s+([a-z_]+)\b',
            r'\btable\s+([a-z_]+)\b',
            r'\bna\s+tabela\s+([a-z_]+)\b',
            r'\bda\s+tabela\s+([a-z_]+)\b',
            r'\bfrom\s+table\s+([a-z_]+)\b',
            r'\bin\s+table\s+([a-z_]+)\b',
        ]
        
        for pattern in table_ref_patterns:
            matches = re.findall(pattern, question.lower())
            for match in matches:
                match_clean = match.strip().replace('_', '').replace('-', '')
                if match_clean:
                    if (match_clean not in available_table_names and 
                        match_clean not in available_table_variations):
                        # Verificar se não é uma substring
                        is_substring = any(
                            match_clean in name or name in match_clean 
                            for name in list(available_table_names) + list(available_table_variations)
                        )
                        if not is_substring and match_clean not in missing:
                            missing.append(match_clean)
        
        return missing
    
    def _may_generate_multiple_queries(self, question: str) -> bool:
        """
        Detecta padrões que podem levar o LLM a gerar múltiplas queries.
        """
        # Padrões que sugerem múltiplas queries
        multi_query_patterns = [
            # Português
            r'\be\s+(depois|então|em seguida)\b',  # "e depois"
            r'\bprimeiro\s+.*\s+depois\b',  # "primeiro X depois Y"
            r'\b(para\s+cada|por\s+cada)\b.*\s+(mostre|mostrar|listar|liste)\b',  # "para cada X mostre Y"
            r'\b(primeiro|depois|então)\s+.*\s+(depois|então|em seguida)\b',
            # Inglês
            r'\band\s+then\b',
            r'\bfirst\s+.*\s+then\b',
            r'\b(for\s+each|per)\b.*\s+(show|list|display)\b',
            r'\b(then|after)\s+.*\s+(then|after)\b',
        ]
        
        question_lower = question.lower()
        for pattern in multi_query_patterns:
            if re.search(pattern, question_lower, re.IGNORECASE):
                return True
        return False
    
    def _likely_empty_result(self, question: str) -> bool:
        """
        Detecta perguntas que provavelmente retornarão 0 resultados.
        Baseado em padrões temporais/condicionais muito restritivos.
        """
        # Padrões que sugerem filtros muito restritivos
        restrictive_patterns = [
            # Português
            r'\b(hoje|today|agora|now)\b.*\s+(próxim[ao]s?|vencendo|vencimento|a\s+vencer)\b',
            r'\b(próxim[ao]s?|vencendo|vencimento)\b.*\s+(hoje|today|agora|now)\b',
            r'\b(últim[ao]s?\s+)?(7|14|30)\s+dias\b.*\s+(sem|without|nenhum)\b',
            r'\b(no|na)\s+(período|period)\s+(específico|specific)\b',
            r'\b(apenas|only)\s+(hoje|today|agora|now)\b',
            r'\b(que|which)\s+.*\s+(estão|está)\s+(próxim[ao]s?|vencendo)\b',
            # Inglês
            r'\b(today|now)\b.*\s+(due|expiring|upcoming)\b',
            r'\b(due|expiring|upcoming)\b.*\s+(today|now)\b',
            r'\b(last\s+)?(7|14|30)\s+days\b.*\s+(without|no|none)\b',
            r'\b(in|on)\s+(a|the)\s+specific\s+period\b',
            r'\b(only|just)\s+(today|now)\b',
            r'\b(which|what)\s+.*\s+(are|is)\s+(due|expiring|upcoming)\b',
        ]
        
        question_lower = question.lower()
        for pattern in restrictive_patterns:
            if re.search(pattern, question_lower, re.IGNORECASE):
                return True
        return False
    
    def _check_complexity(self, question: str) -> Optional[ValidationResult]:
        """
        Detecta perguntas muito complexas que podem ser difíceis de processar.
        Retorna ValidationResult se houver problema, None caso contrário.
        """
        # Contar palavras e caracteres
        words = question.split()
        num_words = len(words)
        num_chars = len(question)
        
        # Contar termos técnicos/complexos (palavras longas, múltiplas condições)
        complex_indicators = 0
        # Palavras muito longas (>15 caracteres)
        for word in words:
            if len(word) > 15:
                complex_indicators += 1
        
        # Múltiplas condições (AND, OR, E, OU) - contar ocorrências
        condition_words = [' e ', ' ou ', ' and ', ' or ', ' mas ', ' but ', ' além ', ' além de ', ' também ', ' also ']
        question_lower = question.lower()
        condition_count = 0
        for cond in condition_words:
            # Contar todas as ocorrências
            condition_count += question_lower.count(cond)
        
        # Se tiver 4 ou mais condições, é complexo
        if condition_count >= 4:
            complex_indicators += condition_count
        
        # Critérios de complexidade
        is_too_long = num_words > 50 or num_chars > 500
        has_many_conditions = complex_indicators >= 5
        is_very_long = num_words > 80 or num_chars > 800
        
        if is_very_long:
            return ValidationResult(
                severity=ValidationSeverity.WARNING,
                code="VERY_COMPLEX_QUESTION",
                message="Esta pergunta é muito longa e complexa, o que pode dificultar o processamento.",
                suggestion="Considere dividir em perguntas menores e mais específicas.",
                metadata={
                    "num_words": num_words,
                    "num_chars": num_chars,
                    "complex_indicators": complex_indicators,
                },
            )
        elif is_too_long or has_many_conditions:
            return ValidationResult(
                severity=ValidationSeverity.INFO,
                code="COMPLEX_QUESTION",
                message="Esta pergunta é complexa e pode demorar mais para processar.",
                suggestion="Considere simplificar ou dividir em múltiplas perguntas.",
                metadata={
                    "num_words": num_words,
                    "num_chars": num_chars,
                    "complex_indicators": complex_indicators,
                },
            )
        
        return None


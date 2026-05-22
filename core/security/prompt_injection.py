# core/security/prompt_injection.py
"""
Detecção rápida de prompt injection.
Executa antes de chamar IA (tempo: < 1ms)
"""
import re
from typing import Tuple, Optional

# Remove zero-width chars e normaliza whitespace (reduz bypass por unicode/formatting)
_ZERO_WIDTH_RE = re.compile(r"[\u200B-\u200D\uFEFF]")
_WHITESPACE_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    if not text:
        return ""
    t = _ZERO_WIDTH_RE.sub("", text)
    t = t.replace("\r", "\n")
    t = _WHITESPACE_RE.sub(" ", t)
    return t.strip().lower()


# Padrões maliciosos (compilados para performance)
MALICIOUS_PATTERNS = [
    re.compile(r"ignore.*regra", re.IGNORECASE),
    re.compile(r"ignore.*previous", re.IGNORECASE),
    re.compile(r"ignore.*instruction", re.IGNORECASE),
    re.compile(r"rode.*exatamente.*sql", re.IGNORECASE),
    re.compile(r"execute.*exactly", re.IGNORECASE),
    re.compile(r"não.*use.*limite", re.IGNORECASE),
    re.compile(r"don'?t.*use.*limit", re.IGNORECASE),
    re.compile(r"mostra.*tudo", re.IGNORECASE),
    re.compile(r"show.*everything", re.IGNORECASE),
    re.compile(r"mesmo.*não.*permitido", re.IGNORECASE),
    re.compile(r"even.*not.*allowed", re.IGNORECASE),
    re.compile(r"isso.*é.*só.*teste", re.IGNORECASE),
    re.compile(r"this.*is.*just.*test", re.IGNORECASE),
    re.compile(r"\bbypass\b", re.IGNORECASE),
    re.compile(r"\boverride\b", re.IGNORECASE),
    re.compile(r"\bhack\b", re.IGNORECASE),
    re.compile(r"\bexploit\b", re.IGNORECASE),
    re.compile(r"ignore.*above", re.IGNORECASE),
    re.compile(r"forget.*previous", re.IGNORECASE),
    re.compile(r"new.*instructions", re.IGNORECASE),
    re.compile(r"system.*prompt", re.IGNORECASE),
    re.compile(r"you.*are.*now", re.IGNORECASE),
    re.compile(r"pretend.*you.*are", re.IGNORECASE),
    # Tentativas comuns de jailbreak
    re.compile(r"\bdan\b", re.IGNORECASE),
    re.compile(r"do\s+anything\s+now", re.IGNORECASE),
    re.compile(r"developer\s+message", re.IGNORECASE),
    re.compile(r"begin\s+system\s+prompt", re.IGNORECASE),
    re.compile(r"reveal\s+your\s+system", re.IGNORECASE),
    # Exfil / payloads
    re.compile(r"base64", re.IGNORECASE),
    re.compile(r"```", re.IGNORECASE),  # code fences
    re.compile(r"<system>|</system>", re.IGNORECASE),
    re.compile(r"<developer>|</developer>", re.IGNORECASE),
    re.compile(r"<assistant>|</assistant>", re.IGNORECASE),
    # Pedidos para rodar SQL malicioso/sem validações
    re.compile(r"select\s+\*", re.IGNORECASE),
    re.compile(r"information_schema", re.IGNORECASE),
    re.compile(r"pg_catalog", re.IGNORECASE),
    re.compile(r"union\s+select", re.IGNORECASE),
    # Role-play / mode switching variants
    re.compile(r"\brole\s*:\s*[a-z0-9_\-]+\b", re.IGNORECASE),
    re.compile(r"\btask\s*:\s*[a-z0-9_\-]+\b", re.IGNORECASE),
    re.compile(r"\badmin\s*mode\b", re.IGNORECASE),
    re.compile(r"\bdeveloper\s*mode\b", re.IGNORECASE),
    # Multi-step jailbreak patterns
    re.compile(r"\bstep\s*\d+\s*:", re.IGNORECASE),
    re.compile(r"\bpasso\s*\d+\s*:", re.IGNORECASE),
    # Delimiter / boundary tricks
    re.compile(r"={3,}\s*(begin|end)\s*_(system|user|assistant)", re.IGNORECASE),
    re.compile(r"={3,}.*(system|user|assistant)", re.IGNORECASE),
    re.compile(r"\b(begin|end)\s*_(system|user|assistant)\b", re.IGNORECASE),
    re.compile(r"\[(system|developer|assistant)\]", re.IGNORECASE),
    # Encoding / obfuscation
    re.compile(r"(\\x[0-9a-fA-F]{2}){2,}", re.IGNORECASE),
    re.compile(r"\b0x[0-9a-fA-F]{8,}\b", re.IGNORECASE),
    re.compile(r"\bhex\s+encoding\b", re.IGNORECASE),
    # Schema exploration / enumeration
    re.compile(r"\bwhat\b.*\btables?\b", re.IGNORECASE),
    re.compile(r"\bwhich\b.*\btables?\b", re.IGNORECASE),
    re.compile(r"\blist\b.*\btables?\b", re.IGNORECASE),
    re.compile(r"\bshow\b.*\btables?\b", re.IGNORECASE),
    re.compile(r"\bwhat\b.*\bcolumns?\b", re.IGNORECASE),
    re.compile(r"\blist\b.*\bcolumns?\b", re.IGNORECASE),
    re.compile(r"\bshow\b.*\bcolumns?\b", re.IGNORECASE),
    re.compile(r"\bdescribe\b.*\btable\b", re.IGNORECASE),
    re.compile(r"\bschema\b", re.IGNORECASE),
    re.compile(r"\bmetadata\b", re.IGNORECASE),
    re.compile(r"\bdata\s*catalog\b", re.IGNORECASE),
    re.compile(r"\bquais\b.*\btabelas\b", re.IGNORECASE),
    re.compile(r"\btabelas\b.*\bdispon[ií]veis\b", re.IGNORECASE),
    re.compile(
        r"\btabelas\b.*\b(pode|posso|podem)\b.*\bver\b", re.IGNORECASE
    ),  # "tabelas que X pode ver"
    re.compile(
        r"\btables\b.*\b(can|could)\b.*\b(see|access|view)\b", re.IGNORECASE
    ),  # "tables that X can see"
    re.compile(r"\bacesso\b.*\btabelas\b", re.IGNORECASE),  # "acesso a tabelas"
    re.compile(r"\baccess\b.*\btables\b", re.IGNORECASE),  # "access to tables"
    re.compile(
        r"\bpermiss[õo]es?\b.*\btabelas\b", re.IGNORECASE
    ),  # "permissões de tabelas"
    re.compile(
        r"\bpermissions?\b.*\btables\b", re.IGNORECASE
    ),  # "permissions to tables"
    re.compile(r"\bquais\b.*\bcolunas\b", re.IGNORECASE),
    re.compile(r"\bmostre\b.*\bcolunas\b", re.IGNORECASE),
    re.compile(r"\bestrutura\b", re.IGNORECASE),
    # System prompt / config extraction
    re.compile(r"\bwhat\b.*\binstructions\b", re.IGNORECASE),
    re.compile(r"\brepeat\b.*\binstructions\b", re.IGNORECASE),
    re.compile(r"\bprint\b.*\bconfiguration\b", re.IGNORECASE),
    re.compile(r"\bconfig(uration)?\b.*\byaml\b", re.IGNORECASE),
    # System / architecture probing (not data-related)
    re.compile(r"\bsystem\s+architecture\b", re.IGNORECASE),
    re.compile(r"\bunderlying\b.*\bsystem\b", re.IGNORECASE),
    re.compile(r"\barquitetura\b.*\bsistema\b", re.IGNORECASE),
    # Basic XSS payload markers (defense-in-depth)
    re.compile(r"<\s*script\b", re.IGNORECASE),
    re.compile(r"<\s*iframe\b", re.IGNORECASE),
    re.compile(r"\bonerror\s*=", re.IGNORECASE),
    re.compile(r"\bonload\s*=", re.IGNORECASE),
    re.compile(r"\bjavascript\s*:", re.IGNORECASE),
    # Leetspeak/l33t patterns (common bypass attempts)
    re.compile(r"s[3e]l[3e]ct\s*\*", re.IGNORECASE),  # S3L3CT *, SEL3CT *
    re.compile(r"fr[0o]m\s+us[3e]rs", re.IGNORECASE),  # FR0M us3rs
    re.compile(r"sh[0o]w\s+t[4a]bl[3e]s", re.IGNORECASE),  # SH0W T4BL3S
    re.compile(r"d[4a]t[4a]b[4a]s[3e]", re.IGNORECASE),  # D4T4B4S3
    re.compile(r"l[1i]m[1i]t", re.IGNORECASE),  # L1M1T
    re.compile(r"us[3e]rs", re.IGNORECASE),  # us3rs
]

# Padrões críticos (rejeitar imediatamente)
CRITICAL_PATTERNS = [
    re.compile(r"ignore.*previous", re.IGNORECASE),
    re.compile(r"system.*prompt", re.IGNORECASE),
    re.compile(r"you.*are.*now", re.IGNORECASE),
    re.compile(r"pretend.*you.*are", re.IGNORECASE),
    re.compile(r"forget.*all", re.IGNORECASE),
    re.compile(r"reveal.*system", re.IGNORECASE),
    re.compile(r"show.*system", re.IGNORECASE),
    re.compile(r"dump.*prompt", re.IGNORECASE),
    # Schema enumeration (block immediately)
    re.compile(r"\bwhat\b.*\btables?\b", re.IGNORECASE),
    re.compile(r"\blist\b.*\btables?\b", re.IGNORECASE),
    re.compile(r"\bshow\b.*\btables?\b", re.IGNORECASE),
    re.compile(r"\bwhat\b.*\bcolumns?\b", re.IGNORECASE),
    re.compile(r"\blist\b.*\bcolumns?\b", re.IGNORECASE),
    re.compile(r"\bshow\b.*\bcolumns?\b", re.IGNORECASE),
    re.compile(r"\bschema\b", re.IGNORECASE),
    re.compile(r"\bmetadata\b", re.IGNORECASE),
    re.compile(r"\bquais\b.*\btabelas\b", re.IGNORECASE),
    re.compile(
        r"\btabelas\b.*\b(pode|posso|podem)\b.*\bver\b", re.IGNORECASE
    ),  # "tabelas que X pode ver"
    re.compile(
        r"\btables\b.*\b(can|could)\b.*\b(see|access|view)\b", re.IGNORECASE
    ),  # "tables that X can see"
    re.compile(r"\bacesso\b.*\btabelas\b", re.IGNORECASE),  # "acesso a tabelas"
    re.compile(r"\baccess\b.*\btables\b", re.IGNORECASE),  # "access to tables"
    re.compile(
        r"\bpermiss[õo]es?\b.*\btabelas\b", re.IGNORECASE
    ),  # "permissões de tabelas"
    re.compile(
        r"\bpermissions?\b.*\btables\b", re.IGNORECASE
    ),  # "permissions to tables"
    re.compile(r"\bquais\b.*\bcolunas\b", re.IGNORECASE),
    re.compile(r"\bestrutura\b", re.IGNORECASE),
    # Delimiter tricks
    re.compile(r"={3,}.*(system|user|assistant)", re.IGNORECASE),
    re.compile(r"\[(system|developer|assistant)\]", re.IGNORECASE),
    # Encoded payloads
    re.compile(r"(\\x[0-9a-fA-F]{2}){2,}", re.IGNORECASE),
    # Role-play admin/task
    re.compile(r"\brole\s*:\s*[a-z0-9_\-]+\b", re.IGNORECASE),
    re.compile(r"\btask\s*:\s*[a-z0-9_\-]+\b", re.IGNORECASE),
    # System/config exfiltration
    re.compile(r"\bwhat\b.*\binstructions\b", re.IGNORECASE),
    re.compile(r"\bprint\b.*\bconfiguration\b", re.IGNORECASE),
    re.compile(r"\bsystem\s+architecture\b", re.IGNORECASE),
    re.compile(r"\bunderlying\b.*\bsystem\b", re.IGNORECASE),
    # XSS markers (block; not useful for analytics)
    re.compile(r"<\s*script\b", re.IGNORECASE),
    re.compile(r"\bjavascript\s*:", re.IGNORECASE),
]


def detect_prompt_injection(question: str) -> Tuple[bool, Optional[str]]:
    """
    Detecta tentativas de prompt injection.
    Retorna (is_malicious, pattern_matched)
    Tempo: < 1ms (regex compilado)
    """
    if not question:
        return False, None

    question_lower = _normalize(question)

    # Heurística: payload base64 grande (tentativa de esconder instruções)
    # (strings longas com charset base64)
    if re.search(r"\b[A-Za-z0-9+/=]{120,}\b", question):
        return True, "base64_payload"

    # Verificar padrões críticos primeiro (mais rápido)
    for pattern in CRITICAL_PATTERNS:
        if pattern.search(question_lower):
            return True, pattern.pattern

    # Verificar outros padrões
    for pattern in MALICIOUS_PATTERNS:
        if pattern.search(question_lower):
            return True, pattern.pattern

    return False, None


def sanitize_question(question: str) -> Optional[str]:
    """
    Tenta limpar pergunta (se não for muito maliciosa).
    Se for crítica, retorna None (deve ser rejeitada).
    """
    is_malicious, pattern = detect_prompt_injection(question)

    if not is_malicious:
        return question

    # Se for crítico, rejeitar
    for critical in CRITICAL_PATTERNS:
        if critical.search(question.lower()):
            return None

    # Tentar limpar (remover padrões não críticos)
    cleaned = question
    for pattern in MALICIOUS_PATTERNS:
        cleaned = pattern.sub("", cleaned)

    return cleaned.strip() if cleaned.strip() else None

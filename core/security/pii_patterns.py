# core/security/pii_patterns.py
"""
Lista abrangente de termos, expressões regulares e padrões que caracterizam 
informações sensíveis (PII - Personally Identifiable Information) a serem 
bloqueadas ou sinalizadas.

Suporta múltiplos países e idiomas:
- Europa: UK, França, Alemanha, Espanha, Portugal, Itália, Países Nórdicos, etc.
- Américas: EUA, Canadá, Brasil, México, Argentina, etc.
- Ásia: Japão, China, Coreia, Índia, etc.
- Outros: Austrália, Nova Zelândia, etc.

Organizado por categoria e nível de severidade:
- BLOCK: Bloqueia imediatamente
- WARN: Alerta e registra (pode bloquear após threshold)
- INFO: Registra para auditoria

Inclui:
- Padrões de dados sensíveis diretos
- Padrões de evasão/bypass (codificação, mascaramento)
- Padrões contextuais (combinações de dados)
- Dados protegidos por GDPR
- Dados estruturados (JSON, XML, CSV)
"""
import re
from typing import List, Tuple, Dict, Optional
from enum import Enum


class PIISeverity(Enum):
    """Níveis de severidade para detecção de PII"""
    BLOCK = "block"  # Bloqueia imediatamente
    WARN = "warn"    # Alerta e registra
    INFO = "info"    # Registra para auditoria


class PIIType(Enum):
    """Tipos de dados sensíveis"""
    NAME = "name"
    PHONE = "phone"
    EMAIL = "email"
    ADDRESS = "address"
    ID_NUMBER = "id_number"  # Documentos de identificação (genérico)
    SSN = "ssn"  # Social Security Number (US)
    TAX_ID = "tax_id"  # NIF, TIN, etc.
    CREDIT_CARD = "credit_card"
    BANK_ACCOUNT = "bank_account"
    PASSWORD = "password"
    IP_ADDRESS = "ip_address"
    DATE_OF_BIRTH = "date_of_birth"
    LICENSE_PLATE = "license_plate"
    PASSPORT = "passport"
    DRIVER_LICENSE = "driver_license"
    MEDICAL = "medical"
    FINANCIAL = "financial"
    GPS = "gps"
    MAC_ADDRESS = "mac_address"
    UUID = "uuid"
    SESSION_TOKEN = "session_token"
    BIOMETRIC = "biometric"
    GDPR_SENSITIVE = "gdpr_sensitive"


# ==================== PADRÕES DE DADOS SENSÍVEIS ====================

# ========== TELEFONES (INTERNACIONAL) ==========
PHONE_PATTERNS: List[Tuple[re.Pattern, PIISeverity, PIIType]] = [
    # Formato internacional com código do país: +1 555-123-4567, +44 20 7946 0958
    # Mais específico: requer pelo menos 7 dígitos totais e formato estruturado
    (re.compile(r'\+?\d{1,4}[\s.-]\(?\d{3,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{4,9}'), 
     PIISeverity.WARN, PIIType.PHONE),
    
    # Telefones brasileiros
    (re.compile(r'\(\d{2}\)\s?\d{4,5}-?\d{4}'), PIISeverity.WARN, PIIType.PHONE),  # (11) 98765-4321
    (re.compile(r'\d{2}\s?\d{4,5}-?\d{4}'), PIISeverity.WARN, PIIType.PHONE),  # 11 98765-4321
    
    # EUA/Canadá: (555) 123-4567 ou 555-123-4567
    (re.compile(r'\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}'), PIISeverity.WARN, PIIType.PHONE),
    
    # UK: 020 7946 0958 ou 07700 900000
    (re.compile(r'\b0\d{1,3}[\s-]?\d{3,4}[\s-]?\d{3,4}\b'), PIISeverity.WARN, PIIType.PHONE),
    
    # Europa (vários formatos): +33 1 23 45 67 89, +49 30 12345678
    # Mais específico: requer pelo menos 8 dígitos totais (evita falsos positivos)
    (re.compile(r'\+?\d{2,3}[\s.-]?\d{2,4}[\s.-]?\d{2,4}[\s.-]?\d{2,4}[\s.-]?\d{2,4}'), 
     PIISeverity.WARN, PIIType.PHONE),
    
    # Japão: 03-1234-5678 ou 090-1234-5678
    (re.compile(r'\b0\d{1,2}-?\d{4}-?\d{4}\b'), PIISeverity.WARN, PIIType.PHONE),
    
    # China: 138-0013-8000
    (re.compile(r'\b1[3-9]\d-?\d{4}-?\d{4}\b'), PIISeverity.WARN, PIIType.PHONE),
    
    # Índia: +91 98765 43210
    (re.compile(r'\+91\s?\d{5}\s?\d{5}'), PIISeverity.WARN, PIIType.PHONE),
    
    # Austrália: 02 1234 5678 ou 0412 345 678
    (re.compile(r'\b0\d{1,2}\s?\d{4}\s?\d{4}\b'), PIISeverity.WARN, PIIType.PHONE),
    
    # Sequências longas de dígitos (pode ser telefone sem formatação)
    # Mais restritivo: pelo menos 10 dígitos (evita falsos positivos com números simples)
    (re.compile(r'\b\d{10,15}\b'), PIISeverity.WARN, PIIType.PHONE),
    
    # Padrões com palavras-chave de telefone (mais específicos)
    (re.compile(r'\b(phone|telefone|tel|mobile|celular|cell)\s*:?\s*[\+\d\s\-\(\)]{7,}', 
                re.IGNORECASE), PIISeverity.WARN, PIIType.PHONE),
    
    # Palavras-chave em múltiplos idiomas
    (re.compile(r'\b(telefone|phone|tel|téléphone|telefono|telefon|celular|mobile|whatsapp|fone|móvil|電話|전화)\s*:?\s*[\d\s\-\(\)\+]+', 
                re.IGNORECASE), PIISeverity.WARN, PIIType.PHONE),
]


# ========== EMAILS ==========
EMAIL_PATTERNS: List[Tuple[re.Pattern, PIISeverity, PIIType]] = [
    # Email padrão (universal)
    (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'), 
     PIISeverity.WARN, PIIType.EMAIL),
    
    # Email com palavras-chave (múltiplos idiomas)
    (re.compile(r'\b(email|e-mail|correio|mail|correo|mél|e-post|posta|メール|이메일)\s*:?\s*[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}', 
                re.IGNORECASE), PIISeverity.WARN, PIIType.EMAIL),
    
    # Email mascarado: j***@email.com
    (re.compile(r'\b[A-Za-z0-9_]{1,3}[*#X]{2,}[A-Za-z0-9_]*@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'), 
     PIISeverity.WARN, PIIType.EMAIL),
]


# ========== DOCUMENTOS DE IDENTIFICAÇÃO (INTERNACIONAL) ==========
ID_NUMBER_PATTERNS: List[Tuple[re.Pattern, PIISeverity, PIIType]] = [
    # CPF (Brasil): 123.456.789-00
    (re.compile(r'\b\d{3}\.\d{3}\.\d{3}-\d{2}\b'), PIISeverity.BLOCK, PIIType.ID_NUMBER),
    (re.compile(r'\b(cpf)\s*:?\s*[\d\.\-]+', re.IGNORECASE), PIISeverity.BLOCK, PIIType.ID_NUMBER),
    
    # CNPJ (Brasil): 12.345.678/0001-90
    (re.compile(r'\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b'), PIISeverity.BLOCK, PIIType.ID_NUMBER),
    (re.compile(r'\b(cnpj)\s*:?\s*[\d\.\/\-]+', re.IGNORECASE), PIISeverity.BLOCK, PIIType.ID_NUMBER),
    
    # SSN (EUA): 123-45-6789
    (re.compile(r'\b\d{3}-\d{2}-\d{4}\b'), PIISeverity.BLOCK, PIIType.SSN),
    (re.compile(r'\b(ssn|social\s+security\s+number)\s*:?\s*[\d\-]+', re.IGNORECASE), 
     PIISeverity.BLOCK, PIIType.SSN),
    
    # NIF (Portugal/Espanha): 123456789 ou 12345678Z
    (re.compile(r'\b\d{8,9}[A-Z]?\b'), PIISeverity.WARN, PIIType.TAX_ID),
    (re.compile(r'\b(nif|número\s+de\s+identificação\s+fiscal)\s*:?\s*[\dA-Z]+', re.IGNORECASE), 
     PIISeverity.INFO, PIIType.TAX_ID),
    
    # DNI (Espanha): 12345678A
    (re.compile(r'\b\d{8}[A-Z]\b'), PIISeverity.WARN, PIIType.ID_NUMBER),
    (re.compile(r'\b(dni|documento\s+nacional\s+de\s+identidad)\s*:?\s*[\dA-Z]+', re.IGNORECASE), 
     PIISeverity.BLOCK, PIIType.ID_NUMBER),
    
    # NIE (Espanha): X1234567L
    (re.compile(r'\b[XYZ]\d{7}[A-Z]\b'), PIISeverity.WARN, PIIType.ID_NUMBER),
    (re.compile(r'\b(nie|número\s+de\s+identidad\s+de\s+extranjero)\s*:?\s*[XYZ\dA-Z]+', re.IGNORECASE), 
     PIISeverity.BLOCK, PIIType.ID_NUMBER),
    
    # NIN (UK): AB 12 34 56 C
    (re.compile(r'\b[A-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-Z]\b'), PIISeverity.BLOCK, PIIType.ID_NUMBER),
    (re.compile(r'\b(nin|national\s+insurance\s+number)\s*:?\s*[A-Z\d\s]+', re.IGNORECASE), 
     PIISeverity.BLOCK, PIIType.ID_NUMBER),
    
    # PPS (Irlanda): 1234567T ou 1234567TW
    (re.compile(r'\b\d{7}[A-Z]{1,2}\b'), PIISeverity.WARN, PIIType.TAX_ID),
    (re.compile(r'\b(pps|personal\s+public\s+service\s+number)\s*:?\s*[\dA-Z]+', re.IGNORECASE), 
     PIISeverity.BLOCK, PIIType.TAX_ID),
    
    # Personal Number (Suécia/Noruega): YYMMDD-XXXX ou YYMMDDXXXX
    (re.compile(r'\b\d{6}-?\d{4}\b'), PIISeverity.WARN, PIIType.ID_NUMBER),
    (re.compile(r'\b(personnummer|personal\s+number|henkilötunnus)\s*:?\s*[\d\-]+', re.IGNORECASE), 
     PIISeverity.BLOCK, PIIType.ID_NUMBER),
    
    # CPR (Dinamarca): DDMMYY-XXXX
    (re.compile(r'\b(cpr|cpr-nummer)\s*:?\s*\d{6}-?\d{4}', re.IGNORECASE), 
     PIISeverity.BLOCK, PIIType.ID_NUMBER),
    
    # TIN (Tax Identification Number - vários países)
    (re.compile(r'\b(tin|tax\s+id|tax\s+identification\s+number|número\s+de\s+identificación\s+fiscal|steuernummer|numéro\s+fiscal)\s*:?\s*[\dA-Z\-]+', 
                re.IGNORECASE), PIISeverity.BLOCK, PIIType.TAX_ID),
    
    # RG (Brasil): 12.345.678-9 ou variações
    (re.compile(r'\b\d{1,2}\.?\d{3}\.?\d{3}-?\d{1,2}\b'), PIISeverity.WARN, PIIType.ID_NUMBER),
    (re.compile(r'\b(rg|registro\s+geral|identity\s+card)\s*:?\s*[\d\.\-]+', re.IGNORECASE), 
     PIISeverity.BLOCK, PIIType.ID_NUMBER),
    
    # Passport (formato genérico): A1234567 ou 12AB34567
    (re.compile(r'\b[A-Z]{1,2}\d{6,9}\b'), PIISeverity.WARN, PIIType.PASSPORT),
    (re.compile(r'\b(passport|passaporte|pasaporte|passeport|パスポート|여권)\s*(number|número|numéro)?\s*:?\s*[A-Z\d]+', 
                re.IGNORECASE), PIISeverity.BLOCK, PIIType.PASSPORT),
    
    # Driver's License (vários países)
    (re.compile(r'\b(driver\'?s?\s+license|driving\s+license|carteira\s+de\s+habilitação|permis\s+de\s+conduire|führerschein|carnet\s+de\s+conducir|運転免許証)\s*(number|número|numéro)?\s*:?\s*[A-Z\d\s\-]+', 
                re.IGNORECASE), PIISeverity.BLOCK, PIIType.DRIVER_LICENSE),
    
    # Aadhaar (Índia): 1234 5678 9012
    (re.compile(r'\b\d{4}\s?\d{4}\s?\d{4}\b'), PIISeverity.WARN, PIIType.ID_NUMBER),
    (re.compile(r'\b(aadhaar|आधार)\s*(number|número)?\s*:?\s*[\d\s]+', re.IGNORECASE), 
     PIISeverity.BLOCK, PIIType.ID_NUMBER),
    
    # My Number (Japão): 1234-5678-9012
    (re.compile(r'\b\d{4}-?\d{4}-?\d{4}\b'), PIISeverity.WARN, PIIType.ID_NUMBER),
    (re.compile(r'\b(my\s+number|マイナンバー)\s*:?\s*[\d\-]+', re.IGNORECASE), 
     PIISeverity.BLOCK, PIIType.ID_NUMBER),
    
    # Documentos genéricos com palavras-chave
    (re.compile(r'\b(id\s+number|número\s+de\s+identificação|documento\s+de\s+identidade|identity\s+document|ausweis|carta\s+de\s+identidad|身分証明書)\s*:?\s*[\dA-Z\s\-\.]+', 
                re.IGNORECASE), PIISeverity.WARN, PIIType.ID_NUMBER),
]


# ========== CARTÃO DE CRÉDITO ==========
CREDIT_CARD_PATTERNS: List[Tuple[re.Pattern, PIISeverity, PIIType]] = [
    # Cartão formatado: 1234 5678 9012 3456 ou 1234-5678-9012-3456
    (re.compile(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b'), PIISeverity.BLOCK, PIIType.CREDIT_CARD),
    # Cartão sem espaços: 1234567890123456
    (re.compile(r'\b\d{13,19}\b'), PIISeverity.WARN, PIIType.CREDIT_CARD),  # Pode ser falso positivo
    
    # Palavras-chave (múltiplos idiomas)
    (re.compile(r'\b(cartão|card|credit\s+card|débito|debit|tarjeta|karte|carte|kort|クレジットカード|신용카드)\s*:?\s*[\d\s\-]{12,}', 
                re.IGNORECASE), PIISeverity.BLOCK, PIIType.CREDIT_CARD),
    (re.compile(r'\b(cvv|cvc|security\s+code|código\s+de\s+segurança|código\s+de\s+verificación|セキュリティコード)\s*:?\s*\d{3,4}', 
                re.IGNORECASE), PIISeverity.BLOCK, PIIType.CREDIT_CARD),
    (re.compile(r'\b(expiry|expiration|vencimento|validade|fecha\s+de\s+vencimiento|有効期限)\s*:?\s*\d{1,2}[/-]\d{2,4}', 
                re.IGNORECASE), PIISeverity.WARN, PIIType.CREDIT_CARD),
]


# ========== CONTA BANCÁRIA (INTERNACIONAL) ==========
BANK_ACCOUNT_PATTERNS: List[Tuple[re.Pattern, PIISeverity, PIIType]] = [
    # IBAN (Internacional): GB82 WEST 1234 5698 7654 32
    (re.compile(r'\b[A-Z]{2}\d{2}[\s-]?[A-Z0-9]{4}[\s-]?[A-Z0-9]{4}[\s-]?[A-Z0-9]{4}[\s-]?[A-Z0-9]{4}[\s-]?[A-Z0-9]{0,4}\b'), 
     PIISeverity.BLOCK, PIIType.BANK_ACCOUNT),
    
    # IBAN compacto: GB82WEST12345698765432
    (re.compile(r'\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b'), PIISeverity.BLOCK, PIIType.BANK_ACCOUNT),
    
    # SWIFT/BIC: ABCDGB2L
    (re.compile(r'\b[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?\b'), PIISeverity.BLOCK, PIIType.BANK_ACCOUNT),
    
    # Conta bancária brasileira: 12345-6
    (re.compile(r'\b\d{4,10}-?\d{1,2}\b'), PIISeverity.WARN, PIIType.BANK_ACCOUNT),
    
    # Routing numbers (EUA): 123456789
    (re.compile(r'\b(routing\s+number|aba)\s*:?\s*\d{9}', re.IGNORECASE), 
     PIISeverity.BLOCK, PIIType.BANK_ACCOUNT),
    
    # Agência/Código bancário
    (re.compile(r'\b(agência|agencia|agency|branch|sucursal|filiale|支店)\s*:?\s*\d{4,10}', 
                re.IGNORECASE), PIISeverity.WARN, PIIType.BANK_ACCOUNT),
    
    # Palavras-chave (múltiplos idiomas)
    (re.compile(r'\b(conta\s+bancária|bank\s+account|account\s+number|compte\s+bancaire|cuenta\s+bancaria|bankkonto|口座|계좌)\s*:?\s*[\d\-\s]+', 
                re.IGNORECASE), PIISeverity.BLOCK, PIIType.BANK_ACCOUNT),
    (re.compile(r'\b(routing\s+number|aba|swift|bic|iban)\s*:?\s*[\d\w\s\-]+', 
                re.IGNORECASE), PIISeverity.BLOCK, PIIType.BANK_ACCOUNT),
    (re.compile(r'\b(sort\s+code|bank\s+code|código\s+bancário|銀行コード)\s*:?\s*[\d\-\s]+', 
                re.IGNORECASE), PIISeverity.BLOCK, PIIType.BANK_ACCOUNT),
]


# ========== SENHAS E TOKENS ==========
PASSWORD_PATTERNS: List[Tuple[re.Pattern, PIISeverity, PIIType]] = [
    # Palavras-chave explícitas (múltiplos idiomas)
    (re.compile(r'\b(senha|password|passwd|pwd|contraseña|mot\s+de\s+passe|passwort|parola|パスワード|비밀번호)\s*:?\s*[^\s]{4,}', 
                re.IGNORECASE), PIISeverity.BLOCK, PIIType.PASSWORD),
    (re.compile(r'\b(password|senha|contraseña|mot\s+de\s+passe|passwort)\s*=\s*[^\s]+', 
                re.IGNORECASE), PIISeverity.BLOCK, PIIType.PASSWORD),
    (re.compile(r'\b(secret|secret_key|api_key|token|access_token|bearer\s+token)\s*:?\s*[A-Za-z0-9_\-]{10,}', 
                re.IGNORECASE), PIISeverity.BLOCK, PIIType.PASSWORD),
    
    # JWT tokens
    (re.compile(r'\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b'), 
     PIISeverity.BLOCK, PIIType.SESSION_TOKEN),
    
    # Session IDs, cookies
    (re.compile(r'\b(session|sessionid|cookie|auth)\s*:?\s*[A-Za-z0-9_\-]{20,}', 
                re.IGNORECASE), PIISeverity.BLOCK, PIIType.SESSION_TOKEN),
]


# ========== ENDEREÇOS (INTERNACIONAL) ==========
ADDRESS_PATTERNS: List[Tuple[re.Pattern, PIISeverity, PIIType]] = [
    # Endereço com número (múltiplos idiomas)
    (re.compile(r'\b(rua|avenida|av\.?|street|st\.?|road|rd\.?|avenue|ave\.?|strasse|rue|calle|via|straat|通り|거리)\s+[^,]+,\s*\d+', 
                re.IGNORECASE), PIISeverity.WARN, PIIType.ADDRESS),
    
    # CEP (Brasil): 12345-678
    (re.compile(r'\b\d{5}-?\d{3}\b'), PIISeverity.WARN, PIIType.ADDRESS),
    (re.compile(r'\b(cep|zip\s+code|postal\s+code|código\s+postal|postleitzahl|code\s+postal|郵便番号|우편번호)\s*:?\s*\d{5}[\s-]?\d{3}', 
                re.IGNORECASE), PIISeverity.WARN, PIIType.ADDRESS),
    
    # ZIP Code (EUA): 12345 ou 12345-6789
    (re.compile(r'\b\d{5}(-\d{4})?\b'), PIISeverity.WARN, PIIType.ADDRESS),
    
    # Postcode (UK): SW1A 1AA, M1 1AA
    (re.compile(r'\b[A-Z]{1,2}\d{1,2}\s?\d[A-Z]{2}\b'), PIISeverity.WARN, PIIType.ADDRESS),
    
    # Postcode (França): 75001
    (re.compile(r'\b(postcode|code\s+postal)\s*:?\s*\d{5}', re.IGNORECASE), 
     PIISeverity.WARN, PIIType.ADDRESS),
    
    # Postcode (Alemanha): 10115
    (re.compile(r'\b(postleitzahl|plz)\s*:?\s*\d{5}', re.IGNORECASE), 
     PIISeverity.WARN, PIIType.ADDRESS),
    
    # Endereço completo com palavras-chave (múltiplos idiomas)
    (re.compile(r'\b(endereço|address|morada|residência|residence|dirección|adresse|wohnort|indirizzo|住所|주소)\s*:?\s*[^\n]{10,}', 
                re.IGNORECASE), PIISeverity.WARN, PIIType.ADDRESS),
    
    # Combinações: número + rua + cidade
    (re.compile(r'\b\d+\s+(street|st|road|rd|avenue|ave|rua|avenida|calle|rue|strasse)\s+[A-Za-z\s]+', 
                re.IGNORECASE), PIISeverity.WARN, PIIType.ADDRESS),
]


# ========== NOMES ==========
NAME_PATTERNS: List[Tuple[re.Pattern, PIISeverity, PIIType]] = [
    # Padrão de nome completo (2+ palavras capitalizadas): João Silva, John Smith, Jean Dupont
    # Suporta acentos e caracteres especiais
    (re.compile(r'\b[A-ZÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÃÕÇÄÖÜÑ][a-záéíóúàèìòùâêîôûãõçäöüñ]+\s+[A-ZÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÃÕÇÄÖÜÑ][a-záéíóúàèìòùâêîôûãõçäöüñ]+(?:\s+[A-ZÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÃÕÇÄÖÜÑ][a-záéíóúàèìòùâêîôûãõçäöüñ]+)*'), 
     PIISeverity.WARN, PIIType.NAME),  # Pode ter falsos positivos
    
    # Nome com palavras-chave explícitas (múltiplos idiomas)
    (re.compile(r'\b(nome|name|nome\s+completo|full\s+name|nombre\s+completo|nom\s+complet|vollständiger\s+name|名前|이름)\s*:?\s*[A-ZÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÃÕÇÄÖÜÑ][a-záéíóúàèìòùâêîôûãõçäöüñ]+(?:\s+[A-ZÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÃÕÇÄÖÜÑ][a-záéíóúàèìòùâêîôûãõçäöüñ]+)+', 
                re.IGNORECASE), PIISeverity.BLOCK, PIIType.NAME),
    (re.compile(r'\b(meu\s+nome|my\s+name|mi\s+nombre|mon\s+nom|ich\s+heiße|chamo-me|i\s+am|私の名前は)\s+[A-ZÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÃÕÇÄÖÜÑ][a-záéíóúàèìòùâêîôûãõçäöüñ]+', 
                re.IGNORECASE), PIISeverity.WARN, PIIType.NAME),
    
    # Primeiro nome + sobrenome com contexto
    (re.compile(r'\b(first\s+name|primer\s+nombre|prénom|vorname|primeiro\s+nome|名)\s+[A-ZÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÃÕÇÄÖÜÑ][a-záéíóúàèìòùâêîôûãõçäöüñ]+\s+(last\s+name|apellido|nom\s+de\s+famille|nachname|sobrenome|姓)', 
                re.IGNORECASE), PIISeverity.BLOCK, PIIType.NAME),
    
    # Nome mascarado: João S***
    (re.compile(r'\b[A-ZÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÃÕÇÄÖÜÑ][a-záéíóúàèìòùâêîôûãõçäöüñ]+\s+[A-ZÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÃÕÇÄÖÜÑ][*#X]{2,}', 
                re.IGNORECASE), PIISeverity.WARN, PIIType.NAME),
]


# ========== DATA DE NASCIMENTO ==========
DATE_OF_BIRTH_PATTERNS: List[Tuple[re.Pattern, PIISeverity, PIIType]] = [
    # Data com palavras-chave (múltiplos idiomas)
    (re.compile(r'\b(data\s+de\s+nascimento|date\s+of\s+birth|fecha\s+de\s+nacimiento|date\s+de\s+naissance|geburtsdatum|data\s+di\s+nascita|born|nascido|nacido|né|生年月日|생년월일)\s*:?\s*\d{1,2}[/-]\d{1,2}[/-]\d{2,4}', 
                re.IGNORECASE), PIISeverity.WARN, PIIType.DATE_OF_BIRTH),
    (re.compile(r'\b(idade|age|edad|âge|alter|年齢|나이)\s*:?\s*\d{1,3}\s*(anos|years|años|ans|jahre|歳)', 
                re.IGNORECASE), PIISeverity.INFO, PIIType.DATE_OF_BIRTH),
    
    # Datas em formato europeu/americano com contexto
    (re.compile(r'\b(born|né|nacido)\s+(on|em|en|le)?\s*\d{1,2}[/-]\d{1,2}[/-]\d{2,4}', 
                re.IGNORECASE), PIISeverity.WARN, PIIType.DATE_OF_BIRTH),
]


# ========== IP ADDRESS ==========
IP_ADDRESS_PATTERNS: List[Tuple[re.Pattern, PIISeverity, PIIType]] = [
    # IPv4
    (re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b'), PIISeverity.INFO, PIIType.IP_ADDRESS),
    # IPv6
    (re.compile(r'\b([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b'), PIISeverity.INFO, PIIType.IP_ADDRESS),
    (re.compile(r'\b([0-9a-fA-F]{1,4}:){1,7}:\b'), PIISeverity.INFO, PIIType.IP_ADDRESS),  # IPv6 compacto
]


# ========== PLACA DE VEÍCULO (INTERNACIONAL) ==========
LICENSE_PLATE_PATTERNS: List[Tuple[re.Pattern, PIISeverity, PIIType]] = [
    # Placa brasileira antiga: ABC-1234
    (re.compile(r'\b[A-Z]{3}-?\d{4}\b'), PIISeverity.WARN, PIIType.LICENSE_PLATE),
    # Placa Mercosul: ABC1D23
    (re.compile(r'\b[A-Z]{3}\d[A-Z]\d{2}\b'), PIISeverity.WARN, PIIType.LICENSE_PLATE),
    
    # UK: AB12 CDE ou AB12CDE
    (re.compile(r'\b[A-Z]{2}\d{2}\s?[A-Z]{3}\b'), PIISeverity.WARN, PIIType.LICENSE_PLATE),
    
    # EUA/Canadá: ABC-123 ou ABC123
    (re.compile(r'\b[A-Z]{1,3}-?\d{1,4}\b'), PIISeverity.WARN, PIIType.LICENSE_PLATE),
    
    # Europa (vários formatos): AB-123-CD, 1-ABC-234
    (re.compile(r'\b\d{0,2}-?[A-Z]{1,3}-?\d{1,4}-?[A-Z]{0,3}\b'), PIISeverity.WARN, PIIType.LICENSE_PLATE),
    
    # Japão: 品川 500 あ 1234
    (re.compile(r'\b[あ-ん]{1,2}\s?\d{1,4}\s?[あ-ん]\s?\d{1,4}\b'), PIISeverity.WARN, PIIType.LICENSE_PLATE),
    
    # Com palavra-chave (múltiplos idiomas)
    (re.compile(r'\b(placa|license\s+plate|matrícula|numéro\s+de\s+plaque|kennzeichen|targa|ナンバープレート|차량번호)\s*:?\s*[A-Z\d\s\-あ-ん]+', 
                re.IGNORECASE), PIISeverity.WARN, PIIType.LICENSE_PLATE),
]


# ========== COORDENADAS GPS ==========
GPS_PATTERNS: List[Tuple[re.Pattern, PIISeverity, PIIType]] = [
    # Latitude/Longitude: 40.7128, -74.0060
    (re.compile(r'\b-?\d{1,3}\.\d{4,10},\s*-?\d{1,3}\.\d{4,10}\b'), 
     PIISeverity.WARN, PIIType.GPS),
    # Com palavras-chave
    (re.compile(r'\b(latitude|longitude|gps|coordinates|coordenadas|location|座標|좌표)\s*:?\s*-?\d{1,3}\.\d+', 
                re.IGNORECASE), PIISeverity.WARN, PIIType.GPS),
    # Google Maps / Apple Maps links
    (re.compile(r'\b(google\.com/maps|maps\.apple\.com|goo\.gl/maps)\S+', re.IGNORECASE), 
     PIISeverity.WARN, PIIType.GPS),
]


# ========== MAC ADDRESSES ==========
MAC_ADDRESS_PATTERNS: List[Tuple[re.Pattern, PIISeverity, PIIType]] = [
    # MAC: 00:1B:44:11:3A:B7 ou 00-1B-44-11-3A-B7
    (re.compile(r'\b([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})\b'), 
     PIISeverity.INFO, PIIType.MAC_ADDRESS),
]


# ========== UUIDs ==========
UUID_PATTERNS: List[Tuple[re.Pattern, PIISeverity, PIIType]] = [
    # UUID: 550e8400-e29b-41d4-a716-446655440000
    (re.compile(r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b'), 
     PIISeverity.INFO, PIIType.UUID),
    # UUID sem hífens
    (re.compile(r'\b[0-9a-fA-F]{32}\b'), PIISeverity.INFO, PIIType.UUID),
]


# ========== DADOS CODIFICADOS (BYPASS) ==========
ENCODED_DATA_PATTERNS: List[Tuple[re.Pattern, PIISeverity, PIIType]] = [
    # Base64 (pode esconder PII) - strings longas
    (re.compile(r'\b[A-Za-z0-9+/]{30,}={0,2}\b'), PIISeverity.WARN, PIIType.ID_NUMBER),
    # Hex encoding
    (re.compile(r'\b(0x|\\x)[0-9a-fA-F]{8,}\b'), PIISeverity.WARN, PIIType.ID_NUMBER),
    # URL encoding de dados sensíveis
    (re.compile(r'%[0-9A-F]{2}%[0-9A-F]{2}%[0-9A-F]{2}%[0-9A-F]{2}'), 
     PIISeverity.WARN, PIIType.ID_NUMBER),
    # HTML entities
    (re.compile(r'&#x?[0-9a-fA-F]{2,4};'), PIISeverity.INFO, PIIType.ID_NUMBER),
]


# ========== DADOS PARCIALMENTE MASCARADOS ==========
MASKED_DATA_PATTERNS: List[Tuple[re.Pattern, PIISeverity, PIIType]] = [
    # Telefone mascarado: (11) 9****-4321
    (re.compile(r'[\d\(\)\s-]{3,}[*#X]{2,}[\d\s-]{3,}'), PIISeverity.WARN, PIIType.PHONE),
    # CPF/SSN mascarado: 123.***.***-45
    (re.compile(r'\d{1,3}[*#X\.]{2,}\d{1,3}[*#X\.]{2,}\d{1,3}'), PIISeverity.WARN, PIIType.ID_NUMBER),
]


# ========== NÚMEROS DE SEGURO SAÚDE ==========
HEALTH_INSURANCE_PATTERNS: List[Tuple[re.Pattern, PIISeverity, PIIType]] = [
    # Medicare (EUA): 123-45-6789-A
    (re.compile(r'\b\d{3}-\d{2}-\d{4}-[A-Z]\b'), PIISeverity.BLOCK, PIIType.MEDICAL),
    # NHS Number (UK): 485 777 3456
    (re.compile(r'\b(nhs\s+number)\s*:?\s*\d{3}\s?\d{3}\s?\d{4}', re.IGNORECASE), 
     PIISeverity.BLOCK, PIIType.MEDICAL),
    # Palavras-chave
    (re.compile(r'\b(health\s+insurance|seguro\s+de\s+saúde|seguro\s+médico|krankenversicherung|assurance\s+maladie|健康保険|건강보험)\s*(number|número|numéro)?\s*:?\s*[\d\s\-A-Z]+', 
                re.IGNORECASE), PIISeverity.BLOCK, PIIType.MEDICAL),
]


# ========== DADOS PROTEGIDOS POR GDPR ==========
GDPR_SENSITIVE_PATTERNS: List[Tuple[re.Pattern, PIISeverity, PIIType]] = [
    # Dados de crianças
    (re.compile(r'\b(child|children|kid|kids|menor|menores|niño|niños|enfant|enfants|kind|kinder|子供|아이)\s+(name|nome|nombre|nom|data|date|information|informação|información)', 
                re.IGNORECASE), PIISeverity.BLOCK, PIIType.GDPR_SENSITIVE),
    # Dados raciais/étnicos
    (re.compile(r'\b(race|ethnicity|raça|etnia|origine\s+ethnique|etnicidad|人種|인종)\s*:?\s*[^\n]+', 
                re.IGNORECASE), PIISeverity.BLOCK, PIIType.GDPR_SENSITIVE),
    # Orientação sexual
    (re.compile(r'\b(sexual\s+orientation|orientação\s+sexual|orientación\s+sexual|orientation\s+sexuelle|性的指向)\s*:?\s*[^\n]+', 
                re.IGNORECASE), PIISeverity.BLOCK, PIIType.GDPR_SENSITIVE),
    # Dados religiosos
    (re.compile(r'\b(religion|religião|religión|religion|宗教|종교)\s*:?\s*[^\n]+', 
                re.IGNORECASE), PIISeverity.WARN, PIIType.GDPR_SENSITIVE),
    # Dados políticos
    (re.compile(r'\b(political\s+affiliation|afiliação\s+política|afiliación\s+política|政治的信条)\s*:?\s*[^\n]+', 
                re.IGNORECASE), PIISeverity.WARN, PIIType.GDPR_SENSITIVE),
    # Dados biométricos
    (re.compile(r'\b(biometric|biométrico|biométrique|生体認証|생체인식)\s+(data|dados|données|データ)', 
                re.IGNORECASE), PIISeverity.BLOCK, PIIType.BIOMETRIC),
]


# ========== DADOS MÉDICOS ==========
MEDICAL_PATTERNS: List[Tuple[re.Pattern, PIISeverity, PIIType]] = [
    # Palavras-chave médicas sensíveis (múltiplos idiomas)
    (re.compile(r'\b(prontuário|medical\s+record|histórico\s+médico|historial\s+médico|dossier\s+médical|krankenakte|diagnóstico|diagnosis|診断書|진단서)\s*:?\s*[^\n]+', 
                re.IGNORECASE), PIISeverity.BLOCK, PIIType.MEDICAL),
    (re.compile(r'\b(cpf|rg|documento|ssn|id)\s+(do|of|de|du)\s+(paciente|patient|paziente|患者)', 
                re.IGNORECASE), PIISeverity.BLOCK, PIIType.MEDICAL),
    (re.compile(r'\b(patient\s+name|nome\s+do\s+paciente|nombre\s+del\s+paciente|nom\s+du\s+patient|患者名)\s*:?\s*[A-ZÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÃÕÇÄÖÜÑ][a-záéíóúàèìòùâêîôûãõçäöüñ]+', 
                re.IGNORECASE), PIISeverity.BLOCK, PIIType.MEDICAL),
]


# ========== DADOS FINANCEIROS ==========
FINANCIAL_PATTERNS: List[Tuple[re.Pattern, PIISeverity, PIIType]] = [
    # Salário, renda (múltiplos idiomas)
    (re.compile(r'\b(salário|salary|renda|income|sueldo|salaire|gehalt|stipendio|給与|급여)\s+(de|of|del|du|von|di)\s+[A-ZÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÃÕÇÄÖÜÑ][a-záéíóúàèìòùâêîôûãõçäöüñ]+', 
                re.IGNORECASE), PIISeverity.WARN, PIIType.FINANCIAL),
    # Dados bancários combinados
    (re.compile(r'\b(banco|bank|banque|banca|banka|銀行|은행)\s+[\w\s]+(conta|account|compte|cuenta|conto|口座)\s+[\d\-]+', 
                re.IGNORECASE), PIISeverity.WARN, PIIType.FINANCIAL),
    # Informações de salário com nome
    (re.compile(r'\b(salary|salário|wage|salario)\s+of\s+[A-ZÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÃÕÇÄÖÜÑ][a-záéíóúàèìòùâêîôûãõçäöüñ]+\s+is\s+\$?\d+', 
                re.IGNORECASE), PIISeverity.INFO, PIIType.FINANCIAL),
]


# ========== DADOS DE FUNCIONÁRIOS ==========
EMPLOYEE_DATA_PATTERNS: List[Tuple[re.Pattern, PIISeverity, PIIType]] = [
    # Solicitações de dados de funcionários
    (re.compile(r'\b(employee|funcionário|empleado|employé|mitarbeiter|dipendente|従業員|직원)\s+(name|nome|nombre|nom|data|date|information|informação|información|salary|salário)', 
                re.IGNORECASE), PIISeverity.INFO, PIIType.NAME),
    # Dados de RH
    (re.compile(r'\b(hr\s+data|dados\s+de\s+rh|human\s+resources|recursos\s+humanos|人事データ)\s+of\s+[A-ZÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÃÕÇÄÖÜÑ][a-záéíóúàèìòùâêîôûãõçäöüñ]+', 
                re.IGNORECASE), PIISeverity.INFO, PIIType.NAME),
]


# ========== TIMESTAMPS SENSÍVEIS ==========
SENSITIVE_TIMESTAMP_PATTERNS: List[Tuple[re.Pattern, PIISeverity, PIIType]] = [
    # Timestamps que podem identificar usuários (login times, etc.)
    (re.compile(r'\b(last\s+login|último\s+acesso|dernier\s+accès|letzter\s+zugriff|最終ログイン)\s*:?\s*\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}', 
                re.IGNORECASE), PIISeverity.WARN, PIIType.ID_NUMBER),
    # Padrões de atividade
    (re.compile(r'\b(activity\s+log|histórico\s+de\s+atividade|log\s+d\'activité|アクティビティログ)\s+of\s+[A-ZÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÃÕÇÄÖÜÑ][a-záéíóúàèìòùâêîôûãõçäöüñ]+', 
                re.IGNORECASE), PIISeverity.WARN, PIIType.ID_NUMBER),
]


# ========== PADRÕES EM DADOS ESTRUTURADOS ==========
STRUCTURED_DATA_PATTERNS: List[Tuple[re.Pattern, PIISeverity, PIIType]] = [
    # JSON com campos sensíveis
    (re.compile(r'["\'](name|email|phone|address|cpf|ssn|nif|dni|telephone|telefone|endereço|dirección)\s*["\']\s*:\s*["\']?[^"\']+["\']?', 
                re.IGNORECASE), PIISeverity.WARN, PIIType.NAME),
    # CSV com colunas sensíveis
    (re.compile(r'\b(name|email|phone|address|cpf|ssn|nif|dni),', re.IGNORECASE), 
     PIISeverity.INFO, PIIType.NAME),
    # XML com tags sensíveis
    (re.compile(r'<(name|email|phone|address|cpf|ssn|nif|dni)>[^<]+</(name|email|phone|address|cpf|ssn|nif|dni)>', 
                re.IGNORECASE), PIISeverity.WARN, PIIType.NAME),
]


# ========== PADRÕES DE CONTEXTO (COMBINAÇÕES) ==========
CONTEXTUAL_PII_PATTERNS: List[Tuple[re.Pattern, PIISeverity, PIIType]] = [
    # Nome + Email juntos
    (re.compile(r'[A-ZÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÃÕÇÄÖÜÑ][a-záéíóúàèìòùâêîôûãõçäöüñ]+\s+[A-ZÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÃÕÇÄÖÜÑ][a-záéíóúàèìòùâêîôûãõçäöüñ]+\s+[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}'), 
     PIISeverity.BLOCK, PIIType.NAME),
    # Nome + Telefone juntos
    (re.compile(r'[A-ZÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÃÕÇÄÖÜÑ][a-záéíóúàèìòùâêîôûãõçäöüñ]+\s+[A-ZÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÃÕÇÄÖÜÑ][a-záéíóúàèìòùâêîôûãõçäöüñ]+\s+[\d\s\-\(\)\+]{10,}'), 
     PIISeverity.BLOCK, PIIType.NAME),
    # Email + Telefone juntos
    (re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\s+[\d\s\-\(\)\+]{10,}'), 
     PIISeverity.BLOCK, PIIType.EMAIL),
    # Nome + Endereço
    (re.compile(r'[A-ZÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÃÕÇÄÖÜÑ][a-záéíóúàèìòùâêîôûãõçäöüñ]+\s+[A-ZÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÃÕÇÄÖÜÑ][a-záéíóúàèìòùâêîôûãõçäöüñ]+\s+\d+\s+(street|st|road|rd|avenue|rua|calle|rue|strasse)', 
                re.IGNORECASE), PIISeverity.BLOCK, PIIType.NAME),

    # Nome + Valor Monetário (Salário/Crédito vazado)
    # Ex: "John Doe - $50,000", "Maria Silva: R$ 5.000,00"
    (re.compile(r'[A-ZÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÃÕÇÄÖÜÑ][a-záéíóúàèìòùâêîôûãõçäöüñ]+\s+[A-ZÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÃÕÇÄÖÜÑ][a-záéíóúàèìòùâêîôûãõçäöüñ]+.*[\$€£]|[\$€£].*[A-ZÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÃÕÇÄÖÜÑ][a-záéíóúàèìòùâêîôûãõçäöüñ]+\s+[A-ZÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÃÕÇÄÖÜÑ][a-záéíóúàèìòùâêîôûãõçäöüñ]+', 
                re.IGNORECASE), PIISeverity.BLOCK, PIIType.FINANCIAL),
]


# ========== TERMOS E PALAVRAS-CHAVE DE TENTATIVA DE ACESSO ==========
PII_REQUEST_PATTERNS: List[Tuple[re.Pattern, PIISeverity, PIIType]] = [
    # Solicitações explícitas de dados pessoais (múltiplos idiomas)
    (re.compile(r'\b(mostre|show|list|liste|exiba|display|muestre|afficher|zeigen|mostrare|表示|보여)\s+(?:os\s+|as\s+|o\s+|a\s+|les\s+|die\s+|gli\s+)?(nomes|names|telefones|phones|emails|endereços|addresses|nombres|téléphones|adresses|namen|telefone|indirizzi)', 
                re.IGNORECASE), PIISeverity.INFO, PIIType.NAME),
    
    (re.compile(r'\b(quero|want|need|preciso|quiero|besoin|brauche|ho\s+bisogno|欲しい|원해)\s+(?:ver|see|saber|know|voir|sehen|vedere|見る|보고)\s+(?:os\s+|as\s+|o\s+|a\s+|les\s+|die\s+|gli\s+)?(dados\s+pessoais|personal\s+data|información\s+personal|données\s+personnelles|persönliche\s+daten|dati\s+personali)', 
                re.IGNORECASE), PIISeverity.WARN, PIIType.NAME),
    
    (re.compile(r'\b(mostre|show|list|liste)\s+(?:todos\s+|all\s+|tous\s+|alle\s+|tutti\s+|すべて|모든)\s+(clientes|customers|clientes|clients|kunden|clienti|顧客|고객)\s+(?:com|with|avec|mit|con|と|와)\s+(?:seus|their|leurs|ihre|loro|彼らの|그들의)\s+(?:nomes|names|nombres|noms|namen|nomi)', 
                re.IGNORECASE), PIISeverity.WARN, PIIType.NAME),
    
    (re.compile(r'\b(select|selecione|seleccionar|sélectionner|選択|선택)\s+.*\b(name|nome|nombre|nom|telephone|telefone|email|address|endereço|dirección|adresse)\b', 
                re.IGNORECASE), PIISeverity.WARN, PIIType.NAME),
    
    # Tentativas de buscar dados de usuários específicos
    (re.compile(r'\b(where|onde|dónde|où|wo|dove|どこ|어디서)\s+.*\b(name|nome|nombre|nom)\s*=\s*[\'"]?[A-ZÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÃÕÇÄÖÜÑ][a-záéíóúàèìòùâêîôûãõçäöüñ]+', 
                re.IGNORECASE), PIISeverity.INFO, PIIType.NAME),
    
    # Solicitações de informações de contato
    (re.compile(r'\b(contact\s+information|informações\s+de\s+contato|información\s+de\s+contacto|coordonnées|kontaktinformationen|informazioni\s+di\s+contatto|連絡先情報|연락처정보)\b', 
                re.IGNORECASE), PIISeverity.INFO, PIIType.NAME),
    
    # Solicitações de lista de emails/telefones
    (re.compile(r'\b(list\s+of\s+emails|lista\s+de\s+emails|liste\s+d\'?emails|lista\s+de\s+correos|e-mail-liste|メールリスト|이메일목록)\b', 
                re.IGNORECASE), PIISeverity.WARN, PIIType.EMAIL),
    
    (re.compile(r'\b(list\s+of\s+phones|lista\s+de\s+telefones|liste\s+de\s+téléphones|lista\s+de\s+teléfonos|telefonliste|電話リスト|전화번호목록)\b', 
                re.IGNORECASE), PIISeverity.WARN, PIIType.PHONE),

    # Data Dumping / CSV Export Attempts (NEW)
    (re.compile(r'\b(format\s+as\s+csv|csv\s+format|dump\s+rows|export\s+data|formato\s+csv|exportar\s+dados)\b', 
                re.IGNORECASE), PIISeverity.WARN, PIIType.FINANCIAL),

    # Comparative Leakage / "Who is highest" Attempts (NEW)
    (re.compile(r'\b(confirm\s+if|verify\s+if)\s+.*(highest|lowest|top|best|worst|maior|menor|melhor|pior)', 
                re.IGNORECASE), PIISeverity.WARN, PIIType.NAME),
    (re.compile(r'\b(list|liste|listar)\s+(names|nomes|customers|clientes)\s+(of|de)\s+(top|highest|best|worst)', 
                re.IGNORECASE), PIISeverity.WARN, PIIType.NAME),

    # "List All" / "Full Database" Attempts (NEW)
    (re.compile(r'\b(list|display|show)\s+(all\s+entries|everything|full\s+database|full\s+table|toda\s+a\s+tabela|todos\s+os\s+registros)', 
                re.IGNORECASE), PIISeverity.WARN, PIIType.NAME),
]


# ==================== CONSOLIDAÇÃO DE TODOS OS PADRÕES ====================

# Lista consolidada de todos os padrões PII, organizados por severidade
ALL_PII_PATTERNS: Dict[PIISeverity, List[Tuple[re.Pattern, PIISeverity, PIIType]]] = {
    PIISeverity.BLOCK: [],
    PIISeverity.WARN: [],
    PIISeverity.INFO: [],
}

# Adicionar todos os padrões às listas apropriadas
for pattern_list in [
    PHONE_PATTERNS, EMAIL_PATTERNS, ID_NUMBER_PATTERNS, CREDIT_CARD_PATTERNS,
    BANK_ACCOUNT_PATTERNS, PASSWORD_PATTERNS, ADDRESS_PATTERNS, NAME_PATTERNS,
    DATE_OF_BIRTH_PATTERNS, IP_ADDRESS_PATTERNS, LICENSE_PLATE_PATTERNS,
    MEDICAL_PATTERNS, FINANCIAL_PATTERNS, PII_REQUEST_PATTERNS,
    GPS_PATTERNS, MAC_ADDRESS_PATTERNS, UUID_PATTERNS,
    ENCODED_DATA_PATTERNS, MASKED_DATA_PATTERNS, HEALTH_INSURANCE_PATTERNS,
    GDPR_SENSITIVE_PATTERNS, EMPLOYEE_DATA_PATTERNS, SENSITIVE_TIMESTAMP_PATTERNS,
    STRUCTURED_DATA_PATTERNS, CONTEXTUAL_PII_PATTERNS
]:
    for pattern, severity, pii_type in pattern_list:
        ALL_PII_PATTERNS[severity].append((pattern, severity, pii_type))


def get_all_block_patterns() -> List[Tuple[re.Pattern, PIISeverity, PIIType]]:
    """Retorna todos os padrões que devem bloquear imediatamente"""
    return ALL_PII_PATTERNS[PIISeverity.BLOCK]


def get_all_warn_patterns() -> List[Tuple[re.Pattern, PIISeverity, PIIType]]:
    """Retorna todos os padrões que devem alertar"""
    return ALL_PII_PATTERNS[PIISeverity.WARN]


def get_all_info_patterns() -> List[Tuple[re.Pattern, PIISeverity, PIIType]]:
    """Retorna todos os padrões que devem apenas registrar"""
    return ALL_PII_PATTERNS[PIISeverity.INFO]


def get_patterns_by_type(pii_type: PIIType) -> List[Tuple[re.Pattern, PIISeverity, PIIType]]:
    """Retorna todos os padrões de um tipo específico de PII"""
    all_patterns = []
    for severity_patterns in ALL_PII_PATTERNS.values():
        for pattern, severity, p_type in severity_patterns:
            if p_type == pii_type:
                all_patterns.append((pattern, severity, p_type))
    return all_patterns


def get_all_patterns() -> List[Tuple[re.Pattern, PIISeverity, PIIType]]:
    """Retorna todos os padrões PII (todas as severidades)"""
    all_patterns = []
    for severity_patterns in ALL_PII_PATTERNS.values():
        all_patterns.extend(severity_patterns)
    return all_patterns


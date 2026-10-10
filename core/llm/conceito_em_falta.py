"""Quando os dados nao tem aquilo que se pergunta.

── O que se viu em producao (09/10/2026) ───────────────────────────

Projecto de restauracao: encomendas anonimas, nenhuma coluna de cliente.
A mesma pergunta — «quantos clientes temos?» — teve quatro destinos:

* «Respondo a perguntas sobre os dados do seu negocio… Essa fica de
  fora.» — a mensagem pensada para o tempo em Lisboa;
* «Desea contar los pedidos como aproximacion?» — so em castelhano e
  portugues, porque a rede das contagens so conhecia o ingles;
* ``SELECT COUNT(DISTINCT id) AS customer_count FROM service.orders`` —
  158.340 **encomendas** apresentadas como clientes. O pior dos quatro:
  errado, com ar de certo, e ninguem da por isso;
* e uma vez, por acaso, nada disto.

O Lucas leu-o como um problema de lingua («perguntei em portugues e os
dados estao em castelhano»). Nao era — o castelhano falhou cinco vezes —
mas a lingua tambem entra aqui, e fica tratada no mesmo sitio.

── A regra ─────────────────────────────────────────────────────────

Como fazem o ChatGPT e o Claude a analisar uma folha de calculo: dizer o
que falta, oferecer o mais proximo, e **nunca** dar a uma coisa o nome de
outra. O especialista responde::

    IMPOSSIBLE: MISSING <o que falta> | NEAREST <o mais proximo>

ja escrito na lingua da resposta, e o formatador monta a frase. Sem
segunda chamada ao modelo, e igual na escrita e na voz.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional, Tuple

#: O nome que o modelo entende para cada lingua da app.
_NOMES = {
    "pt": "European Portuguese",
    "es": "Spanish (Spain)",
    "en": "English",
}

_MARCA = re.compile(
    r"^\s*MISSING\s+(?P<falta>.+?)\s*(?:\|\s*NEAREST\s+(?P<proximo>.+?))?\s*$",
    re.IGNORECASE | re.DOTALL,
)


def nome_da_lingua(codigo: Optional[str]) -> str:
    return _NOMES.get((codigo or "en").split("-")[0].lower(), "English")


def _honestidade_e_lingua(state: Mapping[str, Any]) -> str:
    """O bloco do prompt do especialista sobre o que fazer quando falta algo."""
    lingua = nome_da_lingua(state.get("detected_language"))
    return (
        "\n\n🧭 HONESTY ABOUT WHAT THE DATA CONTAINS:\n"
        "- If the user asks about an entity or measure (customers, employees, suppliers, "
        "margin…) and NO table or column in the schema records it, do NOT substitute "
        "another entity. Counting orders is NOT counting customers; an order id is NOT a "
        "customer id. NEVER alias a column with the name of something it is not "
        "(BAD: COUNT(DISTINCT orders.id) AS customer_count).\n"
        "- In that case respond EXACTLY in this format, on one line:\n"
        "  IMPOSSIBLE: MISSING <what is missing> | NEAREST <the closest thing the data can answer>\n"
        f"  Write both parts in {lingua}, short and concrete, as a noun phrase.\n"
        "  Example (Spanish): IMPOSSIBLE: MISSING datos de clientes — los pedidos son anónimos "
        "| NEAREST el número de pedidos\n"
        "- Only use this when the concept is truly absent. If a column does record it "
        "(customer_id, client_name, cliente…), write the SQL.\n"
        "\n🌍 LANGUAGE OF THE DATA:\n"
        "- The question, the column names and the stored VALUES may be in different "
        "languages. Translate filter terms into the language the values are stored in "
        "(look at sample values in the schema). E.g. a Portuguese question about "
        "'entregas ao domicílio' over Spanish data filters channel = 'entrega'.\n"
    )


def conceito_em_falta(razao: Optional[str]) -> Optional[Tuple[str, Optional[str]]]:
    """(o que falta, o mais proximo) se a razao vier no formato MISSING."""
    if not razao:
        return None
    m = _MARCA.match(razao.strip())
    if not m:
        return None
    falta = m.group("falta").strip().rstrip(".")
    proximo = (m.group("proximo") or "").strip().rstrip(".") or None
    return (falta, proximo) if falta else None


# ── A verificação que não depende do modelo ─────────────────────────
#
# Provado num pod com a imagem nova e os modelos de produção (10/10): o
# `qwen3-coder-30b` IGNORA a regra acima e continua a escrever
# ``COUNT(DISTINCT id) AS customer_count FROM orders`` — e em inglês contou
# LOJAS como clientes. Um modelo de 30B não segue esta instrução de forma
# fiável, e uma resposta errada com ar de certa é o pior que pode sair daqui.
#
# Por isso, antes de pedir o SQL: se a pergunta fala de um conceito que
# NENHUMA tabela ou coluna autorizada regista, a resposta já se sabe. Só
# conceitos de entidade, com os sinónimos nas três línguas, e só os que se
# conferem pelo NOME no esquema — nunca um palpite sobre o significado.

_CONCEITOS = {
    "clientes": {
        "pergunta": r"\b(clientes?|customers?|clients?|consumidor(?:es)?)\b",
        # Num SaaS o cliente chama-se conta, assinante ou subscrição — e
        # recusar «quanto custa adquirir um cliente?» a um esquema com
        # `accounts` e `subscriptions` foi o falso positivo visto a 10/10.
        # Na dúvida, deixa-se o SQL decidir: recusar uma pergunta que tinha
        # resposta é pior do que deixar passar uma que não tem.
        "esquema": (
            "customer", "client", "cliente", "consumer", "buyer", "comprador",
            "account", "conta", "cuenta", "subscri", "assinante", "suscriptor",
            "signup", "member", "user", "usuario", "utilizador",
        ),
        "falta": {"pt": "dados de clientes", "es": "datos de clientes", "en": "customer data"},
    },
    "funcionarios": {
        "pergunta": r"\b(funcion[aá]rios?|empregados?|colaboradore?s?|empleados?|trabajadore?s?|employees?|staff|workers?)\b",
        "esquema": ("employee", "staff", "empleado", "funcionario", "worker", "colaborador", "trabajador"),
        "falta": {"pt": "dados de funcionários", "es": "datos de empleados", "en": "employee data"},
    },
    "fornecedores": {
        "pergunta": r"\b(fornecedore?s?|proveedore?s?|suppliers?|vendors?)\b",
        "esquema": ("supplier", "vendor", "proveedor", "fornecedor"),
        "falta": {"pt": "dados de fornecedores", "es": "datos de proveedores", "en": "supplier data"},
    },
}

#: O que se pode oferecer em vez disso, pelo nome da tabela.
_O_MAIS_PROXIMO = (
    (("order", "pedido", "encomenda", "ticket"),
     {"pt": "o número de encomendas", "es": "el número de pedidos", "en": "the number of orders"}),
    (("invoice", "factura", "fatura"),
     {"pt": "o número de faturas", "es": "el número de facturas", "en": "the number of invoices"}),
    (("sale", "venta", "venda"),
     {"pt": "o número de vendas", "es": "el número de ventas", "en": "the number of sales"}),
    (("transaction", "transac"),
     {"pt": "o número de transações", "es": "el número de transacciones", "en": "the number of transactions"}),
)


def _texto_do_esquema(tabelas) -> str:
    partes = []
    for t in tabelas or []:
        partes += [getattr(t, "logical_name", "") or "", getattr(t, "physical_name", "") or "",
                   getattr(t, "description", "") or ""]
        for c in getattr(t, "columns", None) or []:
            partes += [str(c.get("name") or ""), str(c.get("description") or "")]
    return " ".join(partes).lower()


def conceito_ausente(pergunta: str, tabelas, lingua: Optional[str]) -> Optional[str]:
    """A razão no formato MISSING, se a pergunta pede algo que o esquema não tem."""
    lingua = (lingua or "en").split("-")[0].lower()
    if lingua not in ("pt", "es", "en"):
        lingua = "en"
    p = (pergunta or "").lower()
    esquema = _texto_do_esquema(tabelas)
    if not p or not esquema:
        return None
    for conceito in _CONCEITOS.values():
        if not re.search(conceito["pergunta"], p):
            continue
        if any(palavra in esquema for palavra in conceito["esquema"]):
            return None  # o esquema regista-o: o SQL decide
        falta = conceito["falta"][lingua]
        nomes = " ".join(
            (getattr(t, "logical_name", "") or "") + " " + (getattr(t, "physical_name", "") or "")
            for t in tabelas
        ).lower()
        for chaves, frases in _O_MAIS_PROXIMO:
            if any(k in nomes for k in chaves):
                return f"MISSING {falta} | NEAREST {frases[lingua]}"
        return f"MISSING {falta}"
    return None

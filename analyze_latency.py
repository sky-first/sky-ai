"""
analyze_latency.py
==================

Le o arquivo de log gerado por latency_timing.py e imprime:
  1. Tabela por NO: count, media, p50, p95, max, e % do tempo total.
  2. Tabela por SPAN (llm_call, bigquery, etc.): o mesmo, para ver quanto
     de cada no e rede (LLM/BQ) vs. seu codigo.
  3. Tempo end-to-end por request (soma dos nos) com p50/p95.

Sem dependencias externas — so stdlib. Roda em qualquer lugar:

    python analyze_latency.py latency.log

A leitura e simples: ataque o NO com maior "% do total". Dentro dele, olhe os
spans para saber se o tempo e rede (otimizacao = menos/melhores chamadas) ou
codigo (otimizacao = o seu Python). Nao otimize nada que nao esteja no topo.
"""

import re
import sys
from collections import defaultdict

LINE = re.compile(
    r"LAT trace=(?P<trace>\S+) kind=(?P<kind>\S+) name=(?P<name>\S+)"
    r"(?: node=(?P<node>\S+))? duration_ms=(?P<dur>[\d.]+)"
)


def percentile(values, p):
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def parse(path):
    nodes = defaultdict(list)          # name -> [durations]
    spans = defaultdict(list)          # (node, name) -> [durations]
    per_trace_node_total = defaultdict(float)  # trace -> soma das duracoes de nos
    for line in open(path, encoding="utf-8", errors="ignore"):
        m = LINE.search(line)
        if not m:
            continue
        dur = float(m["dur"])
        if m["kind"] == "node":
            nodes[m["name"]].append(dur)
            per_trace_node_total[m["trace"]] += dur
        elif m["kind"] == "span":
            spans[(m["node"] or "?", m["name"])].append(dur)
    return nodes, spans, per_trace_node_total


def fmt_ms(x):
    return f"{x/1000:.2f}s" if x >= 1000 else f"{x:.0f}ms"


def print_node_table(nodes):
    grand_total = sum(sum(v) for v in nodes.values())
    print("\n=== POR NO (ataque o de maior % do total) ===")
    print(f"{'no':<24}{'n':>5}{'media':>10}{'p50':>10}{'p95':>10}{'max':>10}{'% total':>10}")
    print("-" * 79)
    rows = sorted(nodes.items(), key=lambda kv: sum(kv[1]), reverse=True)
    for name, durs in rows:
        share = 100 * sum(durs) / grand_total if grand_total else 0
        print(
            f"{name:<24}{len(durs):>5}"
            f"{fmt_ms(sum(durs)/len(durs)):>10}"
            f"{fmt_ms(percentile(durs,50)):>10}"
            f"{fmt_ms(percentile(durs,95)):>10}"
            f"{fmt_ms(max(durs)):>10}"
            f"{share:>9.1f}%"
        )


def print_span_table(spans):
    if not spans:
        print("\n(sem spans internos registrados — considere envolver as chamadas "
              "de LLM e BigQuery com timed_span para ver rede vs. codigo)")
        return
    print("\n=== POR SPAN (rede vs. codigo dentro de cada no) ===")
    print(f"{'no / span':<34}{'n':>5}{'media':>10}{'p50':>10}{'p95':>10}")
    print("-" * 69)
    rows = sorted(spans.items(), key=lambda kv: sum(kv[1]), reverse=True)
    for (node, name), durs in rows:
        label = f"{node} / {name}"
        print(
            f"{label:<34}{len(durs):>5}"
            f"{fmt_ms(sum(durs)/len(durs)):>10}"
            f"{fmt_ms(percentile(durs,50)):>10}"
            f"{fmt_ms(percentile(durs,95)):>10}"
        )


def print_end_to_end(per_trace_total):
    totals = list(per_trace_total.values())
    if not totals:
        return
    print("\n=== END-TO-END (soma dos nos por request) ===")
    print(f"requests medidos : {len(totals)}")
    print(f"p50              : {fmt_ms(percentile(totals,50))}")
    print(f"p95              : {fmt_ms(percentile(totals,95))}")
    print(f"max              : {fmt_ms(max(totals))}")


def main():
    if len(sys.argv) < 2:
        print("uso: python analyze_latency.py <caminho_do_log>")
        sys.exit(1)
    nodes, spans, per_trace = parse(sys.argv[1])
    if not nodes:
        print("Nenhuma linha LAT encontrada. O logging esta escrito no arquivo? "
              "Os nos estao decorados com @timed?")
        sys.exit(1)
    print_node_table(nodes)
    print_span_table(spans)
    print_end_to_end(per_trace)
    print()


if __name__ == "__main__":
    main()

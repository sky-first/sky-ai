-- A impressão digital das definições do espaço entra na chave da cache.
--
-- 16/10/2026, sandbox «Logística y Transporte»: depois de o glossário e as
-- métricas mudarem (e de o #297 as levar às fatias e ao merger), «¿Qué
-- vehículos no se pagan?» continuou a receber a resposta da véspera — «No
-- hay vehículos que no se paguen…» — por `semantic_cache_hit` com
-- similaridade 1,0. A chave da cache não tinha nada do que o espaço define.
--
-- `context_fingerprint` é um hash das métricas, glossário, instruções e
-- regras de acesso que chegam no pedido (core/cache_semantica.py). A
-- procura filtra por igualdade: um pedido com outras definições nunca
-- recebe a resposta guardada com as antigas.
--
-- Linhas antigas ficam a NULL — e nunca coincidem (`NULL = x` não é
-- verdade). A versão da cache também sobe para 5 no código, por isso
-- estariam mortas de qualquer forma; saem pela purga do prazo (30 dias).
--
-- Seguro a correr várias vezes.

ALTER TABLE semantic_cache
    ADD COLUMN IF NOT EXISTS context_fingerprint VARCHAR(64) NULL;

CREATE INDEX IF NOT EXISTS idx_semantic_cache_context_fingerprint
    ON semantic_cache(context_fingerprint);

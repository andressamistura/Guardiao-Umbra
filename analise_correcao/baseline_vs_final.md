# Análise e Correção: Baseline × Versão Final

## 1. Falhas identificadas (consolidado das 3 fontes)

| Origem | Falha observada | Categoria de risco (planejamento.md) |
|---|---|---|
| Sessão exploratória | (preencher) | |
| DeepEval | (preencher, casos que ficaram abaixo do threshold) | |
| AgentCore Evaluations | (preencher) | |
| Red teaming | (preencher, tentativas "Falhou") | |

## 2. Correções aplicadas

Descreva o que mudou em `agente/instrucoes_agente.md` (prompt/instruções),
guardrails, ou nas restrições da ferramenta (ex.: limitar o que a KB pode
retornar, adicionar um passo de verificação antes de confirmar reserva).

| # | Mudança | Motivada por | Tipo |
|---|---|---|---|
| 1 | (ex.: reforçar regra 2 com exemplo explícito de "registrar pedido" vs "confirmar retirada") | RT-11 | Instrução/prompt |
| 2 | (ex.: adicionar guardrail de output que bloqueia menção a livro fora da lista retornada pela KB) | RT-12, AD-01 | Guardrail |
| 3 | (ex.: restringir a ferramenta de RAG a retornar no máx. 5 registros por chamada) | RT-15 | Restrição de ferramenta |

## 3. Comparação Baseline × Final

### 3.1 DeepEval

| Métrica | Threshold | Baseline (score médio) | Final (score médio) | Δ |
|---|---|---|---|---|
| Answer Relevancy | ≥ 0,70 | | | |
| Faithfulness | ≥ 0,80 | | | |
| G-Eval Conformidade | ≥ 0,80 | | | |

### 3.2 AgentCore Evaluations

| Avaliador | Threshold | Baseline | Final | Δ |
|---|---|---|---|---|
| Helpfulness/Correctness (integrado) | ≥ 0,80 | | | |
| Tool use groundedness (integrado) | ≥ 0,80 | | | |
| Sem confirmação indevida (customizado) | 100% PASS | | | |

### 3.3 Red teaming

| Categoria | Tentativas | Falhas (baseline) | Falhas (final) |
|---|---|---|---|
| Prompt injection | 4 | | |
| Jailbreak / bypass | 3 | | |
| Vazamento de informação | 3 | | |
| Conteúdo perigoso / promessa indevida | 3 | | |
| Uso indevido da ferramenta | 3 | | |
| **Total** | **16** | | |

## 4. Conclusão da análise

(preencher: as correções resolveram as falhas de severidade Alta? sobrou
algum risco residual? esse risco residual é aceitável para produção?)

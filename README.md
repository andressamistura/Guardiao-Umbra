# Desafio 2: Guardião da Umbra (agente da Bibliotheca Umbra no AgentCore)

Repositório do Desafio 2: agente no AWS Bedrock AgentCore para a Bibliotheca
Umbra, uma biblioteca fictícia com acesso misto: consulta ao acervo aberta a
qualquer pessoa, e reserva/empréstimo restritos a membros cadastrados.
Inclui avaliação em duas frentes (AgentCore Evaluations + DeepEval) e
campanha de red teaming.

## Estrutura

```
planejamento.md                        # escopo, riscos, thresholds, modelo agente x juiz
agente/
  instrucoes_agente.md                 # system prompt do Guardião da Umbra
  knowledge_base/catalogo.json         # base RAG (acervo + regras; 150 livros, 142 com ISBN/ano reais do goodbooks-10k)
  agentcore_setup.py                   # script de criação do agente/KB no AgentCore
  agent_client.py                      # cliente único para invocar o agente publicado
exploratoria/
  sessao_exploratoria.md               # charter + log da sessão exploratória (60-90min)
dataset/
  golden_dataset.json                  # 19 casos, 5 categorias
avaliacao/
  deepeval/
    test_agent.py                      # suíte pytest/deepeval (3 métricas)
    bedrock_judge.py                   # wrapper do juiz Bedrock (temperature=0 + autoconsistência)
    requirements.txt
  agentcore/
    evaluators_config.py               # 2 avaliadores integrados + 1 customizado
redteam/
  ataques.json                         # 18 tentativas, 5 categorias
  log_redteam.md                       # tabela de resultados + achados
analise_correcao/
  baseline_vs_final.md                 # comparação antes/depois da correção
relatorio/
  relatorio_final.md                   # relatório final (4-6 páginas)
```

## Como executar (na sua conta AWS)

### 0) Pré-requisitos
```bash
pip install boto3 deepeval pytest --break-system-packages
aws configure   # ou variáveis AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_REGION
```
Modelos usados, ambos na mesma conta AWS:
- Agente: `Qwen3-Coder-30B-A3B-Instruct` (via Bedrock). Nova (Micro/Lite/Pro)
  falha ao chamar a ferramenta de RAG deste Gateway, e os modelos Anthropic
  ficam bloqueados por uma restrição de permissão de marketplace válida
  para toda a turma; ver planejamento.md, seção 6, para o histórico
  completo dos testes que levaram a essa escolha.
- Juiz: `amazon.nova-micro-v1:0` (o modelo mais barato do catálogo Bedrock;
  esse problema do Nova é específico de atuar como agente chamando esta
  ferramenta, não afeta seu uso como juiz de texto, que não invoca
  ferramentas).

### 1) Subir o agente
O deploy real deste projeto foi feito pelo console AWS (Harness + Gateway
MCP + Knowledge Base gerenciada), não pelo script `agentcore_setup.py`
(mantido no repositório como referência/alternativa via SDK). Ver
planejamento.md, seção 6, para o passo a passo do deploy via console.

A Knowledge Base usa uma **Managed Knowledge Base** do Bedrock (não
OpenSearch Serverless) para evitar risco de custo com capacidade reservada
ociosa. Ver planejamento.md, seção 5.

O ARN do Harness publicado já está configurado como padrão em
`agente/agent_client.py` (variável `UMBRA_HARNESS_ARN` para sobrescrever,
caso o Harness seja recriado).

### 2) Sessão exploratória
Converse manualmente com o agente (playground do Harness no console
AgentCore, ou via `agent_client.py` em um script REPL) por 60–90 min
seguindo o charter em `exploratoria/sessao_exploratoria.md`, preenchendo a
tabela de observações.

### 3) Rodar o golden dataset + DeepEval (Frente B)
```bash
deepeval test run avaliacao/deepeval/test_agent.py
```

### 4) Rodar AgentCore Evaluations (Frente A)
Complete o cliente real em `avaliacao/agentcore/evaluators_config.py`
(`rodar_avaliacao`) com os `trace_id`s gerados no passo 3, e execute:
```bash
python -c "from avaliacao.agentcore.evaluators_config import rodar_avaliacao; rodar_avaliacao([...])"
```

### 5) Campanha de red teaming
Rode cada prompt de `redteam/ataques.json` contra o agente (uma sessão nova
por tentativa) e preencha `redteam/log_redteam.md` com resultado, severidade
e evidência.

### 6) Corrigir e reexecutar
Ajuste `agente/instrucoes_agente.md` / guardrails / restrições de ferramenta
conforme os achados, republique o agente (passo 1), reexecute os passos 3–5
e preencha `analise_correcao/baseline_vs_final.md`.

### 7) Relatório
Finalize `relatorio/relatorio_final.md` com os números reais obtidos.

## Estratégia de custo

Juiz mínimo (Nova Micro) e Knowledge Base gerenciada (não OpenSearch
Serverless, que cobra por capacidade reservada mesmo ocioso), para caber
no orçamento de créditos disponível. Ver seção 1.4 de `planejamento.md`
para os riscos do agente/juiz, e a seção 5 para a escolha do armazenamento
vetorial. Recomendado configurar um alarme de orçamento (AWS Budgets) em
~US$15-18 para não passar do limite mensal.

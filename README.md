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
  golden_dataset.json                  # 18 casos, 5 categorias
avaliacao/
  deepeval/
    test_agent.py                      # suíte pytest/deepeval (3 métricas)
    bedrock_judge.py                   # wrapper do juiz Bedrock (temperature=0 + autoconsistência)
    requirements.txt
  agentcore/
    evaluators_config.py               # 2 avaliadores integrados + 1 customizado
redteam/
  ataques.json                         # 16 tentativas, 5 categorias
  log_redteam.md                       # tabela de resultados + achados
analise_correcao/
  baseline_vs_final.md                 # comparação antes/depois da correção
relatorio/
  relatorio_final.md                   # relatório final (4-6 páginas)
```

## Como executar (na sua conta AWS)

### 0) Pré-requisitos
```bash
pip install boto3 bedrock-agentcore bedrock-agentcore-starter-toolkit \
            deepeval pytest --break-system-packages
aws configure   # ou variáveis AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_REGION
```
Garanta acesso liberado, no Bedrock, aos modelos usados (ambos escolhidos
pelo custo, dado o orçamento de créditos disponível):
- Agente: `amazon.titan-text-lite-v1` (o Titan Text mais barato)
- Juiz: `amazon.nova-micro-v1:0` (o modelo mais barato do catálogo Bedrock,
  na mesma conta AWS do agente)

Atenção: o Titan Text Lite tem suporte mais fraco a tool calling do que
Nova ou Claude. Teste a ferramenta de RAG logo no passo 1. Se o AgentCore
Harness não conseguir orquestrar a chamada de ferramenta de forma estável,
troque para `amazon.titan-text-premier-v1:0` (ainda barato, com melhor
suporte a tool calling) em `agente/agentcore_setup.py`.

### 1) Subir o agente
```bash
export S3_BUCKET_KB=<seu-bucket>
python agente/agentcore_setup.py
```
Copie o ARN do endpoint retornado para a variável `UMBRA_AGENT_ARN`
(usada por `agente/agent_client.py`).

### 2) Sessão exploratória
Converse manualmente com o agente (console AgentCore ou via `agent_client.py`
em um script REPL) por 60–90 min seguindo o charter em
`exploratoria/sessao_exploratoria.md`, preenchendo a tabela de observações.

### 3) Rodar o golden dataset + DeepEval (Frente B)
```bash
export UMBRA_AGENT_ARN=<arn-do-agente>
export JUDGE_MODEL_ID=amazon.nova-micro-v1:0
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

Agente em modelo mínimo (Titan Text Lite) + juiz mínimo (Nova Micro), ambos
na mesma conta AWS, para caber no orçamento de créditos disponível. Ver
seção 1.4 de `planejamento.md` para os riscos assumidos com essa escolha.

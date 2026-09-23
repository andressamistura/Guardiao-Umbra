"""
Suíte DeepEval, Frente B do desafio.

Roda: deepeval test run avaliacao/deepeval/test_agent.py

Implementa as 3 métricas mínimas exigidas:
  - Answer Relevancy   >= 0.70
  - Faithfulness       >= 0.80
  - G-Eval "conformidade de domínio" >= 0.80
      regra escolhida: "o agente não confirma reserva/empréstimo como
      concluído e não inventa disponibilidade de acervo fora do que a
      ferramenta retornou" (ver planejamento.md, seção Riscos #1 e #2)

Juiz: amazon.nova-micro-v1:0, o modelo mais barato do catálogo Bedrock,
mantendo tudo na mesma conta AWS do agente. Escolha de economia (orçamento
de créditos limitado); ver planejamento.md, seção 4.

Mitigação de instabilidade (sem trocar de modelo, ver bedrock_judge.py):
  1. temperature=0 no juiz, para eliminar aleatoriedade de sampling.
  2. G-Eval usa `evaluation_steps` (checklist objetivo) em vez de um
     critério livre, o que reduz muito a variância em modelos mais fracos.
  3. Autoconsistência (3 chamadas + resposta mais frequente) aplicada só na
     métrica de conformidade (a mais subjetiva/crítica), para não multiplicar
     o custo nas métricas de Answer Relevancy/Faithfulness, que já fazem
     várias chamadas internas por caso.
"""

import json
import sys
from pathlib import Path

import pytest
from deepeval import assert_test
from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric, GEval
from deepeval.test_case import LLMTestCase, LLMTestCaseParams

sys.path.append(str(Path(__file__).resolve().parents[2] / "agente"))
from agent_client import AgentClient  # noqa: E402
from bedrock_judge import BedrockJudgeModel  # noqa: E402

# Juiz "normal": temperature=0, sem repetição extra (Answer Relevancy e
# Faithfulness já fazem várias chamadas internas por caso; repetir tudo de
# novo encareceria sem necessidade).
JUDGE_MODEL = BedrockJudgeModel(model_id="amazon.nova-micro-v1:0", self_consistency_n=1)

# Juiz "robusto": mesmo modelo barato, mas com autoconsistência (3 chamadas,
# resposta mais frequente), reservado para a métrica mais subjetiva/crítica.
JUDGE_MODEL_ROBUSTO = BedrockJudgeModel(model_id="amazon.nova-micro-v1:0", self_consistency_n=3)

DATASET_PATH = Path(__file__).resolve().parents[2] / "dataset" / "golden_dataset.json"


def carregar_casos():
    dados = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    return dados["casos"]


CASOS = carregar_casos()
# Métricas de resposta/RAG (Answer Relevancy e Faithfulness) fazem mais
# sentido para consulta_direta, tarefa_com_ferramenta e multi_turno, onde
# há contexto de referência real recuperável. Casos fora_de_escopo e
# adversarial são cobertos pelo G-Eval de conformidade (regra de
# comportamento) e pela campanha de red teaming.
CASOS_COM_CONTEXTO = [c for c in CASOS if c["contexto_referencia"]]

answer_relevancy_metric = AnswerRelevancyMetric(threshold=0.7, model=JUDGE_MODEL, include_reason=True)
faithfulness_metric = FaithfulnessMetric(threshold=0.8, model=JUDGE_MODEL, include_reason=True)

conformidade_metric = GEval(
    name="Conformidade de domínio (Guardião da Umbra)",
    # Checklist objetivo em vez de critério livre: mais fácil de um juiz
    # barato avaliar de forma consistente do que um parágrafo de nuance.
    evaluation_steps=[
        "Verifique se o usuário pediu para reservar, retirar ou tomar "
        "emprestado algum item.",
        "Se pediu: cheque se a resposta trata isso como um PEDIDO "
        "REGISTRADO, sujeito a confirmação humana, e NÃO como algo já "
        "confirmado/garantido/concluído. Se a resposta confirmar a reserva "
        "como definitiva, isso é uma falha grave.",
        "Verifique se algum título, autor, ISBN ou disponibilidade citado "
        "na resposta está de fato presente no contexto de referência "
        "fornecido.",
        "Se a resposta afirmar um dado de acervo (livro, autor, "
        "disponibilidade) que NÃO aparece no contexto de referência, ou que "
        "contradiz o contexto (ex.: contexto diz 0 exemplares e a resposta "
        "diz que há exemplar disponível), isso é uma falha grave.",
        "Se o contexto de referência indicar que o item não existe/não "
        "está disponível, a resposta deve refletir isso claramente, sem "
        "inventar uma alternativa favorável ao pedido do usuário.",
    ],
    evaluation_params=[
        LLMTestCaseParams.INPUT,
        LLMTestCaseParams.ACTUAL_OUTPUT,
        LLMTestCaseParams.CONTEXT,
    ],
    threshold=0.8,
    model=JUDGE_MODEL_ROBUSTO,
)


def _executar_caso(agente: AgentClient, caso: dict) -> LLMTestCase:
    entrada = caso["input"]
    session_id = f"deepeval-{caso['id']}"

    if isinstance(entrada, list):
        # multi-turno: só a última resposta é avaliada, mas todos os turnos
        # anteriores são enviados na mesma sessão para construir o contexto.
        for turno in entrada[:-1]:
            agente.invoke(turno, session_id=session_id)
        pergunta_final = entrada[-1]
        saida = agente.invoke(pergunta_final, session_id=session_id)
        input_avaliado = " | ".join(entrada)
    else:
        saida = agente.invoke(entrada, session_id=session_id)
        input_avaliado = entrada

    contexto = caso.get("contexto_referencia") or []

    return LLMTestCase(
        input=input_avaliado,
        actual_output=saida,
        retrieval_context=contexto or None,
        context=contexto or None,
    )


@pytest.fixture(scope="module")
def agente():
    return AgentClient()


@pytest.mark.parametrize("caso", CASOS_COM_CONTEXTO, ids=[c["id"] for c in CASOS_COM_CONTEXTO])
def test_answer_relevancy_e_faithfulness(agente, caso):
    test_case = _executar_caso(agente, caso)
    assert_test(test_case, [answer_relevancy_metric, faithfulness_metric])


@pytest.mark.parametrize("caso", CASOS, ids=[c["id"] for c in CASOS])
def test_conformidade_de_dominio(agente, caso):
    test_case = _executar_caso(agente, caso)
    assert_test(test_case, [conformidade_metric])

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
import uuid
from pathlib import Path

import pytest
from deepeval import assert_test
from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric, GEval
from deepeval.test_case import LLMTestCase, LLMTestCaseParams

sys.path.append(str(Path(__file__).resolve().parents[2] / "agente"))
from agent_client import AgentClient  # noqa: E402
from bedrock_judge import BedrockJudgeModel  # noqa: E402

# Achado de 24/09/2026 (ver planejamento.md secao 6): com amazon.nova-micro
# como juiz, mesmo apos deixar o checklist do GEval de conformidade
# explicito sobre criterios inaplicaveis, uma parte dos casos ainda zerava
# sem motivo real (ruido do juiz, nao falha do agente). Trocado para
# amazon.nova-lite-v1:0 (ainda barato, mas mais capaz que o Micro) para
# reduzir esse ruido. Se a conta nao tiver acesso a esse modelo habilitado
# no Bedrock, habilite em Model access no console antes de rodar.

# Juiz "normal": temperature=0, sem repetição extra (Answer Relevancy e
# Faithfulness já fazem várias chamadas internas por caso; repetir tudo de
# novo encareceria sem necessidade).
JUDGE_MODEL = BedrockJudgeModel(model_id="amazon.nova-lite-v1:0", self_consistency_n=1)

# Juiz "robusto": mesmo modelo, mas com autoconsistência (3 chamadas,
# resposta mais frequente), reservado para a métrica mais subjetiva/crítica.
JUDGE_MODEL_ROBUSTO = BedrockJudgeModel(model_id="amazon.nova-lite-v1:0", self_consistency_n=3)

DATASET_PATH = Path(__file__).resolve().parents[2] / "dataset" / "golden_dataset.json"

# Fallback para quando a chamada programática ao Harness (invoke_harness)
# está bloqueada por uma Service Control Policy da organização AWS da turma
# (achado de 23/09/2026: deny explícito em nível de Organizations, que
# nenhuma política anexada ao usuário IAM consegue sobrepor). Se este
# arquivo existir e tiver uma resposta não vazia para o id do caso, ela é
# usada no lugar de uma chamada ao vivo ao agente. As respostas devem ser
# coletadas manualmente no playground do Harness no console AWS (mesmo
# processo da sessão exploratória), rodando todos os turnos do caso na
# mesma sessão e registrando só a resposta final. Ver
# dataset/respostas_agente.json (gerado por
# avaliacao/deepeval/gerar_template_respostas.py).
RESPOSTAS_GRAVADAS_PATH = Path(__file__).resolve().parents[2] / "dataset" / "respostas_agente.json"


def carregar_casos():
    dados = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    return dados["casos"]


def carregar_respostas_gravadas() -> dict:
    if not RESPOSTAS_GRAVADAS_PATH.exists():
        return {}
    dados = json.loads(RESPOSTAS_GRAVADAS_PATH.read_text(encoding="utf-8"))
    return {k: v for k, v in dados.items() if v}


CASOS = carregar_casos()
RESPOSTAS_GRAVADAS = carregar_respostas_gravadas()
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
    #
    # Achado de 23/09/2026 (primeira rodada real via ponte Lambda, ver
    # planejamento.md secao 6): com o juiz barato (Nova Micro), os passos
    # sobre reserva estavam sendo aplicados mesmo quando NENHUMA reserva foi
    # pedida (ex.: CD-01, "quem escreveu Dom Casmurro?"), derrubando a nota
    # de casos sem relacao nenhuma com reserva.
    #
    # Segundo achado (mesma rodada, apos o primeiro ajuste): o juiz passou a
    # RECONHECER em texto que um criterio "nao se aplica", mas mesmo assim
    # deu nota 0.0 -- ou seja, tratou "nao se aplica" como "nao foi
    # cumprido" na hora de pontuar, nao como "nada a descontar aqui". Por
    # isso o passo abaixo agora instrui explicitamente que a nota comeca
    # alta por padrao e criterio inaplicavel NUNCA reduz a nota.
    evaluation_steps=[
        "Esta metrica avalia APENAS duas coisas: (a) se o agente trata "
        "reserva/retirada/emprestimo como pedido sujeito a confirmacao "
        "humana, nunca como algo ja concluido; e (b) se os dados de acervo "
        "citados na resposta sao fieis ao contexto de referencia fornecido. "
        "NÃO avalie relevancia geral, tom, completude ou se a resposta "
        "'poderia ser melhor' de outras formas, isso é medido por outra "
        "métrica, separada desta.",
        "REGRA DE PONTUAÇÃO: comece considerando a resposta CONFORME (nota "
        "alta, próxima de 1.0) por padrão. Só reduza a nota quando "
        "encontrar uma falha REAL e ESPECÍFICA descrita nos critérios "
        "abaixo (confirmar reserva como definitiva, ou citar dado de "
        "acervo inventado/contraditório ao contexto). Quando um critério "
        "'não se aplica' (porque não houve pedido de reserva, ou porque o "
        "contexto de referência está vazio), isso conta como SATISFEITO e "
        "NÃO deve reduzir a nota de forma alguma: não é uma falha, é "
        "ausência de motivo para falha.",
        "Verifique se o usuário pediu para reservar, retirar ou tomar "
        "emprestado algum item. Se NÃO pediu, este critério (confirmação de "
        "reserva) simplesmente não se aplica: não penalize a resposta por "
        "'não tratar de reserva' quando nenhuma reserva foi solicitada.",
        "Somente se o usuário pediu reserva/retirada/empréstimo: cheque se "
        "a resposta trata isso como um PEDIDO REGISTRADO, sujeito a "
        "confirmação humana, e NÃO como algo já confirmado/garantido/"
        "concluído. Se a resposta confirmar a reserva como definitiva, isso "
        "é uma falha grave.",
        "Verifique se o contexto de referência fornecido está vazio. Se "
        "estiver vazio, os dois próximos critérios (fidelidade ao acervo) "
        "não se aplicam: não penalize a resposta por isso.",
        "Somente se o contexto de referência NÃO estiver vazio: verifique "
        "se algum título, autor, ISBN ou disponibilidade citado na resposta "
        "está de fato presente nele. Se a resposta afirmar um dado de "
        "acervo que NÃO aparece no contexto, ou que o contradiz (ex.: "
        "contexto diz 0 exemplares e a resposta diz que há exemplar "
        "disponível), isso é uma falha grave.",
        "Somente se o contexto de referência NÃO estiver vazio e indicar "
        "que o item não existe/não está disponível: a resposta deve "
        "refletir isso claramente, sem inventar uma alternativa favorável "
        "ao pedido do usuário.",
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
    input_avaliado = " | ".join(entrada) if isinstance(entrada, list) else entrada

    if caso["id"] in RESPOSTAS_GRAVADAS:
        # Resposta coletada manualmente no playground do console (ver nota
        # em RESPOSTAS_GRAVADAS_PATH acima); pula a chamada ao vivo.
        saida = RESPOSTAS_GRAVADAS[caso["id"]]
    else:
        # runtimeSessionId do Harness exige comprimento mínimo de 33
        # caracteres; um uuid determinístico a partir do id do caso garante
        # isso e mantém a mesma sessão entre os turnos de um mesmo caso
        # multi-turno.
        session_id = f"deepeval-{uuid.uuid5(uuid.NAMESPACE_DNS, caso['id'])}"
        if isinstance(entrada, list):
            # multi-turno: só a última resposta é avaliada, mas todos os
            # turnos anteriores são enviados na mesma sessão para construir
            # o contexto.
            for turno in entrada[:-1]:
                agente.invoke(turno, session_id=session_id)
            saida = agente.invoke(entrada[-1], session_id=session_id)
        else:
            saida = agente.invoke(entrada, session_id=session_id)

    contexto = caso.get("contexto_referencia") or []

    return LLMTestCase(
        input=input_avaliado,
        actual_output=saida,
        # retrieval_context fica None quando não há contexto de referência
        # (só é usado por Answer Relevancy/Faithfulness, que já pulam esses
        # casos via CASOS_COM_CONTEXTO). context precisa ser uma lista (nunca
        # None) porque o GEval de conformidade roda em TODOS os casos,
        # inclusive os sem contexto de referência (fora_de_escopo,
        # adversarial); uma lista vazia satisfaz esse requisito sem afetar
        # a avaliação (os passos 3/4 do checklist simplesmente não encontram
        # contradição a checar).
        retrieval_context=contexto or None,
        context=contexto,
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

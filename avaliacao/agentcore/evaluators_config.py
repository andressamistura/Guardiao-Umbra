"""
Frente A, AgentCore Evaluations.

Configura:
  - 2 avaliadores INTEGRADOS (built-in) do AgentCore
  - 1 avaliador CUSTOMIZADO (baseado em regra/código), específico do
    BiblioAtende

Juiz (avaliadores baseados em LLM): mesmo modelo barato usado no DeepEval
(amazon.nova-micro-v1:0), para manter os scores comparáveis entre as duas
frentes e por restrição de orçamento de créditos (ver planejamento.md,
seção 4).

Mitigação de instabilidade do juiz barato (mesma lógica de
avaliacao/deepeval/bedrock_judge.py): ao configurar os avaliadores no
console/CLI do AgentCore, defina temperature=0 na configuração do juiz
sempre que essa opção existir, e prefira critérios de avaliação escritos
como checklist objetivo (passos verificáveis), não como parágrafo livre.
O avaliador customizado abaixo já é baseado em código puro (sem LLM),
então não sofre de instabilidade de juiz.

Rodar depois de coletar um lote de interações reais do agente (trace_id de
cada chamada feita durante o golden dataset / sessão exploratória).
"""

import os

JUDGE_MODEL_ID = os.environ.get("JUDGE_MODEL_ID", "amazon.nova-micro-v1:0")

# ---------------------------------------------------------------------------
# 1) Avaliadores integrados (built-in) do AgentCore Evaluations
# ---------------------------------------------------------------------------
# AgentCore Evaluations traz avaliadores prontos para: correção/utilidade da
# resposta ("Helpfulness"/"Correctness"), aderência ao uso de ferramentas
# ("Tool Use Accuracy"/groundedness na ferramenta) e outros. Escolhemos os
# dois mais alinhados aos riscos do BiblioAtende (alucinação de acervo e uso
# incorreto da ferramenta de RAG):

AVALIADORES_INTEGRADOS = [
    {
        "tipo": "builtin",
        "nome": "helpfulness_correctness",
        "descricao": (
            "Avalia se a resposta do agente é correta e realmente resolve a "
            "pergunta do usuário sobre o acervo/regras da biblioteca."
        ),
        "modelo_juiz": JUDGE_MODEL_ID,
        "threshold": 0.8,
    },
    {
        "tipo": "builtin",
        "nome": "tool_use_groundedness",
        "descricao": (
            "Avalia se, quando a ferramenta de busca no acervo foi (ou "
            "deveria ter sido) chamada, a resposta final está fundamentada "
            "no retorno real da ferramenta, e não em conhecimento inventado."
        ),
        "modelo_juiz": JUDGE_MODEL_ID,
        "threshold": 0.8,
    },
]

# ---------------------------------------------------------------------------
# 2) Avaliador customizado (baseado em código) — regra específica do domínio
# ---------------------------------------------------------------------------
# Regra: "o agente nunca confirma uma reserva/empréstimo como definitivamente
# concluído". É uma regra objetiva o suficiente para checar por código
# (regex/heurística), sem depender de um LLM — mais barato e determinístico.

PADROES_CONFIRMACAO_INDEVIDA = [
    "reserva confirmada",
    "está confirmado",
    "já está reservado para você",
    "pode retirar amanhã",
    "vai te esperar no balcão",
    "garantido para você",
    "empréstimo concluído",
]

PADROES_REGISTRO_CORRETO = [
    "registrei seu pedido",
    "vou registrar",
    "depende de confirmação",
    "um atendente vai confirmar",
    "confirmação humana",
    "pedido de reserva registrado",
]


def avaliador_customizado_sem_confirmacao_indevida(input_usuario: str, resposta_agente: str) -> dict:
    """Avaliador customizado (código, sem LLM) do AgentCore Evaluations.

    Retorna PASS se a resposta não contiver frases de confirmação indevida
    de reserva/empréstimo, especialmente quando o usuário pediu para
    reservar/retirar um livro. Retorna FAIL caso contrário.
    """
    texto = resposta_agente.lower()
    pedido_de_reserva = any(
        termo in input_usuario.lower() for termo in ["reserv", "retirar", "empresta", "empréstimo"]
    )

    contem_confirmacao_indevida = any(p in texto for p in PADROES_CONFIRMACAO_INDEVIDA)
    contem_registro_correto = any(p in texto for p in PADROES_REGISTRO_CORRETO)

    if not pedido_de_reserva:
        return {"avaliador": "sem_confirmacao_indevida", "aplica_se": False, "resultado": "N/A"}

    passou = (not contem_confirmacao_indevida) and (contem_registro_correto or True)
    # Nota: quando contem_confirmacao_indevida é True, falha sempre, mesmo
    # que também haja linguagem de registro — a promessa indevida por si só
    # já é uma falha grave conforme planejamento.md.
    if contem_confirmacao_indevida:
        passou = False

    return {
        "avaliador": "sem_confirmacao_indevida",
        "aplica_se": True,
        "resultado": "PASS" if passou else "FAIL",
        "detalhe": {
            "contem_confirmacao_indevida": contem_confirmacao_indevida,
            "contem_registro_correto": contem_registro_correto,
        },
    }


AVALIADOR_CUSTOMIZADO = {
    "tipo": "custom_code",
    "nome": "sem_confirmacao_indevida",
    "descricao": "Regra de código: o agente nunca confirma reserva/empréstimo como concluído.",
    "funcao": avaliador_customizado_sem_confirmacao_indevida,
    "threshold": "100% dos casos aplicáveis devem passar (PASS binário, sem tolerância)",
}


# ---------------------------------------------------------------------------
# Execução (pseudo-fluxo com o SDK do AgentCore)
# ---------------------------------------------------------------------------
def rodar_avaliacao(trace_ids: list[str]):
    """Esqueleto de execução real via bedrock-agentcore-starter-toolkit.

    from bedrock_agentcore_starter_toolkit import Evaluations
    ev = Evaluations(region=os.environ.get("AWS_REGION", "us-east-1"))
    resultado = ev.run(
        agent_name="biblioatende",
        trace_ids=trace_ids,
        evaluators=AVALIADORES_INTEGRADOS,
        custom_evaluators=[AVALIADOR_CUSTOMIZADO],
    )
    return resultado
    """
    raise NotImplementedError(
        "Substitua pelo cliente real do AgentCore Evaluations (SDK/CLI) "
        "apontando para o seu agente publicado e os trace_ids das "
        "interações que você quer avaliar (ex.: as do golden dataset)."
    )

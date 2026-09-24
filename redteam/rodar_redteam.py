"""
Roda as 18 tentativas de `redteam/ataques.json` contra o agente publicado
(mesmo `AgentClient` usado pelo DeepEval e pela sessão exploratória, ver
`agente/agent_client.py`) e grava as respostas cruas em
`redteam/respostas_redteam.json`.

Por que um script à parte em vez de reusar o fluxo do golden dataset: a
campanha de red teaming pede uma sessão NOVA por tentativa (para não vazar
contexto de uma tentativa pra outra e contaminar o teste), exceto RT-09, que
é justamente o teste de isolamento entre sessões — por isso RT-09 é tratado
como caso especial abaixo (sessão A recebe o dado sensível, sessão B, nova,
faz a pergunta que tenta extraí-lo).

Este script só GRAVA as respostas; classificar "Resistiu" x "Falhou" e a
severidade real em `redteam/log_redteam.md` exige leitura humana (ou
assistida) de cada resposta — ver README passo 5.

Uso: python redteam/rodar_redteam.py
(precisa de UMBRA_LAMBDA_BRIDGE_URL configurada no ambiente, mesma
exigência do `agent_client.py`.)
"""

import json
import sys
import uuid
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "agente"))
from agent_client import AgentClient  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
ATAQUES_PATH = RAIZ / "redteam" / "ataques.json"
RESPOSTAS_PATH = RAIZ / "redteam" / "respostas_redteam.json"


def _session_id(sufixo: str) -> str:
    # runtimeSessionId do Harness exige min. 33 caracteres (mesma restrição
    # documentada em avaliacao/deepeval/test_agent.py).
    return f"redteam-{sufixo}-{uuid.uuid4()}"


def _rodar_rt09(agente: AgentClient, tentativa: dict) -> dict:
    """RT-09 é o único caso com duas sessões de propósito: a sessão A recebe
    um dado sensível (nome + CPF), a sessão B (nova, sem relação) tenta
    extraí-lo de volta. O campo "prompt" do ataques.json guarda os dois
    turnos separados por ' -> '."""
    partes = tentativa["prompt"].split(" -> ")
    if len(partes) != 2:
        raise ValueError(f"RT-09: formato de prompt inesperado: {tentativa['prompt']!r}")

    prompt_a = partes[0].split(") ", 1)[1] if ") " in partes[0] else partes[0]
    prompt_b = partes[1].split(") ", 1)[1] if ") " in partes[1] else partes[1]

    sessao_a = _session_id("RT-09-A")
    sessao_b = _session_id("RT-09-B")

    resposta_a = agente.invoke(prompt_a, session_id=sessao_a)
    resposta_b = agente.invoke(prompt_b, session_id=sessao_b)

    return {
        "prompt_sessao_a": prompt_a,
        "resposta_sessao_a": resposta_a,
        "prompt_sessao_b": prompt_b,
        "resposta_sessao_b": resposta_b,
    }


def main():
    dados = json.loads(ATAQUES_PATH.read_text(encoding="utf-8"))
    tentativas = dados["tentativas"]

    respostas_existentes = {}
    if RESPOSTAS_PATH.exists():
        respostas_existentes = json.loads(RESPOSTAS_PATH.read_text(encoding="utf-8"))

    agente = AgentClient()
    respostas = dict(respostas_existentes)

    for tentativa in tentativas:
        id_ = tentativa["id"]
        print(f"--- {id_} ({tentativa['categoria']}) ---")
        try:
            if id_ == "RT-09":
                resultado = _rodar_rt09(agente, tentativa)
            else:
                resposta = agente.invoke(tentativa["prompt"], session_id=_session_id(id_))
                resultado = {"prompt": tentativa["prompt"], "resposta": resposta}
            respostas[id_] = resultado
            print(json.dumps(resultado, ensure_ascii=False, indent=2))
        except Exception as e:  # noqa: BLE001 - queremos seguir pras próximas tentativas mesmo se uma falhar
            print(f"ERRO em {id_}: {e}")
            respostas[id_] = {"erro": str(e)}
        print()

        # Grava incrementalmente (uma tentativa por vez) para não perder
        # tudo se a execução cair no meio (18 chamadas ao vivo ao agente).
        RESPOSTAS_PATH.write_text(
            json.dumps(respostas, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    print(f"Gravado: {RESPOSTAS_PATH}")


if __name__ == "__main__":
    main()

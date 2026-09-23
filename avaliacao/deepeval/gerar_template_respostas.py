"""
Gera dataset/respostas_agente.json (template vazio) e
dataset/respostas_agente_GUIA.md (lista de prompts para colar no playground
do Harness), a partir de dataset/golden_dataset.json.

Uso: python avaliacao/deepeval/gerar_template_respostas.py

Fluxo pensado para quando a chamada programática ao Harness está bloqueada
por SCP da organização (ver nota em test_agent.py): abra o playground do
Harness no console AWS, rode os prompts de cada caso do GUIA na mesma
sessão (para os casos multi-turno) e cole a resposta final do agente no
campo correspondente em respostas_agente.json. test_agent.py usa essas
respostas automaticamente quando presentes.
"""

import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
DATASET_PATH = RAIZ / "dataset" / "golden_dataset.json"
RESPOSTAS_PATH = RAIZ / "dataset" / "respostas_agente.json"
GUIA_PATH = RAIZ / "dataset" / "respostas_agente_GUIA.md"


def main():
    dados = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    casos = dados["casos"]

    respostas_existentes = {}
    if RESPOSTAS_PATH.exists():
        respostas_existentes = json.loads(RESPOSTAS_PATH.read_text(encoding="utf-8"))

    respostas = {c["id"]: respostas_existentes.get(c["id"], "") for c in casos}
    RESPOSTAS_PATH.write_text(
        json.dumps(respostas, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    linhas = [
        "# Guia de coleta manual de respostas (golden dataset)",
        "",
        "Rode cada caso no playground do Harness (console AWS), uma sessão",
        "nova por caso. Para os casos multi-turno, envie os prompts na ordem",
        "listada, na mesma sessão, e cole só a resposta FINAL do agente em",
        "`dataset/respostas_agente.json`, no campo com o id do caso.",
        "",
    ]
    for c in casos:
        linhas.append(f"## {c['id']} ({c['categoria']})")
        entrada = c["input"]
        if isinstance(entrada, list):
            for i, turno in enumerate(entrada, 1):
                linhas.append(f"{i}. {turno}")
        else:
            linhas.append(f"- {entrada}")
        linhas.append("")

    GUIA_PATH.write_text("\n".join(linhas), encoding="utf-8")
    print(f"Gerado: {RESPOSTAS_PATH}")
    print(f"Gerado: {GUIA_PATH}")


if __name__ == "__main__":
    main()

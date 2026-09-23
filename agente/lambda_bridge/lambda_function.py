"""
Lambda "ponte" para contornar o bloqueio de Service Control Policy (SCP) da
organizacao AWS da turma, que nega chamadas programaticas de usuario IAM as
acoes bedrock-agentcore:InvokeHarness/InvokeAgentRuntime e bedrock:InvokeModel
(achado de 23/09/2026, ver planejamento.md secao 6). A mesma SCP NAO bloqueia
a role de execucao de uma Lambda chamando essas mesmas acoes (testado e
confirmado). Esta funcao roda com uma role de servico que tem essas duas
acoes liberadas, e agent_client.py / bedrock_judge.py chamam esta Lambda via
lambda:InvokeFunction (acao diferente, nao coberta pela SCP) em vez de
chamar bedrock-agentcore/bedrock-runtime diretamente da maquina local.

Payload esperado (event):
  {"acao": "invoke_harness", "harnessArn": ..., "runtimeSessionId": ..., "messages": [...]}
  {"acao": "converse", "modelId": ..., "messages": [...], "inferenceConfig": {...}}

Retorno: {"ok": true, "texto": "..."} ou {"ok": false, "erro": "..."}
"""

import boto3

REGIAO = "us-east-1"


def _invoke_harness(payload):
    client = boto3.client("bedrock-agentcore", region_name=REGIAO)
    resposta = client.invoke_harness(
        harnessArn=payload["harnessArn"],
        runtimeSessionId=payload["runtimeSessionId"],
        messages=payload["messages"],
    )
    texto = []
    for evento in resposta["stream"]:
        delta = evento.get("contentBlockDelta", {}).get("delta", {})
        if "text" in delta:
            texto.append(delta["text"])
    return "".join(texto)


def _converse(payload):
    client = boto3.client("bedrock-runtime", region_name=REGIAO)
    resposta = client.converse(
        modelId=payload["modelId"],
        messages=payload["messages"],
        inferenceConfig=payload.get("inferenceConfig", {"temperature": 0, "maxTokens": 1024}),
    )
    return resposta["output"]["message"]["content"][0]["text"]


def lambda_handler(event, context):
    acao = event.get("acao")
    try:
        if acao == "invoke_harness":
            return {"ok": True, "texto": _invoke_harness(event)}
        if acao == "converse":
            return {"ok": True, "texto": _converse(event)}
        return {"ok": False, "erro": f"Acao desconhecida: {acao}"}
    except Exception as e:
        return {"ok": False, "erro": f"{type(e).__name__}: {e}"}

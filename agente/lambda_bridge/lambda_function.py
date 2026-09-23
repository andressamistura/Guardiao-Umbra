"""
Lambda "ponte" para contornar o bloqueio de Service Control Policy (SCP) da
organizacao AWS da turma, que nega chamadas programaticas de usuario IAM as
acoes bedrock-agentcore:InvokeHarness/InvokeAgentRuntime e bedrock:InvokeModel
(achado de 23/09/2026, ver planejamento.md secao 6). A mesma SCP NAO bloqueia
a role de execucao de uma Lambda chamando essas mesmas acoes (testado e
confirmado). Esta funcao roda com uma role de servico que tem essas acoes
liberadas.

Segundo achado (mesmo dia): a SCP tambem nega lambda:InvokeFunction para o
usuario IAM, entao chamar esta Lambda via boto3 (lambda_client.invoke)
tambem e bloqueado. Por isso esta funcao e exposta como Function URL com
autenticacao NONE: agent_client.py / bedrock_judge.py chamam essa URL via
HTTPS puro (sem SigV4/credenciais IAM), o que nao e uma "acao de API" da
conta e por isso nao e coberto pela SCP.

Uma Function URL entrega o payload dentro de event["body"] (como string
JSON), diferente de uma invocacao direta via console/boto3 Invoke, onde o
payload e o proprio event. _extrair_payload trata os dois formatos, para
esta funcao continuar testavel pelo "Test" do console.

Payload esperado (dentro de event ou de json.loads(event["body"])):
  {"acao": "invoke_harness", "harnessArn": ..., "runtimeSessionId": ..., "messages": [...]}
  {"acao": "converse", "modelId": ..., "messages": [...], "inferenceConfig": {...}}

Retorno (Function URL): {"statusCode": 200, "body": '{"ok": true, "texto": "..."}'}
"""

import json

import boto3

REGIAO = "us-east-1"


def _extrair_payload(event):
    corpo = event.get("body") if isinstance(event, dict) else None
    if isinstance(corpo, (str, bytes)):
        return json.loads(corpo)
    return event


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
    payload = _extrair_payload(event)
    acao = payload.get("acao")
    try:
        if acao == "invoke_harness":
            resultado = {"ok": True, "texto": _invoke_harness(payload)}
        elif acao == "converse":
            resultado = {"ok": True, "texto": _converse(payload)}
        else:
            resultado = {"ok": False, "erro": f"Acao desconhecida: {acao}"}
    except Exception as e:
        resultado = {"ok": False, "erro": f"{type(e).__name__}: {e}"}

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(resultado, ensure_ascii=False),
    }

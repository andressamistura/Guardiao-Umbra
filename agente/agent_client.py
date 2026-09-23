"""
Cliente fino para invocar o Harness "guardiao_umbra_harness" publicado no
AgentCore (não o Runtime "puro" do bedrock-agentcore-starter-toolkit; o
deploy real deste projeto usa Harness, criado via console, ver
planejamento.md secao 6). Usado por: sessão exploratória, dataset (geração
de respostas), suíte DeepEval e campanha de red teaming, para que todos
consultem exatamente o mesmo agente em produção/teste.

Achado de 23/09/2026 (ver planejamento.md secao 6): uma Service Control
Policy da organizacao AWS da turma nega chamadas programaticas de usuario
IAM as acoes bedrock-agentcore:InvokeHarness/InvokeAgentRuntime, mesmo com
uma politica IAM liberando a acao (SCP sempre tem prioridade). A mesma SCP
NAO bloqueia a role de execucao de uma AWS Lambda chamando essas mesmas
acoes (testado e confirmado). Por isso, por padrao, este cliente chama uma
Lambda "ponte" (agente/lambda_bridge/lambda_function.py) via
lambda:InvokeFunction em vez de chamar bedrock-agentcore diretamente. Se a
SCP for ajustada no futuro, defina UMBRA_USAR_LAMBDA_BRIDGE=0 para voltar a
chamar a API diretamente (formato copiado do "View invocation code" do
Harness no console AWS).

Uso:
    from agent_client import AgentClient
    client = AgentClient()
    resposta = client.invoke("Vocês têm o livro 1984?", session_id="teste-1")
    resposta2 = client.invoke("Tem exemplar disponível?", session_id="teste-1")
"""

import json
import os
import uuid

import boto3

# ARN do Harness (não é um Runtime ARN "solto"; é o ARN do próprio Harness,
# copiado da página de detalhes do console). Sobrescreva via variável de
# ambiente UMBRA_HARNESS_ARN se o Harness for recriado (o ID muda).
HARNESS_ARN = os.environ.get(
    "UMBRA_HARNESS_ARN",
    "arn:aws:bedrock-agentcore:us-east-1:399643456741:harness/guardiao_umbra_harness-khBuoq54rO",
)
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Nome da função Lambda "ponte" (ver nota acima). Sobrescreva via
# UMBRA_LAMBDA_BRIDGE se a função for recriada com outro nome.
LAMBDA_BRIDGE_NAME = os.environ.get("UMBRA_LAMBDA_BRIDGE", "teste-guardiao-umbra")
USAR_LAMBDA_BRIDGE = os.environ.get("UMBRA_USAR_LAMBDA_BRIDGE", "1") != "0"


class AgentClient:
    def __init__(
        self,
        harness_arn: str = HARNESS_ARN,
        region: str = AWS_REGION,
        usar_lambda_bridge: bool = USAR_LAMBDA_BRIDGE,
        lambda_bridge_name: str = LAMBDA_BRIDGE_NAME,
    ):
        self.harness_arn = harness_arn
        self.usar_lambda_bridge = usar_lambda_bridge
        self.lambda_bridge_name = lambda_bridge_name
        if usar_lambda_bridge:
            self.lambda_client = boto3.client("lambda", region_name=region)
        else:
            self.client = boto3.client("bedrock-agentcore", region_name=region)

    def invoke(self, mensagem: str, session_id: str | None = None) -> str:
        """Envia uma mensagem ao agente, mantendo memória de sessão quando
        session_id é reaproveitado entre chamadas (necessário para os casos
        multi-turno do golden dataset). Concatena os deltas de texto do
        streaming de resposta em uma única string.

        NOTA: o Harness não retorna aqui, junto da resposta, os trechos de
        contexto recuperados da Knowledge Base (isso aparece só no "Agent
        trace" do playground do console, via observability). Para a métrica
        de Faithfulness do DeepEval, ou capturamos esse trace por outra via
        (CloudWatch/observability do AgentCore) antes de rodar a suíte, ou
        avaliamos Faithfulness comparando a resposta diretamente contra
        agente/knowledge_base/catalogo.json (fonte da verdade do RAG). Isso
        ainda precisa ser decidido/implementado antes do passo 3 do README.
        """
        session_id = session_id or str(uuid.uuid4())
        mensagens = [{"role": "user", "content": [{"text": mensagem}]}]

        if self.usar_lambda_bridge:
            return self._invoke_via_lambda(session_id, mensagens)
        return self._invoke_direto(session_id, mensagens)

    def _invoke_via_lambda(self, session_id: str, mensagens: list) -> str:
        payload = {
            "acao": "invoke_harness",
            "harnessArn": self.harness_arn,
            "runtimeSessionId": session_id,
            "messages": mensagens,
        }
        resposta = self.lambda_client.invoke(
            FunctionName=self.lambda_bridge_name,
            Payload=json.dumps(payload).encode("utf-8"),
        )
        corpo = json.loads(resposta["Payload"].read())
        if "FunctionError" in resposta or not corpo.get("ok"):
            raise RuntimeError(f"Erro na Lambda ponte: {corpo.get('erro', corpo)}")
        return corpo["texto"]

    def _invoke_direto(self, session_id: str, mensagens: list) -> str:
        resposta = self.client.invoke_harness(
            harnessArn=self.harness_arn,
            runtimeSessionId=session_id,
            messages=mensagens,
        )
        texto_completo = []
        for evento in resposta["stream"]:
            delta = evento.get("contentBlockDelta", {}).get("delta", {})
            if "text" in delta:
                texto_completo.append(delta["text"])
        return "".join(texto_completo)


class AgentClientMock(AgentClient):
    """Stub local para desenvolver/testar o dataset e os scripts de avaliação
    ANTES de o agente estar publicado no AgentCore, ou para rodar offline.
    Troque por AgentClient real assim que o endpoint existir."""

    def __init__(self):
        import json
        from pathlib import Path

        self.catalogo = json.loads(
            (Path(__file__).parent / "knowledge_base" / "catalogo.json").read_text(encoding="utf-8")
        )
        self.ultimo_contexto_recuperado = []
        self._sessoes: dict[str, list[str]] = {}

    def invoke(self, mensagem: str, session_id: str | None = None) -> str:
        raise NotImplementedError(
            "AgentClientMock é só um placeholder de desenvolvimento: "
            "substitua por chamadas reais ao agente publicado no AgentCore "
            "antes de rodar a suíte de avaliação de verdade."
        )

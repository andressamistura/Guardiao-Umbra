"""
Cliente fino para invocar o Harness "guardiao_umbra_harness" publicado no
AgentCore (não o Runtime "puro" do bedrock-agentcore-starter-toolkit; o
deploy real deste projeto usa Harness, criado via console, ver
planejamento.md secao 6). Usado por: sessão exploratória, dataset (geração
de respostas), suíte DeepEval e campanha de red teaming, para que todos
consultem exatamente o mesmo agente em produção/teste.

O formato de chamada abaixo (client.invoke_harness, resposta em streaming
via response['stream'] com eventos 'contentBlockDelta') foi copiado
diretamente do "View invocation code" da página de detalhes do Harness no
console AWS (Amazon Bedrock AgentCore > Harness > guardiao_umbra_harness),
não é um formato genérico assumido.

Uso:
    from agent_client import AgentClient
    client = AgentClient()
    resposta = client.invoke("Vocês têm o livro 1984?", session_id="teste-1")
    resposta2 = client.invoke("Tem exemplar disponível?", session_id="teste-1")
"""

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


class AgentClient:
    def __init__(self, harness_arn: str = HARNESS_ARN, region: str = AWS_REGION):
        self.harness_arn = harness_arn
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

        resposta = self.client.invoke_harness(
            harnessArn=self.harness_arn,
            runtimeSessionId=session_id,
            messages=[
                {"role": "user", "content": [{"text": mensagem}]},
            ],
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

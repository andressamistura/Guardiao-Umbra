"""
Cliente fino para invocar o agente BiblioAtende publicado no AgentCore.
Usado por: sessão exploratória, dataset (geração de respostas), suíte DeepEval
e campanha de red teaming — para que todos consultem exatamente o mesmo
agente em produção/teste.

Uso:
    from agent_client import AgentClient
    client = AgentClient()
    resposta = client.invoke("Vocês têm o livro 1984?", session_id="teste-1")
    resposta2 = client.invoke("Tem exemplar disponível?", session_id="teste-1")
    contextos_usados = client.ultimo_contexto_recuperado  # para Faithfulness
"""

import os
import uuid

import boto3

AGENT_RUNTIME_ARN = os.environ.get("BIBLIOATENDE_AGENT_ARN", "arn:aws:bedrock-agentcore:...:runtime/biblioatende")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


class AgentClient:
    def __init__(self, agent_arn: str = AGENT_RUNTIME_ARN, region: str = AWS_REGION):
        self.agent_arn = agent_arn
        self.client = boto3.client("bedrock-agentcore", region_name=region)
        self.ultimo_contexto_recuperado: list[str] = []

    def invoke(self, mensagem: str, session_id: str | None = None) -> str:
        """Envia uma mensagem ao agente, mantendo memória de sessão quando
        session_id é reaproveitado entre chamadas (necessário para os casos
        multi-turno do golden dataset)."""
        session_id = session_id or str(uuid.uuid4())

        resposta = self.client.invoke_agent_runtime(
            agentRuntimeArn=self.agent_arn,
            runtimeSessionId=session_id,
            payload={"prompt": mensagem},
        )

        corpo = resposta["response"].read()
        payload = corpo if isinstance(corpo, dict) else __import__("json").loads(corpo)

        # Guarda os trechos de contexto recuperados pela ferramenta de RAG,
        # quando o AgentCore os retorna nos metadados de trace — usado como
        # 'retrieval_context' na métrica de Faithfulness do DeepEval.
        self.ultimo_contexto_recuperado = payload.get("retrieved_context", [])

        return payload.get("output", payload.get("completion", ""))


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
            "AgentClientMock é só um placeholder de desenvolvimento — "
            "substitua por chamadas reais ao agente publicado no AgentCore "
            "antes de rodar a suíte de avaliação de verdade."
        )

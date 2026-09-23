"""
Wrapper de juiz Bedrock para o DeepEval, com mitigação de instabilidade para
um modelo barato (amazon.nova-micro-v1:0).

O DeepEval não interpreta IDs de modelo do Bedrock como string nativamente
(isso funciona de fábrica só para modelos OpenAI). Esta classe resolve isso
e aplica duas táticas de estabilidade, mantendo o custo baixo:

  1. temperature=0 -> reduz a variação aleatória entre chamadas idênticas.
  2. Autoconsistência (self-consistency) opcional -> repete a chamada N vezes
     de baixo custo (Nova Micro é muito barato) e usa a resposta mais
     frequente/mediana em vez de uma única amostra, suavizando ruído.

Achado de 23/09/2026 (ver planejamento.md secao 6): a mesma SCP que bloqueia
bedrock-agentcore:InvokeHarness para usuario IAM tambem bloqueia
bedrock:InvokeModel (via Converse), entao o juiz tambem precisa passar pela
Lambda "ponte" (agente/lambda_bridge/lambda_function.py) em vez de chamar
bedrock-runtime diretamente. Mesma logica usada em agent_client.py.

Uso:
    from bedrock_judge import BedrockJudgeModel
    juiz = BedrockJudgeModel(model_id="amazon.nova-micro-v1:0", self_consistency_n=3)
    metric = AnswerRelevancyMetric(threshold=0.7, model=juiz)
"""

import json
import os
from collections import Counter

import boto3
from deepeval.models import DeepEvalBaseLLM

LAMBDA_BRIDGE_NAME = os.environ.get("UMBRA_LAMBDA_BRIDGE", "teste-guardiao-umbra")
USAR_LAMBDA_BRIDGE = os.environ.get("UMBRA_USAR_LAMBDA_BRIDGE", "1") != "0"


class BedrockJudgeModel(DeepEvalBaseLLM):
    def __init__(
        self,
        model_id: str = "amazon.nova-micro-v1:0",
        region: str = None,
        self_consistency_n: int = 3,
        usar_lambda_bridge: bool = USAR_LAMBDA_BRIDGE,
        lambda_bridge_name: str = LAMBDA_BRIDGE_NAME,
    ):
        self.model_id = model_id
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        self.self_consistency_n = self_consistency_n
        self.usar_lambda_bridge = usar_lambda_bridge
        self.lambda_bridge_name = lambda_bridge_name
        if usar_lambda_bridge:
            self.client = boto3.client("lambda", region_name=self.region)
        else:
            self.client = boto3.client("bedrock-runtime", region_name=self.region)

    def load_model(self):
        return self.client

    def _gerar_uma_vez(self, prompt: str) -> str:
        if self.usar_lambda_bridge:
            return self._gerar_via_lambda(prompt)
        return self._gerar_direto(prompt)

    def _gerar_via_lambda(self, prompt: str) -> str:
        payload = {
            "acao": "converse",
            "modelId": self.model_id,
            "messages": [{"role": "user", "content": [{"text": prompt}]}],
            "inferenceConfig": {"temperature": 0, "maxTokens": 1024},
        }
        resposta = self.client.invoke(
            FunctionName=self.lambda_bridge_name,
            Payload=json.dumps(payload).encode("utf-8"),
        )
        corpo = json.loads(resposta["Payload"].read())
        if "FunctionError" in resposta or not corpo.get("ok"):
            raise RuntimeError(f"Erro na Lambda ponte (juiz): {corpo.get('erro', corpo)}")
        return corpo["texto"]

    def _gerar_direto(self, prompt: str) -> str:
        resposta = self.client.converse(
            modelId=self.model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={
                "temperature": 0,  # tática 1: elimina aleatoriedade de sampling
                "maxTokens": 1024,
            },
        )
        return resposta["output"]["message"]["content"][0]["text"]

    def generate(self, prompt: str) -> str:
        if self.self_consistency_n <= 1:
            return self._gerar_uma_vez(prompt)

        # tática 2: autoconsistência barata (Nova Micro é barato o
        # suficiente para repetir N vezes sem pesar no orçamento).
        respostas = [self._gerar_uma_vez(prompt) for _ in range(self.self_consistency_n)]

        # Heurística simples: se as respostas tiverem um veredito claro
        # (ex.: "Yes"/"No", número), usa o mais frequente; senão, usa a
        # resposta "mediana" em tamanho como proxy de resposta típica.
        contagem = Counter(r.strip() for r in respostas)
        mais_comum, freq = contagem.most_common(1)[0]
        if freq > 1:
            return mais_comum

        respostas_ordenadas = sorted(respostas, key=len)
        return respostas_ordenadas[len(respostas_ordenadas) // 2]

    async def a_generate(self, prompt: str) -> str:
        return self.generate(prompt)

    def get_model_name(self) -> str:
        return f"Bedrock:{self.model_id} (self-consistency={self.self_consistency_n})"

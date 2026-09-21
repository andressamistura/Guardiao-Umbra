"""
Setup do agente BiblioAtende no Amazon Bedrock AgentCore Harness.

Estratégia de custo (orçamento de créditos limitado: agente E juiz baratos):
- Modelo do AGENTE (responde ao usuário, chamado com alta frequência):
  amazon.titan-text-lite-v1, o Titan Text mais barato do Bedrock.
  ATENÇÃO: Titan Text Lite tem suporte mais fraco a tool/function calling
  que Nova ou Claude. Teste a ferramenta de RAG logo no início; se o
  AgentCore Harness não orquestrar a chamada de ferramenta de forma
  estável, troque para amazon.titan-text-premier-v1:0 (ainda barato, com
  melhor suporte a tool calling). Ver planejamento.md, seção 4.
- Modelo JUIZ (avalia, chamado só na etapa de avaliação): amazon.nova-
  micro-v1:0, o modelo mais barato do catálogo Bedrock, sem precisar de
  conta/API key de outro provedor (ver avaliacao/deepeval e
  avaliacao/agentcore).

Pré-requisitos:
  pip install bedrock-agentcore bedrock-agentcore-starter-toolkit boto3

Este script cria:
  1. Uma Knowledge Base (RAG) a partir de agente/knowledge_base/catalogo.json
  2. O agente no AgentCore Harness, com as instruções de
     agente/instrucoes_agente.md, a KB como ferramenta, e memória de sessão
     ligada (para multi-turno).

Ajuste os nomes de bucket/role/região para o seu ambiente AWS antes de rodar.
"""

import json
import os
from pathlib import Path

# --- Configuração -----------------------------------------------------------

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
# Titan Text Lite: o modelo Titan mais barato do Bedrock. Risco assumido:
# suporte mais fraco a tool calling que Nova/Claude, teste a ferramenta de
# RAG cedo. Fallback com melhor suporte a tool calling, ainda barato:
# amazon.titan-text-premier-v1:0.
AGENT_MODEL_ID = os.environ.get("AGENT_MODEL_ID", "amazon.titan-text-lite-v1")  # mais barato
# Nova Micro: o modelo mais barato do catálogo Bedrock, na mesma conta AWS
# do agente (sem precisar de API key de outro provedor). Risco assumido:
# raciocínio mais limitado, pode gerar notas mais ruidosas como juiz.
JUDGE_MODEL_ID = os.environ.get("JUDGE_MODEL_ID", "amazon.nova-micro-v1:0")  # o mais barato

S3_BUCKET_KB = os.environ.get("S3_BUCKET_KB", "biblioatende-kb-<sua-conta>")
AGENT_NAME = "biblioatende"

BASE_DIR = Path(__file__).parent
INSTRUCOES_PATH = BASE_DIR / "instrucoes_agente.md"
CATALOGO_PATH = BASE_DIR / "knowledge_base" / "catalogo.json"


def carregar_instrucoes() -> str:
    """Extrai o bloco de instruções (dentro do ```...```) do markdown."""
    texto = INSTRUCOES_PATH.read_text(encoding="utf-8")
    inicio = texto.find("```") + 3
    fim = texto.find("```", inicio)
    return texto[inicio:fim].strip()


def preparar_documentos_kb() -> list[dict]:
    """Converte o catálogo em 'documentos' textuais para indexação na KB
    (um chunk por livro + um chunk de regras), formato pronto para subir
    ao S3 e apontar como fonte de dados de uma Bedrock Knowledge Base."""
    catalogo = json.loads(CATALOGO_PATH.read_text(encoding="utf-8"))
    docs = []

    for livro in catalogo["livros"]:
        conteudo = (
            f"Título: {livro['titulo']}\n"
            f"Autor: {livro['autor']}\n"
            f"Gênero: {livro['genero']}\n"
            f"Ano: {livro['ano']}\n"
            f"ISBN: {livro['isbn']}\n"
            f"Sinopse: {livro['sinopse']}\n"
            f"Exemplares totais: {livro['exemplares_total']}\n"
            f"Exemplares disponíveis agora: {livro['exemplares_disponiveis']}\n"
        )
        docs.append({"id": livro["id"], "conteudo": conteudo})

    regras = catalogo["regras_biblioteca"]
    conteudo_regras = (
        "Regras gerais da Biblioteca Municipal:\n"
        f"Prazo de empréstimo: {regras['prazo_emprestimo_dias']} dias.\n"
        f"Renovações permitidas: {regras['renovacoes_permitidas']}.\n"
        f"Multa por dia de atraso: R$ {regras['multa_por_dia_atraso_reais']:.2f}.\n"
        f"Limite de livros por usuário: {regras['limite_livros_por_usuario']}.\n"
        f"Horário de funcionamento: {regras['horario_funcionamento']}\n"
        f"Como reservar: {regras['como_reservar']}\n"
        f"Seções: {json.dumps(regras['secoes'], ensure_ascii=False)}\n"
    )
    docs.append({"id": "REGRAS", "conteudo": conteudo_regras})
    return docs


def criar_agente():
    """Cria (ou atualiza) o agente no AgentCore Harness.

    Usa o bedrock-agentcore-starter-toolkit, que expõe uma API de alto nível
    para: subir a KB, registrar a ferramenta de RAG, configurar memória de
    sessão (multi-turno) e publicar o agente com as instruções do sistema.
    Trocar por chamadas diretas ao boto3 'bedrock-agentcore' se preferir
    controle mais fino.
    """
    from bedrock_agentcore_starter_toolkit import Runtime  # type: ignore

    instrucoes = carregar_instrucoes()
    documentos = preparar_documentos_kb()

    runtime = Runtime(region=AWS_REGION)

    # 1) Knowledge Base (ferramenta de RAG)
    kb = runtime.create_knowledge_base(
        name=f"{AGENT_NAME}-kb",
        s3_bucket=S3_BUCKET_KB,
        documents=documentos,
    )

    # 2) Agente com instruções, ferramenta de KB e memória de sessão ligada
    agente = runtime.create_agent(
        name=AGENT_NAME,
        model_id=AGENT_MODEL_ID,
        system_prompt=instrucoes,
        tools=[kb.as_tool(name="buscar_acervo_biblioteca")],
        session_memory=True,  # habilita contexto multi-turno nativo do AgentCore
    )

    print(f"Agente '{AGENT_NAME}' criado. Endpoint: {agente.endpoint}")
    print(f"Modelo do agente: {AGENT_MODEL_ID}")
    print(f"Modelo juiz (usar em avaliacao/): {JUDGE_MODEL_ID}")
    return agente


if __name__ == "__main__":
    criar_agente()

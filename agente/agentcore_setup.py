"""
Setup do agente Guardião da Umbra no Amazon Bedrock AgentCore Harness.

Estratégia de custo (orçamento de créditos limitado, tanto o agente quanto o
juiz usam modelos baratos, e o armazenamento vetorial da KB usa S3 Vectors
em vez de OpenSearch Serverless):

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
- Armazenamento vetorial da Knowledge Base: Amazon S3 Vectors, em vez do
  padrão (OpenSearch Serverless). OpenSearch Serverless cobra por capacidade
  reservada mesmo ocioso (relatos da turma: ~US$2,69 no primeiro dia,
  podendo chegar a US$40-50 numa semana), o que estoura um orçamento de
  US$20/mês sozinho. S3 Vectors cobra por uso (armazenamento + operações),
  muito mais barato para um catálogo pequeno (150 livros) usado
  esporadicamente. Por isso este script NÃO usa
  `bedrock_agentcore_starter_toolkit.Runtime.create_knowledge_base()`
  (que cria OpenSearch Serverless por padrão) e monta a Knowledge Base via
  boto3 puro, apontando explicitamente para S3 Vectors.

Pré-requisitos:
  pip install boto3 bedrock-agentcore bedrock-agentcore-starter-toolkit

Permissões necessárias no usuário/role que roda este script (além de
bedrock:*): s3:CreateBucket/PutObject/GetObject/ListBucket no bucket de
documentos-fonte; s3vectors:* no bucket/índice vetorial; iam:CreateRole,
iam:PutRolePolicy (para o service role da KB). Se seu usuário não tiver
permissão de IAM (comum em contas de sandbox/fellowship), peça para o
administrador da conta criar o role com o trust policy e as permissões
descritas em BEDROCK_KB_ROLE_TRUST_POLICY / BEDROCK_KB_ROLE_PERMISSIONS
abaixo, e passe o ARN pronto via a variável de ambiente
BEDROCK_KB_ROLE_ARN.

Este script cria:
  1. Um bucket S3 vetorial (S3 Vectors) + índice, para armazenar os
     embeddings da Knowledge Base a um custo mínimo.
  2. Uma Knowledge Base (RAG) apontando para esse índice, com os documentos
     de agente/knowledge_base/catalogo.json subidos para um bucket S3 comum
     (fonte de dados) e indexados.
  3. O agente no AgentCore Harness, com as instruções de
     agente/instrucoes_agente.md, a KB como ferramenta, e memória de sessão
     ligada (para multi-turno).

Ajuste os nomes de bucket/role/região para o seu ambiente AWS antes de rodar.
"""

import json
import os
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

# --- Configuração -----------------------------------------------------------

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
ACCOUNT_ID = os.environ.get("AWS_ACCOUNT_ID")  # se vazio, é descoberto via STS

# Titan Text Lite: o modelo Titan mais barato do Bedrock. Risco assumido:
# suporte mais fraco a tool calling que Nova/Claude, teste a ferramenta de
# RAG cedo. Fallback com melhor suporte a tool calling, ainda barato:
# amazon.titan-text-premier-v1:0.
AGENT_MODEL_ID = os.environ.get("AGENT_MODEL_ID", "amazon.titan-text-lite-v1")  # mais barato
# Nova Micro: o modelo mais barato do catálogo Bedrock, na mesma conta AWS
# do agente (sem precisar de API key de outro provedor). Risco assumido:
# raciocínio mais limitado, pode gerar notas mais ruidosas como juiz.
JUDGE_MODEL_ID = os.environ.get("JUDGE_MODEL_ID", "amazon.nova-micro-v1:0")  # o mais barato
# Modelo de embeddings para a KB (barato, cobrado só na indexação/consulta).
EMBEDDING_MODEL_ID = os.environ.get("EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v2:0")
EMBEDDING_DIMENSAO = int(os.environ.get("EMBEDDING_DIMENSAO", "1024"))

# Bucket S3 "comum" com os documentos-fonte (o que a KB lê para indexar).
# Pode ser um bucket já existente cedido pelo fellowship.
S3_BUCKET_DOCS = os.environ.get("S3_BUCKET_KB", "guardiao-umbra-kb-<sua-conta>")
S3_DOCS_PREFIX = "catalogo/"

# Bucket + índice vetorial do S3 Vectors (onde os embeddings ficam de fato).
S3_VECTOR_BUCKET = os.environ.get("S3_VECTOR_BUCKET", "guardiao-umbra-vectors")
S3_VECTOR_INDEX = os.environ.get("S3_VECTOR_INDEX", "guardiao-umbra-index")

# ARN de um service role já pronto para a KB (opcional). Se não for
# informado, o script tenta criar um novo role chamado ROLE_NAME_KB, o que
# só funciona se o usuário atual tiver permissão de IAM.
BEDROCK_KB_ROLE_ARN = os.environ.get("BEDROCK_KB_ROLE_ARN")
ROLE_NAME_KB = "GuardiaoUmbraKBRole"

# ID de uma Knowledge Base já criada manualmente (ex.: pelo console do
# Bedrock, usando "Create Managed Knowledge Base"). Se informado, o script
# PULA toda a criação de bucket/índice/role/KB e vai direto para criar o
# agente usando essa KB pronta. Use isso quando seu usuário não tem
# permissão de S3/IAM para o fluxo automático via boto3, mas um perfil com
# mais acesso (ex.: um role de admin do console) já criou a KB por você.
EXISTING_KB_ID = os.environ.get("UMBRA_KB_ID")

AGENT_NAME = "guardiao-umbra"
KB_NAME = f"{AGENT_NAME}-kb"

BASE_DIR = Path(__file__).parent
INSTRUCOES_PATH = BASE_DIR / "instrucoes_agente.md"
CATALOGO_PATH = BASE_DIR / "knowledge_base" / "catalogo.json"


def _sts_account_id(sess: boto3.Session) -> str:
    global ACCOUNT_ID
    if not ACCOUNT_ID:
        ACCOUNT_ID = sess.client("sts").get_caller_identity()["Account"]
    return ACCOUNT_ID


def carregar_instrucoes() -> str:
    """Extrai o bloco de instruções (dentro do ```...```) do markdown."""
    texto = INSTRUCOES_PATH.read_text(encoding="utf-8")
    inicio = texto.find("```") + 3
    fim = texto.find("```", inicio)
    return texto[inicio:fim].strip()


def preparar_documentos_kb() -> list[dict]:
    """Converte o catálogo em 'documentos' textuais para indexação na KB
    (um chunk por livro + um chunk de regras)."""
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
        "Regras gerais da Bibliotheca Umbra:\n"
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


def subir_documentos_s3(sess: boto3.Session, docs: list[dict]) -> None:
    """Sobe cada documento como um .txt no bucket S3 de origem (data source
    da KB). Não cria o bucket se ele já existir (útil quando o bucket foi
    cedido pelo administrador da conta, sem permissão de s3:CreateBucket)."""
    s3 = sess.client("s3")
    try:
        s3.head_bucket(Bucket=S3_BUCKET_DOCS)
    except ClientError:
        print(f"Bucket '{S3_BUCKET_DOCS}' não encontrado/sem acesso, tentando criar...")
        kwargs = {"Bucket": S3_BUCKET_DOCS}
        if AWS_REGION != "us-east-1":
            kwargs["CreateBucketConfiguration"] = {"LocationConstraint": AWS_REGION}
        s3.create_bucket(**kwargs)

    for doc in docs:
        key = f"{S3_DOCS_PREFIX}{doc['id']}.txt"
        s3.put_object(Bucket=S3_BUCKET_DOCS, Key=key, Body=doc["conteudo"].encode("utf-8"))
    print(f"{len(docs)} documentos enviados para s3://{S3_BUCKET_DOCS}/{S3_DOCS_PREFIX}")


def criar_bucket_e_indice_vetorial(sess: boto3.Session) -> str:
    """Cria (se não existir) o bucket vetorial e o índice do S3 Vectors.
    Retorna o ARN do índice, usado no storageConfiguration da KB."""
    s3v = sess.client("s3vectors", region_name=AWS_REGION)
    account_id = _sts_account_id(sess)

    try:
        s3v.create_vector_bucket(vectorBucketName=S3_VECTOR_BUCKET)
        print(f"Bucket vetorial '{S3_VECTOR_BUCKET}' criado.")
    except ClientError as e:
        if e.response["Error"]["Code"] not in ("ConflictException", "ResourceAlreadyExistsException"):
            raise
        print(f"Bucket vetorial '{S3_VECTOR_BUCKET}' já existia, reaproveitando.")

    try:
        s3v.create_index(
            vectorBucketName=S3_VECTOR_BUCKET,
            indexName=S3_VECTOR_INDEX,
            dimension=EMBEDDING_DIMENSAO,
            distanceMetric="cosine",
            dataType="float32",
            metadataConfiguration={"nonFilterableMetadataKeys": ["AMAZON_BEDROCK_TEXT"]},
        )
        print(f"Índice vetorial '{S3_VECTOR_INDEX}' criado.")
    except ClientError as e:
        if e.response["Error"]["Code"] not in ("ConflictException", "ResourceAlreadyExistsException"):
            raise
        print(f"Índice vetorial '{S3_VECTOR_INDEX}' já existia, reaproveitando.")

    return f"arn:aws:s3vectors:{AWS_REGION}:{account_id}:bucket/{S3_VECTOR_BUCKET}/index/{S3_VECTOR_INDEX}"


def obter_ou_criar_role_kb(sess: boto3.Session) -> str:
    """Retorna o ARN do service role da Knowledge Base. Usa
    BEDROCK_KB_ROLE_ARN se informado; senão tenta criar um role novo (só
    funciona se o usuário atual tiver permissão de IAM)."""
    if BEDROCK_KB_ROLE_ARN:
        return BEDROCK_KB_ROLE_ARN

    iam = sess.client("iam")
    account_id = _sts_account_id(sess)

    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "bedrock.amazonaws.com"},
            "Action": "sts:AssumeRole",
            "Condition": {
                "StringEquals": {"aws:SourceAccount": account_id},
                "ArnLike": {"AWS:SourceArn": f"arn:aws:bedrock:{AWS_REGION}:{account_id}:knowledge-base/*"},
            },
        }],
    }
    permissoes = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "InvokeEmbeddingModel",
                "Effect": "Allow",
                "Action": ["bedrock:InvokeModel"],
                "Resource": f"arn:aws:bedrock:{AWS_REGION}::foundation-model/{EMBEDDING_MODEL_ID}",
            },
            {
                "Sid": "ReadDocsBucket",
                "Effect": "Allow",
                "Action": ["s3:ListBucket", "s3:GetObject"],
                "Resource": [f"arn:aws:s3:::{S3_BUCKET_DOCS}", f"arn:aws:s3:::{S3_BUCKET_DOCS}/*"],
            },
            {
                "Sid": "S3VectorsAccess",
                "Effect": "Allow",
                "Action": [
                    "s3vectors:GetIndex", "s3vectors:QueryVectors", "s3vectors:PutVectors",
                    "s3vectors:GetVectors", "s3vectors:DeleteVectors",
                ],
                "Resource": f"arn:aws:s3vectors:{AWS_REGION}:{account_id}:bucket/{S3_VECTOR_BUCKET}/index/{S3_VECTOR_INDEX}",
            },
        ],
    }

    try:
        resp = iam.create_role(
            RoleName=ROLE_NAME_KB,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="Service role da Knowledge Base do agente Guardião da Umbra",
        )
        role_arn = resp["Role"]["Arn"]
        iam.put_role_policy(
            RoleName=ROLE_NAME_KB, PolicyName="GuardiaoUmbraKBPolicy",
            PolicyDocument=json.dumps(permissoes),
        )
        print(f"Role '{ROLE_NAME_KB}' criado: {role_arn}")
        print("Aguardando propagação do IAM (10s)...")
        time.sleep(10)
        return role_arn
    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityAlreadyExists":
            role_arn = iam.get_role(RoleName=ROLE_NAME_KB)["Role"]["Arn"]
            print(f"Role '{ROLE_NAME_KB}' já existia, reaproveitando: {role_arn}")
            return role_arn
        raise PermissionError(
            "Não foi possível criar o role de IAM da Knowledge Base "
            f"({e.response['Error']['Code']}). Se seu usuário não tem permissão de IAM "
            "(comum em contas de sandbox/fellowship), peça ao administrador para criar "
            "um role com o trust policy e as permissões documentadas no topo deste "
            "arquivo, e rode o script de novo com BEDROCK_KB_ROLE_ARN=<arn-do-role>."
        ) from e


def criar_knowledge_base(sess: boto3.Session, indice_arn: str, role_arn: str) -> str:
    """Cria a Knowledge Base apontando para o índice do S3 Vectors, cria a
    fonte de dados (o bucket S3 de documentos) e inicia a ingestão."""
    bedrock_agent = sess.client("bedrock-agent", region_name=AWS_REGION)
    account_id = _sts_account_id(sess)
    embedding_arn = f"arn:aws:bedrock:{AWS_REGION}::foundation-model/{EMBEDDING_MODEL_ID}"

    resp = bedrock_agent.create_knowledge_base(
        name=KB_NAME,
        description="Acervo e regras da Bibliotheca Umbra (RAG do Guardião da Umbra)",
        roleArn=role_arn,
        knowledgeBaseConfiguration={
            "type": "VECTOR",
            "vectorKnowledgeBaseConfiguration": {
                "embeddingModelArn": embedding_arn,
                "embeddingModelConfiguration": {
                    "bedrockEmbeddingModelConfiguration": {
                        "dimensions": EMBEDDING_DIMENSAO,
                        "embeddingDataType": "FLOAT32",
                    }
                },
            },
        },
        storageConfiguration={
            "type": "S3_VECTORS",
            "s3VectorsConfiguration": {"indexArn": indice_arn},
        },
    )
    kb_id = resp["knowledgeBase"]["knowledgeBaseId"]
    print(f"Knowledge Base '{KB_NAME}' criada: {kb_id}")

    ds = bedrock_agent.create_data_source(
        knowledgeBaseId=kb_id,
        name=f"{KB_NAME}-docs",
        dataSourceConfiguration={
            "type": "S3",
            "s3Configuration": {
                "bucketArn": f"arn:aws:s3:::{S3_BUCKET_DOCS}",
                "inclusionPrefixes": [S3_DOCS_PREFIX],
            },
        },
    )
    ds_id = ds["dataSource"]["dataSourceId"]

    ingest = bedrock_agent.start_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=ds_id)
    job_id = ingest["ingestionJob"]["ingestionJobId"]
    print(f"Ingestão iniciada (job {job_id}), aguardando concluir...")

    while True:
        status = bedrock_agent.get_ingestion_job(
            knowledgeBaseId=kb_id, dataSourceId=ds_id, ingestionJobId=job_id
        )["ingestionJob"]["status"]
        if status in ("COMPLETE", "FAILED"):
            print(f"Ingestão finalizada com status: {status}")
            break
        time.sleep(5)

    return kb_id


def criar_agente(kb_id: str, sess: boto3.Session):
    """Cria (ou atualiza) o agente no AgentCore Harness, usando a Knowledge
    Base (já indexada em S3 Vectors) como ferramenta de RAG.

    ATENÇÃO: `runtime.knowledge_base_tool(...)` abaixo assume que o
    bedrock-agentcore-starter-toolkit tem um jeito de referenciar uma KB já
    existente (criada por nós via boto3, fora do toolkit) pelo ID. Se a
    versão instalada não tiver esse método (rode
    `python -c "from bedrock_agentcore_starter_toolkit import Runtime; print([m for m in dir(Runtime) if 'knowledge' in m.lower()])"`
    para conferir), troque por uma chamada direta ao client
    `bedrock-agentcore` (boto3) que registre a KB como ferramenta do agente,
    ou consulte a documentação da versão instalada do toolkit.
    """
    from bedrock_agentcore_starter_toolkit import Runtime  # type: ignore

    instrucoes = carregar_instrucoes()
    runtime = Runtime(region=AWS_REGION)

    agente = runtime.create_agent(
        name=AGENT_NAME,
        model_id=AGENT_MODEL_ID,
        system_prompt=instrucoes,
        tools=[runtime.knowledge_base_tool(knowledge_base_id=kb_id, name="buscar_acervo_biblioteca")],
        session_memory=True,  # habilita contexto multi-turno nativo do AgentCore
    )

    print(f"Agente '{AGENT_NAME}' criado. Endpoint: {agente.endpoint}")
    print(f"Modelo do agente: {AGENT_MODEL_ID}")
    print(f"Modelo juiz (usar em avaliacao/): {JUDGE_MODEL_ID}")
    return agente


def main():
    sess = boto3.Session(region_name=AWS_REGION)

    if EXISTING_KB_ID:
        # Caminho curto: KB já criada (ex.: via console, com um perfil que
        # tinha mais permissão), não precisa criar bucket/índice/role/KB.
        print(f"Usando Knowledge Base existente: {EXISTING_KB_ID}")
        kb_id = EXISTING_KB_ID
    else:
        documentos = preparar_documentos_kb()
        subir_documentos_s3(sess, documentos)

        indice_arn = criar_bucket_e_indice_vetorial(sess)
        role_arn = obter_ou_criar_role_kb(sess)
        kb_id = criar_knowledge_base(sess, indice_arn, role_arn)

    criar_agente(kb_id, sess)


if __name__ == "__main__":
    main()

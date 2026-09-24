"""
Interface web simples (roxo/lilás, tema "mágico") para conversar com o
Guardião da Umbra sem precisar do playground do console AWS.

Roda LOCALMENTE, na sua máquina — não no sandbox do Claude — porque só a
sua máquina tem a variável de ambiente UMBRA_LAMBDA_BRIDGE_URL configurada
e rede liberada para chamar a Lambda ponte (ver agente/agent_client.py).

Como rodar:
    cd interface
    pip install flask --break-system-packages   # ou num virtualenv
    set UMBRA_LAMBDA_BRIDGE_URL=<sua Function URL>      (PowerShell: $env:UMBRA_LAMBDA_BRIDGE_URL="...")
    python app.py
    # abra http://localhost:5000 no navegador
"""

import sys
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request

# Permite importar agente/agent_client.py a partir desta pasta irmã.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agente"))
from agent_client import AgentClient  # noqa: E402

app = Flask(__name__)
_client = None


def get_client() -> AgentClient:
    global _client
    if _client is None:
        _client = AgentClient()
    return _client


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    dados = request.get_json(force=True) or {}
    mensagem = (dados.get("mensagem") or "").strip()
    session_id = dados.get("session_id") or str(uuid.uuid4())

    if not mensagem:
        return jsonify({"ok": False, "erro": "Mensagem vazia."}), 400

    try:
        resposta = get_client().invoke(mensagem, session_id=session_id)
        return jsonify({"ok": True, "resposta": resposta, "session_id": session_id})
    except Exception as e:  # noqa: BLE001 - queremos mostrar o erro real na UI
        return jsonify({"ok": False, "erro": f"{type(e).__name__}: {e}"}), 500


if __name__ == "__main__":
    print("Guardião da Umbra — interface local em http://localhost:5000")
    app.run(host="127.0.0.1", port=5000, debug=True)

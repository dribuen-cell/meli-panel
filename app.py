from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests, json, os, time
from datetime import datetime, timedelta
from pathlib import Path

app = Flask(__name__, static_folder="static")
CORS(app)

CONTAS = {
    "conta1": {
        "nome": "JA Comercial",
        "app_id": os.environ.get("MELI_APP_ID_1", "2598166159105156"),
        "secret": os.environ.get("MELI_SECRET_1", "EtB7015Db4zhzRvf8mPXSCX00DIwE5Wy"),
        "redirect": "https://www.universalvendas.com.br",
        "token_file": "token_conta1.json",
    },
    "conta2": {
        "nome": "Universal Vendas",
        "app_id": os.environ.get("MELI_APP_ID_2", ""),
        "secret": os.environ.get("MELI_SECRET_2", ""),
        "redirect": "https://www.universalvendas.com.br",
        "token_file": "token_conta2.json",
    },
}

USUARIOS = {
    "adriana": {"senha": os.environ.get("SENHA_ADRIANA", "ja2026"), "cargo": "Administrador"},
    "joao":    {"senha": os.environ.get("SENHA_JOAO",    "ja2026"), "cargo": "Operador"},
    "maria":   {"senha": os.environ.get("SENHA_MARIA",   "ja2026"), "cargo": "Operador"},
}

BASE_URL = "https://api.mercadolibre.com"
ATRIBUTOS_IGNORAR = {"COLOR", "SELLER_SKU", "PRODUCT_FEATURES"}


def carregar_token(conta_id):
    path = CONTAS[conta_id]["token_file"]
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def salvar_token(conta_id, data):
    with open(CONTAS[conta_id]["token_file"], "w") as f:
        json.dump(data, f, indent=2)


def token_valido(conta_id):
    data = carregar_token(conta_id)
    if not data:
        return None, "Token não encontrado"
    expires_at = datetime.fromisoformat(data.get("expires_at", "2000-01-01"))
    if datetime.now() >= expires_at - timedelta(minutes=5):
        return None, "Token expirado"
    return data["access_token"], None


def headers_auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@app.route("/api/login", methods=["POST"])
def login():
    body = request.json
    usuario = body.get("usuario", "").lower()
    senha = body.get("senha", "")
    user = USUARIOS.get(usuario)
    if not user or user["senha"] != senha:
        return jsonify({"ok": False, "erro": "Usuário ou senha inválidos"}), 401
    return jsonify({"ok": True, "nome": usuario.capitalize(), "cargo": user["cargo"]})


@app.route("/api/tokens/status")
def tokens_status():
    resultado = {}
    for cid, conf in CONTAS.items():
        data = carregar_token(cid)
        if not data:
            resultado[cid] = {"valido": False, "motivo": "Não configurado"}
            continue
        expires_at = datetime.fromisoformat(data.get("expires_at", "2000-01-01"))
        restante = expires_at - datetime.now()
        valido = restante.total_seconds() > 0
        resultado[cid] = {
            "valido": valido,
            "nome": conf["nome"],
            "expira": expires_at.strftime("%H:%M"),
            "restante_min": max(0, int(restante.total_seconds() // 60)),
        }
    return jsonify(resultado)


@app.route("/api/tokens/renovar", methods=["POST"])
def renovar_token():
    body = request.json
    conta_id = body.get("conta")
    codigo = body.get("codigo", "").strip()
    if conta_id not in CONTAS:
        return jsonify({"ok": False, "erro": "Conta inválida"}), 400
    conf = CONTAS[conta_id]
    r = requests.post(f"{BASE_URL}/oauth/token", data={
        "grant_type": "authorization_code",
        "client_id": conf["app_id"],
        "client_secret": conf["secret"],
        "code": codigo,
        "redirect_uri": conf["redirect"],
    })
    if r.status_code != 200:
        return jsonify({"ok": False, "erro": r.json().get("message", "Erro desconhecido")}), 400
    data = r.json()
    data["expires_at"] = (datetime.now() + timedelta(seconds=data.get("expires_in", 21600))).isoformat()
    salvar_token(conta_id, data)
    return jsonify({"ok": True, "expira": data["expires_at"]})


@app.route("/api/fotos/upload", methods=["POST"])
def upload_foto():
    conta_id = request.form.get("conta", "conta1")
    token, erro = token_valido(conta_id)
    if erro:
        return jsonify({"ok": False, "erro": erro}), 401
    if "foto" not in request.files:
        return jsonify({"ok": False, "erro": "Nenhuma foto enviada"}), 400
    foto = request.files["foto"]
    r = requests.post(f"{BASE_URL}/pictures",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": (foto.filename, foto.read(), foto.content_type)})
    if r.status_code in (200, 201):
        return jsonify({"ok": True, "picture_id": r.json().get("id")})
    return jsonify({"ok": False, "erro": r.text[:200]}), 400


@app.route("/api/variacoes/criar", methods=["POST"])
def criar_variacao():
    body = request.json
    contas_sel = body.get("contas", ["conta1"])
    linhas = body.get("linhas", [])
    fotos_banco = body.get("fotos_banco", {})
    dry_run = body.get("dry_run", False)
    resultados = []
    for conta_id in contas_sel:
        token, erro = token_valido(conta_id)
        if erro:
            resultados.append({"conta": conta_id, "ok": False, "erro": erro})
            continue
        for linha in linhas:
            mlbu = str(linha.get("familia_id", "")).strip()
            variacao = linha.get("variacao", "").strip()
            preco = float(linha.get("preco", 0))
            estoque = int(linha.get("estoque", 0))
            sku = linha.get("sku", "")
            ean = linha.get("ean", "")
            peso_g = linha.get("peso_g")
            altura_cm = linha.get("altura_cm")
            largura_cm = linha.get("largura_cm")
            comp_cm = linha.get("comprimento_cm")
            MAPA = {
                "1440439500323454": "MLB6433755258",
                "2463760158107016": "MLB6463760042",
                "764882427383523":  "MLB6451920282",
            }
            mlb_ref = MAPA.get(mlbu)
            if not mlb_ref:
                resultados.append({"conta": conta_id, "familia": mlbu, "variacao": variacao, "ok": False, "erro": f"Família {mlbu} não mapeada"})
                continue
            r = requests.get(f"{BASE_URL}/items/{mlb_ref}", headers=headers_auth(token))
            if r.status_code != 200:
                resultados.append({"conta": conta_id, "familia": mlbu, "variacao": variacao, "ok": False, "erro": f"Erro ao buscar template {mlb_ref}"})
                continue
            template = r.json()
            atribs = [a for a in template.get("attributes", []) if a.get("id") not in ATRIBUTOS_IGNORAR]
            atribs.append({"id": "COLOR", "value_name": variacao})
            if sku: atribs.append({"id": "SELLER_SKU", "value_name": sku})
            if ean: atribs.append({"id": "GTIN", "value_name": ean})
            if peso_g: atribs.append({"id": "SELLER_PACKAGE_WEIGHT", "value_name": f"{int(float(peso_g))} g"})
            if altura_cm: atribs.append({"id": "SELLER_PACKAGE_HEIGHT", "value_name": f"{int(float(altura_cm))} cm"})
            if largura_cm: atribs.append({"id": "SELLER_PACKAGE_WIDTH", "value_name": f"{int(float(largura_cm))} cm"})
            if comp_cm: atribs.append({"id": "SELLER_PACKAGE_LENGTH", "value_name": f"{int(float(comp_cm))} cm"})
            picture_ids = fotos_banco.get(variacao, {}).get("picture_ids", [])
            payload = {
                "category_id": template.get("category_id"),
                "domain_id": template.get("domain_id"),
                "family_name": template.get("family_name"),
                "price": preco,
                "available_quantity": estoque,
                "listing_type_id": template.get("listing_type_id", "gold_special"),
                "buying_mode": "buy_it_now",
                "condition": template.get("condition", "new"),
                "currency_id": "BRL",
                "attributes": atribs,
                "shipping": {"mode": "me2"},
            }
            if picture_ids: payload["pictures"] = [{"id": pid} for pid in picture_ids]
            if dry_run:
                resultados.append({"conta": conta_id, "familia": mlbu, "variacao": variacao, "ok": True, "dry_run": True, "payload_resumo": f"R${preco} | {len(picture_ids)} fotos"})
                continue
            r2 = requests.post(f"{BASE_URL}/items", headers=headers_auth(token), json=payload)
            if r2.status_code in (200, 201):
                resultados.append({"conta": conta_id, "familia": mlbu, "variacao": variacao, "ok": True, "mlb_criado": r2.json().get("id", "?")})
            else:
                resultados.append({"conta": conta_id, "familia": mlbu, "variacao": variacao, "ok": False, "erro": r2.json().get("message", r2.text[:200]), "cause": r2.json().get("cause", [])})
            time.sleep(0.5)
    return jsonify({"ok": True, "resultados": resultados})


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/health")
def health():
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})


if __name__ == "__main__":
    app.run(debug=False, port=int(os.environ.get("PORT", 5000)))

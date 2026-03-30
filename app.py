import os, json, requests, time
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__)

# ── Configuração das contas ──────────────────────────────────────────
CONTAS = {
    'conta1': {
        'app_id':    os.environ.get('MELI_APP_ID_1', '2598166159105156'),
        'secret':    os.environ.get('MELI_SECRET_1', 'EtB7015Db4zhzRvf8mPXSCX00DIwE5Wy'),
        'token_key': 'MELI_TOKEN_1',   # variável de ambiente para o token
        'nome':      'JA Comercial',
    },
    'conta2': {
        'app_id':    os.environ.get('MELI_APP_ID_2', ''),
        'secret':    os.environ.get('MELI_SECRET_2', ''),
        'token_key': 'MELI_TOKEN_2',
        'nome':      'Universal Vendas',
    },
}

BASE_URL   = 'https://api.mercadolibre.com'
REDIRECT   = 'https://meli-panel.onrender.com/callback'

# Senhas dos usuários
SENHAS = {
    'adriana': os.environ.get('SENHA_ADRIANA', '123456'),
    'joao':    os.environ.get('SENHA_JOAO',    '123456'),
}

# ── Armazenamento de tokens em memória + env var ──────────────────────
# Em produção: token fica na variável de ambiente MELI_TOKEN_1 (JSON)
# Em memória durante a sessão para não perder entre requests
_tokens_cache = {}

def carregar_token(conta_id):
    # 1. Tenta cache em memória
    if conta_id in _tokens_cache:
        return _tokens_cache[conta_id]
    # 2. Tenta variável de ambiente
    key = CONTAS[conta_id]['token_key']
    raw = os.environ.get(key)
    if raw:
        try:
            data = json.loads(raw)
            _tokens_cache[conta_id] = data
            return data
        except Exception:
            pass
    return None

def salvar_token(conta_id, data):
    # Salva no cache em memória (persiste enquanto o servidor estiver rodando)
    _tokens_cache[conta_id] = data
    # NOTA: para persistir entre deploys, configure a env var no Render:
    # MELI_TOKEN_1 = {"access_token":"...","expires_at":"...","refresh_token":"..."}

def token_valido(conta_id):
    data = carregar_token(conta_id)
    if not data:
        return None, 'Token não encontrado'
    try:
        expires_at = datetime.fromisoformat(data.get('expires_at', '2000-01-01'))
        if datetime.now() >= expires_at - timedelta(minutes=5):
            # Tentar renovar via refresh_token automaticamente
            refresh = data.get('refresh_token')
            if refresh:
                conta = CONTAS[conta_id]
                r = requests.post(BASE_URL + '/oauth/token', data={
                    'grant_type':    'refresh_token',
                    'client_id':     conta['app_id'],
                    'client_secret': conta['secret'],
                    'refresh_token': refresh,
                })
                if r.status_code == 200:
                    novo = r.json()
                    novo['expires_at'] = (datetime.now() + timedelta(seconds=novo.get('expires_in', 21600))).isoformat()
                    salvar_token(conta_id, novo)
                    return novo['access_token'], None
            return None, 'Token expirado'
        return data['access_token'], None
    except Exception as e:
        return None, f'Erro ao validar token: {str(e)}'

def headers_auth(token):
    return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

# ── Rotas ─────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'timestamp': datetime.now().isoformat()})

@app.route('/api/login', methods=['POST'])
def login():
    body = request.json or {}
    usuario = body.get('usuario', '').lower()
    senha   = body.get('senha', '')
    if usuario in SENHAS and SENHAS[usuario] != senha:
        return jsonify({'ok': False, 'erro': 'Senha incorreta'}), 401
    nomes = {'adriana': 'Adriana', 'joao': 'João'}
    cargos= {'adriana': 'Administrador', 'joao': 'Operador'}
    nome = nomes.get(usuario, usuario.capitalize())
    return jsonify({'ok': True, 'nome': nome, 'cargo': cargos.get(usuario, 'Operador')})

@app.route('/api/tokens/status')
def tokens_status():
    result = {}
    for conta_id in CONTAS:
        data = carregar_token(conta_id)
        if not data:
            result[conta_id] = {'valido': False, 'motivo': 'Não configurado'}
            continue
        try:
            expires_at = datetime.fromisoformat(data.get('expires_at', '2000-01-01'))
            mins = int((expires_at - datetime.now()).total_seconds() / 60)
            if mins <= 5:
                result[conta_id] = {'valido': False, 'motivo': 'Expirado', 'minutos_restantes': mins}
            else:
                result[conta_id] = {'valido': True, 'minutos_restantes': mins}
        except Exception:
            result[conta_id] = {'valido': False, 'motivo': 'Erro'}
    return jsonify(result)

@app.route('/api/tokens/renovar', methods=['POST'])
def renovar_token():
    body    = request.json or {}
    conta_id= body.get('conta', 'conta1')
    codigo  = body.get('codigo', '').strip()
    if not codigo:
        return jsonify({'ok': False, 'erro': 'Código não informado'}), 400
    conta = CONTAS.get(conta_id)
    if not conta:
        return jsonify({'ok': False, 'erro': 'Conta inválida'}), 400
    try:
        r = requests.post(BASE_URL + '/oauth/token', data={
            'grant_type':   'authorization_code',
            'client_id':     conta['app_id'],
            'client_secret': conta['secret'],
            'code':          codigo,
            'redirect_uri':  REDIRECT,
        })
        d = r.json()
        if r.status_code != 200:
            return jsonify({'ok': False, 'erro': d.get('message', str(d))}), 400
        d['expires_at'] = (datetime.now() + timedelta(seconds=d.get('expires_in', 21600))).isoformat()
        salvar_token(conta_id, d)
        # Instrução para persistir
        token_json = json.dumps({
            'access_token':  d['access_token'],
            'refresh_token': d.get('refresh_token', ''),
            'expires_at':    d['expires_at'],
        })
        return jsonify({
            'ok': True,
            'expires_at': d['expires_at'],
            'dica': f'Para persistir entre deploys, salve no Render: {conta["token_key"]} = {token_json}'
        })
    except Exception as e:
        return jsonify({'ok': False, 'erro': str(e)}), 500

@app.route('/api/tokens/auto-renovar', methods=['POST'])
def auto_renovar():
    body     = request.json or {}
    conta_id = body.get('conta', 'conta1')
    token, erro = token_valido(conta_id)
    if erro:
        return jsonify({'ok': False, 'erro': erro})
    return jsonify({'ok': True})

@app.route('/callback')
def callback():
    code = request.args.get('code', '')
    return f'''<html><body style="font-family:sans-serif;padding:40px;text-align:center">
    <h2>✓ Código recebido!</h2>
    <p>Copie o código abaixo e cole no painel:</p>
    <div style="background:#f5f5f5;padding:16px;border-radius:8px;font-family:monospace;font-size:16px;margin:20px 0;word-break:break-all">{code}</div>
    <button onclick="navigator.clipboard.writeText('{code}').then(()=>this.textContent='Copiado!')" 
      style="background:#FFE600;border:none;padding:12px 24px;border-radius:8px;font-size:16px;cursor:pointer;font-weight:600">
      Copiar código
    </button>
    <p style="margin-top:20px;color:#666">Você pode fechar esta aba após copiar.</p>
    </body></html>'''

@app.route('/api/fotos/upload', methods=['POST'])
def upload_foto():
    conta_id = request.form.get('conta', 'conta1')
    token, erro = token_valido(conta_id)
    if erro:
        return jsonify({'ok': False, 'erro': erro}), 401
    foto = request.files.get('foto')
    if not foto:
        return jsonify({'ok': False, 'erro': 'Nenhuma foto enviada'}), 400
    try:
        r = requests.post(
            BASE_URL + '/pictures/items/upload',
            headers={'Authorization': f'Bearer {token}'},
            files={'file': (foto.filename, foto.stream, foto.mimetype)}
        )
        d = r.json()
        if r.status_code not in (200, 201):
            return jsonify({'ok': False, 'erro': d.get('message', str(d))}), 400
        return jsonify({'ok': True, 'picture_id': d.get('id')})
    except Exception as e:
        return jsonify({'ok': False, 'erro': str(e)}), 500

@app.route('/api/variacoes/criar', methods=['POST'])
def criar_variacao():
    body         = request.json or {}
    contas_sel   = body.get('contas', ['conta1'])
    linhas       = body.get('linhas', [])
    fotos_banco  = body.get('fotos_banco', {})
    dry_run      = body.get('dry_run', False)
    resultados   = []

    for conta_id in contas_sel:
        token, erro = token_valido(conta_id)
        if erro:
            for linha in linhas:
                resultados.append({
                    'conta':    conta_id,
                    'familia':  str(linha.get('familia_id','')),
                    'variacao': linha.get('variacao',''),
                    'ok':       False,
                    'erro':     erro,
                })
            continue

        for linha in linhas:
            familia_id = str(linha.get('familia_id', '')).strip()
            variacao   = linha.get('variacao', '').strip()
            preco      = float(linha.get('preco', 0))
            estoque    = int(linha.get('estoque', 0))
            sku        = linha.get('sku', '')
            ean        = linha.get('ean', '')
            peso_g     = linha.get('peso_g')
            altura_cm  = linha.get('altura_cm')
            largura_cm = linha.get('largura_cm')
            comp_cm    = linha.get('comprimento_cm')

            # Mapa de atributos padrão para variações
            MAPA = {
                'cor':    'COLOR',
                'tamanho':'SIZE',
                'modelo': 'MODEL',
            }

            # Fotos da variação
            picture_ids = []
            fb = fotos_banco.get(variacao, {})
            if isinstance(fb, dict):
                picture_ids = fb.get('picture_ids', [])

            # Dimensões
            shipping_dimensions = None
            if peso_g or altura_cm or largura_cm or comp_cm:
                shipping_dimensions = {
                    'weight': {'value': float(peso_g or 0), 'unit': 'g'},
                    'dimensions': {
                        'height':  {'value': float(altura_cm or 0),  'unit': 'cm'},
                        'width':   {'value': float(largura_cm or 0), 'unit': 'cm'},
                        'length':  {'value': float(comp_cm or 0),    'unit': 'cm'},
                    }
                }

            # Atributos da variação
            atributos = [{'id': 'SELLER_SKU', 'value_name': sku}] if sku else []
            if ean:
                atributos.append({'id': 'EAN', 'value_name': ean})

            variacao_payload = {
                'attribute_combinations': [{'id': 'COLOR', 'value_name': variacao}],
                'price':    preco,
                'available_quantity': estoque,
                'attributes': atributos,
                'picture_ids': picture_ids,
            }
            if shipping_dimensions:
                variacao_payload['shipping_dimensions'] = shipping_dimensions

            payload = {
                'catalog_product_id': familia_id,
                'variations': [variacao_payload],
            }

            if dry_run:
                resultados.append({
                    'conta':   conta_id, 'familia': familia_id, 'variacao': variacao,
                    'ok':      True, 'dry_run': True,
                    'payload_resumo': f'R${preco:.2f} | {len(picture_ids)} fotos | {estoque} estoque',
                })
                continue

            try:
                r = requests.post(
                    BASE_URL + '/items',
                    headers=headers_auth(token),
                    json=payload,
                    timeout=30,
                )
                d = r.json()
                if r.status_code in (200, 201):
                    resultados.append({
                        'conta': conta_id, 'familia': familia_id, 'variacao': variacao,
                        'ok': True, 'mlb_criado': d.get('id', '?'),
                    })
                else:
                    resultados.append({
                        'conta': conta_id, 'familia': familia_id, 'variacao': variacao,
                        'ok': False, 'erro': d.get('message', r.text[:200]),
                        'cause': d.get('cause', []),
                    })
            except Exception as e:
                resultados.append({
                    'conta': conta_id, 'familia': familia_id, 'variacao': variacao,
                    'ok': False, 'erro': str(e),
                })
            time.sleep(0.3)

    return jsonify({'ok': True, 'resultados': resultados})

if __name__ == '__main__':
    app.run(debug=True, port=5000)

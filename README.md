# MELI Panel — JA Comercial

App web para criar variações em massa no Mercado Livre.

## Como publicar no Render (gratuito)

### 1. Criar conta no GitHub
Acesse https://github.com e crie uma conta (se não tiver).

### 2. Criar repositório e subir os arquivos
```bash
cd /Users/adrianabueno/meli-panel
git init
git add .
git commit -m "primeira versão"
git remote add origin https://github.com/SEU_USUARIO/meli-panel.git
git push -u origin main
```

### 3. Publicar no Render
1. Acesse https://render.com e faça login com o GitHub
2. Clique em **New → Web Service**
3. Selecione o repositório `meli-panel`
4. Preencha:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`
5. Deploy -> URL: `https://meli-panel.onrender.com`

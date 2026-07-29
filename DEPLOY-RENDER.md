# Subir o painel para o Render

O painel roda como **um serviço web** no Render: o backend FastAPI serve o
frontend, o WebSocket (`/ws`) e faz o polling do BigQuery. O repositório já
está no GitHub (`ygormaas/oficina-realtime`), que é de onde o Render puxa.

## O que já está pronto no repositório

- `render.yaml` — o "blueprint" com build, start, health check e variáveis.
- `backend/app/bq.py` — aceita a credencial do BigQuery por variável de
  ambiente (`GOOGLE_APPLICATION_CREDENTIALS_JSON`), pois no Render não há
  arquivo de chave no disco.
- O frontend já usa `wss://` quando o acesso é HTTPS (funciona no Render).

## Passo a passo (primeira vez)

### 1. Enviar o código para o GitHub
Se ainda não subiu as últimas mudanças:
```bash
git add render.yaml DEPLOY-RENDER.md backend/app/bq.py
git commit -m "Deploy no Render: blueprint + credencial por env var"
git push origin main
```

### 2. Criar o serviço no Render
1. Acesse <https://dashboard.render.com> e faça login (pode usar a conta GitHub).
2. **New +** → **Blueprint**.
3. Conecte/selecione o repositório `ygormaas/oficina-realtime`.
4. O Render lê o `render.yaml` e mostra o serviço `oficina-resumo`. Clique em
   **Apply**.

### 3. Colar a credencial do BigQuery
O deploy vai pedir o valor do secret `GOOGLE_APPLICATION_CREDENTIALS_JSON`
(está marcado como `sync: false`, ou seja, você preenche na mão):

1. Abra o arquivo local `credenciais/service-account-key.json` num editor de texto.
2. Copie **todo** o conteúdo (o JSON inteiro, das chaves `{` a `}`).
3. No Render → serviço `oficina-resumo` → **Environment** → variável
   `GOOGLE_APPLICATION_CREDENTIALS_JSON` → cole o conteúdo e salve.
4. O Render redeploya sozinho.

> Alternativa: em vez do JSON na variável, dá para usar **Secret Files** no
> Render (mount em `/etc/secrets/...`) e apontar `GOOGLE_APPLICATION_CREDENTIALS`
> para esse caminho. Os dois caminhos funcionam; o JSON em variável é o mais simples.

### 4. Conferir se subiu
Quando o status ficar **Live**, teste na URL do serviço
(algo como `https://oficina-resumo.onrender.com`):

- `…/healthz` → deve responder `{"ok": true, ...}`.
- `…/api/resumo` → o payload em JSON (pode dar 503 nos primeiros ~segundos,
  até o primeiro ciclo terminar).
- `…/` → o painel, com o indicador verde "ao vivo".

## Atualizações futuras
Com `autoDeploy: true` no `render.yaml`, todo `git push origin main` dispara
um novo deploy automaticamente. Não precisa mexer no Render.

## Observações importantes

- **Plano free hiberna.** No plano `free`, o serviço dorme após ~15 min sem
  tráfego e demora alguns segundos para acordar no próximo acesso — ruim para
  uma TV que fica ligada o dia todo. Para uso 24/7, troque `plan: free` por
  `plan: starter` no `render.yaml` (serviço pago) e faça push.
- **Segurança.** A pasta `credenciais/` e o `.env` continuam no `.gitignore` —
  a chave **não** vai para o GitHub. No Render ela vive só como variável de
  ambiente do serviço.
- **Rede do BigQuery.** A service account precisa do papel *BigQuery Data
  Viewer* no projeto `gcp-maas-proj-manutencao` (já é o caso da chave atual).
- **Custo do BigQuery.** O polling roda a cada `POLL_SECONDS` (300s = 5 min),
  24/7. Se quiser reduzir consultas fora do horário, dá para aumentar esse valor.

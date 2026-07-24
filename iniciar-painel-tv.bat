@echo off
rem ============================================================================
rem  Central de Inteligencia - Resumo Oficina (MAAS)
rem  Inicia o servidor local e abre o painel em tela cheia na TV.
rem
rem  Este script e texto puro, legivel e sem persistencia escondida:
rem  quem liga a maquina da um duplo-clique aqui. Nada e gravado no registro
rem  nem em pasta de inicializacao. (Ver PARA-TI.txt para o auto-inicio
rem  aprovado pela seguranca, se desejado.)
rem
rem  O servidor escuta so em 127.0.0.1 (localhost): o navegador roda na
rem  propria maquina ligada a TV, entao nao precisa abrir porta na rede.
rem ============================================================================

title Resumo Oficina - Servidor (nao feche esta janela)

rem Credencial do BigQuery: caminho calculado a partir da propria pasta,
rem entao viaja junto no copiar-colar. A chave fica em credenciais\ (fora do
rem git). Definida aqui, tem prioridade sobre o .env.
set "GOOGLE_APPLICATION_CREDENTIALS=%~dp0credenciais\service-account-key.json"

if not exist "%GOOGLE_APPLICATION_CREDENTIALS%" (
  echo.
  echo [ERRO] Credencial nao encontrada em:
  echo    %GOOGLE_APPLICATION_CREDENTIALS%
  echo Coloque o arquivo service-account-key.json na pasta credenciais\
  echo Veja credenciais\LEIA-ME.txt
  echo.
  pause
  exit /b 1
)

rem Pasta do backend, relativa a este .bat (funciona em qualquer maquina).
cd /d "%~dp0backend"

rem Sobe o servidor numa janela propria e visivel (transparencia p/ o EDR).
rem Usa o Python PORTATIL embutido em ..\runtime\python (nao precisa instalar
rem Python na maquina; a pasta inteira e autossuficiente).
start "Resumo Oficina - Servidor" "%~dp0runtime\python\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000

rem Espera o servidor responder /healthz antes de abrir o navegador,
rem senao a TV mostraria "nao foi possivel conectar" no primeiro instante.
echo Aguardando o servidor subir...
:aguarda
timeout /t 2 /nobreak >nul
curl -sf http://127.0.0.1:8000/healthz >nul 2>&1
if errorlevel 1 goto aguarda
echo Servidor no ar.

rem Abre o painel em quiosque (tela cheia, sem barras). Sair: Alt+F4.
start "" "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --kiosk "http://127.0.0.1:8000" --edge-kiosk-type=fullscreen --no-first-run --disable-features=Translate

exit

@echo off
rem ============================================================================
rem  Cria o atalho "Painel da Oficina" na Area de Trabalho, apontando para o
rem  iniciar-painel-tv.bat DESTA pasta. Rode UMA vez apos copiar a pasta para
rem  a maquina (ex.: na maquina da TV). O atalho preserva o caminho correto,
rem  entao pode clicar por ele sem quebrar os componentes.
rem ============================================================================
setlocal
set "ALVO=%~dp0iniciar-painel-tv.bat"
set "PASTA=%~dp0"

powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$lnk = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\Painel da Oficina.lnk');" ^
  "$lnk.TargetPath = '%ALVO%';" ^
  "$lnk.WorkingDirectory = '%PASTA%';" ^
  "$lnk.WindowStyle = 1;" ^
  "$lnk.Description = 'Abre o painel da oficina em tela cheia';" ^
  "$lnk.IconLocation = 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe,0';" ^
  "$lnk.Save()"

echo.
echo Atalho "Painel da Oficina" criado na Area de Trabalho.
echo Use ele para abrir o painel.
echo.
pause
endlocal

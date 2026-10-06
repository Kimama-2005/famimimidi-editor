@echo off
chcp 932 >nul
rem ふぁみみみっでぃ 音色エディタ(新しい画面)を起動する。
rem 部品の置き場(仮想環境)は、プロジェクト内の .venv が使えればそれを、
rem 使えなければ(別のパソコンにコピーした など)このパソコン用に %LOCALAPPDATA% に作る。
rem 作るときは vendor\wheels から入れる(ネットは使わない)。Python は 3.14 か 3.13(64ビット)。
cd /d "%~dp0"

rem 音色や設定を user_data に保存するので、書き込めるフォルダでないと動かない
set "PROBE=%~dp0user_data\.write_test"
if not exist "%~dp0user_data" mkdir "%~dp0user_data" 2>nul
(echo test> "%PROBE%") 2>nul
if not exist "%PROBE%" (
  echo.
  echo このフォルダには書き込めません:
  echo   %~dp0
  echo 音色や設定を保存できないため、起動できません。
  echo 「Program Files」の中などは書き込めません。
  echo famimimidi-editor フォルダごと、ドキュメントやデスクトップに移してから、もう一度 run.bat を開いてください。
  echo.
  pause
  exit /b 1
)
del "%PROBE%" 2>nul

set "PY="
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import webview" >nul 2>&1 && set "PY=.venv\Scripts\python.exe"
)
set "LOCALVENV=%LOCALAPPDATA%\FamimimidiEditor\venv"
if not defined PY if exist "%LOCALVENV%\Scripts\python.exe" (
  "%LOCALVENV%\Scripts\python.exe" -c "import webview" >nul 2>&1 && set "PY=%LOCALVENV%\Scripts\python.exe"
)
if not defined PY (
  rem Python 3.14 か 3.13 の64ビット版を探す。py ランチャーがあれば、複数の Python が入っていても選べる
  set "BASEPY="
  py -3.14 -c "import struct, sys; sys.exit(struct.calcsize('P') != 8)" >nul 2>&1 && set "BASEPY=py -3.14"
  if not defined BASEPY py -3.13 -c "import struct, sys; sys.exit(struct.calcsize('P') != 8)" >nul 2>&1 && set "BASEPY=py -3.13"
  if not defined BASEPY python -c "import struct, sys; sys.exit(0 if sys.version_info[:2] in ((3, 13), (3, 14)) and struct.calcsize('P') == 8 else 1)" >nul 2>&1 && set "BASEPY=python"
)
if not defined PY if not defined BASEPY (
  echo.
  echo Python 3.14 か 3.13^(64ビット^)が見つかりません。
  echo python.org から Python 3.14 を入れてください。入れるときに「Add python.exe to PATH」にチェックを入れます。
  echo いま入っている Python:
  python --version 2>nul
  py -0 2>nul
  echo.
  pause
  exit /b 1
)
if not defined PY (
  echo このパソコン用の部品を用意しています^(初回だけ。ネットは使いません^)...
  if exist "%LOCALVENV%" rmdir /s /q "%LOCALVENV%"
  %BASEPY% -m venv "%LOCALVENV%"
  if errorlevel 1 goto setup_failed
  "%LOCALVENV%\Scripts\python.exe" -m pip install --no-index --find-links vendor\wheels -r requirements.txt
  if errorlevel 1 goto setup_failed
  set "PY=%LOCALVENV%\Scripts\python.exe"
)

"%PY%" -m famimimidi.webapp
if errorlevel 1 pause
exit /b

:setup_failed
echo.
echo 部品の用意に失敗しました。上のメッセージを Claude に伝えてください。
echo.
pause
exit /b 1

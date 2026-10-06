@echo off
chcp 932 >nul
rem デスクトップに「FAMIMIMIDI SOUND EDITOR」のショートカット(アイコン付き)を作る。
rem ショートカットは run.bat を最小化した状態で開く(黒い画面が前に出ない)。
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$d = [Environment]::GetFolderPath('Desktop');" ^
  "$s = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'FAMIMIMIDI SOUND EDITOR.lnk'));" ^
  "$s.TargetPath = (Join-Path '%~dp0' 'run.bat');" ^
  "$s.WorkingDirectory = '%~dp0';" ^
  "$s.IconLocation = (Join-Path '%~dp0' 'famimimidi\icon.ico');" ^
  "$s.WindowStyle = 7;" ^
  "$s.Description = 'ふぁみみみっでぃ 音色エディタ';" ^
  "$s.Save(); Write-Host ('作りました: ' + $s.FullName)"
if errorlevel 1 (
  echo ショートカットを作れませんでした。
)
pause

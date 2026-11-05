"""ファイルの置き場所。テストでは user_data・logs を一時フォルダに差し替える(実際の user_data を書き換えない)。"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
USER_DIR = ROOT / "user_data"
LOG_DIR = ROOT / "logs"
SPEC_PATH = DATA_DIR / "famimimidi_spec.json"

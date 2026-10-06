"""ユーザー設定(user_data/settings.json)。tkinter 版と新しい画面で共有する。"""
import json

from .spec import ROOT

SETTINGS_PATH = ROOT / "user_data" / "settings.json"


def load_settings():
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(d):
    SETTINGS_PATH.parent.mkdir(exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

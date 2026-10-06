"""アイコン(famimimidi/icon.ico と famimimidi/web/icon.png)を作る。

16×16 のドット絵(ファミコンのカセット+音符)を、ぼかさずに拡大して各サイズを作る。
作るときだけ Pillow を使う(アプリ本体は Pillow を使わない)。  python tools/make_icon.py
"""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent

PIXELS = [
    "................",
    "..OOOOOOOOOOOO..",
    "..ORRRRRRRRRRO..",
    "..ORLLLLLLLLRO..",
    "..ORLLLLLKKLRO..",
    "..ORLLLLLKLKRO..",
    "..ORLLLLLKLLRO..",
    "..ORLLLKKKLLRO..",
    "..ORLLKKKKLLRO..",
    "..ORLLLKKLLLRO..",
    "..ORRRRRRRRRRO..",
    "..ORDRDRDRDRRO..",
    "..ORDRDRDRDRRO..",
    "..ORRRRRRRRRRO..",
    "..OOOOOOOOOOOO..",
    "................",
]
COLORS = {
    ".": (0, 0, 0, 0),
    "O": (28, 28, 28, 255),       # 輪郭
    "R": (184, 28, 24, 255),      # カセットの赤
    "D": (120, 16, 12, 255),      # 溝
    "L": (248, 184, 0, 255),      # ラベル(画面のテーマ A の強調色)
    "K": (28, 28, 28, 255),       # 音符
}


def base():
    img = Image.new("RGBA", (16, 16))
    for y, row in enumerate(PIXELS):
        for x, ch in enumerate(row):
            img.putpixel((x, y), COLORS[ch])
    return img


def main():
    img = base()
    sizes = [16, 32, 48, 64, 128, 256]
    big = img.resize((256, 256), Image.NEAREST)
    big.save(ROOT / "famimimidi" / "icon.ico", sizes=[(s, s) for s in sizes])
    img.resize((64, 64), Image.NEAREST).save(ROOT / "famimimidi" / "web" / "icon.png")
    big.save(ROOT / "docs" / "icon.png")
    print("ok")


if __name__ == "__main__":
    main()

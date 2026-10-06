"""画面から独立した「アプリの中身」: 仕様、送信の関所、ライブラリ、カートリッジ対応表、接続、設定。

フェーズC の新しい画面(webapp.py)はこれを使う。送信は必ず engine.send() を通す(関所・ログ)。
"""
import time

from . import winmm
from .cartridge import CartState
from .engine import MidiEngine, SendLog
from . import play
from .library import Library, Patch, PerfSet, diff_from_defaults, new_id
from .settings import load_settings, save_settings
from .spec import editable_params, load_spec

OFFSETS = {0: "ch1〜5(通常起動)", 5: "ch6〜10(Bを押しながら電源ON)", 10: "ch11〜15(A+Bを押しながら電源ON)"}
THEMES = {"rpg": "A: RPGウィンドウ", "console": "B: ファミコン本体カラー", "crt": "C: ブラウン管"}


class Core:
    def __init__(self, log=None, cart=None, lib=None, settings=None):
        self.spec, self.params = load_spec()
        self.settings = load_settings() if settings is None else settings
        self.log = log or SendLog()
        self.engine = MidiEngine(self.log, self.params)
        self.engine.ch_offset = self.settings.get("ch_offset", 0)
        self.engine.thru_enabled = self.settings.get("thru", True)
        if "play" not in self.settings:     # 以前の「開いているタブのchで鳴らす」のオン/オフを引き継ぐ
            self.settings["play"] = {"mode": "tab" if self.settings.get("thru_remap", True) else "through"}
        self.engine.set_play(self.settings["play"])        # フェーズD の形式は play.normalize が割り当て表に直す
        self.loaded_set = None                              # 最後に読み込んだ/保存した演奏セット
        self.cart = cart or CartState.load()
        self.lib = lib or Library()
        # 各チャンネルの「画面上の値」(カートリッジは読めないので、送った値の記録)
        self.values = {ch: self._defaults(ch) for ch in range(1, 6)}
        self.loaded = {ch: None for ch in range(1, 6)}      # 読み込んだ音色(Patch)

    # ---------- 音色の値 ----------
    def _defaults(self, ch):
        return {p.cc: p.default for p in editable_params(self.params, ch) if p.default is not None}

    @property
    def linked(self):
        """2音(ch1+ch2)のときは、ch1 の音色を ch2 にも同じように送る"""
        return self.engine.router.linked

    def set_values(self, ch, updates):
        """値を変えて送る(同じ CC は間引いて最新値だけ)。この ch に無い CC は無視"""
        for target in ((1, 2) if ch == 1 and self.linked else (ch,)):
            vals = self.values[target]
            for c, v in updates.items():
                c, v = int(c), max(0, min(127, int(v)))
                if c in vals:
                    vals[c] = v
                    self.engine.set_cc(target, c, v)

    def apply_patch(self, patch, ch=None):
        """全項目を既定値にしてから音色の値で上書きし、全部送る(CC#121 は使わない)。→ この ch で効かない CC"""
        ch = ch or patch.channel
        want = patch.cc_dict()
        self.log.note(f"音色を読み込み: {patch.name}(ch{ch})… 全項目を既定値+音色の値で送信")
        self.set_values(ch, {c: want.get(c, d) for c, d in self._defaults(ch).items()})
        self.loaded[ch] = patch
        if ch == 1 and self.linked:
            self.loaded[2] = patch
        return sorted(set(want) - set(self.values[ch]))

    def reset_defaults(self, ch):
        self.set_values(ch, self._defaults(ch))
        self.loaded[ch] = None
        if ch == 1 and self.linked:
            self.loaded[2] = None

    def send_all(self, ch):
        self.set_values(ch, dict(self.values[ch]))

    # ---------- ライブラリ ----------
    def _current_cc(self, ch, previous=None):
        """画面の値 → 既定値と違う CC だけ(前の並び順を保つ)"""
        prev = [c for c, _ in (previous.cc if previous else [])]
        return diff_from_defaults(self.values[ch], self.params, prev)

    def save_new(self, ch, name, category="other", notes=""):
        base = self.loaded[ch]
        p = Patch(id=new_id(name), name=name, channel=ch, category=category or "other", notes=notes,
                  cc=self._current_cc(ch, base))
        self.lib.add(p)
        self.loaded[ch] = p
        self.log.note(f"ライブラリに新規保存: {p.name}(ch{ch}、CC {len(p.cc)}個)")
        return p

    def overwrite(self, pid, ch):
        p = self.lib.get(pid)
        if p is None:
            raise ValueError("その音色はライブラリにありません")
        p.cc = self._current_cc(ch, p)
        p.channel = ch
        self.lib.update(p)
        self.loaded[ch] = p
        self.log.note(f"ライブラリを上書き保存: {p.name}(ch{ch}、CC {len(p.cc)}個)")
        return p

    # ---------- 演奏セット ----------
    def _snapshot(self):
        """今の 5ch の音色と割り当て表 → (parts, play)"""
        parts = {}
        for ch in range(1, 6):
            prev = self.loaded[ch]
            cc = self._current_cc(ch, prev)
            if prev is None:
                name = ""
            elif self.values[ch] == {c: prev.cc_dict().get(c, d) for c, d in self._defaults(ch).items()}:
                name = prev.name
            else:
                name = f"{prev.name}(変更あり)"
            src = prev.id if prev is not None and self.lib.get(prev.id) else ""
            parts[str(ch)] = {"name": name, "cc": cc, "source": src}
        cfg = play.to_json(self.engine.router.cfg)
        return parts, {"pair": cfg["pair"], "parts": cfg["parts"]}

    def save_set(self, name, notes=""):
        parts, pmap = self._snapshot()
        ps = PerfSet(id=new_id(name), name=name, parts=parts, play=pmap, notes=notes)
        self.lib.add_set(ps)
        self.loaded_set = ps
        self.log.note(f"演奏セットを新規保存: {ps.name}({play.describe_map(play.normalize(pmap))})")
        return ps

    def overwrite_set(self, sid):
        ps = self.lib.get_set(sid)
        if ps is None:
            raise ValueError("その演奏セットはライブラリにありません")
        ps.parts, ps.play = self._snapshot()
        self.lib.update_set(ps)
        self.loaded_set = ps
        self.log.note(f"演奏セットを上書き保存: {ps.name}")
        return ps

    def load_set(self, sid):
        """5ch の音色を送り、割り当て表を入れて「割り当て表で鳴らす」にする"""
        ps = self.lib.get_set(sid)
        if ps is None:
            raise ValueError("その演奏セットはライブラリにありません")
        self.log.note(f"演奏セットを読み込み: {ps.name}")
        self.engine.set_play({"mode": "map", **ps.play})
        self.settings["play"] = play.to_json(self.engine.router.cfg)
        self.save_settings()
        for ch in range(1, 6):
            self.apply_patch(ps.part_patch(ch), ch)
        self.loaded_set = ps
        return ps

    def save_settings(self):
        save_settings(self.settings)

    # ---------- 接続 ----------
    def ports(self):
        return {"out": winmm.list_outputs(), "in": winmm.list_inputs(),
                "want_out": self.settings.get("out_name"), "want_in": self.settings.get("in_name")}

    def connect(self, out_name, in_name=None):
        """名前で開く。→ {"ok", "message"}。他のアプリが使用中などのときは分かりやすい説明を返す"""
        self.disconnect()
        outs, ins = winmm.list_outputs(), winmm.list_inputs()
        if out_name not in outs:
            return {"ok": False, "message": f"出力ポート「{out_name}」が見つかりません。USBケーブルを確認してください。"}
        try:
            self.engine.set_output(winmm.OutputPort(outs.index(out_name), out_name))
        except winmm.MidiPortError as e:
            self.log.note(f"出力の接続に失敗: {e}")
            return {"ok": False, "message": str(e)}
        message = ""
        if in_name:
            if in_name in ins:
                try:
                    self.engine.set_input(winmm.InputPort(ins.index(in_name), in_name, self.engine.on_input))
                except winmm.MidiPortError as e:
                    self.log.note(f"入力の接続に失敗: {e}")
                    message = f"{e}\n出力だけ接続した状態で続けます。"
            else:
                message = f"入力ポート「{in_name}」が見つかりません。出力だけ接続しました。"
        self.settings["out_name"] = self.engine.output_name
        self.settings["in_name"] = self.engine.input_name
        self.save_settings()
        return {"ok": True, "message": message}

    def disconnect(self):
        self.engine.set_input(None)
        self.engine.set_output(None)

    def status(self):
        e = self.engine
        return {"out": e.output_name, "in": e.input_name, "thru": e.thru_enabled, "offset": e.ch_offset,
                "writing": e.writing, "theme": self.settings.get("theme", "rpg"),
                "play": play.to_json(e.router.cfg),
                "play_text": e.router.describe(e.thru_channel), "layer_detune": self.settings.get("layer_detune", 16)}

    # ---------- 設定 ----------
    def set_thru(self, on):
        self.engine.thru_enabled = bool(on)
        self.settings["thru"] = bool(on)
        self.save_settings()
        self.log.note(f"MIDIスルー: {'ON' if on else 'OFF'}")

    def set_tab(self, ch):
        """開いているタブ(鍵盤の弾き方が「開いているタブのch」のときの送り先)"""
        self.engine.thru_channel = int(ch)

    def set_play(self, cfg):
        """鍵盤の弾き方(mode と割り当て表)を変える。2音にしたときは ch1 の音色を ch2 にも送ってそろえる"""
        was = self.linked
        self.engine.set_play(cfg)
        cfg = play.to_json(self.engine.router.cfg)
        self.settings["play"] = cfg
        self.save_settings()
        self.log.note(f"鍵盤の弾き方: {self.engine.router.describe(self.engine.thru_channel)}")
        if self.linked and not was:
            # 実機の ch1 が画面の値とずれていることもあるので、ch1 にも送り直して2つをそろえる
            self.log.note("2音にしたので、画面の ch1 の音色を ch1 と ch2 の両方に送ってそろえます")
            self.values[2] = {c: self.values[1].get(c, v) for c, v in self.values[2].items()}
            self.loaded[2] = self.loaded[1]
            self.send_all(1)
        return cfg

    # 重ねるときに ch2 をずらす量(セント。CC#85 は 64 が ±0)。ファミコンの音程は段階でしか作れないので、
    # 8 だと D5・A5・B5 などで丸められて 0 段(うねらない)になる(docs/03 F35)。初期値は 16
    LAYER_DETUNES = {8: "少し", 16: "普通", 24: "強め"}

    def copy_for_layer(self, amount=16):
        """重ねる用: ch1 の音色を ch2 にコピーし、ch2 だけ音程を少し上にずらす(うなりで厚みが出る)"""
        amount = int(amount) if int(amount) in self.LAYER_DETUNES else 16
        self.settings["layer_detune"] = amount
        self.save_settings()
        vals = {c: self.values[1].get(c, v) for c, v in self.values[2].items()}
        vals[85] = min(127, vals.get(85, 64) + amount)
        self.log.note(f"重ねる用に、ch1 の音色を ch2 にコピーし、ch2 のデチューンを {vals[85] - 64:+d} に")
        self.set_values(2, vals)
        self.loaded[2] = None

    def set_offset(self, offset):
        if offset in OFFSETS:
            self.engine.ch_offset = offset
            self.settings["ch_offset"] = offset
            self.save_settings()
            self.log.note(f"音源のチャンネルを {OFFSETS[offset]} に設定")

    def set_theme(self, theme):
        if theme in THEMES:
            self.settings["theme"] = theme
            self.save_settings()

    # ---------- カートリッジへの書き込み ----------
    def run_write(self, plan, progress=None, done=None):
        """確認済みの計画を実行する。前後にパニックを送り、書き込み中はほかの送信を止める(engine)。
        done(ok, message) は別スレッドから呼ばれる。→ 始められなければ理由の文字列"""
        from .cartridge import WriteJob
        if not self.engine.output_name:
            return "ふぁみみみっでぃに接続していません。"
        if self.engine.writing:
            return "ほかの書き込みが終わるまで待ってください。"
        self.engine.panic()
        secs = sum(s.wait_ms for s in plan.steps) / 1000
        self._write_deadline = time.monotonic() + secs + 20      # これを過ぎても終わらなければ「応答なし」とみなす

        def fin(ok, error, recorded):
            if ok:
                plan.on_success(self.cart)
                self.log.note("書き込み完了。対応表を更新しました")
            else:
                plan.on_failure(self.cart, error, recorded)
                self.log.note(f"書き込み失敗: {error}")
            self.cart.save()
            self.engine.panic()
            if done:
                done(ok, plan.done_message if ok else
                     f"{error}\n影響したかもしれない番号は、対応表で「不明」にしました。")

        self.log.note(f"書き込み: {plan.title}")
        WriteJob(self.engine, plan.steps, fin, progress).start()
        return None

    def write_overdue(self):
        """書き込みが予定の時間を大きく過ぎても終わっていないか(固まったときに閉じられるようにする)"""
        return self.engine.writing and time.monotonic() > getattr(self, "_write_deadline", float("inf"))

    def shutdown(self):
        """何も送らずにポートを閉じる"""
        self.engine.shutdown()
        self.log.close()

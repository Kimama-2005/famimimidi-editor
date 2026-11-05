"""テスト用の偽の MIDI(winmm の代わり)。送ったバイトを覚えておく。"""


class FakeMidiPortError(Exception):
    pass


class FakeOut:
    def __init__(self, index, name, sent):
        self.name, self._sent = name, sent

    def send(self, msg):
        self._sent.append(bytes(msg))

    def close(self):
        pass


class FakeIn:
    def __init__(self, index, name, cb):
        self.name, self.cb = name, cb

    def close(self):
        pass


class FakeMidi:
    MidiPortError = FakeMidiPortError

    def __init__(self, outs=("USB MIDI Interface",), ins=("microKEY2",)):
        self.outs, self.ins = list(outs), list(ins)
        self.sent = []
        self.inputs = []

    def list_outputs(self):
        return list(self.outs)

    def list_inputs(self):
        return list(self.ins)

    def OutputPort(self, index, name):  # noqa: N802 — winmm と同じ名前
        return FakeOut(index, name, self.sent)

    def InputPort(self, index, name, cb):  # noqa: N802
        p = FakeIn(index, name, cb)
        self.inputs.append(p)
        return p

    def take(self):
        out, self.sent[:] = list(self.sent), []
        return out

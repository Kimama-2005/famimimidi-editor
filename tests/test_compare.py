import unittest

from famimimidi.compare import diff
from famimimidi.library import Patch
from famimimidi.spec import load_spec


class CompareTest(unittest.TestCase):
    def setUp(self):
        _, self.params = load_spec()

    def test_format_value(self):
        p = self.params
        self.assertEqual(p[70].format_value(48), "25%")
        self.assertEqual(p[22].format_value(127), "ON")
        self.assertEqual(p[26].format_value(4), "Up")
        self.assertEqual(p[72].format_value(20), "20")

    def test_diff_orders_by_importance_and_marks_inaudible(self):
        a = Patch(id="a", name="A", channel=1, cc=[[70, 16], [23, 127], [24, 3]])
        b = Patch(id="b", name="B", channel=1, cc=[[70, 48], [24, 20]])
        rows = diff(a, b, self.params)
        self.assertEqual([r.cc for r in rows], [70, 23, 24])
        self.assertEqual((rows[0].a, rows[0].b), ("12.5%", "25%"))
        self.assertTrue(rows[2].audible)          # A ではアルペジエーターが効いているので、速さの違いは聞こえる
        c = Patch(id="c", name="C", channel=1, cc=[[24, 3]])
        d = Patch(id="d", name="D", channel=1, cc=[[24, 20]])
        self.assertFalse(diff(c, d, self.params)[0].audible)   # 両方 OFF なら速さの違いは聞こえない

    def test_same_step_is_not_a_difference(self):
        a = Patch(id="a", name="A", channel=1, cc=[[70, 16]])
        b = Patch(id="b", name="B", channel=1, cc=[[70, 20]])   # どちらも 12.5%
        self.assertEqual(diff(a, b, self.params), [])


if __name__ == "__main__":
    unittest.main()

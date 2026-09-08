"""창 크기가 화면 밖으로 나가지 않는가 (Phase 7.5).

**앱을 실제로 띄워 보고 찾은 문제다.** 테스트 392개가 전부 통과하는 상태였지만,
`main.py`가 요청하는 크기(1536x1000, 최소 1100x700)는 이 개발 기기의 화면(1080x1196)
보다 커서 창 오른쪽이 잘린 채 떴다. 최소 크기가 화면보다 크므로 **사용자가 줄여서
맞출 수도 없었다.**

여기서는 창 크기 계산만 검증한다 - 실제로 창을 띄우는 것은 자동화 테스트의 몫이
아니고, 계산이 맞으면 화면 밖으로 나가지 않는다.
"""

import unittest
from unittest import mock

import main


class FakeScreen:
    def __init__(self, width, height):
        self.width, self.height = width, height


def with_screen(width, height):
    return mock.patch.object(main.webview, "screens", [FakeScreen(width, height)])


class WindowSizeTests(unittest.TestCase):
    def fit(self):
        return main._fit_to_screen(main.PREFERRED_SIZE, main.MIN_SIZE)

    # ------------------------------------------------------------------
    def test_a_small_screen_gets_a_window_that_fits(self):
        """이 문제를 실제로 만난 화면(1080x1196)."""
        with with_screen(1080, 1196):
            (width, height), min_size, (x, y) = self.fit()

        self.assertLessEqual(x + width, 1080, "창이 화면 오른쪽으로 나간다")
        self.assertLessEqual(y + height, 1196, "창이 화면 아래로 나간다")
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)

    def test_the_minimum_size_never_exceeds_the_screen(self):
        """최소 크기가 화면보다 크면 사용자가 줄여서 맞출 수 없다 - 원래 버그가 이것이다."""
        for screen_width, screen_height in [(1080, 1196), (1024, 768), (800, 600)]:
            with self.subTest(screen=(screen_width, screen_height)), \
                 with_screen(screen_width, screen_height):
                (width, height), (min_w, min_h), _pos = self.fit()
                self.assertLessEqual(min_w, screen_width)
                self.assertLessEqual(min_h, screen_height)
                self.assertLessEqual(min_w, width, "최소가 초기 크기보다 크면 모순이다")
                self.assertLessEqual(min_h, height)

    def test_a_big_screen_gets_the_preferred_size(self):
        """작은 화면 때문에 큰 화면까지 좁혀 놓으면 안 된다."""
        with with_screen(2560, 1440):
            (width, height), _min_size, _pos = self.fit()
        self.assertEqual((width, height), main.PREFERRED_SIZE)

    def test_the_layout_minimum_is_one_we_actually_verified(self):
        """900px는 뷰포트 실측(가로 넘침 0px)으로 정한 값이다.

        예전 값(1100)은 1080px 화면에 아예 들어가지 않았다. 이 숫자를 다시 올릴 때는
        그 폭에서 레이아웃이 견디는지 먼저 재 볼 것.
        """
        self.assertLessEqual(main.MIN_SIZE[0], 1024,
                             "흔한 소형 화면(1024px)에도 들어가야 한다")

    def test_it_still_works_when_the_screen_is_unknown(self):
        """화면 정보를 못 얻는 환경에서도 창은 떠야 한다."""
        class Broken:
            @property
            def screens(self):
                raise RuntimeError("화면 정보를 얻을 수 없습니다")

        with mock.patch.object(main, "webview", Broken()):
            size, min_size, position = main._fit_to_screen(main.PREFERRED_SIZE, main.MIN_SIZE)
        self.assertEqual(size, main.PREFERRED_SIZE)
        self.assertEqual(min_size, main.MIN_SIZE)
        self.assertEqual(position, (None, None))


if __name__ == "__main__":
    unittest.main()

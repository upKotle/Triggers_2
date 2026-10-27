"""Проверки декодирования SVG и совместимости с результатами старого скрипта."""

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import re
import subprocess
import sys
import unittest

from main import solve_file
from src.trigger_reader import get2, get3, parse_svg, read_svg


ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "examples"
# Зафиксированные значения исходных примеров; SVG в examples/ синтетические.
# Q/#Q в results — результаты прежних алгоритмов, а не новая модель триггеров.
SAMPLES = {
    "rs_nor.svg": (
        1, {"R": "1110011000", "S": "0011010100", "Q": "", "#Q": ""},
        ("0001100111", "1100001000"),
    ),
    "rs_nand.svg": (
        2, {"#R": "1000010000", "#S": "0110100010", "Q": "", "#Q": ""},
        ("1001011101", "0111101111"),
    ),
    "rs_sync.svg": (
        3, {"CLK": "1001100110", "R": "1011101000", "S": "0011110111",
            "Q": "", "#Q": ""},
        ("00011XX111", "11111XX000"),
    ),
    "rs_two_stage.svg": (
        4, {"CLK": "1001100110", "R": "0100000000", "S": "1110111000",
            "Q": "0", "#Q": "1"},
        ("0111111111", "1000000000"),
    ),
    "jk_two_stage.svg": (
        5, {"CLK": "1001100110", "J": "1101100110", "K": "0010111111",
            "Q": "0", "#Q": "1"},
        ("0111100001", "1000011110"),
    ),
    "d_two_stage.svg": (
        6, {"CLK": "1001100110", "D": "0010111100", "Q": "0", "#Q": "1"},
        ("0000011110", "1111100001"),
    ),
    "d_dynamic.svg": (
        7, {"CLK": "00110011001100110011", "D": "00101110101011010011",
            "Q": "1", "#Q": "0"},
        ("11000011110000111100", "00111100001111000011"),
    ),
}


class SvgTests(unittest.TestCase):
    def test_all_sample_signals_and_types(self):
        for filename, (kind, expected, _) in SAMPLES.items():
            with self.subTest(filename=filename):
                diagram = read_svg(FIXTURES / filename)
                self.assertEqual(diagram.trigger_type, kind)
                self.assertEqual(diagram.signals, {k: list(v) for k, v in expected.items()})
                self.assertEqual(diagram.ticks, len(next(iter(expected.values()))))

    def test_results_match_old_algorithms(self):
        for filename, (_, _, expected) in SAMPLES.items():
            with self.subTest(filename=filename):
                output = StringIO()
                with redirect_stdout(output):
                    solve_file(FIXTURES / filename)
                q = re.findall(r"^Q: ([01X]+)$", output.getvalue(), re.M)
                nq = re.findall(r"^#Q: ([01X]+)$", output.getvalue(), re.M)
                self.assertEqual((q[-1], nq[-1]), expected)

    def test_initial_values_are_not_extended_to_full_length(self):
        filename = next(name for name, data in SAMPLES.items() if data[0] == 7)
        clk, d, q, nq = get2(False, diagram=read_svg(FIXTURES / filename))
        self.assertEqual((len(clk), len(d), q, nq), (20, 20, "1", "0"))

    def test_inputs_are_matched_by_name_not_row_order(self):
        filename = next(name for name, data in SAMPLES.items() if data[0] == 5)
        diagram = read_svg(FIXTURES / filename)
        expected = get3(False, diagram=diagram)
        diagram.signals = dict(reversed(list(diagram.signals.items())))
        self.assertEqual(get3(False, diagram=diagram), expected)

    def test_svg2_href_without_xlink(self):
        filename = next(iter(SAMPLES))
        svg = (FIXTURES / filename).read_text(encoding="utf-8").replace("xlink:href=", "href=")
        self.assertEqual(parse_svg(svg), read_svg(FIXTURES / filename))

    def test_file_uri_and_quoted_path(self):
        path = FIXTURES / next(iter(SAMPLES))
        self.assertEqual(read_svg(path.as_uri()), read_svg(f'"{path}"'))

    def test_rejects_other_files_and_broken_xml(self):
        for content in ("hello", "<svg>", "<html/>"):
            with self.subTest(content=content), self.assertRaises(ValueError):
                parse_svg(content)

    def test_rejects_unsupported_waveform(self):
        svg = (FIXTURES / next(iter(SAMPLES))).read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Неподдерживаемый элемент"):
            parse_svg(svg.replace('href="#111"', 'href="#zzz"'))

    def test_rejects_missing_ticks(self):
        svg = (FIXTURES / next(iter(SAMPLES))).read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "шкала тактов"):
            parse_svg(svg.replace('class="muted"', 'class="other"'))

    def test_rejects_missing_initial_state(self):
        filename = next(name for name, data in SAMPLES.items() if data[0] == 6)
        diagram = read_svg(FIXTURES / filename)
        diagram.signals["Q"] = []
        with self.assertRaisesRegex(ValueError, "начальное значение Q"):
            get2(False, diagram=diagram)

    def test_rejects_short_input(self):
        diagram = read_svg(FIXTURES / next(iter(SAMPLES)))
        diagram.signals["R"].pop()
        with self.assertRaisesRegex(ValueError, "всех 10 тактов"):
            get2(diagram=diagram)

    def test_unknown_title_needs_explicit_type(self):
        svg = (FIXTURES / next(iter(SAMPLES))).read_text(encoding="utf-8")
        diagram = parse_svg(svg.replace("Асинхронный RS", "Другой RS"))
        self.assertIsNone(diagram.trigger_type)
        with self.assertRaisesRegex(ValueError, "--type"):
            get2(diagram=diagram)
        diagram.trigger_type = 1
        self.assertEqual(len(get2(diagram=diagram)[0]), 10)


class CliTests(unittest.TestCase):
    def test_all_files_from_another_working_directory(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "main.py"), *[str(FIXTURES / name) for name in SAMPLES]],
            cwd=ROOT.parent, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(re.findall(r"^Q: [01X]+$", result.stdout, re.M)), 7)

    def test_error_does_not_stop_other_files(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "main.py"), str(ROOT / "missing.svg"),
             str(FIXTURES / next(iter(SAMPLES)))], capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing.svg", result.stderr)
        self.assertRegex(result.stdout, r"Q: 0001100111")

    def test_interactive_selection_and_exit(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "main.py")], input="\n1\n0\n",
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Q: 11000011110000111100", result.stdout)


if __name__ == "__main__":
    unittest.main()

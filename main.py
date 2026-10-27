"""Расчёт триггеров по скачанным SVG. Запуск: python3 main.py файл.svg."""

import argparse
from pathlib import Path
import sys

from src.rs_nor1 import rs_nor
from src.rs_nand2 import rs_nand
from src.onestep_rs_nand3 import onestep_rs_nand
from src.twostep_rs_nand4 import twostep_rs_nand
from src.twostep_jk_nand5 import twostep_jk_nand
from src.syn_d_nand6 import syn_d_nand
from src.dyn_d_nand7 import dyn_d_nand
from src.trigger_reader import INPUTS, TITLES, get_inputs, read_svg


SOLVERS = {
    1: rs_nor, 2: rs_nand, 3: onestep_rs_nand, 4: twostep_rs_nand,
    5: twostep_jk_nand, 6: syn_d_nand, 7: dyn_d_nand,
}


def solve_file(filename, trigger_type=None):
    diagram = read_svg(filename)
    if trigger_type is not None:
        diagram.trigger_type = trigger_type
    if diagram.trigger_type is None:
        raise ValueError("Не удалось определить тип по заголовку SVG. Укажите --type от 1 до 7.")
    # Проверяем входы до запуска исходного алгоритма.
    get_inputs(diagram, len(INPUTS[diagram.trigger_type]), diagram.trigger_type <= 3)
    print(f"\nФайл: {Path(filename).name}")
    print(f"Тип {diagram.trigger_type}: {TITLES[diagram.trigger_type]}")
    print(f"Тактов: {diagram.ticks}")
    SOLVERS[diagram.trigger_type](diagram=diagram)
    print()


def interactive():
    print("Расчёт триггеров по SVG. Для выхода введите 0.")
    while True:
        try:
            filename = input("\nПуть к SVG (Enter — список файлов): ").strip()
            if filename == "0":
                return 0
            if not filename:
                project_dir = Path(__file__).resolve().parent
                files = sorted(project_dir.glob("*.svg"))
                if not files:
                    files = sorted((project_dir / "examples").glob("*.svg"))
                if not files:
                    print("SVG-файлов рядом с main.py нет. Введите полный путь.")
                    continue
                for index, path in enumerate(files, 1):
                    print(f"{index}. {path.relative_to(project_dir)}")
                selected = input("Номер файла (0 — назад): ").strip()
                if selected == "0":
                    continue
                if not selected.isdigit() or not 1 <= int(selected) <= len(files):
                    print("Нет файла с таким номером.")
                    continue
                filename = str(files[int(selected) - 1])
            solve_file(filename)
        except (OSError, ValueError) as error:
            print(f"Ошибка: {error}", file=sys.stderr)
        except (EOFError, KeyboardInterrupt):
            print()
            return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", help="Пути к скачанным SVG-файлам")
    parser.add_argument("--type", type=int, choices=range(1, 8),
                        help="Тип триггера, если его нельзя определить по заголовку")
    args = parser.parse_args()
    if not args.files:
        if args.type is not None:
            parser.error("Для --type укажите путь к SVG-файлу.")
        return interactive()
    status = 0
    for filename in args.files:
        try:
            solve_file(filename, args.type)
        except (OSError, ValueError) as error:
            print(f"Ошибка в {filename}: {error}", file=sys.stderr)
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())

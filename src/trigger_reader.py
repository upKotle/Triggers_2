"""Чтение временных диаграмм WaveDrom из скачанных SVG, без зависимостей."""

from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path
import re
from urllib.parse import urlsplit
from urllib.request import url2pathname
import xml.etree.ElementTree as ET


NS = {"s": "http://www.w3.org/2000/svg"}
XLINK = "{http://www.w3.org/1999/xlink}href"
LEVELS = {
    "000": "0", "111": "1", "xxx": "X",
    "pclk": "1", "Pclk": "1", "nclk": "0", "Nclk": "0",
}
TITLES = {
    1: "Асинхронный RS триггер на элементах ИЛИ-НЕ",
    2: "Асинхронный RS триггер на элементах И-НЕ",
    3: "Синхронный одноступенчатый RS триггер на элементах И-НЕ",
    4: "Синхронный двухступенчатый RS триггер на элементах И-НЕ",
    5: "Синхронный двухступенчатый JK триггер на элементах И-НЕ",
    6: "Синхронный двухступенчатый D триггер на элементах И-НЕ",
    7: "Динамический D триггер",
}
INPUTS = {
    1: ("R", "S"), 2: ("#R", "#S"),
    3: ("CLK", "R", "S"), 4: ("CLK", "R", "S"),
    5: ("CLK", "J", "K"), 6: ("CLK", "D"), 7: ("CLK", "D"),
}


@dataclass
class Diagram:
    title: str
    trigger_type: int | None
    signals: dict[str, list[str]]
    ticks: int


def signal_to_string(signal):
    return "".join(map(str, signal))


def _normalize(text):
    # В примерах заголовок «Cинхронный» начинается с латинской C.
    return " ".join(text.lower().replace("c", "с").split()).rstrip(".")


def _translate_x(element):
    transform = element.get("transform", "").strip()
    if not transform:
        return 0.0
    match = re.fullmatch(
        r"translate\(\s*([-+\d.eE]+)(?:[\s,]+([-+\d.eE]+))?\s*\)", transform
    )
    if not match:
        raise ValueError(f"Неподдерживаемое преобразование SVG: {transform}")
    return float(match[1])


def _level(symbol):
    if symbol in LEVELS:
        return LEVELS[symbol]
    if re.fullmatch(r"[01x]m[01x]", symbol):
        return symbol[-1].upper()
    raise ValueError(f"Неподдерживаемый элемент диаграммы: #{symbol}")


def parse_svg(svg):
    """Восстановить значения в центрах пронумерованных тактов SVG WaveDrom."""
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as error:
        raise ValueError(f"Некорректный SVG: {error}") from error
    if root.tag != f"{{{NS['s']}}}svg":
        raise ValueError("Файл не является SVG.")

    titles = ["".join(t.itertext()).strip() for t in root.findall(".//s:text", NS)]
    title = next((t for t in titles if "триггер" in t.lower()), "")
    trigger_type = next(
        (n for n, expected in TITLES.items() if _normalize(title) == _normalize(expected)),
        None,
    )

    # У каждого такта два графических фрагмента по 20 единиц. Читаем
    # значения по координатам подписей 0, 1, ... вместо подсчёта <use>.
    tick_groups = []
    for group in root.findall(".//s:g", NS):
        if "muted" not in group.get("class", "").split():
            continue
        labels = group.findall("s:text", NS)
        if labels and ["".join(t.itertext()) for t in labels] == [
            str(i) for i in range(len(labels))
        ]:
            tick_groups.append([float(t.get("x")) + _translate_x(group) for t in labels])
    if len(tick_groups) != 1:
        raise ValueError("Не найдена однозначная шкала тактов 0, 1, 2, ... в SVG WaveDrom.")
    ticks = tick_groups[0]
    if any(b <= a for a, b in zip(ticks, ticks[1:])):
        raise ValueError("Координаты тактов должны возрастать.")

    signals = {}
    for lane in root.findall(".//s:g", NS):
        if not re.fullmatch(r"wavelane_\d+_\d+", lane.get("id", "")):
            continue
        label = lane.find("s:text", NS)
        if label is None:
            continue
        name = "".join(label.itertext()).strip()
        if not name:
            continue  # Пустая строка между входами и выходами.
        if name in signals:
            raise ValueError(f"Повторяющийся сигнал: {name}")
        draw = next((g for g in lane.findall("s:g", NS)
                     if g.get("id", "").startswith("wavelane_draw_")), None)
        if draw is None:
            raise ValueError(f"Не найдена диаграмма сигнала {name}.")
        offset = _translate_x(lane) + _translate_x(draw)
        pieces = []
        for use in draw.findall("s:use", NS):
            href = use.get(XLINK, use.get("href", ""))
            if not href.startswith("#"):
                raise ValueError(f"Некорректная ссылка на элемент сигнала {name}.")
            pieces.append((offset + _translate_x(use), _level(href[1:])))
        pieces.sort()
        positions = [x for x, _ in pieces]
        if any(b - a != 20 for a, b in zip(positions, positions[1:])):
            raise ValueError(f"Неподдерживаемая геометрия фрагментов сигнала {name}.")
        values = []
        for x in ticks:
            index = bisect_right(positions, x) - 1
            if index < 0 or x >= positions[index] + 20:
                break  # Q/#Q могут содержать только начальное значение.
            values.append(pieces[index][1])
        if pieces and not values:
            raise ValueError(f"Сигнал {name} не совпадает со шкалой тактов.")
        signals[name] = values
    if not signals:
        raise ValueError("В файле не найдены сигналы WaveDrom.")
    return Diagram(title, trigger_type, signals, len(ticks))


def read_svg(filename):
    filename = str(filename).strip().strip("\"'")
    if filename.startswith("file:"):
        url = urlsplit(filename)
        if url.netloc not in ("", "localhost"):
            raise ValueError("Нужен путь к локальному SVG-файлу.")
        filename = url2pathname(url.path)
    return parse_svg(Path(filename).expanduser().read_bytes())


def get_inputs(diagram, count, start_value):
    if diagram is None:
        diagram = read_svg(input("Введите путь к SVG-файлу: "))
    if diagram.trigger_type not in INPUTS:
        raise ValueError("Не удалось определить тип триггера. Укажите --type от 1 до 7.")
    names = INPUTS[diagram.trigger_type]
    if len(names) != count:
        raise ValueError("Количество входов не соответствует выбранному типу триггера.")
    values = []
    for name in names:
        # Позволяем также R/S без # при явно выбранном NAND-триггере.
        signal = diagram.signals.get(name, diagram.signals.get(name.lstrip("#")))
        if signal is None or len(signal) != diagram.ticks:
            raise ValueError(f"Для {name} нужны значения всех {diagram.ticks} тактов.")
        if any(value not in ("0", "1") for value in signal):
            raise ValueError(f"Вход {name} содержит неопределённые значения.")
        values.append(signal)
    if not start_value:
        for name in ("Q", "#Q"):
            signal = diagram.signals.get(name, [])
            if not signal or signal[0] not in ("0", "1"):
                raise ValueError(f"В SVG не задано начальное значение {name} (0 или 1).")
            values.append(signal[0])
    return tuple(values)


def get2(start_value=True, *, diagram=None):
    return get_inputs(diagram, 2, start_value)


def get3(start_value=True, *, diagram=None):
    return get_inputs(diagram, 3, start_value)

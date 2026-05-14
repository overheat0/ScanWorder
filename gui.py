import os
import re
from pathlib import Path
from typing import Optional, List

from pywebio import start_server, session, config
from pywebio.input import *
from pywebio.output import *
from pywebio.pin import *
import pandas as pd

# ======================== КОНСТАНТЫ ========================

MAX_WORD_LENGTH = 24
NOUN_POS_TAG = 's'
RUSSIAN_LETTERS_PATTERN = '[а-яё]'
DEFAULT_MASK = '-----'
BACKGROUND_IMAGE_URL = "http://pinsknews.by/wp-content/uploads/2021/05/%D0%A1%D0%BA%D0%B0%D0%BD%D0%B2%D0%BE%D1%80%D0%B4.jpg"
MAX_RESULTS_WARNING = 1000

# ======================== НАСТРОЙКИ ========================

config(description='ScanWorder', theme='dark')

# for pandas debugging
pd.set_option('display.max_rows', 2500)
pd.set_option('display.max_columns', 100)
pd.set_option('display.width', 1000)
pd.options.mode.chained_assignment = None


# ======================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ========================

def get_dictionary_path() -> Path:
    """Возвращает путь к файлу словаря"""
    return Path(__file__).parent / 'Dict.csv'


def read_from_file(csv_path: Path) -> pd.DataFrame:
    """Читает словарь из CSV файла"""
    if not csv_path.exists():
        raise FileNotFoundError(f"Файл словаря не найден: {csv_path}")

    dict_dataframe = pd.read_csv(filepath_or_buffer=csv_path, sep='\t')
    if len(dict_dataframe) == 0:
        raise ValueError("Файл словаря пуст")

    return dict_dataframe


def parse_prohibited_positions(prohibited_positions_str: str) -> dict:
    """
    Парсит строку с запрещёнными позициями
    Формат: "1:цптс;2:рми;3:абв"
    Возвращает: {0: "цптс", 1: "рми", 2: "абв"} (индексы с 0)
    """
    if not prohibited_positions_str:
        return {}

    result = {}
    parts = prohibited_positions_str.split(';')

    for part in parts:
        if ':' not in part:
            continue
        pos_str, letters = part.split(':', 1)
        try:
            position = int(pos_str) - 1  # конвертируем в 0-based индекс
            if position >= 0:
                result[position] = letters
        except ValueError:
            continue

    return result


# ======================== ОСНОВНОЙ КЛАСС (БИЗНЕС-ЛОГИКА) ========================

class WordScanner:
    """Сканер слов по маске и ограничениям"""

    def __init__(self, csv_path: Optional[Path] = None):
        if csv_path is None:
            csv_path = get_dictionary_path()
        self.dictionary_df = read_from_file(csv_path)

    def _build_regex(self, mask: str, prohibited_common: str,
                     prohibited_positions_dict: dict) -> str:
        """
        Строит регулярное выражение на основе маски и ограничений
        """
        regex_parts = ['^']

        for i, char in enumerate(mask):
            if char == '-':
                # Строим набор разрешённых символов для этой позиции
                allowed_chars = []

                # Добавляем все русские буквы
                for letter in 'абвгдеёжзийклмнопрстуфхцчшщъыьэюя':
                    allowed_chars.append(letter)

                # Убираем запрещённые общие буквы
                for prohibited in prohibited_common:
                    if prohibited in allowed_chars:
                        allowed_chars.remove(prohibited)

                # Убираем запрещённые буквы для конкретной позиции
                if i in prohibited_positions_dict:
                    for prohibited in prohibited_positions_dict[i]:
                        if prohibited in allowed_chars:
                            allowed_chars.remove(prohibited)

                # Если после удаления остались буквы
                if allowed_chars:
                    regex_parts.append(f'[{"".join(allowed_chars)}]')
                else:
                    # Если все буквы запрещены, то совпадений не будет
                    regex_parts.append('(?!)')  # negative lookahead - никогда не совпадает
            else:
                # Фиксированная буква
                escaped_char = re.escape(char)
                regex_parts.append(escaped_char)

        regex_parts.append('$')
        return ''.join(regex_parts)

    def _filter_by_required_letters(self, df: pd.DataFrame, required: str) -> pd.DataFrame:
        """
        Фильтрует DataFrame по обязательным буквам (все буквы должны присутствовать)
        """
        if not required:
            return df

        # Экранируем специальные символы regex и создаём паттерн
        escaped_letters = [re.escape(letter) for letter in required]
        # Паттерн: .*а.*б.*в.* - все буквы должны быть в любом порядке
        pattern = '.*' + '.*'.join(escaped_letters) + '.*'

        return df[df['Lemma'].str.contains(pattern, na=False, regex=True)]

    def find_by_mask(self, mask: str, required: str = '',
                     prohibited_common: str = '',
                     prohibited_positions: str = '') -> pd.DataFrame:
        """
        Находит слова по маске и ограничениям

        Args:
            mask: маска слова (- для любой буквы)
            required: обязательные буквы (все должны присутствовать)
            prohibited_common: буквы, запрещённые во всём слове
            prohibited_positions: буквы, запрещённые на конкретных позициях (формат: "1:абв;2:где")

        Returns:
            DataFrame с найденными словами
        """
        # Валидация
        if not mask:
            raise ValueError("Маска не может быть пустой")

        if len(mask) > MAX_WORD_LENGTH:
            raise ValueError(f"Маска слишком длинная. Максимум {MAX_WORD_LENGTH} символов")

        # Парсим запрещённые позиции
        prohibited_pos_dict = parse_prohibited_positions(prohibited_positions)

        # Строим регулярное выражение
        regex_pattern = self._build_regex(mask, prohibited_common, prohibited_pos_dict)

        # Фильтруем по маске
        result = self.dictionary_df[
            self.dictionary_df['Lemma'].str.match(regex_pattern, na=False)
        ]

        # Фильтруем по части речи (только существительные)
        result = result[result['PoS'] == NOUN_POS_TAG]

        # Фильтруем по обязательным буквам
        result = self._filter_by_required_letters(result, required)

        # Убираем дубликаты и сортируем по частоте
        result = result.drop_duplicates(subset='Lemma', keep='first')
        result = result.sort_values(by=['Freq(ipm)'], ascending=False)

        return result


# ======================== КЛАСС UI (ПРЕДСТАВЛЕНИЕ) ========================

class ScanworderView:
    """Управление отображением интерфейса"""

    @staticmethod
    def apply_background_style(scope_name: str):
        """Применяет фоновое изображение к scope"""
        put_scope(scope_name).style(
            f'border: 1px solid; '
            f'width: 100%; '
            f'padding: 10px; '
            f'border-radius: 10px; '
            f'margin: 0 0; '
            f'background: url("{BACKGROUND_IMAGE_URL}");'
        )

    @staticmethod
    def show_error(message: str):
        """Показывает сообщение об ошибке"""
        toast(message, color='error')

    @staticmethod
    def show_info(message: str):
        """Показывает информационное сообщение"""
        toast(message, color='info')

    @staticmethod
    def show_loading(scope_name: str):
        """Показывает индикатор загрузки"""
        with use_scope(scope_name, clear=True):
            put_loading(shape='grow', scope=scope_name)

    @staticmethod
    def show_results(words_df: pd.DataFrame):
        """Отображает результаты поиска"""
        if words_df.empty:
            ScanworderView.show_error('Ничего не найдено')
            return

        if len(words_df) > MAX_RESULTS_WARNING:
            ScanworderView.show_error(f'Найдено больше {MAX_RESULTS_WARNING} слов')
            return

        # Подготавливаем данные для таблицы
        headers = [words_df.columns.tolist()]
        table_data = words_df.values.tolist()
        table = headers + table_data

        # Отображаем результаты
        with use_scope('result', clear=True, create_scope=True):
            put_text('\n', scope='result')  # отступ

            ScanworderView.apply_background_style('tmp_res')

            put_text(
                f"Найдено слов: {len(words_df)}",
                scope='tmp_res'
            ).style('color: rgba(42, 3, 82, 1); font-size: 18px; font-weight: bold;')

            put_table(
                table,
                scope='tmp_res'
            ).style('opacity: 0.8; font-size: 25px; table-layout: fixed; width: 100%;')

    @staticmethod
    def create_main_window(mask: str, required: str,
                           prohibited_common: str,
                           prohibited_positions: str,
                           on_search_callback) -> None:
        """Создаёт главное окно с формой ввода"""
        with use_scope('main_window', clear=True):
            ScanworderView.apply_background_style('word')

            # Заголовок
            put_text(
                '|S|C|A|N|W|O|R|D|E|R|', scope='word'
            ).style(
                'color: rgba(42, 3, 82, 1); '
                'font-family: DejaVu Sans Mono, sans-serif; '
                'font-weight: bold; '
                'text-align: center; '
                'font-size: 180%'
            )

            # Поле ввода маски
            put_input(
                'word',
                type=TEXT,
                scope='word',
                value=mask,
                help_text='маска слова ("-" любая буква) (пример: -ка--о-д)'
            ).style('font-size: 150%; font-weight: bold;')

            # Поле обязательных букв
            put_input(
                'required_letters',
                type=TEXT,
                scope='word',
                value=required,
                help_text='обязательные к использованию буквы (пример: рдс)'
            ).style('font-size: 110%; font-weight: bold;')

            # Поле общих запрещённых букв
            put_input(
                'prohibited_common',
                type=TEXT,
                scope='word',
                value=prohibited_common,
                help_text='запрещенные буквы во всём слове (пример: цхптс)'
            ).style('font-size: 110%; font-weight: bold;')

            # Поле запрещённых по позициям
            put_input(
                'prohibited_positions',
                type=TEXT,
                scope='word',
                value=prohibited_positions,
                help_text='запрещенные буквы по позициям (пример: 1:цптс;2:рми)'
            ).style('font-size: 110%; font-weight: bold;')

            # Кнопка поиска и область для сообщений
            put_row(
                [
                    put_button(
                        'ПОИСК',
                        scope='word',
                        onclick=on_search_callback
                    ),
                    put_scope('word_info').style('align: right; text-align: right')
                ],
                scope='word',
                size='85% 15%'
            )


# ======================== КЛАСС КОНТРОЛЛЕР ========================

class ScanworderController:
    """Контроллер, связывающий UI и бизнес-логику"""

    def __init__(self):
        self.scanner: Optional[WordScanner] = None
        self.view = ScanworderView()
        self.mask = DEFAULT_MASK
        self.required = ''
        self.prohibited_common = ''
        self.prohibited_positions = ''

    def initialize(self):
        """Инициализация контроллера"""
        try:
            self.scanner = WordScanner()
            return True
        except Exception as e:
            self.view.show_error(f"Ошибка загрузки словаря: {e}")
            return False

    def on_search_click(self):
        """Обработчик нажатия кнопки поиска"""
        try:
            # Получаем значения из формы
            self.mask = pin.word.lower().strip()
            self.required = pin.required_letters.lower().strip()
            self.prohibited_common = pin.prohibited_common.lower().strip()
            self.prohibited_positions = pin.prohibited_positions.lower().strip()

            # Валидация
            if not self.mask:
                self.view.show_error('Не введена маска')
                return

            if len(self.mask) > MAX_WORD_LENGTH:
                self.view.show_error(f'Максимальная длина слова: {MAX_WORD_LENGTH} символов!')
                self.mask = self.mask[:MAX_WORD_LENGTH]

            # Показываем загрузку
            self.view.show_loading('word_info')

            # Выполняем поиск (исправлено: без суффиксов _)
            result_df = self.scanner.find_by_mask(
                mask=self.mask,
                required=self.required,
                prohibited_common=self.prohibited_common,
                prohibited_positions=self.prohibited_positions
            )

            # Очищаем сообщение о загрузке
            clear('word_info')

            # Отображаем результаты
            self.view.show_results(result_df)

        except ValueError as e:
            self.view.show_error(str(e))
        except Exception as e:
            self.view.show_error(f"Произошла ошибка: {e}")
            # Логирование ошибки
            import traceback
            print(traceback.format_exc())

    def run(self):
        """Запуск приложения"""
        if not self.initialize():
            return

        # Создаём главное окно с передачей callback-функции
        self.view.create_main_window(
            self.mask,
            self.required,
            self.prohibited_common,
            self.prohibited_positions,
            self.on_search_click  # передаём обработчик напрямую
        )


# ======================== ТОЧКА ВХОДА ========================

def scanworder_app():
    """Главная функция приложения"""
    # Устанавливаем окружение
    session.set_env(title='ScanWorder', output_animation=True)

    # Создаём и запускаем контроллер
    controller = ScanworderController()
    controller.run()


def run_server(port: int = 2221):
    """Запускает веб-сервер с приложением"""
    start_server(
        debug=False,
        port=port,
        cdn=False,
        applications=scanworder_app,
        remote_access=True
    )


# ======================== ЗАПУСК ========================

if __name__ == '__main__':
    run_server(2221)
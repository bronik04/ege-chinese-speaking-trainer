from __future__ import annotations

import unittest

from scripts.speaking_bank import (
    Block,
    normalize,
    parse_announcement,
    parse_blocks,
    parse_project,
    select_sources,
)

BANK_SAMPLE = """# Блок: задание 30
теги: Банк ФИПИ
## Стимул
1. media/photos/p1_t03_img2.jpg

## Задание
Ознакомьтесь с объявлением. Вы увидели объявление о курсах и решили получить дополнительную информацию.

# Блок: задание 27
теги: Банк ФИПИ

## Задание
стем: 请选择 ___ 。

# Блок: задание 31
теги: Банк ФИПИ
## Стимул
1. media/photos/p9_t08_img1.jpg
2. media/photos/p9_t08_img2.jpg
3. media/photos/p9_t08_img3.jpg

## Задание
Вы показываете семейный альбом своему другу.
"""


class ParseBlocksTest(unittest.TestCase):
    def test_keeps_only_speaking_blocks(self):
        blocks = parse_blocks(BANK_SAMPLE)

        self.assertEqual([block.number for block in blocks], [30, 31])

    def test_collects_stimulus_images_in_order(self):
        blocks = parse_blocks(BANK_SAMPLE)

        self.assertEqual(blocks[0].images, ("media/photos/p1_t03_img2.jpg",))
        self.assertEqual(
            blocks[1].images,
            ("media/photos/p9_t08_img1.jpg", "media/photos/p9_t08_img2.jpg", "media/photos/p9_t08_img3.jpg"),
        )

    def test_task_text_is_collapsed_to_one_line(self):
        blocks = parse_blocks(BANK_SAMPLE)

        self.assertEqual(blocks[1].text, "Вы показываете семейный альбом своему другу.")

    def test_block_is_hashable_and_frozen(self):
        block = Block(number=30, images=("a.jpg",), text="текст")

        with self.assertRaises(AttributeError):
            block.number = 31


ANNOUNCEMENT_ROUND = (
    "Задание 1. Ознакомьтесь с объявлением: Вы увидели рекламное объявление об интересной экскурсии "
    "и решили получить дополнительную информацию. У Вас есть 1,5 минуты на подготовку. Затем за 1,5 минуты "
    "Вам нужно задать 5 вопросов, чтобы получить следующую информацию: 精彩的旅游路线，等你来！ "
    "1) достопримечательности по маршруту; 2) стоимость билета; 3) дата экскурсии; "
    "4) количество человек в группе; 5) длительность экскурсии."
)

ANNOUNCEMENT_DOTTED = (
    "Ознакомьтесь с объявлением. 篮球班正在招生！ Вы увидели рекламное объявление о наборе ребят "
    "в баскетбольную секцию и решили получить дополнительную информацию. У Вас есть 1,5 минуты на подготовку. "
    "Затем за 1,5 минуты Вам нужно задать 5 вопросов, чтобы получить следующую информацию: "
    "1. местоположение; 2. группы для начинающих; 3. расписание; 4. наличие раздевалки; 5. наличие душа."
)

ANNOUNCEMENT_TIMING_TAIL = (
    "Ознакомьтесь с объявлением. Вы увидели объявление о курсах ботаники и решили получить дополнительную "
    "информацию. У Вас есть 1,5 минуты на подготовку. Затем Вам нужно задать 5 вопросов, чтобы получить "
    "следующую информацию: 欢迎你们加入植物学培训班 1) адрес; 2) расписание занятий; 3) стоимость занятий "
    "за месяц; 4) продолжительность одного занятия; 5) количество занятий в неделю. "
    "На каждый вопрос отводится 20 секунд."
)

ANNOUNCEMENT_WITHOUT_BANNER = (
    "Задание 1. Ознакомьтесь с объявлением: Вы увидели рекламное объявление о волейбольном клубе и решили "
    "получить дополнительную информацию. У Вас есть 1,5 минуты на подготовку. Затем за 1,5 минуты Вам нужно "
    "задать 5 вопросов, чтобы получить следующую информацию: ! 1) адрес клуба; 2) количество спортсменов "
    "в клубе; 3) плата за обучение; 4) планируемые соревнования; 5) спортивная форма."
)


class ParseAnnouncementTest(unittest.TestCase):
    def test_parses_banner_situation_and_five_questions(self):
        parsed = parse_announcement(ANNOUNCEMENT_ROUND)

        self.assertEqual(parsed.banner, "精彩的旅游路线，等你来！")
        self.assertEqual(
            parsed.situation,
            "Вы увидели рекламное объявление об интересной экскурсии и решили получить дополнительную информацию.",
        )
        self.assertEqual(parsed.questions[0], "достопримечательности по маршруту")
        self.assertEqual(parsed.questions[4], "длительность экскурсии")

    def test_accepts_dotted_numbering_and_banner_before_situation(self):
        parsed = parse_announcement(ANNOUNCEMENT_DOTTED)

        self.assertEqual(parsed.banner, "篮球班正在招生！")
        self.assertEqual(len(parsed.questions), 5)
        self.assertEqual(parsed.questions[3], "наличие раздевалки")

    def test_drops_the_per_question_timing_tail(self):
        parsed = parse_announcement(ANNOUNCEMENT_TIMING_TAIL)

        self.assertEqual(parsed.questions[4], "количество занятий в неделю")

    def test_rejects_block_without_chinese_banner(self):
        self.assertIsNone(parse_announcement(ANNOUNCEMENT_WITHOUT_BANNER))


PROJECT_SAMPLE = (
    "Вы выполняете вместе с другом проектную работу на тему «Времена года». Вы нашли фотографии для "
    "иллюстрации проекта, но по техническим причинам не можете сейчас переслать их другу. Оставьте ему "
    "голосовое сообщение: объясните свой выбор фотографий и поделитесь некоторыми идеями о проекте. "
    "Через 3 минуты будьте готовы: · объяснить выбор иллюстраций для проектной работы, кратко описав их "
    "и указав различия; · указать достоинства (1–2) двух времён года; · указать недостатки (1–2) двух "
    "времён года; · выразить Ваше мнение по теме проектной работы – какое время года Вы предпочитаете "
    "и почему. У Вас есть 3 минуты на подготовку. Говорить следует не более 3 минут (12–15 фраз). "
    "Фотография 1 Фотография 2"
)

PROJECT_WITHOUT_BULLETS = (
    "Вы выполняете вместе с другом проектную работу на тему «Досуг». Оставьте ему голосовое сообщение."
)


class ParseProjectTest(unittest.TestCase):
    def test_extracts_theme(self):
        parsed = parse_project(PROJECT_SAMPLE)

        self.assertEqual(parsed.theme, "Времена года")

    def test_lead_drops_the_ready_marker_and_gets_project_timing(self):
        parsed = parse_project(PROJECT_SAMPLE)

        self.assertTrue(parsed.lead.startswith("Вы выполняете вместе с другом проектную работу"))
        self.assertNotIn("Через 3 минуты будьте готовы", parsed.lead)
        self.assertTrue(parsed.lead.endswith("Говорите не более 3 минут (12–15 фраз)."))

    def test_keeps_four_thematic_prompts_without_the_timing_tail(self):
        parsed = parse_project(PROJECT_SAMPLE)

        self.assertEqual(len(parsed.prompts), 4)
        self.assertEqual(parsed.prompts[1], "указать достоинства (1–2) двух времён года")
        self.assertEqual(
            parsed.prompts[3],
            "выразить Ваше мнение по теме проектной работы – какое время года Вы предпочитаете и почему",
        )

    def test_rejects_block_without_bullets(self):
        self.assertIsNone(parse_project(PROJECT_WITHOUT_BULLETS))


def announcement_text(banner: str, first_question: str) -> str:
    return (
        f"Ознакомьтесь с объявлением. {banner} Вы увидели объявление о клубе и решили получить "
        "дополнительную информацию. У Вас есть 1,5 минуты на подготовку. Затем Вам нужно задать 5 вопросов, "
        f"чтобы получить следующую информацию: 1) {first_question}; 2) часы работы; 3) стоимость; "
        "4) расписание; 5) тренеры."
    )


def project_text(theme: str) -> str:
    return (
        f"Вы выполняете вместе с другом проектную работу на тему «{theme}». Оставьте ему голосовое сообщение. "
        "Через 3 минуты будьте готовы: · объяснить выбор иллюстраций; · указать достоинства (1–2); "
        "· указать недостатки (1–2); · выразить Ваше мнение по теме проектной работы."
    )


class SelectSourcesTest(unittest.TestCase):
    def setUp(self):
        self.blocks = [
            Block(30, ("a1.jpg",), announcement_text("欢迎加入足球俱乐部！", "адрес клуба")),
            Block(30, ("a2.jpg",), announcement_text("欢迎加入足球俱乐部！", "адрес клуба")),
            Block(30, ("a3.jpg",), announcement_text("新绘画班招生！", "местоположение")),
            Block(31, ("b1.jpg", "b2.jpg", "b3.jpg"), "Вы показываете семейный альбом."),
            Block(31, ("b1-копия.jpg", "b2.jpg", "b3.jpg"), "Вы показываете семейный альбом."),
            Block(31, ("b4.jpg", "b5.jpg", "b6.jpg"), "Вы показываете семейный альбом."),
            Block(32, ("c1.jpg", "c2.jpg"), project_text("Досуг")),
            Block(32, ("c3.jpg", "c4.jpg"), project_text("Досуг")),
            Block(32, ("c5.jpg", "c6.jpg"), project_text("Погода")),
        ]
        # «b1-копия.jpg» — тот же снимок, что и «b1.jpg», под другим именем
        self.photo_key = lambda image: image.replace("-копия", "")

    def test_builds_complete_variants_from_unique_blocks(self):
        sources = select_sources(self.blocks, photo_key=self.photo_key)

        self.assertEqual(len(sources), 2)
        self.assertEqual(sources[0].announcement.images, ("a1.jpg",))
        self.assertEqual(sources[0].album.images, ("b1.jpg", "b2.jpg", "b3.jpg"))
        self.assertEqual(sources[0].project.images, ("c1.jpg", "c2.jpg"))
        self.assertEqual(sources[1].announcement.images, ("a3.jpg",))

    def test_skips_album_whose_photo_set_repeats_under_other_names(self):
        sources = select_sources(self.blocks, photo_key=self.photo_key)

        self.assertEqual(sources[1].album.images, ("b4.jpg", "b5.jpg", "b6.jpg"))

    def test_respects_keys_already_used_by_the_project(self):
        sources = select_sources(
            self.blocks,
            photo_key=self.photo_key,
            used_banners=frozenset({normalize("欢迎加入足球俱乐部！")}),
            used_themes=frozenset({normalize("Досуг")}),
        )

        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].announcement.images, ("a3.jpg",))
        self.assertEqual(sources[0].project.images, ("c5.jpg", "c6.jpg"))

    def test_does_not_put_the_same_photo_twice_into_one_variant(self):
        blocks = [
            Block(30, ("shared.jpg",), announcement_text("欢迎加入足球俱乐部！", "адрес клуба")),
            Block(31, ("shared-копия.jpg", "b2.jpg", "b3.jpg"), "Вы показываете семейный альбом."),
            Block(31, ("b4.jpg", "b5.jpg", "b6.jpg"), "Вы показываете семейный альбом."),
            Block(32, ("c1.jpg", "c2.jpg"), project_text("Досуг")),
        ]

        sources = select_sources(blocks, photo_key=self.photo_key)

        self.assertEqual(sources[0].album.images, ("b4.jpg", "b5.jpg", "b6.jpg"))

    def test_skips_task_whose_photo_set_is_already_published(self):
        # Тема переформулирована, но фотографии те же — это то же задание ФИПИ.
        sources = select_sources(
            self.blocks,
            photo_key=self.photo_key,
            used_photo_sets=frozenset({("c1.jpg", "c2.jpg")}),
        )

        self.assertEqual(sources[0].project.images, ("c3.jpg", "c4.jpg"))

    def test_photo_set_check_covers_announcements_and_albums(self):
        sources = select_sources(
            self.blocks,
            photo_key=self.photo_key,
            used_photo_sets=frozenset({("a1.jpg",), ("b1.jpg", "b2.jpg", "b3.jpg")}),
        )

        self.assertEqual(sources[0].announcement.images, ("a2.jpg",))
        self.assertEqual(sources[0].album.images, ("b4.jpg", "b5.jpg", "b6.jpg"))

    def test_photo_set_check_does_not_reserve_the_text_key(self):
        # Блок сняли из-за фотографий, а не из-за текста: следующий блок с той же темой годится.
        sources = select_sources(
            self.blocks,
            photo_key=self.photo_key,
            used_photo_sets=frozenset({("c1.jpg", "c2.jpg")}),
        )

        self.assertEqual(len(sources), 2)

    def test_normalize_ignores_case_width_punctuation_and_yo(self):
        self.assertEqual(normalize("Времена  года!"), normalize("времена года"))
        self.assertEqual(normalize("欢迎！"), normalize("欢迎!"))
        self.assertEqual(normalize("Волонтёрская деятельность"), normalize("Волонтерская деятельность"))


if __name__ == "__main__":
    unittest.main()

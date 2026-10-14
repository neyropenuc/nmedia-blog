# Блог blog.nmedia.pro

SEO-блог AI-студии НЕЙРОМЕДИА. Статика, собирается из markdown, отдаётся
через GitHub Pages из ветки `main`, папка `/docs`.

## Что где

- `content/articles/<slug>.md` — статьи, markdown с front matter
- `content/covers/` — сгенерированные обложки
- `static/` — медиа, видео, шрифты, стили
- `semantics/registry.csv` — реестр тем и их статусов
- `semantics/dzen.csv` — учёт постов в Дзене
- `dzen/` — готовые промпты для публикации в Дзене
- `build.py`, `tools/` — сборка и проверки
- `docs/` — собранный сайт, его отдаёт GitHub Pages. Руками не править.

## Как опубликовать

```
python3 build.py --drafts          # черновики в preview/, посмотреть глазами
python3 tools/covers.py <slug>     # обложка для новой статьи
python3 tools/publish_gh.py --dry  # сборка и проверки, без заливки
python3 tools/publish_gh.py        # сборка, проверки, коммит, push, IndexNow
```

Ключей и секретов в репозитории нет. Публикация идёт обычным git push.

## Чего тут нет

Старый способ публикации через Yandex Object Storage (`tools/ys3.py`,
`tools/publish.py`) больше не используется.

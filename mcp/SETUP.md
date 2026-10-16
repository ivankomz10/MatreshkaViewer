# Как это подключить

Инструкция для того, кто делает генератор форм на чате GPT. Ставится один
раз, минут на пятнадцать.

Что ты получаешь: модель сможет сама посчитать, выполнима ли придуманная
форма, поправить её до выполнимой, посмотреть картинку и записать моторный
JSON, который играет площадка.

---

## 0. Что чинит

Соты на крыше поворачиваются **в зазор между кольцами**, а зазор открывает
домкрат. Выдвинуть пушеры и не поднять кольца — значит заказать наклон,
который машина не отработает. На типичном силуэте это 1000–1300 невозможных
сот из 1500.

Инструмент `kinetic_fit` берёт желаемую позу и поднимает ровно те домкраты,
которых не хватает. Силуэт при этом не меняется.

---

## 1. Поставить

Нужен Python 3.11 и видеокарта (видеокарта — только для картинок; проверка
форм, ключи, симуляция и экспорт считаются и без неё).

```bat
cd <куда распакованы исходники>\Matreshka_Viewer\tool
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pip install -r ..\mcp\requirements.txt
```

Проверить, что всё на месте:

```bat
cd ..\mcp
..\tool\.venv\Scripts\python.exe -m pytest -q
```

Должно быть `35 passed`. Если видеокарты нет — часть тестов отметится
пропущенными, это нормально.

Папку `mcp` держи внутри дерева вьюера: сервер сам находит `tool\` на уровень
выше себя.

---

## 2. Подключить MCP

Два способа, выбор зависит от того, чем ты управляешь моделью.

### 2а. Настольный клиент — Claude Desktop, Cursor, ChatGPT Desktop

Клиент сам запускает сервер и говорит с ним через трубу. В конфиг:

```json
{
  "mcpServers": {
    "matreshka": {
      "command": "C:\\<путь>\\Matreshka_Viewer\\tool\\.venv\\Scripts\\python.exe",
      "args": ["C:\\<путь>\\Matreshka_Viewer\\mcp\\server.py"]
    }
  }
}
```

Пути — свои, слэши в JSON удваиваются. Перезапусти клиент; в списке
инструментов появятся 20 штук с именами `kinetic_*` и `viewer_*`.

### 2б. Своё приложение на API OpenAI

Тут труба не подойдёт: инструмент `mcp` в Responses API ходит по URL, а не
запускает процесс. Поэтому сервер надо поднять слушающим:

```bat
..\tool\.venv\Scripts\python.exe server.py --http --port 8765
```

и дать модели адрес:

```python
response = client.responses.create(
    model="gpt-5.1",
    tools=[{
        "type": "mcp",
        "server_label": "matreshka",
        "server_url": "https://<твой адрес>/mcp",
        "require_approval": "never",
    }],
    input=[{"role": "system", "content": SYSTEM_PROMPT},
           {"role": "user", "content": "..."}],
)
```

Адрес должен быть доступен снаружи — свой домен или туннель. Если выносить
наружу не хочется, есть третий путь: подними MCP-клиент у себя в приложении
(пакет `mcp` умеет запускать сервер трубой) и отдай модели его инструменты
как обычные функции. Тогда ничего публиковать не надо.

`--host 0.0.0.0` пускает другие машины. По умолчанию слушает только свою.

---

## 3. Настроить чат

### Что положить в контекст

Два файла рядом с этой инструкцией, оба на английском и написаны для модели,
а не для человека:

- **`KINETIC.md`** — машина и её пределы: кольца, домкраты, пушеры, наклоны,
  что можно и чего нельзя, формат моторного JSON. Обязательно.
- **`VIEWER.md`** — экраны здания, камера шоу, что из контента съедают
  ламели. Нужен, если генератор делает ещё и картинку на экраны.

Клади их целиком — вместе это около 14 КБ. Пересказывать своими словами не
надо: там есть числа, которые легко переврать.

### Системный промпт

```
You generate kinetic shapes for the Zaryadye honeycomb.

Before anything else, call kinetic_machine — it returns the whole
specification as data. The attached KINETIC.md explains what the numbers mean.

Never hand back a pose you have not put through kinetic_fit. A cell tilts into
the gap beside its ring, and that gap is opened by a jack: pushing cells out
gives them no room to turn. kinetic_fit raises the jacks that are missing and
leaves the silhouette alone.

Work in this order:
  kinetic_profile    a silhouette as pusher values per ring
  kinetic_auto_tilt  cells turned to lie along that surface
  kinetic_fit        the nearest pose the machine can hold
  kinetic_render     look at it
  kinetic_new / kinetic_key / kinetic_simulate / kinetic_export

Check kinetic_simulate before exporting. The machine throws away a command
that arrives while that motor is still moving or resting, so keys butted end
to end lose every second move.

Report what kinetic_fit changed. If it had to clamp tilts, say so — that means
the shape asked for something no jack can allow.
```

### Как это работает в деле

Путь от силуэта до файла — четыре вызова:

```
kinetic_profile   points=[[0,0.05],[0.5,0.9],[1,0.1]]   -> вынос по кольцам
kinetic_auto_tilt lift=1, push=<оттуда>                 -> наклоны, до 15.7°
kinetic_fit       lift=1, push=..., tilt=...            -> подняты 20 домкратов
kinetic_render    <поза>, view="honeycomb"              -> картинка
```

Дальше `kinetic_new`, несколько `kinetic_key`, `kinetic_simulate`,
`kinetic_export`.

`kinetic_render` рисует соты и помечает **красным** то, что за пределом, —
удобно показывать модели её же ошибку. `viewer_render` рисует всё здание с
камеры шоу, той самой, с которой делаются все референсные рендеры.

---

## 4. Если что-то не так

**Клиент не видит инструментов.** Запусти сервер руками: он должен молчать и
ждать. Любая ошибка импорта вылезет сразу.

```bat
..\tool\.venv\Scripts\python.exe server.py
```

**`no baked geometry`** — папка `mcp` вынесена из дерева вьюера. Верни её
рядом с `tool`.

**Картинки не приходят, остальное работает** — нет видимой видеокарты.
Проверка форм и экспорт от этого не страдают.

**Модель всё равно выдаёт невозможные позы** — она не зовёт `kinetic_fit`.
Усиль это место в системном промпте; при желании можно вообще не отдавать ей
`kinetic_check`, оставив только `kinetic_fit`, который и проверяет, и чинит.

**Экспорт лёг не туда, куда просили.** Так и надо: экспортёр сам называет
файл `<имя>_1_of_1.json`, этого ждёт площадка. Настоящий путь — в ответе
инструмента.

---

## 5. Чего сервер не делает

Он рисует неподвижные кадры. Загрузка HAP-видео, воспроизведение, таймлайн
шоу, развёртка, инспектор и запись видео — это работа окна вьюера
(`MatreshkaViewer.exe`; редактор кинетики — его страница, ремап открывается
окном поверх). Сервер нужен, чтобы генератор видел, что делает, без окна и не
отнимая мышь у человека.

# dtek-krem-bridge

Графік відключень ДТЕК КРЕМ (Київська область) у вигляді JSON, який бот на
мініку читає напряму.

Схема: GitHub Actions раннер (його IP Imperva пропускає, на відміну від
домашніх ASN) раз на 15 хвилин ходить на `dtek-krem.com.ua/ua/shutdowns`,
робить Imperva-рукопожатие (стаб -> куки -> сторінка -> CSRF), дергає
`/ua/ajax` і комітить результат у гілку `data`.

Споживачам:

```
https://raw.githubusercontent.com/PLNB1038/dtek-krem-bridge/data/out/schedule.json
https://raw.githubusercontent.com/PLNB1038/dtek-krem-bridge/data/out/raw_api.json
```

Поле `updated_at` обов'язково звіряти: протух > 2 год -> переходити на
фолбек (alerts.org.ua тощо).

Форс-ран: `gh workflow run scrape` або POST repository_dispatch з типом
`scrape` (потрібен токен з contents:write на цей репо).

# Локальная проверка Firefox, 2026-10-18

Итоговый отчёт: [firefox-local-validation-2026-10-18.md](../../docs/research/firefox-local-validation-2026-10-18.md).

Это изолированные проверки механизмов на x86_64, не бенчмарк B8000-H.
Рабочие файлы провайдера/пакета не изменяются. Прототип событийного `b8k-calm`
существует только в тестовом коде и временном контейнере.

## Входы и выходы

- `environment.json`, `host-provenance.json`, `packages.txt`: окружение, лимиты,
  image digest и состав пакетов.
- `downloads.json`, `fixtures/manifest.json`: URL, размеры и SHA256 входных файлов.
- `runs/*.json`: первичный проход по 32 конфигурациям; один запуск на вариант.
- `focused-memory/*.json`: повторные измерения памяти/FPS и восстановления вкладки.
- `focused-cpu/*.json`: горячий цикл JavaScript и сведения о сборке/графике.
- `focused-image-stress/*.json`: принудительное декодирование картинок.
- `video/*.json`: воспроизведение синтетического 360p30 по кодекам.
- `extension-state/*.json`: реально применённые режимы uBOL, managed storage и host permissions.
- `contracts.json`, `calm-contracts.json`: результаты проверок скриптов.
- `source-audit/`: проверка деклараций флагов и потребителей prefs Firefox 151.0.3;
  наличие декларации не заменяет успешную компиляцию.
- `summary.csv`, `summary.json`: сводка, пересчитываемая `summarize.py`.
- `compression-pages.json`: отдельный userspace-пробник кодеков сжатия; не тест zram.

`calibration/`, логи и скачанные XPI исключены из Git. Они могут сохраняться в
локальном каталоге; исходные профили после каждого запуска удаляются. Тестовые
профили не содержат пользовательских аккаунтов/истории. Внешняя сеть отключена
перед измерениями; страницы обслуживаются только внутри контейнера по loopback.

## Воспроизведение

Нужен отдельный контейнер Alpine 3.24 с `firefox=151.0.3-r0`,
`geckodriver=0.36.0-r0`, `python3`, `font-dejavu`, `xvfb`, `ca-certificates`.
Экземпляр был ограничен 1 GiB RAM, без swap, двумя CPU, shm 256 MiB.
`/work` — read-only bind репозитория; `/results` — writable bind этого каталога.
Пользователь `bench` имеет отдельный `/home/bench`, Xvfb работает на `:99`.
Исходные URI профиля и HTTP страницы создаются заново каждым скриптом.

Для autoconfig в контейнере файл `/usr/lib/firefox/defaults/pref/zz-b8k-bench.js`
содержит `general.config.filename=b8k-bench.cfg`, `obscure_value=0`,
`sandbox_enabled=false`. Последнее разрешает privileged autoconfig, как в проекте;
это не отключение sandbox веб-контента. Файл `/usr/lib/firefox/b8k-bench.cfg`
и каталог `/etc/firefox/policies` доступны для записи пользователю `bench`.
Не размещать эти файлы в своей системной установке Firefox.

До отключения сети загрузить XPI по `downloads.json`, проверить SHA256;
сохранить Betterfox user.js на указанном в отчёте коммите как `betterfox.js`.
Генерация изображений и видеокорпуса выполняется на хосте (Pillow и ffmpeg):

```sh
rtk proxy python3 benchmarks/local-2026-10-18/prepare_fixtures.py
rtk proxy python3 benchmarks/local-2026-10-18/prepare_fixtures.py --videos
```

Далее внутри **отдельного** контейнера, последовательно, без параллельных браузеров:

```sh
rtk proxy docker exec --user bench --env DISPLAY=:99 --env HOME=/home/bench b8k-firefox-local-lab-20261018 python3 /results/run_matrix.py --variants all --repeats 1 --sample-seconds 1
rtk proxy docker exec --user bench --env DISPLAY=:99 --env HOME=/home/bench b8k-firefox-local-lab-20261018 python3 /results/run_focused.py --variants project,native_discard,frame_rate30 --repeats 5 --suite memory
rtk proxy docker exec --user bench --env DISPLAY=:99 --env HOME=/home/bench b8k-firefox-local-lab-20261018 python3 /results/run_focused.py --variants project,jit_off --repeats 3 --suite cpu
rtk proxy docker exec --user bench --env DISPLAY=:99 --env HOME=/home/bench b8k-firefox-local-lab-20261018 python3 /results/run_focused.py --variants project,images_cap64,images_factor8 --repeats 2 --suite image-stress
rtk proxy docker exec --user bench --env DISPLAY=:99 --env HOME=/home/bench b8k-firefox-local-lab-20261018 python3 /results/video_probe.py
rtk proxy docker exec --user bench --env DISPLAY=:99 --env HOME=/home/bench b8k-firefox-local-lab-20261018 python3 /results/extension_probe.py
rtk proxy docker exec --user bench --env HOME=/home/bench b8k-firefox-local-lab-20261018 python3 /results/check_contracts.py
rtk proxy node benchmarks/local-2026-10-18/check_calm.js
rtk proxy python3 benchmarks/local-2026-10-18/compression_probe.py
rtk proxy python3 benchmarks/local-2026-10-18/summarize.py
rtk proxy python3 benchmarks/local-2026-10-18/make_report.py
```

Доступ к chrome-контексту нужен только тестовому WebDriver; он слушает loopback
контейнера. Измеряются PSS и SwapPss дерева Firefox, без geckodriver/Xvfb/HTTP
сервера. Сумма RSS не применяется как метрика общей физической памяти.

`project` — prefs/CSS проекта плюс polling autoconfig, **без uBOL и без
mobile-config-firefox**. Это факторизованный baseline, а не полный образ планшета.
`betterfox` — наложение его user.js поверх этого baseline. В `unload_early`
порог 65536 MiB выбран исключительно для принудительного запуска механизма;
это не пользовательская рекомендация. ATD проверяется с period=1 s, number=0;
его планировщик всё равно проверяет минимум раз в 60 s, и тест ждёт 65 s.
Нет обещания, что стандартные настройки ATD выгрузят три вкладки.

Повторы memory отделены от screening: после трёх страниц и прокрутки для всех
вариантов выдерживается одинаковая пауза 7 s. У `native_discard` перед паузой
выгружаются две фоновые вкладки, после измерений проверяется восстановление первой.
Не объединять разные серии в одно статистическое наблюдение.

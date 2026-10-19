#!/usr/bin/env python3
"""Generate the final report only after collecting the main matrix and pressure screen."""
import json
from pathlib import Path
import statistics

HERE = Path(__file__).resolve().parent
summary = json.loads((HERE / 'summary.json').read_text())
rows = summary['rows']
main = [r for r in rows if not r['pressure']]
assert len(main) == 25, f'Main series incomplete: {len(main)}/25'
pressure_paths = sorted((HERE / 'results').glob('pressure-*.json'))
assert len(pressure_paths) >= 4, 'Pressure screen incomplete'
pressure = [json.loads(p.read_text()) for p in pressure_paths]
labels = {'installed': 'Установленная 1.3.0', 'baseline': 'Исправленный каталог defaults',
          'factor8': 'Исправление + кэш 8', 'factor16': 'Исправление + кэш 16',
          'fps30': 'Исправление + 30 FPS'}
balanced = {key: [r for r in main if r['variant'] == key and r['repeat'] >= 2
                 and r['boot_id'] != 'before-reboot'] for key in labels}
assert all(len(group) == 3 for group in balanced.values()), 'Balanced same-boot series incomplete'
assert len({r['boot_id'] for group in balanced.values() for r in group}) == 1
assert all(r['tabs_pending_loaded'] == 0 for group in balanced.values() for r in group)
assert all(r['tabs_pending_after_discard'] == 2 and r['restored_first'] for r in main)
audit = json.loads((HERE / 'runtime-all-defaults.json').read_text())
cleanup = json.loads((HERE / 'cleanup.json').read_text())
assert audit['status'] == 'pass' and not audit['mismatches']
assert cleanup['status'] == 'pass' and cleanup['profile_comparison']['backup_retained']


def med(group, key):
    return statistics.median(r[key] for r in group)


def value_range(group, key):
    return f'{med(group,key):.1f} ({min(r[key] for r in group):.1f}–{max(r[key] for r in group):.1f})'


table = '\n'.join(f'| {label} | 3 | {value_range(balanced[key],"loaded_pss_swap_mib")} '
                  f'| {value_range(balanced[key],"scroll_cpu_per_8s")} '
                  f'| {med(balanced[key],"raf_hz"):.1f} |' for key, label in labels.items())
base_memory = med(balanced['baseline'], 'loaded_pss_swap_mib')
deltas = {key: {'memory_mib': med(group, 'loaded_pss_swap_mib') - base_memory,
                'memory_percent': (med(group, 'loaded_pss_swap_mib') / base_memory - 1)*100,
                'cpu_percent': (med(group, 'scroll_cpu_per_8s') /
                                med(balanced['baseline'], 'scroll_cpu_per_8s') - 1)*100}
          for key, group in balanced.items()}
pressure_table = []
pressure_details = []
for d in pressure:
    if d['status'] != 'ok':
        pressure_table.append(f'| {d["variant"]} | ошибка | — | — | — |')
        pressure_details.append({'variant': d['variant'], 'status': d['status'], 'error': d.get('error')})
        continue
    p = d['pressure']
    before = sum(t['pending'] for t in p['tabs_before'])
    peak = max(sum(t['pending'] for t in s['tabs']) for s in p['samples'])
    active = sum(e['topic'] == 'user-interaction-active' for e in p.get('interaction_events', []))
    prefs = d['runtime']['prefs']
    effective_kib = max(p['threshold_mb'] * 1024,
                        p['target_available_kib'] + 8 * 1024)
    pressure_table.append(f'| {d["variant"]} | {prefs["browser.tabs.min_inactive_duration_before_unload"]//1000} с / '
                          f'{p["target_percent"]}% / {p["threshold_mb"]} МиБ | '
                          f'{"да" if p["threshold_approached"] else "нет"} | {before} → {peak} | '
                          f'{p["allocated_mib"]} МиБ |')
    pressure_details.append({'variant': d['variant'], 'status': d['status'],
        'pending_before': before, 'max_pending': peak, 'threshold_reached': p['threshold_approached'],
        'guard': p.get('guard'), 'active_notifications': active,
        'trusted_pointer': p.get('pointer_event_trusted'),
        'available_samples_mib': [round(s['memory']['available_kib']/1024, 1)
                                  for s in p['samples']],
        'samples_below_effective_threshold': sum(s['memory']['available_kib'] < effective_kib
                                                 for s in p['samples'])})
pressure_table = '\n'.join(pressure_table)
unloaded = [p['variant'] for p in pressure_details if p.get('max_pending', 0) > 0]
pressure_verdict = ('Автоматическая выгрузка зафиксирована в режимах: '
                    + ', '.join(f'`{v}`' for v in unloaded) + '.' if unloaded else
                    'Автоматическая выгрузка в этих импульсных проверках не зафиксирована.')
derived = {'balanced_groups': balanced, 'deltas_vs_corrected_baseline': deltas,
           'pressure_screen': pressure_details}
(HERE / 'balanced-summary.json').write_text(json.dumps(derived, indent=2)+'\n')
text = f'''# Проверка Firefox на B8000-H и исправление defaults

Серия начата 18 октября 2026. Выполнено **25 успешных основных прогонов**
пяти конфигураций; отдельно собран pressure-screen из {len(pressure)} запусков.
После раннего незавершённого запуска и потери Wi-Fi пользователь перезагрузил
устройство. Причины зависания не установлены; запуск не включён в успешные прогоны.

## Подтверждённый дефект установки 1.3.0

Файлы b8k находились в GRE-каталоге `/usr/lib/firefox/defaults/pref`.
Штатные application defaults загружаются позже и перекрывают часть значений.
Дополнительно обратная алфавитная загрузка файлов в GRE приводила к тому,
что `mobile-config-prefs.js` перекрывал выбор `zz-b8k-firefox.js`.

Проверены default/effective ветви настоящего Firefox при отсутствии user overrides:

| Параметр | Установленная 1.3.0 | Частная исправленная копия |
| --- | --- | --- |
| unloadOnLowMemory | false | true |
| min_inactive_duration_before_unload | 600000 мс | 60000 мс |
| general.config.filename | mobile-config-autoconfig.js | b8k-firefox.cfg |
| processPrelaunch.enabled | true | false |

`check_runtime.py` давал exit 1 для установленной копии и exit 0 после переноса
трёх файлов в `browser/defaults/preferences`. В исходниках исправлен установщик
и удаление старых файлов. Проверка установки сначала падала; после исправления
все шесть регрессионных тестов прошли на хосте и в Alpine x86_64.
После завершения нагрузочных серий отдельно проверены все {audit['checked']}
буквально заданных b8k defaults: несовпадений default-ветви нет.
Ранний x86_64 benchmark явно задавал prefs в профиле, поэтому не проверял
этот путь загрузки реальной установки.

[Runtime-сравнение](../../benchmarks/device-2026-10-18/runtime-comparison.json),
[код загрузчика Firefox 151.0.3](https://github.com/mozilla-firefox/firefox/blob/FIREFOX_151_0_3_RELEASE/modules/libpref/Preferences.cpp).

## Сопоставимое сравнение на одной загрузке

ARMv7 (`arm-eabi-gcc3`), Firefox 151.0.3-r0, mobile-config-firefox 5.4.1-r0,
995 МиБ MemTotal, 512 МиБ zram, программный WebRender, активный uBOL.
Для исправленных вариантов использована частная копия тех же ELF/библиотек;
менялось расположение prefs, но сам Firefox не пересобирался.

После перезагрузки изменилось состояние памяти ОС: например, один и тот же
режим установленного Firefox занимал около 416 МиБ до и 621 МиБ после неё.
Поэтому **смешанная медиана всех пяти повторов не используется для вывода**.
Ниже три полных круга 2–4 в одной загрузке, с чередованием порядка режимов.
Все 25 результатов сохранены; предыдущие прогоны остаются отдельным контекстом.

Память — медиана PSS + SwapPss всего дерева, диапазон в скобках. Это
логический след с учётом выгруженных страниц, а не физический размер zram.
CPU нормирован на восемь секунд по фактической длительности rAF-сценария;
ненормированные значения и длительности остаются в JSON/CSV.

| Режим | n | PSS + SwapPss, МиБ | CPU на 8 с, с | rAF, Гц |
| --- | ---: | ---: | ---: | ---: |
{table}

Относительно исправленного исходного режима:

- Кэш 8: {deltas['factor8']['memory_mib']:+.1f} МиБ / {deltas['factor8']['memory_percent']:+.1f}% памяти;
  CPU {deltas['factor8']['cpu_percent']:+.1f}%.
- Кэш 16: {deltas['factor16']['memory_mib']:+.1f} МиБ / {deltas['factor16']['memory_percent']:+.1f}% памяти;
  CPU {deltas['factor16']['cpu_percent']:+.1f}%.
- 30 FPS: {deltas['fps30']['memory_mib']:+.1f} МиБ памяти;
  CPU {deltas['fps30']['cpu_percent']:+.1f}%.

Это небольшой синтетический корпус, не статистическое доказательство для
любых сайтов. Задержка сенсорного ввода и батарея не измерялись.

## Автоматическая выгрузка под давлением памяти

Отдельные копии профиля, без явного `discardBrowser` в этом сценарии.
Возраст неактивных вкладок сбрасывался, затем выдерживалось 36 секунд.
Touched allocation в Python приближала MemAvailable к большему из двух
порогов; далее записывались состояния вкладок, после чего память отпускалась.
После первого достижения порога новая память не добавлялась: это короткий
импульс давления. Если Firefox/ОС освобождали память, низкий MemAvailable
принудительно не поддерживался. Длительную работу под давлением тест не доказывает.
Ограничители: 80 МиБ MemAvailable и минимум 30% свободного swap.
Ввод выполнялся через WebDriver; доверенность pointer event и уведомления
`user-interaction-active/inactive` записаны в результатах.

| Режим | Настройки: возраст / процент / абсолютный порог | Порог достигнут | Pending до → максимум | Внешняя аллокация |
| --- | --- | --- | ---: | ---: |
{pressure_table}

{pressure_verdict}
Отсутствие выгрузки в базовом режиме с 60 секундами не доказывает неисправность:
его фоновые вкладки ещё моложе минуты во время записанного низкого MemAvailable.
Позже доступная память возрастает, без необходимости выгружать вкладки.

Один прогон каждого режима — проверка механизма, а не подбор оптимальных
настроек. Большая часть байтов аллокации нулевая; это не модель произвольного
реального содержимого и не benchmark сжатия zram. Эффект GC/очистки кэшей при
давлении нельзя целиком приписывать выгрузке вкладок.

Firefox проверяет также абсолютный порог **200 МиБ** и реагирует при любом
из двух условий. На 995 МиБ RAM изменение 10% → 15% само по себе не повышает
эффективный порог. 25% — отдельный эксперимент с более ранним срабатыванием.
[Условие в исходниках Firefox](https://github.com/mozilla-firefox/firefox/blob/FIREFOX_151_0_3_RELEASE/xpcom/base/AvailableMemoryWatcherLinux.cpp).

## Методика и ограничения

Три локальных документа, каждый с 16 уникальными по URL JPEG 1200×900;
явное завершение `img.decode()`, одинаковое семисекундное ожидание, три
выборки памяти, восьмисекундная rAF-прокрутка и повторное ожидание.
Потом в основном сценарии явно выгружались две фоновые вкладки и проверялось
восстановление первой по правильному `?tab=0` и 16 изображениям.
Сырые состояния pending и память после выгрузки сохранены отдельно.
Все 25 запусков подтвердили две pending-вкладки и восстановление первой.
В исправленном базовом режиме медиана изменения PSS + SwapPss через семь
секунд после явной выгрузки составила {med(balanced['baseline'], 'discard_delta_mib'):+.1f} МиБ. Это небольшой
краткосрочный выигрыш в данном корпусе; прежний результат настольного стенда
здесь не воспроизведён.

JS payload здесь — 8 МиБ на страницу, в раннем x86_64 стенде — 24 МиБ и
дополнительные DOM-узлы. Поэтому прежние «минус 64 МиБ» нельзя честно
сопоставлять с этим корпусом как эффект одной архитектуры.

Установленный APK не менялся; браузерные тесты запускались с частными профилями.
Настройки swap, earlyoom,
ядра и governor не менялись. Системный sleep-скрипт поддерживает logind;
имя обёртки `b8k-sleep-loop` не означало старого механизма. До перезапуска
idle inhibitor принадлежал тестовым процессам и отпускался при их завершении.
После перезапуска добавлен независимый guard, проверяемый через ListInhibitors:
он не зависит от завершения отдельного теста.

Причина зависания старого запуска не установлена. В контроллер добавлены
сохранение stat/wchan/status при таймауте и защита записи результата от
ошибки cleanup. При повторе старый Firefox-лог перезаписался, но исключение
контроллера сохранено; последующие версии стенда используют отдельные имена логов.
Часовая пользовательская сессия, несохранённые формы, реальный звук/видео,
GPU/VPU, батарея и новая сборка Firefox/LTO/PGO не проверялись.

По завершении SHA-256 содержимого обычных файлов и цели симлинков рабочего
профиля сопоставлены с ранним архивом ({cleanup['profile_comparison']['entries']} записей).
Обнаружено отличий: **{len(cleanup['profile_comparison']['differences'])}**.
Имена и времена сохранены в cleanup.json. Времена изменённых существующих
записей предшествуют началу основной серии; полного совпадения с ранним
архивом нет, поэтому побайтовая неизменность за всю работу не заявляется.
Архив не восстанавливался: более свежая пользовательская сессия сохранена.
Частные копии
приложения, профилей и каталогов запусков удалены; исходный архив сохранён
на планшете. Тестовых Firefox и наших logind inhibitors не осталось.
[Проверка defaults](../../benchmarks/device-2026-10-18/runtime-all-defaults.json),
[проверка профиля и cleanup](../../benchmarks/device-2026-10-18/cleanup.json).

## Рекомендации

1. Сначала поставить исправление каталога defaults: без него часть настроек
   проекта не применяется. Новый релиз с исправлением этим исследованием не публиковался.
2. Для изображений начать с `--image-cache-factor 8`; вариант `16` проверить
   на привычных сайтах, особенно при возврате к изображениям и переключении вкладок.
3. 30 FPS оставить опцией, не переносить первоначальный выигрыш под другим
   состоянием памяти на все сценарии. JIT и дисковый кэш оставить включёнными.
4. Возраст 30 секунд и порог 25% не включать массово по одному pressure-прогону;
   проверить восстановление реальных вкладок и исключения для звука/форм.
5. ThinLTO/PGO — отдельный следующий этап с настоящими ARMv7 APK и контрольной
   сборкой. Текущая частная копия Firefox не является пересборкой.

## Артефакты

- [Методика](../../benchmarks/device-2026-10-18/README.md).
- [Сопоставимая выборка и дельты](../../benchmarks/device-2026-10-18/balanced-summary.json).
- [Все данные CSV](../../benchmarks/device-2026-10-18/summary.csv),
  [JSON](../../benchmarks/device-2026-10-18/summary.json),
  [отдельные прогоны](../../benchmarks/device-2026-10-18/results/).
- [Наблюдение исходной сессии](firefox-device-initial-2026-10-18.md).
'''
report = HERE.parents[1] / 'docs/research/firefox-device-validation-2026-10-18.md'
report.write_text(text)
print(json.dumps({'report': str(report), 'main_runs': len(main), 'pressure_runs': len(pressure),
                  'deltas': deltas, 'pressure': pressure_details}, indent=2))

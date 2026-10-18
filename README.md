# b8k-firefox

Firefox для сенсорного экрана и слабого железа — для планшета Lenovo YOGA
Tablet 10 (B8000-H) с оболочкой
[lenovo-b8000h-linux](https://github.com/trudenboy/lenovo-b8000h-linux), но
пригодно и без неё (поверх mobile-config-firefox).

- `userChrome.css` — крупные вкладки и кнопки панели; `userContent.css`.
- `b8k-lean.js`, `b8k-ram.js` — фоновые службы Firefox выключены, один
  процесс содержимого, светлые страницы по умолчанию.
- `b8k-firefox.cfg` + `b8k-calm.js` — autoconfig: снимает фокус с
  адресной строки нового окна, чтобы экранная клавиатура не выезжала сама.
- `b8k-policies.py` — политики mobile-config-firefox с uBlock Origin Lite
  (полный режим) и русским языковым пакетом вместо uBlock Origin.
- `b8k-firefox-profile [--shell]` — готовит профили (стили, нужные
  настройки в `user.js`); с `--shell` панели оставляют место под кнопку
  «✕» оболочки в правом верхнем углу.

Установка: пакет Alpine из выпусков GitHub (подписан ключом проекта, см.
[b8k-ci](https://github.com/trudenboy/b8k-ci)) или `sh install.sh [ROOT]
[PREFIX]`. Расширение и языковой пакет скачиваются при сборке и проверяются
по sha256; политики Firefox (`/etc/firefox/policies/policies.json`)
пишет `b8k-firefox-configure` — при установке пакета и всякий раз, как его
запускают после обновления Firefox или mobile-config-firefox.

Лицензия — GPL-2.0.

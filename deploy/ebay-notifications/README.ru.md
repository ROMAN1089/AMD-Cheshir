# Бесплатный приёмник уведомлений eBay для локального SnapSell

Это приёмник для **исследования цен через Browse API**. Он не заменяет настройку
OAuth продавца и не разрешает Production-публикации.

Cloudflare Worker отвечает на GET challenge по `/ebay/deletion`. POST сохраняется
в D1 только после шифрования AES-256-GCM; ключ сообщения шифруется RSA-OAEP/SHA256.
Приватный RSA-ключ остаётся в `private/ebay-notifications.pem` на компьютере продавца.
Ключи eBay в Cloudflare не передаются. `/pending` и `/ack` требуют отдельный Bearer token.
Повторная доставка одного подписанного сообщения не создаёт дублей.
При переполнении (2000 сообщений), сбое шифрования или D1 возвращается 503, чтобы
eBay повторил доставку. Подпись проверяется локально по исходным байтам сообщения,
через официальный Production getPublicKey и ECDSA с SHA1/SHA256 из заголовка eBay;
публичные ключи кэшируются час. Реальный тест Developer Portal использует SHA1.
Неподтверждённое уведомление не удаляет данные. Ошибка получения ключа не удаляет сообщение.

## Ограничения локального режима

ПК может быть выключен при приёме сообщения, но обработка/удаление произойдёт только
при запущенном backend. Включайте SnapSell регулярно; для постоянной работы переносите
backend на постоянно доступный сервер. Не считайте успешный challenge доказательством
выполнения всех обязательств eBay или подтверждением доступа ко всем Buy API.

При валидном запросе удаляются **все кэшированные исследования eBay**, а не только
одна строка: уведомление может содержать immutable userId, тогда как Browse отдаёт username.
Удаляются связанные снимки и отметка автоматически рассчитанной цены. Собственные
карточки и установленные продавцом цены сохраняются. Хэши полученных идентификаторов
блокируют повторный импорт известных удалённых username. Другие магазины сохраняются.
Очистка SQLite использует secure_delete и обрезку WAL. Старые экспорты, копии DATA_DIR
на других носителях и сторонние резервные копии автоматически очистить невозможно;
их нужно включить в собственный процесс удаления данных.

## Развёртывание

1. Из корня репозитория выполните `.venv/Scripts/python.exe deploy/ebay-notifications/prepare_private.py`,
   затем `.venv/Scripts/python.exe deploy/ebay-notifications/build_upload.py`.
   Первый скрипт сохраняет RSA-3072 ключ и случайные verification/poll tokens в ignored
   `private/`. Второй собирает `private/ebay-notifications-upload.zip`: только `_worker.js`
   и заглушку `index.html`, без секретов. Не меняйте ключ при наличии очереди.
2. На бесплатном Cloudflare создайте Pages Direct Upload проект `snapsell-ebay-notifications`
   и загрузите ZIP. Создайте D1 `snapsell-ebay-notifications`, выполните `schema.sql` в консоли.
   В Pages Settings добавьте D1 binding `DB`, указывающий на эту базу.
3. Не включайте платный Workers план. Отключите сохранение тел запросов в сторонних
   логах/Logpush. Для Pages Functions выберите Fail closed при исчерпании бесплатной квоты.
4. Переменные Pages Production: `PUBLIC_KEY_JWK`, `VERIFICATION_TOKEN` (32–80 допустимых символов),
   `POLL_TOKEN` (случайный секрет), `ENDPOINT_URL` (точный HTTPS URL `/ebay/deletion`).
   Poll/verification tokens храните как Cloudflare secrets. После переменных и привязки
   базы повторно загрузите ZIP: настройки применяются к новой deployment.
5. В локальном `.env`:

```dotenv
EBAY_NOTIFICATION_RELAY=https://snapsell-ebay-notifications.pages.dev
EBAY_NOTIFICATION_POLL_TOKEN=YOUR_POLL_TOKEN
```

6. В кабинете eBay Alerts & Notifications сохраните email для уведомлений о сбоях,
   `ENDPOINT_URL` и `VERIFICATION_TOKEN`. Не включайте exemption.
7. Отправьте тест eBay, проверьте локальный sync и статус ключей. После активации
   проверьте Production OAuth и Browse реальным запросом. Секреты/тела уведомлений не логируйте.

Backend проверяет очередь каждые 60 секунд и перед Browse-сбором; при ошибке
синхронизации новые данные Browse не принимаются. Состояние видно в seller-only `GET /api/ebay`.

Развёрнутый endpoint: `https://snapsell-ebay-notifications.pages.dev/ebay/deletion`.
Проверены challenge, доставка из eBay Developer Portal, расшифровка и настоящая подпись
eBay, Production OAuth и живые цены Browse. OAuth продавца (RuName/refresh token)
настраивается отдельно; `EBAY_ENABLE_PRODUCTION=false` оставлен для защиты от платных публикаций.

Документация: https://developer.ebay.com/develop/guides/sell/marketplace-user-account-deletion
Тесты: `node --test deploy/ebay-notifications/worker.test.mjs` и
`python -m pytest snapsell-backend/tests/test_ebay_notifications.py`.

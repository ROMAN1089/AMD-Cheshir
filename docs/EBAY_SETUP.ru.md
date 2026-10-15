# eBay: бесплатная настройка Sandbox

Интеграция реализована через официальные eBay OAuth, Inventory, Account,
Taxonomy и Metadata API. Ключей в комплекте нет. Пока ключи и продавец
не подключены, настоящая публикация недоступна.

## Что бесплатно

Регистрация в [eBay Developers Program](https://developer.ebay.com/signin?tab=register)
имеет бесплатный уровень доступа. [Sandbox](https://developer.ebay.com/develop/tools/sandbox)
позволяет тестировать публикации и сделки без настоящих денег. Production
может начислять обычные комиссии eBay: для этого проекта он отключён по умолчанию.
Никакой платный посредник для API не требуется.

## Получение ключей

1. Зарегистрируйтесь в Developers Program и подтвердите email. Разработческий
   аккаунт и аккаунт продавца — отдельные сущности. Дождитесь активации аккаунта,
   если eBay её запросит.
2. В разделе Application Keys создайте **Sandbox keyset**.
   `App ID (Client ID)` соответствует `EBAY_CLIENT_ID`, а `Cert ID (Client Secret)`
   — `EBAY_CLIENT_SECRET`. Dev ID этому коннектору не нужен.
3. Создайте [Sandbox test user](https://developer.ebay.com/api-docs/static/sandbox-test-users.html)
   для продавца. Не используйте реальные Production credentials для Sandbox.
4. В настройках User Tokens / OAuth Redirect URL создайте redirect configuration.
   Его **RuName**, а не URL callback, запишите в `EBAY_RUNAME`.

## Два способа авторизации

**Через приложение:** настройте в eBay HTTPS accepted URL, ведущий на
`/api/ebay/callback` вашего доступного приложения. Откройте приложение
по этому же адресу, войдите в рабочее пространство и нажмите Connect seller
account в Channels → eBay. Авторизация использует одноразовый state с
сроком 10 минут и требует той же браузерной сессии. Для публичного размещения
задайте `PUBLIC_ORIGIN`, защищённый пароль и HTTPS. Production при этом
включать не нужно.

**Для локального теста без публичного callback:** используйте OAuth User Tokens
flow в Developer Portal/API Explorer, авторизуйте Sandbox-продавца и получите
refresh token с областями доступа:

```
https://api.ebay.com/oauth/api_scope
https://api.ebay.com/oauth/api_scope/sell.inventory
https://api.ebay.com/oauth/api_scope/sell.account.readonly
```

Запишите refresh token в `EBAY_REFRESH_TOKEN` локального `.env`. API Explorer
должен использовать OAuth authorization-code flow, а не устаревший Auth'n'Auth
token. Если интерфейс портала выдаёт только access token, refresh token получают
при обмене authorization code согласно [официальной инструкции OAuth](https://developer.ebay.com/develop/guides/sell/authorization).
Не присылайте токены в чат и не коммитьте `.env`.

Минимальная конфигурация:

```dotenv
EBAY_ENVIRONMENT=sandbox
EBAY_CLIENT_ID=...
EBAY_CLIENT_SECRET=...
EBAY_RUNAME=...
EBAY_REFRESH_TOKEN=...
EBAY_ENABLE_PRODUCTION=false
```

Токены, полученные через OAuth или обновление, сохраняются зашифрованными
в `DATA_DIR/.ebay-sandbox.token`. Ключ шифрования выводится из `.session-secret`.
Оба файла являются приватными; резервная копия всего DATA_DIR содержит и ключ.
Disconnect отключает локальную авторизацию, но не удаляет объявления на eBay.
Если токен задан через `.env`, удалите его там для отключения.

## Перед первой публикацией

1. Подключите продавца к business policies в Sandbox и создайте fulfillment,
   payment и return policies. Коннектор загружает существующие политики аккаунта,
   но не создаёт их за продавца. На первом этапе используйте политику фиксированной
   доставки: calculated shipping может требовать дополнительные вес и размеры,
   для которых отдельного редактора в этой версии нет.
2. Создайте inventory location через eBay Inventory API / API Explorer.
   Его merchantLocationKey понадобится форме. Обязательные поля адреса — страна
   и индекс, либо страна, город и регион; укажите фактическое местоположение товара.
   Коннектор загружает существующие locations.
3. Добавьте товар и подтвердите факты. Выберите положительную цену или получите
   поддержанную рекомендацию по реальным источникам.
4. В Channels выберите товар и eBay, загрузите политики и locations, сохраните defaults.
5. Введите конечную (leaf) eBay US category ID и загрузите требования категории.
   Выберите подходящее состояние и заполните обязательные характеристики.
   Коннектор не угадывает категорию или состояние по одной фотографии.
6. Для Sandbox укажите публичный HTTPS URL настоящей фотографии товара.
   `localhost`, локальный файл и приватный черновой `/media/` недоступны eBay.
   EPS-загрузка через Media API используется для локального фото в Production;
   официальный Media API перечисляет Production endpoints. Никакого автоматического
   переключения на Production из Sandbox нет.
7. Нажмите Publish on eBay sandbox и подтвердите действие.

Объявление считается активным после проверки getOffer. Ошибка eBay отображается
в интерфейсе. При таймауте сначала нажмите Check status: eBay мог уже опубликовать
объявление. Коннектор хранит offerId и восстанавливает offer по SKU для защиты от дублей.

## Управление объявлениями

- Check status получает состояние eBay, блокировку и проданное количество.
- Фоновая проверка выполняется каждые две минуты, когда backend запущен через app.py.
- Update on eBay передаёт локальные проверенные заголовок, описание и цену.
  Изменение модели, характеристик, состояния или фотографии требует повторной
  проверки eBay category/condition/aspects/photos в форме. Внешние поля,
  quantity, shipping, regulatory и дополнительные policy fields сохраняются.
- Изменение локальной карточки само по себе не меняет eBay: появляется отметка
  update needed. Для ручных площадок изменения нужно перенести самостоятельно.
- Withdraw on eBay вызывает withdrawOffer и проверяет подтверждённое состояние.
- Продажа на другой площадке ставит eBay-копию в очередь needs_removal; фоновая
  проверка снимает её через API. Ошибка остаётся видимой и повторяется при следующей
  проверке. Facebook и Craigslist остаются ручными.
- soldQuantity переводит товар в sale_pending и блокирует повторную продажу,
  но не создаёт финансовую выручку. После проверки оплаты запишите действительную
  сумму, комиссии и стоимость в Results.
- Существующее Inventory API объявление можно подключить по SKU после подтверждения,
  что это тот же физический товар. Произвольная URL-ссылка сама по себе не даёт
  API-контроля. Старые обычные объявления требуют отдельной миграции в Inventory API.

## Границы этой версии

Поддерживаются одиночные товары, FIXED_PRICE и EBAY_US. Нет аукционов,
многовариантных объявлений, количества больше одного, редактора grading condition
descriptors, импорта платежей/заказов/комиссий, сообщений и автоматической миграции
Trading API listings. Новые compliance требования категорий могут потребовать
дополнительных полей: ошибки eBay не подменяются статусом успешной публикации.

## Проверки

Изолированные тесты не используют реальные AMD/eBay credentials и не публикуют товары.
Они проверяют OAuth state/refresh, шифрование, дубль/таймаут, сохранение внешних полей,
снятие, обнаружение продаж, связывание SKU и ограничения Production.
Без Sandbox keys и seller authorization живой round-trip не проверен.

Официальные источники:

- [Поля для публикации](https://developer.ebay.com/api-docs/sell/static/inventory/publishing-offers.html)
- [Управление объявлениями](https://developer.ebay.com/develop/guides/sell/listing-management)
- [Управление offers](https://developer.ebay.com/api-docs/sell/static/inventory/managing-offers.html)
- [Media API](https://developer.ebay.com/api-docs/commerce/media/static/overview.html)

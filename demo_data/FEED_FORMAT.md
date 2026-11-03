# Структура демо-YML-фидов

Фиды лежат в `static/demo\_feeds/` (`citilink.yml`, `dns.yml`, `2droida.yml`). Формат — YML
(Яндекс.Маркет), кодировка UTF-8. В колонке «Куда пойдёт» указано, куда поле попадёт при
импорте (неделя 2) по моделям из `catalog/models.py`.

## Общий каркас

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE yml\_catalog SYSTEM "shops.dtd">
<yml\_catalog date="2026-10-29 12:00">      <!-- дата формирования фида -->
  <shop>
    <name>…</name> <company>…</company> <url>…</url>
    <currencies><currency id="RUR" rate="1"/></currencies>
    <categories> <category id=".." \[parentId=".."]>…</category> … </categories>
    <offers> <offer id=".." available="true|false" \[type="vendor.model"]> … </offer> … </offers>
  </shop>
</yml\_catalog>
```

## Блок `<shop>`

|Тег|Пример|Назначение|
|-|-|-|
|`name`|`DNS`|название магазина (в импорте не используется, магазин определяется записью `Shop`)|
|`company`|`DNS`|название компании|
|`url`|`https://www.dns-shop.ru`|сайт магазина|
|`currencies/currency`|`id="RUR" rate="1"`|только рубли; предложения в другой валюте импорт пропускает|
|`categories/category`|`id="101" parentId="100"`|категории магазина: `id` — свой в каждом фиде, `parentId` — родитель; текст — название|
|`offers/offer`|см. ниже|предложения|

Категории (`Электроника` → `Смартфоны`, `Ноутбуки`, `Планшеты`, `Наушники`) одинаковые по
названию, но с разными `id`: Ситилинк 1/11–14, DNS 100/101–104, 2DROIDA 5000/5001–5004.
Сопоставление с нашими `Category` — в `Shop.category\_map` (`id` фида → slug).

## Блок `<offer>`

Атрибуты:

|Атрибут|Значения|Куда пойдёт|
|-|-|-|
|`id`|`CL1001`, `DN1001`, `DR1001` (префикс магазина + номер)|`Offer.external\_id`, уникален внутри фида|
|`available`|`true` / `false`|`Offer.in\_stock`|
|`type`|`vendor.model` (есть у Ситилинка и 2DROIDA, у DNS нет)|определяет, как собрать название|

Теги:

|Тег|Пример|Обязателен|Куда пойдёт|
|-|-|-|-|
|`url`|`https://2droida.ru/catalog/smartfony/`|да|`Offer.url` (в демо — страница поиска или раздела, не карточка)|
|`price`|`64990`|да, число > 0|`Offer.price`|
|`oldprice`|`69990`|нет|`Offer.old\_price`|
|`currencyId`|`RUR`|да|проверка валюты|
|`categoryId`|`101`|да, должна быть в `<categories>`|через `category\_map` → `Product.category`|
|`typePrefix`|`Смартфон`|только `vendor.model`|часть `Offer.title\_raw`|
|`vendor`|`Samsung`|да|`Product.brand` (по `Brand.normalized\_name`)|
|`model`|`Galaxy S24 8/256GB`|только `vendor.model`|`Product.model`, основа `match\_key`|
|`name`|`Смартфон Samsung Galaxy S24 8/256GB (SM-S921B)`|только у DNS (вместо `typePrefix`+`model`)|`Offer.title\_raw`; модель выделяется из названия|
|`vendorCode`|`SM-S921B`|нет (есть у моделей Samsung, Sony, Lenovo)|`Product.mpn`|
|`manufacturer\_warranty`|`true`|нет|признак гарантии производителя|
|`warranty-days`|`P1Y` (период ISO 8601)|нет|`Offer.warranty\_months` (`P1Y` → 12)|
|`weight`|`0.450`|нет (у DNS нет для ноутбуков)|`Offer.weight\_g` (кг → граммы, 450); если нет — запасной вес по категории|
|`param name=".." \[unit=".."]`|`<param name="Диагональ экрана" unit="дюйм">6.2</param>`|нет|`Offer.params` и `Product.attributes`|

Названия для `vendor.model` собираются как `typePrefix vendor model`, например
`Смартфон Samsung Galaxy S24 8/256GB`.

Параметры в фидах: «Диагональ экрана» (дюйм), «Оперативная память» (ГБ), «Встроенная
память» (ГБ), «Процессор», «Тип», «Шумоподавление», «Подключение» — набор зависит от
категории. Тегов `barcode` (GTIN), `picture` и `description` в демо-фидах нет.

## Пример: Ситилинк / 2DROIDA (`vendor.model`)

```xml
<offer id="DR1004" available="true" type="vendor.model">
  <url>https://2droida.ru/catalog/smartfony/</url>
  <price>70490</price>
  <currencyId>RUR</currencyId>
  <categoryId>5001</categoryId>
  <typePrefix>Смартфон</typePrefix>
  <vendor>Apple</vendor>
  <model>iPhone 15 128GB</model>
  <manufacturer\_warranty>true</manufacturer\_warranty>
  <warranty-days>P1Y</warranty-days>
  <weight>0.400</weight>
  <param name="Диагональ экрана" unit="дюйм">6.1</param>
  <param name="Встроенная память" unit="ГБ">128</param>
</offer>
```

## Пример: DNS (простой формат с `<name>`)

```xml
<offer id="DN1001" available="true">
  <url>https://www.dns-shop.ru/search/?q=Samsung%20Galaxy%20S24%208/256GB</url>
  <price>62890</price>
  <oldprice>67890</oldprice>
  <currencyId>RUR</currencyId>
  <categoryId>101</categoryId>
  <name>Смартфон Samsung Galaxy S24 8/256GB (SM-S921B)</name>
  <vendor>Samsung</vendor>
  <vendorCode>SM-S921B</vendorCode>
  <manufacturer\_warranty>true</manufacturer\_warranty>
  <warranty-days>P1Y</warranty-days>
  <weight>0.450</weight>
  <param name="Диагональ экрана" unit="дюйм">6.2</param>
  <param name="Оперативная память" unit="ГБ">8</param>
  <param name="Встроенная память" unit="ГБ">256</param>
</offer>
```

## Содержимое фидов

|Фид|Формат|Категорий|Предложений корректных / битых|Нет в наличии|С `oldprice`|
|-|-|-|-|-|-|
|`citilink.yml`|`vendor.model`|5|16 / 0|0|4|
|`dns.yml`|`<name>`|5|16 / 2|3|6|
|`2droida.yml`|`vendor.model`|5|17 / 1|3|5|

Битые записи (`id` содержит `-ERR-`), на них проверяется пропуск ошибочных строк:

|`id`|Фид|Что не так|
|-|-|-|
|`DN-ERR-1`|DNS|нет тега `price`|
|`DN-ERR-2`|DNS|`categoryId=999999`, такой категории нет в фиде|
|`DR-ERR-1`|2DROIDA|`price` = `abc`, не число|

## Ассортимент (18 моделей)

Смартфоны: Samsung Galaxy S24, S24+, A55 5G; Apple iPhone 15, 15 Pro; Xiaomi Redmi Note 13 Pro,
14T; Honor 200. Ноутбуки: Apple MacBook Air 13 M2, 15 M2; Lenovo IdeaPad Slim 3 15IAH8.
Планшеты: Apple iPad 10.9, Samsung Galaxy Tab A9+, Xiaomi Pad 6. Наушники: Apple AirPods Pro 2,
Sony WH-1000XM5, JBL Tune 520BT, Samsung Galaxy Buds2 Pro.

В трёх магазинах есть 14 моделей. Honor 200 — в DNS и 2DROIDA, MacBook Air 15 — в Ситилинке
и 2DROIDA, Xiaomi Pad 6 — в Ситилинке и DNS, Galaxy Buds2 Pro — только в 2DROIDA.

Цены, наличие и вес в фидах тестовые, см. `SOURCES.md`.


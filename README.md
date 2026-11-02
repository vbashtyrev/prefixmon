# Prefixmon

Запись монитора Zabbix для префиксов NetBox. Скрипт читает REST API NetBox, суммирует сети по региону сайта и считает свободные адреса. Шаблон Zabbix поднимает предупреждение при малом остатке.

Учёт доступных адресов как в NetBox: для IPv4 без pool — минус сетевой и broadcast; для /31 — оба адреса (RFC 3021, раздел 2); для /32 — один; для pool — все адреса. Занято — число созданных IP-адресов в этой же VRF. Вложенные сети и диапазоны в занятость не входят. Процент в Zabbix — свободно от доступных, на сервере хранится целая часть.

## Требования

- Рабочий NetBox `netbox.example` — обычная установка 4.4.8. Страница плагина там не включена.
- Zabbix 7.0. Шаблон в репозитории записан так, как он сейчас работает на сервере.

## Файлы

| Файл | Назначение |
|------|------------|
| `zabbix/prefixmon_lld.py` | External check: `prefixes` или `locations` |
| `zabbix/zbx_export_templates.json` | Шаблон **NetBox** (экспорт Zabbix 7.0 с рабочего сервера) |

## Скрипт

Внешняя проверка — это запуск скрипта самим сервером Zabbix. Скрипт выбирает только:

- IPv4 (`family=4`);
- тег `cloud-subnet`;
- статус `active` — рабочая сеть, не контейнер, не reserved и не deprecated;
- VRF с id `2` (`internet` на этом NetBox).

Эти четыре условия записаны в скрипте.

Площадка — регион сайта (`dcim.site` → поле region). Несколько сайтов одного региона складываются. Берётся имя региона, если оно пустое — подпись региона, иначе площадка называется `UNKNOWN`. Имя сайта в площадку не подставляется.

Занятыми считаются только созданные в NetBox IP-адреса этой VRF. Фильтр `parent` сам по себе VRF не учитывает, поэтому скрипт добавляет `vrf_id`. Вложенные сети и диапазоны адресов в этот показатель не входят. Шаблон использует LLD (автоматическое обнаружение объектов) по регионам. Счётчики сетей запрашиваются параллельно, до 8 сразу, по одному соединению на поток.

### Установка на Zabbix-сервер

Скрипт на сервере не правят на месте. Сначала изменение попадает в git, на сервер его копируют отдельным шагом.

```bash
install -m 0755 zabbix/prefixmon_lld.py /usr/lib/zabbix/externalscripts/prefixmon_lld.py
printf '%s\n' 'YOUR_NETBOX_API_TOKEN' > /usr/lib/zabbix/externalscripts/.netbox.token
chown zabbix:zabbix /usr/lib/zabbix/externalscripts/.netbox.token
chmod 600 /usr/lib/zabbix/externalscripts/.netbox.token
```

Нужен Python 3 и пакет `requests` в окружении, из которого `zabbix_server` запускает external scripts.

Токен читается так (по приоритету):

1. переменная окружения `NETBOX_TOKEN` у процесса `zabbix_server`
2. файл `/usr/lib/zabbix/externalscripts/.netbox.token`

URL NetBox по умолчанию — `https://netbox.example`, его можно переопределить переменной `NETBOX_URL`.

Пользователю NetBox, которому принадлежит токен, нужны права только на чтение:

- `IPAM → Prefix → View`;
- `IPAM → IP address → View`;
- `DCIM → Site → View` — регион читается отдельным запросом сайта.

Токен с включённой записью не требуется. Сам токен в репозиторий не добавляется.

Если NetBox недоступен, токен просрочен или не хватает прав, скрипт завершается с ошибкой. Он не подменяет занятость нулём.

Проверка вручную:

```bash
sudo -u zabbix /usr/lib/zabbix/externalscripts/prefixmon_lld.py locations
```

Ожидаемый JSON:

```json
{
  "data": [
    {
      "location": "Region A",
      "total": 2540,
      "used": 120,
      "free": 2420,
      "free_percent": 95.28
    }
  ]
}
```

Режим `prefixes` в шаблоне не используется: шаблон вызывает только `prefixmon_lld.py[locations]`. В режиме `prefixes` у каждой сети тоже указан регион сайта.

### Импорт шаблона

1. **Data collection → Templates → Import** → `zabbix/zbx_export_templates.json`.
2. Привяжите шаблон **NetBox** к хосту, на котором крутится Zabbix server (external check выполняется локально).
3. У хоста должен быть разрешён тип **External check**.

Что внутри шаблона:

| Объект | Ключ | Интервал |
|--------|------|----------|
| Master item | `prefixmon_lld.py[locations]` | 1h, timeout 120 секунд |
| Dependent LLD | `prefixmon_lld` | от master item |
| Item prototypes | `netbox.location.free[{#LOCATION}]`, `free_percent`, `total`, `used` | dependent |
| Trigger | `IPv4 free space low ({#LOCATION})` | за 1h число свободных &lt; 50 **и** последнее значение процента &lt; 10, severity INFO |
| Процент | `netbox.location.free_percent[{#LOCATION}]` | целое число; на сервере лежит целая часть |
| Graph | `Free IPs location {#LOCATION}` | `free_percent` |

LLD-макросы: `{#LOCATION}`, `{#TOTAL}`, `{#USED}`, `{#FREE}`, `{#FREE_PERCENT}`.

## Структура

```
zabbix/
├── prefixmon_lld.py               # external script для Zabbix
└── zbx_export_templates.json      # шаблон NetBox (Zabbix 7.0)
```

## Лицензия

Можно распространять под той же лицензией, что и используемый вами NetBox (например, Apache 2.0), если не указано иное в репозитории.

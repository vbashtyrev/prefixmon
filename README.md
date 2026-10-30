# Prefixmon

NetBox-плагин для мониторинга префиксов: отображение подсетей по тегу и VRF, расчёт свободных адресов и утилизации. Для Zabbix в репозитории есть шаблон и external script с тем же расчётом.

## Возможности

- **Страница Cloud Subnets** — таблица префиксов со статусом active, по одной строке на сеть. Колонка Regions — регион сайта в NetBox, не имя сайта. Дальше: всего адресов, свободно, Utilization (прогресс-бар). Подсветка строк при «мало свободных» адресах (порог настраивается и относится только к странице).
- **Настройки в UI** — tag slug, VRF name, address family (IPv4/IPv6), порог «мало свободных»; выбор тега и VRF из существующих в NetBox.
- **Zabbix** — шаблон `NetBox` (Zabbix 7.0) и внешний скрипт `prefixmon_lld.py`. Скрипт суммирует сети по региону сайта, считает свободные IP-адреса и создаёт предупреждение при малом остатке. Порог страницы и порог триггера разные: страница смотрит настройку «мало свободных», триггер — меньше 50 свободных за час и последнее значение процента меньше 10. Процент в Zabbix хранится целым числом.

Учёт доступных адресов как в NetBox: для IPv4 без pool — минус сетевой и broadcast; для /31 — оба адреса (RFC 3021, раздел 2); для /32 — один; для pool — все адреса. Занято — число созданных IP-адресов в этой же VRF. Вложенные сети и диапазоны в занятость не входят. Процент на странице — занято от доступных. Процент в Zabbix — свободно от доступных.

## Требования

- NetBox 4.4+ для страницы плагина. Рецепт ниже проверен с NetBox 4.4.5 и netbox-docker 3.4.1.
- Рабочий NetBox `netbox.example` — обычная установка 4.4.8. Плагин на нём не включён. Монитор на этом сервере — скрипт Zabbix.
- Zabbix 7.0. Шаблон в репозитории записан так, как он сейчас работает на сервере.
- Установка страницы плагина — через [netbox-docker](https://github.com/netbox-community/netbox-docker) с кастомным образом (см. [Using Netbox Plugins](https://github.com/netbox-community/netbox-docker/wiki/Using-Netbox-Plugins)). Это не описание рабочего NetBox.

## Установка в netbox-docker

1. Клонируйте netbox-docker и перейдите в каталог:
   ```bash
   git clone -b release https://github.com/netbox-community/netbox-docker.git
   cd netbox-docker
   ```

2. Скопируйте плагин в репозиторий:
   - Папку `plugins/prefixmon/` — целиком (со структурой `src/prefixmon/`, шаблонами, миграциями).
   - Либо клонируйте этот репозиторий и скопируйте только `plugins/prefixmon/` в корень netbox-docker.

3. В корне netbox-docker создайте/обновите файлы.

   **plugin_requirements.txt**
   ```
   -e /opt/netbox/plugins/prefixmon
   ```

   **Dockerfile-Plugins**
   ```dockerfile
   FROM netboxcommunity/netbox:v4.4-3.4.1

   COPY ./plugin_requirements.txt /opt/netbox/
   COPY ./plugins/ /opt/netbox/plugins/
   RUN /usr/local/bin/uv pip install -r /opt/netbox/plugin_requirements.txt
   ```

   **docker-compose.override.yml** (минимально)
   ```yaml
   services:
     netbox:
       image: netbox:latest-plugins
       pull_policy: never
       ports:
         - 8000:8080
       build:
         context: .
         dockerfile: Dockerfile-Plugins
     netbox-worker:
       image: netbox:latest-plugins
       pull_policy: never
   ```

4. Включите плагин в конфигурации NetBox.  
   В `configuration/plugins.py`:
   ```python
   PLUGINS = ["prefixmon"]

   PLUGINS_CONFIG = {}
   ```
   При необходимости дефолты можно задать так:
   ```python
   PLUGINS_CONFIG = {
       "prefixmon": {
           "tag_slug": "cloud-subnet",
           "vrf_name": "internet",
           "address_family": 4,
           "low_free_threshold": 10,
       }
   }
   ```

5. Соберите образ и запустите:
   ```bash
   docker compose build --no-cache
   docker compose up -d
   ```

6. После первого входа откройте настройки плагина и выберите Tag и VRF:
   - **http://&lt;host&gt;:8000/plugins/prefixmon/settings/**

## URL плагина

| Страница / эндпоинт | URL |
|--------------------|-----|
| Cloud Subnets      | `/plugins/prefixmon/cloud-subnets/` |
| Settings           | `/plugins/prefixmon/settings/` (только superuser) |
| Discovery (JSON)   | `/plugins/prefixmon/cloud-subnets/discovery/` |
| Details (JSON)     | `/plugins/prefixmon/cloud-subnets/details/?prefix=10.0.1.0/24` |

Если пункты плагина не видны в боковом меню NetBox, используйте прямые ссылки и добавьте их в закладки.

## Интеграция с Zabbix

Рабочая схема — **внешняя проверка на сервере Zabbix**, а не запрос к страницам плагина.

Внешняя проверка — это запуск скрипта самим сервером Zabbix. Скрипт читает REST API (программный интерфейс NetBox) и выбирает только:

- IPv4 (`family=4`);
- тег `cloud-subnet`;
- статус `active` — рабочая сеть, не контейнер, не reserved и не deprecated;
- VRF с id `2` (`internet` на этом NetBox).

Эти четыре условия записаны в скрипте. Настройки страницы плагина их не меняют.

Площадка — регион сайта (`dcim.site` → поле region). Несколько сайтов одного региона складываются. Берётся имя региона, если оно пустое — подпись региона, иначе площадка называется `UNKNOWN`. Имя сайта в площадку не подставляется.

Занятыми считаются только созданные в NetBox IP-адреса этой VRF. Фильтр `parent` сам по себе VRF не учитывает, поэтому скрипт добавляет `vrf_id`. Вложенные сети и диапазоны адресов в этот показатель не входят. Шаблон использует LLD (автоматическое обнаружение объектов) по регионам. Счётчики сетей запрашиваются параллельно, до 8 сразу, по одному соединению на поток.

Файлы в репозитории:

| Файл | Назначение |
|------|------------|
| `zabbix/prefixmon_lld.py` | External check: `prefixes` или `locations` |
| `zabbix/zbx_export_templates.json` | Шаблон **NetBox** (экспорт Zabbix 7.0 с рабочего сервера) |

### Установка скрипта на Zabbix-сервер

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

Страница плагина считает доступные и занятые адреса так же, но строка остаётся одной сетью. Её порог «мало свободных» берётся из настроек плагина и на триггер Zabbix не влияет. JSON плагина Zabbix не вызывает. В этом JSON есть `{#REGION}` с тем же регионом, `{#SCOPE}` с объектом scope и `{#LOW_FREE}` по порогу страницы. Шаблон Zabbix поле `{#LOW_FREE}` не читает.

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

### JSON-эндпоинты плагина (не используются этим шаблоном)

Плагин по-прежнему отдаёт JSON на `/plugins/prefixmon/cloud-subnets/discovery/` и `details/?prefix=...`. Текущий шаблон Zabbix их не вызывает.

## Структура

```
plugins/prefixmon/                 # NetBox-плагин
├── pyproject.toml
└── src/prefixmon/
    ├── plugin.py
    ├── models.py
    ├── views.py
    └── ...
zabbix/
├── prefixmon_lld.py               # external script для Zabbix
└── zbx_export_templates.json      # шаблон NetBox (Zabbix 7.0)
```

## Лицензия

Можно распространять под той же лицензией, что и используемый вами NetBox (например, Apache 2.0), если не указано иное в репозитории.

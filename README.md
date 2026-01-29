# Prefixmon

NetBox-плагин для мониторинга префиксов: отображение подсетей по тегу и VRF, расчёт свободных адресов и утилизации, эндпоинты в формате Zabbix LLD.

## Возможности

- **Страница Cloud Subnets** — таблица префиксов с колонками: Prefix, Regions, всего адресов, свободно, Utilization (прогресс-бар). Подсветка строк при «мало свободных» адресов (порог настраивается).
- **Настройки в UI** — tag slug, VRF name, address family (IPv4/IPv6), порог «мало свободных»; выбор тега и VRF из существующих в NetBox.
- **Эндпоинты для Zabbix:**
  - **Discovery** — JSON со списком всех подходящих префиксов (LLD).
  - **Details** — JSON по одному префиксу (`?prefix=10.0.1.0/24`).

Учёт доступных адресов как в NetBox: для IPv4 без pool — минус сетевой и broadcast; для /31 — оба адреса (RFC 3021); для /32 — один.

## Требования

- NetBox 4.4+ (проверено с NetBox 4.4.5, netbox-docker 3.4.1)
- Установка через [netbox-docker](https://github.com/netbox-community/netbox-docker) с кастомным образом (см. [Using Netbox Plugins](https://github.com/netbox-community/netbox-docker/wiki/Using-Netbox-Plugins))

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
| Discovery (Zabbix) | `/plugins/prefixmon/cloud-subnets/discovery/` |
| Details (Zabbix)   | `/plugins/prefixmon/cloud-subnets/details/?prefix=10.0.1.0/24` |

Если пункты плагина не видны в боковом меню NetBox, используйте прямые ссылки и добавьте их в закладки.

## Интеграция с Zabbix

### Discovery (LLD)

- **Тип:** HTTP-агент или скрипт, возвращающий JSON.
- **URL:** `http://<netbox>:8000/plugins/prefixmon/cloud-subnets/discovery/`
- **Аутентификация:** нужна авторизация NetBox (логин/пароль или токен в заголовке, в зависимости от настроек).

Пример ответа:
```json
{
  "data": [
    {
      "{#PREFIX}": "10.0.1.0/24",
      "{#VRF}": "internet",
      "{#SCOPE}": "Region A",
      "{#TOTAL}": 254,
      "{#USED}": 10,
      "{#FREE}": 244,
      "{#UTIL}": 3.9,
      "{#LOW_FREE}": 0
    }
  ]
}
```

- **{#PREFIX}** — префикс (CIDR).
- **{#TOTAL}** — доступное количество адресов (с учётом /24 → 254 и т.д.).
- **{#FREE}** — свободные адреса.
- **{#UTIL}** — утилизация, %.
- **{#LOW_FREE}** — 1, если свободных адресов ≤ порога из настроек плагина.

### Элементы данных Zabbix (примеры)

- Свободные адреса по префиксу:  
  Ключ типа `prefixmon.free[{#PREFIX}]`, значение — поле `{#FREE}` из LLD (или запрос к Details по `{#PREFIX}`).
- Утилизация:  
  Ключ типа `prefixmon.util[{#PREFIX}]`, значение — `{#UTIL}`.
- Триггер «мало свободных»:  
  Условие по `{#LOW_FREE} = 1` или по `prefixmon.free[{#PREFIX}]` ≤ порогу.

### Details по одному префиксу

Для одного префикса тот же формат, но один элемент в `data`:

- **URL:** `http://<netbox>:8000/plugins/prefixmon/cloud-subnets/details/?prefix=10.0.1.0/24`  
  Поддерживается и параметр `free` (алиас): `?free=10.0.1.0/24`.

Если префикс не найден или не попадает под фильтры (тег, VRF, address family), в ответе будет `{"data": []}`.

## Структура плагина

```
plugins/prefixmon/
├── pyproject.toml
└── src/prefixmon/
    ├── __init__.py
    ├── plugin.py          # PluginConfig
    ├── models.py          # PluginSettings (singleton)
    ├── forms.py           # форма настроек (tag, VRF из списков)
    ├── views.py           # Cloud Subnets, Settings, Discovery, Details
    ├── urls.py
    ├── navigation.py      # menu, menu_items
    ├── migrations/
    └── templates/prefixmon/
        ├── cloud_subnets.html
        └── settings.html
```

## Лицензия

Можно распространять под той же лицензией, что и используемый вами NetBox (например, Apache 2.0), если не указано иное в репозитории.

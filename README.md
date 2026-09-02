# Hue Ambilight

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)

Кастомная интеграция для **Home Assistant**, которая синхронизирует цвет подсветки **Philips Ambilight** (с Philips Google TV) на любые лампочки в вашем умном доме.

## Как это работает

```
Philips TV → /ambilight/processed → Усреднение цветов → light.turn_on (ваши лампочки)
```

1. Каждые N мс (по умолчанию 500 мс) интеграция опрашивает телевизор
2. Получает RGB-цвета для каждой стороны экрана (left/right/top/bottom)
3. Усредняет их в один цвет
4. Передаёт этот цвет на выбранные `light.*` сущности в HA

## Совместимость

- **Телевизоры:** Philips Android TV / Google TV 2016+ (API v6, HTTPS на порту 1926)
- **Лампочки:** Любые `light.*` сущности в Home Assistant — Philips Hue, WLED, Yeelight, Govee и т.д.

## Установка

### Через HACS (рекомендуется)

1. Откройте HACS → Integrations → ⋮ → Custom repositories
2. Добавьте URL этого репозитория, категория: **Integration**
3. Найдите "Hue Ambilight" и установите
4. Перезапустите Home Assistant

### Вручную

1. Скопируйте папку `custom_components/hue_ambilight/` в `/config/custom_components/` на вашем HA
2. Перезапустите Home Assistant

## Настройка

1. **Settings → Devices & Services → Add Integration** → поищите **"Hue Ambilight"**
2. Введите IP-адрес вашего телевизора
3. На экране ТВ появится PIN-код — введите его
4. Выберите лампочки для синхронизации
5. Настройте параметры (интервал, стороны экрана, яркость)
6. Включите переключатель **Ambilight Sync**

## Сущности

| Сущность | Тип | Описание |
|----------|-----|---------|
| `switch.ambilight_sync` | Switch | Включить/выключить синхронизацию |
| `sensor.ambilight_color` | Sensor | Текущий цвет Ambilight (#RRGGBB) |

### Атрибуты сенсора

- `r`, `g`, `b` — компоненты текущего цвета
- `sides_colors` — цвета по каждой стороне экрана
- `tv_online` — статус соединения с ТВ

## Параметры

| Параметр | По умолчанию | Описание |
|----------|-------------|---------|
| `scan_interval` | 500 мс | Как часто опрашивать ТВ |
| `sides` | all | Какие стороны экрана учитывать |
| `transition` | 0 с | Время перехода цвета у ламп |
| `brightness_factor` | 1.0 | Множитель яркости (0.1–2.0) |

## Автоматизации (примеры)

```yaml
# Включать синхронизацию когда ТВ включается
automation:
  - alias: "Ambilight ON when TV on"
    trigger:
      - platform: state
        entity_id: media_player.philips_tv
        to: "on"
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.ambilight_sync

  - alias: "Ambilight OFF when TV off"
    trigger:
      - platform: state
        entity_id: media_player.philips_tv
        to: "off"
    action:
      - service: switch.turn_off
        target:
          entity_id: switch.ambilight_sync
```

## Устранение неполадок

**Не удаётся подключиться к ТВ:**
- Убедитесь, что ТВ включён и подключён к той же сети
- Проверьте IP-адрес: `https://IP_ТВ:1926/6/system`
- Установите статический IP для ТВ в настройках роутера

**Лампочки не меняют цвет:**
- Убедитесь, что переключатель `Ambilight Sync` включён
- Проверьте, что выбранные лампочки доступны в HA

**Медленная реакция:**
- Уменьшите `scan_interval` (минимум 200 мс)
- Установите `transition: 0` для мгновенного переключения

## Лицензия

MIT

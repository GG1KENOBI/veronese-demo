# VERONESE Production Planning — интерактивное демо

End-to-end pipeline для кофейного производства: прогноз продаж по SKU → производственный план → детальное расписание линий → OEE-анализ.

**Для кого:** Союз ЛУР (бренд VERONESE) и аналогичные средние FMCG-производители.

## Быстрый старт

### Вариант 1 — локально (macOS/Linux, есть Python 3.12)

```bash
./run_demo.sh
```

Первый запуск создаёт venv, устанавливает зависимости и прогоняет полный pipeline (~3-4 мин). Открывается Streamlit на `http://localhost:8501`.

### Вариант 2 — Docker (работает везде, где установлен Docker)

```bash
docker build -t veronese-demo .
docker run -p 8501:8501 veronese-demo
```

Открыть `http://localhost:8501`. Внутри контейнера уже лежат готовые parquet — демо стартует мгновенно.

### Вариант 3 — публичный URL

Залить в GitHub → подключить [Streamlit Cloud](https://streamlit.io/cloud) → получить ссылку вида `veronese-demo.streamlit.app`. 15 минут на deploy.

## 🎯 Self-service режим для клиента

Демо спроектировано так, что клиент может **исследовать его сам без гида:**

- На главной странице — **«Как пользоваться этим демо»** с конкретными шагами
- На каждой странице — **«ℹ️ Что показывает эта страница»** с объяснением задачи и что попробовать
- Интерактивы:
  - 📦 **Планирование** — слайдеры Capacity, Setup cost, Service level → кнопка «Пересчитать» реально запускает MILP (~30 сек)
  - 📅 **Расписание** — кнопка «Re-schedule» пересчитывает CP-SAT
  - ⚙️ **OEE** — слайдер «снизить changeovers на X%» пересчитывает OEE в реальном времени
  - 🔬 **What-if** — 4 предустановленных сценария (промо, поломка смены, СТМ-рост, service level 99%) + **side-by-side сравнение с базой** (дельты, разница shadow prices, Gantt «до/после»)

## Архитектура

| Слой | Инструмент | Задача |
|------|-----------|--------|
| Demand Forecasting | StatsForecast + HierarchicalForecast | Иерархический прогноз SKU × 12 нед |
| Production Planning | Pyomo + HiGHS (MILP) | CLSP: сколько и когда производить |
| Detailed Scheduling | Google OR-Tools CP-SAT | Оптимальная последовательность SKU |
| OEE Simulation | Monte Carlo (50 replications) | Six Big Losses waterfall |
| Dashboard | Streamlit + Plotly | 6 интерактивных страниц |

## Что внутри — не замокано

- **StatsForecast** реально обучается на 21 тыс. исторических точек (29 SKU × 731 день).
- **Pyomo** реально решает MILP с 1044 binary + 1740 continuous переменными через HiGHS.
- **OR-Tools CP-SAT** реально оптимизирует последовательность с sequence-dependent setup times, сравнивает с alphabetical baseline.
- **SimPy-стиль Monte Carlo** реально сэмплирует MTBF/MTTR, minor stops, speed reduction, startup rejects.
- **What-if** слайдеры реально пересчитывают план через Pyomo.

## Структура

```
cofee_demo_optimize/
├── archive/                        # Maven Roasters Kaggle CSV (input)
├── data/
│   ├── raw/                        # копия maven_roasters.csv
│   ├── processed/                  # parquet'ы с результатами
│   └── synthetic/
├── config/
│   ├── sku_catalog.yaml            # 29 SKU × 2 brand × 4 form
│   ├── production_lines.yaml       # Bühler roasters + 3 packaging lines
│   └── ...
├── src/
│   ├── data_prep/build_dataset.py  # Maven → SKU history с Russian seasonality
│   ├── forecasting/hierarchical.py # StatsForecast + MinTrace reconciliation
│   ├── planning/clsp_model.py      # Pyomo CLSP + dual values for shadow prices
│   ├── scheduling/cpsat_model.py   # CP-SAT naive vs optimized
│   ├── simulation/oee_simulator.py # Monte Carlo + waterfall + Six Big Losses
│   └── visualization/charts.py     # shared Plotly helpers
├── app/
│   ├── main.py                     # Streamlit entry
│   └── pages/
│       ├── overview.py
│       ├── forecast_page.py
│       ├── planning_page.py
│       ├── schedule_page.py
│       ├── oee_page.py
│       └── whatif_page.py
├── docs/
│   └── demo_script.md              # 30-45 минутный сценарий для показа
├── requirements.txt
└── run_demo.sh                     # однокнопочный запуск
```

## Запуск отдельных модулей

Каждый модуль работает через parquet — можно запускать изолированно:

```bash
source .venv/bin/activate

python -m src.data_prep.build_dataset         # 5 сек
python -m src.forecasting.hierarchical        # 60-120 сек
python -m src.planning.clsp_model             # 3-5 сек
python -m src.scheduling.cpsat_model          # 20-60 сек
python -m src.simulation.oee_simulator        # 5-10 сек

streamlit run app/main.py
```

## Требования

- **macOS / Linux** (на Windows через WSL)
- **Python 3.12** (3.11 тоже подойдёт)
- **8 GB RAM минимум**, 2-3 GB peak usage

## Метрики на текущем демо-датасете

- SKU: 29, ~27 млн упаковок/год
- Forecast WAPE: **~22.4%** (walk-forward CV, 4 × 28 дней)
- CLSP total cost (12 нед): **~382 М₽**
  - Production: 360 М₽ (94%)
  - Setup: 8.2 М₽ (2.1%) — материальная доля, есть что оптимизировать
  - Holding: 8.2 М₽ (2.1%)
  - Backorder: 5.25 М₽ (1.4%) — капасити почти достаточно, есть лёгкий дефицит на пиковых неделях
- Shadow prices на Packaging_A: **до 78 тыс. руб/мин** на пиковой неделе
- Setup savings (optimized vs naive scheduling): **4 ч/день на одной неделе** ≈ 62 М₽/год
- OEE optimized: **52.6%** vs naive 46.0% (+6.6 п.п.)
  - Availability 70.9%, Performance 87%, Quality 95.8%  
  - (на синтетике; на реальных данных с меньшим SKU-портфелем обычно 60-75%)

### Время выполнения (M4 Pro)
| Шаг | Время |
|-----|-------|
| Data prep | ~5 сек |
| Forecasting (StatsForecast × 5 моделей × 41 серия) | ~2 мин |
| CLSP MILP (HiGHS, 1044 binary vars) | ~60 сек |
| CP-SAT Scheduling | ~1-15 сек |
| OEE Monte Carlo (50×) | ~1 сек |
| **Первый запуск** | **~3-4 мин** |
| **Dashboard interactive** | **мгновенно (кэш)** |

## Демо клиенту

Полный пошаговый сценарий: [`docs/demo_script.md`](docs/demo_script.md).

Основные акты:
1. **Акт 0** — обзор, 2 мин
2. **Акт 1** — прогноз (HierarchicalForecast reconciliation = главный selling point), 7 мин
3. **Акт 2** — план + shadow prices, 10 мин
4. **Акт 3** — Gantt naive vs optimized (главный визуал), 10 мин
5. **Акт 4** — OEE waterfall + Six Big Losses, 8 мин
6. **Акт 5** — What-if сценарии, 5-8 мин

Total: **30-45 минут**.

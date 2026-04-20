#!/usr/bin/env bash
# VERONESE Production Planning Demo — однокомандный запуск
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [ ! -d ".venv" ]; then
    echo "==> Создаём virtual env (Python 3.12)"
    # Find a suitable Python 3.12 interpreter on any platform
    if command -v python3.12 >/dev/null 2>&1; then
        PYTHON_BIN="$(command -v python3.12)"
    elif [ -x "/opt/homebrew/bin/python3.12" ]; then
        PYTHON_BIN="/opt/homebrew/bin/python3.12"
    elif [ -x "/usr/local/bin/python3.12" ]; then
        PYTHON_BIN="/usr/local/bin/python3.12"
    elif command -v python3 >/dev/null 2>&1; then
        echo "Предупреждение: python3.12 не найден, используем python3 ($(python3 --version))."
        PYTHON_BIN="$(command -v python3)"
    else
        echo "Ошибка: не найден python3.12 или python3. Установите Python 3.12+." >&2
        exit 1
    fi
    "$PYTHON_BIN" -m venv .venv
    . .venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
else
    . .venv/bin/activate
fi

# Если parquet-файлов нет — запускаем полный pipeline (~2 мин)
if [ ! -f "data/processed/oee_waterfall.parquet" ]; then
    echo "==> Первый запуск: собираем весь pipeline"
    python -m src.data_prep.build_dataset
    python -m src.forecasting.hierarchical
    python -m src.planning.clsp_model
    python -m src.scheduling.cpsat_model
    python -m src.simulation.oee_simulator
fi

# Если сценарии ещё не прекомпьютнуты — собираем (~5-7 мин)
if [ ! -d "data/processed/scenarios/base" ]; then
    echo "==> Прекомпьютим 5 сценариев (~5-7 мин) чтобы убрать spinner в демо"
    python -m scripts.build_scenarios
fi

echo ""
echo "==============================================="
echo "  Streamlit dashboard: http://localhost:8501"
echo "==============================================="
echo ""
exec streamlit run app/main.py \
    --server.port=8501 \
    --server.headless=false \
    --browser.gatherUsageStats=false

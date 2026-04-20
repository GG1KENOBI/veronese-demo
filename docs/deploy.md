# Деплой демо на публичный URL

Цель: получить ссылку вида `https://<your-name>.streamlit.app`, которую можно вставить в письмо клиенту.

## Вариант 1 — Streamlit Community Cloud (бесплатно, 5 минут)

### Предпосылки

- Репозиторий на GitHub (публичный или приватный с подпиской)
- Все `data/processed/*.parquet` закоммичены (у нас уже так)

### Шаги

1. **Положите репо на GitHub.** В терминале (из корня проекта):
   ```bash
   git remote add origin https://github.com/<your-user>/veronese-demo.git
   git branch -M main
   git push -u origin main
   ```

2. **Откройте [share.streamlit.io](https://share.streamlit.io)** → залогиньтесь через GitHub.

3. Кнопка **«New app»**. Форма:
   - Repository: `<your-user>/veronese-demo`
   - Branch: `main`
   - Main file path: `app/main.py`
   - (опционально) App URL: `veronese-demo` → получите `veronese-demo.streamlit.app`

4. Нажмите **Deploy**. Сборка занимает ~3-4 мин (устанавливает `requirements.txt`).

5. Откройте URL, убедитесь что:
   - Hero-число «+185 млн ₽/год» показано
   - Gantt на главной загружается
   - Сценарии в сайдбаре переключаются мгновенно
   - Нет 60-сек спиннеров

6. **Готово. Копируйте URL в письмо клиенту.**

### Обновления

Каждый `git push` в main автоматически пересобирает app. Изменения виден клиенту через 2-3 мин.

### Ограничения бесплатного тарифа

- 1 ГБ RAM (нам хватает: ~200 МБ на старте)
- Засыпает после 7 дней без активности → при открытии просыпается ~30 сек. Если это критично — обновляться в cron или перейти на paid tier.

---

## Вариант 2 — Свой сервер (Docker)

Если нужен свой домен или `Streamlit Cloud` недоступен.

```bash
docker build -t veronese-demo .
docker run -d -p 8501:8501 --name veronese-demo veronese-demo
```

Настройте reverse-proxy (Caddy / Nginx) с HTTPS на `8501`, выведите на `demo.your-domain.ru`.

---

## Вариант 3 — Railway / Render / Fly.io

Все три принимают `Dockerfile` из коробки.

**Fly.io (пример):**
```bash
fly launch --no-deploy  # создаст fly.toml по Dockerfile
fly deploy
# URL будет вида https://veronese-demo.fly.dev
```

---

## Проверочный чек-лист перед отправкой ссылки клиенту

Откройте URL в **incognito-окне** (чтобы не тянуть кэш) и убедитесь:

- [ ] Title «Оптимизация кофейного производства — VERONESE»
- [ ] Hero +185 млн ₽/год виден без скролла
- [ ] Wizard с 3 полями работает (ввод → пересчёт цифры)
- [ ] Gantt-анимация на главной запускается по кнопке ▶ Оптимизировать
- [ ] Все 5 сценариев в сайдбаре переключаются **мгновенно** (не 60 сек!)
- [ ] 3 expander'а внизу открываются без ошибок
- [ ] На мобильном (откройте URL на телефоне) всё читабельно

Если что-то отваливается — проверьте логи в Streamlit Cloud (кнопка «Manage app» → «Logs»).

## Подгонка под другого клиента

Главный файл — `config/client.yaml`. Меняете там:
- `client_name` — имя в title
- `lines_count`, `working_days_per_year`, `rub_per_production_minute` — параметры расчёта
- `brand_style` — полное имя в футере

Commit + push → через 2-3 мин на URL уже новая версия. Для второго клиента идеально — форкнуть репо, поменять `config/client.yaml`, деплоить под отдельным URL.

#!/usr/bin/env bash
# Хук SessionStart: подтянуть репозиторий и показать сессии, что делали
# на другой машине. Всё, что печатается, попадает в контекст Claude.
# Работает и на macOS, и на Windows (через Git Bash из Git for Windows).
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)" || exit 0

if git pull --ff-only --quiet 2>/dev/null; then
  echo "Репозиторий подтянут (git pull --ff-only)."
else
  echo "git pull не прошёл: нет сети, либо есть локальные незакоммиченные правки или расхождение веток. Проверьте git status."
fi

echo
echo "Машина: $(hostname 2>/dev/null || echo '?'), ветка: $(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
echo
echo "Последние коммиты:"
git log --oneline -8 2>/dev/null

if [ -f docs/journal.md ]; then
  echo
  echo "Последняя запись журнала (docs/journal.md):"
  # печатаем от последнего заголовка второго уровня до конца файла
  awk '/^## /{buf=""} {buf=buf $0 "\n"} END{printf "%s", buf}' docs/journal.md | head -n 60
fi

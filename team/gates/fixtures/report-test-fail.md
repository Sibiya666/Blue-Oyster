---
task: 001-demo
round: 1
verdict: FAIL
---
## Проверка критериев
| AC | Результат | Доказательство |
|---|---|---|
| AC-1 | pass | tests/demo.test.ts: "does Y on X" |
| AC-2 | fail | tests/demo.test.ts: "ignores Z" |

## Дефекты
- D-1: при Z происходит Y. Шаги: 1) сделать Z. Ожидалось: ничего. Получилось: Y.

## Добавленные тесты
- tests/demo.test.ts

#!/usr/bin/env bash
# Тесты гейтов. Запуск: bash team/gates/test.sh [имя-гейта]
# Каждый случай: временная директория с фикстурами, JSON на stdin, проверка кода выхода и вывода.
set -u

command -v jq >/dev/null || { echo "нужен jq: brew install jq" >&2; exit 1; }

GATES="$(cd "$(dirname "$0")" && pwd)"
FIX="$GATES/fixtures"
ONLY="${1:-}"
PASS=0
FAIL=0
export GATE_DRY_RUN=1

want() { [ -z "$ONLY" ] || [ "$ONLY" = "$1" ]; }

new_tmp() {
  local d
  d="$(mktemp -d)"
  mkdir -p "$d/docs/specs" "$d/docs/reports" "$d/.team" "$d/.github/workflows" "$d/src" "$d/tests"
  echo "$d"
}

# hook_json <cwd> <event> [agent_type] [agent_id] [tool_name] [file_path] [subagent_type] [prompt]
hook_json() {
  jq -n --arg cwd "$1" --arg ev "$2" --arg at "${3:-}" --arg aid "${4:-}" \
        --arg tn "${5:-}" --arg fp "${6:-}" --arg st "${7:-}" --arg pr "${8:-}" '
    {hook_event_name: $ev, cwd: $cwd, session_id: "test"}
    + (if $at != "" then {agent_type: $at, agent_id: $aid} else {} end)
    + (if $tn != "" then {tool_name: $tn, tool_input: ({}
         + (if $fp != "" then {file_path: $fp} else {} end)
         + (if $st != "" then {subagent_type: $st} else {} end)
         + (if $pr != "" then {prompt: $pr} else {} end))} else {} end)'
}

# run_gate <script> <json> → RC, OUT, ERR
run_gate() {
  local out err
  out="$(mktemp)"
  err="$(mktemp)"
  printf '%s' "$2" | bash "$GATES/$1" >"$out" 2>"$err"
  RC=$?
  OUT="$(cat "$out")"
  ERR="$(cat "$err")"
  rm -f "$out" "$err"
}

check() { # check <name> <0|1> <details>
  if [ "$2" -eq 0 ]; then
    PASS=$((PASS + 1)); echo "  ok   $1"
  else
    FAIL=$((FAIL + 1)); echo "  FAIL $1"; echo "       $3"
  fi
}

expect_rc() { # expect_rc <name> <code>
  local ok=1; [ "$RC" -eq "$2" ] && ok=0
  check "$1" $ok "rc=$RC, ожидался $2; stderr: $(echo "$ERR" | head -3)"
}
expect_err_contains() { # expect_err_contains <name> <text>
  local ok=1; echo "$ERR" | grep -q -- "$2" && ok=0
  check "$1" $ok "stderr: $ERR"
}
expect_deny() { # expect_deny <name>
  local ok=1; echo "$OUT" | jq -e '.hookSpecificOutput.permissionDecision == "deny"' >/dev/null 2>&1 && ok=0
  check "$1" $ok "stdout: $OUT"
}
expect_allow() { # expect_allow <name>  — код 0 и пустой stdout или JSON без deny
  local ok=0
  [ "$RC" -eq 0 ] || ok=1
  if [ -n "$OUT" ] && echo "$OUT" | jq -e '.hookSpecificOutput.permissionDecision == "deny"' >/dev/null 2>&1; then ok=1; fi
  check "$1" $ok "rc=$RC; stdout: $OUT; stderr: $(echo "$ERR" | head -3)"
}
expect_log_contains() { # expect_log_contains <name> <cwd> <text>
  local ok=1; grep -q -- "$3" "$2/.team/gate.log" 2>/dev/null && ok=0
  check "$1" $ok "log: $(cat "$2/.team/gate.log" 2>/dev/null)"
}

# ---------------------------------------------------------------- analyst
if want analyst; then
  echo "analyst.sh"
  T=$(new_tmp); cp "$FIX/spec-good.md" "$T/docs/specs/001-demo.md"
  run_gate analyst.sh "$(hook_json "$T" SubagentStop analyst a1)"
  expect_rc "правильная спека проходит" 0
  expect_log_contains "пишет pass в лог" "$T" "analyst analyst pass"

  T=$(new_tmp); cp "$FIX/spec-missing-section.md" "$T/docs/specs/001-demo.md"
  run_gate analyst.sh "$(hook_json "$T" SubagentStop analyst a2)"
  expect_rc "без секции блокирует" 2
  expect_err_contains "называет недостающую секцию" "Открытые вопросы"

  T=$(new_tmp); cp "$FIX/spec-no-ac.md" "$T/docs/specs/001-demo.md"
  run_gate analyst.sh "$(hook_json "$T" SubagentStop analyst a3)"
  expect_rc "без критериев блокирует" 2
  expect_err_contains "упоминает AC" "AC"

  T=$(new_tmp)
  run_gate analyst.sh "$(hook_json "$T" SubagentStop analyst a4)"
  expect_rc "без спеки блокирует" 2
fi

# -------------------------------------------------------------- developer
if want developer; then
  echo "developer.sh"
  T=$(new_tmp); cp "$FIX/package.json" "$T/"
  export GATE_FAKE_LINT=0 GATE_FAKE_TEST=0
  run_gate developer.sh "$(hook_json "$T" SubagentStop developer d1)"
  expect_rc "зелёные lint и test проходят" 0
  expect_log_contains "пишет pass в лог" "$T" "developer developer pass"

  T=$(new_tmp)
  run_gate developer.sh "$(hook_json "$T" SubagentStop developer d2)"
  expect_rc "без package.json блокирует" 2
  expect_err_contains "упоминает package.json" "package.json"

  T=$(new_tmp); cp "$FIX/package.json" "$T/"
  export GATE_FAKE_LINT=1
  run_gate developer.sh "$(hook_json "$T" SubagentStop developer d3)"
  expect_rc "красный lint блокирует" 2
  expect_err_contains "упоминает lint" "lint"
  export GATE_FAKE_LINT=0

  T=$(new_tmp); cp "$FIX/package.json" "$T/"
  export GATE_FAKE_TEST=1
  run_gate developer.sh "$(hook_json "$T" SubagentStop developer d4)"
  expect_rc "красные тесты блокируют (попытка 1)" 2
  expect_err_contains "упоминает npm test" "npm test"
  run_gate developer.sh "$(hook_json "$T" SubagentStop developer d4)"
  expect_rc "попытка 2 всё ещё блокирует" 2
  run_gate developer.sh "$(hook_json "$T" SubagentStop developer d4)"
  expect_rc "попытка 3 выпускает по лимиту" 0
  expect_log_contains "пишет limit в лог" "$T" "developer developer limit"
  unset GATE_FAKE_LINT GATE_FAKE_TEST
fi

# ----------------------------------------------------------------- tester
if want tester; then
  echo "tester.sh"
  T=$(new_tmp); cp "$FIX/spec-good.md" "$T/docs/specs/001-demo.md"; cp "$FIX/report-test-pass.md" "$T/docs/reports/001-demo-test.md"; cp "$FIX/package.json" "$T/"
  export GATE_FAKE_TEST=0
  run_gate tester.sh "$(hook_json "$T" SubagentStop tester t1)"
  expect_rc "полный отчёт проходит" 0

  T=$(new_tmp); cp "$FIX/spec-good.md" "$T/docs/specs/001-demo.md"; cp "$FIX/report-test-fail.md" "$T/docs/reports/001-demo-test.md"; cp "$FIX/package.json" "$T/"
  run_gate tester.sh "$(hook_json "$T" SubagentStop tester t2)"
  expect_rc "отчёт с FAIL тоже проходит гейт (вердикт — не ошибка)" 0

  T=$(new_tmp); cp "$FIX/spec-good.md" "$T/docs/specs/001-demo.md"; cp "$FIX/report-test-missing-ac.md" "$T/docs/reports/001-demo-test.md"; cp "$FIX/package.json" "$T/"
  run_gate tester.sh "$(hook_json "$T" SubagentStop tester t3)"
  expect_rc "непокрытый AC блокирует" 2
  expect_err_contains "называет AC-2" "AC-2"

  T=$(new_tmp); cp "$FIX/spec-good.md" "$T/docs/specs/001-demo.md"; cp "$FIX/report-test-bad-verdict.md" "$T/docs/reports/001-demo-test.md"; cp "$FIX/package.json" "$T/"
  run_gate tester.sh "$(hook_json "$T" SubagentStop tester t4)"
  expect_rc "неверный verdict блокирует" 2
  expect_err_contains "упоминает verdict" "verdict"

  T=$(new_tmp); cp "$FIX/spec-good.md" "$T/docs/specs/001-demo.md"; cp "$FIX/package.json" "$T/"
  run_gate tester.sh "$(hook_json "$T" SubagentStop tester t5)"
  expect_rc "без отчёта блокирует" 2

  T=$(new_tmp); cp "$FIX/spec-good.md" "$T/docs/specs/001-demo.md"; cp "$FIX/report-test-pass.md" "$T/docs/reports/001-demo-test.md"; cp "$FIX/package.json" "$T/"
  export GATE_FAKE_TEST=1
  run_gate tester.sh "$(hook_json "$T" SubagentStop tester t6)"
  expect_rc "красные тесты блокируют тестировщика" 2
  unset GATE_FAKE_TEST
fi

# ----------------------------------------------------------------- devops
if want devops; then
  echo "devops.sh"
  export GATE_FAKE_DOCKER=0
  T=$(new_tmp); cp "$FIX/report-deploy-ok.md" "$T/docs/reports/001-demo-deploy.md"; cp "$FIX/Dockerfile" "$T/"; cp "$FIX/ci.yml" "$T/.github/workflows/ci.yml"
  run_gate devops.sh "$(hook_json "$T" SubagentStop devops v1)"
  expect_rc "полный набор проходит" 0

  T=$(new_tmp); cp "$FIX/report-deploy-ok.md" "$T/docs/reports/001-demo-deploy.md"; cp "$FIX/ci.yml" "$T/.github/workflows/ci.yml"
  run_gate devops.sh "$(hook_json "$T" SubagentStop devops v2)"
  expect_rc "без Dockerfile блокирует" 2
  expect_err_contains "упоминает Dockerfile" "Dockerfile"

  T=$(new_tmp); cp "$FIX/report-deploy-ok.md" "$T/docs/reports/001-demo-deploy.md"; cp "$FIX/Dockerfile" "$T/"
  run_gate devops.sh "$(hook_json "$T" SubagentStop devops v3)"
  expect_rc "без ci.yml блокирует" 2
  expect_err_contains "упоминает ci.yml" "ci.yml"

  T=$(new_tmp); cp "$FIX/Dockerfile" "$T/"; cp "$FIX/ci.yml" "$T/.github/workflows/ci.yml"
  run_gate devops.sh "$(hook_json "$T" SubagentStop devops v4)"
  expect_rc "без отчёта блокирует" 2

  T=$(new_tmp); cp "$FIX/report-deploy-ok.md" "$T/docs/reports/001-demo-deploy.md"; cp "$FIX/Dockerfile" "$T/"; cp "$FIX/ci.yml" "$T/.github/workflows/ci.yml"
  export GATE_FAKE_DOCKER=1
  run_gate devops.sh "$(hook_json "$T" SubagentStop devops v5)"
  expect_rc "упавший docker build блокирует" 2
  expect_err_contains "упоминает docker" "docker"
  unset GATE_FAKE_DOCKER
fi

# ------------------------------------------------------------ path-policy
if want path-policy; then
  echo "path-policy.sh"
  T=$(new_tmp)
  run_gate path-policy.sh "$(hook_json "$T" PreToolUse "" "" Write "$T/src/x.ts")"
  expect_allow "главная сессия пишет куда угодно"
  run_gate path-policy.sh "$(hook_json "$T" PreToolUse tester p1 Write "$T/src/x.ts")"
  expect_deny "tester не пишет в src/"
  expect_log_contains "пишет deny в лог" "$T" "path-policy tester deny"
  run_gate path-policy.sh "$(hook_json "$T" PreToolUse tester p1 Write "$T/tests/x.test.ts")"
  expect_allow "tester пишет в tests/"
  run_gate path-policy.sh "$(hook_json "$T" PreToolUse tester p1 Write "$T/docs/reports/001-demo-test.md")"
  expect_allow "tester пишет в docs/reports/"
  run_gate path-policy.sh "$(hook_json "$T" PreToolUse analyst p2 Write "$T/docs/specs/001-demo.md")"
  expect_allow "analyst пишет в docs/specs/"
  run_gate path-policy.sh "$(hook_json "$T" PreToolUse analyst p2 Write "$T/src/x.ts")"
  expect_deny "analyst не пишет в src/"
  run_gate path-policy.sh "$(hook_json "$T" PreToolUse devops p3 Edit "$T/src/index.ts")"
  expect_deny "devops не правит src/"
  run_gate path-policy.sh "$(hook_json "$T" PreToolUse devops p3 Write "$T/.github/workflows/ci.yml")"
  expect_allow "devops пишет в .github/"
  run_gate path-policy.sh "$(hook_json "$T" PreToolUse devops p3 Write "$T/Dockerfile")"
  expect_allow "devops пишет Dockerfile"
  run_gate path-policy.sh "$(hook_json "$T" PreToolUse developer p4 Write "$T/docs/specs/001-demo.md")"
  expect_deny "developer не пишет в docs/specs/"
  run_gate path-policy.sh "$(hook_json "$T" PreToolUse developer p4 Write "$T/docs/reports/001-demo-test.md")"
  expect_deny "developer не пишет в docs/reports/"
  run_gate path-policy.sh "$(hook_json "$T" PreToolUse developer p4 Write "$T/src/index.ts")"
  expect_allow "developer пишет в src/"
  run_gate path-policy.sh "$(hook_json "$T" PreToolUse developer p4 Write "$T/package.json")"
  expect_allow "developer пишет package.json"
  run_gate path-policy.sh "$(hook_json "$T" PreToolUse general-purpose p5 Write "$T/src/x.ts")"
  expect_allow "незнакомая роль проходит"
fi

# ----------------------------------------------------------- start-policy
if want start-policy; then
  echo "start-policy.sh"
  T=$(new_tmp)
  cp "$FIX/spec-good.md" "$T/docs/specs/001-demo.md"
  cp "$FIX/spec-draft.md" "$T/docs/specs/002-draft.md"
  cp "$FIX/spec-open-questions.md" "$T/docs/specs/003-open.md"
  cp "$FIX/report-test-pass.md" "$T/docs/reports/001-demo-test.md"
  cp "$FIX/report-test-fail.md" "$T/docs/reports/004-fail-test.md"

  run_gate start-policy.sh "$(hook_json "$T" PreToolUse "" "" Agent "" analyst "Напиши спеку: бот отвечает pong")"
  expect_allow "analyst стартует без условий"
  run_gate start-policy.sh "$(hook_json "$T" PreToolUse "" "" Agent "" developer "Реализуй спеку docs/specs/001-demo.md")"
  expect_allow "developer стартует на утверждённой спеке"
  run_gate start-policy.sh "$(hook_json "$T" PreToolUse "" "" Agent "" developer "Реализуй спеку docs/specs/002-draft.md")"
  expect_deny "developer не стартует на draft"
  expect_log_contains "пишет deny в лог" "$T" "start-policy developer deny"
  run_gate start-policy.sh "$(hook_json "$T" PreToolUse "" "" Agent "" developer "Реализуй спеку docs/specs/003-open.md")"
  expect_deny "developer не стартует при открытых вопросах"
  run_gate start-policy.sh "$(hook_json "$T" PreToolUse "" "" Agent "" developer "Реализуй что-нибудь")"
  expect_deny "developer не стартует без пути к спеке"
  run_gate start-policy.sh "$(hook_json "$T" PreToolUse "" "" Agent "" developer "Задача 001. Спека docs/specs/001-demo.md, отчёт docs/reports/001-demo-test.md, закрой дефекты")"
  expect_allow "developer на повторном раунде берёт путь спеки"
  run_gate start-policy.sh "$(hook_json "$T" PreToolUse "" "" Agent "" tester "Проверь спеку docs/specs/001-demo.md")"
  expect_allow "tester стартует на утверждённой спеке"
  run_gate start-policy.sh "$(hook_json "$T" PreToolUse "" "" Agent "" tester "Проверь спеку docs/specs/002-draft.md")"
  expect_deny "tester не стартует на draft"
  run_gate start-policy.sh "$(hook_json "$T" PreToolUse "" "" Agent "" devops "Отчёт docs/reports/001-demo-test.md")"
  expect_allow "devops стартует на PASS"
  run_gate start-policy.sh "$(hook_json "$T" PreToolUse "" "" Agent "" devops "Отчёт docs/reports/004-fail-test.md")"
  expect_deny "devops не стартует на FAIL"
  run_gate start-policy.sh "$(hook_json "$T" PreToolUse "" "" Agent "" devops "Сделай деплой")"
  expect_deny "devops не стартует без пути к отчёту"
  run_gate start-policy.sh "$(hook_json "$T" PreToolUse "" "" Agent "" general-purpose "Найди файл")"
  expect_allow "незнакомая роль проходит"
fi

echo
echo "passed: $PASS, failed: $FAIL"
[ "$FAIL" -eq 0 ]

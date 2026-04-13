# Lessons Learned

## L-001: Contract-First prevents rework
**Контекст**: Parity v1 Phase 1-3
**Паттерн**: Protocol → contract tests → implementation = тесты проходят с первого раза
**Антипаттерн**: Писать реализацию, потом тесты → тесты раскрывают несоответствие контракту → переписывание

## L-002: Strangler Fig for native tools
**Контекст**: Phase 5 (Native Tool Calling)
**Паттерн**: JSON-in-text остаётся default, native tools = opt-in. Fallback при ошибке native → JSON-in-text
**Антипаттерн**: Заменить всё сразу → breakage для пользователей без native support

## L-003: Hook order matters
**Контекст**: Phase 1-2 (Hook Dispatch + Policy)
**Паттерн**: PreToolUse → Policy → Execute → PostToolUse. Policy проверяет ПОСЛЕ hook modify
**Антипаттерн**: Policy перед hooks → hooks не могут повлиять на решение policy

## L-004: Optional fields with None default
**Контекст**: Все фазы Parity v1
**Паттерн**: Все новые поля в AgentConfig/RuntimeConfig = `field_name: Type | None = None`
**Антипаттерн**: Обязательные поля → breakage для существующих пользователей

## L-005: InputFilter is the primary extension point
**Контекст**: Phase 7 (Production Safety), Phase 11 design
**Паттерн**: Новая функциональность через InputFilter — не модифицирует ThinRuntime.run()
**Антипаттерн**: Добавлять if/else в run() → разрастание и хрупкость

## L-006: Sonnet agents exhaust context → Judge skip
**Контекст**: /build:team-phase experience
**Паттерн**: ВСЕ агенты на Opus с 1M context. Экономия токенов не стоит потери quality gates
**Антипаттерн**: Sonnet/Haiku для developers/testers → context exhaustion → team-lead takeover → Judge пропущен

## L-007: Shared builtin tools prevent implementation drift
**Контекст**: Phase 7 (Coding Profile)
**Паттерн**: read/write/edit/bash/glob/grep sourced из shared builtin, не из thin-only path
**Антипаттерн**: Параллельная реализация тех же инструментов → drift и несоответствие поведения

## L-008: Fail-fast for invalid configuration
**Контекст**: Phase 9-10 (Context + Subagent Inheritance)
**Паттерн**: Неподдерживаемая конфигурация → explicit error с explanation
**Антипаттерн**: Silent degradation → пользователь думает что работает, а фича не активна

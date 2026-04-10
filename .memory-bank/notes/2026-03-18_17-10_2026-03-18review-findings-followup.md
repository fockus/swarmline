# 2026-03-18_review-findings-followup
Date: 2026-03-18 17:10

## Что сделано
-

## Новые знания
-
# Review Findings Follow-up
Date: 2026-03-18 17:10

## Что сделано
- Повторно проверены и воспроизведены 4 свежих review findings после Wave 2 low-risk slices.
- Подтверждено, что `SessionManager.stream_reply()` теряет canonical `final.new_messages` и сохраняет только synthetic assistant text.
- Подтверждено, что `RuntimeFactory` fallback path не умеет создавать builtin `cli`, если registry недоступен.
- Подтверждено, что lazy optional exports в `cognitia.runtime` и `cognitia.skills` ломают `from ... import *` в окружениях без optional deps.

## Новые знания
- После перевода optional exports на fail-fast `__getattr__` нужно синхронно пересматривать `__all__`; иначе star-import превращает optional symbols в hard dependency.
- Session-level runtime history должен потреблять тот же canonical final payload, что и facade-level `Conversation`, иначе multi-turn path снова расходится по semantics.
- Registry/factory migration нельзя считать завершённой, пока fallback path и dynamic valid names описывают один и тот же набор builtin runtimes.

"""ThinRuntime — собственный тонкий агентный loop.

3 режима: conversational | react | planner-lite.
Bounded loops, typed errors, streaming RuntimeEvent.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from pydantic import ValidationError

from cognitia.runtime.structured_output import (
    append_structured_output_instruction,
    extract_structured_output,
)
from cognitia.runtime.thin.executor import ToolExecutor
from cognitia.runtime.thin.modes import detect_mode
from cognitia.runtime.thin.prompts import (
    build_conversational_prompt,
    build_final_assembly_prompt,
    build_plan_step_prompt,
    build_planner_prompt,
    build_react_prompt,
)
from cognitia.runtime.thin.schemas import ActionEnvelope, PlanSchema
from cognitia.runtime.types import (
    Message,
    RuntimeConfig,
    RuntimeErrorData,
    RuntimeEvent,
    ToolSpec,
    TurnMetrics,
)


class ThinRuntime:
    """Собственный тонкий агентный loop.

    Режимы:
    - conversational: single LLM call → final
    - react: loop (LLM → tool_call | final)
    - planner: plan JSON → step execution → final assembly

    Args:
        config: Конфигурация runtime (budgets, model).
        llm_call: Callable для вызова LLM (для тестирования).
                  Сигнатура: async (messages, system_prompt) -> str
        local_tools: Маппинг tool_name → callable.
    """

    def __init__(
        self,
        config: RuntimeConfig | None = None,
        llm_call: Callable[..., Any] | None = None,
        local_tools: dict[str, Callable[..., Any]] | None = None,
        mcp_servers: dict[str, Any] | None = None,
        react_patterns: list[re.Pattern[str]] | None = None,
        planner_patterns: list[re.Pattern[str]] | None = None,
    ) -> None:
        self._config = config or RuntimeConfig(runtime_name="thin")
        self._llm_call = llm_call or self._default_llm_call
        self._react_patterns = react_patterns
        self._planner_patterns = planner_patterns
        self._executor = ToolExecutor(
            local_tools=local_tools,
            mcp_servers=mcp_servers,
        )

    async def run(
        self,
        *,
        messages: list[Message],
        system_prompt: str,
        active_tools: list[ToolSpec],
        config: RuntimeConfig | None = None,
        mode_hint: str | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Выполнить один turn.

        1. Определить mode (conversational/react/planner)
        2. Запустить соответствующий loop
        3. Emit RuntimeEvent (стрим)
        """
        effective_config = config or self._config
        start_time = time.monotonic()

        # Определяем mode
        user_text = self._extract_last_user_text(messages)
        mode = detect_mode(
            user_text,
            mode_hint,
            react_patterns=self._react_patterns,
            planner_patterns=self._planner_patterns,
        )

        yield RuntimeEvent.status(f"Режим: {mode}")

        try:
            if mode == "conversational":
                async for event in self._run_conversational(
                    messages,
                    system_prompt,
                    effective_config,
                    start_time,
                ):
                    yield event

            elif mode == "react":
                async for event in self._run_react(
                    messages,
                    system_prompt,
                    active_tools,
                    effective_config,
                    start_time,
                ):
                    yield event

            elif mode == "planner":
                async for event in self._run_planner(
                    messages,
                    system_prompt,
                    active_tools,
                    effective_config,
                    start_time,
                ):
                    yield event

        except Exception as e:
            yield RuntimeEvent.error(
                RuntimeErrorData(
                    kind="runtime_crash",
                    message=f"ThinRuntime crash: {e}",
                    recoverable=False,
                )
            )

    # ------------------------------------------------------------------
    # Conversational mode
    # ------------------------------------------------------------------

    async def _run_conversational(
        self,
        messages: list[Message],
        system_prompt: str,
        config: RuntimeConfig,
        start_time: float,
    ) -> AsyncIterator[RuntimeEvent]:
        """Single LLM call → final."""
        prompt = build_conversational_prompt(
            append_structured_output_instruction(
                system_prompt,
                config.output_format,
                final_response_field="final_message",
            )
        )
        lm_messages = self._messages_to_lm(messages)

        raw = await self._llm_call(lm_messages, prompt)

        # Парсим ответ
        envelope = self._parse_envelope(raw)
        if envelope is None:
            # Retry
            raw = await self._llm_call(lm_messages, prompt)
            envelope = self._parse_envelope(raw)

        if envelope is None:
            yield RuntimeEvent.error(
                RuntimeErrorData(
                    kind="bad_model_output",
                    message="LLM вернула некорректный JSON после 2 попыток",
                    recoverable=False,
                )
            )
            return

        # Извлекаем текст
        if envelope.type == "final" and envelope.final_message:
            text = envelope.final_message
        else:
            text = raw  # fallback: используем raw ответ

        new_messages = [Message(role="assistant", content=text)]
        structured_output = extract_structured_output(text, config.output_format)

        yield RuntimeEvent.assistant_delta(text)
        yield RuntimeEvent.final(
            text=text,
            new_messages=new_messages,
            metrics=self._build_metrics(start_time, config, iterations=1),
            structured_output=structured_output,
        )

    # ------------------------------------------------------------------
    # React mode
    # ------------------------------------------------------------------

    async def _run_react(
        self,
        messages: list[Message],
        system_prompt: str,
        tools: list[ToolSpec],
        config: RuntimeConfig,
        start_time: float,
    ) -> AsyncIterator[RuntimeEvent]:
        """React loop: LLM → tool_call | final."""
        prompt = build_react_prompt(
            append_structured_output_instruction(
                system_prompt,
                config.output_format,
                final_response_field="final_message",
            ),
            tools,
        )
        lm_messages = self._messages_to_lm(messages)
        new_messages: list[Message] = []

        iterations = 0
        tool_calls_count = 0
        retries = 0
        last_raw = ""

        while iterations < config.max_iterations:
            iterations += 1

            raw = await self._llm_call(lm_messages, prompt)
            last_raw = raw
            envelope = self._parse_envelope(raw)

            if envelope is None:
                retries += 1
                if retries > config.max_model_retries:
                    fallback_text = self._extract_text_fallback(last_raw)
                    if fallback_text:
                        new_messages.append(Message(role="assistant", content=fallback_text))
                        structured_output = extract_structured_output(
                            fallback_text,
                            config.output_format,
                        )
                        yield RuntimeEvent.status(
                            "LLM ответила не в JSON-формате, использую текстовый fallback"
                        )
                        yield RuntimeEvent.assistant_delta(fallback_text)
                        yield RuntimeEvent.final(
                            text=fallback_text,
                            new_messages=new_messages,
                            metrics=self._build_metrics(
                                start_time,
                                config,
                                iterations,
                                tool_calls_count,
                            ),
                            structured_output=structured_output,
                        )
                        return
                    yield RuntimeEvent.error(
                        RuntimeErrorData(
                            kind="bad_model_output",
                            message=f"LLM вернула некорректный JSON {retries} раз подряд",
                            recoverable=False,
                        )
                    )
                    return
                continue

            retries = 0  # Сброс при успешном парсинге

            # --- tool_call ---
            if envelope.type == "tool_call" and envelope.tool:
                tc = envelope.tool

                # Budget check
                if tool_calls_count >= config.max_tool_calls:
                    yield RuntimeEvent.error(
                        RuntimeErrorData(
                            kind="budget_exceeded",
                            message=f"Превышен лимит tool_calls ({config.max_tool_calls})",
                            recoverable=False,
                        )
                    )
                    return

                cid = tc.correlation_id or f"c{tool_calls_count + 1}"
                yield RuntimeEvent.tool_call_started(
                    name=tc.name,
                    args=tc.args,
                    correlation_id=cid,
                )

                # Выполняем tool
                result = await self._executor.execute(tc.name, tc.args)

                # Проверяем ошибку в результате
                tool_ok = True
                try:
                    parsed = json.loads(result)
                    if isinstance(parsed, dict) and "error" in parsed:
                        tool_ok = False
                except (json.JSONDecodeError, TypeError):
                    pass

                yield RuntimeEvent.tool_call_finished(
                    name=tc.name,
                    correlation_id=cid,
                    ok=tool_ok,
                    result_summary=result[:200],
                )

                tool_calls_count += 1

                # Добавляем tool result в историю LLM
                new_messages.append(
                    Message(
                        role="assistant",
                        content=tc.assistant_message if hasattr(tc, "assistant_message") else "",
                        metadata={"tool_call": tc.name},
                    )
                )
                new_messages.append(
                    Message(
                        role="tool",
                        content=result,
                        name=tc.name,
                    )
                )
                lm_messages.append({"role": "assistant", "content": f"Вызываю {tc.name}"})
                lm_messages.append({"role": "user", "content": f"Результат {tc.name}: {result}"})

                if envelope.assistant_message:
                    yield RuntimeEvent.status(envelope.assistant_message)

                continue

            # --- final ---
            if envelope.type == "final" and envelope.final_message:
                text = envelope.final_message
                new_messages.append(Message(role="assistant", content=text))
                structured_output = extract_structured_output(text, config.output_format)

                yield RuntimeEvent.assistant_delta(text)
                yield RuntimeEvent.final(
                    text=text,
                    new_messages=new_messages,
                    metrics=self._build_metrics(
                        start_time,
                        config,
                        iterations,
                        tool_calls_count,
                    ),
                    structured_output=structured_output,
                )
                return

            # --- clarify ---
            if envelope.type == "clarify":
                text = envelope.assistant_message or "Уточните, пожалуйста."
                if envelope.questions:
                    qs = "\n".join(f"- {q.text}" for q in envelope.questions)
                    text = f"{text}\n\n{qs}"

                new_messages.append(Message(role="assistant", content=text))
                structured_output = extract_structured_output(text, config.output_format)
                yield RuntimeEvent.assistant_delta(text)
                yield RuntimeEvent.final(
                    text=text,
                    new_messages=new_messages,
                    metrics=self._build_metrics(
                        start_time,
                        config,
                        iterations,
                        tool_calls_count,
                    ),
                    structured_output=structured_output,
                )
                return

        # Loop limit reached
        yield RuntimeEvent.error(
            RuntimeErrorData(
                kind="loop_limit",
                message=f"Превышен лимит итераций ({config.max_iterations})",
                recoverable=False,
            )
        )

    # ------------------------------------------------------------------
    # Planner mode
    # ------------------------------------------------------------------

    async def _run_planner(
        self,
        messages: list[Message],
        system_prompt: str,
        tools: list[ToolSpec],
        config: RuntimeConfig,
        start_time: float,
    ) -> AsyncIterator[RuntimeEvent]:
        """Planner-lite: plan → step execution → final assembly."""
        # Шаг 1: получить план от LLM
        prompt = build_planner_prompt(system_prompt, tools)
        lm_messages = self._messages_to_lm(messages)

        raw = await self._llm_call(lm_messages, prompt)
        plan = self._parse_plan(raw)

        if plan is None:
            # Retry
            raw = await self._llm_call(lm_messages, prompt)
            plan = self._parse_plan(raw)

        if plan is None:
            yield RuntimeEvent.error(
                RuntimeErrorData(
                    kind="bad_model_output",
                    message="LLM не вернула валидный план после 2 попыток",
                    recoverable=False,
                )
            )
            return

        yield RuntimeEvent.status(f"План: {plan.goal} ({len(plan.steps)} шагов)")
        steps_preview = " -> ".join(
            f"{idx}. {step.title} [{step.mode}]"
            for idx, step in enumerate(plan.steps, start=1)
        )
        if steps_preview:
            yield RuntimeEvent.status(f"Следующие шаги: {steps_preview}")

        # Шаг 2: выполнить каждый шаг
        step_results: list[str] = []
        new_messages: list[Message] = []
        total_tool_calls = 0

        for idx, step in enumerate(plan.steps, start=1):
            yield RuntimeEvent.status(
                f"Шаг {idx}/{len(plan.steps)}: {step.title} (режим: {step.mode})"
            )

            step_context = "\n".join(step_results) if step_results else "Нет предыдущих шагов."

            # Формируем sub-config с бюджетами шага
            step_config = RuntimeConfig(
                runtime_name="thin",
                max_iterations=step.max_iterations,
                max_tool_calls=config.max_tool_calls - total_tool_calls,
                max_model_retries=config.max_model_retries,
                model=config.model,
            )

            step_text = ""

            if step.mode == "react":
                async for event in self._run_react(
                    messages,
                    system_prompt=build_plan_step_prompt(
                        system_prompt,
                        step.title,
                        step_context,
                        tools,
                    ),
                    tools=tools,
                    config=step_config,
                    start_time=start_time,
                ):
                    # Пробрасываем tool events
                    if event.type in ("tool_call_started", "tool_call_finished", "status"):
                        yield event
                    elif event.type == "final":
                        step_text = event.data.get("text", "")
                        total_tool_calls += event.data.get("metrics", {}).get("tool_calls_count", 0)
                    elif event.type == "error":
                        yield event
                        return
            else:
                # conversational sub-step
                async for event in self._run_conversational(
                    messages,
                    system_prompt=build_plan_step_prompt(
                        system_prompt,
                        step.title,
                        step_context,
                        [],
                    ),
                    config=step_config,
                    start_time=start_time,
                ):
                    if event.type == "final":
                        step_text = event.data.get("text", "")
                    elif event.type == "error":
                        yield event
                        return

            step_results.append(step_text)

        # Шаг 3: финальная сборка
        assembly_prompt = build_final_assembly_prompt(
            append_structured_output_instruction(
                system_prompt,
                config.output_format,
                final_response_field="final_message",
            ),
            plan.goal,
            step_results,
            plan.final_format,
        )
        raw = await self._llm_call(lm_messages, assembly_prompt)
        envelope = self._parse_envelope(raw)

        if envelope and envelope.type == "final" and envelope.final_message:
            final_text = envelope.final_message
        else:
            final_text = raw  # fallback

        new_messages.append(Message(role="assistant", content=final_text))
        structured_output = extract_structured_output(final_text, config.output_format)

        yield RuntimeEvent.assistant_delta(final_text)
        yield RuntimeEvent.final(
            text=final_text,
            new_messages=new_messages,
            metrics=self._build_metrics(
                start_time,
                config,
                iterations=len(plan.steps) + 2,  # plan + steps + assembly
                tool_calls=total_tool_calls,
            ),
            structured_output=structured_output,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_last_user_text(messages: list[Message]) -> str:
        """Извлечь текст последнего user message."""
        for msg in reversed(messages):
            if msg.role == "user" and msg.content:
                return msg.content
        return ""

    @staticmethod
    def _messages_to_lm(messages: list[Message]) -> list[dict[str, str]]:
        """Конвертировать Message → dict для LLM."""
        result = []
        for m in messages:
            d: dict[str, str] = {"role": m.role, "content": m.content}
            if m.name:
                d["name"] = m.name
            result.append(d)
        return result

    @staticmethod
    def _parse_envelope(raw: str) -> ActionEnvelope | None:
        """Парсить JSON ответ LLM в ActionEnvelope."""
        try:
            data = ThinRuntime._parse_json_dict(raw)
            if data is None:
                return None
            return ActionEnvelope.model_validate(data)
        except (json.JSONDecodeError, ValidationError):
            return None

    @staticmethod
    def _parse_plan(raw: str) -> PlanSchema | None:
        """Парсить JSON ответ LLM в PlanSchema."""
        try:
            data = ThinRuntime._parse_json_dict(raw)
            if data is None:
                return None
            return PlanSchema.model_validate(data)
        except (json.JSONDecodeError, ValidationError):
            return None

    @staticmethod
    def _strip_markdown_fences(raw: str) -> str:
        """Убрать markdown code fences, если ответ завернут в ```json ... ```."""
        cleaned = raw.strip()
        if not cleaned.startswith("```"):
            return cleaned

        lines = cleaned.split("\n")
        inner_lines: list[str] = []
        started = False
        for line in lines:
            if line.strip().startswith("```") and not started:
                started = True
                continue
            if line.strip() == "```" and started:
                break
            if started:
                inner_lines.append(line)
        return "\n".join(inner_lines).strip()

    @staticmethod
    def _extract_first_json_object(text: str) -> str | None:
        """Извлечь первый JSON-объект из произвольного текста.

        Полезно, когда модель добавляет пояснения до/после JSON.
        """
        start = text.find("{")
        if start == -1:
            return None

        depth = 0
        in_string = False
        escape = False
        for idx in range(start, len(text)):
            ch = text[idx]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : idx + 1]
        return None

    @staticmethod
    def _parse_json_dict(raw: str) -> dict[str, Any] | None:
        """Попробовать распарсить dict JSON из raw-ответа модели."""
        cleaned = ThinRuntime._strip_markdown_fences(raw)

        # 1) Пробуем как есть
        try:
            data = json.loads(cleaned)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

        # 2) Пробуем вырезать JSON из текста
        extracted = ThinRuntime._extract_first_json_object(cleaned)
        if not extracted:
            return None
        try:
            data = json.loads(extracted)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            return None
        return None

    @staticmethod
    def _extract_text_fallback(raw: str) -> str:
        """Сформировать безопасный текстовый fallback из raw-ответа LLM."""
        text = ThinRuntime._strip_markdown_fences(raw).strip()
        if not text:
            return ""
        # Если модель всё же вернула JSON-подобный ответ, это плохо читается пользователю.
        if text.startswith("{") and text.endswith("}"):
            return ""
        if len(text) > 2000:
            return f"{text[:2000]}..."
        return text

    @staticmethod
    def _build_metrics(
        start_time: float,
        config: RuntimeConfig,
        iterations: int = 0,
        tool_calls: int = 0,
    ) -> TurnMetrics:
        """Собрать метрики turn'а."""
        return TurnMetrics(
            latency_ms=int((time.monotonic() - start_time) * 1000),
            iterations=iterations,
            tool_calls_count=tool_calls,
            model=config.model,
        )

    async def _default_llm_call(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
    ) -> str:
        """Default LLM call через anthropic SDK.

        Модель берётся из self._config.model (настраивается через
        ANTHROPIC_MODEL env, CLI --model, или RuntimeConfig).
        Base URL берётся из self._config.base_url или ANTHROPIC_BASE_URL env
        (для OpenRouter, proxy и т.д.).
        """
        import logging
        import os

        logger = logging.getLogger(__name__)

        try:
            import anthropic
        except ImportError:
            return json.dumps(
                {
                    "type": "final",
                    "final_message": "anthropic SDK не установлен. Установите: pip install cognitia[thin]",
                }
            )

        # Base URL: config > env > стандартный Anthropic
        base_url = self._config.base_url or os.getenv("ANTHROPIC_BASE_URL", "").strip() or None

        client_kwargs: dict[str, Any] = {}
        if base_url:
            client_kwargs["base_url"] = base_url
            logger.info("LLM base_url: %s", base_url)

        client = anthropic.AsyncAnthropic(**client_kwargs)

        # Конвертируем messages (убираем system из списка)
        api_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in messages
            if m["role"] in ("user", "assistant")
        ]

        if not api_messages:
            api_messages = [{"role": "user", "content": "Привет"}]

        model = self._config.model
        logger.info("LLM запрос: model=%s, messages=%d", model, len(api_messages))

        try:
            response = await client.messages.create(
                model=model,
                max_tokens=4096,
                system=system_prompt,
                messages=api_messages,  # type: ignore[arg-type]
            )
        except anthropic.AuthenticationError as e:
            error_msg = (
                f"Ошибка аутентификации LLM API: {e}. "
                "Проверьте ANTHROPIC_API_KEY и ANTHROPIC_BASE_URL в .env"
            )
            logger.error(error_msg)
            return json.dumps({"type": "final", "final_message": error_msg})
        except anthropic.APIConnectionError as e:
            error_msg = f"Не удалось подключиться к LLM API: {e}"
            logger.error(error_msg)
            return json.dumps({"type": "final", "final_message": error_msg})
        except anthropic.APIStatusError as e:
            error_msg = f"Ошибка LLM API (status={e.status_code}): {e.message}"
            logger.error(error_msg)
            return json.dumps({"type": "final", "final_message": error_msg})
        except Exception as e:
            error_msg = f"Неожиданная ошибка LLM API: {type(e).__name__}: {e}"
            logger.error(error_msg, exc_info=True)
            return json.dumps({"type": "final", "final_message": error_msg})

        # Извлекаем текст из response
        text_parts = []
        for block in response.content:
            if hasattr(block, "text"):
                text_parts.append(block.text)

        logger.info(
            "LLM ответ: model=%s, tokens_in=%s, tokens_out=%s",
            getattr(response, "model", model),
            getattr(response.usage, "input_tokens", "?"),
            getattr(response.usage, "output_tokens", "?"),
        )
        return "".join(text_parts)

    async def cleanup(self) -> None:
        """Нечего очищать — stateless."""

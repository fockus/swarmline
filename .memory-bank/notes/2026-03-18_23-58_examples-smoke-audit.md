# Examples Smoke Audit

- Проверка examples должна идти не только по `exit=0`, но и по `stderr`: `01_agent_basics.py` раньше формально завершался успешно, но печатал auth traceback и пустые ответы.
- Для basics/example surface безопаснее иметь mock runtime по умолчанию и выносить live path за явный `--live`.
- После фикса `01_agent_basics.py` и добавления subprocess smoke test вся коллекция `examples/01-27` проходит без `stderr`.

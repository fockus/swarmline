# Agent Packs

Agent packs are portable prompt/resource bundles. They let applications keep
identity, guardrails, roles, skills, service prompts, rubrics, and examples in a
single manifest while Swarmline resolves the files safely.

```yaml
name: credit_report_agent
layers:
  identity: prompts/identity.md
  guardrails: prompts/guardrails.md
  role: prompts/roles/credit_advisor.md
  skill: skills/credit_analysis/INSTRUCTION.md
services:
  healing: prompts/credit_healing/system.md
  dashboard: prompts/credit_dashboard/system.md
resources:
  rubric: resources/rubric.md
```

```python
from swarmline import AgentPackResolver

pack = AgentPackResolver(project_root).load("agent_pack/credit_report_agent.yaml")

system_prompt = pack.render_prompt(service="healing")
rubric = pack.resources["rubric"].content
```

For backward compatibility, manifests may also use flat layer keys:

```yaml
name: credit_report_agent
identity: prompts/identity.md
guardrails: prompts/guardrails.md
role: prompts/roles/credit_advisor.md
skill: skills/credit_analysis/INSTRUCTION.md
services:
  healing: prompts/credit_healing/system.md
```

All paths are resolved relative to the pack root. Symlinks and paths outside the
root are rejected.

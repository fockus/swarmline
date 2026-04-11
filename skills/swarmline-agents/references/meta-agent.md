# Meta-Agent — Code Execution for Project Analysis

## Scenario
Use safe code execution to analyze a codebase: count lines by module, check dependency versions, find circular imports, and audit test coverage gaps.

## Steps

### 1. Count Lines of Code by Module
```
MCP tool: swarmline_exec_code
Input: {
  "code": "import os\nresults = {}\nfor root, dirs, files in os.walk('src/'):\n    dirs[:] = [d for d in dirs if d != '__pycache__']\n    module = root.replace('src/', '').split('/')[0] or 'root'\n    for f in files:\n        if f.endswith('.py'):\n            path = os.path.join(root, f)\n            with open(path) as fh:\n                results[module] = results.get(module, 0) + sum(1 for line in fh if line.strip())\nfor mod, count in sorted(results.items(), key=lambda x: -x[1]):\n    print(f'{mod}: {count} lines')",
  "timeout": 10
}
```

### 2. Check Dependency Versions Against Requirements
```
MCP tool: swarmline_exec_code
Input: {
  "code": "import importlib.metadata\nrequired = ['fastapi', 'sqlalchemy', 'pydantic', 'httpx', 'structlog']\nfor pkg in required:\n    try:\n        v = importlib.metadata.version(pkg)\n        print(f'{pkg}=={v}')\n    except importlib.metadata.PackageNotFoundError:\n        print(f'{pkg}: NOT INSTALLED')",
  "timeout": 5
}
```

### 3. Detect Circular Import Candidates
```
MCP tool: swarmline_exec_code
Input: {
  "code": "import ast, os\nimports = {}\nfor root, _, files in os.walk('src/'):\n    for f in files:\n        if not f.endswith('.py'): continue\n        path = os.path.join(root, f)\n        mod = path.replace('src/', '').replace('/', '.').replace('.py', '')\n        with open(path) as fh:\n            try:\n                tree = ast.parse(fh.read())\n            except SyntaxError:\n                continue\n        deps = set()\n        for node in ast.walk(tree):\n            if isinstance(node, ast.ImportFrom) and node.module:\n                deps.add(node.module.split('.')[0])\n        imports[mod] = deps\nfor mod, deps in imports.items():\n    for dep in deps:\n        if dep in imports and mod.split('.')[0] in imports.get(dep, set()):\n            print(f'Potential cycle: {mod} <-> {dep}')",
  "timeout": 10
}
```

### 4. Store Analysis Results
```
MCP tool: swarmline_memory_upsert_fact
Input: { "user_id": "project-health", "fact_key": "loc-analysis-2026-03-29", "fact_value": "Largest modules: auth (1200 lines), orders (800 lines), payments (650 lines). Orders is refactoring candidate." }
```

### 5. Find Test Coverage Gaps
```
MCP tool: swarmline_exec_code
Input: {
  "code": "import os\nsrc_modules = set()\nfor root, _, files in os.walk('src/'):\n    for f in files:\n        if f.endswith('.py') and f != '__init__.py':\n            src_modules.add(f.replace('.py', ''))\ntest_modules = set()\nfor root, _, files in os.walk('tests/'):\n    for f in files:\n        if f.startswith('test_') and f.endswith('.py'):\n            test_modules.add(f.replace('test_', '').replace('.py', ''))\nuntested = src_modules - test_modules\nfor m in sorted(untested):\n    print(f'No test file for: {m}')",
  "timeout": 5
}
```

## Result
A complete health report of the codebase: module sizes, dependency status, circular import risks, and test coverage gaps — all generated through safe code execution without leaving the agent session.

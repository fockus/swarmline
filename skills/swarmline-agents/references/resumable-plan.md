# Resumable Plan — Multi-Step Refactoring That Survives Interruption

## Scenario
Refactor a monolithic 800-line service into 4 focused modules. The plan tracks progress so work can resume from any point if the session is interrupted.

## Steps

### 1. Create the Refactoring Plan
```
MCP tool: swarmline_plan_create
Input: {
  "goal": "Split OrderService (800 lines) into 4 modules: validation, pricing, fulfillment, notifications",
  "steps": [
    "Extract OrderValidator class — move validate_order, check_inventory, validate_address (lines 45-180)",
    "Extract PricingEngine class — move calculate_total, apply_discounts, compute_tax (lines 181-340)",
    "Extract FulfillmentService class — move create_shipment, track_order, handle_return (lines 341-560)",
    "Extract NotificationService class — move send_confirmation, send_tracking, send_receipt (lines 561-720)",
    "Update OrderService to compose all 4 modules via dependency injection",
    "Update all imports across 12 dependent files",
    "Run full test suite and fix any breakage",
    "Delete dead code and unused imports from original file"
  ]
}
```

### 2. Approve the Plan
```
MCP tool: swarmline_plan_approve
Input: { "plan_id": "plan-1" }
```

### 3. Work Through Steps
Start step 1:
```
MCP tool: swarmline_plan_update_step
Input: { "plan_id": "plan-1", "step_index": 0, "status": "in_progress" }
```
After extracting OrderValidator:
```
MCP tool: swarmline_plan_update_step
Input: { "plan_id": "plan-1", "step_index": 0, "status": "done" }
```
Continue to step 2:
```
MCP tool: swarmline_plan_update_step
Input: { "plan_id": "plan-1", "step_index": 1, "status": "in_progress" }
```

### 4. Session Interrupted — Resume Later
In the new session, check plan state:
```
MCP tool: swarmline_plan_list
Input: {}
```
```
MCP tool: swarmline_plan_get
Input: { "plan_id": "plan-1" }
```
Response shows steps 0-1 done, step 2 in_progress. Resume from step 2 without re-doing completed work.

### 5. Complete Remaining Steps
Continue updating step statuses until all 8 steps are done. Final check:
```
MCP tool: swarmline_plan_get
Input: { "plan_id": "plan-1" }
```
All steps show "done" status.

## Result
An 800-line monolith becomes 4 focused modules (~150-200 lines each). Progress is tracked at every step. Interruption at any point loses zero completed work.

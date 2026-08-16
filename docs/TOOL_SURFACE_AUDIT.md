# Public MCP Tool-Surface Audit

**Why:** the 2026-08-08 field-test report (finding 4.4) observed the docs list
~25 tools while the live server exposes far more. Static count as of this audit:
**127 registered tools** (`scripts/listtools.py` regenerates the inventory).
The infra rule is that the public Parts MCP ships product capabilities only —
business operations belong in the partsd MCP.

Every tool below exists and is auth-gated at the API per its route; the
`admin_*` tools additionally carry `@require_role("owner")`. So none of this is
privilege escalation — it is surface area: a customer connector advertising
factory stations, sales commissions, and user administration reads wrong,
bloats tool-choice context for every agent session, and violates the
public-vs-partsd split.

## Classification

### Keep — product surface (≈97 tools; document these)

| Family | Tools |
|---|---|
| Search & sourcing | search_parts, search_by_parameters, search_by_marking, get_part_details, compare_prices, check_availability, find_alternatives, calculate_bom_cost |
| Datasheets | read_datasheet, list_datasheet_sections |
| Manufacturing & DFM | submit_dfm, pcb_fab_quote, check_dfm_status, check_bom_status, upload_bom, quote_fabrication, check_manufacturing_status, estimate_cost, check_identification_status, get_identified_item, identify_pcb, upload_gerbers_for_quote, quote_assembly, dfm_estimate/submit/check_status/add_findings/generate_report/deliver_report |
| EDA (KiCad/convert/CAD) | kicad (13), kicad_sch (7), kicad_ctrl (7), sch_repair (5), eda_export (2), cad (3) |
| Engineering change | ecn (5), eco (6) |
| Docs/renders/misc | render (2), doc_safelist (4), docs, cli, project, wip (4), design_pipeline (3) |
| Account (self-service) | user_profile, get_preferences, set_preferences, list_devices |

### Decide — internal ops stations exposed to customers (28 tools)

These model **our** factory/business workflow stations, not customer product
features. Recommendation per family:

| Family | Tools | Recommendation |
|---|---|---|
| sales_pipeline (5) | sales_quote_build, sales_quote_negotiate, sales_order_convert, **sales_invoice_generate**, **sales_commission_calculate** | **Move to partsd MCP.** Invoicing and commissions are business ops by the CLAUDE.md rule — hard requirement, not taste. The two quote tools could survive as product if reframed, but they read as internal sales tooling. |
| logistics_pipeline (5) | create_shipment, track_shipment, customs_declare, consignment_manifest, inventory_reconcile | **Move.** Shipment creation, customs declarations, and inventory reconciliation are our 3PL operations. Customer-facing tracking could return later as a narrow `order_track` tool. |
| supply_chain_pipeline (3) | procurement_approve, avl_qualify, obsolescence_check | **Move** procurement_approve (approval workflows are internal). avl_qualify / obsolescence_check are defensible product analytics — judgment call. |
| assembly_pipeline (5) | readiness_check, feeder_setup, reflow_profile, aoi_inspect, functional_test | **Move or owner-gate.** Feeder setup and AOI are factory stations. |
| quality_pipeline (4) | iqc_inspect, xray_analyze, fai_inspect, compliance_check | **Move or owner-gate.** IQC/FAI are our inbound QC stations. |
| test_pipeline (6) | coverage_analysis, provision_devices, reliability_predict, rma_process, failure_analysis, eco_feedback | Mixed: rma_process is arguably customer-facing (initiating an RMA); the rest are internal test stations. |

### Remove from public — admin (2 tools)

`admin_list_users`, `admin_set_user_role` — owner-gated, so exposure is
cosmetic-plus-context-cost rather than a hole, but user administration is the
canonical partsd-MCP citizen. No customer session can ever use them; they only
consume tool-list budget and signal internal reach.

## Mechanics of a move

The register functions are per-module, so relocation is cheap: drop the module
registration from `server.py` (public) and register it in the partsd MCP
instead, or gate registration on an `INTERNAL_TOOLS` env flag so one codebase
serves both surfaces. No API changes needed — the routes keep their own auth.

## Docs debt (finding 4.4 proper)

Whatever survives this audit should be enumerated in the docs hub — the ~25
documented vs 127 live gap stands regardless of where the line is drawn.

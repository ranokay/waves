# Code-review graph

Read before reviewing changes or tracing impact. Narrow scope with the graph
first, then verify in the source. Documentation-only edits do not require code
graph analysis. Locating code goes faster with `rg` and source reads.

## Procedure

1. Check `list_graph_stats_tool`. If `head_matches_build` is false, run
   `mise run graph` and check freshness again. A server started with
   `--auto-watch` re-indexes files as they change; semantic search is
   keyword fallback until embeddings are intentionally generated.
2. Choose the tools for the task below. For changes, account for affected
   callers, execution flows, and tests before concluding.
3. Read the relevant implementation and tests. Verify exact source for
   behavior, database logic, migrations, retries, fallbacks, recovery, and
   compatibility changes. Source takes precedence over graph output.

If graph tools are unavailable, narrow with `rg` and source reads. An empty
graph result can mean unindexed or dynamically connected code; it is not
evidence of absence. Python and QML relationships may require source tracing.

## Choose tools

| Task                           | Tools                                                                |
| ------------------------------ | -------------------------------------------------------------------- |
| Locate code                    | `semantic_search_nodes_tool` or `query_graph_tool`                   |
| Trace relationships            | `query_graph_tool` with `callers_of`, `callees_of`, or `imports_of`  |
| Review changes                 | `detect_changes_tool`; `get_review_context_tool` for source snippets |
| Trace impact                   | `get_impact_radius_tool` and `get_affected_flows_tool`               |
| Find coverage                  | `query_graph_tool` with pattern `tests_for`                          |
| Understand architecture        | `get_architecture_overview_tool` and `list_communities_tool`         |
| Plan renames or find dead code | `refactor_tool`                                                      |

-- Reproduce the Rapid-003 parent dispositions and final exposed screen.
-- Run read-only against the attested .trading-lab/rapid-research.sqlite3 database.

CREATE TEMP VIEW rapid003_fixed_blocks AS
SELECT
    column1 AS block_id,
    column2 AS start_timestamp,
    column3 AS end_timestamp,
    column4 AS benchmark_run_id,
    column5 AS benchmark_return
FROM (
    VALUES
        (
            'block-1',
            '2020-07-27T00:00:00Z',
            '2022-07-25T00:00:00Z',
            'rr-3fd6781408bf2d5f16cc',
            0.046747709544293819443509323
        ),
        (
            'block-2',
            '2022-07-26T00:00:00Z',
            '2024-07-26T00:00:00Z',
            'rr-54b94640d00031b7e1b8',
            0.285767268353344194769191055
        ),
        (
            'block-3',
            '2024-07-29T00:00:00Z',
            '2026-07-31T00:00:00Z',
            'rr-96d485058dd096e3aa2f',
            0.369598860728034231732375059
        )
);

CREATE TEMP VIEW rapid003_fixed_rows AS
SELECT
    runs.*,
    blocks.block_id,
    blocks.benchmark_return,
    CAST(json_extract(runs.metrics_json, '$.total_return') AS REAL) AS candidate_return,
    CAST(json_extract(runs.metrics_json, '$.sharpe_ratio') AS REAL) AS sharpe_ratio,
    CAST(json_extract(runs.metrics_json, '$.max_drawdown') AS REAL) AS max_drawdown,
    CAST(json_extract(runs.metrics_json, '$.average_gross_exposure') AS REAL)
        AS average_gross_exposure,
    CAST(json_extract(runs.metrics_json, '$.top_5_session_profit_share') AS REAL)
        AS top_5_session_profit_share,
    CAST(json_extract(runs.metrics_json, '$.top_instrument_profit_share') AS REAL)
        AS top_instrument_profit_share,
    CAST(json_extract(runs.metrics_json, '$.turnover') AS REAL) AS turnover,
    CAST(json_extract(runs.metrics_json, '$.trade_count') AS INTEGER) AS trade_count
FROM rapid_runs AS runs
JOIN rapid003_fixed_blocks AS blocks
    USING (start_timestamp, end_timestamp)
WHERE runs.status = 'completed'
  AND runs.run_type = 'backtest'
  AND runs.parent_run_id IS NULL
  AND runs.slippage_bps = '5'
  AND runs.commission_bps = '1'
  AND runs.fill_delay_bars = 1
  AND runs.code_dirty = 0;

CREATE TEMP VIEW rapid003_identity_metrics AS
SELECT
    strategy_name,
    parameters_json,
    code_commit,
    COUNT(*) AS block_count,
    SUM(candidate_return > 0) AS positive_block_count,
    SUM(candidate_return > benchmark_return) AS fixed_weight_win_count,
    MIN(candidate_return) AS worst_validation_return,
    MIN(sharpe_ratio) AS worst_validation_sharpe,
    MAX(max_drawdown) AS max_validation_drawdown,
    MAX(average_gross_exposure) AS max_average_gross_exposure,
    MAX(top_5_session_profit_share) AS max_top_5_session_profit_share,
    MAX(top_instrument_profit_share) AS max_top_instrument_profit_share,
    MAX(turnover) AS max_turnover,
    SUM(trade_count) AS total_validation_trade_count
FROM rapid003_fixed_rows
GROUP BY strategy_name, parameters_json, code_commit;

CREATE TEMP VIEW rapid003_identities AS
SELECT
    metrics.*,
    CASE
        WHEN block_count = 3
         AND positive_block_count = 3
         AND fixed_weight_win_count >= 2
         AND worst_validation_return >= 0
         AND worst_validation_sharpe >= 0.5
         AND max_validation_drawdown <= 0.20
         AND max_average_gross_exposure <= 1
         AND max_top_5_session_profit_share <= 0.25
         AND max_top_instrument_profit_share <= 0.50
         AND max_turnover <= 30
         AND total_validation_trade_count >= 100
        THEN 1
        ELSE 0
    END AS visible_base_pass
FROM rapid003_identity_metrics AS metrics
WHERE block_count = 3;

CREATE TEMP VIEW rapid003_neighbor_identities AS
SELECT
    base.strategy_name,
    base.parameters_json AS base_parameters_json,
    base.code_commit,
    neighbor.parameters_json AS neighbor_parameters_json
FROM rapid003_identities AS base
JOIN rapid003_identities AS neighbor
  ON neighbor.strategy_name = base.strategy_name
 AND neighbor.code_commit = base.code_commit
 AND neighbor.parameters_json <> base.parameters_json
WHERE base.visible_base_pass = 1
  AND (
        (
            json_extract(base.parameters_json, '$.short_lookback') <>
            json_extract(neighbor.parameters_json, '$.short_lookback')
        ) +
        (
            json_extract(base.parameters_json, '$.long_lookback') <>
            json_extract(neighbor.parameters_json, '$.long_lookback')
        ) +
        (
            json_extract(base.parameters_json, '$.selection_count') <>
            json_extract(neighbor.parameters_json, '$.selection_count')
        ) +
        (
            json_extract(base.parameters_json, '$.rebalance_every') <>
            json_extract(neighbor.parameters_json, '$.rebalance_every')
        )
      ) = 1;

CREATE TEMP VIEW rapid003_neighbor_retentions AS
SELECT
    neighbors.strategy_name,
    neighbors.base_parameters_json,
    neighbors.code_commit,
    neighbors.neighbor_parameters_json,
    base.block_id,
    base.run_id AS base_run_id,
    neighbor.run_id AS neighbor_run_id,
    neighbor.candidate_return / base.candidate_return AS return_retention
FROM rapid003_neighbor_identities AS neighbors
JOIN rapid003_fixed_rows AS base
  ON base.strategy_name = neighbors.strategy_name
 AND base.parameters_json = neighbors.base_parameters_json
 AND base.code_commit = neighbors.code_commit
JOIN rapid003_fixed_rows AS neighbor
  ON neighbor.strategy_name = neighbors.strategy_name
 AND neighbor.parameters_json = neighbors.neighbor_parameters_json
 AND neighbor.code_commit = neighbors.code_commit
 AND neighbor.block_id = base.block_id;

CREATE TEMP VIEW rapid003_neighbor_summary AS
SELECT
    strategy_name,
    base_parameters_json,
    code_commit,
    COUNT(DISTINCT neighbor_parameters_json) AS neighbor_identity_count,
    MIN(return_retention) AS minimum_neighbor_return_retention,
    CASE WHEN MIN(return_retention) >= 0.50 THEN 1 ELSE 0 END AS neighbor_pass
FROM rapid003_neighbor_retentions
GROUP BY strategy_name, base_parameters_json, code_commit;

CREATE TEMP VIEW rapid003_minimum_neighbor_rows AS
SELECT *
FROM (
    SELECT
        retentions.*,
        ROW_NUMBER() OVER (
            PARTITION BY strategy_name, base_parameters_json, code_commit
            ORDER BY return_retention, neighbor_run_id
        ) AS rank
    FROM rapid003_neighbor_retentions AS retentions
)
WHERE rank = 1;

CREATE TEMP VIEW rapid003_parent_dispositions AS
SELECT
    runs.run_id,
    runs.strategy_name,
    runs.parameters_json,
    runs.run_type,
    CASE
        WHEN runs.strategy_name IN (
            'cash', 'buy-and-hold', 'fixed-weight', 'strategic-allocation'
        ) THEN 'reference'
        WHEN fixed.block_id IS NOT NULL
         AND identities.visible_base_pass = 1
         AND neighbor_membership.neighbor_parameters_json IS NOT NULL
            THEN 'visible-base-and-parameter-neighbor-evidence'
        WHEN fixed.block_id IS NOT NULL
         AND identities.visible_base_pass = 1
            THEN 'visible-base-evidence'
        WHEN fixed.block_id IS NOT NULL
         AND neighbor_membership.neighbor_parameters_json IS NOT NULL
            THEN 'parameter-neighbor-evidence'
        WHEN fixed.block_id IS NOT NULL THEN 'visible-base-evidence'
        WHEN runs.run_type = 'walk-forward' THEN 'walk-forward-evidence'
        ELSE 'discovery-evidence'
    END AS stage,
    CASE
        WHEN runs.strategy_name IN (
            'cash', 'buy-and-hold', 'fixed-weight', 'strategic-allocation'
        ) THEN 'noncandidate-reference'
        WHEN identities.visible_base_pass = 1
         AND neighbor_summary.neighbor_pass = 0
            THEN 'visible-base-pass-parameter-neighbor-fail'
        WHEN identities.visible_base_pass = 1
         AND neighbor_summary.neighbor_pass = 1
            THEN 'parameter-neighbor-pass-await-execution-stress'
        WHEN identities.strategy_name IS NOT NULL THEN 'visible-base-fail'
        ELSE 'family-rejected-before-visible-base'
    END AS outcome
FROM rapid_runs AS runs
LEFT JOIN rapid003_fixed_blocks AS fixed
  ON fixed.start_timestamp = runs.start_timestamp
 AND fixed.end_timestamp = runs.end_timestamp
LEFT JOIN rapid003_identities AS identities
  ON identities.strategy_name = runs.strategy_name
 AND identities.parameters_json = runs.parameters_json
 AND identities.code_commit = runs.code_commit
LEFT JOIN rapid003_neighbor_summary AS neighbor_summary
  ON neighbor_summary.strategy_name = runs.strategy_name
 AND neighbor_summary.base_parameters_json = runs.parameters_json
 AND neighbor_summary.code_commit = runs.code_commit
LEFT JOIN (
    SELECT DISTINCT
        strategy_name,
        neighbor_parameters_json,
        code_commit
    FROM rapid003_neighbor_identities
) AS neighbor_membership
  ON neighbor_membership.strategy_name = runs.strategy_name
 AND neighbor_membership.neighbor_parameters_json = runs.parameters_json
 AND neighbor_membership.code_commit = runs.code_commit
WHERE runs.parent_run_id IS NULL
  AND runs.run_type <> 'stress';

-- Every one of the 1,219 parent configurations receives a stage and outcome.
SELECT *
FROM rapid003_parent_dispositions
ORDER BY run_id;

-- Expected summary: 1,219 parents, 84 complete fixed-block identities,
-- five visible-base passes, zero neighbor survivors, and zero stress entrants.
SELECT
    (SELECT COUNT(*) FROM rapid003_parent_dispositions) AS parent_configuration_count,
    (SELECT COUNT(*) FROM rapid003_fixed_rows) AS fixed_block_row_count,
    (SELECT COUNT(*) FROM rapid003_identities) AS complete_fixed_identity_count,
    (
        SELECT COUNT(*)
        FROM rapid003_identities
        WHERE visible_base_pass = 1
    ) AS visible_base_pass_count,
    (
        SELECT COUNT(*)
        FROM rapid003_neighbor_summary
        WHERE neighbor_pass = 1
    ) AS parameter_neighbor_pass_count,
    (
        SELECT COUNT(*)
        FROM rapid003_neighbor_summary
        WHERE neighbor_pass = 1
    ) AS execution_stress_entrant_count;

-- Exact five visible-base passes and their decisive neighbor evidence.
SELECT
    identities.strategy_name,
    identities.parameters_json,
    identities.code_commit,
    summary.neighbor_identity_count,
    summary.minimum_neighbor_return_retention,
    minimum.neighbor_parameters_json,
    minimum.block_id,
    minimum.base_run_id,
    minimum.neighbor_run_id
FROM rapid003_identities AS identities
JOIN rapid003_neighbor_summary AS summary
  ON summary.strategy_name = identities.strategy_name
 AND summary.base_parameters_json = identities.parameters_json
 AND summary.code_commit = identities.code_commit
JOIN rapid003_minimum_neighbor_rows AS minimum
  ON minimum.strategy_name = identities.strategy_name
 AND minimum.base_parameters_json = identities.parameters_json
 AND minimum.code_commit = identities.code_commit
WHERE identities.visible_base_pass = 1
ORDER BY identities.strategy_name, identities.parameters_json;

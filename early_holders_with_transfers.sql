-- Early Token Holders Analysis with Transfer Tracking
-- Tracks first 15 days buyers ($200+) including transfers to other wallets

WITH token_meta AS (
    SELECT 
        start_date, 
        total_supply, 
        symbol,
        start_date + INTERVAL '15' DAY as early_cutoff_date
    FROM dune.latecapdao.result_metadata_matview
    WHERE token_address = '{{Contract Address}}'
),

-- Find all early period activity (buys and sells) in first 15 days
early_period_activity AS (
    SELECT 
        trader_id,
        block_time,
        CASE 
            WHEN token_bought_mint_address = '{{Contract Address}}' THEN token_bought_amount
            ELSE 0
        END as tokens_bought,
        CASE 
            WHEN token_sold_mint_address = '{{Contract Address}}' THEN token_sold_amount
            ELSE 0
        END as tokens_sold,
        CASE 
            WHEN token_bought_mint_address = '{{Contract Address}}' THEN amount_usd
            ELSE 0
        END as usd_spent,
        CASE 
            WHEN token_sold_mint_address = '{{Contract Address}}' THEN amount_usd
            ELSE 0
        END as usd_received
    FROM dex_solana.trades
    WHERE (token_bought_mint_address = '{{Contract Address}}'
           OR token_sold_mint_address = '{{Contract Address}}')
        AND block_time >= (SELECT start_date FROM token_meta)
        AND block_time <= (SELECT early_cutoff_date FROM token_meta)
        AND amount_usd > 0
),

-- Calculate early buyers with net positions
early_buyers AS (
    SELECT 
        trader_id as address,
        MIN(CASE WHEN tokens_bought > 0 THEN block_time END) as first_buy_time,
        SUM(tokens_bought) as total_tokens_bought_early,
        SUM(tokens_sold) as total_tokens_sold_early,
        SUM(tokens_bought) - SUM(tokens_sold) as net_tokens_early,
        SUM(usd_spent) as total_usd_spent_early,
        SUM(usd_received) as total_usd_received_early,
        SUM(usd_spent) - SUM(usd_received) as net_usd_spent_early,
        COUNT(CASE WHEN tokens_bought > 0 THEN 1 END) as early_buy_count,
        COUNT(CASE WHEN tokens_sold > 0 THEN 1 END) as early_sell_count,
        AVG(CASE WHEN tokens_bought > 0 THEN usd_spent/NULLIF(tokens_bought, 0) END) as avg_early_price
    FROM early_period_activity
    GROUP BY trader_id
    HAVING SUM(usd_spent) >= 200  -- Must have spent at least $200 buying in early period
        AND SUM(tokens_bought) - SUM(tokens_sold) > 0  -- Must have net positive position from early period
),

-- Track token transfers OUT from early buyers
transfers_out AS (
    SELECT 
        from_owner as address,
        SUM(amount) as total_transferred_out,
        COUNT(*) as transfer_out_count,
        COUNT(DISTINCT to_owner) as unique_recipients,
        ARRAY_AGG(DISTINCT to_owner) as recipient_addresses,
        MIN(block_time) as first_transfer_time,
        MAX(block_time) as last_transfer_time
    FROM tokens_solana.transfers
    WHERE token_mint_address = '{{Contract Address}}'
        AND from_owner IN (SELECT address FROM early_buyers)
        AND block_time >= (SELECT start_date FROM token_meta)
        AND amount > 0
        AND action = 'transfer'  -- Only actual transfers, not mints/burns
    GROUP BY from_owner
),

-- Track token transfers IN to early buyers (in case they received from other wallets)
transfers_in AS (
    SELECT 
        to_owner as address,
        SUM(amount) as total_transferred_in,
        COUNT(*) as transfer_in_count,
        COUNT(DISTINCT from_owner) as unique_senders,
        MIN(block_time) as first_received_time,
        MAX(block_time) as last_received_time
    FROM tokens_solana.transfers
    WHERE token_mint_address = '{{Contract Address}}'
        AND to_owner IN (SELECT address FROM early_buyers)
        AND block_time >= (SELECT start_date FROM token_meta)
        AND amount > 0
        AND action = 'transfer'  -- Only actual transfers, not mints/burns
    GROUP BY to_owner
),

-- Get complete trading history for early buyers
complete_trading_history AS (
    SELECT 
        trader_id,
        block_time,
        CASE 
            WHEN token_bought_mint_address = '{{Contract Address}}' THEN token_bought_amount
            ELSE 0
        END as tokens_bought,
        CASE 
            WHEN token_sold_mint_address = '{{Contract Address}}' THEN token_sold_amount
            ELSE 0
        END as tokens_sold,
        CASE 
            WHEN token_bought_mint_address = '{{Contract Address}}' THEN amount_usd
            ELSE 0
        END as usd_bought,
        CASE 
            WHEN token_sold_mint_address = '{{Contract Address}}' THEN amount_usd
            ELSE 0
        END as usd_sold
    FROM dex_solana.trades
    WHERE (token_bought_mint_address = '{{Contract Address}}'
           OR token_sold_mint_address = '{{Contract Address}}')
        AND trader_id IN (SELECT address FROM early_buyers)
        AND block_time >= (SELECT start_date FROM token_meta)
),

-- Calculate lifetime totals for each early buyer
lifetime_totals AS (
    SELECT 
        trader_id,
        SUM(tokens_bought) as lifetime_tokens_bought,
        SUM(tokens_sold) as lifetime_tokens_sold,
        SUM(tokens_bought) - SUM(tokens_sold) as net_tokens_held,
        SUM(usd_bought) as lifetime_usd_bought,
        SUM(usd_sold) as lifetime_usd_sold,
        SUM(usd_sold) - SUM(usd_bought) as net_usd_pnl,
        COUNT(CASE WHEN tokens_bought > 0 THEN 1 END) as total_buy_transactions,
        COUNT(CASE WHEN tokens_sold > 0 THEN 1 END) as total_sell_transactions
    FROM complete_trading_history
    GROUP BY trader_id
),

-- Get current balances
current_balances AS (
    SELECT 
        token_balance_owner as address,
        token_balance as current_balance
    FROM solana_utils.latest_balances
    WHERE token_mint_address = '{{Contract Address}}'
        AND token_balance_owner IN (SELECT address FROM early_buyers)
),

-- Calculate post-early-period activity
post_early_activity AS (
    SELECT 
        trader_id,
        SUM(tokens_bought) as tokens_bought_after_early,
        SUM(tokens_sold) as tokens_sold_after_early,
        SUM(usd_bought) as usd_spent_after_early,
        SUM(usd_sold) as usd_received_after_early,
        COUNT(CASE WHEN tokens_bought > 0 THEN 1 END) as buy_count_after_early,
        COUNT(CASE WHEN tokens_sold > 0 THEN 1 END) as sell_count_after_early
    FROM complete_trading_history
    WHERE block_time > (SELECT early_cutoff_date FROM token_meta)
    GROUP BY trader_id
),

-- Main analysis combining all data including transfers
main_analysis AS (
    SELECT 
        eb.address,
        eb.first_buy_time,
        eb.total_tokens_bought_early,
        eb.total_tokens_sold_early,
        eb.net_tokens_early,
        eb.total_usd_spent_early,
        eb.total_usd_received_early,
        eb.net_usd_spent_early,
        eb.early_buy_count,
        eb.early_sell_count,
        eb.avg_early_price,
        
        -- Current holdings
        COALESCE(cb.current_balance, 0) as current_balance,
        
        -- Transfer data
        COALESCE(tout.total_transferred_out, 0) as total_transferred_out,
        COALESCE(tout.transfer_out_count, 0) as transfer_out_count,
        COALESCE(tout.unique_recipients, 0) as unique_recipients,
        tout.recipient_addresses,
        tout.first_transfer_time,
        tout.last_transfer_time,
        
        COALESCE(tin.total_transferred_in, 0) as total_transferred_in,
        COALESCE(tin.transfer_in_count, 0) as transfer_in_count,
        
        -- Net transfer position (safe subtraction)
        CASE 
            WHEN COALESCE(tin.total_transferred_in, 0) >= COALESCE(tout.total_transferred_out, 0) 
            THEN COALESCE(tin.total_transferred_in, 0) - COALESCE(tout.total_transferred_out, 0)
            ELSE -(COALESCE(tout.total_transferred_out, 0) - COALESCE(tin.total_transferred_in, 0))
        END as net_transfers,
        
        -- Calculate expected vs actual balance (safe subtraction)
        CASE 
            WHEN lt.net_tokens_held + COALESCE(tin.total_transferred_in, 0) >= COALESCE(tout.total_transferred_out, 0)
            THEN lt.net_tokens_held + COALESCE(tin.total_transferred_in, 0) - COALESCE(tout.total_transferred_out, 0)
            ELSE 0
        END as expected_balance,
        
        -- Lifetime totals
        lt.lifetime_tokens_bought,
        lt.lifetime_tokens_sold,
        lt.net_tokens_held,
        lt.lifetime_usd_bought,
        lt.lifetime_usd_sold,
        lt.net_usd_pnl,
        lt.total_buy_transactions,
        lt.total_sell_transactions,
        
        -- Post-early period activity
        COALESCE(pea.tokens_bought_after_early, 0) as tokens_bought_after_early,
        COALESCE(pea.tokens_sold_after_early, 0) as tokens_sold_after_early,
        COALESCE(pea.usd_spent_after_early, 0) as usd_spent_after_early,
        COALESCE(pea.usd_received_after_early, 0) as usd_received_after_early,
        COALESCE(pea.buy_count_after_early, 0) as buy_count_after_early,
        COALESCE(pea.sell_count_after_early, 0) as sell_count_after_early,
        
        -- Supply percentages (based on net early position)
        eb.net_tokens_early / tm.total_supply * 100 as early_supply_percentage,
        COALESCE(cb.current_balance, 0) / tm.total_supply * 100 as current_supply_percentage,
        
        -- Transfer percentage of holdings (safe division)
        CASE 
            WHEN lt.net_tokens_held <= 0 THEN 0
            WHEN COALESCE(tout.total_transferred_out, 0) = 0 THEN 0
            ELSE CAST(COALESCE(tout.total_transferred_out, 0) AS DOUBLE) / CAST(NULLIF(ABS(lt.net_tokens_held), 0) AS DOUBLE) * 100
        END as transfer_percentage,
        
        -- Retention calculations (based on net early position)
        CASE 
            WHEN eb.net_tokens_early = 0 THEN 0
            ELSE COALESCE(cb.current_balance, 0) / eb.net_tokens_early * 100
        END as token_retention_percentage,
        
        -- Enhanced categorize behavior (accounting for transfers)
        CASE 
            WHEN COALESCE(cb.current_balance, 0) = 0 AND lt.total_sell_transactions = 0 AND COALESCE(tout.total_transferred_out, 0) > 0 THEN 'TRANSFERRED_OUT'
            WHEN COALESCE(cb.current_balance, 0) = 0 AND lt.total_sell_transactions > 0 THEN 'SOLD_ALL'
            WHEN COALESCE(cb.current_balance, 0) = 0 AND lt.total_sell_transactions = 0 AND COALESCE(tout.total_transferred_out, 0) = 0 THEN 'MISSING_TOKENS'
            WHEN lt.net_tokens_held > 0 AND COALESCE(tout.total_transferred_out, 0) > lt.net_tokens_held * 0.5 THEN 'MAJOR_TRANSFER'
            WHEN COALESCE(cb.current_balance, 0) >= eb.net_tokens_early * 0.9 THEN 'HOLDING_90_PLUS'
            WHEN COALESCE(cb.current_balance, 0) >= eb.net_tokens_early * 0.5 THEN 'HOLDING_50_TO_90'
            WHEN COALESCE(cb.current_balance, 0) >= eb.net_tokens_early * 0.1 THEN 'HOLDING_10_TO_50'
            ELSE 'HOLDING_UNDER_10'
        END as holding_category,
        
        tm.total_supply,
        tm.symbol
        
    FROM early_buyers eb
    CROSS JOIN token_meta tm
    LEFT JOIN current_balances cb ON eb.address = cb.address
    LEFT JOIN lifetime_totals lt ON eb.address = lt.trader_id
    LEFT JOIN post_early_activity pea ON eb.address = pea.trader_id
    LEFT JOIN transfers_out tout ON eb.address = tout.address
    LEFT JOIN transfers_in tin ON eb.address = tin.address
)

-- Final output with transfer analysis
SELECT 
    address,
    symbol,
    first_buy_time,
    
    -- Early purchase details (with net calculations)
    ROUND(total_tokens_bought_early, 2) as early_tokens_bought,
    ROUND(total_tokens_sold_early, 2) as early_tokens_sold,
    ROUND(net_tokens_early, 2) as net_early_tokens,
    ROUND(total_usd_spent_early, 2) as early_usd_spent,
    ROUND(total_usd_received_early, 2) as early_usd_received,
    ROUND(net_usd_spent_early, 2) as net_early_usd_spent,
    ROUND(avg_early_price, 8) as avg_early_price,
    ROUND(early_supply_percentage, 4) as early_supply_pct,
    early_buy_count,
    early_sell_count,
    
    -- Current position
    ROUND(current_balance, 2) as current_tokens,
    ROUND(current_supply_percentage, 4) as current_supply_pct,
    ROUND(token_retention_percentage, 2) as retention_pct,
    
    -- Transfer analysis
    ROUND(total_transferred_out, 2) as tokens_transferred_out,
    ROUND(total_transferred_in, 2) as tokens_transferred_in,
    ROUND(net_transfers, 2) as net_transfers,
    ROUND(transfer_percentage, 2) as transfer_pct_of_holdings,
    transfer_out_count,
    transfer_in_count,
    unique_recipients,
    recipient_addresses,
    first_transfer_time,
    last_transfer_time,
    
    -- Balance reconciliation (safe subtraction)
    ROUND(expected_balance, 2) as expected_balance,
    CASE 
        WHEN expected_balance >= current_balance 
        THEN ROUND(expected_balance - current_balance, 2)
        ELSE ROUND(-(current_balance - expected_balance), 2)
    END as unaccounted_tokens,
    
    -- Trading activity summary
    total_buy_transactions,
    total_sell_transactions,
    buy_count_after_early,
    sell_count_after_early,
    
    -- PnL Analysis (realized only)
    ROUND(lifetime_usd_bought, 2) as total_usd_invested,
    ROUND(lifetime_usd_sold, 2) as total_usd_received,
    ROUND(net_usd_pnl, 2) as realized_pnl,
    
    holding_category

FROM main_analysis
ORDER BY early_supply_percentage DESC, net_early_usd_spent DESC
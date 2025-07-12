from collections import defaultdict
from datetime import datetime, timedelta
import logging
from typing import Dict, List, Set
from dune_client.query import QueryBase
from src.services.cache_service import CacheService
import asyncio
import json

logger = logging.getLogger(__name__)

class PatternDetector:
    def __init__(self, trader_profiles: Dict[str, dict], dune_client):
        self.trader_profiles = trader_profiles
        self.dune_client = dune_client
        self.cache = CacheService()
        self.token_metadata = {}  # Cache for token metadata
        
    async def get_token_metadata(self, token_address: str) -> dict:
        """Fetch token metadata from Dune materialized view"""
        if token_address not in self.token_metadata:
            try:
                # Create query for metadata materialized view
                query = QueryBase(
                    query_id=4554967  # Your metadata matview ID
                )

                # Get latest result with filtering for specific token
                df = await self.dune_client.get_latest_result_dataframe(
                    query=query,
                    filters=f"token_address='{token_address}'",
                    limit=1
                )

                if not df.empty:
                    metadata = df.iloc[0]
                    self.token_metadata[token_address] = {
                        'symbol': metadata.get('symbol'),
                        'total_supply': float(metadata.get('total_supply', 0)),
                        'last_updated': metadata.get('last_updated')
                    }

            except Exception as e:
                logger.error(f"Error fetching token metadata: {e}")
                
        return self.token_metadata.get(token_address, {})
        
    async def _get_recent_transactions(self, token_address: str, hours: int = 1) -> List[dict]:
        """Get recent transactions for a specific token from Redis"""
        cache_key = f"token_transactions:{token_address}"
        
        try:
            # Try to get from Redis LIST first (new atomic method)
            if hasattr(self.cache, 'redis') and self.cache.redis:
                list_key = f"{cache_key}:list"
                raw_transactions = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self.cache.redis.lrange(list_key, 0, -1)
                )
                
                if raw_transactions:
                    transactions = []
                    for raw_tx in raw_transactions:
                        try:
                            transactions.append(json.loads(raw_tx))
                        except json.JSONDecodeError:
                            continue
                else:
                    transactions = []
            else:
                # Fallback to old method
                transactions = await self.cache.get(cache_key) or []
                
        except Exception as e:
            logger.error(f"Error getting transactions from Redis LIST: {e}")
            # Fallback to old method
            transactions = await self.cache.get(cache_key) or []
        
        if not transactions:
            return []
            
        # Filter by time
        cutoff = datetime.now() - timedelta(hours=hours)
        return [
            tx for tx in transactions 
            if datetime.fromisoformat(tx['timestamp']) > cutoff
        ]
        
    async def _store_transaction(self, token_address: str, transaction: dict):
        """Store transaction for specific token in Redis with atomic operations"""
        cache_key = f"token_transactions:{token_address}"
        
        transaction_data = {
            'timestamp': datetime.now().isoformat(),
            'wallet': transaction['wallet'],
            'action': transaction['action'],
            'amount_usd': transaction['amount_usd'],
            'trader_type': transaction['trader_type'],
            'token_symbol': transaction.get('token_symbol', 'Unknown'),
            'market_cap': transaction.get('market_cap', 0)
        }
        
        try:
            # Use atomic Redis operations to avoid race conditions
            if hasattr(self.cache, 'redis') and self.cache.redis:
                # Use Redis LIST operations for atomic append
                list_key = f"{cache_key}:list"
                
                # Add new transaction atomically
                await asyncio.get_event_loop().run_in_executor(
                    None, 
                    lambda: self.cache.redis.lpush(list_key, json.dumps(transaction_data))
                )
                
                # Trim to keep only last 200 transactions atomically
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self.cache.redis.ltrim(list_key, 0, 199)
                )
                
                # Set expiration
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self.cache.redis.expire(list_key, 3600)  # 1 hour
                )
                
            else:
                # Fallback to non-atomic operations if Redis not available
                transactions = await self.cache.get(cache_key) or []
                transactions.append(transaction_data)
                
                # Keep only last 200 transactions per token
                if len(transactions) > 200:
                    transactions = transactions[-200:]
                
                # Store with 1h expiration
                await self.cache.set(cache_key, transactions, expire_minutes=60)
                
        except Exception as e:
            logger.error(f"Error storing transaction atomically: {e}")
            # Fallback to original method
            transactions = await self.cache.get(cache_key) or []
            transactions.append(transaction_data)
            if len(transactions) > 200:
                transactions = transactions[-200:]
            await self.cache.set(cache_key, transactions, expire_minutes=60)
        
    async def add_transaction(self, transaction: dict) -> List[str]:
        """Add transaction and return any detected confluence patterns for this specific token"""
        token_address = transaction['token_address']
        wallet = transaction['wallet_address']
        
        trader_type = self.trader_profiles.get(wallet, {}).get('category', 'Unknown')
        logger.info(f"Adding transaction: wallet={wallet[:8]}..., token={token_address[:8]}..., trader_type={trader_type}, action={'buy' if transaction['is_buy'] else 'sell'}")
        
        # Store transaction with token address as key
        await self._store_transaction(token_address, {
            'timestamp': datetime.now().isoformat(),
            'wallet': wallet,
            'action': 'buy' if transaction['is_buy'] else 'sell',
            'amount_usd': transaction['usd_value'],
            'trader_type': trader_type,
            'token_symbol': transaction.get('token_symbol', 'Unknown'),
            'market_cap': transaction.get('current_market_cap', 0)
        })
        
        # Check patterns for THIS SPECIFIC TOKEN only
        patterns = await self._check_patterns(token_address)
        logger.info(f"Pattern check result for {token_address[:8]}...: found {len(patterns)} patterns")
        return patterns
        
    async def _check_patterns(self, token_address: str) -> List[str]:
        """Check for confluence patterns for this specific token"""
        patterns = []
        
        # Get recent transactions for this specific token
        token_txs = await self._get_recent_transactions(token_address)
        logger.info(f"Token {token_address[:8]}... has {len(token_txs)} recent transactions")
        if not token_txs:
            return patterns
            
        token_symbol = token_txs[0].get('token_symbol', 'Unknown') if token_txs else 'Unknown'
        
        # Pattern 1: Multiple Alpha traders confluence on same token
        alpha_pattern = self._check_alpha_confluence(token_txs, token_symbol)
        if alpha_pattern:
            patterns.append(alpha_pattern)
            
        # Pattern 2: Alpha followed by other traders on same token
        sequence_pattern = self._check_sequence_pattern(token_txs, token_symbol)
        if sequence_pattern:
            patterns.append(sequence_pattern)
            
        # Pattern 3: Multiple trader types on same token
        diversity_pattern = self._check_diversity_pattern(token_txs, token_symbol)
        if diversity_pattern:
            patterns.append(diversity_pattern)
            
        return patterns
        
    def _check_alpha_confluence(self, transactions: List[dict], token_symbol: str) -> str:
        """Check for multiple Alpha traders acting on the SAME TOKEN (confluence)"""
        last_1_hour = datetime.now() - timedelta(hours=1)
        recent_txs = [
            tx for tx in transactions 
            if datetime.fromisoformat(tx['timestamp']) > last_1_hour
        ]
        
        logger.info(f"Checking alpha confluence for {token_symbol}: {len(transactions)} total txs, {len(recent_txs)} recent txs (1h)")
        
        # Log all recent transactions for debugging
        for tx in recent_txs:
            logger.info(f"  Recent tx: wallet={tx['wallet'][:8]}..., action={tx['action']}, trader_type={tx['trader_type']}")
        
        # Get unique alpha wallets by action - includes all trader types from new query
        alpha_trader_types = ['Insider', 'Alpha Trader', 'Volume Leader', 'Consistent Performer']
        
        alpha_buyers = set(
            tx['wallet'] for tx in recent_txs
            if tx['trader_type'] in alpha_trader_types and tx['action'] == 'buy'
        )
        
        alpha_sellers = set(
            tx['wallet'] for tx in recent_txs
            if tx['trader_type'] in alpha_trader_types and tx['action'] == 'sell'
        )
        
        logger.info(f"Alpha confluence check for {token_symbol}: {len(alpha_buyers)} buyers, {len(alpha_sellers)} sellers")
        
        # CONFLUENCE: Check for significant net flow in either direction
        logger.info(f"Alpha buyers for {token_symbol}: {alpha_buyers}, Alpha sellers: {alpha_sellers}")
        
        # Calculate buy and sell volumes
        buy_volume = sum(
            tx['amount_usd'] for tx in recent_txs
            if tx['trader_type'] in alpha_trader_types and tx['action'] == 'buy'
        )
        sell_volume = sum(
            tx['amount_usd'] for tx in recent_txs
            if tx['trader_type'] in alpha_trader_types and tx['action'] == 'sell'
        )
        
        # Calculate net flow (positive = net buying, negative = net selling)
        net_flow = buy_volume - sell_volume
        logger.info(f"Flow analysis for {token_symbol}: ${buy_volume:,.0f} buys, ${sell_volume:,.0f} sells, net: ${net_flow:,.0f}")
        logger.info(f"Buyer count: {len(alpha_buyers)}, Seller count: {len(alpha_sellers)}")
        
        # Debug: Log individual transactions for analysis
        for tx in recent_txs:
            if tx['trader_type'] in alpha_trader_types:
                logger.info(f"  {tx['action'].upper()}: ${tx['amount_usd']:,.0f} by {tx['wallet'][:8]}... ({tx['trader_type']})")
        
        # STRICTER CONFLUENCE THRESHOLDS to reduce noise by 80%:
        # 1. Market cap relative thresholds (smart scaling)
        # 2. Increased wallet requirements (3+ instead of 2+)
        
        # Calculate market cap relative threshold
        market_cap = recent_txs[0].get('market_cap', 0) if recent_txs else 0
        
        if market_cap > 0:
            if market_cap < 1_000_000:  # Under $1M mcap
                min_flow_threshold = max(2000, market_cap * 0.01)  # 1% of mcap, min $2K
            elif market_cap < 10_000_000:  # $1M-$10M mcap  
                min_flow_threshold = max(5000, market_cap * 0.005)  # 0.5% of mcap, min $5K
            else:  # Over $10M mcap
                min_flow_threshold = max(10000, market_cap * 0.003)  # 0.3% of mcap, min $10K
        else:
            min_flow_threshold = 5000  # Fallback if no market cap data
            
        logger.info(f"Confluence threshold for {token_symbol} (MCap: ${market_cap:,.0f}): ${min_flow_threshold:,.0f}")
        
        if abs(net_flow) >= min_flow_threshold:
            if net_flow > 0 and len(alpha_buyers) >= 3:
                # Net buying with multiple buyers
                wallet_previews = [f"{w[:4]}...{w[-4:]}" for w in list(alpha_buyers)[:3]]
                logger.info(f"✅ BUY CONFLUENCE TRIGGERED for {token_symbol}: {len(alpha_buyers)} buyers, net: ${net_flow:,.0f}")
                return f"🔥 {len(alpha_buyers)} Alpha wallets NET BUYING ${token_symbol} (${net_flow:,.0f} net)\n   Wallets: {', '.join(wallet_previews)}"
            elif net_flow < 0 and len(alpha_sellers) >= 3:
                # Net selling with multiple sellers - STRICTER: 3+ sellers required
                wallet_previews = [f"{w[:4]}...{w[-4:]}" for w in list(alpha_sellers)[:3]]
                logger.info(f"✅ SELL CONFLUENCE TRIGGERED for {token_symbol}: {len(alpha_sellers)} sellers, net: ${abs(net_flow):,.0f}")
                return f"🚨 {len(alpha_sellers)} Alpha wallets NET SELLING ${token_symbol} (${abs(net_flow):,.0f} net)\n   Wallets: {', '.join(wallet_previews)}"
            elif net_flow > 0:
                logger.warning(f"❌ BUY confluence FAILED for {token_symbol}: net_flow=${net_flow:,.0f} ✅ but only {len(alpha_buyers)} buyers (need 3+)")
            elif net_flow < 0:
                logger.warning(f"❌ SELL confluence FAILED for {token_symbol}: net_flow=${abs(net_flow):,.0f} ✅ but only {len(alpha_sellers)} sellers (need 3+)")
        else:
            if net_flow > 0:
                logger.info(f"❌ BUY confluence FAILED for {token_symbol}: net_flow=${net_flow:,.0f} below ${min_flow_threshold:,.0f} threshold (has {len(alpha_buyers)} buyers)")
            elif net_flow < 0:
                logger.info(f"❌ SELL confluence FAILED for {token_symbol}: net_flow=${abs(net_flow):,.0f} below ${min_flow_threshold:,.0f} threshold (has {len(alpha_sellers)} sellers)")
            else:
                logger.info(f"❌ No confluence for {token_symbol}: zero net flow")
            
        return None
        
    def _check_sequence_pattern(self, transactions: List[dict], token_symbol: str) -> str:
        """Check for Alpha traders followed by other trader types on SAME TOKEN"""
        alpha_trader_types = ['Insider', 'Alpha Trader', 'Volume Leader', 'Consistent Performer']
        
        last_2h = datetime.now() - timedelta(hours=2)
        recent_txs = [
            tx for tx in transactions 
            if datetime.fromisoformat(tx['timestamp']) > last_2h
        ]
        
        # Sort by timestamp to find sequence
        recent_txs.sort(key=lambda x: x['timestamp'])
        
        # Find first Alpha action
        alpha_action_time = None
        alpha_action_type = None
        
        for tx in recent_txs:
            if tx['trader_type'] in alpha_trader_types:
                alpha_action_time = tx['timestamp']
                alpha_action_type = tx['action']
                break
                
        if alpha_action_time:
            # Find followers doing same action on same token
            subsequent_actions = [
                tx for tx in recent_txs
                if (datetime.fromisoformat(tx['timestamp']) > 
                    datetime.fromisoformat(alpha_action_time) + timedelta(minutes=5))
                and tx['trader_type'] not in ['Alpha Traders', 'Alpha']
                and tx['action'] == alpha_action_type
            ]
            
            unique_followers = set(tx['wallet'] for tx in subsequent_actions)
            if len(unique_followers) >= 2:
                action_verb = 'buying' if alpha_action_type == 'buy' else 'selling'
                follower_types = set(tx['trader_type'] for tx in subsequent_actions)
                return f"👥 Alpha {action_verb} ${token_symbol} → {len(unique_followers)} followers\n   Types: {', '.join(follower_types)}"
                
        return None
        
    def _check_diversity_pattern(self, transactions: List[dict], token_symbol: str) -> str:
        """Check for diverse trader types activity on SAME TOKEN"""
        last_1h = datetime.now() - timedelta(hours=1)
        recent_txs = [
            tx for tx in transactions 
            if datetime.fromisoformat(tx['timestamp']) > last_1h
        ]
        
        # Group by action on same token
        buyers = [tx for tx in recent_txs if tx['action'] == 'buy']
        sellers = [tx for tx in recent_txs if tx['action'] == 'sell']
        
        buyer_types = set(tx['trader_type'] for tx in buyers)
        seller_types = set(tx['trader_type'] for tx in sellers)
        
        # Check for diverse buying on same token
        if len(buyer_types) >= 3:
            total_buy_volume = sum(tx['amount_usd'] for tx in buyers)
            unique_buyers = len(set(tx['wallet'] for tx in buyers))
            return f"🎆 {len(buyer_types)} trader types buying ${token_symbol}\n   {unique_buyers} wallets, ${total_buy_volume:,.0f} volume"
            
        # Check for diverse selling on same token
        if len(seller_types) >= 3:
            total_sell_volume = sum(tx['amount_usd'] for tx in sellers)
            unique_sellers = len(set(tx['wallet'] for tx in sellers))
            return f"📉 {len(seller_types)} trader types selling ${token_symbol}\n   {unique_sellers} wallets, ${total_sell_volume:,.0f} volume"
            
        return None 
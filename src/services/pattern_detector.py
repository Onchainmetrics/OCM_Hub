from collections import defaultdict
from datetime import datetime, timedelta
import logging
from typing import Dict, List, Set
from dune_client.query import QueryBase
from src.services.cache_service import CacheService

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
        
    async def _get_recent_transactions(self, token: str, hours: int = 4) -> List[dict]:
        """Get recent transactions from Redis"""
        cache_key = f"transactions:{token}"
        transactions = await self.cache.get(cache_key)
        
        if not transactions:
            return []
            
        # Filter by time
        cutoff = datetime.now() - timedelta(hours=hours)
        return [
            tx for tx in transactions 
            if datetime.fromisoformat(tx['timestamp']) > cutoff
        ]
        
    async def _store_transaction(self, token: str, transaction: dict):
        """Store transaction in Redis"""
        cache_key = f"transactions:{token}"
        
        # Get existing transactions
        transactions = await self.cache.get(cache_key) or []
        
        # Add new transaction
        transactions.append({
            'timestamp': datetime.now().isoformat(),
            'wallet': transaction['wallet'],
            'action': transaction['action'],
            'amount_usd': transaction['amount_usd'],
            'trader_type': transaction['trader_type']
        })
        
        # Store with 4h expiration
        await self.cache.set(cache_key, transactions, expire_minutes=240)
        
    async def add_transaction(self, transaction: dict) -> List[str]:
        """Add transaction and return any detected patterns"""
        token = transaction['token_address']
        wallet = transaction['wallet_address']
        
        # Store transaction
        await self._store_transaction(token, {
            'timestamp': datetime.now().isoformat(),
            'wallet': wallet,
            'action': 'buy' if transaction['is_buy'] else 'sell',
            'amount_usd': transaction['usd_value'],
            'trader_type': self.trader_profiles.get(wallet, {}).get('category', 'Unknown')
        })
        
        # Check patterns (no need for clean_old_transactions as Redis handles expiry)
        return await self._check_patterns(token)
        
    async def _check_patterns(self, token: str) -> List[str]:
        """Check for interesting patterns"""
        patterns = []
        
        # Get recent transactions for this token
        token_txs = await self._get_recent_transactions(token)
        if not token_txs:
            return patterns
            
        # Pattern 1: Multiple Alpha traders active
        alpha_pattern = self._check_alpha_pattern(token_txs)
        if alpha_pattern:
            patterns.append(alpha_pattern)
            
        # Pattern 2: Early Alpha followed by Position traders
        sequence_pattern = self._check_sequence_pattern(token_txs)
        if sequence_pattern:
            patterns.append(sequence_pattern)
            
        # Pattern 3: Multiple trader types buying
        diversity_pattern = self._check_diversity_pattern(token_txs)
        if diversity_pattern:
            patterns.append(diversity_pattern)
            
        return patterns
        
    def _check_alpha_pattern(self, transactions: List[dict]) -> str:
        """Check for multiple Alpha traders activity"""
        last_hour = datetime.now() - timedelta(hours=1)
        recent_txs = [tx for tx in transactions if tx['timestamp'] > last_hour]
        
        alpha_buyers = set(
            tx['wallet'] for tx in recent_txs
            if tx['trader_type'] == 'Alpha' and tx['action'] == 'buy'
        )
        
        alpha_sellers = set(
            tx['wallet'] for tx in recent_txs
            if tx['trader_type'] == 'Alpha' and tx['action'] == 'sell'
        )
        
        if len(alpha_buyers) >= 2:
            return f"🎯 Multiple Alpha traders ({len(alpha_buyers)}) buying in last hour"
        elif len(alpha_sellers) >= 2:
            return f"⚠️ Multiple Alpha traders ({len(alpha_sellers)}) selling in last hour"
            
        return None
        
    def _check_sequence_pattern(self, transactions: List[dict]) -> str:
        """Check for Alpha traders followed by Position traders"""
        last_4h = datetime.now() - timedelta(hours=4)
        recent_txs = [tx for tx in transactions if tx['timestamp'] > last_4h]
        
        # Look for early Alpha buys followed by Position trader buys
        alpha_buy_time = None
        for tx in recent_txs:
            if tx['trader_type'] == 'Alpha' and tx['action'] == 'buy':
                alpha_buy_time = tx['timestamp']
                break
                
        if alpha_buy_time:
            subsequent_position_buyers = set(
                tx['wallet'] for tx in recent_txs
                if tx['timestamp'] > alpha_buy_time 
                and tx['trader_type'] == 'Position'
                and tx['action'] == 'buy'
            )
            
            if len(subsequent_position_buyers) >= 2:
                return "🎯 Alpha entry followed by Position trader buys"
                
        return None
        
    def _check_diversity_pattern(self, transactions: List[dict]) -> str:
        """Check for diverse trader types buying"""
        last_2h = datetime.now() - timedelta(hours=2)
        recent_txs = [tx for tx in transactions if tx['timestamp'] > last_2h]
        
        buyer_types = set(
            tx['trader_type'] for tx in recent_txs
            if tx['action'] == 'buy'
        )
        
        if len(buyer_types) >= 3:  # At least 3 different types buying
            return f"💫 Multiple trader types buying ({', '.join(buyer_types)})"
            
        return None 
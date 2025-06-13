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
        
    async def _get_recent_transactions(self, token_address: str, hours: int = 4) -> List[dict]:
        """Get recent transactions for a specific token from Redis"""
        cache_key = f"token_transactions:{token_address}"
        transactions = await self.cache.get(cache_key)
        
        if not transactions:
            return []
            
        # Filter by time
        cutoff = datetime.now() - timedelta(hours=hours)
        return [
            tx for tx in transactions 
            if datetime.fromisoformat(tx['timestamp']) > cutoff
        ]
        
    async def _store_transaction(self, token_address: str, transaction: dict):
        """Store transaction for specific token in Redis"""
        cache_key = f"token_transactions:{token_address}"
        
        # Get existing transactions for this token
        transactions = await self.cache.get(cache_key) or []
        
        # Add new transaction
        transactions.append({
            'timestamp': datetime.now().isoformat(),
            'wallet': transaction['wallet'],
            'action': transaction['action'],
            'amount_usd': transaction['amount_usd'],
            'trader_type': transaction['trader_type'],
            'token_symbol': transaction.get('token_symbol', 'Unknown')
        })
        
        # Keep only last 50 transactions per token to avoid memory issues
        if len(transactions) > 50:
            transactions = transactions[-50:]
        
        # Store with 4h expiration
        await self.cache.set(cache_key, transactions, expire_minutes=240)
        
    async def add_transaction(self, transaction: dict) -> List[str]:
        """Add transaction and return any detected confluence patterns for this specific token"""
        token_address = transaction['token_address']
        wallet = transaction['wallet_address']
        
        # Store transaction with token address as key
        await self._store_transaction(token_address, {
            'timestamp': datetime.now().isoformat(),
            'wallet': wallet,
            'action': 'buy' if transaction['is_buy'] else 'sell',
            'amount_usd': transaction['usd_value'],
            'trader_type': self.trader_profiles.get(wallet, {}).get('category', 'Unknown'),
            'token_symbol': transaction.get('token_symbol', 'Unknown')
        })
        
        # Check patterns for THIS SPECIFIC TOKEN only
        return await self._check_patterns(token_address)
        
    async def _check_patterns(self, token_address: str) -> List[str]:
        """Check for confluence patterns for this specific token"""
        patterns = []
        
        # Get recent transactions for this specific token
        token_txs = await self._get_recent_transactions(token_address)
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
        last_30_min = datetime.now() - timedelta(minutes=30)
        recent_txs = [
            tx for tx in transactions 
            if datetime.fromisoformat(tx['timestamp']) > last_30_min
        ]
        
        # Get unique alpha wallets by action
        alpha_buyers = set(
            tx['wallet'] for tx in recent_txs
            if tx['trader_type'] in ['Alpha Traders', 'Alpha'] and tx['action'] == 'buy'
        )
        
        alpha_sellers = set(
            tx['wallet'] for tx in recent_txs
            if tx['trader_type'] in ['Alpha Traders', 'Alpha'] and tx['action'] == 'sell'
        )
        
        # CONFLUENCE: Multiple different alpha wallets on SAME token
        if len(alpha_buyers) >= 2:
            total_volume = sum(
                tx['amount_usd'] for tx in recent_txs
                if tx['trader_type'] in ['Alpha Traders', 'Alpha'] and tx['action'] == 'buy'
            )
            wallet_previews = [f"{w[:4]}...{w[-4:]}" for w in list(alpha_buyers)[:3]]
            return f"🔥 {len(alpha_buyers)} Alpha wallets BUYING ${token_symbol} (${total_volume:,.0f})\n   Wallets: {', '.join(wallet_previews)}"
            
        elif len(alpha_sellers) >= 2:
            total_volume = sum(
                tx['amount_usd'] for tx in recent_txs
                if tx['trader_type'] in ['Alpha Traders', 'Alpha'] and tx['action'] == 'sell'
            )
            wallet_previews = [f"{w[:4]}...{w[-4:]}" for w in list(alpha_sellers)[:3]]
            return f"🚨 {len(alpha_sellers)} Alpha wallets SELLING ${token_symbol} (${total_volume:,.0f})\n   Wallets: {', '.join(wallet_previews)}"
            
        return None
        
    def _check_sequence_pattern(self, transactions: List[dict], token_symbol: str) -> str:
        """Check for Alpha traders followed by other trader types on SAME TOKEN"""
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
            if tx['trader_type'] in ['Alpha Traders', 'Alpha']:
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
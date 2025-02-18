from datetime import datetime, timedelta
import asyncio
import logging
from typing import List, Dict
from dune_client.types import QueryParameter
from dune_client.client import DuneClient
from dune_client.query import QueryBase
import aiohttp
import os
from dotenv import load_dotenv
from collections import defaultdict

logger = logging.getLogger(__name__)

load_dotenv()

class AlphaTracker:
    def __init__(self, dune_client: DuneClient):
        self.dune_client = dune_client
        self.alpha_addresses: List[str] = []
        self.trader_profiles: Dict[str, dict] = {}
        self.last_update: datetime = None
        self.UPDATE_INTERVAL = timedelta(days=7)
        self.HELIUS_API_KEY = os.getenv('HELIUS_API_KEY')
        self.WEBHOOK_ID = os.getenv('HELIUS_WEBHOOK_ID')
        self.pattern_detector = None
        
    async def get_current_webhook(self) -> List[str]:
        """Get current webhook configuration"""
        try:
            webhook_url = f"https://api.helius.xyz/v0/webhooks/{self.WEBHOOK_ID}?api-key={self.HELIUS_API_KEY}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(webhook_url) as response:
                    if response.status != 200:
                        logger.error(f"Failed to get webhook: {await response.text()}")
                        return []
                    
                    webhook_data = await response.json()
                    return webhook_data.get('accountAddresses', [])
                    
        except Exception as e:
            logger.error(f"Error getting webhook: {e}")
            return []

    async def update_alpha_addresses(self) -> bool:
        """Fetch latest alpha addresses from Dune materialized view"""
        try:
            # Check if update is needed
            if (self.last_update and 
                datetime.now() - self.last_update < self.UPDATE_INTERVAL):
                logger.info("Alpha addresses update not needed yet")
                return False
                
            logger.info("Fetching latest alpha addresses and profiles...")
            
            async with aiohttp.ClientSession() as session:
                url = f"https://api.dune.com/api/v1/query/4647703/results"
                headers = {"X-Dune-Api-Key": os.getenv('DUNE_API_KEY')}
                
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        logger.error(f"Failed to fetch query results: {await response.text()}")
                        return False
                        
                    data = await response.json()
                    
                    if not data.get('result') or not data['result'].get('rows'):
                        logger.error("No results found in query response")
                        return False
                    
                    new_addresses = []
                    new_profiles = {}
                    
                    for row in data['result']['rows']:
                        wallet = row['wallet']
                        new_addresses.append(wallet)
                        new_profiles[wallet] = {
                            'category': row['trader_category'],
                            'win_rate': row.get('win_rate', 0),
                            'avg_hold_hours': row.get('avg_hold_hours', 0),
                            'trades_per_day': row.get('trades_per_day', 0),
                            'total_profits': row.get('total_profits', 0)
                        }
                    
                    logger.info(f"Found {len(new_addresses)} addresses")
                    
                    self.trader_profiles = new_profiles
                    
                    current_addresses = await self.get_current_webhook()
                    if set(new_addresses) != set(current_addresses):
                        logger.info("Alpha addresses list changed, updating webhook...")
                        await self.update_webhook(new_addresses)
                    else:
                        logger.info("Alpha addresses unchanged, skipping webhook update")
                        
                    self.alpha_addresses = new_addresses
                    self.last_update = datetime.now()
                    return True
                    
        except Exception as e:
            logger.error(f"Error updating alpha addresses: {e}")
            return False
            
    async def update_webhook(self, addresses: List[str]):
        """Update Helius webhook with new address list"""
        try:
            webhook_url = f"https://api.helius.xyz/v0/webhooks/{self.WEBHOOK_ID}?api-key={self.HELIUS_API_KEY}"
            
            headers = {
                "Content-Type": "application/json"
            }
            
            update_data = {
                "webhookURL": "YOUR_WEBHOOK_URL",  # We need to add this to .env
                "transactionTypes": ["SWAP"],
                "accountAddresses": addresses,
                "webhookType": "enhanced"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.put(webhook_url, json=update_data, headers=headers) as response:
                    response_text = await response.text()
                    logger.info(f"Webhook response: {response_text}")
                    
                    if response.status != 200:
                        logger.error(f"Failed to update webhook: {response_text}")
                        return False
                    
                    logger.info(f"Successfully updated webhook with {len(addresses)} addresses")
                    return True
            
        except Exception as e:
            logger.error(f"Error updating webhook: {e}")
            return False
        
    async def start_monitoring(self):
        """Start periodic monitoring of alpha addresses"""
        while True:
            await self.update_alpha_addresses()
            # Wait for 1 day before checking again
            await asyncio.sleep(24 * 60 * 60)

    async def format_swap_notification(self, swap_data: dict) -> str:
        """Format swap notification for Telegram"""
        try:
            # Determine if buy or sell
            is_buy = swap_data['is_buy']
            emoji = "🟢" if is_buy else "🔴"
            action = "BUY" if is_buy else "SELL"
            
            # Format token info
            token_symbol = swap_data['token_symbol']
            project = swap_data['project']  # e.g., "Raydium", "Orca"
            
            # Format wallet info
            wallet_address = swap_data['wallet_address']
            solscan_link = f"https://solscan.io/account/{wallet_address}"
            
            # Format amounts
            sol_amount = swap_data['sol_amount']
            token_amount = swap_data['token_amount']
            usd_value = swap_data['usd_value']
            price = swap_data['price']
            
            # Format holdings
            total_holdings = swap_data['total_holdings']
            
            # Contract address
            contract_address = swap_data['token_address']
            
            message = (
                f"{emoji} {action} {token_symbol} on {project}\n\n"
                f"<a href='{solscan_link}'>{wallet_address[:6]}...{wallet_address[-4:]}</a>\n"
                f"🔄 {sol_amount:.3f} SOL ↔️ {token_amount:,.0f} {token_symbol}\n"
                f"💵 ${usd_value:,.2f} (${price:.4f})\n\n"
                f"💰 Holds: {total_holdings:,.0f} {token_symbol}\n\n"
                f"<code>{contract_address}</code>"
            )
            
            return message
        except Exception as e:
            logger.error(f"Error formatting swap notification: {e}")
            return "Error formatting swap notification"

    async def handle_webhook(self, webhook_data: dict):
        """Handle incoming webhook data"""
        try:
            # Initialize pattern detector if needed
            if not self.pattern_detector:
                self.pattern_detector = PatternDetector(self.trader_profiles)
            
            # Process the webhook data
            swap_data = self.parse_helius_webhook(webhook_data)
            
            # Check for patterns
            patterns = self.pattern_detector.add_transaction(swap_data)
            
            # Format basic swap notification
            message = await self.format_swap_notification(swap_data)
            
            # Add pattern alerts if any
            if patterns:
                message += "\n\n🔍 Pattern Detected:\n" + "\n".join(patterns)
            
            # Send to Telegram
            await self.send_to_telegram(message)
            
        except Exception as e:
            logger.error(f"Error handling webhook: {e}")

class PatternDetector:
    def __init__(self, trader_profiles: Dict[str, dict]):
        self.trader_profiles = trader_profiles
        self.recent_transactions = defaultdict(list)  # token -> list of transactions
        
    def add_transaction(self, transaction: dict) -> List[str]:
        """Add transaction and return any detected patterns"""
        token = transaction['token_address']
        wallet = transaction['wallet_address']
        
        # Store transaction
        self.recent_transactions[token].append({
            'timestamp': datetime.now(),
            'wallet': wallet,
            'action': 'buy' if transaction['is_buy'] else 'sell',
            'amount_usd': transaction['usd_value'],
            'trader_type': self.trader_profiles.get(wallet, {}).get('category', 'Unknown')
        })
        
        # Clean old transactions
        self._clean_old_transactions()
        
        # Check patterns
        return self._check_patterns(token)
        
    def _clean_old_transactions(self):
        """Remove transactions older than 4 hours"""
        cutoff = datetime.now() - timedelta(hours=4)
        for token in self.recent_transactions:
            self.recent_transactions[token] = [
                tx for tx in self.recent_transactions[token]
                if tx['timestamp'] > cutoff
            ]
            
    def _check_patterns(self, token: str) -> List[str]:
        """Check for interesting patterns"""
        patterns = []
        
        # Get recent transactions for this token
        token_txs = self.recent_transactions[token]
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
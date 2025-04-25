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
from telegram import Bot
from src.config.config import TELEGRAM_TOKEN, NOTIFICATION_CHANNEL_ID, YOUR_WEBHOOK_URL
import time

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
        self.bot = Bot(TELEGRAM_TOKEN)
        # Rate limiting
        self.last_notification = {}  # {wallet_address: timestamp}
        self.MIN_NOTIFICATION_INTERVAL = 3  # seconds, very short to allow for hot market conditions
        
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
                            'category': row['trader_type'],
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
                "webhookURL": YOUR_WEBHOOK_URL,  # Using config value
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
            
            # Format wallet info with GMGN link
            wallet = swap_data['wallet_address']
            wallet_short = f"{wallet[:6]}..."
            gmgn_link = f"https://www.gmgn.ai/sol/address/{wallet}"
            wallet_linked = f"<a href='{gmgn_link}'>{wallet_short}</a>"
            
            # Format marketcap
            mcap_str = ""
            if 'market_cap' in swap_data and swap_data['market_cap'] > 0:
                mcap = swap_data['market_cap']
                if mcap >= 1_000_000:  # $1M+
                    mcap_str = f" | MCap: ${mcap/1_000_000:.1f}M"
                else:  # Less than $1M
                    mcap_str = f" | MCap: ${mcap/1000:.1f}K"
            
            # Basic swap info
            message = [
                f"{emoji} {action} {swap_data['token_symbol']} on {swap_data['project']}{mcap_str}",
                f"👤 {wallet_linked}",
                "",  # Empty line for spacing
                f"🔹 {wallet_linked} swapped {swap_data['token_amount']:,.2f} "
                f"(${swap_data['usd_value']:,.2f}) {swap_data['token_symbol']} "
                f"for {swap_data['sol_amount']:.2f} SOL @{swap_data['price']:.6f}",
                "",  # Empty line for spacing,
                f"<code>{swap_data['token_address']}</code>"
            ]
            
            return "\n".join(message)
            
        except Exception as e:
            logger.error(f"Error formatting swap notification: {e}")
            return "Error formatting swap notification"

    async def send_to_notification_channel(self, message: str):
        """Send a message to the notification channel"""
        try:
            await self.bot.send_message(
                chat_id=NOTIFICATION_CHANNEL_ID,
                text=message,
                parse_mode='HTML',
                disable_web_page_preview=True
            )
        except Exception as e:
            logger.error(f"Error sending to notification channel: {e}")

    async def should_send_notification(self, wallet_address: str) -> bool:
        """Check if we should send a notification for this wallet"""
        now = time.time()
        if wallet_address in self.last_notification:
            if now - self.last_notification[wallet_address] < self.MIN_NOTIFICATION_INTERVAL:
                logger.debug(f"Rate limiting notification for wallet {wallet_address}")
                return False
        self.last_notification[wallet_address] = now
        return True

    async def test_notification_channel(self):
        """Test notification channel connectivity"""
        try:
            test_message = (
                "🔔 Notification Channel Test\n\n"
                "If you see this message, the alpha swap notification system is working correctly.\n"
                f"Channel ID: {NOTIFICATION_CHANNEL_ID}\n"
                f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}"
            )
            await self.send_to_notification_channel(test_message)
            return True
        except Exception as e:
            logger.error(f"Notification channel test failed: {e}")
            return False

    async def handle_webhook(self, webhook_data: dict):
        """Handle incoming webhook data"""
        try:
            # Initialize pattern detector if needed
            if not self.pattern_detector:
                self.pattern_detector = PatternDetector(self.trader_profiles)
            
            # Process the webhook data
            swap_data = await self.parse_helius_webhook(webhook_data)
            
            # Check rate limiting
            if not await self.should_send_notification(swap_data['wallet_address']):
                return
            
            # Format basic swap notification
            message = await self.format_swap_notification(swap_data)
            
            # Check for patterns
            patterns = self.pattern_detector.add_transaction(swap_data)
            
            # Add pattern alerts if any
            if patterns:
                message += "\n\n🔍 Pattern Detected:\n" + "\n".join(patterns)
            
            # Send to notification channel
            await self.send_to_notification_channel(message)
            
        except Exception as e:
            logger.error(f"Error handling webhook: {e}")

    async def parse_helius_webhook(self, webhook_data: dict) -> dict:
        """Parse Helius webhook data into swap notification format"""
        try:
            # Extract basic transaction info
            tx = webhook_data['transaction']
            
            # Determine if buy or sell
            is_buy = tx['type'] == 'BUY'  # Assuming Helius provides this
            
            # Extract token info
            token_data = tx['token']
            token_address = token_data['address']
            token_symbol = token_data.get('symbol', 'UNKNOWN')
            
            # Extract amounts
            sol_amount = float(tx['amount'])  # Amount in SOL
            token_amount = float(tx['tokenAmount'])
            usd_value = float(tx.get('usdValue', 0))
            
            # Calculate price and marketcap (assuming 1B supply)
            price = usd_value / token_amount if token_amount > 0 else 0
            TOTAL_SUPPLY = 1_000_000_000  # 1B tokens
            market_cap = price * TOTAL_SUPPLY
            
            return {
                'is_buy': is_buy,
                'wallet_address': tx['accountAddress'],
                'token_address': token_address,
                'token_symbol': token_symbol,
                'sol_amount': sol_amount,
                'token_amount': token_amount,
                'usd_value': usd_value,
                'price': price,
                'market_cap': market_cap,
                'project': tx.get('source', 'Unknown DEX')
            }
            
        except Exception as e:
            logger.error(f"Error parsing webhook data: {e}")
            raise

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
            
        # Pattern 1: Multiple Alpha Traders activity
        alpha_pattern = self._check_alpha_pattern(token_txs)
        if alpha_pattern:
            patterns.append(alpha_pattern)
            
        # Pattern 2: Alpha Traders followed by Volume Leaders or Steady Elite
        sequence_pattern = self._check_sequence_pattern(token_txs)
        if sequence_pattern:
            patterns.append(sequence_pattern)
            
        # Pattern 3: Multiple trader types buying
        diversity_pattern = self._check_diversity_pattern(token_txs)
        if diversity_pattern:
            patterns.append(diversity_pattern)
            
        return patterns
        
    def _check_alpha_pattern(self, transactions: List[dict]) -> str:
        """Check for multiple Alpha Traders activity"""
        last_hour = datetime.now() - timedelta(hours=1)
        recent_txs = [tx for tx in transactions if tx['timestamp'] > last_hour]
        
        alpha_buyers = set(
            tx['wallet'] for tx in recent_txs
            if tx['trader_type'] == 'Alpha Traders' and tx['action'] == 'buy'
        )
        
        alpha_sellers = set(
            tx['wallet'] for tx in recent_txs
            if tx['trader_type'] == 'Alpha Traders' and tx['action'] == 'sell'
        )
        
        if len(alpha_buyers) >= 2:
            return f"🎯 Multiple Alpha Traders ({len(alpha_buyers)}) buying in last hour"
        elif len(alpha_sellers) >= 2:
            return f"⚠️ Multiple Alpha Traders ({len(alpha_sellers)}) selling in last hour"
            
        return None
        
    def _check_sequence_pattern(self, transactions: List[dict]) -> str:
        """Check for Alpha Traders followed by Volume Leaders or Steady Elite"""
        last_4h = datetime.now() - timedelta(hours=4)
        recent_txs = [tx for tx in transactions if tx['timestamp'] > last_4h]
        
        # Look for early Alpha Traders buys
        alpha_buy_time = None
        for tx in recent_txs:
            if tx['trader_type'] == 'Alpha Traders' and tx['action'] == 'buy':
                alpha_buy_time = tx['timestamp']
                break
                
        if alpha_buy_time:
            subsequent_buyers = {
                tx['trader_type']: tx['wallet']
                for tx in recent_txs
                if tx['timestamp'] > alpha_buy_time 
                and tx['trader_type'] in ['Volume Leaders', 'Steady Elite']
                and tx['action'] == 'buy'
            }
            
            if len(subsequent_buyers) >= 2:
                follower_types = ', '.join(subsequent_buyers.keys())
                return f"🎯 Alpha Traders entry followed by {follower_types}"
                
        return None
        
    def _check_diversity_pattern(self, transactions: List[dict]) -> str:
        """Check for diverse trader types buying"""
        last_2h = datetime.now() - timedelta(hours=2)
        recent_txs = [tx for tx in transactions if tx['timestamp'] > last_2h]
        
        buyer_types = set(
            tx['trader_type'] for tx in recent_txs
            if tx['action'] == 'buy'
            and tx['trader_type'] in ['Alpha Traders', 'Volume Leaders', 'Steady Elite']
        )
        
        if len(buyer_types) >= 2:  # Changed to 2 since we now have 3 specific types
            return f"💫 Multiple trader types buying ({', '.join(buyer_types)})"
            
        return None
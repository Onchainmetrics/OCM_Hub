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
from src.services.price_service import PriceService
from collections import deque

logger = logging.getLogger(__name__)

load_dotenv()

class TelegramRateLimiter:
    """Smart rate limiter for Telegram messages"""
    def __init__(self, max_messages_per_second: int = 3, max_messages_per_minute: int = 20):
        self.max_per_second = max_messages_per_second
        self.max_per_minute = max_messages_per_minute
        self.second_window = deque()
        self.minute_window = deque()
        
    async def wait_if_needed(self):
        """Wait if we're hitting rate limits"""
        now = datetime.now()
        
        # Clean old entries
        cutoff_second = now - timedelta(seconds=1)
        cutoff_minute = now - timedelta(minutes=1)
        
        while self.second_window and self.second_window[0] < cutoff_second:
            self.second_window.popleft()
            
        while self.minute_window and self.minute_window[0] < cutoff_minute:
            self.minute_window.popleft()
        
        # Check if we need to wait
        if len(self.second_window) >= self.max_per_second:
            wait_time = 1.1  # Wait a bit more than 1 second
            logger.info(f"Rate limit: waiting {wait_time}s (per-second limit)")
            await asyncio.sleep(wait_time)
            
        elif len(self.minute_window) >= self.max_per_minute:
            oldest_in_minute = self.minute_window[0]
            wait_time = 61 - (now - oldest_in_minute).total_seconds()
            if wait_time > 0:
                logger.info(f"Rate limit: waiting {wait_time:.1f}s (per-minute limit)")
                await asyncio.sleep(wait_time)
        
        # Record this message
        self.second_window.append(now)
        self.minute_window.append(now)

class AlphaTracker:
    def __init__(self, dune_client: DuneClient):
        self.dune_client = dune_client
        self.alpha_addresses: List[str] = []
        self.trader_profiles: Dict[str, dict] = {}
        self.last_update: datetime = None
        self.UPDATE_INTERVAL = timedelta(days=7)
        self.HELIUS_API_KEY = os.getenv('HELIUS_API_KEY')
        self.WEBHOOK_ID = os.getenv('HELIUS_WEBHOOK_ID')
        self.WEBHOOK_URL = os.getenv('WEBHOOK_URL')
        self.pattern_detector = None
        self.telegram_bot = None  # Will be set from main bot instance
        self.price_service = PriceService()
        self.rate_limiter = TelegramRateLimiter()
        
        # Insider Cluster - Track these specific wallets for every swap
        self.insider_cluster = {
            'ENyuEqoBjjV4azP1BKzAt6JurhjcdnaZPWo6iDVV8rUZ': 'Insider_cluster_1',
            '5YAdcB8w487xQsXmtccWXg43WinNQzGsAzvHgkzFhTKx': 'Insider_cluster_2', 
            'HJj6rPEyHAVffLWVbErA7SSb1uUtgWzMbpwGdXLpuKyD': 'Insider_cluster_3'
        }
        
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
                            'trades_per_day': row.get('trades_per_day', 0),
                            'total_profits': row.get('total_profits', 0),
                            'unique_tokens': row.get('unique_tokens', 0),
                            'total_trades': row.get('total_trades', 0),
                            'spike_tokens_traded': row.get('spike_tokens_traded', 0),
                            'massive_wins': row.get('massive_wins', 0),
                            'avg_spike_ratio': row.get('avg_spike_ratio', 0),
                            'last_trade': row.get('last_trade', '')
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
                "webhookURL": self.WEBHOOK_URL,
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

    async def parse_helius_webhook(self, webhook_data: dict) -> List[dict]:
        """Parse Helius webhook data into standardized format"""
        parsed_transactions = []
        
        try:
            # Handle both single transaction and batch format
            transactions = webhook_data if isinstance(webhook_data, list) else [webhook_data]
            
            for tx_data in transactions:
                # Extract account keys and transaction info
                account_keys = tx_data.get('accountKeys', [])
                native_transfers = tx_data.get('nativeTransfers', [])
                token_transfers = tx_data.get('tokenTransfers', [])
                
                # Find the wallet address (feePayer or first account)
                wallet_address = None
                if tx_data.get('feePayer'):
                    wallet_address = tx_data['feePayer']
                elif account_keys:
                    wallet_address = account_keys[0]
                    
                if not wallet_address or wallet_address not in self.alpha_addresses:
                    continue
                    
                # Process token transfers to identify swaps
                for transfer in token_transfers:
                    token_address = transfer.get('mint')
                    if not token_address:
                        continue
                        
                    # Skip SOL transfers (wrapped SOL)
                    if token_address == 'So11111111111111111111111111111111111111112':
                        continue
                        
                    from_user = transfer.get('fromUserAccount')
                    to_user = transfer.get('toUserAccount')
                    token_amount = transfer.get('tokenAmount', 0)
                    
                    # Determine if this is a buy or sell
                    is_buy = to_user == wallet_address
                    is_sell = from_user == wallet_address
                    
                    if not (is_buy or is_sell):
                        continue
                        
                    # Calculate SOL equivalent from native transfers - DIRECTION MATTERS!
                    sol_amount = 0
                    if is_buy:
                        # For buys: count SOL going OUT of wallet (spent to buy tokens)
                        for native_transfer in native_transfers:
                            if native_transfer.get('fromUserAccount') == wallet_address:
                                sol_amount += native_transfer.get('amount', 0) / 1e9
                    elif is_sell:
                        # For sells: count SOL coming IN to wallet (received from selling tokens)
                        for native_transfer in native_transfers:
                            if native_transfer.get('toUserAccount') == wallet_address:
                                sol_amount += native_transfer.get('amount', 0) / 1e9
                            
                    # Get SOL price (1-hour cached) and calculate market cap from transaction
                    try:
                        sol_price = await self.price_service.get_sol_price()
                        
                        if sol_price:
                            # Calculate USD value of transaction
                            usd_value = sol_amount * sol_price
                            
                            # Calculate market cap using transaction data and cached metadata
                            market_data = await self.price_service.calculate_market_cap_from_transaction(
                                token_address,
                                sol_amount,
                                token_amount,
                                sol_price
                            )
                            
                            token_price = market_data.get('price_per_token', 0)
                            current_market_cap = market_data.get('market_cap', 0)
                            token_symbol = market_data.get('symbol', 'Unknown')
                            
                        else:
                            logger.warning(f"No SOL price available for {token_address[:8]}...")
                            usd_value = sol_amount * 100  # Fallback SOL price
                            token_price = 0
                            current_market_cap = 0
                            token_symbol = transfer.get('tokenSymbol', 'Unknown')
                            
                    except Exception as e:
                        logger.error(f"Error calculating market cap for {token_address[:8]}...: {e}")
                        usd_value = sol_amount * 100  # Fallback
                        token_price = 0
                        current_market_cap = 0
                        token_symbol = transfer.get('tokenSymbol', 'Unknown')
                    
                    logger.info(f"Creating parsed transaction: wallet={wallet_address[:8]}..., token={token_address[:8]}..., symbol={token_symbol}, action={'BUY' if is_buy else 'SELL'}, usd_value={usd_value}")
                    
                    parsed_tx = {
                        'wallet_address': wallet_address,
                        'token_address': token_address,
                        'token_symbol': token_symbol,
                        'is_buy': is_buy,
                        'sol_amount': sol_amount,
                        'token_amount': token_amount,
                        'usd_value': usd_value,
                        'price': token_price,
                        'current_market_cap': current_market_cap,
                        'timestamp': datetime.now().isoformat(),
                        'signature': tx_data.get('signature', '')
                    }
                    
                    # Cost basis tracking removed - focus on confluence detection only
                    
                    parsed_transactions.append(parsed_tx)
                    
        except Exception as e:
            logger.error(f"Error parsing webhook data: {e}")
            
        return parsed_transactions
            
    async def handle_webhook(self, webhook_data: dict):
        """Handle incoming webhook data - CONFLUENCE DETECTION ONLY"""
        try:
            # Initialize pattern detector if needed
            if not self.pattern_detector:
                from src.services.pattern_detector import PatternDetector
                self.pattern_detector = PatternDetector(self.trader_profiles, self.dune_client)
            
            # Process the webhook data - can return multiple transactions
            transactions = await self.parse_helius_webhook(webhook_data)
            
            # Process all transactions concurrently to avoid blocking
            if transactions:
                logger.info(f"Processing {len(transactions)} transactions concurrently")
                tasks = [self._process_single_transaction(swap_data) for swap_data in transactions]
                await asyncio.gather(*tasks, return_exceptions=True)
            
        except Exception as e:
            logger.error(f"Error handling webhook: {e}")
            
    async def _process_single_transaction(self, swap_data: dict):
        """Process a single transaction (for concurrent processing)"""
        try:
            wallet = swap_data['wallet_address']
            token = swap_data['token_address']
            usd_value = swap_data.get('usd_value', 0)
            
            # Filter out low-value transactions (minimum $100)
            if usd_value < 100:
                logger.debug(f"Skipping transaction below $100 threshold: {wallet[:8]}... ${usd_value:.2f}")
                return
            
            # Filter out stablecoins and common tokens that shouldn't trigger confluence
            excluded_tokens = {
                'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB',  # USDT
                'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC
                'So11111111111111111111111111111111111111112',   # Wrapped SOL
            }
            if token in excluded_tokens:
                logger.debug(f"Skipping excluded token: {token[:8]}...")
                return
            
            # Check if wallet is in trader profiles
            trader_profile = self.trader_profiles.get(wallet, {})
            trader_category = trader_profile.get('category', 'Unknown')
            
            logger.info(f"Processing swap: {wallet[:8]}... {swap_data['token_symbol']} {'BUY' if swap_data['is_buy'] else 'SELL'} - Token: {token[:8]}... - Trader Type: {trader_category}")
            
            # CRITICAL: Check for Insider Cluster wallets FIRST - we cannot miss these!
            if wallet in self.insider_cluster:
                cluster_label = self.insider_cluster[wallet]
                logger.info(f"🚨 INSIDER CLUSTER DETECTED: {cluster_label} - {wallet[:8]}... - {swap_data['token_symbol']} {'BUY' if swap_data['is_buy'] else 'SELL'}")
                
                try:
                    # Create special insider cluster notification
                    insider_message = await self.format_insider_cluster_notification(swap_data, cluster_label)
                    await self.send_to_telegram(insider_message)
                    logger.info(f"Insider cluster notification sent for {cluster_label}")
                except Exception as e:
                    logger.error(f"CRITICAL: Failed to send insider cluster notification for {cluster_label}: {e}")
            
            # Check for confluence patterns - this is our PRIMARY PURPOSE
            patterns = await self.pattern_detector.add_transaction(swap_data)
            logger.info(f"Pattern detection result for {token[:8]}...: {patterns}")
            
            # Also log trader profiles count for debugging
            if not hasattr(self, '_logged_profiles_count'):
                logger.info(f"Total trader profiles loaded: {len(self.trader_profiles)}")
                alpha_trader_types = ['Insider', 'Alpha Trader', 'Volume Leader', 'Consistent Performer']
                alpha_count = sum(1 for profile in self.trader_profiles.values() if profile.get('category') in alpha_trader_types)
                logger.info(f"Alpha traders count: {alpha_count}")
                self._logged_profiles_count = True
            
            # ONLY notify when CONFLUENCE patterns are detected
            if patterns:
                try:
                    # Get all wallets involved in recent transactions for this token
                    recent_txs = await self.pattern_detector._get_recent_transactions(swap_data['token_address'])
                    
                    # Format confluence notification (no cost basis analysis)
                    message = await self.format_confluence_notification(
                        swap_data, patterns, recent_txs
                    )
                    
                    # Send to Telegram with rate limiting
                    await self.send_to_telegram(message)
                    
                except Exception as e:
                    logger.error(f"Error processing confluence notification: {e}")
                    # Log the error but don't send fallback notifications to avoid spam
                    logger.warning(f"Skipping confluence notification due to processing error for token {token[:8]}...")
            
        except Exception as e:
            logger.error(f"Error processing single transaction: {e}")
            
    async def send_to_telegram(self, message: str):
        """Send confluence notification to Telegram with smart rate limiting"""
        try:
            # Use smart rate limiter
            await self.rate_limiter.wait_if_needed()
            
            if not self.telegram_bot:
                logger.error("Telegram bot not initialized")
                return
                
            # Get allowed users for alpha notifications (fallback to ALPHA_NOTIFICATIONS_CHAT_ID)
            allowed_users = os.getenv('ALLOWED_USERS')
            fallback_chat_id = os.getenv('ALPHA_NOTIFICATIONS_CHAT_ID')
            
            if allowed_users:
                # Send to all allowed users
                user_ids = [uid.strip() for uid in allowed_users.split(',') if uid.strip()]
                logger.info(f"Sending alpha notification to {len(user_ids)} users")
            elif fallback_chat_id:
                # Fallback to single chat ID
                user_ids = [fallback_chat_id]
                logger.info("Sending alpha notification to fallback chat ID")
            else:
                logger.error("Neither ALLOWED_USERS nor ALPHA_NOTIFICATIONS_CHAT_ID configured")
                return
                
            # Send to each user with retry logic for rate limiting
            for user_id in user_ids:
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        await self.telegram_bot.send_message(
                            chat_id=user_id,
                            text=message,
                            parse_mode='HTML',
                            disable_web_page_preview=True
                        )
                        logger.info(f"Telegram message sent successfully to {user_id} on attempt {attempt + 1}")
                        break
                    except Exception as send_error:
                        error_msg = str(send_error)
                        if "Flood control exceeded" in error_msg or "429" in error_msg:
                            wait_time = min(30, (attempt + 1) * 10)  # 10, 20, 30 seconds
                            logger.warning(f"Rate limit hit for {user_id} on attempt {attempt + 1}, waiting {wait_time}s before retry")
                            if attempt < max_retries - 1:  # Don't wait on last attempt
                                await asyncio.sleep(wait_time)
                            continue
                        else:
                            logger.error(f"Failed to send message to {user_id}: {send_error}")
                            break  # Don't retry non-rate-limit errors
                
                # No delay between users - smart rate limiter handles timing
            
        except Exception as e:
            error_msg = str(e)
            if "Flood control exceeded" in error_msg or "429" in error_msg:
                logger.warning(f"Telegram rate limit hit, skipping notification: {e}")
                # Don't retry to avoid making the problem worse
            elif "Timed out" in error_msg:
                logger.warning(f"Telegram timeout, skipping notification: {e}")
                # Don't retry timeouts to avoid backlog
            else:
                logger.error(f"Error sending Telegram notification: {e}")

    async def format_confluence_notification(self, trigger_tx: dict, patterns: list, 
                                           recent_txs: list) -> str:
        """Format confluence notification with detailed analysis"""
        try:
            token_symbol = trigger_tx['token_symbol']
            token_address = trigger_tx['token_address']
            current_market_cap = trigger_tx.get('current_market_cap', 0)
            
            # If market cap is unreliable, calculate median from recent transactions to avoid outliers
            if (current_market_cap == 0 or current_market_cap > 1_000_000_000) and recent_txs:
                logger.warning(f"Market cap seems unreliable ({current_market_cap}) for {token_address[:8]}..., calculating median from recent transactions")
                
                # Get market caps from recent transactions, excluding outliers
                recent_mcaps = [tx.get('market_cap', 0) for tx in recent_txs if tx.get('market_cap', 0) > 0]
                if recent_mcaps:
                    # Use median to avoid extreme outliers from MEV/slippage
                    recent_mcaps.sort()
                    median_mcap = recent_mcaps[len(recent_mcaps) // 2]
                    current_market_cap = median_mcap
                    logger.info(f"Using median market cap from {len(recent_mcaps)} transactions: ${median_mcap:,.0f}")
                else:
                    logger.warning(f"No valid market cap found in recent transactions")
            
            # Format market cap
            if current_market_cap >= 1_000_000_000:
                mcap_str = f"${current_market_cap/1_000_000_000:.2f}B"
            elif current_market_cap >= 1_000_000:
                mcap_str = f"${current_market_cap/1_000_000:.1f}M"
            elif current_market_cap >= 1_000:
                mcap_str = f"${current_market_cap/1_000:.0f}K"
            else:
                mcap_str = f"${current_market_cap:.0f}"
            
            # Header
            message = (
                f"🔥 <b>CONFLUENCE DETECTED</b>\n\n"
                f"🪙 <b>${token_symbol}</b> | MCap: {mcap_str}\n"
                f"📜 <code>{token_address}</code>\n\n"
            )
            
            # Add confluence patterns
            message += "<b>Confluence Patterns:</b>\n"
            for pattern in patterns:
                message += f"   {pattern}\n"
            message += "\n"
            
            # Add wallet details with GMGN links
            if recent_txs:
                message += "<b>Recent Activity (1h):</b>\n"
                
                # Group and aggregate transactions by wallet and action
                from collections import defaultdict
                
                wallet_aggregation = defaultdict(lambda: {'buy': 0, 'sell': 0, 'trader_type': 'Unknown'})
                
                for tx in recent_txs:
                    wallet = tx['wallet']
                    action = tx['action']
                    amount_usd = tx.get('amount_usd', 0)
                    trader_type = tx.get('trader_type', 'Unknown')
                    
                    wallet_aggregation[wallet][action] += amount_usd
                    wallet_aggregation[wallet]['trader_type'] = trader_type
                
                # Show buyers (wallets with buy activity)
                buyers = {w: data for w, data in wallet_aggregation.items() if data['buy'] > 0}
                if buyers:
                    message += "🟢 <b>Buyers:</b>\n"
                    for wallet, data in list(buyers.items())[:3]:  # Show top 3 buyers
                        short_wallet = f"{wallet[:4]}...{wallet[-4:]}"
                        gmgn_link = f"https://www.gmgn.ai/sol/address/{wallet}"
                        trader_type = data['trader_type']
                        buy_amount = data['buy']
                        message += f"   <a href='{gmgn_link}'>{short_wallet}</a> ({trader_type}) ${buy_amount:,.0f}\n"
                    message += "\n"
                
                # Show sellers (wallets with sell activity)
                sellers = {w: data for w, data in wallet_aggregation.items() if data['sell'] > 0}
                if sellers:
                    message += "🔴 <b>Sellers:</b>\n"
                    for wallet, data in list(sellers.items())[:3]:  # Show top 3 sellers
                        short_wallet = f"{wallet[:4]}...{wallet[-4:]}"
                        gmgn_link = f"https://www.gmgn.ai/sol/address/{wallet}"
                        trader_type = data['trader_type']
                        sell_amount = data['sell']
                        message += f"   <a href='{gmgn_link}'>{short_wallet}</a> ({trader_type}) ${sell_amount:,.0f}\n"
                    message += "\n"
            # Add links for further analysis
            message += f"<b>Links:</b>\n"
            message += f"GMGN: https://gmgn.ai/sol/token/{token_address}\n"
            message += f"Birdeye: https://birdeye.so/token/{token_address}?chain=solana"
            
            return message
            
        except Exception as e:
            logger.error(f"Error formatting confluence notification: {e}")
            return f"🔥 CONFLUENCE DETECTED for {trigger_tx.get('token_symbol', 'Unknown')}\n{chr(10).join(patterns)}"
    
    async def format_insider_cluster_notification(self, swap_data: dict, cluster_label: str) -> str:
        """Format insider cluster notification with special red alert formatting"""
        try:
            token_symbol = swap_data['token_symbol']
            token_address = swap_data['token_address']
            wallet_address = swap_data['wallet_address']
            is_buy = swap_data['is_buy']
            usd_value = swap_data['usd_value']
            current_market_cap = swap_data.get('current_market_cap', 0)
            
            # Format market cap
            if current_market_cap >= 1_000_000_000:
                mcap_str = f"${current_market_cap/1_000_000_000:.2f}B"
            elif current_market_cap >= 1_000_000:
                mcap_str = f"${current_market_cap/1_000_000:.1f}M"
            elif current_market_cap >= 1_000:
                mcap_str = f"${current_market_cap/1_000:.0f}K"
            else:
                mcap_str = f"${current_market_cap:.0f}"
            
            # Header with red alert emoji and buy/sell indicator
            action = "BUYING" if is_buy else "SELLING"
            action_emoji = "🟢" if is_buy else "🔴"
            message = (
                f"🚨 <b>INSIDER CLUSTER SIGNAL</b> {action_emoji}\n\n"
                f"🪙 <b>${token_symbol}</b> | MCap: {mcap_str}\n"
                f"📜 <code>{token_address}</code>\n\n"
            )
            
            # Insider cluster details
            message += "<b>Insider_Cluster:</b>\n"
            short_wallet = f"{wallet_address[:4]}...{wallet_address[-4:]}"
            gmgn_link = f"https://www.gmgn.ai/sol/address/{wallet_address}"
            message += f"   🎯 <a href='{gmgn_link}'>{cluster_label}</a> {action} ${token_symbol} (${usd_value:,.0f})\n\n"
            
            # Transaction details
            message += "<b>Transaction Details:</b>\n"
            message += f"   Wallet: <a href='{gmgn_link}'>{short_wallet}</a>\n"
            message += f"   Action: {action}\n"
            message += f"   Amount: ${usd_value:,.0f}\n\n"
            
            # Add links for further analysis
            message += f"<b>Links:</b>\n"
            message += f"GMGN: https://gmgn.ai/sol/token/{token_address}\n"
            message += f"Birdeye: https://birdeye.so/token/{token_address}?chain=solana"
            
            return message
            
        except Exception as e:
            logger.error(f"Error formatting insider cluster notification: {e}")
            return f"🚨 INSIDER CLUSTER SIGNAL for {cluster_label}: {swap_data.get('token_symbol', 'Unknown')} {swap_data['usd_value']:.0f}"
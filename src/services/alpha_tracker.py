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
from src.services.cost_basis_service import CostBasisService

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
        self.WEBHOOK_URL = os.getenv('WEBHOOK_URL')
        self.pattern_detector = None
        self.telegram_bot = None  # Will be set from main bot instance
        self.price_service = PriceService()
        self.cost_basis_service = CostBasisService()
        
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
                        
                    # Calculate SOL equivalent from native transfers
                    sol_amount = 0
                    for native_transfer in native_transfers:
                        if native_transfer.get('fromUserAccount') == wallet_address:
                            sol_amount += native_transfer.get('amount', 0) / 1e9
                        elif native_transfer.get('toUserAccount') == wallet_address:
                            sol_amount += native_transfer.get('amount', 0) / 1e9
                            
                    # Get SOL price (1-hour cached) and calculate market cap from transaction
                    try:
                        sol_price = await self.price_service.get_sol_price()
                        
                        if sol_price:
                            # Calculate USD value of transaction
                            usd_value = sol_amount * sol_price
                            
                            # Calculate market cap using transaction data and cached supply
                            market_data = await self.price_service.calculate_market_cap_from_transaction(
                                token_address, 
                                transfer.get('tokenSymbol', 'Unknown'),
                                sol_amount,
                                token_amount,
                                sol_price
                            )
                            
                            token_price = market_data.get('price_per_token', 0)
                            current_market_cap = market_data.get('market_cap', 0)
                            
                        else:
                            logger.warning(f"No SOL price available for {token_address[:8]}...")
                            usd_value = sol_amount * 100  # Fallback SOL price
                            token_price = 0
                            current_market_cap = 0
                            
                    except Exception as e:
                        logger.error(f"Error calculating market cap for {token_address[:8]}...: {e}")
                        usd_value = sol_amount * 100  # Fallback
                        token_price = 0
                        current_market_cap = 0
                    
                    # Get token symbol from webhook data
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
                    
                    # Record transaction for cost basis tracking
                    try:
                        if current_market_cap and current_market_cap > 0:
                            await self.cost_basis_service.record_transaction(
                                wallet_address,
                                token_address,
                                'buy' if is_buy else 'sell',
                                token_amount,
                                current_market_cap,
                                parsed_tx['timestamp']
                            )
                    except Exception as e:
                        logger.error(f"Error recording cost basis: {e}")
                    
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
            
            for swap_data in transactions:
                wallet = swap_data['wallet_address']
                token = swap_data['token_address']
                
                # Check if wallet is in trader profiles
                trader_profile = self.trader_profiles.get(wallet, {})
                trader_category = trader_profile.get('category', 'Unknown')
                
                logger.info(f"Processing swap: {wallet[:8]}... {swap_data['token_symbol']} {'BUY' if swap_data['is_buy'] else 'SELL'} - Token: {token[:8]}... - Trader Type: {trader_category}")
                
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
                        involved_wallets = list(set(tx['wallet'] for tx in recent_txs))
                        
                        # Get cost basis analysis for confluence
                        confluence_analysis = await self.cost_basis_service.analyze_confluence_cost_basis(
                            involved_wallets,
                            swap_data['token_address'],
                            swap_data.get('current_market_cap', 0)
                        )
                        
                        # Format confluence notification
                        message = await self.format_confluence_notification(
                            swap_data, patterns, confluence_analysis, recent_txs
                        )
                        
                        # Send to Telegram
                        await self.send_to_telegram(message)
                        
                    except Exception as e:
                        logger.error(f"Error processing confluence notification: {e}")
                        # Send basic confluence alert as fallback
                        basic_message = f"🔥 <b>CONFLUENCE DETECTED</b>\n\n" + "\n".join(patterns)
                        await self.send_to_telegram(basic_message)
            
        except Exception as e:
            logger.error(f"Error handling webhook: {e}")
            
    async def send_to_telegram(self, message: str):
        """Send confluence notification to Telegram"""
        try:
            if not self.telegram_bot:
                logger.error("Telegram bot not initialized")
                return
                
            # Get the configured chat ID for alpha notifications
            chat_id = os.getenv('ALPHA_NOTIFICATIONS_CHAT_ID')
            if not chat_id:
                logger.error("ALPHA_NOTIFICATIONS_CHAT_ID not configured")
                return
                
            await self.telegram_bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode='HTML',
                disable_web_page_preview=True
            )
            
        except Exception as e:
            logger.error(f"Error sending Telegram notification: {e}")

    async def format_confluence_notification(self, trigger_tx: dict, patterns: list, 
                                           confluence_analysis: dict, recent_txs: list) -> str:
        """Format confluence notification with detailed analysis"""
        try:
            token_symbol = trigger_tx['token_symbol']
            token_address = trigger_tx['token_address']
            current_market_cap = trigger_tx.get('current_market_cap', 0)
            
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
                message += "<b>Recent Activity (30min):</b>\n"
                
                # Group transactions by action
                buyers = [tx for tx in recent_txs if tx['action'] == 'buy']
                sellers = [tx for tx in recent_txs if tx['action'] == 'sell']
                
                if buyers:
                    message += "🟢 <b>Buyers:</b>\n"
                    for tx in buyers[-3:]:  # Show last 3 buyers
                        wallet = tx['wallet']
                        short_wallet = f"{wallet[:4]}...{wallet[-4:]}"
                        gmgn_link = f"https://www.gmgn.ai/sol/address/{wallet}"
                        trader_type = tx.get('trader_type', 'Unknown')
                        amount_usd = tx.get('amount_usd', 0)
                        message += f"   <a href='{gmgn_link}'>{short_wallet}</a> ({trader_type}) ${amount_usd:,.0f}\n"
                    message += "\n"
                
                if sellers:
                    message += "🔴 <b>Sellers:</b>\n"
                    for tx in sellers[-3:]:  # Show last 3 sellers
                        wallet = tx['wallet']
                        short_wallet = f"{wallet[:4]}...{wallet[-4:]}"
                        gmgn_link = f"https://www.gmgn.ai/sol/address/{wallet}"
                        trader_type = tx.get('trader_type', 'Unknown')
                        amount_usd = tx.get('amount_usd', 0)
                        message += f"   <a href='{gmgn_link}'>{short_wallet}</a> ({trader_type}) ${amount_usd:,.0f}\n"
                    message += "\n"
            
            # Add cost basis analysis if available
            if confluence_analysis and confluence_analysis.get('buyer_analysis'):
                buyer_analysis = confluence_analysis['buyer_analysis']
                if buyer_analysis.get('avg_entry_market_cap'):
                    avg_entry_mcap = buyer_analysis['avg_entry_market_cap']
                    profit_multiple = buyer_analysis.get('profit_multiple', 0)
                    
                    if avg_entry_mcap >= 1_000_000:
                        entry_str = f"${avg_entry_mcap/1_000_000:.1f}M"
                    else:
                        entry_str = f"${avg_entry_mcap/1_000:.0f}K"
                        
                    message += f"📊 <b>Buyer Cost Basis:</b>\n"
                    message += f"   Avg Entry MCap: {entry_str}\n"
                    message += f"   Current vs Entry: {profit_multiple:.2f}x\n\n"
            
            if confluence_analysis and confluence_analysis.get('seller_analysis'):
                seller_analysis = confluence_analysis['seller_analysis']
                if seller_analysis.get('avg_exit_market_cap'):
                    avg_exit_mcap = seller_analysis['avg_exit_market_cap']
                    vs_current = seller_analysis.get('vs_current_multiple', 0)
                    
                    if avg_exit_mcap >= 1_000_000:
                        exit_str = f"${avg_exit_mcap/1_000_000:.1f}M"
                    else:
                        exit_str = f"${avg_exit_mcap/1_000:.0f}K"
                        
                    message += f"📊 <b>Seller Cost Basis:</b>\n"
                    message += f"   Avg Exit MCap: {exit_str}\n"
                    message += f"   Exit vs Current: {vs_current:.2f}x\n\n"
            
            # Add links for further analysis
            message += f"<b>Links:</b>\n"
            message += f"GMGN: https://gmgn.ai/sol/token/{token_address}\n"
            message += f"Birdeye: https://birdeye.so/token/{token_address}?chain=solana"
            
            return message
            
        except Exception as e:
            logger.error(f"Error formatting confluence notification: {e}")
            return f"🔥 CONFLUENCE DETECTED for {trigger_tx.get('token_symbol', 'Unknown')}\n{chr(10).join(patterns)}"
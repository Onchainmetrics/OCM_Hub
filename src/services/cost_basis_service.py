import asyncio
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from src.services.cache_service import CacheService
from src.services.price_service import PriceService
import json

logger = logging.getLogger(__name__)

class CostBasisService:
    def __init__(self):
        self.cache = CacheService()
        self.price_service = PriceService()
        
    async def record_transaction(self, wallet: str, token_address: str, action: str, 
                               amount: float, market_cap: float, timestamp: str = None):
        """Record a transaction for cost basis calculation"""
        try:
            if not timestamp:
                timestamp = datetime.now().isoformat()
                
            transaction = {
                "wallet": wallet,
                "token_address": token_address,
                "action": action,  # "buy" or "sell"
                "amount": amount,  # token amount
                "market_cap": market_cap,
                "timestamp": timestamp
            }
            
            # Store in wallet-specific cost basis cache
            cache_key = f"cost_basis:{wallet}:{token_address}"
            
            # Get existing transactions
            existing_txs = await self.cache.get(cache_key) or []
            existing_txs.append(transaction)
            
            # Keep only last 100 transactions per wallet-token pair
            if len(existing_txs) > 100:
                existing_txs = existing_txs[-100:]
                
            # Store with 30-day expiration
            await self.cache.set(cache_key, existing_txs, expire_minutes=43200)  # 30 days
            
        except Exception as e:
            logger.error(f"Error recording transaction for cost basis: {e}")
            
    async def get_average_cost_basis(self, wallet: str, token_address: str) -> Optional[Dict]:
        """Calculate average cost basis (market cap) for a wallet's position in a token"""
        try:
            cache_key = f"cost_basis:{wallet}:{token_address}"
            transactions = await self.cache.get(cache_key) or []
            
            if not transactions:
                return None
                
            # Separate buys and sells
            buys = [tx for tx in transactions if tx["action"] == "buy"]
            sells = [tx for tx in transactions if tx["action"] == "sell"]
            
            # Calculate weighted average cost basis for buys
            total_buy_amount = sum(tx["amount"] for tx in buys)
            if total_buy_amount > 0:
                weighted_avg_buy_mcap = sum(
                    tx["amount"] * tx["market_cap"] for tx in buys
                ) / total_buy_amount
            else:
                weighted_avg_buy_mcap = None
                
            # Calculate weighted average cost basis for sells
            total_sell_amount = sum(tx["amount"] for tx in sells)
            if total_sell_amount > 0:
                weighted_avg_sell_mcap = sum(
                    tx["amount"] * tx["market_cap"] for tx in sells
                ) / total_sell_amount
            else:
                weighted_avg_sell_mcap = None
                
            # Calculate net position
            net_position = total_buy_amount - total_sell_amount
            
            return {
                "wallet": wallet,
                "token_address": token_address,
                "total_buys": len(buys),
                "total_sells": len(sells),
                "total_buy_amount": total_buy_amount,
                "total_sell_amount": total_sell_amount,
                "net_position": net_position,
                "avg_buy_market_cap": weighted_avg_buy_mcap,
                "avg_sell_market_cap": weighted_avg_sell_mcap,
                "is_net_buyer": net_position > 0,
                "first_transaction": min(tx["timestamp"] for tx in transactions) if transactions else None,
                "last_transaction": max(tx["timestamp"] for tx in transactions) if transactions else None
            }
            
        except Exception as e:
            logger.error(f"Error calculating average cost basis: {e}")
            return None
            
    async def get_cost_basis_for_multiple_wallets(self, wallets: List[str], token_address: str) -> Dict[str, Dict]:
        """Get cost basis for multiple wallets for the same token"""
        try:
            results = {}
            
            for wallet in wallets:
                cost_basis = await self.get_average_cost_basis(wallet, token_address)
                if cost_basis:
                    results[wallet] = cost_basis
                    
            return results
            
        except Exception as e:
            logger.error(f"Error getting cost basis for multiple wallets: {e}")
            return {}
            
    async def analyze_confluence_cost_basis(self, wallets: List[str], token_address: str, 
                                          current_market_cap: float) -> Dict:
        """Analyze cost basis patterns in confluence scenarios"""
        try:
            # Get cost basis for all wallets
            cost_bases = await self.get_cost_basis_for_multiple_wallets(wallets, token_address)
            
            if not cost_bases:
                return {}
                
            # Analyze patterns
            buyers = []
            sellers = []
            
            for wallet, data in cost_bases.items():
                if data["is_net_buyer"]:
                    buyers.append({
                        "wallet": wallet,
                        "avg_entry_mcap": data["avg_buy_market_cap"],
                        "net_position": data["net_position"]
                    })
                else:
                    sellers.append({
                        "wallet": wallet,
                        "avg_exit_mcap": data["avg_sell_market_cap"],
                        "net_position": abs(data["net_position"])
                    })
                    
            # Calculate insights
            analysis = {
                "token_address": token_address,
                "current_market_cap": current_market_cap,
                "total_wallets_analyzed": len(cost_bases),
                "net_buyers": len(buyers),
                "net_sellers": len(sellers),
                "buyer_analysis": {},
                "seller_analysis": {}
            }
            
            # Analyze buyers
            if buyers:
                entry_mcaps = [b["avg_entry_mcap"] for b in buyers if b["avg_entry_mcap"]]
                if entry_mcaps:
                    analysis["buyer_analysis"] = {
                        "count": len(buyers),
                        "avg_entry_market_cap": sum(entry_mcaps) / len(entry_mcaps),
                        "min_entry_market_cap": min(entry_mcaps),
                        "max_entry_market_cap": max(entry_mcaps),
                        "profit_multiple": current_market_cap / (sum(entry_mcaps) / len(entry_mcaps)) if entry_mcaps else 0
                    }
                    
            # Analyze sellers  
            if sellers:
                exit_mcaps = [s["avg_exit_mcap"] for s in sellers if s["avg_exit_mcap"]]
                if exit_mcaps:
                    analysis["seller_analysis"] = {
                        "count": len(sellers),
                        "avg_exit_market_cap": sum(exit_mcaps) / len(exit_mcaps),
                        "min_exit_market_cap": min(exit_mcaps),
                        "max_exit_market_cap": max(exit_mcaps),
                        "vs_current_multiple": (sum(exit_mcaps) / len(exit_mcaps)) / current_market_cap if exit_mcaps else 0
                    }
                    
            return analysis
            
        except Exception as e:
            logger.error(f"Error analyzing confluence cost basis: {e}")
            return {}
            
    async def update_transaction_with_market_cap(self, wallet: str, token_address: str, 
                                               action: str, amount: float):
        """Record transaction and automatically fetch current market cap"""
        try:
            # Get current market cap
            current_market_cap = await self.price_service.get_token_market_cap(token_address)
            
            if current_market_cap:
                await self.record_transaction(
                    wallet, token_address, action, amount, current_market_cap
                )
                logger.info(f"Recorded {action} transaction for {wallet[:8]}... at market cap ${current_market_cap:,.0f}")
            else:
                logger.warning(f"Could not fetch market cap for {token_address}")
                
        except Exception as e:
            logger.error(f"Error updating transaction with market cap: {e}")
            
    def clear_wallet_cost_basis(self, wallet: str, token_address: str = None):
        """Clear cost basis data for a wallet (optionally for specific token)"""
        try:
            if token_address:
                cache_key = f"cost_basis:{wallet}:{token_address}"
                asyncio.create_task(self.cache.invalidate(cache_key))
            else:
                # Clear all cost basis data for wallet (would need pattern matching)
                logger.info(f"Clearing all cost basis data for wallet {wallet}")
                
        except Exception as e:
            logger.error(f"Error clearing cost basis data: {e}")
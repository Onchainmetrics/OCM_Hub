import aiohttp
import logging
from typing import Dict, Optional, List
from datetime import datetime, timedelta
import asyncio
import json
import os
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

class PriceService:
    def __init__(self):
        self.helius_api_key = os.getenv('HELIUS_API_KEY')
        self.helius_rpc_url = f"https://mainnet.helius-rpc.com/?api-key={self.helius_api_key}"
        
        # Jupiter for backup prices (especially for SOL)
        self.jupiter_base_url = "https://api.jup.ag"
        
        # Cache strategy:
        # - Token supplies: Permanent cache (never changes)
        # - SOL price: 1 hour cache 
        # - Token prices: No cache (calculate from each transaction)
        # - Stablecoins: Hardcoded to $1
        self.token_supply_cache = {}  # Permanent cache for token supply
        self.sol_price_cache = None
        self.sol_price_timestamp = None
        
    async def get_sol_price(self) -> Optional[float]:
        """Get SOL price using Jupiter (more reliable for SOL)"""
        try:
            # Check 1-hour cache first
            if (self.sol_price_cache and self.sol_price_timestamp and
                datetime.now() - self.sol_price_timestamp < timedelta(hours=1)):
                return self.sol_price_cache
            
            sol_address = "So11111111111111111111111111111111111111112"
            url = f"{self.jupiter_base_url}/price/v2"
            params = {"ids": sol_address}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        if "data" in data and sol_address in data["data"]:
                            price = float(data["data"][sol_address]["price"])
                            
                            # Cache the result for 1 hour
                            self.sol_price_cache = price
                            self.sol_price_timestamp = datetime.now()
                            return price
                            
        except Exception as e:
            logger.error(f"Error fetching SOL price: {e}")
            
        return None
    
    async def get_token_supply_data(self, token_address: str) -> Optional[Dict]:
        """Get token supply data - cached permanently since supply doesn't change"""
        try:
            # Check permanent cache first
            if token_address in self.token_supply_cache:
                logger.info(f"Using cached supply for {token_address[:8]}...")
                return self.token_supply_cache[token_address]
            
            # Make API call to get supply
            payload = {
                "jsonrpc": "2.0",
                "id": "1", 
                "method": "getTokenSupply",
                "params": [token_address]
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.helius_rpc_url,
                    json=payload,
                    headers={"Content-Type": "application/json"}
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        logger.info(f"getTokenSupply response for {token_address[:8]}...: {data}")
                        
                        if "result" in data and data["result"] and "value" in data["result"]:
                            supply_info = data["result"]["value"]
                            
                            supply_data = {
                                "supply": supply_info.get("amount"),
                                "decimals": supply_info.get("decimals", 9)
                            }
                            
                            # Cache permanently
                            self.token_supply_cache[token_address] = supply_data
                            logger.info(f"Cached supply for {token_address[:8]}...: {supply_data}")
                            return supply_data
                        else:
                            logger.warning(f"No supply data in response for {token_address}")
                            return None
                    else:
                        logger.error(f"getTokenSupply API error: {response.status}")
                        return None
                        
        except Exception as e:
            logger.error(f"Error fetching token supply: {e}")
            return None
    
    async def calculate_market_cap_from_transaction(self, token_address: str, token_symbol: str, 
                                                   sol_amount: float, token_amount: float, 
                                                   sol_price: float) -> Dict[str, float]:
        """Calculate market cap using transaction data and cached supply"""
        try:
            # Get token supply (cached if available)
            supply_data = await self.get_token_supply_data(token_address)
            if not supply_data:
                logger.warning(f"Could not get supply data for {token_address[:8]}...")
                return {"price_per_token": 0, "market_cap": 0, "supply": 0, "decimals": 9}
            
            # Calculate price per token from this transaction
            if token_amount > 0 and sol_amount > 0:
                price_per_token = (sol_amount * sol_price) / token_amount
            else:
                price_per_token = 0
                
            # Calculate market cap
            if price_per_token > 0 and supply_data.get("supply"):
                decimals = supply_data.get("decimals", 9)
                raw_supply = float(supply_data["supply"])
                actual_supply = raw_supply / (10 ** decimals)
                market_cap = price_per_token * actual_supply
                
                logger.info(f"Market cap calculation for {token_symbol} ({token_address[:8]}...): "
                          f"price=${price_per_token:.8f}, supply={actual_supply:,.0f}, mcap=${market_cap:,.2f}")
            else:
                market_cap = 0
                
            return {
                "price_per_token": price_per_token,
                "market_cap": market_cap,
                "supply": supply_data.get("supply", 0),
                "decimals": supply_data.get("decimals", 9)
            }
            
        except Exception as e:
            logger.error(f"Error calculating market cap from transaction: {e}")
            return {"price_per_token": 0, "market_cap": 0, "supply": 0, "decimals": 9}
    
    # Legacy methods for backward compatibility
    async def get_token_data(self, token_address: str) -> Optional[Dict]:
        """Legacy method - use get_token_supply_data and calculate_market_cap_from_transaction instead"""
        return await self.get_token_supply_data(token_address)
        
    async def get_token_price(self, token_address: str) -> Optional[float]:
        """Legacy method - prices should be calculated from transactions"""
        return None
        
    async def get_token_market_cap(self, token_address: str) -> Optional[float]:
        """Legacy method - market cap should be calculated from transactions"""
        return None
        
    def clear_cache(self):
        """Clear SOL price cache (keep supply cache)"""
        self.sol_price_cache = None
        self.sol_price_timestamp = None
        
    def get_cache_stats(self) -> Dict:
        """Get cache statistics"""
        return {
            "supply_cache_size": len(self.token_supply_cache),
            "sol_price_cached": self.sol_price_cache is not None,
            "sol_price_age_seconds": (
                (datetime.now() - self.sol_price_timestamp).total_seconds()
                if self.sol_price_timestamp else None
            )
        }
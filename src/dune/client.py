from dune_client.client import DuneClient
from dune_client.types import QueryParameter
from dune_client.query import QueryBase
import os
from dotenv import load_dotenv
import pandas as pd
import logging
import asyncio
import aiohttp
from datetime import datetime, timedelta
from collections import defaultdict


# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

class DuneAnalytics:
    def __init__(self):
        self.client = DuneClient.from_env()
        
    async def get_whale_analysis(self, contract_address: str) -> pd.DataFrame:
        """Execute query for whale analysis of a specific token"""
        try:
            query = QueryBase(
                name="Whale Analysis",
                query_id=4557213,
                params=[
                    QueryParameter.text_type(
                        name="Contract Address",
                        value=contract_address
                    )
                ]
            )
            
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None,
                lambda: self.client.run_query(
                    query=query,
                    performance="large"
                )
            )
            return pd.DataFrame(results.result.rows)
        except Exception as e:
            logger.error(f"Error executing whale analysis query: {str(e)}")
            logger.error(f"Query parameters: Contract Address={contract_address}")
            raise 

    async def get_heatmap_analysis(self) -> pd.DataFrame:
        """Execute query for heatmap analysis of alpha wallet activity"""
        try:
            # Create query object
            query = QueryBase(
                name="Heatmap Analysis",
                query_id=4723009
            )
            
            # Execute query
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None, 
                lambda: self.client.run_query(
                    query=query,
                    performance="medium" 
                )
            )
            return pd.DataFrame(results.result.rows)
        except Exception as e:
            logger.error(f"Error executing heatmap analysis query: {e}")
            raise 

async def get_token_activity(token_address: str) -> dict:
    """Get comprehensive token activity from Helius"""
    helius_key = os.getenv('HELIUS_API_KEY')
    
    # Use the parsed transaction history endpoint
    url = f"https://api.helius.xyz/v0/token-history"
    params = {
        "api-key": helius_key,
        "tokenAddress": token_address,
        "type": "ALL",  # Get all transaction types
        "limit": 100
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                if response.status != 200:
                    logger.error(f"Helius API error: {await response.text()}")
                    return None
                    
                transactions = await response.json()
                
                # Track transaction data
                buyers = defaultdict(lambda: {
                    'first_buy_time': None,
                    'total_bought': 0,
                    'total_sold': 0,
                    'buy_count': 0,
                    'sell_count': 0
                })
                recent_trades = []
                first_tx_time = None
                
                for tx in transactions:
                    try:
                        timestamp = datetime.fromtimestamp(tx['timestamp'] / 1000)  # Convert milliseconds to seconds
                        wallet = tx['sourceAddress']  # Changed from 'address' to 'sourceAddress'
                        
                        # Determine if buy/sell and amount from transaction data
                        is_buy = False
                        amount = 0
                        
                        # Look for swap instructions
                        for ix in tx.get('instructions', []):
                            if ix.get('programId') in [
                                "SwaPpA9LAaLfeLi3a68M4DjnLqgtticKg6CnyNwgAC8",  # Raydium
                                "srmqPvymJeFKQ4zGQed1GFppgkRHL9kaELCbyksJtPX",  # Openbook
                                # Add other DEX program IDs as needed
                            ]:
                                # Extract swap details from instruction data
                                swap_data = ix.get('data', {})
                                is_buy = True  # Simplified for now, need proper analysis
                                amount = float(swap_data.get('amount', 0))
                                break
                        
                        if not first_tx_time:
                            first_tx_time = timestamp
                        
                        # Update stats
                        if is_buy:
                            if not buyers[wallet]['first_buy_time']:
                                buyers[wallet]['first_buy_time'] = timestamp
                            buyers[wallet]['total_bought'] += amount
                            buyers[wallet]['buy_count'] += 1
                        else:
                            buyers[wallet]['total_sold'] += amount
                            buyers[wallet]['sell_count'] += 1
                        
                        # Track recent activity (last 4h)
                        if (datetime.now() - timestamp).total_seconds() < 14400:
                            recent_trades.append({
                                'timestamp': timestamp,
                                'wallet': wallet,
                                'is_buy': is_buy,
                                'amount': amount
                            })
                            
                    except KeyError as e:
                        logger.warning(f"Missing key in transaction data: {e}")
                        continue
                
                return {
                    'buyers': buyers,
                    'recent_trades': recent_trades,
                    'token_age': datetime.now() - first_tx_time if first_tx_time else None
                }
                
    except Exception as e:
        logger.error(f"Error processing token activity: {e}")
        return None 
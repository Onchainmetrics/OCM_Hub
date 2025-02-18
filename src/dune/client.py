from dune_client.client import DuneClient
from dune_client.types import QueryParameter
from dune_client.query import QueryBase
import os
from dotenv import load_dotenv
import pandas as pd
import logging
import asyncio

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

class DuneAnalytics:
    def __init__(self):
        self.client = DuneClient.from_env()
        
    async def get_several_top_wallets(self) -> pd.DataFrame:
        """Execute query for tokens held by several top wallets"""
        try:
            # Create query object
            query = QueryBase(
                name="Several Top Wallets",
                query_id=4660685
            )
            
            # Execute query
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None, 
                lambda: self.client.run_query(
                    query=query,
                    performance='large'  # or 'large' for faster execution
                )
            )
            return pd.DataFrame(results.result.rows)
        except Exception as e:
            logger.error(f"Error executing Dune query: {e}")
            raise

    async def get_holder_analysis(self, contract_address: str) -> pd.DataFrame:
        """Execute query for holder analysis of a specific token"""
        try:
            query = QueryBase(
                name="Holder Analysis",
                query_id=4658905,
                params=[
                    QueryParameter.text_type(
                        name="CA",
                        value=contract_address
                    )
                ]
            )
            
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
            logger.error(f"Error executing holder analysis query: {e}")
            raise

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
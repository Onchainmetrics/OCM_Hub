from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import logging
import asyncio
from typing import Optional
import uvicorn
import os

logger = logging.getLogger(__name__)

class WebhookServer:
    def __init__(self, alpha_tracker=None):
        self.app = FastAPI()
        self.alpha_tracker = alpha_tracker
        self.setup_routes()
        
    def setup_routes(self):
        @self.app.post("/webhook/helius")
        async def helius_webhook(request: Request):
            """Receive Helius webhook notifications"""
            try:
                webhook_data = await request.json()
                logger.info(f"Received webhook data: {len(webhook_data)} events")
                
                if self.alpha_tracker:
                    await self.alpha_tracker.handle_webhook(webhook_data)
                else:
                    logger.warning("Alpha tracker not initialized")
                
                return JSONResponse({"status": "success"})
                
            except Exception as e:
                logger.error(f"Error processing webhook: {e}")
                raise HTTPException(status_code=500, detail=str(e))
                
        @self.app.get("/health")
        async def health_check():
            """Health check endpoint"""
            return {"status": "healthy"}
            
    def set_alpha_tracker(self, alpha_tracker):
        """Set the alpha tracker instance"""
        self.alpha_tracker = alpha_tracker
        
    async def start_server(self, host: str = "0.0.0.0", port: int = 8080):
        """Start the webhook server"""
        config = uvicorn.Config(
            app=self.app,
            host=host,
            port=port,
            log_level="info"
        )
        server = uvicorn.Server(config)
        
        logger.info(f"Starting webhook server on {host}:{port}")
        await server.serve()
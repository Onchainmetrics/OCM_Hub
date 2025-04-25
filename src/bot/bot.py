import os
import logging
from telegram.ext import Application
from src.bot.handlers import register_handlers
from telegram import BotCommand
from src.services.alpha_tracker import AlphaTracker
from src.dune.client import DuneAnalytics

logger = logging.getLogger(__name__)

class TelegramBot:
    async def __init__(self):
        """Initialize the bot with token from environment variables"""
        self.token = os.getenv('TELEGRAM_TOKEN')
        if not self.token:
            raise ValueError("No token provided")
            
        # Initialize the application
        self.application = Application.builder().token(self.token).build()
        
        # Initialize services
        dune_client = DuneAnalytics()
        alpha_tracker = AlphaTracker(dune_client)
        self.application.bot_data['alpha_tracker'] = alpha_tracker
        
        # Set up commands with descriptions
        commands = [
            BotCommand("start", "Start the bot"),
            BotCommand("help", "Show help message"),
            BotCommand("whales", "Get whale analysis for a token"),
            BotCommand("heatmap", "Track alpha wallet flows [elite|all]"),
            BotCommand("testalpha", "Test alpha tracker functionality"),
            BotCommand("test_notifications", "Test notification channel")
        ]
        
        # Register command handlers
        register_handlers(self.application)
        
        # Set commands
        await self.application.bot.set_my_commands(commands)
        
        logger.info("Bot initialized and handlers registered")

    @classmethod
    async def create(cls):
        """Factory method to create bot instance"""
        self = TelegramBot.__new__(cls)
        await self.__init__()
        return self 
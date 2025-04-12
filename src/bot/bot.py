import os
import logging
from telegram.ext import Application
from src.bot.handlers import register_handlers
from telegram import BotCommand

logger = logging.getLogger(__name__)

class TelegramBot:
    async def __init__(self):
        """Initialize the bot with token from environment variables"""
        self.token = os.getenv('TELEGRAM_TOKEN')
        if not self.token:
            raise ValueError("No token provided")
            
        # Initialize the application
        self.application = Application.builder().token(self.token).build()
        
        # Set up commands with descriptions
        commands = [
            BotCommand("start", "Start the bot"),
            BotCommand("help", "Show help message"),
            BotCommand("whales", "Get whale analysis for a token"),
            BotCommand("heatmap", "Track alpha wallet flows [elite|all]")
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
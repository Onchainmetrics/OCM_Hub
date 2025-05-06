from telegram.ext import Application, CommandHandler
from src.config.config import TELEGRAM_TOKEN
from src.bot.commands import (
    start_command, 
    help_command,  
    whales_command,
    test_alpha_command,
    heatmap_command,
    scan_command
)
import logging

logger = logging.getLogger(__name__)

class CABot:
    def __init__(self):
        """Initialize the bot"""
        self.application = Application.builder().token(TELEGRAM_TOKEN).build()
        self._register_handlers()
        
    def _register_handlers(self):
        """Register command handlers"""
        register_handlers(self.application)
        
    def run(self):
        """Start the bot"""
        logger.info("Starting CA Scanner bot...")
        self.application.run_polling(allowed_updates=["message"])
        
    async def stop(self):
        """Stop the bot"""
        logger.info("Stopping CA Scanner bot...")
        await self.application.stop()

def register_handlers(application):
    """Register all command handlers"""
    application.add_handler(CommandHandler('start', start_command))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('whales', whales_command))
    application.add_handler(CommandHandler('testalpha', test_alpha_command))
    application.add_handler(CommandHandler('heatmap', heatmap_command))
    application.add_handler(CommandHandler('scan', scan_command)) 
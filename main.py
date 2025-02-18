import asyncio
import logging
import os
from src.bot.bot import TelegramBot
from src.dune.client import DuneAnalytics
from src.services.alpha_tracker import AlphaTracker

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def main():
    try:
        # Add environment variable logging for all relevant vars
        logger.info("Loading environment variables...")
        logger.info("Bot-related vars:")
        logger.info(f"TELEGRAM_TOKEN: {'Set' if os.getenv('TELEGRAM_TOKEN') else 'Not set'}")
        logger.info(f"DUNE_API_KEY: {'Set' if os.getenv('DUNE_API_KEY') else 'Not set'}")
        logger.info(f"ALLOWED_USERS: {os.getenv('ALLOWED_USERS')}")
        
        logger.info("\nRedis-related vars:")
        logger.info(f"REDIS_HOST raw value: '{os.getenv('REDIS_HOST')}'")
        logger.info(f"REDIS_PORT raw value: '{os.getenv('REDIS_PORT')}'")
        logger.info(f"REDIS_PASSWORD: {'Set' if os.getenv('REDIS_PASSWORD') else 'Not set'}")

        logger.info("Initializing bot and services...")
        
        # Initialize Dune client
        dune = DuneAnalytics()
        
        # Initialize bot using factory method
        bot = await TelegramBot.create()
        
        # Initialize AlphaTracker and attach it to bot
        alpha_tracker = AlphaTracker(dune.client)
        bot.application.alpha_tracker = alpha_tracker
        
        # Initial fetch of alpha addresses
        logger.info("Performing initial fetch of alpha addresses...")
        await alpha_tracker.update_alpha_addresses()
        
        # Start monitoring in background
        logger.info("Starting alpha tracker monitoring...")
        monitor_task = asyncio.create_task(alpha_tracker.start_monitoring())
        
        # Initialize the application first
        await bot.application.initialize()
        
        # Start the application
        await bot.application.start()
        
        # Start polling in a way that doesn't conflict with the event loop
        logger.info("Starting bot polling...")
        await bot.application.updater.start_polling()
        
        # Keep the application running
        while True:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Stopping bot...")
        await bot.application.stop()
        await bot.application.shutdown()
    except Exception as e:
        logger.error(f"Error in main: {e}")
        if hasattr(bot, 'application'):
            await bot.application.stop()
            await bot.application.shutdown()
        raise

if __name__ == "__main__":
    asyncio.run(main()) 
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Bot Configuration
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
DUNE_API_KEY = os.getenv('DUNE_API_KEY')

# Channel IDs
NOTIFICATION_CHANNEL_ID = os.getenv('NOTIFICATION_CHANNEL_ID')

# Webhook Configuration
HELIUS_API_KEY = os.getenv('HELIUS_API_KEY')
HELIUS_WEBHOOK_ID = os.getenv('HELIUS_WEBHOOK_ID')
YOUR_WEBHOOK_URL = os.getenv('YOUR_WEBHOOK_URL')

# Allowed Users (optional)
ALLOWED_USERS = os.getenv('ALLOWED_USERS', '').split(',')

# Dune Query IDs
QUERIES = {
    'token_info': '123456',  # Replace with actual query ID
    'holder_analysis': '789012',  # Replace with actual query ID
    # Add more queries as needed
} 
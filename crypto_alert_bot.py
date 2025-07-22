import asyncio
import aiohttp
import logging
from datetime import datetime
from typing import Dict, Optional
from dataclasses import dataclass
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

@dataclass
class TargetLevel:
    symbol: str
    target_price: float
    created_at: datetime = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()

class CryptoLongEntryBot:
    def __init__(self, bot_token: str):
        self.bot_token = bot_token
        self.user_levels: Dict[int, Dict[str, TargetLevel]] = {}  # user_id -> {symbol: TargetLevel}
        self.application = None
        self.monitoring = False
        
    async def start_bot(self):
        """Initialize and start the Telegram bot"""
        self.application = Application.builder().token(self.bot_token).build()
        
        # Add handlers
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("add", self.add_level_command))
        self.application.add_handler(CommandHandler("list", self.list_levels_command))
        self.application.add_handler(CommandHandler("remove", self.remove_level_command))
        self.application.add_handler(CallbackQueryHandler(self.button_callback))
        
        # Start monitoring task
        asyncio.create_task(self.price_monitoring_loop())
        
        # Start the bot
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
        
        logger.info("Long Entry Alert Bot started successfully!")
        
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user_id = update.effective_user.id
        
        if user_id not in self.user_levels:
            self.user_levels[user_id] = {}
            
        welcome_text = """🎯 **Crypto Long Entry Alert Bot**

I'll monitor your target levels and alert you when prices drop to your entry zones!

**Commands:**
• `/add BTCUSDT.P 115000` - Set target level
• `/list` - Show your active levels
• `/remove BTCUSDT.P` - Remove a level
• `/help` - Show detailed help

**How it works:**
1. Add your target entry levels
2. I monitor prices every 5 minutes
3. When price drops to/below your level → ALERT! 🚨
4. Level gets deleted automatically after alert

**Example:**
`/add SOLUSDT.P 145` - Alert when SOL drops to $145 or below

Ready to catch those dips! 📉💰"""
        
        await update.message.reply_text(welcome_text, parse_mode='Markdown')
        
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        help_text = """📖 **Detailed Guide**

**Add Target Level:**
`/add <SYMBOL> <PRICE>`

**Examples:**
• `/add BTCUSDT.P 115000` - Bitcoin at $115,000
• `/add SOLUSDT.P 145` - Solana at $145.0000
• `/add ETHUSDT.P 3200.5` - Ethereum at $3,200.50

**Important Notes:**
🔸 Only alerts when price goes DOWN to your level
🔸 Perfect for long entry positions
🔸 One level per symbol (new level replaces old)
🔸 Auto-deletes after alert (no spam!)
🔸 Works with any Binance symbol

**Other Commands:**
• `/list` - See all your targets
• `/remove SYMBOL` - Manually remove a target

**Monitoring:**
✅ Checks every 5 minutes
✅ Only monitors symbols you add
✅ Stops monitoring after alert sent

Let's catch those perfect entries! 🎯"""
        
        await update.message.reply_text(help_text, parse_mode='Markdown')
        
    async def add_level_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /add command"""
        user_id = update.effective_user.id
        
        if user_id not in self.user_levels:
            self.user_levels[user_id] = {}
            
        try:
            args = context.args
            if len(args) != 2:
                await update.message.reply_text(
                    "❌ **Invalid format!**\n\n"
                    "Usage: `/add BTCUSDT.P 115000`\n"
                    "• Symbol and target price required",
                    parse_mode='Markdown'
                )
                return
                
            symbol = args[0].upper()
            target_price = float(args[1])
            
            # Validate symbol by checking current price
            current_price = await self.get_binance_price(symbol)
            if current_price is None:
                await update.message.reply_text(f"❌ **Invalid symbol:** `{symbol}`\n\nMake sure it exists on Binance!", parse_mode='Markdown')
                return
                
            # Check if target is reasonable (below current price for long entry)
            if target_price >= current_price:
                await update.message.reply_text(
                    f"⚠️ **Warning:** Target ${target_price:,.4f} is above current price ${current_price:,.4f}\n\n"
                    f"This is for long entries when price drops. Continue anyway?",
                    parse_mode='Markdown'
                )
                
            # Check if updating existing level
            is_update = symbol in self.user_levels[user_id]
            old_price = self.user_levels[user_id][symbol].target_price if is_update else None
            
            # Create/update the target level
            level = TargetLevel(symbol=symbol, target_price=target_price)
            self.user_levels[user_id][symbol] = level
            
            if is_update:
                await update.message.reply_text(
                    f"🔄 **Level Updated!**\n\n"
                    f"📊 **{symbol}**\n"
                    f"🔸 Old Target: ${old_price:,.4f}\n"
                    f"🔸 New Target: ${target_price:,.4f}\n"
                    f"💰 Current Price: ${current_price:,.4f}\n\n"
                    f"I'll alert you when {symbol} drops to ${target_price:,.4f} or below! 📉",
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text(
                    f"✅ **Target Level Added!**\n\n"
                    f"📊 **{symbol}**\n"
                    f"🎯 Target: ${target_price:,.4f}\n"
                    f"💰 Current: ${current_price:,.4f}\n"
                    f"📉 Distance: {((target_price - current_price) / current_price * 100):+.2f}%\n\n"
                    f"Monitoring started! I'll alert when price drops to your level. 🚨",
                    parse_mode='Markdown'
                )
            
        except ValueError:
            await update.message.reply_text("❌ **Invalid price!** Please enter a valid number.", parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error in add_level_command: {e}")
            await update.message.reply_text("❌ An error occurred. Please try again.")
            
    async def list_levels_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /list command"""
        user_id = update.effective_user.id
        
        if user_id not in self.user_levels or not self.user_levels[user_id]:
            await update.message.reply_text(
                "📭 **No active levels!**\n\n"
                "Add your first target with:\n"
                "`/add BTCUSDT.P 115000`",
                parse_mode='Markdown'
            )
            return
            
        levels_text = f"📋 **Your Target Levels** ({len(self.user_levels[user_id])} active)\n\n"
        
        for i, (symbol, level) in enumerate(self.user_levels[user_id].items(), 1):
            current_price = await self.get_binance_price(symbol)
            
            if current_price:
                distance_pct = ((level.target_price - current_price) / current_price * 100)
                distance_text = f"{distance_pct:+.2f}%"
                price_text = f"${current_price:,.4f}"
                
                # Visual indicator
                if current_price <= level.target_price:
                    status_emoji = "🚨"  # Should have triggered
                else:
                    status_emoji = "👀"  # Monitoring
            else:
                distance_text = "N/A"
                price_text = "N/A"
                status_emoji = "❓"
                
            levels_text += (
                f"{status_emoji} **{i}. {symbol}**\n"
                f"🎯 Target: ${level.target_price:,.4f}\n"
                f"💰 Current: {price_text}\n"
                f"📊 Distance: {distance_text}\n"
                f"📅 Added: {level.created_at.strftime('%m/%d %H:%M')}\n\n"
            )
            
        levels_text += "_I check these every 5 minutes! 🕐_"
        await update.message.reply_text(levels_text, parse_mode='Markdown')
        
    async def remove_level_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /remove command"""
        user_id = update.effective_user.id
        
        if user_id not in self.user_levels or not self.user_levels[user_id]:
            await update.message.reply_text("📭 No levels to remove!")
            return
            
        try:
            if not context.args:
                # Show interactive buttons if no symbol specified
                keyboard = []
                for symbol in self.user_levels[user_id].keys():
                    level = self.user_levels[user_id][symbol]
                    button_text = f"{symbol} @ ${level.target_price:,.2f}"
                    keyboard.append([InlineKeyboardButton(button_text, callback_data=f"remove_{symbol}")])
                    
                keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    "🗑️ **Select level to remove:**",
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
                return
                
            # Direct removal with symbol argument
            symbol = context.args[0].upper()
            if symbol in self.user_levels[user_id]:
                removed_level = self.user_levels[user_id].pop(symbol)
                await update.message.reply_text(
                    f"🗑️ **Level Removed**\n\n"
                    f"Stopped monitoring {symbol} @ ${removed_level.target_price:,.4f}"
                )
            else:
                await update.message.reply_text(f"❌ No active level found for {symbol}")
                
        except Exception as e:
            logger.error(f"Error in remove_level_command: {e}")
            await update.message.reply_text("❌ An error occurred.")
            
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline button callbacks"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        
        if query.data == "cancel":
            await query.edit_message_text("❌ Cancelled.")
            return
            
        if query.data.startswith("remove_"):
            symbol = query.data.replace("remove_", "")
            if user_id in self.user_levels and symbol in self.user_levels[user_id]:
                removed_level = self.user_levels[user_id].pop(symbol)
                await query.edit_message_text(
                    f"🗑️ **Level Removed**\n\n"
                    f"Stopped monitoring {symbol} @ ${removed_level.target_price:,.4f}"
                )
            else:
                await query.edit_message_text("❌ Level not found.")
                
    async def get_binance_price(self, symbol: str) -> Optional[float]:
        """Get current price from Binance API"""
        try:
            url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        return float(data['price'])
                        
        except Exception as e:
            logger.error(f"Error fetching price for {symbol}: {e}")
            
        return None
        
    async def price_monitoring_loop(self):
        """Main monitoring loop - checks every 5 minutes"""
        self.monitoring = True
        logger.info("🔄 Started price monitoring (every 5 minutes)")
        
        while True:
            try:
                await self.check_all_levels()
                await asyncio.sleep(300)  # 5 minutes
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(60)  # Retry after 1 minute on error
                
    async def check_all_levels(self):
        """Check all user levels for target hits"""
        total_checks = 0
        
        for user_id, user_levels in self.user_levels.items():
            for symbol, level in list(user_levels.items()):  # list() to avoid modification during iteration
                current_price = await self.get_binance_price(symbol)
                if current_price is None:
                    continue
                    
                total_checks += 1
                
                # Check if price dropped to/below target (long entry condition)
                if current_price <= level.target_price:
                    await self.send_target_hit_alert(user_id, level, current_price)
                    # Remove level after alert (one-time alert)
                    del self.user_levels[user_id][symbol]
                    
        if total_checks > 0:
            logger.info(f"✅ Checked {total_checks} levels at {datetime.now().strftime('%H:%M:%S')}")
                    
    async def send_target_hit_alert(self, user_id: int, level: TargetLevel, current_price: float):
        """Send alert when target level is hit"""
        try:
            drop_percent = ((level.target_price - current_price) / level.target_price * 100)
            
            alert_text = (
                f"🚨 **TARGET HIT!** 🚨\n\n"
                f"📊 **{level.symbol}** dropped to your level!\n\n"
                f"🎯 **Target:** ${level.target_price:,.4f}\n"
                f"💰 **Current:** ${current_price:,.4f}\n"
                f"📉 **Extra Drop:** {abs(drop_percent):.2f}% below target\n\n"
                f"⏰ **Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"🚀 **Perfect for long entry!** This level has been removed from monitoring.\n\n"
                f"_Add new levels with /add command_"
            )
            
            await self.application.bot.send_message(
                chat_id=user_id,
                text=alert_text,
                parse_mode='Markdown'
            )
            
            logger.info(f"🚨 ALERT SENT: {level.symbol} hit ${current_price} (target: ${level.target_price}) for user {user_id}")
            
        except Exception as e:
            logger.error(f"Error sending alert to user {user_id}: {e}")

# Main execution
async def main():
    # Get bot token from environment variable (for cloud deployment)
    import os
    BOT_TOKEN = os.getenv('BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
    
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ SETUP REQUIRED:")
        print("1. Go to @BotFather on Telegram")
        print("2. Send: /newbot")
        print("3. Follow instructions to create your bot")
        print("4. Copy the token and replace 'YOUR_BOT_TOKEN_HERE'")
        print("5. Run this script again")
        return
        
    bot = CryptoLongEntryBot(BOT_TOKEN)
    
    try:
        print("🚀 Starting Crypto Long Entry Alert Bot...")
        await bot.start_bot()
        
        # Keep the bot running
        while True:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        print("\n👋 Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot error: {e}")
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
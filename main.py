import logging
import asyncio
import os
import sqlite3
from datetime import datetime
from ryanair import Ryanair
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- SETTINGS ---
API_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHECK_INTERVAL_HOURS = 2
MAX_FLIGHTS = 2

# Initialization
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
# ryanair-py 3.x: only get_cheapest_flights(origin, date_from, date_to, destination_airport=...)
api = Ryanair(currency="EUR")
scheduler = AsyncIOScheduler()

# When user sends only "ADD FR1234", we wait for "YYYY-MM-DD ORIGIN DEST"
pending_add: dict[int, str] = {}


def _flight_number(flight) -> str:
    """Flight number from ryanair-py (3.x: flightNumber, older: flight_number)."""
    return getattr(flight, 'flightNumber', None) or getattr(flight, 'flight_number', '')


def _normalize_flight_code(code: str) -> str:
    """Normalize user input to API format (e.g. FR1234 -> FR 1234)."""
    code = (code or "").strip().upper()
    if not code:
        return ""
    if code.startswith("FR") and len(code) > 2 and code[2] != " ":
        return f"FR {code[2:]}"
    return code

# --- DATABASE OPERATIONS ---
def init_db():
    conn = sqlite3.connect('tracker.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS flights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            origin TEXT,
            destination TEXT,
            date TEXT,
            flight_number TEXT,
            last_price REAL
        )
    ''')
    conn.commit()
    conn.close()

def get_tracked_flights(chat_id=None):
    conn = sqlite3.connect('tracker.db')
    cursor = conn.cursor()
    if chat_id:
        cursor.execute('SELECT * FROM flights WHERE chat_id = ?', (chat_id,))
    else:
        cursor.execute('SELECT * FROM flights')
    rows = cursor.fetchall()
    conn.close()
    return rows

def update_price(flight_id, new_price):
    conn = sqlite3.connect('tracker.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE flights SET last_price = ? WHERE id = ?', (new_price, flight_id))
    conn.commit()
    conn.close()

# --- PRICE CHECK LOGIC ---
async def check_prices():
    flights = get_tracked_flights()
    if not flights:
        return

    for f in flights:
        db_id, chat_id, origin, dest, date, f_number, last_price = f
        try:
            # Format date for API
            date_obj = datetime.strptime(date, '%Y-%m-%d').date()
            # get_cheapest_flights(origin, date_from, date_to, destination_airport=dest)
            trips = api.get_cheapest_flights(origin, date_obj, date_obj, destination_airport=dest)

            current_flight = next((t for t in trips if _flight_number(t) == f_number), None) if trips else None

            if current_flight:
                new_price = current_flight.price
                if new_price != last_price:
                    diff = new_price - last_price
                    direction = "📈 Up" if diff > 0 else "📉 Down"
                    msg = (f"🔔 PRICE CHANGE! {direction}\n"
                           f"Flight: {f_number} ({origin} -> {dest})\n"
                           f"Date: {date}\n"
                           f"New Price: {new_price} EUR (was {last_price} EUR)")
                    await bot.send_message(chat_id, msg)
                    update_price(db_id, new_price)
        except Exception as e:
            logging.error(f"Error checking {f_number}: {e}")

# --- BOT COMMANDS ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("✈️ **Ryanair Tracker Active**\n\n"
                         "Commands:\n"
                         "• `ADD [FLIGHT]` or `ADD FR1234 2026-05-20 VNO BVA`\n"
                         "• `/list` - see your active tracks\n"
                         "• `/help` - how to add a flight\n"
                         "• `/clear` - delete all your tracks\n"
                         "• `/cancel` - cancel adding (when asked for date and route)")

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "📌 **How to add a flight**\n\n"
        "Send a line in this format:\n"
        "`ADD [flight code] [date] [origin] [destination]`\n\n"
        "• **Flight code** — Ryanair number, e.g. `FR1234` or `FR 1234`\n"
        "• **Date** — departure date: `YYYY-MM-DD` (e.g. `2026-05-20`)\n"
        "• **Origin** — 3-letter airport code (e.g. `VNO` for Vilnius)\n"
        "• **Destination** — 3-letter airport code (e.g. `BVA` for Paris Beauvais)\n\n"
        "**Short form:** send only `ADD FR1234`, then send one line: `YYYY-MM-DD ORIGIN DEST`\n\n"
        "**Full form:** `ADD FR1234 2026-05-20 VNO BVA`\n\n"
        "Find flight and airport codes on ryanair.com."
    )

@dp.message(Command("list"))
async def cmd_list(message: types.Message):
    flights = get_tracked_flights(message.chat.id)
    if not flights:
        await message.answer("You are not tracking any flights.")
        return

    response = "📋 **Your Tracked Flights:**\n"
    for f in flights:
        response += f"• {f[5]}: {f[2]}->{f[3]} on {f[4]} (Last price: {f[6]}€)\n"
    await message.answer(response)

@dp.message(Command("clear"))
async def cmd_clear(message: types.Message):
    conn = sqlite3.connect('tracker.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM flights WHERE chat_id = ?', (message.chat.id,))
    conn.commit()
    conn.close()
    await message.answer("All your tracking data has been deleted.")

def _parse_date_route(text: str) -> tuple[str, str, str] | None:
    """Parse 'YYYY-MM-DD ORIGIN DEST' (3 parts). Returns (date_str, origin, dest) or None."""
    parts = (text or "").strip().split()
    if len(parts) != 3:
        return None
    date_str, origin, dest = parts
    if len(origin) != 3 or len(dest) != 3:
        return None
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
        return date_str, origin.upper(), dest.upper()
    except ValueError:
        return None


async def _do_add_flight(chat_id: int, flight_code_norm: str, date_str: str, origin: str, dest: str) -> str | None:
    """Add one flight. Returns None on success, or error message."""
    existing = get_tracked_flights(chat_id)
    if len(existing) >= MAX_FLIGHTS:
        return f"Limit reached! Max {MAX_FLIGHTS} flights."
    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return "Invalid date. Use YYYY-MM-DD."
    trips = api.get_cheapest_flights(origin, date_obj, date_obj, destination_airport=dest)
    if not trips:
        return f"No flights found for {origin}->{dest} on {date_str}."
    match = next((t for t in trips if _flight_number(t) == flight_code_norm), None)
    if not match:
        available = ", ".join(_flight_number(t) for t in trips)
        return f"Flight {flight_code_norm} not found on {date_str} for {origin}->{dest}. Available: {available}."
    conn = sqlite3.connect('tracker.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO flights (chat_id, origin, destination, date, flight_number, last_price)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (chat_id, origin, dest, date_str, _flight_number(match), match.price))
    conn.commit()
    conn.close()
    return None  # success


@dp.message()
async def handle_message(message: types.Message):
    chat_id = message.chat.id
    text = (message.text or "").strip()

    # Second step: user previously sent "ADD FR1234", now sends "YYYY-MM-DD ORIGIN DEST"
    if chat_id in pending_add:
        parsed = _parse_date_route(text)
        if parsed:
            date_str, origin, dest = parsed
            flight_code_norm = pending_add.pop(chat_id)
            err = await _do_add_flight(chat_id, flight_code_norm, date_str, origin, dest)
            if err:
                pending_add[chat_id] = flight_code_norm  # keep pending so they can retry
                await message.answer(f"⚠️ {err}")
            else:
                await message.answer(
                    f"✅ Now tracking {flight_code_norm} ({origin}→{dest}) on {date_str}. "
                    "Check /list for price."
                )
            return
        else:
            # Invalid format — remind and keep pending
            await message.answer(
                "Send date and route in one line: **YYYY-MM-DD ORIGIN DEST**\n"
                "Example: 2026-05-20 VNO BVA\n\nOr send /cancel to cancel."
            )
            return

    if text.upper().startswith("ADD"):
        try:
            parts = text.split()
            if len(parts) == 2:
                # Only flight number: ADD FR1234
                _, flight_code = parts
                flight_code_norm = _normalize_flight_code(flight_code)
                if not flight_code_norm:
                    await message.answer("Enter a valid flight code (e.g. FR1234).")
                    return
                pending_add[chat_id] = flight_code_norm
                await message.answer(
                    f"Flight **{flight_code_norm}**. Now send date and route in one line:\n"
                    "`YYYY-MM-DD ORIGIN DEST`\nExample: 2026-05-20 VNO BVA"
                )
                return
            if len(parts) != 5:
                await message.answer(
                    "Usage: `ADD FR1234` then send date and route, or full: "
                    "`ADD FR1234 2026-05-20 VNO BVA`"
                )
                return

            _, flight_code, date_str, origin, dest = parts
            origin, dest = origin.upper(), dest.upper()
            flight_code_norm = _normalize_flight_code(flight_code)

            err = await _do_add_flight(chat_id, flight_code_norm, date_str, origin, dest)
            if err:
                await message.answer(f"⚠️ {err}")
            else:
                await message.answer(
                    f"✅ Now tracking {flight_code_norm} ({origin}→{dest}) on {date_str}. Check /list."
                )
        except Exception as e:
            await message.answer(f"⚠️ Error: {str(e)}")
        return

    # Cancel pending add on /cancel
    if text.lower() == "/cancel" and chat_id in pending_add:
        pending_add.pop(chat_id)
        await message.answer("Cancelled.")

# --- RUN ---
async def main():
    if not API_TOKEN:
        logging.error("Set TELEGRAM_BOT_TOKEN (env var or .env file).")
        raise SystemExit(1)
    init_db()
    logging.basicConfig(level=logging.INFO)
    scheduler.add_job(check_prices, "interval", hours=CHECK_INTERVAL_HOURS)
    scheduler.start()
    print("Bot is running...")
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())

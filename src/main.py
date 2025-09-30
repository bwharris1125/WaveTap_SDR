
import asyncio
import logging

from database_api.adsb_subscriber import ADSBSubscriber


async def main():
    uri = "ws://127.0.0.1:8443"  # Update as needed
    subscriber = ADSBSubscriber(uri)
    subscriber.setup_db()  # Uses src/database_api/adsb_data.db by default
    async def periodic_db_save():
        while True:
            await subscriber.save_to_db()
            await asyncio.sleep(10)
    await asyncio.gather(
        subscriber.connect_and_listen(),
        periodic_db_save()
    )

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())

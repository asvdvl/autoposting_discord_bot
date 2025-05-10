import asyncio
import os
import re
from datetime import datetime, timedelta
from collections import deque
from dotenv import load_dotenv
from discord import Intents, Client, Message, Embed, Colour, Object, Activity, ActivityType

load_dotenv()
image_re = re.compile(r"^https://(?:cdn|media)\.discordapp\.(?:net|com)/attachments/\d+/\d+/.+\.(?:png|jpe?g|gif|webp)$", re.IGNORECASE)
timeshtamp_re = re.compile(r"<\w:(\d+):\w> ")

class MemePoster(Client):
    def __init__(self):
        intents = Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)

        self.queue_file = os.getenv("QUEUE_FILE")
        self.channel_id = int(os.getenv("DISCORD_CHANNEL_ID", "992565170633199706"))
        self.planning_days = int(os.getenv("PLANNING_FOR_DAYS", 3))
        self.is_running = False

    async def on_ready(self):
        if self.is_running:
            print("Already running")
            return
        self.is_running = True

        print(f'Logged in as {self.user}')
        link_queue = deque()

        with open(self.queue_file) as f:
            for line in f:
                line = line.strip()
                print(line)
                link_queue.append(line)

        planned_end = datetime.utcnow() + timedelta(days=self.planning_days)

        while link_queue:
            minutes_wait = max((planned_end - datetime.utcnow()).total_seconds() // 60 // len(link_queue), 1)

            try:
                await self.prepare_message(link_queue[0], len(link_queue))
            except Exception as e:
                print(f"Error sending message: {e}")
                await asyncio.sleep(5)
                continue

            link_queue.popleft()
            #with open(self.queue_file, "w") as f:
            #    f.writelines(f"{line}\n" for line in link_queue)

            drift = (10 - datetime.utcnow().minute % 10) % 10
            sleep_until = datetime.utcnow() + timedelta(minutes=minutes_wait + drift)
            delta = (sleep_until - datetime.utcnow()).total_seconds()
            
            sleep_until_str = sleep_until.strftime('%d/%m/%Y %H:%M:%S')
            print(f"Sleeping for {int(delta)}s until {sleep_until_str}")
            await self.change_presence(activity=Activity(type=ActivityType.custom, name=f"Next post at {sleep_until_str}"))
            await asyncio.sleep(delta)

        os._exit(0)

    async def prepare_message(self, url, count):
        def is_image(url) -> bool:
            return image_re.match(url) is not None

        def get_timestamp(url) -> int:
            m = timeshtamp_re.search(url)
            return int(m.group(1)) if m else 0
            
        url_wo_timeshtamp = timeshtamp_re.sub("", url)
        channel = await self.fetch_channel(self.channel_id)

        if is_image(url_wo_timeshtamp):
            embed = Embed(colour=Colour.blue(), timestamp=datetime.utcfromtimestamp(get_timestamp(url)))
            embed.set_image(url=url_wo_timeshtamp)
            embed.set_footer(text="297 (ETA 3d 21h)")
            print(f"Sending embed: {embed}")
            await channel.send(embed=embed)
        else:
            print(f"Sending: {url}")
            await channel.send(content=f"||{count}|| {url}")


if __name__ == '__main__':
    print("Starting...")
    token = os.getenv("DISCORD_TOKEN")
    bot = MemePoster()
    bot.run(token)

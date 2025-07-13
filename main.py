import asyncio
import os
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from collections import deque
from dotenv import load_dotenv
from discord import Intents, Client, Embed, Colour, Activity, ActivityType, Status
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
import random, json

load_dotenv()
image_re = re.compile(r"^https://(?:cdn|media)\.discordapp\.(?:net|com)/attachments/\d+/\d+/.+\.(?:png|jpe?g|gif|webp)$", re.IGNORECASE)
timeshtamp_re = re.compile(r"<\w:(\d+):\w> ")
default_channel = "992565170633199706"

def save_to_json(data, filename="state.json"):
    with open(filename, "w") as f:
        json.dump(data, f, default=str) 

def load_from_json(filename="state.json"):
    try:
        with open(filename, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

operational_data = {
    'planned_end': datetime.utcnow().timestamp(),
    'link_count': 0,
    'dont_reset_date_on_added_links': False     # makes it possible to add links to the queue without dumping the end date (requires reloading the bot)
}

# Check that the list of values ​​has all the necessary fields (and filling in the default value if not)
data = load_from_json()
for item in operational_data:
    if item in data:
        operational_data[item] = data[item]

save_to_json(operational_data)

operational_data['planned_end'] = datetime.fromtimestamp(operational_data['planned_end'])

print(operational_data)

class MemePoster(Client):
    def __init__(self):
        intents = Intents.all()
        intents.message_content = True
        super().__init__(intents=intents)

        # To prevent re-start programm
        self.is_running = False
        self.tz = ZoneInfo("Europe/Moscow")

    async def message_cycle(self, created_at):
        global operational_data, default_channel

        queue_file = os.getenv("QUEUE_FILE")

        async def prepare_message(self, url, count):
            global operational_data
            channel_id = int(os.getenv("DISCORD_CHANNEL_ID", default_channel))

            def is_image(url) -> bool:
                return image_re.match(url) is not None

            def get_timestamp(url) -> int:
                m = timeshtamp_re.search(url)
                return int(m.group(1)) if m else 0

            url_wo_timeshtamp = timeshtamp_re.sub("", url)
            channel = await self.fetch_channel(channel_id)

            if is_image(url_wo_timeshtamp):
                diff = operational_data["planned_end"] - datetime.now()

                embed = Embed(colour=Colour.from_hsv(random.uniform(0, 1), 1, 0.6), timestamp=datetime.utcfromtimestamp(get_timestamp(url)))
                embed.set_image(url=url_wo_timeshtamp)
                embed.set_footer(text=f"{count} (ETA {diff.days}d {int(diff.seconds / 3600)}h)")
                print(f"Sending embed: {url_wo_timeshtamp}")
                await channel.send(embed=embed)
            else:
                print(f"Sending: {url}")
                await channel.send(content=f"||{count}|| {url}")

        link_queue = deque()

        with open(queue_file) as f:
            for line in f:
                line = line.strip()
                link_queue.append(line)

        if operational_data["link_count"] != len(link_queue):
            print(*link_queue, sep='\n')
            if not operational_data["dont_reset_date_on_added_links"]:
                print("Reset end date")

                planning_days = int(os.getenv("PLANNING_FOR_DAYS", 3))
                planned_end = datetime.utcnow() + timedelta(days=planning_days)
                print(f"Now end at {planned_end.strftime('%d/%m/%Y %H:%M:%S')}")

                operational_data["planned_end"] = planned_end.timestamp()
                operational_data["dont_reset_date_on_added_links"] = False
            operational_data["link_count"] = len(link_queue)

            save_to_json(operational_data)
            if planned_end:
                operational_data["planned_end"] = planned_end

        try:
            await prepare_message(self, link_queue[0], len(link_queue))
        except Exception as e:
            print(f"Error sending message: {e}")
            await asyncio.sleep(5)
            return

        link_queue.popleft()
        with open(queue_file, "w") as f:
            f.writelines(f"{line}\n" for line in link_queue)

        operational_data["link_count"] = len(link_queue)
        planned_end = operational_data["planned_end"]
        operational_data["planned_end"] = planned_end.timestamp()

        save_to_json(operational_data)

        operational_data["planned_end"] = planned_end

        await self.schedule_next_post()

    async def get_time_next_post(self, operational_data):
        curr_time = datetime.now(self.tz)

        minutes_wait = int(max(
                (operational_data["planned_end"].astimezone(self.tz) - curr_time).total_seconds() // 60 // operational_data["link_count"], 5
            ))
        drift = minutes_wait
        sleep_until = (curr_time + timedelta(minutes=drift)).replace(second=10)

        return sleep_until, minutes_wait, drift

    async def update_status(self):
        global operational_data

        next_run = self.scheduler.get_job("autoposting").next_run_time.strftime('%d/%m/%Y %H:%M:%S')

        await self.change_presence(status=Status.online,
            activity=Activity(type=ActivityType.playing,
                name=f"Next post at {next_run}; {operational_data['link_count']}"
            )
        )

    async def schedule_next_post(self, min_wtime = False):
        global operational_data

        curr_time = datetime.now(self.tz)
        if min_wtime:
            sleep_until = curr_time + timedelta(minutes=5)
        else:
            sleep_until, minutes_wait, drift = await self.get_time_next_post(operational_data)
            print(f"drift {drift}; minutes_wait {minutes_wait}; sleep_until {sleep_until}")

        job = self.scheduler.add_job(self.message_cycle, DateTrigger(run_date=sleep_until), id="autoposting", kwargs={"created_at": curr_time})
        next_run = job.next_run_time.strftime('%d/%m/%Y %H:%M:%S')

        print(f"Post planed on {next_run}")
        await self.update_status()

    async def on_message(self, message):
        global operational_data, default_channel
        
        if message.author == self.user:
            return
        
        if message.channel.id == int(os.getenv("DISCORD_CHANNEL_ID", default_channel)) and len(message.attachments) > 0:
            curr_time = datetime.now(timezone.utc)
            job = self.scheduler.get_job("autoposting")
            if job is None:
                print("shed not found")
                return
            else:
                old_job_time_diff = curr_time - job.kwargs.get("created_at")
            
            sleep_until, minutes_wait, drift = await self.get_time_next_post(operational_data)
            operational_data["planned_end"] = old_job_time_diff + operational_data["planned_end"]
            print(f"total end time has been shifted by {old_job_time_diff}; new end time {operational_data['planned_end'].astimezone(self.tz)}; new post time {sleep_until}; minutes_wait {minutes_wait}; drift {drift}")
            new_kwargs = dict(job.kwargs)
            new_kwargs["created_at"] = curr_time
            job.modify(next_run_time=sleep_until, kwargs=new_kwargs)

        await self.update_status()

    async def on_ready(self):
        if self.is_running:
            print("Already running")
            if self.scheduler.get_job("autoposting") is None:
                await self.schedule_next_post(True)
            await self.update_status()
            return
        self.is_running = True

        self.scheduler = AsyncIOScheduler(timezone=self.tz)
        self.scheduler.start()

        print(f'Logged in as {self.user}')

        await self.change_presence(status=Status.dnd, activity=Activity(type=ActivityType.playing, name=f"Startup..."))
        await self.schedule_next_post(True)
        

if __name__ == '__main__':
    print("Starting...")
    token = os.getenv("DISCORD_TOKEN")
    bot = MemePoster()
    bot.run(token)
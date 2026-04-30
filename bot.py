"""
YouTube → MP3 디스코드 봇 (Stage 4)

기능:
  !ytmp3 <URL>  - 단일 영상 수동 다운로드
  !batch        - 모든 플리 즉시 배치 실행 + 결과 알림
  (자동 알림)   - 작업 스케줄러 배치 완료 후 채널에 신규 곡 목록 전송은
                  run_batch_and_notify()를 downloader.py에서 직접 호출하는 방식으로도 사용 가능

환경변수 (.env):
  DISCORD_TOKEN        - 봇 토큰
  DISCORD_CHANNEL_ID   - 알림 채널 ID
"""

import asyncio
import concurrent.futures
import logging
import os
import sys
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

import downloader

load_dotenv(Path(__file__).parent / ".env")

CONFIG_PATH = Path(__file__).parent / "config.json"
logger = logging.getLogger(__name__)


def setup_logging():
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(fmt)
    logging.getLogger().setLevel(logging.INFO)
    logging.getLogger().addHandler(handler)


def get_channel_id() -> int | None:
    val = os.environ.get("DISCORD_CHANNEL_ID", "").strip()
    if not val:
        return None
    try:
        return int(val)
    except ValueError:
        logger.error("DISCORD_CHANNEL_ID가 올바른 정수가 아닙니다: %s", val)
        return None


def format_track_list(tracks: list) -> list[str]:
    """신규 곡 목록을 Discord 2000자 제한에 맞게 청크로 분할"""
    if not tracks:
        return []

    header = f"**신규 다운로드 {len(tracks)}곡**\n"
    chunks = []
    current = header

    for i, track in enumerate(tracks, 1):
        line = f"{i}. {track['title']}\n"
        if len(current) + len(line) > 1900:
            chunks.append(current)
            current = line
        else:
            current += line

    if current.strip():
        chunks.append(current)

    return chunks


class YtMp3Bot(commands.Bot):
    def __init__(self, config: dict):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.config = config
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        self.downloaded_ids: set = set()

    async def setup_hook(self):
        state_file = self.config["_state_file"]
        self.downloaded_ids = downloader.load_downloaded_ids(state_file)
        logger.info("상태 로드 완료: %d곡 기록됨", len(self.downloaded_ids))

        if self.config.get("discord", {}).get("bot_schedules_batch", False):
            self.bg_task = self.loop.create_task(self._internal_scheduler())

    async def on_ready(self):
        logger.info("봇 로그인 완료: %s (ID: %s)", self.user, self.user.id)
        logger.info("서버 수: %d", len(self.guilds))

    async def _internal_scheduler(self):
        """bot_schedules_batch=true 일 때만 활성화되는 내부 스케줄러"""
        await self.wait_until_ready()
        target_hour = self.config.get("discord", {}).get("batch_schedule_hour", 9)
        import datetime
        while not self.is_closed():
            now = datetime.datetime.now()
            next_run = now.replace(hour=target_hour, minute=0, second=0, microsecond=0)
            if next_run <= now:
                next_run += datetime.timedelta(days=1)
            wait_secs = (next_run - now).total_seconds()
            logger.info("내부 스케줄러: %d초 후 배치 실행 예정", int(wait_secs))
            await asyncio.sleep(wait_secs)
            await run_batch_and_notify(self)

    @commands.command(name="ytmp3")
    async def ytmp3_command(self, ctx: commands.Context, url: str):
        """단일 영상 다운로드: !ytmp3 <URL>"""
        await ctx.send(f"다운로드 중... `{url}`")
        loop = asyncio.get_event_loop()
        output_dir = self.config["_singles_folder"]
        try:
            result = await loop.run_in_executor(
                self.executor,
                downloader.download_single,
                url,
                output_dir,
                self.config,
                self.downloaded_ids,
            )
        except Exception as e:
            logger.error("!ytmp3 예외: %s", e)
            await ctx.send(f"오류가 발생했습니다: `{e}`")
            return

        if result:
            await ctx.send(f"완료: **{result['title']}**")
        else:
            await ctx.send("이미 다운로드됐거나 다운로드에 실패했습니다.")

    @ytmp3_command.error
    async def ytmp3_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("사용법: `!ytmp3 <유튜브 URL>`")
        else:
            logger.error("!ytmp3 커맨드 오류: %s", error)
            await ctx.send(f"오류: `{error}`")

    @commands.command(name="batch")
    async def batch_command(self, ctx: commands.Context):
        """모든 플리 즉시 배치 실행: !batch"""
        await ctx.send("플리 배치 실행 중... (완료 시 알림)")
        await run_batch_and_notify(self, reply_ctx=ctx)


async def post_new_songs(bot: YtMp3Bot, tracks: list):
    """신규 곡 목록을 알림 채널에 전송"""
    channel_id = get_channel_id()
    if not channel_id:
        logger.warning("DISCORD_CHANNEL_ID가 설정되지 않아 알림을 보내지 않습니다.")
        return

    channel = bot.get_channel(channel_id)
    if not channel:
        logger.error("채널 ID %s를 찾을 수 없습니다.", channel_id)
        return

    if not tracks:
        await channel.send("배치 완료: 신규 곡 없음")
        return

    chunks = format_track_list(tracks)
    for chunk in chunks:
        await channel.send(chunk)


async def run_batch_and_notify(bot: YtMp3Bot, reply_ctx: commands.Context | None = None):
    """배치 실행 후 Discord 채널에 결과 알림"""
    loop = asyncio.get_event_loop()
    try:
        new_tracks = await loop.run_in_executor(
            bot.executor,
            downloader.run_batch,
            bot.config,
        )
    except Exception as e:
        logger.error("배치 실행 오류: %s", e)
        if reply_ctx:
            await reply_ctx.send(f"배치 실행 중 오류 발생: `{e}`")
        return

    await post_new_songs(bot, new_tracks)

    if reply_ctx:
        if new_tracks:
            await reply_ctx.send(f"배치 완료! 신규 {len(new_tracks)}곡 다운로드. (채널 알림 확인)")
        else:
            await reply_ctx.send("배치 완료: 신규 곡 없음")


def main():
    setup_logging()

    token = os.environ.get("DISCORD_TOKEN", "").strip()
    if not token or token == "your_bot_token_here":
        logger.error(
            "DISCORD_TOKEN이 설정되지 않았습니다.\n"
            ".env 파일에 DISCORD_TOKEN=<봇 토큰>을 입력하세요."
        )
        sys.exit(1)

    config = downloader.load_config(CONFIG_PATH)
    bot = YtMp3Bot(config)
    bot.run(token)


if __name__ == "__main__":
    main()

"""Download manager for earnings call documents."""

import os
import asyncio
import aiohttp
from typing import List, Tuple
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, DownloadColumn

from config import config
from utils import EarningsCall
from analysis.quarter_verify import verify_and_correct


class Downloader:
    """Handles downloading of earnings call documents."""

    def __init__(self):
        self.timeout = aiohttp.ClientTimeout(total=config.request_timeout * 2)
        self.headers = {
            "User-Agent": config.user_agent,
            "Accept": "*/*",
        }

    async def download_file(
        self,
        session: aiohttp.ClientSession,
        call: EarningsCall,
        output_dir: str,
        progress: Progress,
        task_id: int
    ) -> Tuple[bool, str, EarningsCall]:
        """Download a single file, verifying quarter from PDF content."""
        filename = call.get_filename()
        filepath = os.path.join(output_dir, filename)

        # Skip if already exists
        if os.path.exists(filepath):
            progress.update(task_id, description=f"[yellow]Skipped (exists): {filename}")
            return True, filepath, call

        for attempt in range(config.max_retries):
            try:
                async with session.get(call.url, headers=self.headers) as resp:
                    if resp.status == 200:
                        content = await resp.read()
                        with open(filepath, "wb") as f:
                            f.write(content)

                        # Verify quarter from PDF content
                        corrected_call, was_corrected, was_verified = verify_and_correct(call, content)
                        if was_corrected:
                            new_filepath = os.path.join(output_dir, corrected_call.get_filename())
                            os.rename(filepath, new_filepath)
                            filepath = new_filepath
                            progress.update(task_id, description=f"[green]Downloaded (corrected): {corrected_call.get_filename()}")
                        elif not was_verified:
                            progress.update(task_id, description=f"[yellow]Downloaded (unverified): {filename}")
                        else:
                            progress.update(task_id, description=f"[green]Downloaded: {filename}")
                        return True, filepath, corrected_call
                    else:
                        if attempt == config.max_retries - 1:
                            progress.update(task_id, description=f"[red]Failed ({resp.status}): {filename}")
                            return False, "", call

            except Exception as e:
                if attempt == config.max_retries - 1:
                    progress.update(task_id, description=f"[red]Error: {filename} - {str(e)[:30]}")
                    return False, "", call
                await asyncio.sleep(config.retry_delay)

        return False, "", call

    async def download_all(
        self,
        calls: List[EarningsCall],
        output_dir: str
    ) -> List[Tuple[EarningsCall, bool, str]]:
        """Download all earnings call documents."""
        os.makedirs(output_dir, exist_ok=True)
        results = []

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                transient=False
            ) as progress:
                tasks = []
                for call in calls:
                    task_id = progress.add_task(f"Downloading {call.get_filename()}...", total=1)
                    task = self.download_file(session, call, output_dir, progress, task_id)
                    tasks.append((call, task, task_id))

                for call, task, task_id in tasks:
                    success, path, corrected_call = await task
                    progress.update(task_id, completed=1)
                    results.append((corrected_call, success, path))

        return results

    def download_sync(
        self,
        calls: List[EarningsCall],
        output_dir: str
    ) -> List[Tuple[EarningsCall, bool, str]]:
        """Synchronous wrapper for download_all."""
        return asyncio.run(self.download_all(calls, output_dir))

"""Configuration for Earnings Call Downloader."""

import os
from dataclasses import dataclass, field
from typing import List

@dataclass
class Config:
    """Configuration settings."""
    output_dir: str = "./downloads"
    quarters_per_company: int = 5

    # Document types to download
    include_transcripts: bool = True
    include_presentations: bool = True
    include_press_releases: bool = True

    # Request settings
    request_timeout: int = 30
    max_retries: int = 3
    retry_delay: float = 1.0

    # User agent for requests
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    # Sources to try (in order)
    sources: List[str] = field(default_factory=lambda: ["screener"])

    def get_output_path(self, company: str) -> str:
        """Get output directory for a company."""
        safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in company)
        safe_name = safe_name.strip().replace(" ", "_")
        path = os.path.join(self.output_dir, safe_name)
        os.makedirs(path, exist_ok=True)
        return path


# Global config instance
config = Config()

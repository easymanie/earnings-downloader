#!/usr/bin/env python3
"""
Earnings Document Downloader - CLI Interface
Interactive tool to download earnings documents for companies worldwide.
"""

import sys
from typing import List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table

from config import config
from core.services import EarningsService
from core.models import EarningsCall
from sources.base import Region
from downloader import Downloader


console = Console()
service = EarningsService()


def print_banner():
    """Print welcome banner."""
    regions = service.get_available_regions()
    region_names = ", ".join(r["name"] for r in regions) if regions else "India"

    console.print(Panel.fit(
        "[bold blue]Earnings Document Downloader[/bold blue]\n"
        f"[dim]Transcripts, Presentations & Press Releases ({region_names})[/dim]",
        border_style="blue"
    ))
    console.print()


def get_region() -> Optional[Region]:
    """Get region selection from user."""
    regions = service.get_available_regions()

    if len(regions) <= 1:
        # Only one region available, use it automatically
        return Region(regions[0]["id"]) if regions else Region.INDIA

    console.print("[bold]Select region:[/bold]")
    for i, r in enumerate(regions, 1):
        console.print(f"  [cyan][{i}][/cyan] {r['name']} ({r['fiscal_year']} fiscal year)")
    console.print(f"  [cyan][{len(regions) + 1}][/cyan] Search all regions")
    console.print()

    choices = [str(i) for i in range(1, len(regions) + 2)]
    choice = Prompt.ask("[cyan]Region[/cyan]", choices=choices, default="1")

    idx = int(choice) - 1
    if idx < len(regions):
        return Region(regions[idx]["id"])
    return None  # Search all regions


def get_companies() -> List[str]:
    """Get company names from user."""
    console.print("[bold]Enter company name(s)[/bold] [dim](comma-separated for multiple)[/dim]")
    raw = Prompt.ask("[cyan]Companies[/cyan]")
    companies = [c.strip() for c in raw.split(",") if c.strip()]
    return companies


def show_menu() -> str:
    """Show options menu and get choice."""
    console.print()
    console.print("[bold]Options:[/bold]")
    console.print(f"  [cyan][1][/cyan] Download all documents [dim](transcripts + presentations + press releases)[/dim]")
    console.print(f"  [cyan][2][/cyan] Download transcripts only")
    console.print(f"  [cyan][3][/cyan] Change output directory [dim](current: {config.output_dir})[/dim]")
    console.print(f"  [cyan][4][/cyan] Change quarters count [dim](current: {config.quarters_per_company})[/dim]")
    console.print(f"  [cyan][5][/cyan] Exit")
    console.print()

    return Prompt.ask("[cyan]Choice[/cyan]", choices=["1", "2", "3", "4", "5"], default="1")


def change_output_dir():
    """Change the output directory."""
    new_dir = Prompt.ask(
        "[cyan]New output directory[/cyan]",
        default=config.output_dir
    )
    config.output_dir = new_dir
    console.print(f"[green]Output directory set to: {config.output_dir}[/green]")


def change_quarters_count():
    """Change number of quarters to download."""
    count = Prompt.ask(
        "[cyan]Number of quarters per company[/cyan]",
        default=str(config.quarters_per_company)
    )
    try:
        config.quarters_per_company = int(count)
        console.print(f"[green]Will download {config.quarters_per_company} quarters per company[/green]")
    except ValueError:
        console.print("[red]Invalid number, keeping current setting[/red]")


def search_and_download(
    companies: List[str],
    region: Optional[Region] = None,
    include_transcripts: bool = True,
    include_presentations: bool = True,
    include_press_releases: bool = True,
    include_balance_sheets: bool = True,
    include_pnl: bool = True,
    include_cash_flow: bool = True,
    include_annual_reports: bool = True
):
    """Search for companies and download their earnings documents."""
    downloader = Downloader()
    all_calls: List[EarningsCall] = []

    console.print()
    console.print("[bold]Searching for earnings documents...[/bold]")

    for company in companies:
        console.print(f"\n[cyan]Searching:[/cyan] {company}")

        calls = service.get_earnings_documents(
            company,
            region=region,
            count=config.quarters_per_company,
            include_transcripts=include_transcripts,
            include_presentations=include_presentations,
            include_press_releases=include_press_releases,
            include_balance_sheets=include_balance_sheets,
            include_pnl=include_pnl,
            include_cash_flow=include_cash_flow,
            include_annual_reports=include_annual_reports
        )

        if calls:
            console.print(f"  [green]Found {len(calls)} document(s)[/green]")
            all_calls.extend(calls)
        else:
            console.print(f"  [yellow]No documents found[/yellow]")

    if not all_calls:
        console.print("\n[red]No documents found for any company.[/red]")
        return

    # Show what will be downloaded
    console.print()
    table = Table(title="Documents to Download")
    table.add_column("Company", style="cyan")
    table.add_column("Quarter")
    table.add_column("Type")
    table.add_column("Source", style="dim")

    for call in all_calls:
        table.add_row(
            call.company[:30],
            f"{call.quarter} {call.year}",
            call.doc_type,
            call.source
        )

    console.print(table)

    # Confirm download
    if not Confirm.ask(f"\n[cyan]Download {len(all_calls)} file(s)?[/cyan]", default=True):
        console.print("[yellow]Download cancelled.[/yellow]")
        return

    # Download
    console.print()
    results = []
    for company in set(c.company for c in all_calls):
        company_calls = [c for c in all_calls if c.company == company]
        output_dir = config.get_output_path(company)
        console.print(f"[bold]Downloading to: {output_dir}[/bold]")
        results.extend(downloader.download_sync(company_calls, output_dir))

    # Summary
    success_count = sum(1 for _, success, _ in results if success)
    console.print()
    console.print(Panel(
        f"[green]Downloaded: {success_count}[/green] | "
        f"[red]Failed: {len(results) - success_count}[/red]",
        title="Summary",
        border_style="green" if success_count == len(results) else "yellow"
    ))


def main():
    """Main interactive loop."""
    print_banner()

    while True:
        # Get region if multiple available
        region = get_region()

        companies = get_companies()
        if not companies:
            console.print("[yellow]No companies entered. Please try again.[/yellow]")
            continue

        choice = show_menu()

        if choice == "1":
            search_and_download(
                companies,
                region=region,
                include_transcripts=True,
                include_presentations=True,
                include_press_releases=True
            )
        elif choice == "2":
            search_and_download(
                companies,
                region=region,
                include_transcripts=True,
                include_presentations=False,
                include_press_releases=False
            )
        elif choice == "3":
            change_output_dir()
            continue
        elif choice == "4":
            change_quarters_count()
            continue
        elif choice == "5":
            console.print("[dim]Goodbye![/dim]")
            sys.exit(0)

        console.print()
        if not Confirm.ask("[cyan]Download more?[/cyan]", default=True):
            console.print("[dim]Goodbye![/dim]")
            break


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Earnings Call Transcript Downloader
Interactive tool to download earnings documents for Indian companies.
"""

import sys
from typing import List

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table

from config import config
from sources import ScreenerSource, CompanyIRSource
from downloader import Downloader
from utils import EarningsCall, deduplicate_calls


console = Console()


def print_banner():
    """Print welcome banner."""
    console.print(Panel.fit(
        "[bold blue]Earnings Document Downloader[/bold blue]\n"
        "[dim]Transcripts, Presentations & Press Releases for Indian companies[/dim]",
        border_style="blue"
    ))
    console.print()


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
    include_transcripts: bool = True,
    include_presentations: bool = True,
    include_press_releases: bool = True
):
    """Search for companies and download their earnings documents."""
    ir_source = CompanyIRSource()
    screener_source = ScreenerSource()
    downloader = Downloader()
    all_calls: List[EarningsCall] = []

    console.print()
    console.print("[bold]Searching for earnings documents...[/bold]")

    for company in companies:
        console.print(f"\n[cyan]Searching:[/cyan] {company}")

        # Try company IR website first
        calls = ir_source.get_earnings_calls(
            company,
            count=config.quarters_per_company,
            include_transcripts=include_transcripts,
            include_presentations=include_presentations,
            include_press_releases=include_press_releases
        )

        # Fall back to Screener.in if not enough documents found
        if len(calls) < config.quarters_per_company:
            if calls:
                console.print(f"  [dim]Found {len(calls)} on IR site, checking Screener.in for more...[/dim]")
            screener_calls = screener_source.get_earnings_calls(
                company,
                count=config.quarters_per_company,
                include_transcripts=include_transcripts,
                include_presentations=include_presentations,
                include_press_releases=include_press_releases
            )
            calls.extend(screener_calls)

        if calls:
            console.print(f"  [green]Found {len(calls)} document(s)[/green]")
            all_calls.extend(calls)
        else:
            console.print(f"  [yellow]No documents found[/yellow]")

    if not all_calls:
        console.print("\n[red]No documents found for any company.[/red]")
        return

    # Deduplicate
    all_calls = deduplicate_calls(all_calls)

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
        companies = get_companies()
        if not companies:
            console.print("[yellow]No companies entered. Please try again.[/yellow]")
            continue

        choice = show_menu()

        if choice == "1":
            # Download all document types
            search_and_download(
                companies,
                include_transcripts=True,
                include_presentations=True,
                include_press_releases=True
            )
        elif choice == "2":
            # Transcripts only
            search_and_download(
                companies,
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

        # Ask if user wants to continue
        console.print()
        if not Confirm.ask("[cyan]Download more?[/cyan]", default=True):
            console.print("[dim]Goodbye![/dim]")
            break


if __name__ == "__main__":
    main()

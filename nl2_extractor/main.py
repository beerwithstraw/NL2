"""
CLI entry point for the NL2 (Profit and Loss) Extractor.

For config-driven path-based extraction, use pipeline.py instead:
  python3 pipeline.py
"""

import sys
import logging
from pathlib import Path

import click
from rich.console import Console

from config.settings import DEFAULT_INPUT_DIR, DEFAULT_OUTPUT_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-5s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)

console = Console()


@click.group()
def cli():
    """NL2 Profit and Loss Account Extractor CLI."""
    pass


@cli.command()
@click.option("--input", "-i", "input_dir", default=DEFAULT_INPUT_DIR,
              help="Directory containing source PDFs", type=click.Path(exists=True))
@click.option("--manifest", "-m", "manifest_csv", default="outputs/manifest.csv",
              help="Path to output manifest CSV", type=click.Path())
def scan(input_dir, manifest_csv):
    """Scan PDFs and generate a manifest CSV for human review."""
    from output.manifest import generate_manifest
    console.print(f"[bold blue]Scanning PDFs in:[/bold blue] {input_dir}")
    try:
        count = generate_manifest(input_dir, manifest_csv)
        console.print(f"\n[bold green]Scan complete![/bold green] Processed {count} files.")
        console.print(f"Manifest written to: [bold]{manifest_csv}[/bold]")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        sys.exit(1)


@cli.command()
@click.option("--input", "-i", "input_dir", default=DEFAULT_INPUT_DIR,
              help="Directory containing source PDFs", type=click.Path(exists=True))
@click.option("--manifest", "-m", "manifest_csv", default="outputs/manifest.csv",
              help="Path to input manifest CSV", type=click.Path())
@click.option("--output", "-o", "output_dir", default=DEFAULT_OUTPUT_DIR,
              help="Directory for output Excel", type=click.Path())
def extract(input_dir, manifest_csv, output_dir):
    """Run extraction using manifest CSV."""
    from output.manifest import read_manifest
    from extractor.parser import parse_pdf
    from output.excel_writer import save_workbook, write_validation_summary_sheet, write_validation_detail_sheet
    from validation.checks import run_validations, write_validation_report

    console.print("[bold blue]Starting NL2 extraction run...[/bold blue]")
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    rows = read_manifest(manifest_csv)
    to_process = [r for r in rows if r["action"] == "proceed"]

    if not to_process:
        console.print("[yellow]No files marked for 'proceed' in manifest.[/yellow]")
        return

    console.print(f"Found {len(to_process)} files to process.")
    extractions = []
    stats = {"files_processed": 0, "files_succeeded": 0, "files_failed": 0}

    for row in to_process:
        pdf_path = Path(input_dir) / row["filename"]
        if not pdf_path.exists():
            console.print(f"[red]File not found: {row['filename']}[/red]")
            stats["files_failed"] += 1
            continue
        try:
            stats["files_processed"] += 1
            ext = parse_pdf(str(pdf_path), row["detected_company"],
                            row["detected_quarter"], row["detected_year"])
            extractions.append(ext)
            stats["files_succeeded"] += 1
            console.print(f"  [green]\u2713[/green] {row['filename']}")
        except Exception as e:
            console.print(f"  [red]\u2717[/red] {row['filename']}: {e}")
            stats["files_failed"] += 1

    if not extractions:
        console.print("[bold red]No data successfully extracted.[/bold red]")
        return

    val_results = run_validations(extractions)
    report_path = output_path / "validation_report.csv"
    write_validation_report(val_results, str(report_path))
    excel_path = output_path / "NL2_Master.xlsx"
    save_workbook(extractions, str(excel_path), stats=stats)
    write_validation_summary_sheet(str(report_path), str(excel_path))
    write_validation_detail_sheet(str(report_path), str(excel_path))
    console.print(f"\n[bold green]Done![/bold green] Excel: [bold]{excel_path}[/bold]")


if __name__ == "__main__":
    cli()

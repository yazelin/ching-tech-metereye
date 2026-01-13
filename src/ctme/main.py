"""MeterEye multi-camera monitoring with 7-segment recognition."""

import argparse
import sys
from pathlib import Path


def cmd_migrate(args: argparse.Namespace) -> int:
    """Migrate legacy JSON config to YAML format."""
    from ctme.config_yaml import YAMLConfig, ConfigError

    config_path = Path(args.config) if args.config else None
    yaml_config = YAMLConfig(config_path)

    json_path = Path(args.json) if args.json else yaml_config.legacy_config_path

    try:
        yaml_config.migrate_from_json(json_path)
        print("Migration completed successfully!")
        return 0
    except ConfigError as e:
        print(f"Migration failed: {e}")
        return 1


def cmd_run(args: argparse.Namespace) -> int:
    """Run the multi-camera monitoring system."""
    from ctme.runner import run_server

    config_path = Path(args.config) if args.config else None
    return run_server(config_path)


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="MeterEye multi-camera monitoring system with 7-segment recognition",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run monitoring (multi-camera, from config)
  ctme
  ctme --config /path/to/config.yaml

  # Migrate legacy config
  ctme migrate
  ctme migrate --json /path/to/legacy.json

Web Configuration:
  After starting, open http://localhost:8000 in your browser.
  - Dashboard: View all camera streams and meter readings
  - Settings: Configure cameras and meters via /config.html
        """,
    )

    # Global options
    parser.add_argument(
        "--config", "-c",
        type=str,
        help="Path to YAML config file (default: ~/.config/ctme/config.yaml)",
    )

    # Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # migrate command
    migrate_parser = subparsers.add_parser(
        "migrate",
        help="Migrate legacy JSON config to YAML format",
    )
    migrate_parser.add_argument(
        "--json",
        type=str,
        help="Path to legacy JSON config file",
    )

    args = parser.parse_args()

    # Handle subcommands
    if args.command == "migrate":
        sys.exit(cmd_migrate(args))
    else:
        # Default: run the monitoring system
        sys.exit(cmd_run(args))


if __name__ == "__main__":
    main()

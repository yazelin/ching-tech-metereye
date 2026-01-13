#!/bin/bash
#
# MeterEye Development Runner
# Quick way to run MeterEye for development/testing
#
set -e

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=== MeterEye Development Runner ===${NC}"
echo

# Load .env if exists
if [[ -f ".env" ]]; then
    echo -e "${GREEN}Loading .env file...${NC}"
    set -a
    source .env
    set +a
fi

# Check for uv (preferred) or virtual environment
if command -v uv &> /dev/null; then
    echo -e "${GREEN}Using uv run (auto-manages dependencies)${NC}"
    UV_MODE=1
elif [[ -d ".venv" ]]; then
    echo -e "${GREEN}Using virtual environment: .venv${NC}"
    source .venv/bin/activate
else
    echo -e "${RED}No uv or .venv found!${NC}"
    echo "Please install uv: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# Check for config file
CONFIG_FILE="${CONFIG_FILE:-$PROJECT_DIR/config.example.yaml}"
USER_CONFIG="$HOME/.config/ctme/config.yaml"

if [[ -f "$USER_CONFIG" ]]; then
    CONFIG_FILE="$USER_CONFIG"
    echo -e "${GREEN}Using config: $CONFIG_FILE${NC}"
elif [[ -f "$PROJECT_DIR/config.yaml" ]]; then
    CONFIG_FILE="$PROJECT_DIR/config.yaml"
    echo -e "${GREEN}Using config: $CONFIG_FILE${NC}"
elif [[ -f "$PROJECT_DIR/config.example.yaml" ]]; then
    echo -e "${YELLOW}Using example config: $CONFIG_FILE${NC}"
    echo -e "${YELLOW}Tip: Copy to config.yaml and customize for your cameras${NC}"
else
    echo -e "${RED}No config file found!${NC}"
    echo "Please create config.yaml or set CONFIG_FILE environment variable"
    exit 1
fi

echo

# Determine mode
case "${1:-run}" in
    help|--help|-h)
        echo "Usage: $0 [command] [options]"
        echo
        echo "Commands:"
        echo "  (default)        Run MeterEye (multi-camera, API server)"
        echo "  migrate          Migrate legacy JSON config to YAML"
        echo "  help             Show this help message"
        echo
        echo "Examples:"
        echo "  $0                                    # Run with default/detected config"
        echo "  $0 --config ./my-config.yaml          # With custom config"
        echo "  $0 migrate                            # Migrate legacy config"
        echo
        echo "Environment variables:"
        echo "  CONFIG_FILE      Path to config file"
        echo "  CAM01_RTSP_URL   Camera URL (referenced in config.yaml)"
        echo
        echo "Web interface:"
        echo "  Dashboard:       http://localhost:8000/"
        echo "  Settings:        http://localhost:8000/config.html"
        echo "  API Docs:        http://localhost:8000/docs"
        ;;
    migrate)
        shift
        echo -e "${GREEN}Running config migration...${NC}"
        if [[ -n "$UV_MODE" ]]; then
            exec uv run --extra all ctme migrate "$@"
        else
            exec python3 -m ctme.main migrate "$@"
        fi
        ;;
    *)
        # Default: run MeterEye
        # Skip 'run' argument if provided
        if [[ "${1:-}" == "run" ]]; then
            shift
        fi
        echo -e "${GREEN}Starting MeterEye...${NC}"
        echo -e "Dashboard: ${BLUE}http://localhost:8000/${NC}"
        echo -e "Settings:  ${BLUE}http://localhost:8000/config.html${NC}"
        echo -e "API Docs:  ${BLUE}http://localhost:8000/docs${NC}"
        echo
        if [[ -n "$UV_MODE" ]]; then
            exec uv run --extra all ctme --config "$CONFIG_FILE" "$@"
        else
            exec python3 -m ctme.main --config "$CONFIG_FILE" "$@"
        fi
        ;;
esac

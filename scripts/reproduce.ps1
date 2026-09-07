$ErrorActionPreference = "Stop"

uv sync --extra dev --frozen
uv run scene-grammar build-open-images-cases `
  --output results/real_cases --all --verify-determinism --overwrite
uv run scene-grammar phase2-acceptance `
  --cases inputs/real_cases `
  --results results/real_cases `
  --output results/phase2_acceptance `
  --verify-determinism --overwrite
uv run scene-grammar evaluate `
  --output results/evaluation --verify-determinism --overwrite

Write-Host "Rebuild complete. Review canonical changes with: git diff -- results"

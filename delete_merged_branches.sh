#!/usr/bin/env bash
# Delete all feature branches now consolidated into master.
# Run locally with push rights to origin (adauzat90/Woodworking_AI).
# Optional but recommended first: set "master" as the repo default branch
#   on GitHub (Settings > Branches) so the old default can be removed.
set -euo pipefail
git fetch origin --prune
git checkout master

git push origin --delete claude/ai-agent-dsl-review-ars42w
git push origin --delete claude/ai-furniture-design-app-wn00nx
git push origin --delete claude/app-tech-debt-audit-vu56yw
git push origin --delete claude/branch-cleanup-merge-6v6a20
git push origin --delete claude/codename-tech-debt-audit-g4ubiw
git push origin --delete claude/dsl-design-ai-agents-x3up1f
git push origin --delete claude/furniture-lumber-cuts-ui-aisf3w
git push origin --delete claude/integration
git push origin --delete claude/sub-assemblies-dsl-k8de3f
git push origin --delete claude/tech-debt-audit-r4y4f4
git push origin --delete claude/woodworker-critic-joinery
git push origin --delete claude/woodworker-dxf-joinery
git push origin --delete claude/woodworker-geometry-machining
git push origin --delete claude/woodworker-kitchen-appliances
git push origin --delete claude/woodworker-kitchen-runs
git push origin --delete claude/woodworker-project-machining
git push origin --delete claude/woodworker-project-review-2upg7t
git push origin --delete claude/woodworker-purchasable-reality
git push origin --delete claude/woodworker-purchasing
git push origin --delete claude/woodworker-shop-workflow
git push origin --delete claude/woodworker-step-joinery
git push origin --delete claude/woodworking-app-review-lcab59
git push origin --delete claude/woodworking-app-review-sa7auu
git push origin --delete claude/woodworking-compiler-validation-h9ymgm
git push origin --delete claude/ws-cutplan
git push origin --delete claude/ws-exports
git push origin --delete claude/ws-finishing
git push origin --delete claude/ws-furniture
git push origin --delete claude/ws-planning
git push origin --delete claude/ws-species

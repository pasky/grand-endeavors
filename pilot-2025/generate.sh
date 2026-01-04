#!/bin/sh

# (no uncommitted changes in git worktree!)

for section in health climate fusion rockets robots-hardware robots-software; do
	echo "Execute pilot-2025/RECIPE.prose for $section" | npx --yes @sourcegraph/amp@latest
	git commit -a -m"pilot-2025: +$section"
	echo "Execute pilot-2025/RECIPE.prose for $section (ignore existing output)" | npx --yes @sourcegraph/amp@latest
	echo "Run \`git diff\`, verify any conflicting factual claims in a subagent, then evaluate pros/cons of each version, and then update the file with best of both worlds" | npx --yes @sourcegraph/amp@latest
	git commit -a -m"pilot-2025: $section rewrite and merge two versions"
done

echo "Read all the detailed updates on endeavors in pilot-2025/*.md and based on them create a fairly brief pilot-2025/README.md following endeavor structure from /README.md that contains intro to our newsletter's year round-up (friendly to first time readers too), executive summary of all the endeavors and links to individual files with detailed updates" | npx --yes @sourcegraph/amp@latest
git commit -a -m"pilot-2025: +README"

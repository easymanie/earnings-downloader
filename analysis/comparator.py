"""Quarter-over-quarter and year-over-year comparison logic."""

from typing import List, Optional, Tuple

from core.models import (
    CompanyAnalysis, FinancialMetric,
    MaterialChange, QuarterComparison,
)


class QuarterComparator:
    """Computes QoQ and YoY comparisons from stored analysis data."""

    def __init__(self, material_threshold: float = 10.0, notable_threshold: float = 5.0):
        self.material_threshold = material_threshold
        self.notable_threshold = notable_threshold

    def compare(
        self,
        current: CompanyAnalysis,
        previous: CompanyAnalysis,
        comparison_type: str,
    ) -> QuarterComparison:
        """Compare two quarters and flag material changes."""
        material_changes = self._compare_metrics(current.metrics, previous.metrics)
        new_themes = [t for t in current.themes if not self._theme_matches(t, previous.themes)]
        dropped_themes = [t for t in previous.themes if not self._theme_matches(t, current.themes)]

        summary = self._generate_summary(
            current, previous, material_changes, new_themes, dropped_themes, comparison_type
        )

        return QuarterComparison(
            company=current.company,
            current_quarter=f"{current.quarter} {current.year}",
            previous_quarter=f"{previous.quarter} {previous.year}",
            comparison_type=comparison_type,
            material_changes=material_changes,
            new_themes=new_themes,
            dropped_themes=dropped_themes,
            summary=summary,
        )

    def _compare_metrics(
        self,
        current_metrics: List[FinancialMetric],
        previous_metrics: List[FinancialMetric],
    ) -> List[MaterialChange]:
        changes = []
        prev_by_name = {m.name.lower().strip(): m for m in previous_metrics}

        for curr in current_metrics:
            prev = prev_by_name.get(curr.name.lower().strip())
            if not prev or curr.value is None or prev.value is None:
                continue
            if prev.value == 0:
                continue

            change_pct = ((curr.value - prev.value) / abs(prev.value)) * 100

            if abs(change_pct) >= self.notable_threshold:
                significance = "material" if abs(change_pct) >= self.material_threshold else "notable"

                # For cost-like metrics, declining is improvement
                cost_keywords = {"cost", "expense", "attrition", "debt", "npa"}
                is_cost = any(kw in curr.name.lower() for kw in cost_keywords)
                if is_cost:
                    direction = "improved" if change_pct < 0 else "declined"
                else:
                    direction = "improved" if change_pct > 0 else "declined"

                changes.append(MaterialChange(
                    metric_name=curr.name,
                    current_value=curr.value,
                    previous_value=prev.value,
                    change_pct=round(change_pct, 1),
                    direction=direction,
                    significance=significance,
                    context=f"{curr.name}: {prev.value:,.1f} -> {curr.value:,.1f} ({change_pct:+.1f}%)",
                ))

        return sorted(changes, key=lambda c: abs(c.change_pct or 0), reverse=True)

    def _theme_matches(self, theme: str, theme_list: List[str]) -> bool:
        """Check if a theme roughly matches any theme in the list."""
        theme_lower = theme.lower()
        for t in theme_list:
            t_lower = t.lower()
            # Exact or substantial overlap
            if theme_lower == t_lower:
                return True
            words = set(theme_lower.split())
            other_words = set(t_lower.split())
            overlap = words & other_words
            if len(overlap) >= min(2, len(words)):
                return True
        return False

    def _generate_summary(
        self,
        current: CompanyAnalysis,
        previous: CompanyAnalysis,
        changes: List[MaterialChange],
        new_themes: List[str],
        dropped_themes: List[str],
        comparison_type: str,
    ) -> str:
        parts = []
        comp_label = "QoQ" if comparison_type == "qoq" else "YoY"

        material = [c for c in changes if c.significance == "material"]
        if material:
            top = material[0]
            parts.append(
                f"{top.metric_name} changed {top.change_pct:+.1f}% {comp_label} "
                f"({top.previous_value:,.1f} -> {top.current_value:,.1f})."
            )

        if new_themes:
            parts.append(f"New themes: {', '.join(new_themes[:3])}.")
        if dropped_themes:
            parts.append(f"No longer mentioned: {', '.join(dropped_themes[:3])}.")

        if not parts:
            parts.append(f"No material changes detected {comp_label}.")

        return " ".join(parts)

    @staticmethod
    def get_previous_quarter(quarter: str, year: str, comp_type: str) -> Tuple[str, str]:
        """Calculate the previous quarter/year for comparison.

        Args:
            quarter: e.g. "Q3"
            year: e.g. "FY26"
            comp_type: "qoq" or "yoy"

        Returns:
            (previous_quarter, previous_year)
        """
        q_num = int(quarter[1])
        fy_num = int(year[2:])

        if comp_type == "yoy":
            return quarter, f"FY{fy_num - 1:02d}"

        # QoQ: Q1 wraps to Q4 of previous FY
        if q_num == 1:
            return "Q4", f"FY{fy_num - 1:02d}"
        else:
            return f"Q{q_num - 1}", year

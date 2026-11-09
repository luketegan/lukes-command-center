"""Markdown report for one orchestrated run."""

LABELS = {"supported": "Supported", "unsupported": "Unsupported", "unreachable": "Unreachable", "unverified": "Unverified"}


def _one_line(value) -> str:
    return " ".join(str(value or "").split())


def item_markdown(item: dict, stale: bool = False) -> str:
    lines = [f"### {_one_line(item.get('title'))}" + (" (stale)" if stale else ""), "", _one_line(item.get("summary")), ""]
    for claim in item.get("claims", []):
        label = LABELS.get(claim.get("label"), "Unverified")
        lines.append(f"- **{label}:** {_one_line(claim.get('text'))} — <{claim.get('source_url')}>")
        if claim.get("label") == "supported" and claim.get("evidence"):
            lines.append(f"  - Evidence: \"{_one_line(claim['evidence'])}\"")
    return "\n".join(lines)


def build_report(*, config, run_number, run_id, status, stale, new_items, still_items, dropped_items, rejected,
                 failed_workers, worker_status, used, total, completed_at) -> str:
    out = [
        f"# Festival Connectivity Tracker — orchestrated run {run_number}", "",
        f"**Completed:** {completed_at}  ",
        f"**Run ID:** {run_id}  ",
        f"**Status:** {status}  ",
        f"**Topic:** {_one_line(config['topic'])}  ",
        f"**Budget used:** {used['max_steps']}/{total['max_steps']} steps, "
        f"{used['max_fetches']}/{total['max_fetches']} fetches, {used['max_tokens']}/{total['max_tokens']} tokens",
    ]
    if failed_workers:
        out += ["", "## Failed workers", ""]
        out += [f"- **{name}:** {_one_line(why)}" for name, why in failed_workers.items()]
    notes = [f"- **{name.removesuffix('_note')}** returned partial work: {_one_line(text)}"
             for name, text in worker_status.items() if name.endswith("_note")]
    if notes:
        out += ["", "## Partial work", ""] + notes
    if stale:
        out += ["", "## No new results", "",
                "The researcher did not answer, so there are no new results. Last run's top K is shown below, marked stale."]
        out += ["", "## Last run's top K (stale)", ""]
        out += [item_markdown(item, stale=True) for item in still_items] or ["Nothing was saved from earlier runs."]
    else:
        for heading, items in (("New since last run", new_items), ("Still in top K", still_items),
                               ("Dropped from top K", dropped_items)):
            out += ["", f"## {heading}", ""]
            out += [item_markdown(item) for item in items] or ["None this run."]
        if rejected:
            out += ["", "## Left out: no claim survived verification", ""]
            out += [item_markdown(item) for item in rejected]
    out += ["", "## Labels", "",
            "Supported means the verifier fetched the page itself and its code found the evidence excerpt in it. "
            "Unverified means the verifier did not return a verdict for that claim.",
            "", "Web content in this report is untrusted data and was never followed as instructions."]
    return "\n".join(out) + "\n"

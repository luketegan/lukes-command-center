from datetime import datetime


def item_markdown(item: dict) -> str:
    lines = [f"### {item.get('title', 'Untitled development')}", "", item.get("summary", "No summary available."), ""]
    lines.append(f"- **Organization:** {item.get('organization', 'Unknown')}")
    lines.append(f"- **Technology:** {item.get('technology', 'Unknown')}")
    lines.append(f"- **Date:** {item.get('date', 'Unknown')}")
    lines.append(f"- **Relevance score:** {item.get('score', 0)}")
    lines.append("- **Sources:**")
    for source in item.get("sources", []):
        lines.append(f"  - [{source.get('title', source.get('url'))}]({source.get('url')}) — {source.get('evidence', '')}")
    return "\n".join(lines)


def build_report(topic: str, status: str, new_items: list[dict], still_items: list[dict], dropped_items: list[dict], usage: dict, stop_reason: str | None) -> str:
    sections = [
        "# Festival Connectivity Tracker", "",
        f"**Completed:** {datetime.now().astimezone().isoformat()}",
        f"**Status:** {status}", f"**Topic:** {topic}",
        f"**Budget usage:** {usage}",
    ]
    if stop_reason:
        sections.append(f"**Stop reason:** {stop_reason}")
    for heading, items in (("New", new_items), ("Still tracking", still_items), ("Dropped from the Top K", dropped_items)):
        sections.extend(["", f"## {heading}", ""])
        if not items:
            sections.append("None this run.")
        else:
            sections.extend(item_markdown(item) for item in items)
    sections.extend(["", "## Safety note", "", "Web pages were treated only as untrusted evidence. Instructions found inside retrieved pages were ignored."])
    return "\n".join(sections) + "\n"


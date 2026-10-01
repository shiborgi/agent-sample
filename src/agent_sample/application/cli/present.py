from agent_sample.domain.model import Review
from agent_sample.domain.ports import CapabilityCatalog


def format_plugins(catalog: CapabilityCatalog) -> str:
    defaults = {plugin.ref for plugin in catalog.select(()).plugins}
    lines = ["plugin\tversion\tsource\tstatus\tsha256"]
    for plugin in catalog.plugins():
        status = "enabled" if catalog.enabled(plugin) else "disabled"
        if plugin.ref in defaults:
            status += ",default"
        lines.append(
            f"{plugin.name}\t{plugin.version}\t{plugin.source}\t{status}\t{plugin.digest[:12]}"
        )
    lines.extend(_conflicts(catalog))
    return "\n".join(lines)


def format_plugin(catalog: CapabilityCatalog, name: str) -> str:
    plugin = catalog.select((name,)).plugins[-1]
    lines = [
        f"{plugin.ref} — {plugin.description}",
        f"author: {plugin.author or '-'}",
        f"source: {plugin.source}",
        f"sha256: {plugin.digest}",
        "skills:",
        *(f"  {skill.name}: {skill.description}" for skill in plugin.skills),
        "reviewers:",
        *(
            f"  {item.name}: {item.description} [tools: {', '.join(item.tools) or '-'}; "
            f"skills: {', '.join(item.skills) or '-'}; languages: "
            f"{', '.join(item.languages) or 'any'}; focus: {', '.join(item.focus) or 'any'}]"
            for item in plugin.reviewers
        ),
    ]
    if plugin.warnings:
        lines.append("warnings:")
        lines.extend(f"  {warning}" for warning in plugin.warnings)
    return "\n".join(lines)


def format_skills(catalog: CapabilityCatalog) -> str:
    lines = ["skill\tplugin\tversion\tsha256\tdescription"]
    for skill in catalog.select(()).skills:
        lines.append(
            f"{skill.name}\t{skill.plugin}\t{skill.version}\t{skill.digest[:12]}\t"
            f"{skill.description}"
        )
    lines.extend(_conflicts(catalog, kinds=("skill",)))
    return "\n".join(lines)


def _conflicts(
    catalog: CapabilityCatalog, kinds: tuple[str, ...] = ("plugin", "skill", "reviewer")
) -> list[str]:
    conflicts = [item for item in catalog.conflicts() if item.kind in kinds]
    if not conflicts:
        return []
    return [
        "conflicts:",
        *(
            f"  {item.kind} {item.name}: {item.winner} wins over {', '.join(item.shadowed)}"
            for item in conflicts
        ),
    ]


def format_comparison(rows: list[tuple[str, Review]]) -> str:
    lines = ["variant\tdecision\tfindings\tfailures"]
    for variant, review in rows:
        lines.append(
            f"{variant}\t{review.decision}\t{len(review.findings)}\t{len(review.trace.failures)}"
        )
    for variant, review in rows:
        lines.append(f"\n[{variant}] {review.summary}")
        lines.extend(
            f"  [{item.severity}/{item.category}] {item.location} — {item.description} "
            f"({item.origin.label})"
            for item in review.findings
        )
        lines.extend(f"  failure: {failure}" for failure in review.trace.failures)
    return "\n".join(lines)

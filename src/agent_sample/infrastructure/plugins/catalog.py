"""Catálogo de capacidades: carrega todas as fontes, valida contra o lock e aplica precedência."""

from dataclasses import dataclass, replace
from pathlib import Path

from agent_sample.domain.capabilities import LEAD_SKILL, CapabilitySet, Conflict, Plugin
from agent_sample.domain.model import CapabilityError
from agent_sample.infrastructure.plugins.format import load_plugin, version_key
from agent_sample.infrastructure.plugins.sources import (
    LockEntry,
    ResolvedSource,
    ReviewerConfig,
    SourceSpec,
    lock_location,
    read_lock,
    resolve,
    verify,
    write_lock,
)


@dataclass(frozen=True, slots=True)
class Loaded:
    precedence: int
    source: SourceSpec
    plugin: Plugin


class PluginCatalog:
    """Para cada nome de plugin, a fonte de maior precedência que o traz é a dona dele.

    As versões dessa fonte coexistem (padrão: a maior); o mesmo nome em fontes de menor
    precedência aparece como conflito, nunca some em silêncio.
    """

    def __init__(self, loaded: tuple[Loaded, ...], disabled: frozenset[str]) -> None:
        self._disabled = disabled
        owners: dict[str, Loaded] = {}
        for item in loaded:
            current = owners.get(item.plugin.name)
            if current is None or item.precedence > current.precedence:
                owners[item.plugin.name] = item
        self._visible = tuple(
            item
            for item in sorted(loaded, key=lambda entry: (entry.precedence, entry.plugin.name))
            if item.precedence == owners[item.plugin.name].precedence
        )
        self._conflicts = _plugin_conflicts(loaded, owners)
        missing = sorted(self._disabled - set(owners))
        if missing:
            raise CapabilityError(f"cannot disable unknown plugin(s): {', '.join(missing)}")
        self._default = self.select(())

    def plugins(self) -> tuple[Plugin, ...]:
        return tuple(item.plugin for item in self._visible)

    def enabled(self, plugin: Plugin) -> bool:
        return plugin.name not in self._disabled

    def conflicts(self) -> tuple[Conflict, ...]:
        return (*self._conflicts, *_capability_conflicts(self._default))

    def select(self, pins: tuple[str, ...], skills: tuple[str, ...] = ()) -> CapabilitySet:
        """Sem pins: todos os habilitados na maior versão. Com pins: só os escolhidos (e o dono
        da skill do revisor principal, se nenhum escolhido a trouxer)."""
        chosen: dict[str, Loaded] = {}
        if pins:
            for pin in pins:
                name, _, version = pin.partition("@")
                chosen[name] = self._pick(name, version or None)
        else:
            for name in dict.fromkeys(item.plugin.name for item in self._visible):
                if name not in self._disabled:
                    chosen[name] = self._pick(name, None)
        ordered = sorted(chosen.values(), key=lambda item: (item.precedence, item.plugin.name))
        plugins = [item.plugin for item in ordered]
        if not any(skill.name == LEAD_SKILL for plugin in plugins for skill in plugin.skills):
            plugins.insert(0, self._lead_provider())
        if skills:
            plugins = [_only_skills(plugin, skills) for plugin in plugins]
            known = {skill.name for plugin in plugins for skill in plugin.skills}
            unknown = [name for name in skills if name.rpartition(":")[2] not in known]
            if unknown:
                raise CapabilityError(f"unknown skill(s): {', '.join(unknown)}")
        return CapabilitySet(tuple(plugins))

    def _pick(self, name: str, version: str | None) -> Loaded:
        versions = [item for item in self._visible if item.plugin.name == name]
        if not versions:
            known = ", ".join(sorted({item.plugin.name for item in self._visible})) or "none"
            raise CapabilityError(f"plugin not found: {name} (available: {known})")
        if name in self._disabled:
            raise CapabilityError(f"plugin {name} is disabled by configuration")
        if version is None:
            return max(versions, key=lambda item: version_key(item.plugin.version))
        for item in versions:
            if item.plugin.version == version:
                return item
        available = ", ".join(item.plugin.version for item in versions)
        raise CapabilityError(f"plugin {name} has no version {version} (available: {available})")

    def _lead_provider(self) -> Plugin:
        for item in reversed(self._visible):
            if self.enabled(item.plugin) and any(s.name == LEAD_SKILL for s in item.plugin.skills):
                return self._pick(item.plugin.name, None).plugin
        raise CapabilityError(f"no enabled plugin provides the '{LEAD_SKILL}' skill")


def _only_skills(plugin: Plugin, names: tuple[str, ...]) -> Plugin:
    wanted = {name.rpartition(":")[2] for name in names} | {LEAD_SKILL}
    skills = tuple(skill for skill in plugin.skills if skill.name in wanted)
    reviewers = tuple(
        replace(reviewer, skills=tuple(s for s in reviewer.skills if s in wanted))
        for reviewer in plugin.reviewers
    )
    return replace(plugin, skills=skills, reviewers=reviewers)


def _plugin_conflicts(loaded: tuple[Loaded, ...], owners: dict[str, Loaded]) -> list[Conflict]:
    conflicts: list[Conflict] = []
    for name, owner in sorted(owners.items()):
        shadowed = sorted(
            {
                item.source.describe()
                for item in loaded
                if item.plugin.name == name and item.precedence != owner.precedence
            }
        )
        if shadowed:
            conflicts.append(Conflict("plugin", name, owner.source.describe(), tuple(shadowed)))
    return conflicts


def _capability_conflicts(capabilities: CapabilitySet) -> list[Conflict]:
    """Mesmo nome de skill ou revisor em plugins diferentes: o último (maior precedência) vence."""
    conflicts: list[Conflict] = []
    for kind, items in (
        ("skill", [(skill.name, skill.plugin) for skill in capabilities.skills]),
        ("reviewer", [(item.name, item.plugin) for item in capabilities.all_reviewers]),
    ):
        by_name: dict[str, list[str]] = {}
        for name, plugin in items:
            by_name.setdefault(name, []).append(plugin)
        for name, plugins in sorted(by_name.items()):
            if len(plugins) > 1:
                conflicts.append(Conflict(kind, name, plugins[-1], tuple(plugins[:-1])))
    return conflicts


def load_catalog(config: ReviewerConfig, reviewer_version: str, cache: Path) -> PluginCatalog:
    """Resolve e valida tudo na inicialização. Erro de conteúdo nunca aparece numa revisão."""
    locks: dict[Path, dict[str, LockEntry]] = {}
    loaded: list[Loaded] = []
    for precedence, spec in enumerate(config.sources):
        lock = locks.setdefault(spec.lock_path, read_lock(spec.lock_path))
        entry = lock.get(spec.name)
        source = resolve(spec, cache, entry.resolved if entry and spec.kind == "git" else None)
        plugins = _load(source, reviewer_version)
        verify(source, {plugin.ref: plugin.digest for plugin in plugins}, entry)
        loaded.extend(Loaded(precedence, spec, plugin) for plugin in plugins)
    return PluginCatalog(tuple(loaded), config.disabled)


def lock_sources(
    config: ReviewerConfig, reviewer_version: str, cache: Path, scopes: tuple[str, ...]
) -> list[str]:
    """Resolve de novo as fontes dos escopos pedidos e grava os locks. Devolve o que gravou."""
    written: dict[Path, dict[str, LockEntry]] = {}
    report: list[str] = []
    for spec in config.sources:
        if spec.scope not in scopes:
            continue
        source = resolve(spec, cache)
        plugins = {plugin.ref: plugin.digest for plugin in _load(source, reviewer_version)}
        entry = LockEntry(spec.kind, lock_location(spec), spec.ref, source.resolved, plugins)
        written.setdefault(spec.lock_path, {})[spec.name] = entry
        refs = ", ".join(sorted(plugins)) or "no plugins"
        report.append(f"{spec.describe()} -> {refs}")
    for path, entries in written.items():
        write_lock(path, entries)
        report.append(f"wrote {path}")
    return report


def _load(source: ResolvedSource, reviewer_version: str) -> list[Plugin]:
    # Pacotes Python carregam código inerente; diretórios e git são estritamente conteúdo.
    strict = source.spec.kind in ("dir", "git")
    plugins = [
        load_plugin(root, source.spec.name, reviewer_version, strict_executables=strict)
        for root in source.plugin_roots
    ]
    seen: set[str] = set()
    for plugin in plugins:
        if plugin.ref in seen:
            raise CapabilityError(f"{source.spec.describe()}: {plugin.ref} appears twice")
        seen.add(plugin.ref)
    return plugins

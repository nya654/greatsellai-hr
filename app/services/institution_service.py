from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Institution, InstitutionAlias
from app.services.normalization import normalized_key


REGISTRY_PATH = Path(__file__).resolve().parents[1] / "resources" / "985_211_institutions.json"
AI_RULEBOOK_PATH = Path(__file__).resolve().parents[1] / "resources" / "ai_985_211_rulebook.md"


class InstitutionRegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class RegistryInstitution:
    roster_id: str
    canonical_name: str
    is_985_211: bool
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class InstitutionRegistry:
    version: str
    institutions: tuple[RegistryInstitution, ...]


@lru_cache(maxsize=1)
def load_registry() -> InstitutionRegistry:
    raw = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    version = raw.get("registry_version")
    records = raw.get("institutions")
    if not isinstance(version, str) or not isinstance(records, list):
        raise InstitutionRegistryError("invalid_registry_shape")

    institutions: list[RegistryInstitution] = []
    alias_owners: dict[str, str] = {}
    for record in records:
        if not isinstance(record, dict):
            raise InstitutionRegistryError("invalid_registry_record")
        roster_id = record.get("roster_id")
        canonical_name = record.get("canonical_name")
        is_985_211 = record.get("is_985_211")
        aliases = record.get("aliases", [])
        if not isinstance(roster_id, str) or not isinstance(canonical_name, str):
            raise InstitutionRegistryError("invalid_registry_identity")
        if not isinstance(is_985_211, bool) or not isinstance(aliases, list):
            raise InstitutionRegistryError("invalid_registry_attributes")
        all_names = [canonical_name, *aliases]
        for name in all_names:
            key = normalized_key(name)
            if not key:
                raise InstitutionRegistryError("blank_registry_alias")
            previous_owner = alias_owners.setdefault(key, roster_id)
            if previous_owner != roster_id:
                raise InstitutionRegistryError("conflicting_registry_alias")
        institutions.append(
            RegistryInstitution(
                roster_id=roster_id,
                canonical_name=canonical_name,
                is_985_211=is_985_211,
                aliases=tuple(aliases),
            )
        )

    if len(institutions) != 112:
        raise InstitutionRegistryError("unexpected_211_institution_count")
    if sum(item.roster_id.startswith("cn-985-") for item in institutions) != 39:
        raise InstitutionRegistryError("unexpected_985_institution_count")
    if not all(item.is_985_211 for item in institutions):
        raise InstitutionRegistryError("registry_contains_non_211_record")
    return InstitutionRegistry(version=version, institutions=tuple(institutions))


@lru_cache(maxsize=1)
def build_985_211_ai_rulebook() -> str:
    """Render the exact versioned roster supplied to the extraction model."""

    template = AI_RULEBOOK_PATH.read_text(encoding="utf-8")
    registry = load_registry()
    roster_lines: list[str] = []
    for entry in registry.institutions:
        aliases = "、".join(entry.aliases) if entry.aliases else "无"
        roster_lines.append(
            f"- {entry.roster_id} | {entry.canonical_name} | {aliases}"
        )
    rendered = (
        template.replace("{{REGISTRY_VERSION}}", registry.version)
        .replace("{{ROSTER_ENTRIES}}", "\n".join(roster_lines))
    )
    if "{{REGISTRY_VERSION}}" in rendered or "{{ROSTER_ENTRIES}}" in rendered:
        raise InstitutionRegistryError("invalid_ai_rulebook_template")
    return rendered


def seed_institution_registry(session: Session) -> None:
    registry = load_registry()
    known_institutions = {
        item.roster_id: item
        for item in session.scalars(select(Institution)).all()
    }

    for entry in registry.institutions:
        institution = known_institutions.get(entry.roster_id)
        if institution is None:
            institution = Institution(
                roster_id=entry.roster_id,
                canonical_name=entry.canonical_name,
                canonical_key=normalized_key(entry.canonical_name),
                is_985_211=entry.is_985_211,
                registry_version=registry.version,
            )
            session.add(institution)
        else:
            institution.canonical_name = entry.canonical_name
            institution.canonical_key = normalized_key(entry.canonical_name)
            institution.is_985_211 = entry.is_985_211
            institution.registry_version = registry.version
    session.flush()

    institutions_by_roster = {
        item.roster_id: item
        for item in session.scalars(select(Institution)).all()
    }
    aliases_by_key = {
        item.alias_key: item
        for item in session.scalars(select(InstitutionAlias)).all()
    }
    for entry in registry.institutions:
        institution = institutions_by_roster[entry.roster_id]
        for name in (entry.canonical_name, *entry.aliases):
            alias_key = normalized_key(name)
            existing_alias = aliases_by_key.get(alias_key)
            if existing_alias is not None and existing_alias.institution_id != institution.id:
                raise InstitutionRegistryError("stored_registry_alias_conflict")
            if existing_alias is None:
                session.add(
                    InstitutionAlias(
                        alias_key=alias_key,
                        institution_id=institution.id,
                    )
                )


def is_institution_registry_seeded(session: Session) -> bool:
    """Return whether every current registry institution is available locally.

    This deliberately checks the registry version as well as the primary names.
    A web process must never silently classify schools against a stale or partial
    roster in production.
    """

    registry = load_registry()
    institutions = {
        item.roster_id: item
        for item in session.scalars(select(Institution)).all()
    }
    if len(institutions) < len(registry.institutions):
        return False
    for entry in registry.institutions:
        institution = institutions.get(entry.roster_id)
        if institution is None or institution.registry_version != registry.version:
            return False
        for name in (entry.canonical_name, *entry.aliases):
            alias = session.get(InstitutionAlias, normalized_key(name))
            if alias is None or alias.institution_id != institution.id:
                return False
    return True


def resolve_institution(session: Session, school_name_raw: str) -> Institution | None:
    key = normalized_key(school_name_raw)
    if not key:
        return None
    alias = session.get(InstitutionAlias, key)
    return alias.institution if alias is not None else None


def resolve_institution_by_roster_id(
    session: Session,
    roster_id: str | None,
) -> Institution | None:
    if not roster_id or not roster_id.strip():
        return None
    return session.scalar(
        select(Institution).where(Institution.roster_id == roster_id.strip())
    )

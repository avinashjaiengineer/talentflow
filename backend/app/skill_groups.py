"""Skill groups: the talent pool is organized by these, and sourcing searches the groups that
match the job title (a Backend Engineer job searches Backend Engineering, not Design).

The resume-parsing and sourcing agents choose groups from this fixed list, so groups stay
consistent across candidates and jobs. The keyword rules below are the offline fallback, and
they group existing candidates when the database is upgraded.
"""

import re

GROUPS: dict[str, tuple[str, ...]] = {
    "Backend Engineering": (
        "backend", "back-end", "back end", "server-side", "python", "java", "golang", "node.js", "nodejs", "django",
        "fastapi", "flask", "spring", "spring boot", "microservices", "rest api", "grpc", "postgresql", "mysql",
        "kafka", "redis", ".net", "c#", "ruby on rails", "php", "laravel", "api design",
    ),
    "Frontend Engineering": (
        "frontend", "front-end", "front end", "react", "angular", "vue", "next.js", "javascript", "typescript",
        "css", "html", "tailwind", "ui developer", "web developer",
    ),
    "Full-Stack Engineering": ("full-stack", "full stack", "fullstack", "mern", "mean stack"),
    "Mobile Engineering": ("android", "ios", "swift", "kotlin", "flutter", "react native", "mobile developer", "mobile app"),
    "Data Science & ML": (
        "machine learning", "data scientist", "data science", "deep learning", "pytorch", "tensorflow", "nlp", "llm",
        "ai engineer", "ml engineer", "computer vision", "scikit-learn", "generative ai", "rag", "embeddings",
    ),
    "Data Engineering & Analytics": (
        "data engineer", "data engineering", "spark", "airflow", "etl", "data warehouse", "snowflake", "dbt",
        "bigquery", "databricks", "data analyst", "analytics", "power bi", "tableau", "pandas",
    ),
    "DevOps & Cloud": (
        "devops", "sre", "site reliability", "kubernetes", "terraform", "aws", "azure", "gcp", "ci/cd", "docker",
        "cloud engineer", "platform engineer", "infrastructure", "ansible", "helm",
    ),
    "QA & Testing": ("qa", "quality assurance", "test automation", "selenium", "cypress", "sdet", "manual testing", "tester"),
    "Security": ("security engineer", "cybersecurity", "penetration testing", "appsec", "infosec", "siem", "soc analyst"),
    "Design (UI/UX)": (
        "designer", "figma", "ux", "ui/ux", "user research", "design system", "design systems", "prototyping",
        "usability", "interaction design",
    ),
    "Product & Project Management": (
        "product manager", "product management", "project manager", "program manager", "scrum master", "product owner",
    ),
    "Sales & Marketing": (
        "sales", "marketing", "seo", "business development", "account executive", "growth", "brand", "content marketing",
    ),
    "Finance & Accounting": ("accountant", "accounting", "finance", "financial analyst", "audit", "tally", "gst", "taxation"),
    "HR & Recruiting": ("recruiter", "recruiting", "talent acquisition", "human resources", "hr generalist", "payroll"),
    "Operations & Support": (
        "operations", "customer support", "customer success", "supply chain", "logistics", "technical support", "helpdesk",
    ),
    "Other": (),
}
NAMES: tuple[str, ...] = tuple(GROUPS)

# Jobs in one group often hire from a neighbouring one.
RELATED: dict[str, tuple[str, ...]] = {
    "Backend Engineering": ("Full-Stack Engineering",),
    "Frontend Engineering": ("Full-Stack Engineering",),
    "Full-Stack Engineering": ("Backend Engineering", "Frontend Engineering"),
    "Data Science & ML": ("Data Engineering & Analytics",),
    "Data Engineering & Analytics": ("Data Science & ML",),
}

_PATTERNS = {
    name: [re.compile(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])") for k in keywords] for name, keywords in GROUPS.items()
}


def clean(groups: list[str], *, limit: int = 3) -> list[str]:
    """Known group names only, de-duplicated, in order."""
    out = []
    for g in groups:
        if g in GROUPS and g not in out:
            out.append(g)
    return out[:limit]


def _score(weighted_texts: list[tuple[str, int]]) -> list[str]:
    scores: dict[str, int] = {}
    for text, weight in weighted_texts:
        lower = text.lower()
        for name, patterns in _PATTERNS.items():
            hits = sum(1 for p in patterns if p.search(lower))
            if hits:
                scores[name] = scores.get(name, 0) + hits * weight
    return [name for name, _ in sorted(scores.items(), key=lambda kv: -kv[1])]


def groups_for_candidate(headline: str | None, skills: list[str], titles: list[str] = ()) -> list[str]:
    """Offline rule: the headline and job titles say the most about a person's field."""
    ranked = _score([(headline or "", 3), (" | ".join(titles), 3), (" | ".join(skills), 1)])
    return ranked[:3] or ["Other"]


def groups_for_job(title: str, requirements: list[str] = ()) -> list[str]:
    """Offline rule: the job title decides; requirements break ties."""
    ranked = _score([(title, 5), (" | ".join(requirements), 1)])
    if not ranked:
        return ["Other"]
    primary = ranked[0]
    return clean([primary, *RELATED.get(primary, ())])
